import unittest
from deploy_stack.deploy_stack import (StackDeployer, LambdaCollection, VersionManifest, S3Uploadable, DirectoryScanner,
CloudformationCollection, ColorFormatter, StackParameters)
from unittest.mock import patch
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

    def load_init(self):
        logging.disable(logging.CRITICAL)
        testargs = ["PassArgs", "-i", "test-stack", "-e", "prod",
                    "-d", "test.unit.cld", "--parameters-dir",
                    "test/parameters", "--templates-dir", "test/cloudformation",
                    "--lambda-dir", "test/src", "deploy"]
        with patch.object(sys, 'argv', testargs):
            deploy_stack_object = StackDeployer()
        return deploy_stack_object

    def test_s3_uploadable(self):
        self.load_init()
        s3Bucket = self.__moto_setup()
        s3_uploadable = S3Uploadable('test/cloudformation/servicecatalog/v9/cf-provision-shared-services.cf.yaml',
                             s3Bucket,
                            ('cloudformation/servicecatalog/v9/'
                            '16fb196c9ed62b83167ff381565b5f0b76175332-cf-provision-shared-services.cf.yaml'))
        return s3_uploadable


class TestDeploy(unittest.TestCase):
    @patch('deploy_stack.deploy_stack.s')
    def test_deploy_environment(self, mock_session):
        test = CommonClass(mock_session)
        deploy_object = test.load_init()
        mock_session.client.return_value.describe_stack_set.return_value = {'StackSet': 'logging-set'}
        deploy_env = deploy_object.deploy_environment()
        self.assertIsNone(deploy_env)

    @patch('deploy_stack.deploy_stack.s')
    def test_lambda_collection(self, mock_session):
        lambda_collection = LambdaCollection('test/src', 'rc0-avm-root-ops.test.unit.cld', 'lambda')
        self.assertIsNotNone(lambda_collection)

    @patch('deploy_stack.deploy_stack.VersionManifest.default_manifest')
    @patch('deploy_stack.deploy_stack.s')
    def test_version_manifest(self, mock_session, mock_artifact):
        mock_artifact.return_value = {'release': {'release_version': 0, 'artifacts': ['TestArtifact']}}
        version_manifest = VersionManifest('rc0-avm-root-ops.prod.innablr-root.cld', None)
        self.assertIsNotNone(version_manifest)

    @patch('deploy_stack.deploy_stack.VersionManifest.default_manifest')
    @patch('deploy_stack.deploy_stack.s')
    def test_version_manifest_name(self, mock_session, mock_artifact):
        artifact_list = [{'name': 'TestArtifact'}]
        mock_artifact.return_value = {'release': {'release_version': 0, 'artifacts': artifact_list}}
        version_manifest = VersionManifest('rc0-avm-root-ops.prod.innablr-root.cld', None)
        obj_get_artificat = version_manifest.get_artifact_by_name('TestArtifact')
        self.assertEqual(obj_get_artificat['name'], 'TestArtifact', 'Artifact doesn\'t match')

    @patch('deploy_stack.deploy_stack.s')
    def test_check_md5(self, mock_session):
        obj_common_class = CommonClass(mock_session)
        obj_s3Upload = obj_common_class.test_s3_uploadable()
        check_md = obj_s3Upload.calculate_md5(
            'test/cloudformation/servicecatalog/v9/cf-provision-shared-services.cf.yaml')
        self.assertEqual(check_md, '56b048edd931e568e838f84b6ae89eba', 'md5 doesn\'t match')

    @patch('deploy_stack.deploy_stack.s')
    def test_print_progress(self, mock_session):
        obj_common_class = CommonClass(mock_session)
        obj_s3Upload = obj_common_class.test_s3_uploadable()
        obj_s3Upload.print_progress(1000)
        self.assertEqual(obj_s3Upload.bytes, 1000, 'file size doesn\'t match')

    @patch('deploy_stack.deploy_stack.S3Uploadable')
    @patch('deploy_stack.deploy_stack.s')
    def test_verify_existing_checksum(self, mock_session, mock_verify):
        # obj_common_class= CommonClass(mock_session)
        # obj_s3Upload = obj_common_class.test_s3_uploadable()
        mock_verify.Object.return_value = ''
        # work needs to be done
        # obj_s3Upload.verify_existing_checksum()

    @patch('deploy_stack.deploy_stack.S3Uploadable.verify_existing_checksum')
    @patch('deploy_stack.deploy_stack.s')
    def test_no_upload_if_existing_checksum(self, mock_session, mock_verify):
        obj_common_class = CommonClass(mock_session)
        obj_s3Upload = obj_common_class.test_s3_uploadable()
        mock_verify.return_value = True
        ret = obj_s3Upload.upload()
        self.assertIsNone(ret)

    @patch('deploy_stack.deploy_stack.s')
    def test_s3_url(self, mock_session):
        obj_common_class = CommonClass(mock_session)
        obj_s3Upload = obj_common_class.test_s3_uploadable()
        ret = obj_s3Upload.s3_url
        self.assertIsNotNone(ret)

    def test_scan_directory(self):
        obj = DirectoryScanner()
        files = obj.scan_directories('test/cloudformation')
        self.assertNotEqual(len(files), 0, 'Directory shoud not be null')

    @patch('deploy_stack.deploy_stack.s')
    def test_find_template(self, mock_session):
        obj_common_class = CommonClass(mock_session)
        obj_bucket = obj_common_class._bucket()
        obj = CloudformationCollection('test/cloudformation', obj_bucket, 'test/cloudformation',
        {'ssm-parameters': {}})
        obj_cfn_template = obj.find_template('servicecatalog/v9/cf-provision-shared-services.cf.yaml')
        self.assertEqual(obj_cfn_template.name, 'servicecatalog/v9/cf-provision-shared-services.cf.yaml',
        'Failed to pop the template from template folder')

    @patch('deploy_stack.deploy_stack.s')
    def test_find_template_file(self, mock_session):
        obj_common_class = CommonClass(mock_session)
        obj_bucket = obj_common_class._bucket()
        obj = CloudformationCollection('test/cloudformation', obj_bucket, ' test/cloudformation',
        {'ssm-parameters': {}})
        obj_cfn_template_file = obj.find_template_file('support/kms-parameters-lambda.cf.yaml')
        self.assertEqual(obj_cfn_template_file, 'test/cloudformation/support/kms-parameters-lambda.cf.yaml',
        'Failed to pop the template from template folder')

    @patch('deploy_stack.deploy_stack.s')
    def test_color_formatter_gray(self, mock_session):
        ch = ColorFormatter('%(levelname).1s %(message)s')
        record = logging.LogRecord(name='__name__', level=2, pathname='',
                                 lineno='', msg='GRAY', args=None,
                                 exc_info=None)
        obj_format = ch.format(record)
        self.assertEqual(obj_format, '\x1b \x1b[2mGRAY\x1b[0m', 'Failed: Gray color formatter')

    @patch('deploy_stack.deploy_stack.s')
    def test_color_formatter_red(self, mock_session):
        ch = ColorFormatter('%(levelname).1s %(message)s')
        record = logging.LogRecord(name='__name__', level=50, pathname='',
                                 lineno='', msg='RED', args=None,
                                 exc_info=None)
        obj_format = ch.format(record)
        self.assertEqual(obj_format, '\x1b \x1b[31mRED\x1b[0m', 'Failed: Red color formatter')

    @patch('deploy_stack.deploy_stack.s')
    def test_color_formatter_yellow(self, mock_session):
        ch = ColorFormatter('%(levelname).1s %(message)s')
        record = logging.LogRecord(name='__name__', level=31, pathname='',
                                 lineno='', msg='YELLOW', args=None,
                                 exc_info=None)
        obj_format = ch.format(record)
        self.assertEqual(obj_format, '\x1b \x1b[33mYELLOW\x1b[0m', 'Failed: Yello color formatter')

    @patch('deploy_stack.deploy_stack.StackParameters.format_role_pair')
    @patch('deploy_stack.deploy_stack.StackParameters.parse_parameters')
    @patch('deploy_stack.deploy_stack.StackParameters.set_stack_output')
    @patch('deploy_stack.deploy_stack.StackParameters.set_lambda_zip')
    @patch('deploy_stack.deploy_stack.s')
    def test_format_role_pair(self, mock_session, mock_stack_lambda, mock_stack_output,
    mock_parse_parameters, mock_format_role_pair):
        class Options:
            def __init__(self):
                self.installation_name = 'rco'
                self.component_name = 'generic-ops'
                self.dns_domain = 'test.innablr.cld'
                self.org_arn = None
                self.runtime_environment = 'prod'
                self.parameters_dir = 'test/parameters'

        class Template:
            def __init__(self):
                self.name = 'logging-set'
                self.template_type = 'stackset'

        obj_common_class = CommonClass(mock_session)
        obj_bucket = obj_common_class._bucket()
        mock_stack_lambda.return_value = 'Test.zip'
        mock_stack_output.return_value = '100'
        mock_parse_parameters.return_value = {}
        mock_format_role_pair.return_value = {}
        test = StackParameters(obj_bucket, Template(), '', Options(), 'prod')
        test.format_operation_preferences()
