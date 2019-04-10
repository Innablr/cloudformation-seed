#!/usr/bin/env python3

from typing import Union, Dict, List, Tuple, Any, Optional, NoReturn

import re
import yaml
import boto3
import hashlib
import zipfile
import copy
import time
import os
import subprocess
import sys
import argparse
import logging
import itertools
from functools import wraps
from colorama import init as init_colorama, Fore, Style
from string import Template
from botocore.exceptions import ClientError

log = logging.getLogger('deploy-stack')


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

s = boto3.Session()


class InvalidParameters(Exception): pass            # noqa E701,E302
class InvalidStackConfiguration(Exception): pass    # noqa E701,E302
class DeploymentFailed(Exception): pass             # noqa E701,E302
class StackTemplateInvalid(Exception): pass         # noqa E701,E302


ORG_ARN_RE = re.compile('^arn:aws:organizations::\d{12}:\w+/(?P<org_id>o-\w+)')


class DirectoryScanner(object):
    def scan_directories(self, path: str) -> List[Tuple[str, str]]:
        u = list()
        for root, _, files in os.walk(path):
            relative_root = root.replace(path, '').strip(os.sep)
            u.extend([(f'{relative_root}/{f}'.replace(os.sep, '/').strip('/'), os.path.join(root, f)) for f in files])
        return u


class S3Uploadable(object):
    def __init__(self, file_path: str, s3_bucket: Any, s3_key: str, object_checksum: Optional[str] = None) -> None:
        self.file_path: str = file_path
        self.file_checksum: str = object_checksum or self.calculate_md5(self.file_path)
        self.s3_bucket: Any = s3_bucket
        self.s3_key: str = s3_key
        self.bytes: int = 0
        self.total_bytes: int = os.path.getsize(self.file_path)

    def calculate_md5(self, file_path: str) -> str:
        md5sum = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65535), b''):
                md5sum.update(chunk)
        return md5sum.hexdigest()

    def print_progress(self, current_bytes: int) -> None:
        self.bytes += current_bytes
        log.debug(f'{self.bytes} bytes out of {self.total_bytes} complete')

    def verify_existing_checksum(self) -> bool:
        etag: str = ''
        object_key: str = ''
        o = self.s3_bucket.Object(self.s3_key)
        try:
            etag = o.e_tag.strip('"')
            object_key = o.key
        except ClientError:
            log.debug(f'{self.s3_key} doesn\'t seem to exist in the bucket')
            return False
        if self.file_checksum in object_key:
            log.debug(f'Object name {self.s3_key} contains checksum {self.file_checksum}')
            return True
        if etag == self.file_checksum:
            log.debug(f'{self.s3_key} etag matches file md5sum: {self.file_checksum}')
            return True
        log.debug(f'Checksum {self.file_checksum} doesn\'t match object {object_key} etag {etag}')
        return False

    def upload(self) -> None:
        if self.verify_existing_checksum():
            log.info(f'Object in S3 is identical to {Fore.GREEN}{self.file_path}{Style.RESET_ALL}, skipping upload')
            return
        log.info(f'Uploading {Fore.GREEN}{self.file_path}{Style.RESET_ALL} '
            f'into {Fore.GREEN}{self.s3_url}{Style.RESET_ALL}')
        self.s3_bucket.upload_file(self.file_path, self.s3_key, Callback=self.print_progress)

    @property
    def s3_url(self):
        return f'{s.client("s3").meta.endpoint_url}/{self.s3_bucket.name}/{self.s3_key}'


class S3RecursiveUploader(DirectoryScanner):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.s3_bucket: Any = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        log.info(f'Scanning files in {Fore.GREEN}{path}{Style.RESET_ALL}...')
        self.u = [S3Uploadable(f, self.s3_bucket, f'{self.s3_key_prefix}/{k}')
            for k, f in self.scan_directories(path)]

    def upload(self) -> None:
        for xu in self.u:
            xu.upload()


