import unittest
from unittest.mock import patch

from app import app
import routes
from config import SKILL_COLUMNS, get_specialist_fallback_targets


class TestSpecialistFallbackRoutes(unittest.TestCase):
    def test_configured_specialist_fallback_targets(self) -> None:
        for skill in SKILL_COLUMNS:
            with self.subTest(skill=skill):
                targets = get_specialist_fallback_targets(skill, "ct")
                if skill == "mdh":
                    self.assertEqual(targets, [("aou", "ct"), ("cvt", "ct")])
                else:
                    self.assertEqual(targets, [])

    def test_assign_without_fallback_route_keeps_normal_overflow(self) -> None:
        candidate = {
            "PPL": "Dr. AOU",
            "Modifier": 1.0,
            "__is_weighted": False,
            "__modality_source": "ct",
            "__skill_source": "aou",
        }

        with app.test_request_context("/api/ct/aou"):
            with patch("routes.get_next_available_worker", return_value=(candidate, "aou", "ct")) as mock_next, \
                 patch("routes.update_global_assignment", return_value="AOU1"), \
                 patch("routes.save_state"), \
                 patch("routes.usage_logger.record_skill_modality_usage"), \
                 patch("routes.usage_logger.check_and_export_at_scheduled_time"):
                response = routes._assign_worker("ct", "aou", allow_overflow=True)

        self.assertEqual(response.status_code, 200)
        kwargs = mock_next.call_args.kwargs
        self.assertTrue(kwargs["allow_overflow"])
        self.assertIsNone(kwargs["target_skill_modalities"])

    def test_assign_strict_without_fallback_route_stays_strict(self) -> None:
        candidate = {
            "PPL": "Dr. Strict AOU",
            "Modifier": 1.0,
            "__is_weighted": False,
            "__modality_source": "ct",
            "__skill_source": "aou",
        }

        with app.test_request_context("/api/ct/aou/strict"):
            with patch("routes.get_next_available_worker", return_value=(candidate, "aou", "ct")) as mock_next, \
                 patch("routes.update_global_assignment", return_value="AOU2"), \
                 patch("routes.save_state"), \
                 patch("routes.usage_logger.record_skill_modality_usage"), \
                 patch("routes.usage_logger.check_and_export_at_scheduled_time"):
                response = routes._assign_worker("ct", "aou", allow_overflow=False)

        self.assertEqual(response.status_code, 200)
        kwargs = mock_next.call_args.kwargs
        self.assertFalse(kwargs["allow_overflow"])
        self.assertIsNone(kwargs["target_skill_modalities"])


if __name__ == "__main__":
    unittest.main()
