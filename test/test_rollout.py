import boto3
from botocore.stub import Stubber

import unittest
from deploy_stack.deploy_stack import StackSetRollout


client = boto3.client('cloudformation')
stubber = Stubber(client)
stack_list_resp = {'Summaries': []}
stack_list_expected_params = {}
stubber.add_response('list_stack_instances', stack_list_resp, stack_list_expected_params)


class TestGroupedRollout(unittest.TestCase):
    def setUp(self):
        pass

    def test_initialise(self):
        r = StackSetRollout('x0-test-stack', None)
        with stubber:
            r.retrieve()


if __name__ == '__main__':
    unittest.main()
