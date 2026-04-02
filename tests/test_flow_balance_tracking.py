import copy
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

import routes
from data_manager import global_worker_data, modality_data
from config import allowed_modalities
import data_manager.scheduled_tasks as scheduled_tasks


class TestFlowBalanceTracking(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_flow = copy.deepcopy(global_worker_data.get('flow_cross_pool', {}))
        self.prev_last_reset_date = global_worker_data.get('last_reset_date')
        self.prev_weighted_counts = copy.deepcopy(global_worker_data.get('weighted_counts', {}))
        self.prev_assignments_per_mod = copy.deepcopy(global_worker_data.get('assignments_per_mod', {}))
        self.prev_modality_state = {
            mod: {
                'skill_counts': copy.deepcopy(modality_data[mod].get('skill_counts', {})),
                'last_reset_date': modality_data[mod].get('last_reset_date'),
            }
            for mod in allowed_modalities
        }

    def tearDown(self) -> None:
        global_worker_data['flow_cross_pool'] = self.prev_flow
        global_worker_data['last_reset_date'] = self.prev_last_reset_date
        global_worker_data['weighted_counts'] = self.prev_weighted_counts
        global_worker_data['assignments_per_mod'] = self.prev_assignments_per_mod
        for mod in allowed_modalities:
            modality_data[mod]['skill_counts'] = self.prev_modality_state[mod]['skill_counts']
            modality_data[mod]['last_reset_date'] = self.prev_modality_state[mod]['last_reset_date']

    def test_record_cross_pool_flow_only_on_skill_mismatch(self) -> None:
        global_worker_data['flow_cross_pool'] = {}

        same_pool = routes._record_cross_pool_flow(
            requested_skill='aou',
            target_skill='aou',
            amount=1.0,
        )
        self.assertFalse(same_pool)
        self.assertEqual(global_worker_data['flow_cross_pool'], {})

        cross_pool = routes._record_cross_pool_flow(
            requested_skill='aou',
            target_skill='cvt',
            amount=2.5,
        )
        self.assertTrue(cross_pool)
        self.assertEqual(
            global_worker_data['flow_cross_pool'],
            {'aou': {'cvt': 2.5}},
        )

    def test_resolve_flow_target_skill_maps_generalist_overflow_back_to_main_skill(self) -> None:
        direct_specialist = routes._resolve_flow_target_skill(
            {'aou': 1, 'cvt': 1, 'mdh': 0},
            assigned_skill='aou',
        )
        self.assertEqual(direct_specialist, 'aou')

        overflow_generalist = routes._resolve_flow_target_skill(
            {'aou': 0, 'cvt': 1, 'mdh': 0},
            assigned_skill='aou',
        )
        self.assertEqual(overflow_generalist, 'cvt')

        unmapped = routes._resolve_flow_target_skill(
            {'aou': 0, 'cvt': 0, 'mdh': 0},
            assigned_skill='aou',
        )
        self.assertIsNone(unmapped)

    def test_flow_balance_payload_aggregates_weighted_skill_links(self) -> None:
        global_worker_data['flow_cross_pool'] = {
            'aou': {'cvt': 2.5, 'mdh': 1.0},
            'cvt_ct': {'aou_ct': 1.5},
        }
        payload = routes._build_flow_balance_payload()

        self.assertTrue(payload['success'])
        self.assertIn('aou', payload['skills'])
        self.assertIn('cvt', payload['skills'])

        self.assertEqual(
            payload['out_by_skill']['aou'],
            [{'to': 'cvt', 'weight': 2.5}, {'to': 'mdh', 'weight': 1.0}],
        )
        self.assertEqual(
            payload['in_by_skill']['aou'],
            [{'from': 'cvt', 'weight': 1.5}],
        )
        self.assertEqual(payload['totals']['aou']['out_total'], 3.5)
        self.assertEqual(payload['totals']['aou']['in_total'], 1.5)
        self.assertEqual(payload['grand_totals']['cross_pool_total'], 5.0)

    def test_daily_reset_snapshots_and_clears_flow_counters(self) -> None:
        global_worker_data['flow_cross_pool'] = {'aou': {'cvt': 3.5}}
        global_worker_data['last_reset_date'] = date(2026, 3, 1)
        global_worker_data['weighted_counts'] = {'AOU': 1.2}
        global_worker_data['assignments_per_mod'] = {mod: {} for mod in allowed_modalities}
        for mod in allowed_modalities:
            modality_data[mod]['skill_counts'] = {}

        with patch('data_manager.scheduled_tasks.get_local_now', return_value=datetime(2026, 3, 2, 8, 0, 0)), \
             patch('data_manager.worker_management.invalidate_work_hours_cache'), \
             patch('data_manager.file_ops.initialize_data_from_unified', return_value=False), \
             patch('data_manager.file_ops.backup_dataframe'), \
             patch('data_manager.state_persistence.save_state'), \
             patch('data_manager.scheduled_tasks.os.path.exists', return_value=False), \
             patch('data_manager.scheduled_tasks.FLOW_SNAPSHOT_LOGGER.info') as mock_flow_log:
            scheduled_tasks.check_and_perform_daily_reset()

        self.assertEqual(global_worker_data['flow_cross_pool'], {})
        self.assertEqual(global_worker_data['last_reset_date'], date(2026, 3, 2))
        self.assertTrue(mock_flow_log.called)

        snapshot_payload = json.loads(mock_flow_log.call_args.args[0])
        self.assertEqual(snapshot_payload['event'], 'daily_flow_snapshot')
        self.assertEqual(snapshot_payload['snapshot_date'], '2026-03-01')
        self.assertEqual(snapshot_payload['total_cross_pool'], 3.5)
        self.assertEqual(snapshot_payload['flow_cross_pool'], {'aou': {'cvt': 3.5}})


if __name__ == '__main__':
    unittest.main()
