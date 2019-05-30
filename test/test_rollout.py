import itertools
import unittest
from unittest import mock
from cloudformation_seed.cfn_stackset import StackSetRollout

existing_stack_simple = {
    'Summaries': [
        {
            'Account': '111111111111',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '222222222222',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '333333333333',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '444444444444',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
    ]
}

existing_stack_multi_reg = {
    'Summaries': [
        {
            'Account': '111111111111',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '111111111111',
            'Region': 'eu-west-1',
            'Status': 'CURRENT',
        },
        {
            'Account': '222222222222',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '333333333333',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
        {
            'Account': '333333333333',
            'Region': 'us-east-1',
            'Status': 'CURRENT',
        },
        {
            'Account': '333333333333',
            'Region': 'eu-west-1',
            'Status': 'CURRENT',
        },
        {
            'Account': '444444444444',
            'Region': 'ap-southeast-2',
            'Status': 'CURRENT',
        },
    ]
}

existing_stack_instance = {
    'StackInstance': {
        'ParameterOverrides': [
            {
                'ParameterKey': 'testParam1',
                'ParameterValue': 'testValue1'
            }
        ],
        'Status': 'CURRENT',
    }
}

existing_stack_instance2 = {
    'StackInstance': {
        'ParameterOverrides': [
            {
                'ParameterKey': 'testParam2',
                'ParameterValue': 'testValue2'
            }
        ],
        'Status': 'CURRENT',
    }
}


class TestGroupedRollout(unittest.TestCase):
    longMessage = 'Group rollout failure: '

    def check_if_deploying(self, rollout, account, region, overrides=None):
        for xr in rollout:
            for xa in xr['accounts']:
                if account in xa['accounts'] and region in xa['regions']:
                    if overrides is None:
                        return True
                    if sorted(xr['override'], key=lambda x: x['ParameterKey']) == \
                            sorted(overrides, key=lambda x: x['ParameterKey']):
                        return True
        return False

    @mock.patch('cloudformation_seed.util.session')
    def test_single_region_no_update(self, mock_session):
        mock_session.client.return_value.list_stack_instances.return_value = existing_stack_simple
        mock_session.client.return_value.describe_stack_instance.return_value = existing_stack_instance
        config = [{
            'account': xa['Account'],
            'regions': {'ap-southeast-2'},
            'override': existing_stack_instance['StackInstance']['ParameterOverrides']
        } for xa in existing_stack_simple['Summaries']]
        r = StackSetRollout('x0-test-stack', config)
        d = r.rollout_delete()
        c, u = r.rollout_create_update()
        self.assertEqual(len(d), 0, 'should not be deleting instances')
        self.assertEqual(len(c), 0, 'should not be creating instances')
        self.assertEqual(len(u), 0, 'should not be updating instances')

    @mock.patch('cloudformation_seed.util.session')
    def test_multi_region_no_update(self, mock_session):
        config = list()
        for account, group in itertools.groupby(sorted(existing_stack_multi_reg['Summaries'],
                key=lambda x: x['Account']), lambda x: x['Account']):
            regions = set([xg['Region'] for xg in group])
            config.append({
                'account': account,
                'regions': regions,
                'override': existing_stack_instance['StackInstance']['ParameterOverrides']
            })
        mock_session.client.return_value.list_stack_instances.return_value = existing_stack_multi_reg
        mock_session.client.return_value.describe_stack_instance.return_value = existing_stack_instance
        r = StackSetRollout('x0-test-stack', config)
        d = r.rollout_delete()
        c, u = r.rollout_create_update()
        self.assertEqual(len(d), 0, 'should not be deleting instances')
        self.assertEqual(len(c), 0, 'should not be creating instances')
        self.assertEqual(len(u), 0, 'should not be updating instances')

    @mock.patch('cloudformation_seed.util.session')
    def test_multi_region_create_update(self, mock_session):
        config = list()
        creating = {
            '222222222222': {'eu-west-1', 'us-east-1'},
            '333333333333': {'ap-southeast-1'}
        }
        updating = {
            '111111111111': {'eu-west-1', 'ap-southeast-2'},
            '444444444444': {'ap-southeast-2'}
        }
        for account, group in itertools.groupby(sorted(existing_stack_multi_reg['Summaries'],
                key=lambda x: x['Account']), lambda x: x['Account']):
            regions = set([xg['Region'] for xg in group])
            override = existing_stack_instance['StackInstance']['ParameterOverrides']
            if account in creating:
                regions.update(creating[account])
            if account in updating:
                override = existing_stack_instance2['StackInstance']['ParameterOverrides']
            config.append({
                'account': account,
                'regions': regions,
                'override': override
            })
        mock_session.client.return_value.list_stack_instances.return_value = existing_stack_multi_reg
        mock_session.client.return_value.describe_stack_instance.return_value = existing_stack_instance
        r = StackSetRollout('x0-test-stack', config)
        d = r.rollout_delete()
        c, u = r.rollout_create_update()
        self.assertEqual(len(d), 0, 'should not be deleting instances')
        for xa, xr in creating.items():
            for xr in xr:
                self.assertTrue(self.check_if_deploying(c, xa, xr,
                    existing_stack_instance['StackInstance']['ParameterOverrides']))
        for xa, xr in updating.items():
            for xr in xr:
                self.assertTrue(self.check_if_deploying(u, xa, xr,
                    existing_stack_instance2['StackInstance']['ParameterOverrides']))


if __name__ == '__main__':
    unittest.main()
