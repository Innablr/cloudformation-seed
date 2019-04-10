from . import common_class
import unittest
from deploy_stack.deploy_stack import LambdaCollection
from unittest.mock import patch


class TestTearDown(unittest.TestCase):
    @patch('deploy_stack.deploy_stack.s')
    def test_teardown_environment(self, mock_session):
        test = common_class.CommonClass(mock_session)
        tear_object = test.load_init('teardown')
        tear_env = tear_object.teardown_environment()
        self.assertIsNone(tear_env)

    @patch('deploy_stack.deploy_stack.s')
    def test_lambda_cleanup(self, mock_session):
        obj_lambda_cleanup = common_class.CommonClass(mock_session)
        tear_bucket = obj_lambda_cleanup._bucket()
        lambda_collection = LambdaCollection('test/src', tear_bucket, 'lambda')
        lambda_collection.cleanup()
