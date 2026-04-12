import unittest
from datetime import datetime, time

import pandas as pd

import balancer
from config import allowed_modalities


class TestBalancerGapFiltering(unittest.TestCase):
    def setUp(self) -> None:
        self.modality = allowed_modalities[0]
        for modality in allowed_modalities:
            balancer.modality_data[modality]["working_hours_df"] = pd.DataFrame()
        balancer.get_state().invalidate_work_hours_cache()

    def test_filter_active_rows_excludes_gaps(self) -> None:
        current_dt = datetime(2026, 1, 23, 9, 30)
        df = pd.DataFrame(
            [
                {
                    "PPL": "Alex",
                    "row_type": "shift_segment",
                    "start_time": time(8, 0),
                    "end_time": time(12, 0),
                },
                {
                    "PPL": "Alex",
                    "row_type": "gap_segment",
                    "start_time": time(9, 0),
                    "end_time": time(10, 0),
                },
            ]
        )

        active = balancer._filter_active_rows(df, current_dt)

        self.assertEqual(len(active), 1)
        self.assertEqual(active.iloc[0]["row_type"], "shift_segment")

    def test_calculate_work_hours_now_ignores_gap_rows(self) -> None:
        current_dt = datetime(2026, 1, 23, 10, 0)
        df = pd.DataFrame(
            [
                {
                    "PPL": "Alex",
                    "row_type": "shift_segment",
                    "start_time": time(8, 0),
                    "end_time": time(12, 0),
                    "counts_for_hours": True,
                },
                {
                    "PPL": "Alex",
                    "row_type": "gap_segment",
                    "start_time": time(9, 0),
                    "end_time": time(10, 0),
                    "counts_for_hours": False,
                },
            ]
        )

        balancer.modality_data[self.modality]["working_hours_df"] = df
        balancer.get_state().invalidate_work_hours_cache(self.modality)

        hours = balancer.calculate_work_hours_now(current_dt, self.modality)

        self.assertIn("Alex", hours)
        self.assertAlmostEqual(hours["Alex"], 2.0)

    def test_calculate_global_work_hours_now_merges_parallel_modalities(self) -> None:
        if len(allowed_modalities) < 2:
            self.skipTest("Need at least two modalities for overlap regression test")

        current_dt = datetime(2026, 1, 23, 10, 0)
        first_modality = allowed_modalities[0]
        second_modality = allowed_modalities[1]
        shared_shift = pd.DataFrame(
            [
                {
                    "PPL": "Alex",
                    "row_type": "shift_segment",
                    "start_time": time(8, 0),
                    "end_time": time(12, 0),
                    "counts_for_hours": True,
                }
            ]
        )

        balancer.modality_data[first_modality]["working_hours_df"] = shared_shift.copy()
        balancer.modality_data[second_modality]["working_hours_df"] = shared_shift.copy()
        balancer.get_state().invalidate_work_hours_cache()

        global_hours = balancer.calculate_global_work_hours_now(current_dt)

        self.assertIn("Alex", global_hours)
        self.assertAlmostEqual(global_hours["Alex"], 2.0)


if __name__ == "__main__":
    unittest.main()
