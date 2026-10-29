import unittest
import copy
from datetime import time
from unittest.mock import patch

import pandas as pd

from config import SKILL_COLUMNS, allowed_modalities
from data_manager import schedule_crud


class TestGapBatch(unittest.TestCase):
    def setUp(self) -> None:
        self.modalities = allowed_modalities[:2]
        self.original_data = {modality: copy.deepcopy(schedule_crud.modality_data[modality])
                              for modality in self.modalities}
        self.original_global = copy.deepcopy(schedule_crud.global_worker_data)
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
        for modality, data in self.original_data.items():
            schedule_crud.modality_data[modality].clear()
            schedule_crud.modality_data[modality].update(data)
        schedule_crud.global_worker_data.clear()
        schedule_crud.global_worker_data.update(self.original_global)

    def test_add_gap_batch_updates_all_modalities_atomically(self) -> None:
        with (
            patch.object(schedule_crud, "persist_schedule_snapshot") as persist,
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
        persist.assert_called_once_with(use_staged=False)

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

    def test_gap_batch_persistence_failure_restores_all_frames_and_tracking(self) -> None:
        before = {mod: schedule_crud.modality_data[mod]['working_hours_df'].copy(deep=True)
                  for mod in self.modalities}
        tracking_before = copy.deepcopy(schedule_crud.global_worker_data)

        def change_tracking(modality):
            schedule_crud.global_worker_data['weighted_counts'] = {'synthetic': 999}

        with (
            patch.object(schedule_crud, 'persist_schedule_snapshot', side_effect=OSError('disk full')),
            patch.object(schedule_crud, 'reconcile_live_worker_tracking', side_effect=change_tracking),
            patch.object(schedule_crud, 'attach_schedule_change') as audit,
        ):
            success, _, error = schedule_crud.add_gap_to_schedule_batch(
                {mod: 0 for mod in self.modalities}, 'Break', '09:00', '10:00', False)
        self.assertFalse(success)
        self.assertIn('could not be persisted', error)
        for mod in self.modalities:
            pd.testing.assert_frame_equal(schedule_crud.modality_data[mod]['working_hours_df'], before[mod])
        self.assertEqual(schedule_crud.global_worker_data, tracking_before)
        audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
