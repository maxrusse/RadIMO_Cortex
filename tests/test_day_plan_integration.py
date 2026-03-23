import csv
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from config import SKILL_COLUMNS, allowed_modalities
from data_manager import schedule_crud
from data_manager import worker_management
from data_manager.csv_parser import build_working_hours_from_medweb


class TestDayPlanIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.modality = allowed_modalities[0]
        schedule_crud.modality_data[self.modality]["working_hours_df"] = pd.DataFrame()

    def test_csv_import_matches_edit_flow(self) -> None:
        target_date = datetime(2026, 1, 23)
        worker_name = "Alice (A1)"
        skill_key = SKILL_COLUMNS[0]
        skill_override_key = f"{skill_key}_{self.modality}"

        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [
                    {
                        "match": "Shift A",
                        "type": "shift",
                        "label": "Shift A",
                        "times": {"default": "08:00-12:00"},
                        "skill_overrides": {skill_override_key: 1},
                    },
                    {
                        "match": "Shift B",
                        "type": "shift",
                        "label": "Shift B",
                        "times": {"default": "10:00-14:00"},
                        "skill_overrides": {skill_override_key: 1},
                    },
                    {
                        "match": "Break",
                        "type": "gap",
                        "label": "Break",
                        "times": {"default": "09:00-09:30"},
                        "counts_for_hours": False,
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {
                "A1": {
                    f"{skill_key}_{self.modality}": 0,
                }
            },
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Beschreibung der Aktivität",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                    ]
                )
                writer.writerow(["23.01.2026", "Shift A", "Alice", "A1"])
                writer.writerow(["23.01.2026", "Shift B", "Alice", "A1"])
                writer.writerow(["23.01.2026", "Break", "Alice", "A1"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]

            with patch.object(schedule_crud, "backup_dataframe"):
                base_skills = {skill: 0 for skill in SKILL_COLUMNS}
                base_skills[skill_key] = 1
                for worker_data in [
                    {
                        "PPL": worker_name,
                        "start_time": "08:00",
                        "end_time": "12:00",
                        "tasks": "Shift A",
                        "Modifier": 1.0,
                        "row_type": "shift",
                        "counts_for_hours": True,
                        **base_skills,
                    },
                    {
                        "PPL": worker_name,
                        "start_time": "10:00",
                        "end_time": "14:00",
                        "tasks": "Shift B",
                        "Modifier": 1.0,
                        "row_type": "shift",
                        "counts_for_hours": True,
                        **base_skills,
                    },
                    {
                        "PPL": worker_name,
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "tasks": "Break",
                        "Modifier": 1.0,
                        "row_type": "gap",
                        "counts_for_hours": False,
                    },
                ]:
                    success, _, error = schedule_crud._add_worker_to_schedule(
                        self.modality,
                        worker_data,
                        use_staged=False,
                    )
                    self.assertTrue(success, msg=error)

            edit_df = schedule_crud.modality_data[self.modality]["working_hours_df"]

            cols = [
                "PPL",
                "row_type",
                "start_time",
                "end_time",
                "tasks",
                "Modifier",
                "counts_for_hours",
                "shift_duration",
                *SKILL_COLUMNS,
            ]

            csv_norm = csv_df[cols].copy()
            edit_norm = edit_df[cols].copy()

            sort_cols = ["row_type", "start_time", "end_time", "tasks"]
            csv_norm = csv_norm.sort_values(by=sort_cols).reset_index(drop=True)
            edit_norm = edit_norm.sort_values(by=sort_cols).reset_index(drop=True)
            csv_norm["shift_duration"] = csv_norm["shift_duration"].round(4)
            edit_norm["shift_duration"] = edit_norm["shift_duration"].round(4)

            assert_frame_equal(csv_norm, edit_norm, check_dtype=False)
        finally:
            os.unlink(csv_path)

    def test_missing_roster_worker_stays_excluded(self) -> None:
        target_date = datetime(2026, 1, 23)
        skill_key = SKILL_COLUMNS[0]
        skill_override_key = f"{skill_key}_{self.modality}"

        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [
                    {
                        "match": "Shift A",
                        "type": "shift",
                        "label": "Shift A",
                        "times": {"default": "08:00-12:00"},
                        "skill_overrides": {skill_override_key: 1},
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {},
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Beschreibung der Aktivität",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                    ]
                )
                writer.writerow(["23.01.2026", "Shift A", "Alice", "A1"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]
            self.assertEqual(len(csv_df), 1)
            for skill in SKILL_COLUMNS:
                self.assertEqual(str(csv_df.iloc[0][skill]), "-1")
        finally:
            os.unlink(csv_path)

    def test_auto_import_new_worker_defaults_to_passive_zero(self) -> None:
        df = pd.DataFrame([
            {"PPL": "Alice (A1)"},
        ])

        worker_management.worker_skill_json_roster.clear()
        try:
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}), \
                 patch("data_manager.worker_management.save_worker_skill_json") as mock_save:
                added_count, added_workers = worker_management.auto_populate_skill_roster(
                    {self.modality: df}
                )

            self.assertEqual(added_count, 1)
            self.assertEqual(added_workers, ["A1"])
            saved_roster = mock_save.call_args.args[0]
            self.assertEqual(saved_roster["A1"]["full_name"], "Alice (A1)")
            for skill in SKILL_COLUMNS:
                for modality in allowed_modalities:
                    self.assertEqual(saved_roster["A1"][f"{skill}_{modality}"], 0)
        finally:
            worker_management.worker_skill_json_roster.clear()

    def test_auto_import_existing_worker_backfills_full_name_and_saves(self) -> None:
        df = pd.DataFrame([
            {"PPL": "Alice (A1)"},
        ])

        existing_roster = {
            "A1": {
                f"{skill}_{modality}": 0
                for skill in SKILL_COLUMNS
                for modality in allowed_modalities
            }
        }

        worker_management.worker_skill_json_roster.clear()
        try:
            with patch("data_manager.worker_management.load_worker_skill_json", return_value=existing_roster), \
                 patch("data_manager.worker_management.save_worker_skill_json") as mock_save:
                added_count, added_workers = worker_management.auto_populate_skill_roster(
                    {self.modality: df}
                )

            self.assertEqual(added_count, 0)
            self.assertEqual(added_workers, [])
            saved_roster = mock_save.call_args.args[0]
            self.assertEqual(saved_roster["A1"]["full_name"], "Alice (A1)")
        finally:
            worker_management.worker_skill_json_roster.clear()

    def test_auto_import_new_worker_from_csv_uses_shift_rules_and_defaults_to_disabled(self) -> None:
        config = {
            "medweb_mapping": {
                "columns": {
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [
                    {
                        "match": "Shift A",
                        "type": "shift",
                    },
                    {
                        "match": "Board",
                        "type": "gap",
                    },
                ],
            },
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                        "Beschreibung der Aktivität",
                    ]
                )
                writer.writerow(["23.01.2026", "Alice", "A1", "Shift A"])
                writer.writerow(["23.01.2026", "Alice", "A1", "Board"])
                writer.writerow(["23.01.2026", "Bob", "B2", "Board"])
                writer.writerow(["23.01.2026", "Cara", "C3", "No Match"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}), \
                 patch("data_manager.worker_management.save_worker_skill_json") as mock_save:
                added_count, added_workers = worker_management.auto_populate_skill_roster_from_csv(
                    csv_path,
                    config,
                )

            self.assertEqual(added_count, 1)
            self.assertEqual(set(added_workers), {"A1"})
            saved_roster = mock_save.call_args.args[0]
            self.assertEqual(saved_roster["A1"]["full_name"], "Alice (A1)")
            for skill in SKILL_COLUMNS:
                for modality in allowed_modalities:
                    self.assertEqual(saved_roster["A1"][f"{skill}_{modality}"], -1)
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_csv_auto_import_existing_worker_backfills_full_name_and_saves(self) -> None:
        config = {
            "medweb_mapping": {
                "columns": {
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [
                    {
                        "match": "Shift A",
                        "type": "shift",
                    },
                ],
            },
        }

        existing_roster = {
            "A1": {
                f"{skill}_{modality}": -1
                for skill in SKILL_COLUMNS
                for modality in allowed_modalities
            }
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                        "Beschreibung der Aktivität",
                    ]
                )
                writer.writerow(["23.01.2026", "Alice", "A1", "Shift A"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value=existing_roster), \
                 patch("data_manager.worker_management.save_worker_skill_json") as mock_save:
                added_count, added_workers = worker_management.auto_populate_skill_roster_from_csv(
                    csv_path,
                    config,
                )

            self.assertEqual(added_count, 0)
            self.assertEqual(added_workers, [])
            saved_roster = mock_save.call_args.args[0]
            self.assertEqual(saved_roster["A1"]["full_name"], "Alice (A1)")
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_synthetic_shift_loads_without_same_day_medweb_rows_and_seeds_roster(self) -> None:
        target_date = datetime(2026, 1, 23)  # Friday
        worker_name = "GynDoc"
        skill_key = SKILL_COLUMNS[0]
        skill_override_key = f"{skill_key}_{self.modality}"

        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "synthetic_shifts": [
                {
                    "worker_name": worker_name,
                    "label": "Gyn Summary",
                    "weekdays": ["friday"],
                    "times": {"default": "07:30-15:45"},
                    "skill_overrides": {skill_override_key: 1},
                }
            ],
            "worker_roster": {},
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Beschreibung der Aktivität",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                    ]
                )
                writer.writerow(["22.01.2026", "Other Day", "Alice", "A1"])

            worker_management.worker_skill_json_roster.clear()

            def _fake_save(roster, create_backup=True):
                worker_management.worker_skill_json_roster.clear()
                worker_management.worker_skill_json_roster.update(roster)
                return True

            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}), \
                 patch("data_manager.worker_management.save_worker_skill_json", side_effect=_fake_save):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            self.assertIn(self.modality, csv_result)
            csv_df = csv_result[self.modality]
            self.assertEqual(len(csv_df), 1)
            self.assertEqual(csv_df.iloc[0]["PPL"], worker_name)
            self.assertEqual(csv_df.iloc[0]["tasks"], "Gyn Summary")
            self.assertEqual(csv_df.iloc[0]["start_time"].strftime("%H:%M"), "07:30")
            self.assertEqual(csv_df.iloc[0]["end_time"].strftime("%H:%M"), "15:45")
            self.assertEqual(str(csv_df.iloc[0][skill_key]), "1")
            self.assertIn(worker_name, worker_management.worker_skill_json_roster)
            self.assertEqual(
                worker_management.worker_skill_json_roster[worker_name],
                {"full_name": worker_name},
            )
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_synthetic_shift_preserves_yaml_roster_exclusions_after_json_seed(self) -> None:
        target_date = datetime(2026, 1, 23)  # Friday
        worker_name = "Gynarzt (GYNDOC)"

        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                },
                "rules": [],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {
                "GYNDOC": {
                    "gyn_ct": 0,
                    "notfall_ct": -1,
                }
            },
            "synthetic_shifts": [
                {
                    "worker_name": worker_name,
                    "label": "Gynarzt-shift",
                    "weekdays": ["friday"],
                    "times": {"default": "07:30-16:15"},
                    "skill_overrides": {"gyn_ct": 1},
                }
            ],
        }

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Beschreibung der Aktivität",
                        "Name des Mitarbeiters",
                        "Code des Mitarbeiters",
                    ]
                )
                writer.writerow(["22.01.2026", "Other Day", "Alice", "A1"])

            worker_management.worker_skill_json_roster.clear()

            def _fake_save(roster, create_backup=True):
                worker_management.worker_skill_json_roster.clear()
                worker_management.worker_skill_json_roster.update(roster)
                return True

            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}), \
                 patch("data_manager.worker_management.save_worker_skill_json", side_effect=_fake_save):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]
            self.assertEqual(len(csv_df), 1)
            self.assertEqual(csv_df.iloc[0]["PPL"], worker_name)
            self.assertEqual(str(csv_df.iloc[0]["gyn"]), "1")
            self.assertEqual(str(csv_df.iloc[0]["notfall"]), "-1")
            self.assertEqual(
                worker_management.worker_skill_json_roster["GYNDOC"],
                {"full_name": worker_name},
            )
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)


if __name__ == "__main__":
    unittest.main()
