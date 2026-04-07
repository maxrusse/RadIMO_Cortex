import unittest
from datetime import time
from unittest.mock import patch

import pandas as pd

from config import SKILL_COLUMNS, allowed_modalities
from data_manager import schedule_crud


class TestGapCrud(unittest.TestCase):
    def setUp(self) -> None:
        self.modality = allowed_modalities[0]
        base_row = {
            "PPL": "Dana",
            "start_time": time(8, 0),
            "end_time": time(12, 0),
            "Modifier": 1.0,
            "row_type": "shift",
            "counts_for_hours": True,
            "shift_duration": 4.0,
            "tasks": "Shift",
        }
        for skill in SKILL_COLUMNS:
            base_row[skill] = 0
        schedule_crud.modality_data[self.modality]["working_hours_df"] = pd.DataFrame([base_row])
        self.other_modality = allowed_modalities[1]
        schedule_crud.modality_data[self.other_modality]["working_hours_df"] = pd.DataFrame([base_row])

    def test_add_update_remove_gap_row(self) -> None:
        with patch.object(schedule_crud, "backup_dataframe") as backup_mock:
            success, _, error = schedule_crud._add_gap_to_schedule(
                self.modality,
                row_index=0,
                gap_type="Break",
                gap_start="09:00",
                gap_end="10:00",
                use_staged=False,
            )
            self.assertTrue(success, msg=error)

            df = schedule_crud.modality_data[self.modality]["working_hours_df"]
            gap_rows = df[df["row_type"] == "gap_segment"]
            self.assertEqual(len(gap_rows), 1)
            gap_row = gap_rows.iloc[0]
            self.assertEqual(gap_row["tasks"], "Break")
            self.assertFalse(gap_row["counts_for_hours"])
            for skill in SKILL_COLUMNS:
                self.assertEqual(gap_row[skill], -1)

            success, _, error = schedule_crud._update_gap_in_schedule(
                self.modality,
                row_index=0,
                gap_index=None,
                new_start="09:30",
                new_end="10:30",
                new_activity="Updated Break",
                use_staged=False,
                gap_match={"start": "09:00", "end": "10:00", "activity": "Break"},
            )
            self.assertTrue(success, msg=error)

            df = schedule_crud.modality_data[self.modality]["working_hours_df"]
            gap_row = df[df["row_type"] == "gap_segment"].iloc[0]
            self.assertEqual(gap_row["start_time"], time(9, 30))
            self.assertEqual(gap_row["end_time"], time(10, 30))
            self.assertEqual(gap_row["tasks"], "Updated Break")

            success, _, error = schedule_crud._remove_gap_from_schedule(
                self.modality,
                row_index=0,
                gap_index=None,
                use_staged=False,
                gap_match={"start": "09:30", "end": "10:30", "activity": "Updated Break"},
            )
            self.assertTrue(success, msg=error)

            df = schedule_crud.modality_data[self.modality]["working_hours_df"]
            self.assertTrue(df[df["row_type"] == "gap_segment"].empty)
            shift_rows = df[df["row_type"] == "shift_segment"]
            # Intentional behavior: removing a gap does not refill/merge missing time.
            self.assertEqual(len(shift_rows), 2)
            shift_rows = shift_rows.sort_values(by=["start_time"]).reset_index(drop=True)
            self.assertEqual(shift_rows.iloc[0]["start_time"], time(8, 0))
            self.assertEqual(shift_rows.iloc[0]["end_time"], time(9, 0))
            self.assertEqual(shift_rows.iloc[1]["start_time"], time(10, 30))
            self.assertEqual(shift_rows.iloc[1]["end_time"], time(12, 0))
            backup_mock.assert_called()

    def test_update_row_to_gap_enforces_defaults(self) -> None:
        with patch.object(schedule_crud, "backup_dataframe"):
            success, result = schedule_crud._update_schedule_row(
                self.modality,
                row_index=0,
                updates={"row_type": "gap"},
                use_staged=False,
            )
            self.assertTrue(success, msg=result)

            df = schedule_crud.modality_data[self.modality]["working_hours_df"]
            row = df.iloc[0]
            self.assertEqual(row["row_type"], "gap_segment")
            self.assertEqual(row["shift_duration"], 0.0)
            for skill in SKILL_COLUMNS:
                self.assertEqual(row[skill], -1)

    def test_add_gap_batch_updates_all_modalities_atomically(self) -> None:
        with patch.object(schedule_crud, "backup_dataframe"), patch.object(schedule_crud, "reconcile_live_worker_tracking"):
            success, _, error = schedule_crud.add_gap_to_schedule_batch(
                {
                    self.modality: 0,
                    self.other_modality: 0,
                },
                gap_type="Break",
                gap_start="09:00",
                gap_end="10:00",
                use_staged=False,
            )
            self.assertTrue(success, msg=error)

        for modality in (self.modality, self.other_modality):
            df = schedule_crud.modality_data[modality]["working_hours_df"]
            gap_rows = df[df["row_type"] == "gap_segment"]
            self.assertEqual(len(gap_rows), 1)
            gap_row = gap_rows.iloc[0]
            self.assertEqual(gap_row["tasks"], "Break")
            self.assertFalse(gap_row["counts_for_hours"])
            for skill in SKILL_COLUMNS:
                self.assertEqual(gap_row[skill], -1)

            shift_rows = df[df["row_type"] == "shift_segment"].sort_values(by=["start_time"]).reset_index(drop=True)
            self.assertEqual(len(shift_rows), 2)
            self.assertEqual(shift_rows.iloc[0]["start_time"], time(8, 0))
            self.assertEqual(shift_rows.iloc[0]["end_time"], time(9, 0))
            self.assertEqual(shift_rows.iloc[1]["start_time"], time(10, 0))
            self.assertEqual(shift_rows.iloc[1]["end_time"], time(12, 0))


if __name__ == "__main__":
    unittest.main()
