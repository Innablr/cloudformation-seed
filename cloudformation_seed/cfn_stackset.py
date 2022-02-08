from cloudformation_seed import util, cfn_template

from typing import Dict, List, Any, Optional, NoReturn

import logging
import copy
import hashlib
import itertools
import time

from functools import wraps
from colorama import Fore, Style
from botocore.exceptions import ClientError

log = logging.getLogger('stack-deployer')


class StackSetOrganizationRollout(object):
    def __init__(self, stack_name, rollout_config):
        self.stack_name = stack_name
        self.rollout_config = rollout_config
        self.strategy = 'organization'
        self.stack_instances_by_ou = None
        self.create_ou = list()
        self.update_ou = list()
        self.delete_ou = list()

    def retrieve(self) -> None:
        c = util.session.client('cloudformation')
        log.info('Loading stack instances...')
        r = c.list_stack_instances(StackSetName=self.stack_name)
        self.stack_instances_by_ou = dict()
        for xi in r['Summaries']:
            if 'OrganizationalUnitId' in xi:
                self.stack_instances_by_ou.setdefault(xi['OrganizationalUnitId'], set()).add(xi['Region'])
        log.info(f'Found {Fore.GREEN}{sum(len(xv) for xv in self.stack_instances_by_ou.values())}{Style.RESET_ALL} '
            f'stack instances in {Fore.MAGENTA}{len(self.stack_instances_by_ou)}{Style.RESET_ALL} OUs')

    def find_or_add_ou(self, where, ou):
        coll = self.create_ou if where == 'create' else self.update_ou
        matches = [xa for xa in coll if xa['ou'] == ou['ou'] and xa['override'] == ou['override']]
        try:
            return matches[0]
        except IndexError:
            new_ou = copy.copy(ou)
            new_ou['regions'] = set()
            coll.append(new_ou)
            return new_ou

    def ou_region_need_update(self, ou_id, region, overrides):
        return True

    def set_create_or_update_ou(self, rollout_item):
        ou_id = rollout_item['ou']
        if ou_id not in self.stack_instances_by_ou and len(rollout_item['regions']) > 0:
            log.debug(f'Stackset will create instances in OU '
                f'{Fore.GREEN}{ou_id}{Style.RESET_ALL} regions '
                f'{Fore.GREEN}{rollout_item["regions"]}{Style.RESET_ALL}')
            self.create_ou.append(copy.copy(rollout_item))
            return
        for region in rollout_item['regions']:
            if region in self.stack_instances_by_ou[ou_id]:
                if not self.ou_region_need_update(ou_id, region, rollout_item['override']):
                    log.info(f'Stack instance in OU '
                        f'{Fore.GREEN}{ou_id}{Style.RESET_ALL} '
                        f'region {Fore.GREEN}{region}{Style.RESET_ALL} is not updating')
                    continue
                log.debug(f'Stackset will update instance in OU {ou_id} region {region}')
                rollout_ou = self.find_or_add_ou('update', rollout_item)
            else:
                log.debug(f'Stackset will create instance in OU {ou_id} region {region}')
                rollout_ou = self.find_or_add_ou('create', rollout_item)
            rollout_ou['regions'].add(region)

    def set_delete_ou(self, ou, regions):
        rollout_ous = [xa for xa in self.rollout_config if xa['ou'] == ou]
        rollout_regions = set.union(*[xa['regions'] for xa in rollout_ous]) if len(rollout_ous) > 0 else set()
        delete_regions = regions - rollout_regions
        if len(delete_regions) > 0:
            log.debug(f'OU {ou} is set for deletion in regions {delete_regions}')
            self.delete_ou.append({
                'ou': ou,
                'regions': delete_regions,
                'override': dict()
            })

    def collate_instances_create_update(self):
        self.create_ou.clear()
        self.update_ou.clear()
        self.retrieve()
        for rollout_item in self.rollout_config:
            self.set_create_or_update_ou(rollout_item)

    def collate_instances_delete(self):
        self.delete_ou.clear()
        self.retrieve()
        for ou, regions in self.stack_instances_by_ou.items():
            self.set_delete_ou(ou, regions)

    def rollout_delete(self):
        self.collate_instances_delete()
        return self.delete_ou

    def rollout_create_update(self):
        self.collate_instances_create_update()
        return self.create_ou, self.update_ou


