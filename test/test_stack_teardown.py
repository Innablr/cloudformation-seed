from . import common_class
import unittest
from unittest import mock
from deploy_stack.deploy_stack import StackDeployer, LambdaCollection
from unittest.mock import patch, Mock

class TestTearDown(unittest.TestCase):
    @patch('deploy_stack.deploy_stack.s')
    def test_teardown_environment(self, mock_session):
        test = common_class.CommonClass(mock_session)
        tear_object = test.load_init('teardown')
        tear_env = tear_object.teardown_environment()
        self.assertIsNone(tear_env)

    @patch('deploy_stack.deploy_stack.s')
    def test_lambda_cleanup(self, mock_session):
        test = common_class.CommonClass(mock_session)
        tear_bucket = test._bucket()
        lambda_collection = LambdaCollection('test/src',tear_bucket,'lambda')
        lambda_collection.cleanup()