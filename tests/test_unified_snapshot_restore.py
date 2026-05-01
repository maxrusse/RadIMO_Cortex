import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import data_manager.file_ops as file_ops
from config import SKILL_COLUMNS, allowed_modalities
from data_manager import modality_data


class TestUnifiedSnapshotRestore(unittest.TestCase):
    def setUp(self) -> None:
        self.modality = "ct" if "ct" in allowed_modalities else allowed_modalities[0]
        self.skill = "aou" if "aou" in SKILL_COLUMNS else SKILL_COLUMNS[0]
        for mod in allowed_modalities:
            modality_data[mod]["working_hours_df"] = pd.DataFrame()

    def _records(self) -> list[dict]:
        row = {
            "PPL": "Probe Worker (PROBE)",
            "TIME": "08:00-16:00",
            "Modifier": 1.0,
            "tasks": "Probe Shift",
            "counts_for_hours": True,
            "row_type": "shift_segment",
            "training": True,
            "modality": self.modality,
        }
        for skill in SKILL_COLUMNS:
            row[skill] = 0
        row[self.skill] = 1
        return [row]

    def test_generated_records_still_enforce_roster_exclusion(self) -> None:
        original_get_merged = file_ops.get_merged_worker_roster
        original_get_combinations = file_ops.get_worker_skill_mod_combinations
        try:
            combinations = {
                f"{skill}_{modality}": 0
                for modality in allowed_modalities
                for skill in SKILL_COLUMNS
            }
            combinations[f"{self.skill}_{self.modality}"] = "-1"
            file_ops.get_merged_worker_roster = lambda config: {}
            file_ops.get_worker_skill_mod_combinations = lambda canonical_id, roster: dict(combinations)

            df = file_ops._build_dataframe_from_records(
                [
                    {key: value for key, value in self._records()[0].items() if key != "modality"}
                ],
                self.modality,
                validate=True,
            )

            self.assertEqual(str(df.iloc[0][self.skill]), "-1")
        finally:
            file_ops.get_merged_worker_roster = original_get_merged
            file_ops.get_worker_skill_mod_combinations = original_get_combinations

    def test_unified_snapshot_restore_preserves_stored_skill_values(self) -> None:
        original_get_merged = file_ops.get_merged_worker_roster
        original_get_combinations = file_ops.get_worker_skill_mod_combinations
        try:
            combinations = {
                f"{skill}_{modality}": 0
                for modality in allowed_modalities
                for skill in SKILL_COLUMNS
            }
            combinations[f"{self.skill}_{self.modality}"] = "-1"
            file_ops.get_merged_worker_roster = lambda config: {}
            file_ops.get_worker_skill_mod_combinations = lambda canonical_id, roster: dict(combinations)

            payload = {
                "working_hours": self._records(),
                "info_texts": {},
                "info_texts_by_skill": {},
            }
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "Cortex_ALL_staged_probe.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

                self.assertTrue(file_ops.initialize_data_from_unified(str(path), context="test"))

            df = modality_data[self.modality]["working_hours_df"]
            self.assertEqual(str(df.iloc[0][self.skill]), "1")
            self.assertEqual(df.iloc[0]["TIME"], "08:00-16:00")
        finally:
            file_ops.get_merged_worker_roster = original_get_merged
            file_ops.get_worker_skill_mod_combinations = original_get_combinations


if __name__ == "__main__":
    unittest.main()