class LambdaFunction(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.path: str = path
        self.s3_bucket: str = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        self.zip_file: Optional[str] = None
        self.zip_checksum: Optional[str] = None
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

    def checksum_zipfile(self) -> str:
        sha1sum = hashlib.sha1()
        with zipfile.ZipFile(os.path.join(self.path, self.zip_file), 'r') as f:
            for xc in sorted([xf.CRC for xf in f.filelist]):
                sha1sum.update(xc.to_bytes((xc.bit_length() + 7) // 8, 'big') or b'\0')
        return sha1sum.hexdigest()

    def prepare(self) -> None:
        log.info(f'Running make in {Fore.GREEN}{self.path}{Style.RESET_ALL}...')
        try:
            m = subprocess.run(['make'], check=True, cwd=self.path, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, encoding='utf-8')
            log.debug('Make output will follow:')
            log.debug('-' * 64)
            log.debug(m.stdout)
            log.debug('-' * 64)
        except subprocess.CalledProcessError as e:
            log.error(f'Make failed in {self.path}, make output will follow:')
            log.error('-' * 64)
            log.error(e.stdout)
            log.error('-' * 64)
            log.error('Aborting deployment')
            raise DeploymentFailed(f'Make failed in {self.path}') from None
        self.zip_file = self.find_lambda_zipfile()
        self.zip_checksum = self.checksum_zipfile()
        self.u = S3Uploadable(os.path.join(self.path, self.zip_file), self.s3_bucket,
            f'{self.s3_key_prefix}/{self.zip_checksum}-{self.zip_file}', self.zip_checksum)

    def upload(self) -> None:
        self.u.upload()

    def cleanup(self) -> None:
        log.info(f'Running make clean in {Fore.GREEN}{self.path}{Style.RESET_ALL}...')
        subprocess.run(['make', 'clean'], cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LambdaCollection(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.s3_bucket: Any = s3_bucket
        self.lambdas: List[LambdaFunction] = list()
        if os.path.isdir(path):
            self.lambdas = [LambdaFunction(os.path.join(path, x), self.s3_bucket, s3_key_prefix)
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
            raise InvalidStackConfiguration(f'Lambda function bundle {zip_name} not found') from None


class CloudformationTemplateBody:
    def __init__(self, template_text: str) -> None:
        self.text = template_text
        self.checksum = self.calculate_checksum(self.text)
        self.body: Dict[str, Any] = yaml.load(template_text, Loader=IgnoreYamlLoader)

    @property
    def parameters(self) -> Dict[str, Dict[str, str]]:
        return self.body['Parameters']

    def calculate_checksum(self, text) -> str:
        sha1sum = hashlib.sha1()
        sha1sum.update(bytes(self.text, 'utf-8'))
        return sha1sum.hexdigest()


class CloudformationTemplate(object):
    def __init__(self, s3_bucket: Any, template_key: str, s3_key_prefix: str,
                    file_path: str, template_parameters: Dict[str, Any]) -> None:
        self.template_key: str = template_key
        self.template_parameters: Dict[str, Any] = template_parameters
        self.template_body: CloudformationTemplateBody = self.load_template(file_path)
        self.s3_key_prefix: str = s3_key_prefix
        self.s3_key: str = self.build_s3_key(self.template_key, self.template_checksum)
        self.u: S3Uploadable = S3Uploadable(file_path, s3_bucket, f'{self.s3_key_prefix}/{self.s3_key}')

    @property
    def name(self) -> str:
        return self.template_parameters['name']

    @property
    def template(self) -> str:
        return self.template_parameters['template']

    @property
    def template_checksum(self) -> str:
        return self.template_body.checksum

    @property
    def template_type(self) -> str:
        return self.template_parameters.get('type', 'stack')

    @property
    def template_s3_key(self) -> str:
        return self.u.s3_key

    @property
    def template_url(self) -> str:
        return self.u.s3_url

    def build_s3_key(self, template_key, template_checksum) -> str:
        if self.template_parameters.get('predictable_name', False) is True:
            return template_key
        return '/'.join([os.path.dirname(template_key),
            f'{template_checksum}-{os.path.basename(template_key)}']).strip('/')

    def load_template(self, file_path: str) -> CloudformationTemplateBody:
        log.info(f'Loading template for stack {Fore.GREEN}{self.name}{Style.RESET_ALL} '
            f'from {Fore.GREEN}{file_path}{Style.RESET_ALL}...')
        with open(file_path, 'r') as f:
            return CloudformationTemplateBody(f.read())

    def upload(self) -> None:
        self.u.upload()


class CloudformationCollection(DirectoryScanner):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str,
                    environment_parameters: Dict['str', Any]) -> None:
        self.s3_bucket: Any = s3_bucket
        self.environment_parameters: Dict['str', Any] = environment_parameters
        self.template_files: List[Tuple[str, str]] = self.scan_directories(path)
        log_section('Collecting templates included in the environment')
        self.templates: List[CloudformationTemplate] = [
            CloudformationTemplate(
                self.s3_bucket,
                xs['template'],
                s3_key_prefix,
                self.find_template_file(xs['template']),
                xs
            ) for xs in self.environment_parameters.get('stacks', list())
        ]
        log_section('Collecting templates not included in the environment')
        for xf in self.template_files:
            if len([xt for xt in self.templates if xt.template_key == xf[0]]) > 0:
                continue
            self.templates.append(CloudformationTemplate(
                self.s3_bucket,
                xf[0],
                s3_key_prefix,
                xf[1],
                {
                    'name': xf[0],
                    'template': xf[0]
                })
            )
        log_section('Done collecting templates')

    def list_deployable(self) -> List[CloudformationTemplate]:
        u = list()
        for xs in self.environment_parameters.get('stacks', list()):
            try:
                if xs.get('deployable', True) is False:
                    log.info(f'Stack {Fore.GREEN}{xs.get("name")}{Style.RESET_ALL} is not deployable, skipping')
                    continue
                stack_template = [xt for xt in self.templates if xt.name == xs.get('name')].pop()
                u.append(stack_template)
            except IndexError:
                raise InvalidStackConfiguration(f'Template not found for {xs.get("name")}') from None
        return u

    def find_template(self, template_name: str) -> CloudformationTemplate:
        try:
            return [x for x in self.templates if x.template == template_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Template {template_name} not found in this deployment') from None

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
            log.warning('No version manifest supplied, artifact tags are not supported for this deployment')
            return self.default_manifest()
        log.info(f'Loading version manifest from {Fore.GREEN}s3://{s3_bucket.name}/{s3_key}{Style.RESET_ALL}')
        o = s3_bucket.Object(s3_key)
        r: Dict[str, Any] = o.get()
        m: Dict[str, Any] = yaml.load(r['Body'])
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
        c = s.client('ssm')
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

        self.parameters_loader = self.configure_parameters_loader()
        self.STACK_OUTPUT_RE = \
            re.compile('^(?P<stack_name>[^\.]+)\.(?P<output_name>[^\.:]+)(:(?P<default_value>.*))?$')

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
        self.operation_preferences: Dict[str, Union[str, List[str]]] = \
                self.stack_definition.get('operation_preferences', {})
        self.rollout = self.format_rollout()

    def format_rollout(self):
        c = s.client('cloudformation')
        if 'rollout' not in self.stack_definition:
            return None
        rollout = self.stack_definition['rollout']
        for xr in rollout:
            xr['regions'] = set(xr.get('regions', {c.meta.region_name}))
            xr['override'] = [{'ParameterKey': k, 'ParameterValue': str(v)}
                for k, v in xr.get('override', dict()).items() if v is not None]
        return rollout

    def configure_parameters_loader(self):
        class ParametersLoader(yaml.Loader):
            pass
        ParametersLoader.add_constructor('!Builtin', self.set_builtin)
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

    def set_builtin(self, loader, node):
        param_name = loader.construct_scalar(node)
        log.debug(f'Setting parameter {param_name}...')
        val = self.get_special_parameter_value(param_name)
        if val is None:
            raise InvalidStackConfiguration(f'Unsupported builtin parameter [{param_name}]')
        return val

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
        c = s.client('ssm')
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
            return yaml.load(f, Loader=self.parameters_loader)

    def compute_parameter_value(self, param_name):
        common_val = self.common_parameters.get(param_name)
        specific_val = self.specific_parameters.get(param_name)
        for source, xv in (('SPECIFIC', specific_val), ('COMMON', common_val),
                ('BUILTIN', self.get_special_parameter_value(param_name)), ('ABSENT', None)):
            if xv is not None or source == 'ABSENT':
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
        return {'OperationPreferences': prefs}


class CloudformationStack(object):

    def __init__(self, installation_name: str, template: CloudformationTemplate) -> None:
        self.template: CloudformationTemplate = template
        self.stack_name = f'{installation_name}-{self.template.name}'
        self.stack_parameters = None
        self.existing_stack = self.find_existing_stack()
        self.caps = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND']
        self.stack = None

    def set_parameters(self, parameters: StackParameters) -> None:
        self.stack_parameters = parameters

    def find_existing_stack(self) -> Optional[Dict[str, Any]]:
        c = s.client('cloudformation')
        try:
            r = c.describe_stacks(StackName=self.stack_name)
            log.info(f'Stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} exists')
            return r['Stacks'].pop()
        except Exception:
            log.info(f'Stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} does not exist')
            return None

    def get_stack_output(self, output_name: str) -> Optional[str]:
        if self.stack is None:
            log.debug(f'Can\'t find output {self.stack_name}.{output_name}, stack has not been yet deployed')
            return None
        for xo in self.stack.outputs:
            if xo['OutputKey'] == output_name:
                log.debug(f'Output {self.stack_name}.{output_name} = {xo["OutputValue"]}')
                return xo['OutputValue']

    def create_stack(self) -> None:
        c = s.client('cloudformation')
        log.info(f'Creating stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        c.create_stack(
            StackName=self.stack_name,
            TemplateURL=self.template.template_url,
            Parameters=self.stack_parameters.format_parameters(),
            DisableRollback=True,
            Capabilities=self.caps
        )
        self.wait('stack_create_complete')
        self.retrieve()

    def update_stack(self) -> None:
        c = s.client('cloudformation')
        p = self.stack_parameters.format_parameters()
        log.info(f'Updating stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        log.debug(' Parameters '.center(48, '-'))
        log.debug(p)
        log.debug('-'.center(48, '-'))
        try:
            c.update_stack(
                StackName=self.stack_name,
                TemplateURL=self.template.template_url,
                Parameters=p,
                Capabilities=self.caps
            )
            self.wait('stack_update_complete')
        except ClientError as e:
            if e.response['Error']['Message'] == 'No updates are to be performed.':
                log.info(f'No updates are to be done on stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL}')
            else:
                raise
        self.retrieve()

    def deploy(self) -> None:
        if self.existing_stack is None:
            self.create_stack()
        else:
            self.update_stack()

    def teardown(self) -> None:
        if self.existing_stack is None:
            log.warning(f'Stack {self.stack_name} does not exist. Skipping.')
            return
        c = s.client('cloudformation')
        log.info(f'Deleting stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL}...')
        c.delete_stack(StackName=self.stack_name)
        self.wait('stack_delete_complete')

    def wait(self, event: str) -> None:
        log.info('Waiting for operation to finish...')
        c = s.client('cloudformation')
        waiter = c.get_waiter(event)
        try:
            waiter.wait(StackName=self.stack_name)
        except Exception as e:
            self.retrieve()
            raise DeploymentFailed(f'Stack {self.stack_name} deployment failed: {str(e)}') from None

    def retrieve(self) -> None:
        r = s.resource('cloudformation')
        self.stack = r.Stack(self.stack_name)
        log.info(f'Found stack {Fore.GREEN}{self.stack.stack_name}{Style.RESET_ALL} '
            f'in status {Fore.MAGENTA}{self.stack.stack_status}{Style.RESET_ALL}')


class StackSetRollout:
    def __init__(self, stack_name, rollout_config):
        self.stack_name = stack_name
        self.rollout_config = rollout_config
        self.stack_instances = None
        self.create = list()
        self.update = list()
        self.delete = list()

    def retrieve(self) -> None:
        c = s.client('cloudformation')
        log.info('Loading stack instances...')
        r = c.list_stack_instances(StackSetName=self.stack_name)
        self.stack_instances = dict()
        for xi in r['Summaries']:
            self.stack_instances.setdefault(xi['Account'], set()).add(xi['Region'])
        log.info(f'Found {Fore.GREEN}{sum(len(xv) for xv in self.stack_instances.values())}{Style.RESET_ALL} '
            f'stack instances in {Fore.MAGENTA}{len(self.stack_instances)}{Style.RESET_ALL} accounts')

    def find_or_add_account(self, where, account):
        coll = self.create if where == 'create' else self.update
        matches = [xa for xa in coll if xa['account'] == account['account'] and xa['override'] == account['override']]
        try:
            return matches[0]
        except IndexError:
            new_account = copy.copy(account)
            new_account['regions'] = set()
            coll.append(new_account)
            return new_account

    def region_need_update(self, account_id, region, overrides):
        c = s.client('cloudformation')
        r = c.describe_stack_instance(
            StackSetName=self.stack_name,
            StackInstanceAccount=account_id,
            StackInstanceRegion=region
        )
        current_overrides = [{'ParameterKey': xo['ParameterKey'], 'ParameterValue': xo['ParameterValue']}
            for xo in r['StackInstance']['ParameterOverrides']]
        if sorted(current_overrides, key=lambda x: x['ParameterKey']) != \
                sorted(overrides, key=lambda x: x['ParameterKey']):
            log.info('Parameter overrides are changing in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} in region {region}')
            return True
        if r['StackInstance']['Status'] != 'CURRENT':
            log.info(f'Stackset instance is {Fore.MAGENTA}NOT CURRENT{Style.RESET_ALL} in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} in region {region}')
            return True
        return False

    def set_create_or_update_account(self, account) -> None:
        account_id = account['account']
        if account_id not in self.stack_instances and len(account['regions']) > 0:
            log.debug(f'Stackset will create instances in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} regions '
                f'{Fore.GREEN}{account["regions"]}{Style.RESET_ALL}')
            self.create.append(copy.copy(account))
            return
        for region in account['regions']:
            if region in self.stack_instances[account_id]:
                if not self.region_need_update(account_id, region, account['override']):
                    log.info(f'Stack instance in account '
                        f'{Fore.GREEN}{account_id}{Style.RESET_ALL} '
                        f'region {Fore.GREEN}{region}{Style.RESET_ALL} is not updating')
                    continue
                log.debug(f'Stackset will update instance in account {account_id} region {region}')
                rollout_account = self.find_or_add_account('update', account)
            else:
                log.debug(f'Stackset will create instance in account {account_id} region {region}')
                rollout_account = self.find_or_add_account('create', account)
            rollout_account['regions'].add(region)

    def set_delete_account(self, account, regions) -> None:
        rollout_accounts = [xa for xa in self.rollout_config if xa['account'] == account]
        rollout_regions = set.union(*[xa['regions'] for xa in rollout_accounts]) if len(rollout_accounts) > 0 else set()
        delete_regions = regions - rollout_regions
        if len(delete_regions) > 0:
            log.debug(f'Account {account} is set for deletion in regions {delete_regions}')
            self.delete.append({
                'account': account,
                'regions': delete_regions,
                'override': dict()
            })

    def collate_instances_create_update(self):
        self.create.clear()
        self.update.clear()
        self.retrieve()
        for rollout_account in self.rollout_config:
            self.set_create_or_update_account(rollout_account)

    def collate_instances_delete(self):
        self.delete.clear()
        self.retrieve()
        for account, regions in self.stack_instances.items():
            self.set_delete_account(account, regions)

    def calculate_overrides_checksum(self, account):
        if len(account['override']) == 0:
            return '-'
        sha1sum = hashlib.sha1()
        for item in sorted(account['override'],
                key=lambda x: '{ParameterKey}-{ParameterValue}'.format_map(x)):
            sha1sum.update(bytes(repr(item), 'utf-8'))
        return sha1sum.hexdigest()

    def rank_sets(self, a):
        ranking = list()
        for i in range(len(a), 1, -1):
            for subset in itertools.combinations(sorted(a), i):
                intersected = set.intersection(*(a[k] for k in subset))
                if len(intersected) > 0:
                    if intersected not in ranking:
                        ranking.append(intersected)
                else:
                    for k in subset:
                        if a[k] not in ranking:
                            ranking.append(a[k])
        return sorted(ranking, reverse=True, key=lambda x: len(x))

    def compute_deployment(self, initial, xset):
        new = dict()
        deployment = {
            'accounts': list(),
            'regions': xset
        }
        for account, regions in initial.items():
            if regions >= xset:
                deployment['accounts'].append(account)
                if len(regions - xset) > 0:
                    new[account] = regions - xset
            else:
                new[account] = regions
        return deployment, new

    def generate_deployments(self, rollout):
        while len(rollout) > 1:
            costed_sets = []
            for xs in self.rank_sets(rollout):
                if len(xs) > 0:
                    d, r0 = self.compute_deployment(rollout, xs)
                    cost = sum(1 for _ in self.generate_deployments(r0))
                    costed_sets.append((cost, xs))
            winner = sorted(costed_sets, key=lambda x: x[0])[0]
            d, rollout = self.compute_deployment(rollout, winner[1])
            yield d
        for account, regions in rollout.items():
            yield {
                'accounts': [account],
                'regions': regions
            }

    def grouped_rollout(self, coll):
        deployments = list()
        for _, group in itertools.groupby(sorted(coll, key=self.calculate_overrides_checksum),
                self.calculate_overrides_checksum):
            group_list = list(group)
            deployment = {
                'override': group_list[0]['override'],
                'accounts': list()
            }
            deployment_accounts = dict()
            for xd in group_list:
                deployment_accounts.setdefault(xd['account'], set()).update(xd['regions'])
            for xd in self.generate_deployments(deployment_accounts):
                deployment['accounts'].append(xd)
            deployments.append(deployment)
        return deployments

    def rollout_delete(self):
        self.collate_instances_delete()
        return self.grouped_rollout(self.delete)

    def rollout_create_update(self):
        self.collate_instances_create_update()
        return self.grouped_rollout(self.create), self.grouped_rollout(self.update)


class CloudformationStackSet(object):
    def __init__(self, installation_name: str, template: CloudformationTemplate) -> None:
        self.template: CloudformationTemplate = template
        self.stack_name: str = f'{installation_name}-{self.template.name}'
        self.stack_parameters: Optional[StackParameters] = None
        self.existing_stack: Optional[Dict[str, Any]] = self.find_existing_stackset()
        self.caps = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND']
        self.stack = None
        self.stackset_rollout: Optional[StackSetRollout] = None

    def retry_pending(f):
        @wraps(f)
        def wrapper(self, *args, **kwargs):
            while True:
                try:
                    return f(self, *args, **kwargs)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'OperationInProgressException':
                        log.warning(f'Operation is in progress on stackset {self.stack_name}, retrying after wait...')
                        self.wait_pending_operations()
                        log.warning('Retrying operation')
                    else:
                        raise
        return wrapper

    def set_parameters(self, parameters: StackParameters) -> None:
        self.stack_parameters = parameters
        if self.stack_parameters.rollout is not None:
            self.stackset_rollout = StackSetRollout(self.stack_name, self.stack_parameters.rollout)

    def find_existing_stackset(self) -> Optional[Dict[str, Any]]:
        c = s.client('cloudformation')
        try:
            r = c.describe_stack_set(StackSetName=self.stack_name)
            stackset = r['StackSet']
            log.info(f'Found stackset {Fore.GREEN}{stackset["StackSetName"]}{Style.RESET_ALL} '
                f'in status {Fore.MAGENTA}{stackset["Status"]}{Style.RESET_ALL}')
            return stackset
        except Exception:
            log.info(f'Stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} does not exist')
            return None

    def get_stack_output(self, output_name: str) -> NoReturn:
        raise InvalidStackConfiguration(f'Can\'t retrieve output {output_name} of stackset {self.stack_name}'
                                        f', stacksets don\'t have outputs. Please review your configuration')

    @retry_pending
    def create_stackset(self) -> None:
        c = s.client('cloudformation')
        params: Dict[str, Any] = {
            'StackSetName': self.stack_name,
            'TemplateURL': self.template.template_url,
            'Parameters': self.stack_parameters.format_parameters(),
            'Capabilities': self.caps
        }
        params.update(self.stack_parameters.format_role_pair())
        log.info(f'Creating stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        c.create_stack_set(**params)
        self.wait_pending_operations()

    def stackset_need_update(self) -> bool:
        current_parameters: List[Dict[str, str]] = \
            [{'ParameterKey': xo['ParameterKey'], 'ParameterValue': xo['ParameterValue']}
                for xo in self.existing_stack['Parameters']]
        log.debug('>> Current parameters')
        log.debug(current_parameters)
        log.debug('>> New parameters')
        log.debug(self.stack_parameters.format_parameters())
        parameters_changed: bool = sorted(current_parameters, key=lambda x: x['ParameterKey']) != \
            sorted(self.stack_parameters.format_parameters(), key=lambda x: x['ParameterKey'])
        log.info('Parameters are {color}{is_changing}{color_reset} for stackset {color}{stackset_name}{color_reset}'
            .format(is_changing='changing' if parameters_changed else 'not changing',
                stackset_name=self.stack_name,
                color=Fore.GREEN,
                color_reset=Style.RESET_ALL))
        template_changed: bool = \
            CloudformationTemplateBody(self.existing_stack['TemplateBody']).checksum != self.template.template_checksum
        log.info('Template is {color}{is_changing}{color_reset} for stackset {color}{stackset_name}{color_reset}'
            .format(is_changing='changing' if template_changed else 'not changing',
                stackset_name=self.stack_name,
                color=Fore.GREEN,
                color_reset=Style.RESET_ALL))
        return parameters_changed or template_changed

    @retry_pending
    def update_stackset(self) -> None:
        if not self.stackset_need_update():
            log.info('No changes to stackset template or parameters. Skipping stackset update')
            return

        p = self.stack_parameters.format_parameters()
        c = s.client('cloudformation')
        log.info(f'Updating stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        log.debug(' Parameters '.center(48, '-'))
        log.debug(p)
        log.debug('-'.center(48, '-'))
        params = {
            'StackSetName': self.stack_name,
            'TemplateURL': self.template.template_url,
            'Parameters': p,
            'Capabilities': self.caps,
        }
        params.update(self.stack_parameters.format_role_pair())
        params.update(self.stack_parameters.format_operation_preferences())
        c.update_stack_set(**params)
        self.wait_pending_operations()

    def deploy(self) -> None:
        if self.existing_stack is None:
            self.create_stackset()
        else:
            self.cleanup_stack_instances()
            self.update_stackset()
        self.stack = self.find_existing_stackset()
        self.rollout_accounts()

    @retry_pending
    def cleanup_stack_instances(self) -> None:
        c = s.client('cloudformation')
        if self.stackset_rollout is None:
            log.info('Rollout configuration is missing, not cleaning up stack instances')
            return
        delete_groups = self.stackset_rollout.rollout_delete()
        log.debug(f'Delete instances: {delete_groups}')
        for xg in delete_groups:
            for xd in xg['accounts']:
                log.info(f'Deleting stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'RetainStacks': False
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.delete_stack_instances(**params)
                self.wait_pending_operations()

    @retry_pending
    def rollout_accounts(self) -> None:
        c = s.client('cloudformation')
        if self.stackset_rollout is None:
            log.info('Rollout configuration is missing, not deploying stack instances')
            return
        create_groups, update_groups = self.stackset_rollout.rollout_create_update()
        log.debug(f'Update instances: {update_groups}')
        log.debug(f'Create instances: {create_groups}')
        for xg in create_groups:
            for xd in xg['accounts']:
                log.info(f'Creating new stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'ParameterOverrides': xg['override']
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.create_stack_instances(**params)
                self.wait_pending_operations()
        for xg in update_groups:
            for xd in xg['accounts']:
                log.info(f'Updating stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'ParameterOverrides': xg['override']
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.update_stack_instances(**params)
                self.wait_pending_operations()

    @retry_pending
    def wipe_out_stackset_instances(self) -> None:
        c = s.client('cloudformation')
        i = c.list_stack_instances(StackSetName=self.stack_name)
        for account, group in itertools.groupby(sorted(i['Summaries'],
                key=lambda x: x['Account']), lambda x: x['Account']):
            regions = [xg['Region'] for xg in group]
            log.info(f'Deleting stack instance in account {account} regions {regions}...')
            c.delete_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account],
                Regions=regions,
                RetainStacks=False,
                OperationPreferences={
                    'MaxConcurrentPercentage': 100
                }
            )
            self.wait_pending_operations()

    @retry_pending
    def delete_stackset(self) -> None:
        c = s.client('cloudformation')
        log.info(f'Deleting stackset {self.stack_name}...')
        c.delete_stack_set(StackSetName=self.stack_name)

    def teardown(self) -> None:
        if self.existing_stack is None:
            log.info(f'StackSet {self.stack_name} does not exist. Skipping.')
            return
        self.wipe_out_stackset_instances()
        self.delete_stackset()

    def wait_pending_operations(self) -> None:
        c = s.client('cloudformation')
        try:
            time.sleep(1)
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
                log.info(f'Adding stack {Fore.GREEN}{xt.name}{Style.RESET_ALL}...')
                stacks.append(CloudformationStack(self.installation_name, xt))
            elif xt.template_type == 'stackset':
                log.info(f'Adding stackset {Fore.GREEN}{xt.name}{Style.RESET_ALL}...')
                stacks.append(CloudformationStackSet(self.installation_name, xt))
        return stacks

    def find_stack_output(self, stack_name, output_name):
        try:
            return [xs.get_stack_output(output_name) for xs in self.stacks if xs.template.name == stack_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Can\'t find output {output_name} on stack {stack_name}, '
                        f'template {stack_name} is not part of the deployment') from None

    def find_template(self, template_name):
        try:
            return [f'{xt.s3_key_prefix}/{xt.s3_key}' for xt in self.templates if xt.s3_key == template_name].pop()
        except IndexError:
            raise InvalidStackConfiguration(f'Template {template_name} is not part of the deployment') from None

    def deploy_stacks(self):
        for xs in self.stacks:
            log_section(f'Deploying {xs.template.template_type} {xs.stack_name}')
            p = StackParameters(self.s3_bucket, xs.template, self.manifest, self.options, self)
            xs.set_parameters(p)
            xs.deploy()
            log_section(f'{xs.stack_name} deployment complete')

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
        gc.add_argument('-o', '--org-arn', help='AWS Organisation ARN to allow S3 bucket access')
        gc.add_argument('-m', '--manifest', help='S3 key of a version manifest')

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
        go.add_argument('--no-color', action='store_true', help='Strip colors for basic terminals')
        go.add_argument('--cleanup-lambda', action='store_true', help='Run make clean after uploading Lambda functions')

        opts.add_argument('command', choices=['deploy', 'teardown'], help='Deploy or teardown the environment')

        return opts.parse_args()

    def setup_args(self):
        self.bucket = self.set_bucket()
        if self.o.org_arn is not None:
            if ORG_ARN_RE.match(self.o.org_arn) is None:
                raise InvalidParameters(f'Organisation ARN must be a valid ARN, not [{self.o.org_arn}]')
            self.set_bucket_policy()
        self.environment_parameters = self.read_parameters_yaml()

    def setup_logging(self):
        if self.o.no_color:
            init_colorama(strip=True)
        log.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        if not self.o.no_color:
            ch.setFormatter(ColorFormatter('%(levelname)s %(message)s'))
        else:
            ch.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        log.addHandler(ch)

    def __init__(self):
        self.o = self.configure_args()
        self.setup_logging()
        log.info(f'{Fore.CYAN} >> Cloudformation Seed >> '
            f'Orchestrates large Cloudformation deployments >> {Style.RESET_ALL}')
        log.info(' '.join(sys.argv))
        try:
            self.setup_args()
        except Exception as e:
            log.exception(str(e), exc_info=False)
            sys.exit(4)

    def read_parameters_yaml(self):
        env_config_path = os.path.join(self.o.parameters_dir, f'{self.o.runtime_environment}.yaml')
        log.info(f'Loading environment parameters from {Fore.GREEN}{env_config_path}{Style.RESET_ALL}')
        try:
            with open(env_config_path, 'r') as f:
                return yaml.load(f, Loader=IgnoreYamlLoader)
        except OSError:
            raise InvalidParameters(f'You have specified runtime environment {self.o.runtime_environment},'
                f' but the file {env_config_path} does not exist') from None

    def set_bucket_policy(self) -> None:
        org_id = ORG_ARN_RE.match(self.o.org_arn).group('org_id')
        policy_template = Template('''
        { "Version": "2012-10-17", "Statement": [ {
            "Sid": "ReadTemplatesBucket",
            "Effect": "Allow",
            "Principal": { "AWS": "*" },
            "Action": ["s3:GetObject","s3:ListBucket"],
            "Resource": ["arn:aws:s3:::${bucket_name}/*","arn:aws:s3:::${bucket_name}"],
            "Condition": {"StringEquals":
                {"aws:PrincipalOrgID": [ "${aws_org_id}" ]}
            }
        } ] }
        ''')
        policy_text = policy_template.substitute(bucket_name=self.bucket.name, aws_org_id=org_id).strip()
        log.info(f'Allowing access to the bucket for AWS Organization {Fore.GREEN}{self.o.org_arn}{Style.RESET_ALL}...')
        log.debug("Policy text will follow...")
        log.debug(policy_text)
        p = self.bucket.Policy()
        p.put(Policy=policy_text)

    def set_bucket(self):
        r = s.resource('s3')
        c = s.client('s3')
        b = r.Bucket(f'{self.o.installation_name}-{self.o.component_name}.{self.o.dns_domain}')
        v = r.BucketVersioning(b.name)
        log.info(f'Creating S3 bucket {Fore.GREEN}{b.name}{Style.RESET_ALL}...')

        bucket_create_kwargs = {
          'ACL': 'private',
        }
        if (s.region_name != 'us-east-1'):
            bucket_create_kwargs['CreateBucketConfiguration'] = {'LocationConstraint': s.region_name}

        try:
            b.create(**bucket_create_kwargs)
            v.enable()
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                log.info(f'Bucket {Fore.GREEN}{b.name}{Style.RESET_ALL} exists, reusing')
            else:
                log.warning(f'Bucket {Fore.GREEN}{b.name}{Style.RESET_ALL} creation failed!')

        c.put_bucket_encryption(
            Bucket=b.name,
            ServerSideEncryptionConfiguration={
                'Rules': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]
            }
        )
        return b

    def delete_bucket(self):
        log.info(f'Deleting S3 bucket {Fore.GREEN}{self.bucket.name}{Style.RESET_ALL}...')
        self.bucket.objects.all().delete()
        self.bucket.delete()

    def deploy_environment(self):
        if 'ssm-parameters' in self.environment_parameters:
            log_section('Set parameter values in SSM', bold=True)
            s = SSMParameters(self.environment_parameters['ssm-parameters'],
                self.o.component_name, self.o.installation_name)
            s.set_all_parameters()

        log_section('Upload lambda code', bold=True)
        l = LambdaCollection(self.o.lambda_dir, self.bucket, self.o.lambda_prefix)  # noqa E741
        l.prepare()
        l.upload()
        if self.o.cleanup_lambda:
            l.cleanup()

        log_section('Loading version manifest', bold=True)
        m = VersionManifest(self.bucket, self.o.manifest)

        log_section('Upload Application configuration', bold=True)
        c = S3RecursiveUploader(os.path.join(self.o.appconfig_dir, self.o.runtime_environment),
                self.bucket, self.o.appconfig_prefix)
        c.upload()

        log_section('Collect and upload Cloudformation templates', bold=True)
        t = CloudformationCollection(self.o.templates_dir, self.bucket,
                self.o.templates_prefix, self.environment_parameters)
        t.upload()

        log_section('Initialise Cloudformation environment', bold=True)
        e = CloudformationEnvironment(self.bucket, l, t, m, self.o)

        log_section('Deploy stacks', bold=True)
        e.deploy_stacks()

    def teardown_environment(self):
        log_section('Collect Cloudformation templates', bold=True)
        t = CloudformationCollection(self.o.templates_dir, self.bucket,
                self.o.templates_prefix, self.environment_parameters)

        log_section('Initialise Cloudformation environment', bold=True)
        e = CloudformationEnvironment(self.bucket, None, t, None, self.o)

        log_section('Delete stacks', bold=True)
        e.teardown_stacks()

        log_section('Delete bucket', bold=True)
        self.delete_bucket()

    def run(self):
        try:
            if self.o.command == 'deploy':
                self.deploy_environment()
            elif self.o.command == 'teardown':
                self.teardown_environment()
        except Exception as e:
            log.exception(str(e), exc_info=self.o.verbose)
            log.error('Aborting deployment')
            sys.exit(8)
