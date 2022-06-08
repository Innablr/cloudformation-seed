#!/usr/bin/env python3
from datetime import datetime
from cloudformation_seed import util, s3_classes, lambdas, cfn_template, cfn_stack, cfn_stackset

import yaml
import os
import argparse
import logging
import sys
from colorama import init as init_colorama, Fore, Style
from string import Template
from botocore.exceptions import ClientError
from .version import VERSION

log = logging.getLogger('stack-deployer')


class StackParser(object):
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
                stacks.append(cfn_stack.CloudformationStack(self.installation_name, xt))
            elif xt.template_type == 'stackset':
                log.info(f'Adding stackset {Fore.GREEN}{xt.name}{Style.RESET_ALL}...')
                stacks.append(cfn_stackset.CloudformationStackSet(self.installation_name, xt))
        return stacks

    def find_stack_output(self, stack_name, output_name):
        try:
            return [xs.get_stack_output(output_name) for xs in self.stacks if xs.template.name == stack_name].pop()
        except IndexError:
            raise util.InvalidStackConfiguration(f'Can\'t find output {output_name} on stack {stack_name}, '
                        f'template {stack_name} is not part of the deployment') from None

    def find_template(self, template_name):
        try:
            return [f'{xt.s3_key_prefix}/{xt.s3_key}' for xt in self.templates if xt.s3_key == template_name].pop()
        except IndexError:
            raise util.InvalidStackConfiguration(f'Template {template_name} is not part of the deployment')\
                from None

    def deploy_stacks(self):
        for xs in self.stacks:
            util.log_section(f'Deploying {xs.template.template_type} {xs.stack_name}')
            p = util.StackParameters(self.s3_bucket, xs.template, self.manifest, self.options, self)
            xs.set_parameters(p)
            if xs.template.tags:
                xs.validate_tags(xs.template.tags)
            xs.deploy()
            util.log_section(f'{xs.stack_name} deployment complete')

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
        gc.add_argument('-m', '--manifest', help='S3 key of a version manifest or local path to upload')
        gc.add_argument('-p', '--param-overrides', type=self.parse_override, metavar='stack-name:VarName=value',
            nargs='+', help='Override template parameters, if stack-name omitted VarName is overriden for every stack')

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
        go.add_argument('--version', action='version', version='%(prog)s ' + VERSION, help='Print version number')

        opts.add_argument('command', choices=['deploy', 'teardown'], help='Deploy or teardown the environment')

        return opts.parse_args()

    def parse_override(self, value):
        var_name, var_value = value.split('=')
        if ':' in var_name:
            stack_name, var_name = var_name.split(':')
        else:
            stack_name = None
        return (stack_name, var_name, var_value)

    def setup_args(self):
        self.bucket = self.set_bucket()
        if self.o.org_arn is not None:
            if util.ORG_ARN_RE.match(self.o.org_arn) is None:
                raise util.InvalidParameters(f'Organisation ARN must be a valid ARN, not [{self.o.org_arn}]')
            self.set_bucket_policy()
        self.environment_parameters = self.read_parameters_yaml()

    def setup_logging(self):
        if self.o.no_color:
            init_colorama(strip=True)
        log.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.o.verbose else logging.INFO)
        if not self.o.no_color:
            ch.setFormatter(util.ColorFormatter('%(levelname)s %(message)s'))
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
                return yaml.load(f, Loader=util.IgnoreYamlLoader)
        except OSError:
            raise util.InvalidParameters(f'You have specified runtime environment {self.o.runtime_environment},'
                f' but the file {env_config_path} does not exist') from None

    def set_bucket_policy(self) -> None:
        org_id = util.ORG_ARN_RE.match(self.o.org_arn).group('org_id')
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
        r = util.session.resource('s3')
        c = util.session.client('s3')
        b = r.Bucket(f'{self.o.installation_name}-{self.o.component_name}.{self.o.dns_domain}')
        v = r.BucketVersioning(b.name)
        log.info(f'Creating S3 bucket {Fore.GREEN}{b.name}{Style.RESET_ALL}...')

        bucket_create_kwargs = {
            'ACL': 'private'
        }

        if util.session.region_name != 'us-east-1':
            bucket_create_kwargs['CreateBucketConfiguration'] = {'LocationConstraint': util.session.region_name}

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
        while len(list(self.bucket.object_versions.limit(1))) > 0:
            log.info(f'Deleting object versions in bucket {Fore.GREEN}{self.bucket.name}{Style.RESET_ALL}...')
            self.bucket.object_versions.limit(1000).delete()
        while len(list(self.bucket.objects.limit(1))) > 0:
            log.info(f'Deleting objects in bucket {Fore.GREEN}{self.bucket.name}{Style.RESET_ALL}...')
            self.bucket.objects.limit(1000).delete()
        log.info(f'Deleting S3 bucket {Fore.GREEN}{self.bucket.name}{Style.RESET_ALL}...')
        self.bucket.delete()
        log.info(f'Successfully deleted S3 bucket {Fore.GREEN}{self.bucket.name}{Style.RESET_ALL}...')

    def deploy_environment(self):
        if 'ssm-parameters' in self.environment_parameters:
            util.log_section('Set parameter values in SSM', bold=True)
            s = util.SSMParameters(self.environment_parameters['ssm-parameters'],
                                   self.o.component_name, self.o.installation_name)
            s.set_all_parameters()

        util.log_section('Upload lambda code', bold=True)
        l = lambdas.LambdaCollection(self.o.lambda_dir, self.bucket, self.o.lambda_prefix)  # noqa E741
        l.prepare()
        l.upload()
        if self.o.cleanup_lambda:
            l.cleanup()

        if self.o.manifest and os.path.exists(self.o.manifest):
            util.log_section('Uploading version manifest', bold=True)
            upload_key = f"manifests/{datetime.now().isoformat()}/manifest.json"
            s3_classes.S3Uploadable(self.o.manifest, self.bucket, upload_key).upload()
            self.o.manifest = upload_key

        util.log_section('Loading version manifest', bold=True)
        m = util.VersionManifest(self.bucket, self.o.manifest)

        util.log_section('Upload Application configuration', bold=True)
        c = s3_classes.S3RecursiveUploader(os.path.join(self.o.appconfig_dir, self.o.runtime_environment),
                self.bucket, self.o.appconfig_prefix)
        c.upload()

        util.log_section('Collect and upload Cloudformation templates', bold=True)
        t = cfn_template.CloudformationCollection(self.o.templates_dir, self.bucket,
                                                  self.o.templates_prefix, self.environment_parameters)
        t.upload()

        util.log_section('Initialise Cloudformation environment', bold=True)
        e = StackParser(self.bucket, l, t, m, self.o)

        util.log_section('Deploy stacks', bold=True)
        e.deploy_stacks()

    def teardown_environment(self):
        util.log_section('Collect Cloudformation templates', bold=True)
        t = cfn_template.CloudformationCollection(self.o.templates_dir, self.bucket,
                                                  self.o.templates_prefix, self.environment_parameters)

        util.log_section('Initialise Cloudformation environment', bold=True)
        e = StackParser(self.bucket, None, t, None, self.o)

        util.log_section('Delete stacks', bold=True)
        e.teardown_stacks()

        util.log_section('Delete bucket', bold=True)
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
