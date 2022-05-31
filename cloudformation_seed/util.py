from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional, Union
from pathlib import Path
import types
import logging
import boto3
import re
import os
import yaml
import objectpath
from colorama import Fore, Style
import copy

log = logging.getLogger('stack-deployer')


class ColorFormatter(logging.Formatter):
    DIM_LEVELS_BELOW = logging.DEBUG
    YELLOW_LEVELS_ABOVE = logging.WARNING
    RED_LEVELS_ABOVE = logging.ERROR

    def format(self, record, *args, **kwargs):
        new_record = copy.copy(record)
        new_record.levelname = f'{Style.DIM}{new_record.levelname}{Style.RESET_ALL}'

        if new_record.levelno <= self.__class__.DIM_LEVELS_BELOW:
            new_record.msg = f'{Style.DIM}{new_record.msg}'
        elif self.__class__.YELLOW_LEVELS_ABOVE <= new_record.levelno < self.__class__.RED_LEVELS_ABOVE:
            new_record.msg = f'{Fore.YELLOW}{new_record.msg}'
        elif self.__class__.RED_LEVELS_ABOVE <= new_record.levelno:
            new_record.msg = f'{Fore.RED}{new_record.msg}'

        new_record.msg = f'{new_record.msg}{Style.RESET_ALL}'
        return super().format(new_record, *args, **kwargs)


def log_section(section_text, color=Fore.CYAN, bold=False):
    log.info(f' {color}{section_text}{Style.RESET_ALL} '.center(80, '=' if bold else '-'))


class IgnoreYamlLoader(yaml.Loader):
    pass


IgnoreYamlLoader.add_constructor(None, lambda l, n: n)

session = boto3.Session()


class InvalidParameters(Exception): pass            # noqa E701,E302
class InvalidStackConfiguration(Exception): pass    # noqa E701,E302
class DeploymentFailed(Exception): pass             # noqa E701,E302
class StackTemplateInvalid(Exception): pass         # noqa E701,E302


ORG_ARN_RE = re.compile(r'^arn:aws:organizations::\d{12}:\w+/(?P<org_id>o-\w+)')


class DirectoryScanner(object):
    def scan_directories(self, path: str, glob: str = '**/*') -> List[Tuple[str, str]]:
        u = list()
        for item in Path(path).glob(glob):
            if Path.is_file(item):
                relative_path = str(item)
                key = relative_path[len(path):].strip(os.sep)
                u.extend([(key, relative_path)])
        return u


class VersionManifest(object):
    def __init__(self, s3_bucket: Any, s3_key: str) -> None:
        self.manifest: Dict[str, Any] = self.load_manifest(s3_bucket, s3_key)

    def load_manifest(self, s3_bucket: Any, s3_key: str) -> Dict[str, Any]:
        if s3_key is None:
            log.warning('No version manifest supplied, artifact tags are not supported for this deployment')
            return self.default_manifest()
        log.info(f'Loading version manifest from {Fore.GREEN}s3://{s3_bucket.name}/{s3_key}{Style.RESET_ALL}')
        o = s3_bucket.Object(s3_key)
        r: Dict[str, Any] = o.get()
        m: Dict[str, Any] = yaml.load(r['Body'], Loader=yaml.SafeLoader)
        log.info(f'Loaded version manifest for release {Fore.YELLOW}{m["release"]["release_version"]}{Style.RESET_ALL} '
            f'(S3 version: {Fore.YELLOW}{o.version_id}{Style.RESET_ALL})')
        log.debug('Version Manifest'.center(64, '-'))
        log.debug(m)
        return m

    def default_manifest(self) -> Dict[str, Any]:
        return {
            'release': {
                'release_version': 0,
                'artifacts': list()
            }
        }

    def get_artifact_by_name(self, name: str) -> Dict[str, Any]:
        for xa in self.manifest['release'].get('artifacts', list()):
            if xa['name'] == name:
                return xa
        raise DeploymentFailed(f'Artifact {name} is not part of the release')


