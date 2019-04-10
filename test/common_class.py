from deploy_stack.deploy_stack import StackDeployer
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

    def load_init(self, operation):
        logging.disable(logging.CRITICAL)
        testargs = ["PassArgs", "-i", "test-stack", "-e", "prod",
                    "-d", "test.unit.cld", "--parameters-dir", "test/parameters",
                    "--templates-dir", "test/cloudformation", "--lambda-dir", "test/src", operation]
        with patch.object(sys, 'argv', testargs):
            deploy_stack_object = StackDeployer()
        return deploy_stack_object
