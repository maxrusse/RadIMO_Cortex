import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask
import pandas as pd

from config import allowed_modalities
from routes import routes
from data_manager import global_worker_data


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
    @patch("routes.is_strict_button_visible", side_effect=lambda skill, modality: skill == "notfall" and modality == "ct")
    def test_index_page_renders_strict_button_when_enabled(self, _mock_visibility, _mock_access) -> None:
        response = self.client.get("/?modality=ct")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Strikte Zuweisung"', response.data)

    @patch("routes.is_access_protection_enabled", return_value=False)
    @patch("routes.is_special_task_strict_button_visible", return_value=False)
    @patch("routes.is_strict_button_visible", return_value=False)
    def test_xray_page_shows_normal_notfall_privat_and_hides_specialty_buttons(
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
        self.assertNotIn(b'id="skill-btn-gyn"', response.data)
        self.assertNotIn(b'id="skill-btn-aou"', response.data)
        self.assertNotIn(b'id="skill-btn-cvt"', response.data)
        self.assertNotIn(b'id="skill-btn-mhd"', response.data)
        self.assertLess(
            response.data.index(b'id="special-btn-xray-normal"'),
            response.data.index(b'id="skill-btn-notfall"'),
        )

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

    @patch("routes.has_admin_access", return_value=True)
    def test_worker_load_simple_mode_renders_summary_sections_without_detail_tables(self, _mock_admin) -> None:
        response = self.client.get("/worker-load?mode=simple")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="table-global"', response.data)
        self.assertIn(b'id="summary-modality"', response.data)
        self.assertIn(b'id="summary-skill"', response.data)
        self.assertNotIn(b'id="table-modality"', response.data)
        self.assertNotIn(b'id="table-skill"', response.data)

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


if __name__ == "__main__":
    unittest.main()
