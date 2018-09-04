#!/usr/bin/env python3

from typing import Dict, List, Tuple, Any, Optional, NoReturn

import yaml
import boto3
import hashlib
import zipfile
import time
import os
import subprocess
import sys
import argparse
import logging
from botocore.exceptions import ClientError

log = logging.getLogger('deploy-stack')


class IgnoreYamlLoader(yaml.Loader):
    pass


IgnoreYamlLoader.add_constructor(None, lambda l, n: n)

s = boto3.Session()


class InvalidStackConfiguration(Exception): pass    # noqa E701,E302
class DeploymentFailed(Exception): pass             # noqa E701,E302
class StackTemplateInvalid(Exception): pass         # noqa E701,E302


class DirectoryScanner(object):
    def scan_directories(self, path: str) -> List[Tuple[str, str]]:
        u = list()
        for root, _, files in os.walk(path):
            relative_root = root.replace(path, '').strip(os.sep)
            u.extend([(f'{relative_root}/{f}'.replace(os.sep, '/').strip('/'), os.path.join(root, f)) for f in files])
        return u


class S3Uploadable(object):
    def __init__(self, file_path: str, s3_bucket: Any, s3_key: str) -> None:
        self.file_path: str = file_path
        self.s3_bucket: Any = s3_bucket
        self.s3_key: str = s3_key
        self.bytes: int = 0
        self.total_bytes: int = os.path.getsize(self.file_path)

    def print_progress(self, current_bytes: int) -> None:
        self.bytes += current_bytes
        log.debug(f'{self.bytes} bytes out of {self.total_bytes} complete')

    def upload(self) -> None:
        log.info(f'Uploading {self.file_path} into {self.s3_url}')
        self.s3_bucket.upload_file(self.file_path, self.s3_key, Callback=self.print_progress)

    @property
    def s3_url(self):
        return f'{s.client("s3").meta.endpoint_url}/{self.s3_bucket.name}/{self.s3_key}'


class S3RecursiveUploader(DirectoryScanner):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.s3_bucket: Any = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        log.info(f'Scanning files in {path}...')
        self.u = [S3Uploadable(f, self.s3_bucket, f'{self.s3_key_prefix}/{k}')
            for k, f in self.scan_directories(path)]

    def upload(self) -> None:
        for xu in self.u:
            xu.upload()


