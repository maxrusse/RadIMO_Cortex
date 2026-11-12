"""Role exclusion affects compact comparisons, without discarding worker data."""
from flask import Flask
import pandas as pd
import pytest
import routes


@pytest.mark.parametrize('excluded', [True, False])
def test_role_exclusion_marks_whole_person_but_keeps_matrix_data(monkeypatch, excluded):
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(routes.routes)
    monkeypatch.setattr(routes,'has_admin_access',lambda:True)
    monkeypatch.setattr(routes,'APP_CONFIG',{'medweb_mapping':{'rules':[
        {'match':'Private source','label':'Private role','exclude_from_compact_stats':excluded}]}})
    monkeypatch.setattr(routes,'allowed_modalities',['ct','mr'])
    monkeypatch.setattr(routes,'SKILL_COLUMNS',['cvt'])
    monkeypatch.setattr(routes,'global_worker_data',{'assignments_per_mod':{},'recent_distributions':[]})
    def frame(rows):
        return pd.DataFrame([dict(PPL=name,tasks=task,cvt=1,
            start_time=pd.Timestamp('2026-11-12 07:30'),end_time=pd.Timestamp('2026-11-12 16:00')) for name,task in rows])
    monkeypatch.setattr(routes,'modality_data',{
        'ct':{'working_hours_df':frame([('Offset','Private role'),('Normal','Normal role')])},
        'mr':{'working_hours_df':frame([('Offset','Normal role')])}})
    monkeypatch.setattr(routes,'get_canonical_worker_id',lambda name:name)
    monkeypatch.setattr(routes,'calculate_global_work_hours_now',lambda now:{'Offset':2,'Normal':2})
    monkeypatch.setattr(routes,'get_global_base_weighted_count',lambda name:200 if name=='Offset' else 2)
    monkeypatch.setattr(routes,'get_global_weighted_count',lambda name:200 if name=='Offset' else 2)
    monkeypatch.setattr(routes,'get_manual_weight_adjustment',lambda name:0)
    monkeypatch.setattr(routes,'get_global_assignments',lambda name:{})
    monkeypatch.setattr(routes,'get_modality_weighted_count',lambda *args:0)
    payload=app.test_client().get('/api/worker-load/data').get_json()
    workers={w['canonical_id']:w for w in payload['workers']}
    assert set(workers)=={'Normal','Offset'}
    assert workers['Offset']['exclude_from_compact_stats'] is excluded
    assert workers['Normal']['exclude_from_compact_stats'] is False
    assert set(workers['Offset']['modalities'])=={'ct','mr'}
    assert workers['Offset']['global_weight']==200
    assert payload['summary']['global']['max_worker_per_hour']['canonical_id']==('Normal' if excluded else 'Offset')


def test_unmarked_roles_are_not_excluded_and_synthetic_flags_are_supported(monkeypatch):
    monkeypatch.setattr(routes,'APP_CONFIG',{
        'medweb_mapping':{'rules':[{'match':'Normal'},{'match':'Private','exclude_from_compact_stats':True}]},
        'synthetic_shifts':[{'use_shift':'Kinderarzt','exclude_from_compact_stats':True}]})
    assert routes._compact_excluded_role_names()=={'Private','Kinderarzt'}
