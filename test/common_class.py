from deploy_stack.deploy_stack import StackDeployer
from unittest.mock import patch, Mock
import sys
import logging
from moto import mock_s3
import boto3


class CommonClass():
    @mock_s3
    def __moto_setup(self):
        """
        Simulate s3
        """
        r = boto3.resource('s3')
        b = r.Bucket(f'Hello')
        v = r.BucketVersioning(b.name)
        b.create(ACL='private', CreateBucketConfiguration={'LocationConstraint': 'ap-southeast-2'})
        v.enable()
        return b

    def __init__(self, mock_session):
        self.mock_session = mock_session
        self.bucket = 'static'
        self.key = 'style.css'
        self.value = 'value'

    def _bucket(self):
        return self.__moto_setup()

    def load_init(self, operation):
        logging.disable(logging.CRITICAL)
        testargs = ["PassArgs", "-i", "test-stack", "-e", "prod",
                    "-d", "test.unit.cld", "--parameters-dir", "test/parameters",
                    "--templates-dir", "test/cloudformation", "--lambda-dir", "test/src", operation]
        with patch.object(sys, 'argv', testargs):
            deploy_stack_object = StackDeployer()
        return deploy_stack_object


class Options:
    def __init__(self):
        self.installation_name = 'rco'
        self.component_name = 'generic-ops'
        self.dns_domain = 'test.innablr.cld'
        self.org_arn = None
        self.runtime_environment = 'prod'
        self.parameters_dir = 'test/parameters'


class CloudformationEnvironment():
    @patch('deploy_stack.deploy_stack.s')
    def __init__(self, mock_session):
        self.s3_bucket = CommonClass(mock_session)._bucket
        self.installation_name = Options().installation_name
        self.dns_domain = Options().dns_domain
        self.runtime_environment = Options().runtime_environment
        self.templates = CloudformationCollection()
        self.parameters_dir = Options().parameters_dir


class CloudformationCollection():
    @patch('deploy_stack.deploy_stack.s')
    def __init__(self, mock_session):
        self.s3_bucket = CommonClass(mock_session)._bucket
        self.environment_parameters = {'ssm-parameters': {'RootServicesAccountId': '24234234324234',
        'SharedServicesAccountId': '13123123123',
         'LoggingAccountId': '1232144325235'},
         'AllConnectedAccounts':
         'arn:aws:iam::000000000000:root, arn:aws:iam::111111111111:root,arn:aws:iam::222222222222:root',
         'stacks': [{'name': 'my-project-kms-decrypt-lambda', 'template': 'support/kms-parameters-lambda.cf.yaml',
         'parameters': {'LambdaSourceS3Key': 'kmsParameters.zip'}}]}
        self.template_files = [('support/kms-parameters-lambda.cf.yaml',
        'test/cloudformation/support/kms-parameters-lambda.cf.yaml')]
        self.templates = CloudformationTemplate()

    def find_template(self, template_name: str):
        d = {'template_url': 'kms-parameters-lambda.cf.yaml', 'template_s3_key ': 'myS3Key'}
        return Mock(**d)


class CloudformationTemplate():
    def __init__(self):
        self.template_key: str = 'support/kms-parameters-lambda.cf.yaml'
        self.template_parameters = {'name': 'my-project-kms-decrypt-lambda',
        'template': 'support/kms-parameters-lambda.cf.yaml',
        'parameters': {'LambdaSourceS3Key': 'kmsParameters.zip'}}
        self.template_body = CloudformationTemplateBody()
        self.s3_key_prefix: str = 'cloudformation'
        self.s3_key: str = 'support/7d413e7a42238ddb5eb35ef3c4d08c5c717a5e5b-kms-parameters-lambda.cf.yaml'
        self.u = 'False'


class CloudformationTemplateBody():
    def __init__(self) -> None:
        self.text = 'Testing'
        self.checksum = '213123123123'
        self.body = {'Key': 'Value'}


class StackParameters():
    def __init__(self) -> None:
        self.bucket = 'Test'

    def format_parameters(self):
        d = {'ParameterKey': 'Test', 'ParameterValue': 'Success'}
        return Mock(**d)


class Template():
    def __init__(self):
        self.name = 'logging-set'
        self.template_type = 'stackset'
        self.outputs = [{'OutputKey': 'BucketName', 'OutputValue': 'myteststack-output'}]
        self.template_url = 'dummy_url'
        self.stack_parameters = StackParameters()