class LambdaFunction(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str):
        self.path: str = path
        self.s3_bucket: str = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        self.zip_file: Optional[str] = None
        self.u: Optional[S3Uploadable] = None

    @property
    def s3_key(self) -> str:
        return self.u.s3_key

    def find_lambda_zipfile(self) -> str:
        log.debug(f'Looking for zipfile in {self.path}')
        for xf in os.listdir(self.path):
            if xf.endswith('.zip'):
                log.debug(f'Finally {xf} looks like a zip file')
                return xf
            log.debug(f'{xf} is not a zip file')
        raise InvalidStackConfiguration(f'Lambda function source at {self.path} must produce a zipfile')

    def build_bucket_key(self) -> str:
        sha1sum = hashlib.sha1()
        with zipfile.ZipFile(os.path.join(self.path, self.zip_file), 'r') as f:
            for xc in sorted([xf.CRC for xf in f.filelist]):
                sha1sum.update(xc.to_bytes((xc.bit_length() + 7) // 8, 'big') or b'\0')
        return f'{self.s3_key_prefix}/{sha1sum.hexdigest()}-{self.zip_file}'

    def prepare(self) -> None:
        log.info(f'Running make in {self.path}...')
        subprocess.run(['make'], check=True, cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.zip_file = self.find_lambda_zipfile()
        self.u = S3Uploadable(os.path.join(self.path, self.zip_file), self.s3_bucket, self.build_bucket_key())

    def upload(self) -> None:
        self.u.upload()

    def cleanup(self) -> None:
        log.info(f'Running make clean in {self.path}...')
        subprocess.run(['make', 'clean'], cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LambdaCollection(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str):
        self.s3_bucket: Any = s3_bucket
        self.lambdas: List[LambdaFunction] = [LambdaFunction(os.path.join(path, x), self.s3_bucket, s3_key_prefix)
                        for x in os.listdir(path) if os.access(os.path.join(path, x, 'Makefile'), os.R_OK)]

    def prepare(self) -> None:
        for x in self.lambdas:
            x.prepare()

    def upload(self) -> None:
        for x in self.lambdas:
            x.upload()

    def cleanup(self) -> None:
        for x in self.lambdas:
            x.cleanup()

    def find_lambda_key(self, zip_name) -> str:
        try:
            return [x.s3_key for x in self.lambdas if x.zip_file == zip_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Lambda function bundle {zip_name} not found')


class CloudformationTemplate(object):
    def __init__(self, s3_bucket: Any, s3_key: str, s3_key_prefix: str,
                    file_path: str, template_parameters: Dict[str, Any]) -> None:
        self.s3_key_prefix: str = s3_key_prefix
        self.s3_key: str = s3_key
        self.template_parameters: Dict[str, Any] = template_parameters
        self.template_body: Dict['str', Any] = self.read_template_yaml(file_path)
        self.u: S3Uploadable = S3Uploadable(file_path, s3_bucket, f'{self.s3_key_prefix}/{self.s3_key}')

    @property
    def name(self) -> str:
        return self.template_parameters['name']

    @property
    def template(self) -> str:
        return self.template_parameters['template']

    @property
    def template_type(self) -> str:
        return self.template_parameters.get('type', 'stack')

    @property
    def template_key(self) -> str:
        return self.u.s3_key

    @property
    def template_url(self) -> str:
        return self.u.s3_url

    def read_template_yaml(self, file_path: str) -> Dict['str', Any]:
        log.info(f'Loading template for stack {self.name} from {file_path}...')
        with open(file_path, 'r') as f:
            return yaml.load(f, Loader=IgnoreYamlLoader)

    def upload(self) -> None:
        self.u.upload()


class CloudformationCollection(DirectoryScanner):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str,
                    environment_parameters: Dict['str', Any]) -> None:
        self.s3_bucket: Any = s3_bucket
        self.environment_parameters: Dict['str', Any] = environment_parameters
        self.template_files: List[Tuple[str, str]] = self.scan_directories(path)
        self.templates: List[CloudformationTemplate] = [
            CloudformationTemplate(
                self.s3_bucket,
                xs['template'],
                s3_key_prefix,
                self.find_template_file(xs['template']), xs
            ) for xs in self.environment_parameters.get('stacks', list())
        ]

    def list_deployable(self) -> List[CloudformationTemplate]:
        u = list()
        for xs in self.environment_parameters.get('stacks', list()):
            try:
                stack_template = [xt for xt in self.templates if xt.name == xs.get('name')].pop()
                u.append(stack_template)
            except IndexError:
                raise InvalidStackConfiguration(f'Template not found for {xs.get("name")}')
        return u

    def find_template_key(self, template_name: str) -> str:
        try:
            return [x.template_key for x in self.templates if x.template == template_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Template {template_name} not found')

    def find_template_file(self, template_key: str) -> str:
        for xk, xp in self.template_files:
            if xk == template_key:
                return xp
        raise InvalidStackConfiguration(f'Template file not found for {template_key}')

    def upload(self) -> None:
        for xt in [xt for n, xt in enumerate(self.templates)
                        if xt.template not in [xxt.template for xxt in self.templates[:n]]]:
            xt.upload()


class VersionManifest(object):
    def __init__(self, s3_bucket: Any, s3_key: str) -> None:
        self.manifest: Dict[str, Any] = self.load_manifest(s3_bucket, s3_key)

    def load_manifest(self, s3_bucket: Any, s3_key: str) -> Dict[str, Any]:
        if s3_key is None:
            log.info('No version manifest supplied, artifact tags are not supported for this deployment')
            return self.default_manifest()
        log.info(f'Loading version manifest from s3://{s3_bucket.name}/{s3_key}')
        o: boto3.Object = s3_bucket.Object(s3_key)
        r: Dict[str, Any] = o.get()
        m: Dict[str, Any] = yaml.load(r['Body'])
        log.info(f'Loaded version manifest for release {m["release"]["release_version"]} (S3 version: {o.version_id})')
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
        raise RuntimeError(f'Artifact {name} is not part of the release')


class StackParameters(object):
    def __init__(self, bucket, template, manifest, options, environment):
        self.parameters = dict()
        self.overrides = dict()
        self.bucket = bucket
        self.template = template
        self.environment = environment
        self.manifest = manifest

        self.installation_name = options.installation_name
        self.dns_domain = options.dns_domain
        self.runtime_environment = options.runtime_environment
        self.parameters_dir = options.parameters_dir

        self.parameters_loader = self.configure_parameters_loader()

        self.environment_parameters = self.read_parameters_yaml(
                                            os.path.join(self.parameters_dir,
                                            f'{self.runtime_environment}.yaml')
                                        ) or dict()
        self.common_parameters = self.environment_parameters.get('common-parameters', dict())
        self.stack_definition = [xs for xs in self.environment_parameters['stacks']
                                    if xs['name'] == self.template.name].pop()
        self.specific_parameters = self.stack_definition.get('parameters', dict())
        self.rollout = self.stack_definition.get('rollout', list())
        self.pilot_configuration = self.stack_definition.get('pilot', dict())
        self.pilot_accounts = self.pilot_configuration.get('accounts', list())
        self.pilot_regions = self.pilot_configuration.get(
                                'regions',
                                [s.client('cloudformation').meta.region_name]
                            ) if len(self.pilot_accounts) > 0 else list()

    def configure_parameters_loader(self):
        class ParametersLoader(yaml.Loader):
            pass
        ParametersLoader.add_constructor('!LambdaZip', self.set_lambda_zip)
        ParametersLoader.add_constructor('!CloudformationTemplate', self.set_cloudformation_template)
        ParametersLoader.add_constructor('!StackOutput', self.set_stack_output)
        ParametersLoader.add_constructor('!ArtifactVersion', self.set_artifact_version)
        ParametersLoader.add_constructor('!ArtifactRepo', self.set_artifact_repo)
        ParametersLoader.add_constructor('!ArtifactImage', self.set_artifact_image)
        return ParametersLoader

    def set_lambda_zip(self, loader, node):
        zip_name = loader.construct_scalar(node)
        log.debug(f'Looking up Lambda zip {zip_name}...')
        val = self.environment.lambdas.find_lambda_key(zip_name)
        log.debug(f'Found Lambda zip {val}...')
        return val

    def set_cloudformation_template(self, loader, node):
        template_name = loader.construct_scalar(node)
        log.debug(f'Looking up Cloudformation template {template_name}...')
        val = self.environment.templates.find_template_key(template_name)
        log.debug(f'Found template {val}...')
        return val

    def set_stack_output(self, loader, node):
        output_id = loader.construct_scalar(node)
        log.debug(f'Looking up stack output {output_id}...')
        val = self.environment.find_stack_output(output_id)
        log.debug(f'Found stack output {val}...')
        return val

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
            return yaml.load(f, Loader=self.parameters_loader)

    def compute_parameter_value(self, param_name):
        common_val = self.common_parameters.get(param_name)
        specific_val = self.specific_parameters.get(param_name)
        log.debug(f'Parameter {param_name}: common [{common_val}] - specific [{specific_val}]')
        for xv in (self.get_special_parameter_value(param_name), specific_val, common_val):
            if xv is not None:
                return xv

    def get_installation_name(self):
        return self.installation_name

    def get_runtime_environment(self):
        return self.runtime_environment

    def get_templates_s3_bucket(self):
        return self.bucket.name

    def get_dns_domain(self):
        return self.dns_domain

    def get_special_parameter_value(self, param_name):
        if param_name == 'InstallationName':
            return self.get_installation_name()
        if param_name == 'TemplatesS3Bucket':
            return self.get_templates_s3_bucket()
        if param_name == 'Route53ZoneDomain':
            return self.get_dns_domain()
        if param_name == 'RuntimeEnvironment':
            return self.get_runtime_environment()

    def parse_parameters(self):
        for k in self.template.template_body['Parameters'].keys():
            val = self.compute_parameter_value(k)
            log.info(f'{k} = [{val if val is not None else ">>NOTSET<<"}]')
            self.parameters[k] = val

    def format_parameters_create(self):
        return [{'ParameterKey': k, 'ParameterValue': str(v)} for k, v in self.parameters.items() if v is not None]

    def format_parameters_update(self, stack):
        existing_parameters = {xp['ParameterKey']: xp['ParameterValue'] for xp in stack['Parameters']}
        f = list()
        for k, v in self.parameters.items():
            if v is not None:
                f.append({
                    'ParameterKey': k,
                    'ParameterValue': str(v)
                })
                continue
            if k in existing_parameters:
                f.append({
                    'ParameterKey': k,
                    'UsePreviousValue': True
                })
        return f

    def format_stackset_overrides(self, account_id):
        if self.template.template_type != 'stackset':
            raise RuntimeError('Parameter overrides only work for stacksets')
        for xa in self.rollout:
            if xa['account'] == account_id:
                if 'override' in xa:
                    return [{'ParameterKey': k, 'ParameterValue': str(v)}
                                for k, v in xa['override'].items() if v is not None]
                return []
        raise RuntimeError(f'Stackset is not rolling out to account {account_id}')


class CloudformationStack(object):

    def __init__(self, installation_name: str, template: CloudformationTemplate) -> None:
        self.template: CloudformationTemplate = template
        self.stack_name: str = f'{installation_name}-{self.template.name}'
        self.stack_parameters: Optional[StackParameters] = None
        self.existing_stack = self.find_existing_stack()
        self.stack = None

    def set_parameters(self, parameters: StackParameters) -> None:
        self.stack_parameters = parameters

    def find_existing_stack(self) -> Optional[Dict[str, Any]]:
        c = s.client('cloudformation')
        log.info(f'Loading stack {self.stack_name}...')
        try:
            r = c.describe_stacks(StackName=self.stack_name)
            log.info(f'Stack {self.stack_name} found')
            return r['Stacks'].pop()
        except Exception:
            log.info(f'Stack {self.stack_name} does not exist, skipping')
            return None

    def get_stack_output(self, output_name: str) -> Optional[str]:
        if self.stack is None:
            log.debug(f'Can\'t find output {self.stack_name}.{output_name}, stack has not been yet deployed')
            return None
        for xo in self.stack.outputs:
            if xo['OutputKey'] == output_name:
                log.debug(f'Output {self.stack_name}.{output_name} = {xo["OutputValue"]}')
                return xo['OutputValue']

    def create_stack(self, caps: List[str]) -> None:
        c = s.client('cloudformation')
        log.info(f'Creating stack {self.stack_name} with template {self.template.template_url} capabilities {caps}')
        c.create_stack(
            StackName=self.stack_name,
            TemplateURL=self.template.template_url,
            Parameters=self.stack_parameters.format_parameters_create(),
            DisableRollback=True,
            Capabilities=caps
        )
        self.wait('stack_create_complete')
        self.retrieve()

    def update_stack(self, caps: List[str]) -> None:
        c = s.client('cloudformation')
        p = self.stack_parameters.format_parameters_update(self.existing_stack)
        log.info(f'Updating stack {self.stack_name} with template {self.template.template_url} capabilities {caps}')
        log.debug(' Parameters '.center(48, '-'))
        log.debug(p)
        log.debug('-'.center(48, '-'))
        try:
            c.update_stack(
                StackName=self.stack_name,
                TemplateURL=self.template.template_url,
                Parameters=p,
                Capabilities=caps
            )
            self.wait('stack_update_complete')
        except ClientError as e:
            if e.response['Error']['Message'] == 'No updates are to be performed.':
                log.info(f'No updates are to be done on stack {self.stack_name}')
            else:
                raise
        self.retrieve()

    def format_caps(self, cap_iam: bool, cap_named_iam: bool) -> List[str]:
        caps = list()
        if cap_iam:
            caps.append('CAPABILITY_IAM')
        if cap_named_iam:
            caps.append('CAPABILITY_NAMED_IAM')
        return caps

    def deploy(self, cap_iam: bool, cap_named_iam: bool) -> None:
        caps = self.format_caps(cap_iam, cap_named_iam)
        if self.existing_stack is None:
            self.create_stack(caps)
        else:
            self.update_stack(caps)

    def teardown(self) -> None:
        if self.existing_stack is None:
            log.info(f'Stack {self.stack_name} does not exist. Skipping.')
            return
        c = s.client('cloudformation')
        log.info(f'Deleting stack {self.stack_name}...')
        c.delete_stack(StackName=self.stack_name)
        self.wait('stack_delete_complete')

    def wait(self, event: str) -> None:
        log.info('Waiting for operation to finish...')
        c = s.client('cloudformation')
        waiter = c.get_waiter(event)
        try:
            waiter.wait(StackName=self.stack_name)
        except Exception:
            r = s.resource('cloudformation')
            self.stack = r.Stack(self.stack_name)
            log.error(f'Operation failed: {self.stack.stack_status_reason}')
            raise DeploymentFailed(self.stack.stack_status_reason)

    def retrieve(self) -> None:
        r = s.resource('cloudformation')
        self.stack = r.Stack(self.stack_name)
        log.info(f'Found stack {self.stack.stack_name} in status {self.stack.stack_status}')


class CloudformationStackSet(object):
    def __init__(self, installation_name: str, template: CloudformationTemplate) -> None:
        self.template: CloudformationTemplate = template
        self.stack_name: str = f'{installation_name}-{self.template.name}'
        self.stack_parameters: Optional[StackParameters] = None
        self.existing_stack: Optional[Dict[str, Any]] = self.find_existing_stackset()
        self.stack = None

    def set_parameters(self, parameters: StackParameters) -> None:
        self.stack_parameters = parameters

    def find_existing_stackset(self) -> Optional[Dict[str, Any]]:
        c = s.client('cloudformation')
        log.info(f'Loading stackset {self.stack_name}...')
        try:
            r = c.describe_stack_set(StackSetName=self.stack_name)
            log.info(f'Stackset {self.stack_name} found')
            return r['StackSet']
        except Exception:
            log.info(f'Stackset {self.stack_name} does not exist, skipping')
            return None

    def get_stack_output(self, output_name: str) -> NoReturn:
        raise InvalidStackConfiguration(f'Can\'t retrieve output {output_name} of stackset {self.stack_name}'
                                        f', stacksets don\'t have outputs. Please review your configuration')

    def create_stackset(self, caps: List[str]) -> None:
        c = s.client('cloudformation')
        log.info(f'Creating stackset {self.stack_name} with template {self.template.template_url} capabilities {caps}')
        c.create_stack_set(
            StackSetName=self.stack_name,
            TemplateURL=self.template.template_url,
            Parameters=self.stack_parameters.format_parameters_create(),
            Capabilities=caps
        )

    def update_stackset(self, caps: List[str]) -> None:
        c = s.client('cloudformation')
        p = self.stack_parameters.format_parameters_update(self.existing_stack)
        log.info(f'Updating stackset {self.stack_name} with template {self.template.template_url} capabilities {caps}')
        log.info(f' => capabilities {caps}')
        log.info(f' => pilot accounts {self.stack_parameters.pilot_accounts}')
        log.info(f' => pilot regions {self.stack_parameters.pilot_regions}')
        log.debug(' Parameters '.center(48, '-'))
        log.debug(p)
        log.debug('-'.center(48, '-'))
        c.update_stack_set(
            StackSetName=self.stack_name,
            TemplateURL=self.template.template_url,
            Parameters=p,
            Capabilities=caps,
            Accounts=self.stack_parameters.pilot_accounts,
            Regions=self.stack_parameters.pilot_regions
        )

    def retrieve(self) -> None:
        c = s.client('cloudformation')
        r = c.describe_stack_set(StackSetName=self.stack_name)
        self.stack = r['StackSet']
        log.info(f'Found stackset {self.stack["StackSetName"]} in status {self.stack["Status"]}')

    def format_caps(self, cap_iam: bool, cap_named_iam: bool) -> List[str]:
        caps = list()
        if cap_iam:
            caps.append('CAPABILITY_IAM')
        if cap_named_iam:
            caps.append('CAPABILITY_NAMED_IAM')
        return caps

    def deploy(self, cap_iam: bool, cap_named_iam: bool) -> None:
        caps = self.format_caps(cap_iam, cap_named_iam)
        self.wait_pending_operations()
        if self.existing_stack is None:
            self.create_stackset(caps)
        else:
            for xa in self.stack_parameters.rollout:
                log.info(f'Cleanup account {xa["account"]}...')
                self.cleanup_stack_instances(xa)
                self.wait_pending_operations()
            self.update_stackset(caps)
        self.wait_pending_operations()
        self.retrieve()
        for xa in self.stack_parameters.rollout:
            self.rollout_account(xa)
            self.wait_pending_operations()

    def cleanup_stack_instances(self, account_info: Dict[str, Any]) -> None:
        c = s.client('cloudformation')
        regions = account_info.get('regions', [c.meta.region_name])
        i = c.list_stack_instances(
            StackSetName=self.stack_name,
            StackInstanceAccount=account_info['account']
        )
        existing_regions = {xi['Region'] for xi in i['Summaries']}
        delete_regions = existing_regions - set(regions)
        if len(delete_regions) > 0:
            log.info(f'Cleaning up stack instances for account {account_info["account"]} '
                        f'in regions {delete_regions}...')
            c.delete_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account_info['account']],
                Regions=list(delete_regions),
                RetainStacks=False
            )

    def rollout_account(self, account_info: Dict[str, Any]) -> None:
        c = s.client('cloudformation')
        log.info(f'Rolling out stackset {self.stack_name} to account {account_info["account"]}...')
        overrides = self.stack_parameters.format_stackset_overrides(account_info['account'])
        regions = account_info.get('regions', [c.meta.region_name])
        if len(overrides) == 0:
            log.info('Reset parameter overrides')
        for xo in overrides:
            log.info(f'Override {xo["ParameterKey"]}={xo["ParameterValue"]}')
        i = c.list_stack_instances(
            StackSetName=self.stack_name,
            StackInstanceAccount=account_info['account']
        )
        existing_regions = {xi['Region'] for xi in i['Summaries']}
        create_regions = set(regions) - existing_regions
        update_regions = set(regions) & existing_regions
        delete_regions = existing_regions - set(regions)
        if len(delete_regions) > 0:
            log.info(f'Deleting stack instances in regions {delete_regions}...')
            c.delete_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account_info['account']],
                Regions=list(delete_regions),
                RetainStacks=False
            )
            self.wait_pending_operations()
        if len(create_regions) > 0:
            log.info(f'Creating new stack instances in regions {create_regions}...')
            c.create_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account_info['account']],
                Regions=list(create_regions),
                ParameterOverrides=overrides
            )
            self.wait_pending_operations()
        if len(update_regions) > 0:
            log.info(f'Updating stack instances in regions {update_regions}...')
            c.update_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account_info['account']],
                Regions=list(update_regions),
                ParameterOverrides=overrides
            )
            self.wait_pending_operations()

    def delete_stack_instances(self) -> None:
        c = s.client('cloudformation')
        i = c.list_stack_instances(StackSetName=self.stack_name)
        for xi in i['Summaries']:
            log.info(f'Deleting stack instance in account {xi["Account"]} region {xi["Region"]}...')
            c.delete_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[xi['Account']],
                Regions=[xi['Region']],
                RetainStacks=False
            )
            self.wait_pending_operations()

    def delete_stackset(self) -> None:
        c = s.client('cloudformation')
        log.info(f'Deleting stackset {self.stack_name}...')
        c.delete_stack_set(StackSetName=self.stack_name)

    def teardown(self) -> None:
        if self.existing_stack is None:
            log.info(f'StackSet {self.stack_name} does not exist. Skipping.')
            return
        self.wait_pending_operations()
        self.delete_stack_instances()
        self.delete_stackset()

    def wait_pending_operations(self) -> None:
        c = s.client('cloudformation')
        try:
            while True:
                r = c.list_stack_set_operations(StackSetName=self.stack_name, MaxResults=10)
                if len([xo for xo in r['Summaries'] if xo['Status'] in ['RUNNING', 'STOPPING']]) > 0:
                    log.info(f'There\'s operations pending on stackset {self.stack_name}')
                    time.sleep(10)
                    continue
                return
        except ClientError as e:
            if e.response['Error']['Code'] != 'StackSetNotFoundException':
                raise


