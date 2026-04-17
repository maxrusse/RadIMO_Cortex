import unittest
from datetime import date
from unittest.mock import patch

from config import SKILL_COLUMNS, allowed_modalities
import routes


class TestTaskPreviewResolution(unittest.TestCase):
    def setUp(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
