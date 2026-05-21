import os
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask
import pandas as pd

from config import allowed_modalities
from routes import routes
import routes as routes_module
from data_manager import global_worker_data
import data_manager.file_ops as file_ops


class TestHealthEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__, template_folder="../templates")
        app.secret_key = "test-secret"
        app.register_blueprint(routes)
        self.client = app.test_client()

    def test_healthz_returns_ok(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "RadIMO Cortex")
        self.assertIn("timestamp", payload)

    @patch("routes.run_operational_checks")
    def test_readyz_returns_200_when_no_errors(self, mock_checks) -> None:
        mock_checks.return_value = {
            "results": [
                {"name": "Config File", "status": "OK", "detail": "Loaded"},
                {"name": "Worker Data", "status": "WARNING", "detail": "No workers"},
            ],
            "timestamp": "2026-02-10T12:00:00+01:00",
        }

        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["summary"]["error"], 0)

    @patch("routes.run_operational_checks")
    def test_readyz_returns_503_when_error_exists(self, mock_checks) -> None:
        mock_checks.return_value = {
            "results": [
                {"name": "Upload Folder", "status": "ERROR", "detail": "Not writable"},
            ],
            "timestamp": "2026-02-10T12:00:00+01:00",
        }

        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["summary"]["error"], 1)

    @patch("routes.run_operational_checks")
    def test_status_page_renders(self, mock_checks) -> None:
        mock_checks.return_value = {
            "results": [
                {"name": "Config File", "status": "OK", "detail": "Loaded"},
            ],
            "timestamp": "2026-02-10T12:00:00+01:00",
        }

        response = self.client.get("/status")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Readiness Checks", response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_index_page_does_not_render_strict_buttons(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        response = self.client.get("/?modality=ct")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_skill_page_does_not_render_strict_buttons(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        response = self.client.get("/by-skill")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    def test_dashboard_pages_send_no_store_cache_headers(self, _mock_access) -> None:
        for path in ("/?modality=mr", "/by-skill?skill=AOU&modality=mr"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")
            self.assertEqual(response.headers.get("Pragma"), "no-cache")
            self.assertEqual(response.headers.get("Expires"), "0")

    def test_logout_redirect_sends_no_store_headers(self) -> None:
        with self.client.session_transaction() as session_ctx:
            session_ctx["admin_logged_in"] = True

        response = self.client.get("/logout?modality=mr")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?modality=mr", response.location)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_strict_button_visible", side_effect=lambda skill, modality: skill == "notfall" and modality == "ct")
    def test_index_page_renders_strict_button_when_enabled(self, _mock_visibility, _mock_access) -> None:
        response = self.client.get("/?modality=ct")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_xray_page_shows_normal_notfall_privat_mdh_and_hides_other_specialty_buttons(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        response = self.client.get("/?modality=xray")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="special-btn-xray-normal"', response.data)
        self.assertIn(b'id="skill-btn-notfall"', response.data)
        self.assertIn(b'id="skill-btn-privat"', response.data)
        self.assertIn(b'id="skill-btn-mdh"', response.data)
        self.assertNotIn(b'id="skill-btn-gyn"', response.data)
        self.assertNotIn(b'id="skill-btn-aou"', response.data)
        self.assertNotIn(b'id="skill-btn-cvt"', response.data)
        self.assertLess(
            response.data.index(b'id="special-btn-xray-normal"'),
            response.data.index(b'id="skill-btn-notfall"'),
        )

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_xray_page_shows_mdh_without_strict_button(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        response = self.client.get("/?modality=xray")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="skill-btn-mdh"', response.data)
        self.assertIn(b'title="MSK / Derma / Hals"', response.data)
        self.assertNotIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", side_effect=lambda skill, modality: skill == "mdh" and modality in {"ct", "mr"})
    def test_ct_and_mr_pages_render_mdh_strict_button_when_enabled(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        ct_response = self.client.get("/?modality=ct")
        mr_response = self.client.get("/?modality=mr")

        self.assertEqual(ct_response.status_code, 200)
        self.assertEqual(mr_response.status_code, 200)
        self.assertIn(b'aria-label="Strikte Zuweisung"', ct_response.data)
        self.assertIn(b'aria-label="Strikte Zuweisung"', mr_response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    def test_notfall_uses_no_overflow_without_strict_button_by_config(
        self,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        ct_response = self.client.get("/?modality=ct")
        mr_response = self.client.get("/?modality=mr")
        xray_response = self.client.get("/?modality=xray")

        self.assertEqual(ct_response.status_code, 200)
        self.assertEqual(mr_response.status_code, 200)
        self.assertEqual(xray_response.status_code, 200)
        self.assertNotIn(b"getNextAssignment('notfall', 'Notfall', true)", ct_response.data)
        self.assertNotIn(b"getNextAssignment('notfall', 'Notfall', true)", mr_response.data)
        self.assertNotIn(b"getNextAssignment('notfall', 'Notfall', true)", xray_response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_ct_and_mr_herz_buttons_are_hidden_when_disabled(
        self,
        _mock_visibility,
        _mock_special_visibility,
        _mock_access,
    ) -> None:
        ct_response = self.client.get("/?modality=ct")
        mr_response = self.client.get("/?modality=mr")

        self.assertEqual(ct_response.status_code, 200)
        self.assertEqual(mr_response.status_code, 200)
        self.assertNotIn(b'id="special-btn-ct-herz"', ct_response.data)
        self.assertNotIn(b'id="special-btn-mr-herz"', mr_response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_strict_button_visible", side_effect=lambda skill, modality: skill == "notfall" and modality == "ct")
    def test_skill_page_renders_strict_button_when_enabled(self, _mock_visibility, _mock_access) -> None:
        response = self.client.get("/by-skill?skill=notfall")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_no_overflow", return_value=True)
    @patch("routes.get_next_available_worker")
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_no_overflow_regular_route_keeps_normal_weight_mode(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_worker,
        _mock_no_overflow,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "notfall": 1},
            "notfall",
            "ct",
        )

        response = self.client.get("/api/ct/notfall")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_no_overflow", return_value=True)
    @patch("routes.get_next_available_worker")
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_notfall_xray_regular_route_keeps_normal_weight_mode(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_worker,
        _mock_no_overflow,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "notfall": 1},
            "notfall",
            "xray",
        )

        response = self.client.get("/api/xray/notfall")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.get_next_available_worker")
    @patch("routes.get_special_task_weight", return_value=1.0)
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_special_task_regular_route_keeps_normal_special_weight_mode(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_special_weight,
        mock_get_worker,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "cvt": 1},
            "cvt",
            "ct",
        )

        response = self.client.get("/api/ct/aou-ct-seg")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])
        self.assertFalse(mock_get_special_weight.call_args.kwargs["strict"])

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.get_next_available_worker")
    @patch("routes.get_special_task_weight", return_value=1.0)
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_xray_normal_special_task_routes_to_cvt_only(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_special_weight,
        mock_get_worker,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "cvt": 1},
            "cvt",
            "xray",
        )

        response = self.client.get("/api/xray/xray-normal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_get_worker.call_args.kwargs["target_skill_modalities"], [("cvt", "xray")])
        self.assertEqual(mock_get_worker.call_args.kwargs["role"], "cvt")
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])
        self.assertFalse(mock_get_special_weight.call_args.kwargs["strict"])

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_no_overflow", return_value=True)
    @patch("routes.get_next_available_worker")
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_mdh_xray_regular_route_keeps_normal_weights_but_no_overflow(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_worker,
        _mock_no_overflow,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "mdh": 1},
            "mdh",
            "xray",
        )

        response = self.client.get("/api/xray/mdh")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])
        self.assertFalse(mock_get_worker.call_args.kwargs["allow_overflow"])

    @patch("routes.has_admin_access", return_value=True)
    def test_balance_summary_page_renders_management_sections(self, _mock_admin) -> None:
        response = self.client.get("/performance")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Performance", response.data)
        self.assertIn("Tageslast".encode("utf-8"), response.data)
        self.assertIn("Lasttreiber".encode("utf-8"), response.data)
        self.assertIn("Gesamtansicht".encode("utf-8"), response.data)
        self.assertIn(b'id="summary-overview"', response.data)
        self.assertIn(b'id="daily-load-skill-chart"', response.data)
        self.assertIn(b'id="leaders-skill-total"', response.data)
        self.assertIn(b'id="leaders-overflow"', response.data)
        self.assertNotIn(b"Top Skills / Hour", response.data)
        self.assertNotIn(b"Top Modalities / Hour", response.data)
        self.assertIn(b'js/balance_summary.js', response.data)

    def test_balance_summary_js_labels_manual_adjustment_component(self) -> None:
        with open("static/js/balance_summary.js", "r", encoding="utf-8") as js_file:
            script = js_file.read()

        self.assertIn("manual_adjustment", script)
        self.assertIn("davon manuelle Anpassung", script)

    @patch("routes.has_admin_access", return_value=True)
    def test_balance_summary_route_redirects_to_performance(self, _mock_admin) -> None:
        response = self.client.get("/balance-summary?modality=mr")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/performance?modality=mr", response.location)

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_simple_mode_renders_global_table_without_extra_summary_blocks(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=simple")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="table-global"', response.data)
        self.assertIn(b'Weight / Hour', response.data)
        self.assertIn(b'Total Weight', response.data)
        self.assertIn(b'<th class="sortable" data-sort="manual_adjustment"', response.data)
        self.assertIn(b"Weighted Matrix", response.data)
        self.assertIn(b"Count Matrix", response.data)
        self.assertIn(b"Recent Events", response.data)
        self.assertNotIn(b'id="summary-modality"', response.data)
        self.assertNotIn(b'id="summary-skill"', response.data)
        self.assertNotIn(b'id="summary-modality-hour"', response.data)
        self.assertNotIn(b'id="summary-skill-hour"', response.data)
        self.assertNotIn(b'id="summary-overview"', response.data)

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_advanced_weight_mode_renders_derived_weight_matrix(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=advanced-weight")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="table-advanced-weight"', response.data)
        self.assertIn(b'Derived load view using assignment count', response.data)

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_advanced_count_mode_renders_count_matrix(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=advanced-count")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="table-advanced-count"', response.data)
        self.assertIn(b'Raw assignment counts', response.data)

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_recent_mode_renders_recent_distribution_table(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=recent")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="table-recent"', response.data)
        self.assertIn(b'Recent Assignment Events', response.data)

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.allowed_modalities", ["ct"])
    @patch.dict(
        "routes.modality_data",
        {
            "ct": {
                "working_hours_df": pd.DataFrame(
                    [
                        {
                            "PPL": "Worker One",
                            "start_time": pd.Timestamp("2026-03-27 08:00:00"),
                            "end_time": pd.Timestamp("2026-03-27 10:00:00"),
                            "Modifier": 1.0,
                        }
                    ]
                ),
            }
        },
        clear=True,
    )
    @patch("routes.get_canonical_worker_id", side_effect=lambda name: "worker-one")
    @patch("routes.calculate_global_work_hours_now", return_value={"worker-one": 2.0})
    @patch("routes.get_global_base_weighted_count", return_value=3.5)
    @patch("routes.get_manual_weight_adjustment", return_value=0.5)
    @patch("routes.get_global_weighted_count", return_value=4.0)
    @patch("routes.get_global_assignments", return_value={"total": 2})
    @patch("routes.get_modality_weighted_count", return_value=4.0)
    def test_worker_load_api_exposes_weight_per_hour(
        self,
        *_mocks,
    ) -> None:
        response = self.client.get("/api/worker-load/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["max_weight_per_hour"], 2.0)
        worker = payload["workers"][0]
        self.assertEqual(worker["hours_worked_now"], 2.0)
        self.assertEqual(worker["weight_per_hour"], 2.0)
        self.assertEqual(worker["balance_weight"], 3.5)
        self.assertEqual(worker["manual_adjustment"], 0.5)
        self.assertEqual(worker["global_weight"], 4.0)
        self.assertEqual(worker["global_assignments"]["total"], 2)
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["valid_worker_threshold_hours"], 1.0)
        self.assertIn("skills_per_hour", payload["summary"])
        self.assertIn("modalities_per_hour", payload["summary"])

    @patch("routes.has_admin_access", return_value=True)
    def test_manual_adjustments_page_renders(self, _mock_admin) -> None:
        response = self.client.get("/manual-adjustments")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Adjust Weight", response.data)
        self.assertIn(b"Your name", response.data)
        self.assertIn(b'id="manual-worker-body"', response.data)
        self.assertIn(b'js/manual_adjustments.js', response.data)

        script_path = os.path.join(os.path.dirname(__file__), "..", "static/js/manual_adjustments.js")
        with open(script_path, encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("Manual adjust", script)

    @patch("routes.has_admin_access", return_value=False)
    def test_manual_adjustments_nav_hidden_without_admin_access(self, _mock_admin) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Adjust Weight", response.data)
        self.assertIn(b"Admin", response.data)

    def test_manual_adjustments_page_requires_admin_session(self) -> None:
        response = self.client.get("/manual-adjustments")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?modality=ct", response.location)

    def test_manual_adjustments_api_requires_admin_session(self) -> None:
        response = self.client.get("/api/manual-adjustments")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?modality=ct", response.location)

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes._get_manual_adjustment_deltas", return_value=[-1.0, 1.0])
    @patch("routes._build_manual_adjustment_workers", return_value=[
        {
            "canonical_id": "worker-one",
            "name": "Worker One",
            "hours_worked_now": 2.0,
            "balance_weight": 3.0,
            "manual_adjustment": 0.0,
            "total_weight": 3.0,
        }
    ])
    def test_manual_adjustments_api_returns_workers_and_log(self, _mock_workers, _mock_deltas, _mock_admin) -> None:
        original_log = list(routes_module.global_worker_data.get("manual_weight_adjustments", []))
        try:
            routes_module.global_worker_data["manual_weight_adjustments"] = [
                {"admin_name": "MR", "worker_id": "worker-one", "delta": 1.0}
            ]
            response = self.client.get("/api/manual-adjustments")
        finally:
            routes_module.global_worker_data["manual_weight_adjustments"] = original_log

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["allowed_deltas"], [-1.0, 1.0])
        self.assertEqual(payload["workers"][0]["canonical_id"], "worker-one")
        self.assertEqual(payload["adjustments"][0]["admin_name"], "MR")

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.get_admin_password", return_value="secret")
    @patch("routes._get_manual_adjustment_deltas", return_value=[-1.0, 1.0])
    @patch("routes._build_manual_adjustment_workers", return_value=[
        {
            "canonical_id": "worker-one",
            "name": "Worker One",
            "hours_worked_now": 2.0,
            "balance_weight": 3.0,
            "manual_adjustment": 0.0,
            "total_weight": 3.0,
        }
    ])
    @patch("routes.get_global_base_weighted_count", return_value=3.0)
    @patch("routes.save_state")
    def test_manual_adjustment_publish_updates_manual_state_not_assignment_counts(
        self,
        mock_save_state,
        _mock_base,
        _mock_workers,
        _mock_deltas,
        _mock_password,
        _mock_admin,
    ) -> None:
        original_totals = dict(routes_module.global_worker_data.get("manual_weight_totals", {}))
        original_log = list(routes_module.global_worker_data.get("manual_weight_adjustments", []))
        original_assignments = json.loads(json.dumps(routes_module.global_worker_data.get("assignments_per_mod", {})))
        try:
            routes_module.global_worker_data["manual_weight_totals"] = {}
            routes_module.global_worker_data["manual_weight_adjustments"] = []
            response = self.client.post(
                "/api/manual-adjustments",
                json={
                    "worker_id": "worker-one",
                    "delta": 1.0,
                    "admin_name": "MR",
                    "reason": "Wrong booking correction",
                    "admin_password": "secret",
                },
                environ_base={"REMOTE_ADDR": "10.1.2.3"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            self.assertEqual(routes_module.global_worker_data["manual_weight_totals"]["worker-one"], 1.0)
            self.assertEqual(
                routes_module.global_worker_data.get("assignments_per_mod", {}),
                original_assignments,
            )
            entry = payload["entry"]
            self.assertEqual(entry["admin_name"], "MR")
            self.assertEqual(entry["client_ip"], "10.1.2.3")
            self.assertNotIn("user_agent", entry)
            self.assertEqual(entry["total_after"], 4.0)
            mock_save_state.assert_called_once()
        finally:
            routes_module.global_worker_data["manual_weight_totals"] = original_totals
            routes_module.global_worker_data["manual_weight_adjustments"] = original_log

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.get_admin_password", return_value="secret")
    @patch("routes._get_manual_adjustment_deltas", return_value=[-1.0, 1.0])
    @patch("routes._build_manual_adjustment_workers", return_value=[
        {
            "canonical_id": "worker-one",
            "name": "Worker One",
            "hours_worked_now": 2.0,
            "balance_weight": 3.0,
            "manual_adjustment": 0.0,
            "total_weight": 3.0,
        }
    ])
    def test_manual_adjustment_publish_rejects_wrong_password(
        self,
        _mock_workers,
        _mock_deltas,
        _mock_password,
        _mock_admin,
    ) -> None:
        response = self.client.post(
            "/api/manual-adjustments",
            json={
                "worker_id": "worker-one",
                "delta": 1.0,
                "admin_name": "MR",
                "reason": "Wrong booking correction",
                "admin_password": "bad",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Admin password confirmation failed")

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_recent_distributions_api_returns_latest_items(self, _mock_admin) -> None:
        original_recent = list(routes_module.global_worker_data.get("recent_distributions", []))
        try:
            routes_module.global_worker_data["recent_distributions"] = [
                {
                    "timestamp": "2026-04-20T09:00:00",
                    "person": "Worker One",
                    "canonical_id": "worker-one",
                    "requested_skill": "aou",
                    "requested_modality": "ct",
                    "actual_skill": "cvt",
                    "actual_modality": "ct",
                    "weight": 1.5,
                    "overflowed": True,
                    "unresolved": False,
                    "task_label": "Task A",
                }
            ]

            response = self.client.get("/api/worker-load/recent-distributions")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["limit"], 1)
            self.assertEqual(payload["items"][0]["requested_skill"], "aou")
            self.assertTrue(payload["items"][0]["overflowed"])
            self.assertEqual(payload["items"][0]["person_raw"], "Worker One")
            self.assertEqual(payload["items"][0]["person"], "One, Worker (worker-one)")
        finally:
            routes_module.global_worker_data["recent_distributions"] = original_recent

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_daily_load_api_returns_cumulative_time_series(self, _mock_admin) -> None:
        original_events = list(routes_module.global_worker_data.get("daily_load_events", []))
        try:
            routes_module.global_worker_data["daily_load_events"] = []
            routes_module._record_daily_load_event(
                requested_skill="aou",
                requested_modality="ct",
                request_weight=1.5,
                timestamp=datetime(2026, 4, 20, 8, 30),
            )
            routes_module._record_daily_load_event(
                requested_skill="aou",
                requested_modality="mr",
                request_weight=2.0,
                timestamp=datetime(2026, 4, 20, 10, 0),
            )
            routes_module._record_daily_load_event(
                requested_skill="cvt",
                requested_modality="ct",
                request_weight=0.5,
                timestamp=datetime(2026, 4, 20, 21, 30),
            )

            response = self.client.get("/api/worker-load/daily-load")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["meta"]["start_label"], "07:00")
            self.assertEqual(payload["meta"]["end_label"], "21:00")
            self.assertEqual(payload["event_count"], 3)
            self.assertEqual(payload["total_weight"], 4.0)

            skill_series = {item["key"]: item for item in payload["skill_series"]}
            modality_series = {item["key"]: item for item in payload["modality_series"]}
            self.assertEqual(skill_series["aou"]["total"], 3.5)
            self.assertEqual(skill_series["cvt"]["total"], 0.5)
            self.assertEqual(modality_series["ct"]["total"], 2.0)
            self.assertEqual(modality_series["mr"]["total"], 2.0)
            self.assertEqual(skill_series["cvt"]["points"][-1], [1260, 0.5])
            self.assertTrue(all(
                skill_series["aou"]["points"][idx][1] <= skill_series["aou"]["points"][idx + 1][1]
                for idx in range(len(skill_series["aou"]["points"]) - 1)
            ))
        finally:
            routes_module.global_worker_data["daily_load_events"] = original_events

    def test_distribution_request_records_daily_load_event(self) -> None:
        original_events = list(routes_module.global_worker_data.get("daily_load_events", []))
        original_stats = dict(routes_module.global_worker_data.get("distribution_stats", {}))
        try:
            routes_module.global_worker_data["daily_load_events"] = []
            routes_module.global_worker_data["distribution_stats"] = {}

            recorded = routes_module._record_distribution_request(
                requested_skill="aou",
                requested_modality="ct",
                request_weight=1.25,
            )

            self.assertTrue(recorded)
            self.assertEqual(len(routes_module.global_worker_data["daily_load_events"]), 1)
            event = routes_module.global_worker_data["daily_load_events"][0]
            self.assertEqual(event["requested_skill"], "aou")
            self.assertEqual(event["requested_modality"], "ct")
            self.assertEqual(event["weight"], 1.25)
        finally:
            routes_module.global_worker_data["daily_load_events"] = original_events
            routes_module.global_worker_data["distribution_stats"] = original_stats

    @patch("routes._df_to_api_response", return_value={})
    @patch("routes._get_staged_target_date", return_value=datetime(2026, 4, 8).date())
    @patch("routes._ensure_next_workday_preloaded")
    @patch.dict(
        "routes.staged_modality_data",
        {
            "ct": {
                "working_hours_df": pd.DataFrame([{"PPL": "Worker One"}]),
                "last_modified": datetime(2026, 4, 2, 12, 12),
                "last_prepped_at": "02.04.2026 12:12",
                "target_date": datetime(2026, 4, 8).date(),
            }
        },
        clear=True,
    )
    @patch("routes.allowed_modalities", ["ct"])
    @patch("routes.has_admin_access", return_value=True)
    def test_prep_data_exposes_freshness_status(self, *_mocks) -> None:
        response = self.client.get("/api/prep-next-day/data")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["prep_loaded_label"], "Mittwoch (08.04.2026)")
        self.assertEqual(payload["prep_last_edit_label"], "02.04.2026 12:12")

    @patch("routes.has_admin_access", return_value=True)
    def test_prep_pages_expose_segmented_gap_task_roles_in_page_config(self, _mock_admin) -> None:
        for path in ("/prep-tomorrow", "/prep-today"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'"segments"', response.data)
            self.assertIn(b"ZGT Ausgleich", response.data)

    @patch("routes.update_schedule_row", return_value=(True, {"reindexed": False}))
    @patch("routes._validate_modality", return_value=None)
    @patch("routes._get_snapshot_version", return_value="token-1")
    @patch("routes.reload_staged_data_from_disk", return_value=True)
    @patch("routes._get_staged_target_date", return_value=datetime(2026, 4, 8).date())
    @patch("routes.has_admin_access", return_value=True)
    def test_prep_update_row_uses_request_target_date(
        self,
        _mock_admin,
        _mock_get_staged_date,
        mock_reload_staged,
        mock_get_snapshot,
        _mock_validate,
        _mock_update,
    ) -> None:
        target_date = datetime(2026, 4, 20).date()

        response = self.client.post(
            "/api/prep-next-day/update-row",
            json={
                "target_date": target_date.isoformat(),
                "snapshot_version": "token-1",
                "modality": "ct",
                "row_index": 0,
                "updates": {"Modifier": 1.1},
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_reload_staged.assert_called_once_with(target_date=target_date)
        self.assertTrue(
            any(
                kwargs.get("target_date") == target_date
                for _args, kwargs in mock_get_snapshot.call_args_list
            )
        )

    @patch("routes.update_schedule_row", return_value=(True, {"reindexed": False}))
    @patch("routes._validate_modality", return_value=None)
    @patch("routes._get_snapshot_version", return_value="token-current")
    @patch("routes._get_staged_target_date", return_value=datetime(2026, 4, 20).date())
    @patch("routes.has_admin_access", return_value=True)
    def test_prep_update_row_allows_missing_snapshot_token_for_current_target(
        self,
        _mock_admin,
        _mock_get_staged_date,
        mock_get_snapshot,
        _mock_validate,
        _mock_update,
    ) -> None:
        target_date = datetime(2026, 4, 20).date()

        response = self.client.post(
            "/api/prep-next-day/update-row",
            json={
                "target_date": target_date.isoformat(),
                "modality": "ct",
                "row_index": 0,
                "updates": {"Modifier": 1.1},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["snapshot_version"], "token-current")
        self.assertTrue(
            any(
                kwargs.get("target_date") == target_date
                for _args, kwargs in mock_get_snapshot.call_args_list
            )
        )

    @patch("routes.save_state")
    @patch("routes.preload_next_workday")
    @patch("routes.reload_staged_data_from_disk", return_value=True)
    @patch("routes._get_staged_target_date", return_value=datetime(2026, 4, 8).date())
    @patch("routes.get_next_workday", return_value=datetime(2026, 4, 8))
    @patch("routes._maybe_reload_runtime_config")
    @patch("routes.os.path.exists", return_value=True)
    @patch("routes.has_admin_access", return_value=True)
    def test_prep_preload_prefers_saved_staged_data_when_not_forced(
        self,
        _mock_admin,
        _mock_exists,
        _mock_reload_runtime,
        _mock_next_workday,
        mock_get_staged_date,
        mock_reload_staged,
        mock_preload,
        mock_save_state,
    ) -> None:
        response = self.client.post(
            "/preload-from-master",
            json={"target_date": "2026-04-08", "force_csv": False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["target_date"], "2026-04-08")
        self.assertIn("Gespeicherte Staging-Daten", payload["message"])
        mock_reload_staged.assert_called_once_with(target_date=datetime(2026, 4, 8).date())
        mock_preload.assert_not_called()
        mock_save_state.assert_called_once()

    @patch("routes.save_state")
    @patch("routes.reload_staged_data_from_disk", return_value=True)
    @patch("routes._get_staged_target_date", return_value=datetime(2026, 4, 8).date())
    @patch("routes.get_next_workday", return_value=datetime(2026, 4, 8))
    def test_ensure_next_workday_preloaded_restores_snapshot_after_restart(
        self,
        _mock_next_workday,
        _mock_get_staged_date,
        mock_reload_staged,
        mock_save_state,
    ) -> None:
        next_day = datetime(2026, 4, 8).date()

        with patch.dict(
            "routes.global_worker_data",
            {"last_preload_date": next_day, "last_preload_source": "csv"},
            clear=False,
        ):
            routes_module._ensure_next_workday_preloaded()
            mock_reload_staged.assert_called_once_with(target_date=next_day)
            mock_save_state.assert_called_once()
            self.assertEqual(routes_module.global_worker_data["last_preload_date"], next_day)
            self.assertEqual(routes_module.global_worker_data["last_preload_source"], "snapshot")

    @patch("routes.render_template", return_value="rendered")
    @patch("routes._ensure_next_workday_preloaded")
    @patch("routes._get_staged_target_date", side_effect=[None, datetime(2026, 4, 8).date()])
    @patch("routes.get_next_workday", return_value=datetime(2026, 4, 8))
    @patch("routes.has_admin_access", return_value=True)
    def test_prep_tomorrow_refreshes_staged_target_after_preload(
        self,
        _mock_admin,
        _mock_next_workday,
        _mock_get_staged_date,
        _mock_ensure,
        mock_render_template,
    ) -> None:
        routes_module._render_prep_page("tomorrow")

        self.assertTrue(mock_render_template.called)
        self.assertEqual(mock_render_template.call_args.kwargs["target_date"], "2026-04-08")

    def test_reload_staged_data_prefers_day_snapshot_over_generic_snapshot(self) -> None:
        target_date = datetime(2026, 4, 8).date()
        other_date = datetime(2026, 4, 9).date()

        with tempfile.TemporaryDirectory() as tmpdir:
            backups_dir = f"{tmpdir}/backups"
            staged_days_dir = f"{backups_dir}/staged_days"
            os.makedirs(staged_days_dir, exist_ok=True)

            generic_path = f"{backups_dir}/Cortex_ALL_staged.json"
            target_path = f"{staged_days_dir}/Cortex_ALL_staged_{target_date.isoformat()}.json"

            with open(generic_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "working_hours": [
                            {
                                "modality": "ct",
                                "PPL": "Wrong Worker",
                                "TIME": "07:30-15:30",
                                "Modifier": 1.0,
                            }
                        ],
                        "info_texts": {},
                        "info_texts_by_skill": {},
                        "metadata": {"ct": {"target_date": other_date.isoformat()}},
                    },
                    f,
                )

            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "working_hours": [
                            {
                                "modality": "ct",
                                "PPL": "Target Worker",
                                "TIME": "07:30-15:30",
                                "Modifier": 1.0,
                            }
                        ],
                        "info_texts": {},
                        "info_texts_by_skill": {},
                        "metadata": {"ct": {"target_date": target_date.isoformat()}},
                    },
                    f,
                )

            staged_state = {
                "ct": {
                    "working_hours_df": None,
                    "info_texts": [],
                    "info_texts_by_skill": {},
                    "total_work_hours": {},
                    "worker_modifiers": {},
                    "last_modified": None,
                    "last_prepped_at": None,
                    "last_prepped_by": None,
                    "target_date": None,
                }
            }

            with patch.object(file_ops, "UPLOAD_FOLDER", tmpdir), patch.object(
                file_ops,
                "allowed_modalities",
                ["ct"],
            ), patch.object(
                file_ops,
                "modality_data",
                {"ct": {}},
            ), patch.object(
                file_ops,
                "staged_modality_data",
                staged_state,
            ), patch.object(
                file_ops,
                "unified_schedule_paths",
                {
                    "scheduled": f"{backups_dir}/Cortex_ALL_scheduled.json",
                    "live": f"{backups_dir}/Cortex_ALL_live.json",
                    "scheduled_backup": f"{backups_dir}/Cortex_ALL_scheduled.json",
                },
            ), patch.object(
                file_ops,
                "_unified_load_state",
                {"live": False, "staged": False, "scheduled": False},
            ):
                loaded = file_ops.reload_staged_data_from_disk(target_date=target_date)
                self.assertTrue(loaded)
                self.assertEqual(file_ops.staged_modality_data["ct"]["target_date"], target_date)
                self.assertEqual(
                    file_ops.staged_modality_data["ct"]["working_hours_df"].iloc[0]["PPL"],
                    "Target Worker",
                )

    def test_reload_staged_data_accepts_top_level_target_date_metadata(self) -> None:
        target_date = datetime(2026, 4, 20).date()

        with tempfile.TemporaryDirectory() as tmpdir:
            backups_dir = f"{tmpdir}/backups"
            staged_days_dir = f"{backups_dir}/staged_days"
            os.makedirs(staged_days_dir, exist_ok=True)

            target_path = f"{staged_days_dir}/Cortex_ALL_staged_{target_date.isoformat()}.json"
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "working_hours": [
                            {
                                "modality": "ct",
                                "PPL": "Future Worker",
                                "TIME": "07:30-15:30",
                                "Modifier": 1.0,
                            }
                        ],
                        "info_texts": {},
                        "info_texts_by_skill": {},
                        "metadata": {"target_date": target_date.isoformat()},
                    },
                    f,
                )

            staged_state = {
                "ct": {
                    "working_hours_df": None,
                    "info_texts": [],
                    "info_texts_by_skill": {},
                    "total_work_hours": {},
                    "worker_modifiers": {},
                    "last_modified": None,
                    "last_prepped_at": None,
                    "last_prepped_by": None,
                    "target_date": None,
                }
            }

            with patch.object(file_ops, "UPLOAD_FOLDER", tmpdir), patch.object(
                file_ops,
                "allowed_modalities",
                ["ct"],
            ), patch.object(
                file_ops,
                "modality_data",
                {"ct": {}},
            ), patch.object(
                file_ops,
                "staged_modality_data",
                staged_state,
            ), patch.object(
                file_ops,
                "unified_schedule_paths",
                {
                    "scheduled": f"{backups_dir}/Cortex_ALL_scheduled.json",
                    "live": f"{backups_dir}/Cortex_ALL_live.json",
                    "scheduled_backup": f"{backups_dir}/Cortex_ALL_scheduled.json",
                },
            ), patch.object(
                file_ops,
                "_unified_load_state",
                {"live": False, "staged": False, "scheduled": False},
            ):
                loaded = file_ops.reload_staged_data_from_disk(target_date=target_date)
                self.assertTrue(loaded)
                self.assertEqual(file_ops.staged_modality_data["ct"]["target_date"], target_date)
                self.assertEqual(
                    file_ops.staged_modality_data["ct"]["working_hours_df"].iloc[0]["PPL"],
                    "Future Worker",
                )

    def test_reload_staged_data_accepts_empty_top_level_target_date_snapshot(self) -> None:
        target_date = datetime(2026, 4, 21).date()

        with tempfile.TemporaryDirectory() as tmpdir:
            backups_dir = f"{tmpdir}/backups"
            staged_days_dir = f"{backups_dir}/staged_days"
            os.makedirs(staged_days_dir, exist_ok=True)

            target_path = f"{staged_days_dir}/Cortex_ALL_staged_{target_date.isoformat()}.json"
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "working_hours": [],
                        "info_texts": {},
                        "info_texts_by_skill": {},
                        "metadata": {"target_date": target_date.isoformat()},
                    },
                    f,
                )

            staged_state = {
                "ct": {
                    "working_hours_df": None,
                    "info_texts": [],
                    "info_texts_by_skill": {},
                    "total_work_hours": {},
                    "worker_modifiers": {},
                    "last_modified": None,
                    "last_prepped_at": None,
                    "last_prepped_by": None,
                    "target_date": None,
                }
            }

            with patch.object(file_ops, "UPLOAD_FOLDER", tmpdir), patch.object(
                file_ops,
                "allowed_modalities",
                ["ct"],
            ), patch.object(
                file_ops,
                "modality_data",
                {"ct": {}},
            ), patch.object(
                file_ops,
                "staged_modality_data",
                staged_state,
            ), patch.object(
                file_ops,
                "unified_schedule_paths",
                {
                    "scheduled": f"{backups_dir}/Cortex_ALL_scheduled.json",
                    "live": f"{backups_dir}/Cortex_ALL_live.json",
                    "scheduled_backup": f"{backups_dir}/Cortex_ALL_scheduled.json",
                },
            ), patch.object(
                file_ops,
                "_unified_load_state",
                {"live": False, "staged": False, "scheduled": False},
            ):
                loaded = file_ops.reload_staged_data_from_disk(target_date=target_date)
                self.assertTrue(loaded)
                self.assertEqual(file_ops.staged_modality_data["ct"]["target_date"], target_date)
                self.assertTrue(file_ops.staged_modality_data["ct"]["working_hours_df"].empty)

    def test_reload_staged_data_does_not_fall_back_to_generic_snapshot(self) -> None:
        target_date = datetime(2026, 4, 8).date()
        other_date = datetime(2026, 4, 9).date()

        with tempfile.TemporaryDirectory() as tmpdir:
            backups_dir = f"{tmpdir}/backups"
            staged_days_dir = f"{backups_dir}/staged_days"
            os.makedirs(staged_days_dir, exist_ok=True)

            generic_path = f"{backups_dir}/Cortex_ALL_staged.json"
            target_path = f"{staged_days_dir}/Cortex_ALL_staged_{target_date.isoformat()}.json"

            with open(generic_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "working_hours": [
                            {
                                "modality": "ct",
                                "PPL": "Wrong Worker",
                                "TIME": "07:30-15:30",
                                "Modifier": 1.0,
                            }
                        ],
                        "info_texts": {},
                        "info_texts_by_skill": {},
                        "metadata": {"ct": {"target_date": other_date.isoformat()}},
                    },
                    f,
                )

            staged_state = {
                "ct": {
                    "working_hours_df": pd.DataFrame([{"PPL": "Stale Worker"}]),
                    "info_texts": ["stale"],
                    "info_texts_by_skill": {},
                    "total_work_hours": {},
                    "worker_modifiers": {},
                    "last_modified": datetime(2026, 4, 1, 10, 0),
                    "last_prepped_at": "01.04.2026 10:00",
                    "last_prepped_by": None,
                    "target_date": None,
                }
            }

            with patch.object(file_ops, "UPLOAD_FOLDER", tmpdir), patch.object(
                file_ops,
                "allowed_modalities",
                ["ct"],
            ), patch.object(
                file_ops,
                "modality_data",
                {"ct": {}},
            ), patch.object(
                file_ops,
                "staged_modality_data",
                staged_state,
            ), patch.object(
                file_ops,
                "unified_schedule_paths",
                {
                    "scheduled": f"{backups_dir}/Cortex_ALL_scheduled.json",
                    "live": f"{backups_dir}/Cortex_ALL_live.json",
                    "scheduled_backup": f"{backups_dir}/Cortex_ALL_scheduled.json",
                },
            ), patch.object(
                file_ops,
                "_unified_load_state",
                {"live": False, "staged": False, "scheduled": False},
            ):
                loaded = file_ops.reload_staged_data_from_disk(target_date=target_date)
                self.assertFalse(loaded)
                self.assertIsNone(file_ops.staged_modality_data["ct"]["working_hours_df"])
                self.assertEqual(file_ops.staged_modality_data["ct"]["target_date"], None)

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_flow_mode_hides_granular_flow_rows(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=flow")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="flow-diagram"', response.data)
        self.assertNotIn(b'id="flow-rows"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    def test_timetable_uses_shared_timeline_feed_config(self, _mock_access) -> None:
        response = self.client.get("/timetable?modality=all")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'js/timeline_feed.js', response.data)
        self.assertIn(b'dataByModality:', response.data)
        self.assertIn(b'taskRoles:', response.data)
        self.assertIn(b'workerSkills:', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.get_next_available_worker")
    @patch("routes.update_global_assignment", return_value="TT")
    @patch("routes.save_state")
    @patch("routes._record_cross_pool_flow", return_value=False)
    @patch("routes.usage_logger.record_skill_modality_usage")
    @patch("routes.usage_logger.check_and_export_at_scheduled_time")
    def test_strict_route_uses_strict_weight_mode(
        self,
        _mock_export,
        _mock_usage,
        _mock_flow,
        _mock_save,
        mock_update,
        mock_get_worker,
        _mock_access,
    ) -> None:
        mock_get_worker.return_value = (
            {"PPL": "Tester (TT)", "Modifier": 1.0, "notfall": 1},
            "notfall",
            "ct",
        )

        response = self.client.get("/api/ct/notfall/strict")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_update.call_args.kwargs["strict_mode"])

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.persist_live_backup")
    @patch("routes.save_state")
    @patch("routes.auto_populate_skill_roster", return_value=(0, []))
    @patch("routes.build_working_hours_from_medweb")
    @patch("routes.pd.read_csv")
    @patch("routes._maybe_reload_runtime_config", return_value=None)
    @patch("routes.get_local_now", return_value=datetime(2026, 3, 23, 10, 0, 0))
    @patch("routes.os.path.exists", return_value=True)
    def test_load_today_from_master_persists_live_backup_on_success(
        self,
        _mock_exists,
        _mock_now,
        _mock_reload,
        mock_read_csv,
        mock_build,
        _mock_auto_populate,
        _mock_save_state,
        mock_persist_live_backup,
        _mock_admin,
    ) -> None:
        mock_read_csv.return_value = pd.DataFrame({
            "Datum": ["23.03.2026"],
            "Beschreibung der Aktivität": ["Shift A"],
        })
        mock_build.return_value = {
            allowed_modalities[0]: pd.DataFrame({"PPL": ["Tester (TT)"]}),
        }

        response = self.client.post("/load-today-from-master")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        mock_persist_live_backup.assert_called_once()

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.persist_live_backup")
    @patch("routes.save_state")
    @patch("routes.auto_populate_skill_roster", return_value=(0, []))
    @patch("routes.build_working_hours_from_medweb")
    @patch("routes.pd.read_csv")
    @patch("routes._maybe_reload_runtime_config", return_value=None)
    @patch("routes.get_local_now", return_value=datetime(2026, 3, 23, 10, 0, 0))
    @patch("routes.os.path.exists", return_value=True)
    def test_load_today_from_master_clears_flow_counters_on_success(
        self,
        _mock_exists,
        _mock_now,
        _mock_reload,
        mock_read_csv,
        mock_build,
        _mock_auto_populate,
        _mock_save_state,
        _mock_persist_live_backup,
        _mock_admin,
    ) -> None:
        mock_read_csv.return_value = pd.DataFrame({
            "Datum": ["23.03.2026"],
            "Beschreibung der Aktivität": ["Shift A"],
        })
        mock_build.return_value = {
            allowed_modalities[0]: pd.DataFrame({"PPL": ["Tester (TT)"]}),
        }
        global_worker_data["flow_cross_pool"] = {"aou": {"cvt": 2.5}}

        response = self.client.post("/load-today-from-master")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(global_worker_data["flow_cross_pool"], {})

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.persist_live_backup")
    @patch("routes.save_state")
    @patch("routes.build_working_hours_from_medweb", return_value={})
    @patch("routes.pd.read_csv")
    @patch("routes._maybe_reload_runtime_config", return_value=None)
    @patch("routes.get_local_now", return_value=datetime(2026, 3, 23, 10, 0, 0))
    @patch("routes.os.path.exists", return_value=True)
    def test_load_today_from_master_persists_live_backup_when_reload_clears_day(
        self,
        _mock_exists,
        _mock_now,
        _mock_reload,
        mock_read_csv,
        _mock_build,
        _mock_save_state,
        mock_persist_live_backup,
        _mock_admin,
    ) -> None:
        mock_read_csv.return_value = pd.DataFrame({
            "Datum": ["24.03.2026"],
            "Beschreibung der Aktivität": ["Shift A"],
        })

        response = self.client.post("/load-today-from-master")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total_workers"], 0)
        mock_persist_live_backup.assert_called_once()

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.persist_live_backup")
    @patch("routes.save_state")
    @patch("routes.build_working_hours_from_medweb", return_value={})
    @patch("routes.pd.read_csv")
    @patch("routes._maybe_reload_runtime_config", return_value=None)
    @patch("routes.get_local_now", return_value=datetime(2026, 3, 23, 10, 0, 0))
    @patch("routes.os.path.exists", return_value=True)
    def test_load_today_from_master_clears_flow_counters_when_reload_clears_day(
        self,
        _mock_exists,
        _mock_now,
        _mock_reload,
        mock_read_csv,
        _mock_build,
        _mock_save_state,
        _mock_persist_live_backup,
        _mock_admin,
    ) -> None:
        mock_read_csv.return_value = pd.DataFrame({
            "Datum": ["24.03.2026"],
            "Beschreibung der Aktivität": ["Shift A"],
        })
        global_worker_data["flow_cross_pool"] = {"gyn": {"aou": 1.0}}

        response = self.client.post("/load-today-from-master")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(global_worker_data["flow_cross_pool"], {})

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.get_missing_csv_worker_candidates", return_value=[
        {
            "worker_id": "B2",
            "full_name": "Bob (B2)",
            "display_name": "Bob (B2)",
            "auto_import_eligible": False,
            "source_activity": "Urlaub",
            "source_date": "23.01.2026",
        }
    ])
    @patch("routes.build_worker_name_mapping", return_value={"A1": "Alice (A1)"})
    @patch("routes.load_worker_skill_json", return_value={"A1": {"full_name": "Alice (A1)"}})
    def test_skill_roster_api_includes_csv_candidates(
        self,
        _mock_load_roster,
        _mock_name_map,
        _mock_candidates,
        _mock_admin,
    ) -> None:
        response = self.client.get("/api/admin/skill_roster")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["csv_candidates"][0]["worker_id"], "B2")

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes.import_csv_worker_to_skill_roster", return_value={
        "worker_id": "B2",
        "full_name": "Bob (B2)",
        "display_name": "Bob (B2)",
        "auto_import_eligible": False,
        "source_activity": "Urlaub",
        "source_date": "23.01.2026",
    })
    def test_import_csv_skill_roster_worker_api_imports_selected_worker(
        self,
        mock_import,
        _mock_admin,
    ) -> None:
        response = self.client.post(
            "/api/admin/skill_roster/import_csv_worker",
            json={"worker_id": "B2"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["worker_id"], "B2")
        mock_import.assert_called_once()


if __name__ == "__main__":
    unittest.main()
