import unittest
from unittest import mock
from deploy_stack.deploy_stack import CloudformationStack


existing_stack_simple = [{
            'StackId': 'arn:aws:cloudformation:us-east-1:123456789012:stack/myteststack/qwqw',
            'Description': 'Dummy CFN',
            'Tags': [],
            'Outputs': [{
                    'Description': 'Output to be tested',
                    'OutputKey': 'BucketName',
                    'OutputValue': 'myteststack-output'}],
            'StackStatusReason': 'null',
            'CreationTime': '2013-08-23T01:02:15.422Z',
            'Capabilities': [],
            'StackName': 'rc0-myteststack1',
            'StackStatus': 'CREATE_IN_PROGRESS',
            'DisableRollback': 'false',
        }]


class template():
    name = 'myteststack1'
    outputs = [{'OutputKey': 'BucketName', 'OutputValue': 'myteststack-output'}]
    template_url = 'dummy_url'

    class stack_parameters():
        def format_parameters():
            return [{'ParameterKey': 'Test', 'ParameterValue': 'Success'}]


class TestCloudformationStack(unittest.TestCase):
    @mock.patch('deploy_stack.deploy_stack.s')
    def test_update_stack(self, mock_session):
        existing_stack = {}
        existing_stack['Stacks'] = existing_stack_simple
        mock_session.client.return_value.describe_stacks.return_value = existing_stack
        r = CloudformationStack('rc0', template())
        r.stack_parameters = template().stack_parameters
        output_value = r.deploy()
        self.assertEqual(output_value, None, 'Must be a update stack operation')

    @mock.patch('deploy_stack.deploy_stack.s')
    def test_stack_output(self, mock_session):
        r = CloudformationStack('rc0', template())
        r.stack = template()
        output_value = r.get_stack_output('BucketName')
        self.assertEqual(output_value, 'myteststack-output', 'Stack output is not matching')

    @mock.patch('deploy_stack.deploy_stack.s')
    def test_create_stack(self, mock_session):
        r = CloudformationStack('rc0', template())
        r.existing_stack = None
        r.stack_parameters = template().stack_parameters
        output_value = r.deploy()
        self.assertEqual(output_value, None, 'Must be a create stack operation')

    @mock.patch('deploy_stack.deploy_stack.s')
    def test_teardown(self, mock_session):
        mock_session.client.return_value.delete_stack.return_value = None
        r = CloudformationStack('rc0', template())
        output_value = r.teardown()
        self.assertEqual(output_value, None, 'Error in teardown')
