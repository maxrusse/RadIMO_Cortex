from unittest.mock import patch

from flask import Flask
import pandas as pd
import pytest

import routes


@pytest.mark.parametrize("scheduled", [False, True])
def test_worker_load_keeps_recorded_balances_after_schedule_removal(monkeypatch, scheduled):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(routes.routes)
    monkeypatch.setattr(routes, "has_admin_access", lambda: True)
    monkeypatch.setattr(routes, "allowed_modalities", ["ct", "mr"])
    monkeypatch.setattr(routes, "SKILL_COLUMNS", ["A"])
    monkeypatch.setattr(routes, "global_worker_data", {
        "assignments_per_mod": {"ct": {"assigned": {"A": 3}}, "mr": None},
        "manual_weight_totals": {"corrected": -1.0},
    })
    frame = pd.DataFrame([{
        "PPL": "assigned", "start_time": pd.Timestamp("2026-10-15 07:00"),
        "end_time": pd.Timestamp("2026-10-15 15:00"), "A": 1,
    }]) if scheduled else pd.DataFrame()
    monkeypatch.setattr(routes, "modality_data", {
        "ct": {"working_hours_df": pd.DataFrame()},
        "mr": {"working_hours_df": frame},
    })
    monkeypatch.setattr(routes, "get_canonical_worker_id", lambda name: name)
    monkeypatch.setattr(routes, "_get_preferred_display_name", lambda worker_id: worker_id)
    monkeypatch.setattr(routes, "calculate_global_work_hours_now", lambda now: {})
    monkeypatch.setattr(routes, "get_global_base_weighted_count", lambda worker_id: 6.0 if worker_id == "assigned" else 0.0)
    monkeypatch.setattr(routes, "get_manual_weight_adjustment", lambda worker_id: -1.0 if worker_id == "corrected" else 0.0)
    monkeypatch.setattr(routes, "get_global_weighted_count", lambda worker_id: 6.0 if worker_id == "assigned" else -1.0)
    monkeypatch.setattr(routes, "get_global_assignments", lambda worker_id: {"A": 3} if worker_id == "assigned" else {})
    monkeypatch.setattr(routes, "get_modality_weighted_count", lambda worker_id, mod: 6.0 if mod == "ct" else 0.0)
    monkeypatch.setattr(routes, "get_skill_modality_weight", lambda skill, mod: 2.0)

    response = app.test_client().get("/api/worker-load/data")
    assert response.status_code == 200
    workers = {worker["canonical_id"]: worker for worker in response.get_json()["workers"]}
    assert set(workers) == {"assigned", "corrected"}
    assert workers["assigned"]["skills"] == {"A": 3}
    assert workers["assigned"]["skill_weights"] == {"A": 6.0}
    assert workers["assigned"]["modalities"]["ct"]["assignment_total"] == 3
    assert workers["assigned"]["modalities"]["ct"]["start_time"] == ""
    assert workers["assigned"]["global_weight"] == 6.0
    assert workers["corrected"]["manual_adjustment"] == -1.0
    assert workers["corrected"]["global_weight"] == -1.0
    assert workers["corrected"]["hours_worked_now"] == 0.0
    assert workers["corrected"]["weight_per_hour"] == 0.0
    if scheduled:
        assert workers["assigned"]["modalities"]["mr"]["start_time"] == "07:00"

    # The displayed historical worker remains eligible for an authenticated reversal.
    with app.test_request_context(), patch("routes.get_admin_password", return_value="test-password"):
        payload, error = routes._verify_manual_adjustment_payload({
            "worker_id": "corrected", "admin_name": "Test", "reason": "Reverse correction",
            "delta": routes._get_manual_adjustment_deltas()[0], "admin_password": "test-password",
        })
    assert error is None
    assert payload["worker_id"] == "corrected"
