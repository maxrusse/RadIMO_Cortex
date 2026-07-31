import unittest
from datetime import time, date

from data_manager.schedule_crud import (
    build_day_plan_rows,
    resolve_overlapping_shifts,
)


class TestScheduleOverlap(unittest.TestCase):
    def test_build_day_plan_rows_drops_invalid_times(self) -> None:
        target_date = date(2026, 1, 23)
        rows = [
            {
                "PPL": "Dana",
                "row_type": "shift",
                "start_time": time(8, 0),
                "end_time": time(12, 0),
            },
            {
                "PPL": "Dana",
                "row_type": "shift",
                "start_time": time(9, 0),
                "end_time": None,
            },
        ]

        built = build_day_plan_rows(rows, target_date)

        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["start_time"], time(8, 0))
        self.assertEqual(built[0]["end_time"], time(12, 0))

    def test_resolve_overlapping_shifts_crops_earlier(self) -> None:
        target_date = date(2026, 1, 23)
        shifts = [
            {"PPL": "Alice", "start_time": time(8, 0), "end_time": time(12, 0)},
            {"PPL": "Alice", "start_time": time(10, 0), "end_time": time(14, 0)},
        ]

        resolved = resolve_overlapping_shifts(shifts, target_date)
        self.assertEqual(len(resolved), 2)
        first, second = resolved

        self.assertEqual(first["start_time"], time(8, 0))
        self.assertEqual(first["end_time"], time(10, 0))
        self.assertAlmostEqual(first["shift_duration"], 2.0)

        self.assertEqual(second["start_time"], time(10, 0))
        self.assertEqual(second["end_time"], time(14, 0))
        self.assertAlmostEqual(second["shift_duration"], 4.0)

if __name__ == "__main__":
    unittest.main()
