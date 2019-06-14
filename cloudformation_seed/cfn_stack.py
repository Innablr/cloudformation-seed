from cloudformation_seed import util, cfn_template

from typing import Dict, Any, Optional

import logging
from colorama import Fore, Style
from botocore.exceptions import ClientError


log = logging.getLogger('stack-deployer')


class CloudformationStack(object):

    def __init__(self, installation_name: str, template: cfn_template.CloudformationTemplate) -> None:
        self.template: cfn_template.CloudformationTemplate = template
        self.stack_name = f'{installation_name}-{self.template.name}'
        self.stack_parameters = None
        self.existing_stack = self.find_existing_stack()
        self.caps = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND']
        self.stack = None
        self.stack_tags = []

    def set_parameters(self, parameters: util.StackParameters) -> None:
        self.stack_parameters = parameters

    def find_existing_stack(self) -> Optional[Dict[str, Any]]:
        c = util.session.client('cloudformation')
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

    def format_tags(self, tags_passed):
        self.stack_tags = [{'Key': k, 'Value': str(v)} for k, v in tags_passed.items() if v is not None]

    def validate_tags(self, tags_passed):
        for k, v in tags_passed.items():
            if len(k) > 127:
                raise RuntimeError('Tag Key {0} cannot be more than 127 characters long'.format(k))
            if len(v) > 255:
                raise RuntimeError('Tag Value {0} cannot be more than 255 characters long'.format(v))
        self.format_tags(tags_passed)

    def create_stack(self) -> None:
        c = util.session.client('cloudformation')
        log.info(f'Creating stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        c.create_stack(
            StackName=self.stack_name,
            TemplateURL=self.template.template_url,
            Parameters=self.stack_parameters.format_parameters(),
            DisableRollback=True,
            Capabilities=self.caps,
            Tags=self.stack_tags
        )
        self.wait('stack_create_complete')
        self.retrieve()

    def update_stack(self) -> None:
        c = util.session.client('cloudformation')
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
                Capabilities=self.caps,
                Tags=self.stack_tags
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
        c = util.session.client('cloudformation')
        log.info(f'Deleting stack {Fore.GREEN}{self.stack_name}{Style.RESET_ALL}...')
        c.delete_stack(StackName=self.stack_name)
        self.wait('stack_delete_complete')

    def wait(self, event: str) -> None:
        log.info('Waiting for operation to finish...')
        c = util.session.client('cloudformation')
        waiter = c.get_waiter(event)
        try:
            waiter.wait(StackName=self.stack_name)
        except Exception as e:
            self.retrieve()
            raise util.DeploymentFailed(f'Stack {self.stack_name} deployment failed: {str(e)}') from None

    def retrieve(self) -> None:
        r = util.session.resource('cloudformation')
        self.stack = r.Stack(self.stack_name)
        log.info(f'Found stack {Fore.GREEN}{self.stack.stack_name}{Style.RESET_ALL} '
            f'in status {Fore.MAGENTA}{self.stack.stack_status}{Style.RESET_ALL}')
