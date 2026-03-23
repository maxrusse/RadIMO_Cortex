import unittest

from config import SKILL_COLUMNS, allowed_modalities
from data_manager.worker_management import apply_skill_overrides


class TestWorkerSkillOverrides(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = SKILL_COLUMNS[0]
        self.modality = allowed_modalities[0]
        self.key = f"{self.skill}_{self.modality}"

    def test_weighted_roster_with_shift_one_stays_weighted(self) -> None:
        result = apply_skill_overrides(
            {self.key: 'w'},
            {self.key: 1},
        )
        self.assertEqual(result[self.key], 'w')

    def test_weighted_roster_with_shift_weighted_stays_weighted(self) -> None:
        result = apply_skill_overrides(
            {self.key: 'w'},
            {self.key: 'w'},
        )
        self.assertEqual(result[self.key], 'w')

    def test_weighted_roster_with_shift_zero_becomes_excluded(self) -> None:
        result = apply_skill_overrides(
            {self.key: 'w'},
            {self.key: 0},
        )
        self.assertEqual(result[self.key], '-1')

    def test_weighted_roster_with_shift_excluded_stays_excluded(self) -> None:
        result = apply_skill_overrides(
            {self.key: 'w'},
            {self.key: -1},
        )
        self.assertEqual(result[self.key], '-1')


if __name__ == "__main__":
    unittest.main()
