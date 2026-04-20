from datetime import datetime, time
from unittest.mock import patch
import unittest

import pandas as pd

import balancer
from data_manager import global_worker_data, modality_data
from state_manager import get_state


class TestWarmStartOverflowMode(unittest.TestCase):
    def setUp(self) -> None:
        self.current_dt = datetime(2026, 3, 2, 12, 0)
        self.modality = "ct"
        self.skill = "notfall"
        self.df = pd.DataFrame(
            [
                {"PPL": "S1", "start_time": time(8, 0), "end_time": time(16, 0), self.skill: 1},
                {"PPL": "S2", "start_time": time(8, 0), "end_time": time(16, 0), self.skill: 1},
                {"PPL": "G1", "start_time": time(8, 0), "end_time": time(16, 0), self.skill: 0},
            ]
        )
        self._reset_state()

    def _reset_state(self) -> None:
        for mod in list(modality_data.keys()):
            modality_data[mod]["working_hours_df"] = pd.DataFrame()

        modality_data[self.modality]["working_hours_df"] = self.df.copy()

        global_worker_data["weighted_counts"] = {}
        for mod in list(global_worker_data["assignments_per_mod"].keys()):
            global_worker_data["assignments_per_mod"][mod] = {}

        get_state().invalidate_work_hours_cache()

    def _pick(
        self,
        weighted_counts: dict[str, float],
        *,
        allow_overflow: bool,
        min_assignments: int,
        start_minutes: int,
        release_mode: str,
    ) -> str:
        global_worker_data["weighted_counts"] = dict(weighted_counts)
        with patch.dict(
            balancer.BALANCER_SETTINGS,
            {
                "enabled": True,
                "min_assignments_per_skill": min_assignments,
                "warm_start_release_mode": release_mode,
                "imbalance_threshold_pct": 20,
                "disable_overflow_at_shift_start_minutes": start_minutes,
                "disable_overflow_at_shift_end_minutes": 0,
            },
            clear=False,
        ):
            result = balancer.get_next_available_worker(
                current_dt=self.current_dt,
                role=self.skill,
                modality=self.modality,
                allow_overflow=allow_overflow,
            )
        self.assertIsNotNone(result)
        row, _, _ = result
        return str(row["PPL"])

    def test_release_mode_either_unlocks_when_time_ready(self) -> None:
        # Min-count not met, but time gate is met -> overflow allowed in "either".
        picked = self._pick(
            {"S1": 40.0, "S2": 50.0, "G1": 0.0},
            allow_overflow=True,
            min_assignments=100,
            start_minutes=60,
            release_mode="either",
        )
        self.assertEqual(picked, "G1")

    def test_release_mode_either_unlocks_when_min_ready(self) -> None:
        # Time gate not met, but min-count gate is met -> overflow allowed in "either".
        picked = self._pick(
            {"S1": 40.0, "S2": 50.0, "G1": 0.0},
            allow_overflow=True,
            min_assignments=1,
            start_minutes=300,
            release_mode="either",
        )
        self.assertEqual(picked, "G1")

    def test_release_mode_either_blocks_when_neither_ready(self) -> None:
        # Neither time nor min-count ready -> stay in specialist pool.
        picked = self._pick(
            {"S1": 40.0, "S2": 50.0, "G1": 0.0},
            allow_overflow=True,
            min_assignments=100,
            start_minutes=300,
            release_mode="either",
        )
        self.assertIn(picked, {"S1", "S2"})

    def test_release_mode_both_requires_both_conditions(self) -> None:
        # Time ready but min-count not met -> overflow still blocked in "both".
        picked = self._pick(
            {"S1": 40.0, "S2": 50.0, "G1": 0.0},
            allow_overflow=True,
            min_assignments=100,
            start_minutes=60,
            release_mode="both",
        )
        self.assertIn(picked, {"S1", "S2"})

    def test_strict_mode_still_disables_overflow(self) -> None:
        picked = self._pick(
            {"S1": 40.0, "S2": 50.0, "G1": 0.0},
            allow_overflow=False,
            min_assignments=1,
            start_minutes=0,
            release_mode="either",
        )
        self.assertIn(picked, {"S1", "S2"})


if __name__ == "__main__":
    unittest.main()
