import unittest
from datetime import time
from unittest.mock import patch

import pandas as pd

from config import SKILL_COLUMNS, allowed_modalities
from data_manager import schedule_crud


class TestGapBatch(unittest.TestCase):
    def setUp(self) -> None:
        self.modalities = allowed_modalities[:2]
        self.original_frames = {
            modality: schedule_crud.modality_data[modality]["working_hours_df"]
            for modality in self.modalities
        }
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
        for modality in self.modalities:
            schedule_crud.modality_data[modality]["working_hours_df"] = pd.DataFrame([base_row])

    def tearDown(self) -> None:
        for modality, frame in self.original_frames.items():
            schedule_crud.modality_data[modality]["working_hours_df"] = frame

    def test_add_gap_batch_updates_all_modalities_atomically(self) -> None:
        with (
            patch.object(schedule_crud, "backup_dataframe"),
            patch.object(schedule_crud, "reconcile_live_worker_tracking"),
        ):
            success, _, error = schedule_crud.add_gap_to_schedule_batch(
                {modality: 0 for modality in self.modalities},
                gap_type="Break",
                gap_start="09:00",
                gap_end="10:00",
                use_staged=False,
            )
        self.assertTrue(success, msg=error)

        for modality in self.modalities:
            df = schedule_crud.modality_data[modality]["working_hours_df"]
            gap_rows = df[df["row_type"] == "gap_segment"]
            self.assertEqual(len(gap_rows), 1)
            self.assertEqual(gap_rows.iloc[0]["tasks"], "Break")
            self.assertFalse(gap_rows.iloc[0]["counts_for_hours"])
            for skill in SKILL_COLUMNS:
                self.assertEqual(gap_rows.iloc[0][skill], -1)

            shifts = df[df["row_type"] == "shift_segment"].sort_values("start_time").reset_index(drop=True)
            self.assertEqual(
                list(zip(shifts["start_time"], shifts["end_time"])),
                [(time(8, 0), time(9, 0)), (time(10, 0), time(12, 0))],
            )


if __name__ == "__main__":
    unittest.main()
