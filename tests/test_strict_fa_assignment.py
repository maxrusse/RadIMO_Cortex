"""Exercise FÄ coverage through CSV import, strict routing and manual selection."""
import copy
from datetime import datetime

import pandas as pd
import pytest

import balancer
import routes
from app import app
from config import APP_CONFIG
from data_manager.csv_parser import build_working_hours_from_medweb


@pytest.fixture
def fa_schedule(tmp_path, monkeypatch):
    config = copy.deepcopy(APP_CONFIG)
    config.pop('synthetic_shifts', None)
    config['medweb_mapping'].pop('synthetic_shifts', None)
    # Use the actual configured FÄ rules, without unrelated synthetic workers.
    config['medweb_mapping']['rules'] = [
        rule for rule in config['medweb_mapping']['rules']
        if rule.get('match') == 'SBZ: FÄ'
    ]
    assert config['medweb_mapping']['rules']

    def install(day_part='VMNM', roster_value=1, now=None):
        roster = {'FA_TEST': {'all': -1, 'mdh_MR': roster_value, 'aou_mr': 1}}
        monkeypatch.setattr('data_manager.csv_parser.get_merged_worker_roster',
                            lambda config: roster)
        csv_path = tmp_path / 'fa.csv'
        pd.DataFrame([{
            'Datum': '27.10.2026', 'Tageszeit': day_part,
            'Beschreibung der Aktivität': 'SBZ: FÄ',
            'Name des Mitarbeiters': 'Synthetic FA',
            'Personalnummer': 'FA_TEST',
        }]).to_csv(csv_path, index=False)
        frames = build_working_hours_from_medweb(
            str(csv_path), datetime(2026, 10, 27), config)
        for modality, data in balancer.modality_data.items():
            monkeypatch.setitem(data, 'working_hours_df', frames.get(modality, pd.DataFrame()))
        balancer.get_state().invalidate_work_hours_cache()
        monkeypatch.setattr(routes, 'get_local_now',
                            lambda: now or datetime(2026, 10, 27, 14, 0))
        return frames

    yield install
    balancer.get_state().invalidate_work_hours_cache()


@pytest.mark.parametrize('day_part,hour', [('VM', 10), ('VMNM', 14), ('NM', 14)])
@pytest.mark.parametrize('roster_value', [1, '1', 'w'])
def test_only_fa_with_mdh_mr_is_available_to_strict_assignment(
        fa_schedule, day_part, hour, roster_value):
    now = datetime(2026, 10, 27, hour, 0)
    frames = fa_schedule(day_part, roster_value, now)
    assert frames['mr']['mdh'].map(str).eq(str(roster_value)).all()

    result = balancer.get_next_available_worker(
        now, role='mdh', modality='mr', allow_overflow=False)
    assert result is not None
    candidate, skill, modality = result
    assert candidate['PPL'] == 'Synthetic FA (FA_TEST)'
    assert (skill, modality) == ('mdh', 'mr')
    assert candidate['__is_weighted'] == (roster_value == 'w')

    candidates = routes._get_strict_manual_candidates_for_button(now, 'mdh', 'mr')
    assert len(candidates) == 1
    assert candidates[0]['canonical_id'] == 'FA_TEST'


@pytest.mark.parametrize('manual', [False, True])
def test_strict_api_assigns_only_fa_and_uses_strict_weights(fa_schedule, monkeypatch, manual):
    fa_schedule()
    recorded = []
    monkeypatch.setattr(routes, 'update_global_assignment',
                        lambda *args, **kwargs: recorded.append(kwargs) or 'FA_TEST')
    monkeypatch.setattr(routes, 'save_state', lambda: None)
    monkeypatch.setattr(routes.usage_logger, 'record_skill_modality_usage', lambda *args: None)
    monkeypatch.setattr(routes.usage_logger, 'check_and_export_at_scheduled_time', lambda: None)
    if manual:
        now = datetime(2026, 10, 27, 14)
        candidates = routes._get_strict_manual_candidates_for_button(now, 'mdh', 'mr')
        with app.test_request_context('/api/mr/mdh/strict/manual', method='POST',
                                      json={'candidate_key': candidates[0]['candidate_key']}):
            response = routes.assign_worker_strict_manual_api.__wrapped__('mr', 'mdh')
    else:
        with app.test_request_context('/api/mr/mdh/strict'):
            response = routes.assign_worker_strict_api.__wrapped__('mr', 'mdh')
    assert response.status_code == 200
    assert response.get_json()['canonical_id'] == 'FA_TEST'
    assert response.get_json()['manual_selection'] is manual
    assert recorded[0]['strict_mode'] is True


@pytest.mark.parametrize('roster_value', [0, -1])
def test_fa_rule_respects_roster_exclusion_but_promotes_passive_skills(
        fa_schedule, roster_value):
    fa_schedule(roster_value=roster_value)
    result = balancer.get_next_available_worker(
        datetime(2026, 10, 27, 14), role='mdh', modality='mr', allow_overflow=False)
    assert (result is not None) == (roster_value == 0)


def test_fa_is_unavailable_outside_shift(fa_schedule):
    fa_schedule(day_part='NM')
    assert balancer.get_next_available_worker(
        datetime(2026, 10, 27, 10), role='mdh', modality='mr', allow_overflow=False) is None


@pytest.mark.parametrize('skill_value,row_type', [('0', 'shift_segment'), ('-1', 'shift_segment'),
                                                ('1', 'gap_segment')])
def test_strict_rejects_generalist_excluded_and_gap_rows(fa_schedule, skill_value, row_type):
    frames = fa_schedule()
    frames['mr']['mdh'] = skill_value
    frames['mr']['row_type'] = row_type
    now = datetime(2026, 10, 27, 14)
    assert balancer.get_next_available_worker(
        now, role='mdh', modality='mr', allow_overflow=False) is None
    assert routes._get_strict_manual_candidates_for_button(now, 'mdh', 'mr') == []


def test_configured_exclusion_can_remove_otherwise_eligible_fa(fa_schedule, monkeypatch):
    frames = fa_schedule()
    frames['mr']['aou'] = '1'
    monkeypatch.setitem(balancer.EXCLUDE_SKILLS, 'mdh', ['aou'])
    now = datetime(2026, 10, 27, 14)
    assert balancer.get_next_available_worker(
        now, role='mdh', modality='mr', allow_overflow=False) is None
    assert routes._get_strict_manual_candidates_for_button(now, 'mdh', 'mr') == []