class StackSetRollout(object):
    def __init__(self, stack_name, rollout_config):
        self.stack_name = stack_name
        self.rollout_config = rollout_config
        self.strategy = 'accounts'
        self.stack_instances = None
        self.create = list()
        self.update = list()
        self.delete = list()

    def retrieve(self) -> None:
        c = util.session.client('cloudformation')
        log.info('Loading stack instances...')
        r = c.list_stack_instances(StackSetName=self.stack_name)
        self.stack_instances = dict()
        for xi in r['Summaries']:
            self.stack_instances.setdefault(xi['Account'], set()).add(xi['Region'])
        log.info(f'Found {Fore.GREEN}{sum(len(xv) for xv in self.stack_instances.values())}{Style.RESET_ALL} '
            f'stack instances in {Fore.MAGENTA}{len(self.stack_instances)}{Style.RESET_ALL} accounts')

    def find_or_add_account(self, where, account):
        coll = self.create if where == 'create' else self.update
        matches = [xa for xa in coll if xa['account'] == account['account'] and xa['override'] == account['override']]
        try:
            return matches[0]
        except IndexError:
            new_account = copy.copy(account)
            new_account['regions'] = set()
            coll.append(new_account)
            return new_account

    def region_need_update(self, account_id, region, overrides):
        c = util.session.client('cloudformation')
        r = c.describe_stack_instance(
            StackSetName=self.stack_name,
            StackInstanceAccount=account_id,
            StackInstanceRegion=region
        )
        current_overrides = [{'ParameterKey': xo['ParameterKey'], 'ParameterValue': xo['ParameterValue']}
            for xo in r['StackInstance']['ParameterOverrides']]
        if sorted(current_overrides, key=lambda x: x['ParameterKey']) != \
                sorted(overrides, key=lambda x: x['ParameterKey']):
            log.info('Parameter overrides are changing in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} in region {region}')
            return True
        if r['StackInstance']['Status'] != 'CURRENT':
            log.info(f'Stackset instance is {Fore.MAGENTA}NOT CURRENT{Style.RESET_ALL} in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} in region {region}')
            return True
        return False

    def set_create_or_update_account(self, account) -> None:
        account_id = account['account']
        if account_id not in self.stack_instances and len(account['regions']) > 0:
            log.debug(f'Stackset will create instances in account '
                f'{Fore.GREEN}{account_id}{Style.RESET_ALL} regions '
                f'{Fore.GREEN}{account["regions"]}{Style.RESET_ALL}')
            self.create.append(copy.copy(account))
            return
        for region in account['regions']:
            if region in self.stack_instances[account_id]:
                if not self.region_need_update(account_id, region, account['override']):
                    log.info(f'Stack instance in account '
                        f'{Fore.GREEN}{account_id}{Style.RESET_ALL} '
                        f'region {Fore.GREEN}{region}{Style.RESET_ALL} is not updating')
                    continue
                log.debug(f'Stackset will update instance in account {account_id} region {region}')
                rollout_account = self.find_or_add_account('update', account)
            else:
                log.debug(f'Stackset will create instance in account {account_id} region {region}')
                rollout_account = self.find_or_add_account('create', account)
            rollout_account['regions'].add(region)

    def set_delete_account(self, account, regions):
        rollout_accounts = [xa for xa in self.rollout_config if xa['account'] == account]
        rollout_regions = set.union(*[xa['regions'] for xa in rollout_accounts]) if len(rollout_accounts) > 0 else set()
        delete_regions = regions - rollout_regions
        if len(delete_regions) > 0:
            log.debug(f'Account {account} is set for deletion in regions {delete_regions}')
            self.delete.append({
                'account': account,
                'regions': delete_regions,
                'override': dict()
            })

    def collate_instances_create_update(self):
        self.create.clear()
        self.update.clear()
        self.retrieve()
        for rollout_account in self.rollout_config:
            self.set_create_or_update_account(rollout_account)

    def collate_instances_delete(self):
        self.delete.clear()
        self.retrieve()
        for account, regions in self.stack_instances.items():
            self.set_delete_account(account, regions)

    def calculate_overrides_checksum(self, account):
        if len(account['override']) == 0:
            return '-'
        sha1sum = hashlib.sha1()
        for item in sorted(account['override'],
                key=lambda x: '{ParameterKey}-{ParameterValue}'.format_map(x)):
            sha1sum.update(bytes(repr(item), 'utf-8'))
        return sha1sum.hexdigest()

    def rank_sets(self, a):
        ranking = list()
        for i in range(len(a), 1, -1):
            for subset in itertools.combinations(sorted(a), i):
                intersected = set.intersection(*(a[k] for k in subset))
                if len(intersected) > 0:
                    if intersected not in ranking:
                        ranking.append(intersected)
                else:
                    for k in subset:
                        if a[k] not in ranking:
                            ranking.append(a[k])
        return sorted(ranking, reverse=True, key=lambda x: len(x))

    def compute_deployment(self, initial, xset):
        new = dict()
        deployment = {
            'accounts': list(),
            'regions': xset
        }
        for account, regions in initial.items():
            if regions >= xset:
                deployment['accounts'].append(account)
                if len(regions - xset) > 0:
                    new[account] = regions - xset
            else:
                new[account] = regions
        return deployment, new

    def generate_deployments(self, rollout):
        while len(rollout) > 1:
            costed_sets = []
            for xs in self.rank_sets(rollout):
                if len(xs) > 0:
                    d, r0 = self.compute_deployment(rollout, xs)
                    cost = sum(1 for _ in self.generate_deployments(r0))
                    costed_sets.append((cost, xs))
            winner = sorted(costed_sets, key=lambda x: x[0])[0]
            d, rollout = self.compute_deployment(rollout, winner[1])
            yield d
        for account, regions in rollout.items():
            yield {
                'accounts': [account],
                'regions': regions
            }

    def grouped_rollout(self, coll):
        deployments = list()
        for _, group in itertools.groupby(sorted(coll, key=self.calculate_overrides_checksum),
                self.calculate_overrides_checksum):
            group_list = list(group)
            deployment = {
                'override': group_list[0]['override'],
                'accounts': list()
            }
            deployment_accounts = dict()
            for xd in group_list:
                deployment_accounts.setdefault(xd['account'], set()).update(xd['regions'])
            for xd in self.generate_deployments(deployment_accounts):
                deployment['accounts'].append(xd)
            deployments.append(deployment)
        return deployments

    def rollout_delete(self):
        self.collate_instances_delete()
        return self.grouped_rollout(self.delete)

    def rollout_create_update(self):
        self.collate_instances_create_update()
        return self.grouped_rollout(self.create), self.grouped_rollout(self.update)


