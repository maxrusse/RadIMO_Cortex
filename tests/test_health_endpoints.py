import unittest
from unittest.mock import patch

from flask import Flask

from routes import routes


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
        self.assertIn(b'data-skill-name="gyn" style="display: none"', response.data)
        self.assertIn(b'data-skill-name="aou" style="display: none"', response.data)
        self.assertIn(b'data-skill-name="cvt" style="display: none"', response.data)
        self.assertIn(b'data-skill-name="mhd" style="display: none"', response.data)

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

        response = self.client.get("/api/ct/ct-herz")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(mock_update.call_args.kwargs["strict_mode"])
        self.assertFalse(mock_get_special_weight.call_args.kwargs["strict"])

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


if __name__ == "__main__":
    unittest.main()
