import unittest
from datetime import date
from unittest.mock import patch

from flask import Flask

from config import SKILL_COLUMNS, allowed_modalities
import routes


class TestTaskPreviewResolution(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__, template_folder="../templates")
        app.secret_key = "test-secret"
        app.register_blueprint(routes.routes)
        self.client = app.test_client()
        self.modality = allowed_modalities[0]
        self.primary_skill = SKILL_COLUMNS[0]
        self.secondary_skill = SKILL_COLUMNS[1] if len(SKILL_COLUMNS) > 1 else SKILL_COLUMNS[0]
        self.primary_key = f"{self.primary_skill}_{self.modality}"
        self.secondary_key = f"{self.secondary_skill}_{self.modality}"
        self.shift_rule = {
            "name": "Shift A",
            "type": "shift",
            "times": {"default": "08:00-12:00"},
            "skill_overrides": {self.primary_key: 1},
            "modifier": 1.0,
            "counts_for_hours": True,
            "allow_roster_exclusion_override": False,
        }

    def test_new_preview_preserves_unspecified_roster_skills(self) -> None:
        roster = {
            "A1": {
                self.primary_key: 0,
                self.secondary_key: 1,
            }
        }

        with patch("routes._build_task_roles", return_value=[self.shift_rule]), patch(
            "routes.load_worker_skill_json",
            return_value=roster,
        ):
            preview = routes._resolve_task_preview(
                worker="Alice (A1)",
                task_name="Shift A",
                training=True,
                use_staged=True,
                target_date=date(2026, 4, 16),
                mode="new",
            )

        self.assertEqual(preview["skills_by_modality"][self.modality][self.primary_skill], "1")
        self.assertEqual(preview["skills_by_modality"][self.modality][self.secondary_skill], "1")

    def test_edit_preview_uses_current_shift_as_base(self) -> None:
        roster = {
            "A1": {
                self.primary_key: 0,
                self.secondary_key: 0,
            }
        }
        current_shift = {
            "modalities": {
                self.modality: {
                    "skills": {
                        self.primary_skill: 0,
                        self.secondary_skill: 1,
                    }
                }
            }
        }

        with patch("routes._build_task_roles", return_value=[self.shift_rule]), patch(
            "routes.load_worker_skill_json",
            return_value=roster,
        ):
            preview = routes._resolve_task_preview(
                worker="Alice (A1)",
                task_name="Shift A",
                training=True,
                use_staged=True,
                target_date=date(2026, 4, 16),
                mode="edit",
                current_shift=current_shift,
            )

        self.assertEqual(preview["skills_by_modality"][self.modality][self.primary_skill], "1")
        self.assertEqual(preview["skills_by_modality"][self.modality][self.secondary_skill], "1")

    def test_new_preview_keeps_backend_weighted_training_logic(self) -> None:
        roster = {
            "A1": {
                self.primary_key: "w",
            }
        }

        with patch("routes._build_task_roles", return_value=[self.shift_rule]), patch(
            "routes.load_worker_skill_json",
            return_value=roster,
        ):
            preview = routes._resolve_task_preview(
                worker="Alice (A1)",
                task_name="Shift A",
                training=False,
                use_staged=True,
                target_date=date(2026, 4, 16),
                mode="new",
            )

        self.assertEqual(preview["skills_by_modality"][self.modality][self.primary_skill], "-1")

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes._resolve_task_preview")
    @patch("routes._resolve_preview_target_date", return_value=date(2026, 4, 18))
    def test_prep_preview_endpoint_returns_resolved_payload(
        self,
        _mock_target_date,
        mock_preview,
        _mock_admin_access,
    ) -> None:
        mock_preview.return_value = {
            "task": "Shift A",
            "row_type": "shift",
            "training": True,
            "modifier": 1.0,
            "counts_for_hours": True,
            "start_time": "08:00",
            "end_time": "12:00",
            "base_skills_by_modality": {self.modality: {self.primary_skill: "0"}},
            "skills_by_modality": {self.modality: {self.primary_skill: "1"}},
            "task_controlled_keys_by_modality": {self.modality: [self.primary_skill]},
        }

        response = self.client.post(
            "/api/prep-next-day/resolve-task-preview",
            json={"worker": "Alice (A1)", "task": "Shift A", "training": True, "target_date": "2026-04-18"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["task"], "Shift A")
        self.assertEqual(payload["target_date"], "2026-04-18")
        mock_preview.assert_called_once()
        self.assertEqual(mock_preview.call_args.kwargs["mode"], "new")
        self.assertEqual(mock_preview.call_args.kwargs["target_date"], date(2026, 4, 18))

    @patch("routes.has_admin_access", return_value=True)
    def test_prep_preview_endpoint_rejects_invalid_target_date(self, _mock_admin_access) -> None:
        response = self.client.post(
            "/api/prep-next-day/resolve-task-preview",
            json={"worker": "Alice (A1)", "task": "Shift A", "target_date": "bad-date"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid target_date. Use YYYY-MM-DD.")

    @patch("routes.has_admin_access", return_value=True)
    @patch("routes._resolve_task_preview", side_effect=ValueError("Unknown task: bogus"))
    @patch("routes.get_local_now")
    def test_live_preview_endpoint_uses_today_and_surfaces_resolver_errors(
        self,
        mock_local_now,
        _mock_preview,
        _mock_admin_access,
    ) -> None:
        class FakeNow:
            def date(self) -> date:
                return date(2026, 4, 17)

        mock_local_now.return_value = FakeNow()

        response = self.client.post(
            "/api/live-schedule/resolve-task-preview",
            json={"worker": "Alice (A1)", "task": "bogus", "mode": "edit", "current_shift": {"modalities": {}}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Unknown task: bogus")


if __name__ == "__main__":
    unittest.main()