class CloudformationStackSet(object):
    def __init__(self, installation_name: str, template: cfn_template.CloudformationTemplate) -> None:
        self.template: cfn_template.CloudformationTemplate = template
        self.stack_name: str = f'{installation_name}-{self.template.name}'
        self.stack_parameters: Optional[util.StackParameters] = None
        self.existing_stack: Optional[Dict[str, Any]] = self.find_existing_stackset()
        self.caps = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND']
        self.stack = None
        self.stackset_rollout: Optional[StackSetRollout] = None
        self.stack_tags = []
        self.formatted_stack_tags = []

    def retry_pending(f):
        @wraps(f)
        def wrapper(self, *args, **kwargs):
            while True:
                try:
                    return f(self, *args, **kwargs)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'OperationInProgressException':
                        log.warning(f'Operation is in progress on stackset {self.stack_name}, retrying after wait...')
                        self.wait_pending_operations()
                        log.warning('Retrying operation')
                    else:
                        raise
        return wrapper

    def set_parameters(self, parameters: util.StackParameters) -> None:
        self.stack_parameters = parameters
        if self.stack_parameters.rollout is not None:
            if self.stack_parameters.rollout_strategy == 'organization':
                self.stackset_rollout = StackSetOrganizationRollout(self.stack_name, self.stack_parameters.rollout)
            else:
                self.stackset_rollout = StackSetRollout(self.stack_name, self.stack_parameters.rollout)

    def find_existing_stackset(self) -> Optional[Dict[str, Any]]:
        c = util.session.client('cloudformation')
        try:
            r = c.describe_stack_set(StackSetName=self.stack_name)
            stackset = r['StackSet']
            log.info(f'Found stackset {Fore.GREEN}{stackset["StackSetName"]}{Style.RESET_ALL} '
                f'in status {Fore.MAGENTA}{stackset["Status"]}{Style.RESET_ALL}')
            return stackset
        except Exception:
            log.info(f'Stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} does not exist')
            return None

    def tags_need_update(self):
        c = util.session.client('cloudformation')
        response = c.describe_stack_set(StackSetName=self.stack_name)
        return response['StackSet']['Tags'] != self.formatted_stack_tags

    def get_stack_output(self, output_name: str) -> NoReturn:
        raise util.InvalidStackConfiguration(f'Can\'t retrieve output {output_name} '
                                                     f'of stackset {self.stack_name}'
                                        f', stacksets don\'t have outputs. Please review your configuration')

    def format_tags(self, tags_passed):
        self.formatted_stack_tags = [{'Key': k, 'Value': str(v)} for k, v in tags_passed.items() if v is not None]

    def validate_tags(self, tags_passed):
        self.stack_tags = tags_passed
        for k, v in tags_passed.items():
            if len(k) > 127:
                raise RuntimeError('Tag Key {0} cannot be more than 127 characters long'.format(k))
            if len(v) > 255:
                raise RuntimeError('Tag Value {0} cannot be more than 255 characters long'.format(v))
        self.format_tags(tags_passed)

    @retry_pending
    def create_stackset(self) -> None:
        c = util.session.client('cloudformation')
        params: Dict[str, Any] = {
            'StackSetName': self.stack_name,
            'TemplateURL': self.template.template_url,
            'Parameters': self.stack_parameters.format_parameters(),
            'Capabilities': self.caps,
            'Tags': self.formatted_stack_tags,
            'PermissionModel': 'SERVICE_MANAGED' if self.stackset_rollout.strategy == 'organization' else 'SELF_MANAGED'
        }
        params.update(self.stack_parameters.format_role_pair())
        params.update(self.stack_parameters.format_rollout_autodeploy())
        log.info(f'Creating stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        c.create_stack_set(**params)
        self.wait_pending_operations()

    def stackset_need_update(self) -> bool:
        current_parameters: List[Dict[str, str]] = \
            [{'ParameterKey': xo['ParameterKey'], 'ParameterValue': xo['ParameterValue']}
                for xo in self.existing_stack['Parameters']]
        log.debug('>> Current parameters')
        log.debug(current_parameters)
        log.debug('>> New parameters')
        log.debug(self.stack_parameters.format_parameters())
        parameters_changed: bool = sorted(current_parameters, key=lambda x: x['ParameterKey']) != \
            sorted(self.stack_parameters.format_parameters(), key=lambda x: x['ParameterKey'])
        log.info('Parameters are {color}{is_changing}{color_reset} for stackset {color}{stackset_name}{color_reset}'
            .format(is_changing='changing' if parameters_changed else 'not changing',
                stackset_name=self.stack_name,
                color=Fore.GREEN,
                color_reset=Style.RESET_ALL))
        template_changed: bool = \
            cfn_template.CloudformationTemplateBody(self.existing_stack['TemplateBody'])\
                .checksum != self.template.template_checksum
        log.info('Template is {color}{is_changing}{color_reset} for stackset {color}{stackset_name}{color_reset}'
            .format(is_changing='changing' if template_changed else 'not changing',
                stackset_name=self.stack_name,
                color=Fore.GREEN,
                color_reset=Style.RESET_ALL))
        tags_changed: bool = self.tags_need_update()
        log.info('Tags are {color}{is_changing}{color_reset} for stackset {color}{stackset_name}{color_reset}'
            .format(is_changing='changing' if tags_changed else 'not changing',
                stackset_name=self.stack_name,
                color=Fore.GREEN,
                color_reset=Style.RESET_ALL))
        return parameters_changed or template_changed or tags_changed

    @retry_pending
    def update_stackset(self) -> None:
        if not self.stackset_need_update():
            log.info('No changes to stackset template or parameters. Skipping stackset update')
            return
        p = self.stack_parameters.format_parameters()
        c = util.session.client('cloudformation')
        log.info(f'Updating stackset {Fore.GREEN}{self.stack_name}{Style.RESET_ALL} with template'
            f' {Fore.GREEN}{self.template.template_url}{Style.RESET_ALL}')
        log.debug(' Parameters '.center(48, '-'))
        log.debug(p)
        log.debug('-'.center(48, '-'))
        params = {
            'StackSetName': self.stack_name,
            'TemplateURL': self.template.template_url,
            'Parameters': p,
            'Capabilities': self.caps,
            'Tags': self.formatted_stack_tags,
            'PermissionModel': 'SERVICE_MANAGED' if self.stackset_rollout.strategy == 'organization' else 'SELF_MANAGED'
        }
        params.update(self.stack_parameters.format_role_pair())
        params.update(self.stack_parameters.format_rollout_autodeploy())
        params.update(self.stack_parameters.format_operation_preferences())
        c.update_stack_set(**params)
        self.wait_pending_operations()

    def deploy(self) -> None:
        if self.existing_stack is None:
            self.create_stackset()
        else:
            self.cleanup_stackset()
            self.update_stackset()
        self.stack = self.find_existing_stackset()
        self.rollout_stackset()

    def cleanup_stackset(self):
        if self.stackset_rollout is None:
            log.info('Rollout configuration is missing, not cleaning up stack instances')
            return
        if self.stackset_rollout.strategy == 'organization':
            self.cleanup_organization()
        else:
            self.cleanup_stack_instances()

    @retry_pending
    def cleanup_organization(self) -> None:
        c = util.session.client('cloudformation')
        delete_items = self.stackset_rollout.rollout_delete()
        log.debug(f'Delete instances: {delete_items}')
        for xg in delete_items:
            log.info(f'Deleting stack instances for OU {xg["ou"]} '
                f'in regions {xg["regions"]}...')
            params = {
                'StackSetName': self.stack_name,
                'DeploymentTargets': {},
                'Regions': list(xg["regions"]),
                'RetainStacks': False
            }
            params['DeploymentTargets'].setdefault('OrganizationalUnitIds', list()).append(xg['ou'])
            if self.stack_parameters.stackset_call_as == 'delegated_admin':
                params['CallAs'] = 'DELEGATED_ADMIN'
            params.update(self.stack_parameters.format_operation_preferences())
            c.delete_stack_instances(**params)
            self.wait_pending_operations()

    @retry_pending
    def cleanup_stack_instances(self) -> None:
        c = util.session.client('cloudformation')
        delete_groups = self.stackset_rollout.rollout_delete()
        log.debug(f'Delete instances: {delete_groups}')
        for xg in delete_groups:
            for xd in xg['accounts']:
                log.info(f'Deleting stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'RetainStacks': False
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.delete_stack_instances(**params)
                self.wait_pending_operations()

    def rollout_stackset(self):
        if self.stackset_rollout is None:
            log.info('Rollout configuration is missing, not deploying stack instances')
            return
        if self.stackset_rollout.strategy == 'organization':
            self.rollout_organization()
        else:
            self.rollout_accounts()

    @retry_pending
    def rollout_organization(self) -> None:
        c = util.session.client('cloudformation')
        create_items, update_items = self.stackset_rollout.rollout_create_update()
        log.debug(f'Update instances: {update_items}')
        log.debug(f'Create instances: {create_items}')
        for xg in create_items:
            params = {
                'StackSetName': self.stack_name,
                'DeploymentTargets': {},
                'Regions': list(xg["regions"]),
                'ParameterOverrides': xg['override']
            }
            log.info(f'Creating new stack instances for OU {xg["ou"]} '
                f'in regions {xg["regions"]}...')
            params['DeploymentTargets'].setdefault('OrganizationalUnitIds', list()).append(xg['ou'])
            if self.stack_parameters.stackset_call_as == 'delegated_admin':
                params['CallAs'] = 'DELEGATED_ADMIN'
            params.update(self.stack_parameters.format_operation_preferences())
            c.create_stack_instances(**params)
            self.wait_pending_operations()
        for xg in update_items:
            params = {
                'StackSetName': self.stack_name,
                'DeploymentTargets': {},
                'Regions': list(xg["regions"]),
                'ParameterOverrides': xg['override']
            }
            log.info(f'Updating stack instances for OU {xg["ou"]} '
                f'in regions {xg["regions"]}...')
            params['DeploymentTargets'].setdefault('OrganizationalUnitIds', list()).append(xg['ou'])
            if self.stack_parameters.stackset_call_as == 'delegated_admin':
                params['CallAs'] = 'DELEGATED_ADMIN'
            params.update(self.stack_parameters.format_operation_preferences())
            c.update_stack_instances(**params)
            self.wait_pending_operations()

    @retry_pending
    def rollout_accounts(self) -> None:
        c = util.session.client('cloudformation')
        create_groups, update_groups = self.stackset_rollout.rollout_create_update()
        log.debug(f'Update instances: {update_groups}')
        log.debug(f'Create instances: {create_groups}')
        for xg in create_groups:
            for xd in xg['accounts']:
                log.info(f'Creating new stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'ParameterOverrides': xg['override']
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.create_stack_instances(**params)
                self.wait_pending_operations()
        for xg in update_groups:
            for xd in xg['accounts']:
                log.info(f'Updating stack instances for accounts {xd["accounts"]} '
                    f'in regions {xd["regions"]}...')
                params = {
                    'StackSetName': self.stack_name,
                    'Accounts': xd["accounts"],
                    'Regions': list(xd["regions"]),
                    'ParameterOverrides': xg['override']
                }
                params.update(self.stack_parameters.format_operation_preferences())
                c.update_stack_instances(**params)
                self.wait_pending_operations()

    @retry_pending
    def wipe_out_stackset_instances(self) -> None:
        c = util.session.client('cloudformation')
        i = c.list_stack_instances(StackSetName=self.stack_name)
        for account, group in itertools.groupby(sorted(i['Summaries'],
                key=lambda x: x['Account']), lambda x: x['Account']):
            regions = [xg['Region'] for xg in group]
            log.info(f'Deleting stack instance in account {account} regions {regions}...')
            c.delete_stack_instances(
                StackSetName=self.stack_name,
                Accounts=[account],
                Regions=regions,
                RetainStacks=False,
                OperationPreferences={
                    'MaxConcurrentPercentage': 100
                }
            )
            self.wait_pending_operations()

    @retry_pending
    def delete_stackset(self) -> None:
        c = util.session.client('cloudformation')
        log.info(f'Deleting stackset {self.stack_name}...')
        c.delete_stack_set(StackSetName=self.stack_name)

    def teardown(self) -> None:
        if self.existing_stack is None:
            log.info(f'StackSet {self.stack_name} does not exist. Skipping.')
            return
        self.wipe_out_stackset_instances()
        self.delete_stackset()

    def wait_pending_operations(self) -> None:
        c = util.session.client('cloudformation')
        try:
            time.sleep(1)
            while True:
                r = c.list_stack_set_operations(StackSetName=self.stack_name, MaxResults=10)
                if len([xo for xo in r['Summaries'] if xo['Status'] in ['RUNNING', 'STOPPING']]) > 0:
                    log.info(f'There\'s operations pending on stackset {self.stack_name}')
                    time.sleep(10)
                    continue
                return
        except ClientError as e:
            if e.response['Error']['Code'] != 'StackSetNotFoundException':
                raise