class SSMParameters(object):
    def __init__(self, ssm_parameters: Dict[str, str], product_name: str, installation_name: str) -> None:
        self.product_name: str = product_name
        self.installation_name: str = installation_name
        self.parameters: Dict[str, str] = ssm_parameters

    def parameter_path(self, parameter_name: str) -> str:
        return f'/{self.product_name}/{self.installation_name}/{parameter_name}'

    def set_all_parameters(self) -> None:
        c = session.client('ssm')
        for k, v in self.parameters.items():
            log.info(f'Setting SSM {Fore.GREEN}{self.parameter_path(k)}{Style.RESET_ALL}='
                f'[{Fore.GREEN}{v}{Style.RESET_ALL}]')
            c.put_parameter(
                Name=self.parameter_path(k),
                Description='Set by Cloudformation Seed',
                Value=v,
                Type='String',
                Overwrite=True
            )


class StackParameters(object):
    def __init__(self, bucket, template, manifest, options, environment):
        self.bucket = bucket
        self.template = template
        self.environment = environment
        self.manifest = manifest

        self.installation_name = options.installation_name
        self.product_name = options.component_name
        self.dns_domain = options.dns_domain
        self.aws_org_arn = options.org_arn
        self.aws_org_id = ORG_ARN_RE.match(self.aws_org_arn).group('org_id') \
            if self.aws_org_arn is not None else None
        self.runtime_environment = options.runtime_environment
        self.parameters_dir = options.parameters_dir
        self.param_overrides = options.param_overrides or list()

        self.parameters_loader = self.configure_parameters_loader()
        self.STACK_OUTPUT_RE = \
            re.compile(r'^(?P<stack_name>[^\.]+)\.(?P<output_name>[^\.:]+)(:(?P<default_value>.*))?$')

        self.environment_parameters = \
            self.read_parameters_yaml(
                os.path.join(self.parameters_dir,
                f'{self.runtime_environment}.yaml')
            )

        self.common_parameters = self.environment_parameters.get('common-parameters', dict())
        self.stack_definition = [xs for xs in self.environment_parameters['stacks']
                                    if xs['name'] == self.template.name].pop()
        self.specific_parameters = self.stack_definition.get('parameters', dict())

        self.parameters = self.parse_parameters()

        self.stackset_admin_role_arn: Optional[str] = self.stack_definition.get('admin_role_arn')
        self.stackset_exec_role_name: Optional[str] = self.stack_definition.get('exec_role_name')
        self.stackset_call_as: Optional[str] = self.stack_definition.get('call_as', 'self')
        if self.stackset_call_as not in ('self', 'delegated_admin'):
            raise InvalidStackConfiguration(f'call_as for [{self.stack_definition["name"]}]'
                f' must be "self" or "delegated_admin", not [{self.stackset_call_as}]')
        self.operation_preferences: Dict[str, Union[str, List[str]]] = \
                self.stack_definition.get('operation_preferences', {})
        self.rollout_strategy: str = self.stack_definition.get('rollout_strategy', 'accounts')
        if self.rollout_strategy not in ('accounts', 'organization'):
            raise InvalidStackConfiguration(f'rollout_strategy for [{self.stack_definition["name"]}]'
                f' must be "accounts" or "organization", not [{self.rollout_strategy}]')
        self.rollout_autodeploy: Dict[str, bool] = self.stack_definition.get('rollout_autodeploy', {'enable': False})
        self.rollout = self.format_rollout()

    def format_rollout(self):
        c = session.client('cloudformation')
        if 'rollout' not in self.stack_definition:
            return None
        rollout = self.stack_definition['rollout']
        for xr in rollout:
            xr['regions'] = set(xr.get('regions', {c.meta.region_name}))
            xr['override'] = [{'ParameterKey': k, 'ParameterValue': str(v) if not isinstance(v, list) else ','.join(v)}
                for k, v in xr.get('override', dict()).items() if v is not None]
        return rollout

    def format_rollout_autodeploy(self):
        if self.rollout_strategy != 'organization':
            return dict()
        rollout_autodeploy = {
            'AutoDeployment': {
                'Enabled': self.rollout_autodeploy['enable']
            }
        }
        if self.rollout_autodeploy['enable']:
            rollout_autodeploy['AutoDeployment']['RetainStacksOnAccountRemoval'] = \
                self.rollout_autodeploy.get('retain_on_removal', False)
        return rollout_autodeploy

    def configure_parameters_loader(self):
        class ParametersLoader(yaml.Loader):
            pass
        ParametersLoader.add_constructor('!ObjectPath', self.run_objectpath)
        ParametersLoader.add_constructor('!IncludeAll', self.include_files)
        ParametersLoader.add_constructor('!Builtin', self.set_builtin)
        ParametersLoader.add_constructor('!EnvironmentVariable', self.set_env_var)
        ParametersLoader.add_constructor('!LambdaZip', self.set_lambda_zip)
        ParametersLoader.add_constructor('!CloudformationTemplateS3Key', self.set_cloudformation_template_s3_key)
        ParametersLoader.add_constructor('!CloudformationTemplateS3Url', self.set_cloudformation_template_url)
        ParametersLoader.add_constructor('!StackOutput', self.set_stack_output)
        ParametersLoader.add_constructor('!SSMParameterDirect', self.set_ssm_parameter)
        ParametersLoader.add_constructor('!SSMParameterDeclared', self.set_ssm_parameter_declared)
        ParametersLoader.add_constructor('!ArtifactVersion', self.set_artifact_version)
        ParametersLoader.add_constructor('!ArtifactRepo', self.set_artifact_repo)
        ParametersLoader.add_constructor('!ArtifactImage', self.set_artifact_image)
        return ParametersLoader

    def run_objpath_core(self, data, objpath):
        r = objectpath.Tree(data).execute(objpath)
        if isinstance(r, types.GeneratorType):
            return list(r)
        return r

    def run_objectpath(self, loader, node):
        @dataclass
        class Command:
            what: List or Dict
            objpath: str
        cmd = Command(*loader.construct_sequence(node, deep=True))
        val = self.run_objpath_core(cmd.what, cmd.objpath)
        return val

    def include_files_cat(self, files_glob, objpath):
        node = list()
        for f in Path(self.parameters_dir).glob(files_glob):
            log.info(f'Concatenating from {f}...')
            r = self.read_parameters_yaml(f)
            if objpath is not None:
                r = self.run_objpath_core(r, objpath)
            node.append(r)
        return node

    def include_files_merge(self, files_glob, objpath):
        node = dict()
        for f in Path(self.parameters_dir).glob(files_glob):
            log.info(f'Merging from {f}...')
            r = self.read_parameters_yaml(f)
            if objpath is not None:
                r = self.run_objpath_core(r, objpath)
            node.update(r)
        return node

    def include_files(self, loader, node):
        @dataclass
        class Command:
            operation: str
            files_glob: str
            objpath: str = None
        cmd = Command(*loader.construct_sequence(node, deep=True))
        val = None
        if cmd.operation == 'concat':
            log.info(f'Concatenating include file(s) from {cmd.files_glob}...')
            val = self.include_files_cat(cmd.files_glob, cmd.objpath)
        else:
            log.info(f'Merging include file(s) from {cmd.files_glob}...')
            val = self.include_files_merge(cmd.files_glob, cmd.objpath)
        log.debug(f'Successfully read include file(s) from {cmd.files_glob}')
        return val

    def set_builtin(self, loader, node):
        param_name = loader.construct_scalar(node)
        log.debug(f'Setting parameter {param_name}...')
        val = self.get_special_parameter_value(param_name)
        if val is None:
            raise InvalidStackConfiguration(f'Unsupported builtin parameter [{param_name}]')
        return val

    def set_env_var(self, loader, node):
        var_name = loader.construct_scalar(node)
        log.debug(f'Looking up environment variable {var_name}...')
        try:
            val = os.environ[var_name]
            return val
        except KeyError:
            raise InvalidStackConfiguration(f'Environment variable [{var_name}] is not set')

    def set_lambda_zip(self, loader, node):
        zip_name = loader.construct_scalar(node)
        log.debug(f'Looking up Lambda zip {zip_name}...')
        val = self.environment.lambdas.find_lambda_key(zip_name)
        log.debug(f'Found Lambda zip {val}...')
        return val

    def set_cloudformation_template_s3_key(self, loader, node):
        template_name = loader.construct_scalar(node)
        log.debug(f'Looking up Cloudformation template {template_name}...')
        t = self.environment.templates.find_template(template_name)
        val = t.template_s3_key
        log.debug(f'Found template {val}...')
        return val

    def set_cloudformation_template_url(self, loader, node):
        template_name = loader.construct_scalar(node)
        log.debug(f'Looking up Cloudformation template {template_name}...')
        t = self.environment.templates.find_template(template_name)
        val = t.template_url
        log.debug(f'Found template {val}...')
        return val

    def set_stack_output(self, loader, node):
        output_id = loader.construct_scalar(node)
        m = self.STACK_OUTPUT_RE.match(output_id)
        if m is None:
            raise InvalidStackConfiguration(f'Output specification [{output_id}] invalid, '
                f'must be stack-name.OutputId:default value')
        log.debug(f'Looking up stack output {output_id}...')
        val = self.environment.find_stack_output(m.group('stack_name'), m.group('output_name'))
        if val is None:
            if m.group('default_value') is not None:
                val = m.group('default_value')
        log.debug(f'Found stack output {val}...')
        return val

    def set_ssm_parameter(self, loader, node):
        c = session.client('ssm')
        parameter_name = loader.construct_scalar(node)
        parameter_path = f'/{self.product_name}/{self.installation_name}/{parameter_name}'
        log.debug(f'Looking up SSM parameter {parameter_path}...')
        r = c.get_parameter(Name=parameter_path, WithDecryption=True)
        val = r['Parameter']['Value']
        log.debug(f'Found parameter version {r["Parameter"]["Version"]}: {val}...')
        return val

    def set_ssm_parameter_declared(self, loader, node):
        parameter_name = loader.construct_scalar(node)
        parameter_path = f'/{self.product_name}/{self.installation_name}/{parameter_name}'
        log.debug(f'Setting declared SSM parameter to {parameter_path}')
        return parameter_path

    def set_artifact_version(self, loader, node):
        artifact_name = loader.construct_scalar(node)
        log.debug(f'Looking up artifact {artifact_name}...')
        artifact = self.manifest.get_artifact_by_name(artifact_name)
        val = artifact['version']
        log.debug(f'Found version {val} for artifact {artifact_name}...')
        return val

    def set_artifact_repo(self, loader, node):
        artifact_name = loader.construct_scalar(node)
        log.debug(f'Looking up artifact {artifact_name}...')
        artifact = self.manifest.get_artifact_by_name(artifact_name)
        val = artifact['artifactory_host']
        log.debug(f'Found repo {val} for artifact {artifact_name}...')
        return val

    def set_artifact_image(self, loader, node):
        artifact_name = loader.construct_scalar(node)
        log.debug(f'Looking up artifact {artifact_name}...')
        artifact = self.manifest.get_artifact_by_name(artifact_name)
        val = f'{artifact["artifactory_host"]}/{artifact_name}:{artifact["version"]}'
        log.debug(f'Found image name {val} for artifact {artifact_name}...')
        return val

    def read_parameters_yaml(self, filename):
        with open(filename, 'r') as f:
            r = yaml.load(f, Loader=self.parameters_loader)
            return r

    def compute_parameter_value(self, param_name):
        common_val = self.common_parameters.get(param_name)
        specific_val = self.specific_parameters.get(param_name)
        for source, xv in (('OVERRIDE', self.get_parameter_override(param_name)),
                ('SPECIFIC', specific_val),
                ('COMMON', common_val),
                ('BUILTIN', self.get_special_parameter_value(param_name)),
                ('ABSENT', None)):
            if xv is not None or source == 'ABSENT':
                if isinstance(xv, list):
                    xv = ','.join(xv)
                return source, xv

    def get_special_parameter_value(self, param_name):
        if param_name == 'ProductName':
            return self.product_name
        if param_name == 'InstallationName':
            return self.installation_name
        if param_name == 'TemplatesS3Bucket':
            return self.bucket.name
        if param_name == 'Route53ZoneDomain':
            return self.dns_domain
        if param_name == 'RuntimeEnvironment':
            return self.runtime_environment
        if param_name == 'AWSOrganizationID':
            return self.aws_org_id
        if param_name == 'AWSOrganizationARN':
            return self.aws_org_arn

    def get_parameter_override(self, param_name):
        for xp in self.param_overrides:
            if xp[0] == self.stack_definition['name'] or xp[0] is None:
                if xp[1] == param_name:
                    return xp[2]

    def parse_parameters(self):
        p = dict()
        for k in self.template.template_body.parameters.keys():
            source, v = self.compute_parameter_value(k)
            log.info('{key:>30} ... ({source:^10}) [{value}]'.format(key=k, source=source,
                value=f'{Fore.CYAN}>> EMPTY <<{Style.RESET_ALL}' if v is None else f'{Fore.GREEN}{v}{Style.RESET_ALL}'))
            p[k] = v
        return p

    def format_parameters(self):
        return [{'ParameterKey': k, 'ParameterValue': str(v)} for k, v in self.parameters.items() if v is not None]

    def format_role_pair(self) -> Dict[str, str]:
        if self.template.template_type != 'stackset':
            raise RuntimeError('Stackset roles only work for stacksets')
        if self.stackset_admin_role_arn and self.stackset_exec_role_name:
            return {
                'AdministrationRoleARN': self.stackset_admin_role_arn,
                'ExecutionRoleName': self.stackset_exec_role_name
            }
        if self.stackset_admin_role_arn or self.stackset_exec_role_name:
            raise InvalidStackConfiguration('Either specify both admin_role_arn and exec_role_name or none of them.'
                                            ' Only one will not work')
        return dict()

    def format_operation_preferences(self):
        if self.template.template_type != 'stackset':
            raise RuntimeError('Operation preferences only work for stacksets')
        prefs = dict()
        tolerance = self.operation_preferences.get('failure_tolerance')
        max_concurrent = self.operation_preferences.get('max_concurrent')
        region_order = self.operation_preferences.get('region_order')
        region_concurrency_type = self.operation_preferences.get('region_concurrency_type')
        if tolerance is not None:
            if isinstance(tolerance, int):
                prefs['FailureToleranceCount'] = tolerance
                log.info(f'Setting tolerance to '
                    f'{Fore.GREEN}{prefs["FailureToleranceCount"]}{Style.RESET_ALL} stack instances')
            elif tolerance.endswith('%'):
                prefs['FailureTolerancePercentage'] = int(tolerance.rstrip('%'))
                log.info(f'Setting tolerance percentage to '
                    f'{Fore.GREEN}{prefs["FailureTolerancePercentage"]}%{Style.RESET_ALL}')
            else:
                raise InvalidStackConfiguration('failure_tolerance in operation_preferences must either be '
                    f'integer or have a percent sign on stack {self.template.name}')
        if max_concurrent is not None:
            if isinstance(max_concurrent, int):
                prefs['MaxConcurrentCount'] = max_concurrent
                log.info(f'Setting concurrency to '
                    f'{Fore.GREEN}{prefs["MaxConcurrentCount"]}{Style.RESET_ALL} stack instances')
            elif max_concurrent.endswith('%'):
                prefs['MaxConcurrentPercentage'] = int(max_concurrent.rstrip('%'))
                log.info(f'Setting concurrency percentage to '
                    f'{Fore.GREEN}{prefs["MaxConcurrentPercentage"]}%{Style.RESET_ALL}')
            else:
                raise InvalidStackConfiguration('max_concurrent in operation_preferences must either be '
                    f'integer or have a percent sign on stack {self.template.name}')
        if region_order is not None:
            if isinstance(region_order, list):
                prefs['RegionOrder'] = region_order
                log.info(f'Setting region order to '
                    f'{Fore.GREEN}{" >> ".join(prefs["RegionOrder"])}{Style.RESET_ALL}')
            else:
                raise InvalidStackConfiguration('region_order in operation_preferences must be a list '
                    f'on stack {self.template.name}')
        if region_concurrency_type is not None:
            if region_concurrency_type not in ('PARALLEL', 'SEQUENTIAL'):
                raise InvalidStackConfiguration('region_concurrency_type in operation_preferences must be '
                    f'either PARALLEL or SEQUENTIAL on stack {self.template.name}')
            prefs['RegionConcurrencyType'] = region_concurrency_type
            log.info(f'Setting region concurrency type to '
                f'{Fore.GREEN}{prefs["RegionConcurrencyType"]}{Style.RESET_ALL}')
        return {'OperationPreferences': prefs}