class CloudformationEnvironment(object):
    def __init__(self, s3_bucket, lambdas, templates, manifest, options):
        self.s3_bucket = s3_bucket
        self.options = options
        self.installation_name = options.installation_name
        self.dns_domain = options.dns_domain
        self.runtime_environment = options.runtime_environment
        self.cap_iam = options.cap_iam
        self.cap_named_iam = options.cap_named_iam

        self.lambdas = lambdas
        self.templates = templates
        self.manifest = manifest

        self.templates_dir = options.templates_dir
        self.parameters_dir = options.parameters_dir
        self.templates_prefix = options.templates_prefix

        self.stacks = self.setup_stacks()

    def setup_stacks(self):
        stacks = list()
        for xt in self.templates.list_deployable():
            if xt.template_type == 'stack':
                log.info(f'Adding stack {xt.name} at {xt.template_url}...')
                stacks.append(CloudformationStack(self.installation_name, xt))
            elif xt.template_type == 'stackset':
                log.info(f'Adding stackset {xt.name} at {xt.template_url}...')
                stacks.append(CloudformationStackSet(self.installation_name, xt))
        return stacks

    def find_stack_output(self, output_id):
        stack_name, output_name = output_id.split('.')
        try:
            return [xs.get_stack_output(output_name) for xs in self.stacks if xs.template.name == stack_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Can\'t find output {output_id}, '
                        f'template {stack_name} is not part of the deployment')

    def find_template(self, template_name):
        try:
            return [f'{xt.s3_key_prefix}/{xt.s3_key}' for xt in self.templates if xt.s3_key == template_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Template {template_name} is not part of the deployment')

    def deploy_stacks(self):
        for xs in self.stacks:
            log.info(f'Computing parameters for stack {xs.stack_name}...')
            p = StackParameters(self.s3_bucket, xs.template, self.manifest, self.options, self)
            p.parse_parameters()
            xs.set_parameters(p)
            xs.deploy(self.cap_iam, self.cap_named_iam)
            log.info(f' {xs.stack_name} completed '.center(64, '-'))

    def teardown_stacks(self):
        for xs in reversed(self.stacks):
            xs.teardown()


class StackDeployer(object):
    def configure_args(self):
        opts = argparse.ArgumentParser(description='Generates parameters and deploys Cloudformation stacks')

        gc = opts.add_argument_group('Configuration')
        gc.add_argument('-c', '--component-name', default='generic-ops', help='Name of the component being deployed')
        gc.add_argument('-i', '--installation-name', required=True, help='Stack name')
        gc.add_argument('-e', '--runtime-environment', required=True, help='Configuration section name')
        gc.add_argument('-d', '--dns-domain', required=True, help='DNS domain associated with this installation')
        gc.add_argument('-m', '--manifest', help='S3 key of a version manifest')
        gc.add_argument('--cap-iam', action='store_true', help='Enable CAP_IAM on the stack')
        gc.add_argument('--cap-named-iam', action='store_true', help='Enable CAP_NAMED_IAM on the stack')

        gp = opts.add_argument_group('Paths')
        gp.add_argument('--templates-dir', default='cloudformation', help='Relative path to CF templates')
        gp.add_argument('--appconfig-dir', default='config', help='Relative path to application configuration')
        gp.add_argument('--parameters-dir', default='parameters', help='Relative path to parameters')
        gp.add_argument('--lambda-dir', default='src', help='Relative path to Lambda function sources')
        gp.add_argument('--templates-prefix', default='cloudformation', help='S3 prefix for Cloudformation templates')
        gp.add_argument('--appconfig-prefix', default='config', help='S3 prefix for application configuration')
        gp.add_argument('--lambda-prefix', default='lambda', help='S3 prefix for Lambda function sources')

        go = opts.add_argument_group('Operation parameters')
        go.add_argument('-v', '--verbose', action='store_true', help='Be more verbose')
        go.add_argument('--cleanup-lambda', action='store_true', help='Run make clean after uploading Lambda functions')

        opts.add_argument('command', choices=['deploy', 'teardown'], help='Deploy or teardown the environment')

        return opts.parse_args()

    def setup_args(self):
        self.bucket = self.set_bucket()
        self.environment_parameters = self.read_parameters_yaml()

    def setup_logging(self):
        log.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        log.addHandler(ch)

    def format_commandline(self):
        password_args = ['--access-key', '--secret-key']
        r = list()
        mask_next = False
        for xa in sys.argv:
            if len(xa.split('=')) > 1 and xa.split('=')[0] in password_args:
                r.append('{0}=******'.format(xa.split('=')[0]))
            elif mask_next:
                r.append('******')
                mask_next = False
            else:
                r.append(xa)

            if xa in password_args:
                mask_next = True
        return ' '.join(r)

    def __init__(self):
        self.o = self.configure_args()
        self.setup_logging()
        log.info(' Commandline '.center(64, '-'))
        log.info(self.format_commandline())
        self.setup_args()

    def read_parameters_yaml(self):
        env_config_path = os.path.join(self.o.parameters_dir, f'{self.o.runtime_environment}.yaml')
        log.info(f'Loading environment parameters from {env_config_path}')
        with open(env_config_path, 'r') as f:
            return yaml.load(f, Loader=IgnoreYamlLoader)

    def set_bucket(self):
        r = s.resource('s3')
        b = r.Bucket(f'{self.o.installation_name}-{self.o.component_name}.{self.o.dns_domain}')
        v = r.BucketVersioning(b.name)
        log.info(f'Creating S3 bucket {b.name}...')
        try:
            b.create(ACL='private', CreateBucketConfiguration={'LocationConstraint': s.region_name})
            v.enable()
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                log.info(f'Bucket {b.name} exists')
        return b

    def delete_bucket(self):
        log.info(f'Deleting S3 bucket {self.bucket.name}...')
        self.bucket.objects.all().delete()
        self.bucket.delete()

    def deploy_environment(self):
        log.info(' Upload lambda code '.center(64, '-'))
        l = LambdaCollection(self.o.lambda_dir, self.bucket, self.o.lambda_prefix)
        l.prepare()
        l.upload()
        if self.o.cleanup_lambda:
            l.cleanup()

        log.info(' Loading version manifest '.center(64, '-'))
        m = VersionManifest(self.bucket, self.o.manifest)

        log.info(' Upload Application configuration '.center(64, '-'))
        c = S3RecursiveUploader(os.path.join(self.o.appconfig_dir, self.o.runtime_environment),
                self.bucket, self.o.appconfig_prefix)
        c.upload()

        log.info(' Collect and upload Cloudformation templates '.center(64, '-'))
        t = CloudformationCollection(self.o.templates_dir, self.bucket,
                self.o.templates_prefix, self.environment_parameters)
        t.upload()

        log.info(' Initialise Cloudformation environment '.center(64, '-'))
        e = CloudformationEnvironment(self.bucket, l, t, m, self.o)

        log.info(' Deploy stacks '.center(64, '-'))
        e.deploy_stacks()

    def teardown_environment(self):
        log.info(' Collect Cloudformation templates '.center(64, '-'))
        t = CloudformationCollection(self.o.templates_dir, self.bucket,
                self.o.templates_prefix, self.environment_parameters)

        log.info(' Initialise Cloudformation environment '.center(64, '-'))
        e = CloudformationEnvironment(self.bucket, None, t, None, self.o)

        log.info(' Delete stacks '.center(64, '-'))
        e.teardown_stacks()

        log.info(' Delete bucket '.center(64, '-'))
        self.delete_bucket()

    def run(self):
        if self.o.command == 'deploy':
            self.deploy_environment()
        elif self.o.command == 'teardown':
            self.teardown_environment()


if __name__ == '__main__':
    d = StackDeployer()
    d.run()
