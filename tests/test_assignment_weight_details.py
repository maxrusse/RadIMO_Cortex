"""Booked weights must retain strict/modifier effects rather than reprice counts."""
from unittest.mock import Mock

import pytest
import routes


@pytest.mark.parametrize('booked, expected, exact', [(1.6, 3.2, True), (0.8, 1.6, True), (None, 3.2, False)])
def test_details_sum_booking_deltas_and_mark_legacy(monkeypatch, booked, expected, exact):
    event = {'canonical_id': 'synthetic', 'actual_modality': 'ct',
             'actual_skill': 'cvt', 'weight': 1.6, 'booked_weight': booked}
    monkeypatch.setattr(routes, 'global_worker_data', {'recent_distributions': [event, event]})
    assert routes._assignment_weight_details()[('synthetic', 'ct', 'cvt')] == {
        'count': 2, 'weight': expected, 'exact': exact}


def test_mixed_history_uses_actual_credit_when_available(monkeypatch):
    base = {'canonical_id': 'synthetic', 'actual_modality': 'ct', 'actual_skill': 'cvt'}
    monkeypatch.setattr(routes, 'global_worker_data', {'recent_distributions': [
        {**base, 'weight': 1.6}, {**base, 'weight': 1.6, 'booked_weight': 0.8},
        {**base, 'canonical_id': 'other', 'weight': 10, 'booked_weight': 10},
        {**base, 'actual_modality': 'mr', 'weight': 3, 'booked_weight': 3},
    ]})
    assert routes._assignment_weight_details()[('synthetic', 'ct', 'cvt')] == {
        'count': 2, 'weight': 2.4, 'exact': False}


def test_finalized_assignment_records_credit_separately_from_requested_weight(monkeypatch):
    monkeypatch.setattr(routes, 'global_worker_data', {'recent_distributions': []})
    monkeypatch.setattr(routes, 'get_canonical_worker_id', lambda person: 'synthetic')
    monkeypatch.setattr(routes, 'get_global_base_weighted_count', Mock(side_effect=[5.0, 5.8]))
    update = Mock(return_value='synthetic')
    monkeypatch.setattr(routes, 'update_global_assignment', update)
    monkeypatch.setattr(routes, '_resolve_flow_target_skill', lambda *args: 'cvt')
    monkeypatch.setattr(routes, '_get_cross_pool_flow_weight', lambda *args, **kwargs: 1.6)
    monkeypatch.setattr(routes, '_record_cross_pool_flow', Mock())
    monkeypatch.setattr(routes, '_record_distribution_stats', Mock())
    monkeypatch.setattr(routes.usage_logger, 'record_skill_modality_usage', Mock())
    monkeypatch.setattr(routes.usage_logger, 'check_and_export_at_scheduled_time', Mock())
    routes._finalize_assignment_candidate(
        {'PPL': 'Synthetic', 'Modifier': 2.0}, 'cvt', 'ct',
        requested_modality='ct', role='cvt', canonical_skill='cvt', use_strict_weights=True)
    event = routes.global_worker_data['recent_distributions'][0]
    assert event['weight'] == 1.6
    assert event['booked_weight'] == 0.8
    assert update.call_args.kwargs['strict_mode'] is True
