import itertools
import unittest
from unittest import mock
import json
from deploy_stack.deploy_stack import CloudformationStack


existing_stack_simple = [{
            'StackId': 'arn:aws:cloudformation:us-east-1:123456789012:stack/myteststack/466df9e0-0dff-08e3-8e2f-5088487c4896',
            'Description': 'Dummy CFN',
            'Tags': [],
            'Outputs': [{
                    'Description': 'Output to be tested',
                    'OutputKey': 'BucketName',
                    'OutputValue': 'myteststack-output',
                }],
            'StackStatusReason': 'null',
            'CreationTime': '2013-08-23T01:02:15.422Z',
            'Capabilities': [],
            'StackName': 'rc0-myteststack1',
            'StackStatus': 'CREATE_COMPLETE',
            'DisableRollback': 'false',
        }]

stack_output = {'outputs':[{'OutputKey': 'BucketName',
                        'OutputValue': 'myteststack-output',
                      }]}


class template():
    name= 'myteststack1'
    outputs = [{'OutputKey': 'BucketName',
                        'OutputValue': 'myteststack-output',
                      }]

class TestCloudformationStack(unittest.TestCase):
    @mock.patch('deploy_stack.deploy_stack.s')
    def test_find_existing_stack(self, mock_session):
        existing_stack = {}
        existing_stack['Stacks']=existing_stack_simple
        mock_session.client.return_value.describe_stacks.return_value = existing_stack
        r = CloudformationStack('rc0',template())
        self.assertEqual(r.existing_stack['StackName'], f'rc0-{template().name}', 'stack is present, but seed not validating')

    @mock.patch('deploy_stack.deploy_stack.s')
    def test_stack_output(self, mock_session):
        r = CloudformationStack('rc0',template())
        r.stack= template()
        output_value=r.get_stack_output('BucketName')
        self.assertEqual(output_value, 'myteststack-output','Stack output is not matching')




