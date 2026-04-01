import csv
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

import routes
from config import APP_CONFIG, SKILL_COLUMNS, allowed_modalities
from data_manager import schedule_crud
from data_manager import worker_management
from data_manager.csv_parser import (
    _normalize_day_part_label,
    _normalize_rule_day_parts,
    build_ppl_from_row,
    build_working_hours_from_medweb,
    match_mapping_rule,
)


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
                    "day_part": "Tageszeit",
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

            self.assertTrue(csv_result)
            csv_df = next(iter(csv_result.values()))

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

            self.assertTrue(csv_result)
            csv_df = next(iter(csv_result.values()))
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

    def test_csv_import_prefers_personalnummer_over_code(self) -> None:
        config = {
            "medweb_mapping": {
                "columns": {
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_personalnummer": "Personalnummer",
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

        row = pd.Series(
            {
                "Name des Mitarbeiters": "Alex Example",
                "Personalnummer": "P123",
                "Code des Mitarbeiters": "C12",
            }
        )
        self.assertEqual(build_ppl_from_row(row, config["medweb_mapping"]["columns"]), "Alex Example (P123)")

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(csv_path, mode="w", encoding="utf-8", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Datum",
                        "Name des Mitarbeiters",
                        "Personalnummer",
                        "Code des Mitarbeiters",
                        "Beschreibung der Aktivität",
                    ]
                )
                writer.writerow(["23.01.2026", "Alex Example", "P123", "C12", "Shift A"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}),                  patch("data_manager.worker_management.save_worker_skill_json") as mock_save:
                added_count, added_workers = worker_management.auto_populate_skill_roster_from_csv(
                    csv_path,
                    config,
                )

            self.assertEqual(added_count, 1)
            self.assertEqual(added_workers, ["P123"])
            saved_roster = mock_save.call_args.args[0]
            self.assertIn("P123", saved_roster)
            self.assertNotIn("C12", saved_roster)
            self.assertEqual(saved_roster["P123"]["full_name"], "Alex Example (P123)")
            for skill in SKILL_COLUMNS:
                for modality in allowed_modalities:
                    self.assertEqual(saved_roster["P123"][f"{skill}_{modality}"], -1)
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

    def test_gap_presets_include_gyn_and_notfall_blockers(self) -> None:
        rules = APP_CONFIG.get("medweb_mapping", {}).get("rules", [])
        labels = {str(rule.get("label", "")).strip(): rule for rule in rules}

        for label in ("Gyn Spät", "Notfall spät"):
            self.assertIn(label, labels)
            rule = labels[label]
            self.assertEqual(rule.get("type"), "shift")
            self.assertEqual(rule.get("times", {}).get("default"), "07:30-12:00")
            self.assertFalse(bool(rule.get("counts_for_hours", False)))
            self.assertEqual(rule.get("skill_overrides", {}).get("all"), -1)
        gyn_rule = labels["Gyn Spät"]
        self.assertEqual(gyn_rule.get("skill_overrides", {}).get("gyn_ct"), 1)
        self.assertEqual(gyn_rule.get("skill_overrides", {}).get("gyn_mr"), 1)
        notfall_rule = labels["Notfall spät"]
        self.assertEqual(notfall_rule.get("skill_overrides", {}).get("notfall_ct"), 1)
        self.assertEqual(notfall_rule.get("skill_overrides", {}).get("notfall_mr"), 1)
        self.assertEqual(notfall_rule.get("skill_overrides", {}).get("notfall_xray"), 1)

    def test_segmented_shift_rule_applies_time_sliced_skill_overrides(self) -> None:
        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                    "day_part": "Tageszeit",
                },
                "rules": [
                    {
                        "match": "SBZ: Spätdienst",
                        "type": "shift",
                        "label": "SBZ: Spätdienst",
                        "day_part": "NM",
                        "times": {"default": "12:00-20:00"},
                        "skill_overrides": {
                            f"notfall_{self.modality}": -1,
                            f"gyn_{self.modality}": 0,
                        },
                        "segments": [
                            {
                                "times": {"default": "12:00-15:45"},
                                "skill_overrides": {f"gyn_{self.modality}": -1},
                            },
                            {
                                "times": {"default": "15:45-20:00"},
                                "skill_overrides": {f"gyn_{self.modality}": 0},
                            },
                        ],
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
        }

        rule = config["medweb_mapping"]["rules"][0]
        self.assertEqual(rule["match"], "SBZ: Spätdienst")
        self.assertEqual(rule["label"], "SBZ: Spätdienst")
        self.assertEqual(rule["day_part"], "NM")
        self.assertEqual(rule["times"]["default"], "12:00-20:00")
        self.assertEqual(rule["segments"][0]["times"]["default"], "12:00-15:45")
        self.assertEqual(rule["segments"][1]["times"]["default"], "15:45-20:00")
        self.assertEqual(rule["segments"][0]["skill_overrides"][f"gyn_{self.modality}"], -1)
        self.assertEqual(rule["segments"][1]["skill_overrides"][f"gyn_{self.modality}"], 0)

    def test_day_part_filters_use_medweb_tageszeit(self) -> None:
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
                    "day_part": "Tageszeit",
                },
                "rules": [
                    {
                        "match": "Gerätearzt",
                        "type": "shift",
                        "label": "Gerätearzt",
                        "times": {"default": "07:30-15:45"},
                        "skill_overrides": {skill_override_key: 1},
                        "segments": [
                            {
                                "label": "Gerätearzt VM",
                                "day_part": "VM",
                                "times": {"default": "07:30-12:00"},
                            },
                            {
                                "label": "Gerätearzt NM",
                                "day_part": "NM",
                                "times": {"default": "13:00-15:45"},
                            },
                        ],
                    },
                    {
                        "match": "Spätdienst Aufklärung",
                        "type": "gap",
                        "label": "Aufklärung Spät",
                        "day_part": "NM",
                        "times": {"default": "15:45-20:00"},
                        "skill_overrides": {"all": -1},
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {
                "A1": {
                    f"{skill}_{modality}": 0
                    for skill in SKILL_COLUMNS
                    for modality in allowed_modalities
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
                        "Tageszeit",
                    ]
                )
                writer.writerow(["23.01.2026", "Gerätearzt", "Alice", "A1", "VM"])
                writer.writerow(["23.01.2026", "Gerätearzt", "Alice", "A1", "NM"])
                writer.writerow(["23.01.2026", "Spätdienst Aufklärung", "Alice", "A1", "VM"])
                writer.writerow(["23.01.2026", "Spätdienst Aufklärung", "Alice", "A1", "NM"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]
            shift_rows = csv_df[csv_df["tasks"].isin(["Gerätearzt VM", "Gerätearzt NM"])]
            gap_rows = csv_df[csv_df["tasks"] == "Aufklärung Spät"]

            self.assertEqual(len(shift_rows), 2)
            self.assertEqual(
                sorted(shift_rows["tasks"].tolist()),
                ["Gerätearzt NM", "Gerätearzt VM"],
            )
            self.assertEqual(
                sorted(time.strftime("%H:%M") for time in shift_rows["start_time"]),
                ["07:30", "13:00"],
            )
            self.assertEqual(
                sorted(time.strftime("%H:%M") for time in shift_rows["end_time"]),
                ["12:00", "15:45"],
            )

            self.assertEqual(len(gap_rows), 1)
            self.assertEqual(gap_rows.iloc[0]["start_time"].strftime("%H:%M"), "15:45")
            self.assertEqual(gap_rows.iloc[0]["end_time"].strftime("%H:%M"), "20:00")
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_day_part_helper_normalizes_vmnm(self) -> None:
        self.assertEqual(_normalize_day_part_label("VM"), "VM")
        self.assertEqual(_normalize_day_part_label("NM"), "NM")
        self.assertEqual(_normalize_day_part_label("VM+NM"), "VMNM")
        self.assertEqual(_normalize_day_part_label("NM/VM"), "VMNM")

    def test_rule_day_parts_default_to_all_three_when_unspecified(self) -> None:
        self.assertEqual(
            _normalize_rule_day_parts({"match": "Example Shift"}),
            {"VM", "VMNM", "NM"},
        )

    def test_real_medweb_config_matches_late_geraeteassistenz_before_generic_rule(self) -> None:
        rules = APP_CONFIG["medweb_mapping"]["rules"]

        normal_rule = match_mapping_rule("SBZ: Geräteassistenz", rules, day_part="VM+NM")
        self.assertIsNotNone(normal_rule)
        self.assertEqual(normal_rule["label"], "Aufklärung")
        self.assertEqual(normal_rule["day_part"], "VM")

        late_rule = match_mapping_rule("SBZ: Geräteassistenz", rules, day_part="NM")
        self.assertIsNotNone(late_rule)
        self.assertEqual(late_rule["label"], "Aufklärung Spät")
        self.assertEqual(late_rule["day_part"], "NM")

    def test_real_medweb_config_has_nm_only_specialty_shift_variants(self) -> None:
        rules = APP_CONFIG["medweb_mapping"]["rules"]
        expected = [
            ("SBZ: Abdomen/Onko/Uro", "SBZ: Abdomen/Onko/Uro NM", "12:00-15:45"),
            ("SBZ: Cardio/Vask/Thorax", "SBZ: Cardio/Vask/Thorax NM", "12:00-15:45"),
            ("SBZ: Muskel-Skelett/Hals/Derma", "SBZ: Muskel-Skelett/Hals/Derma NM", "12:00-15:45"),
        ]

        for activity, expected_label, expected_time in expected:
            with self.subTest(activity=activity):
                nm_rule = match_mapping_rule(activity, rules, day_part="NM")
                self.assertIsNotNone(nm_rule)
                self.assertEqual(nm_rule["label"], expected_label)
                self.assertEqual(nm_rule["day_part"], "NM")
                self.assertEqual(nm_rule["times"]["default"], expected_time)
                self.assertAlmostEqual(float(nm_rule.get("modifier", 1.0)), 1.0)

                base_rule = match_mapping_rule(activity, rules, day_part="VM")
                self.assertIsNotNone(base_rule)
                self.assertEqual(base_rule["times"]["default"], "07:30-15:45")
                self.assertAlmostEqual(float(base_rule.get("modifier", 1.0)), 1.0)
                self.assertIn("VMNM", base_rule.get("day_parts", []))

                vmnm_rule = match_mapping_rule(activity, rules, day_part="VMNM")
                self.assertIsNotNone(vmnm_rule)
                self.assertEqual(vmnm_rule["times"]["default"], "07:30-15:45")

    def test_vm_nm_pair_collapses_to_single_base_shift(self) -> None:
        target_date = datetime(2026, 4, 1)
        skill_key = SKILL_COLUMNS[0]
        skill_override_key = f"{skill_key}_{self.modality}"

        config = {
            "medweb_mapping": {
                "columns": {
                    "date": "Datum",
                    "activity": "Beschreibung der Aktivität",
                    "employee_name": "Name des Mitarbeiters",
                    "employee_code": "Code des Mitarbeiters",
                    "day_part": "Tageszeit",
                },
                "rules": [
                    {
                        "match": "SBZ: Cardio/Vask/Thorax",
                        "type": "shift",
                        "label": "SBZ: Cardio/Vask/Thorax NM",
                        "day_part": "NM",
                        "times": {"default": "12:00-15:45"},
                        "modifier": 1.0,
                        "skill_overrides": {skill_override_key: 1},
                    },
                    {
                        "match": "SBZ: Cardio/Vask/Thorax",
                        "type": "shift",
                        "day_parts": ["VM", "VMNM"],
                        "times": {"default": "07:30-15:45"},
                        "modifier": 1.0,
                        "skill_overrides": {skill_override_key: 1},
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {
                "WALZ": {
                    skill_override_key: 0,
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
                        "Tageszeit",
                    ]
                )
                writer.writerow(["01.04.2026", "SBZ: Cardio/Vask/Thorax", "Malin Walz", "WALZ", "VM"])
                writer.writerow(["01.04.2026", "SBZ: Cardio/Vask/Thorax", "Malin Walz", "WALZ", "NM"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]
            shift_rows = csv_df[csv_df["tasks"] == "SBZ: Cardio/Vask/Thorax"]

            self.assertEqual(len(shift_rows), 1)
            self.assertEqual(shift_rows.iloc[0]["start_time"].strftime("%H:%M"), "07:30")
            self.assertEqual(shift_rows.iloc[0]["end_time"].strftime("%H:%M"), "15:45")
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_segmented_gap_rule_creates_multiple_gap_intervals(self) -> None:
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
                        "times": {"default": "08:00-16:00"},
                        "skill_overrides": {skill_override_key: 1},
                    },
                    {
                        "match": "Board",
                        "type": "gap",
                        "label": "Board",
                        "segments": [
                            {
                                "label": "Board A",
                                "times": {"default": "09:00-10:00"},
                            },
                            {
                                "label": "Board B",
                                "times": {"default": "14:00-15:00"},
                            },
                        ],
                    },
                ],
            },
            "balancer": {"hours_counting": {"shift_default": True, "gap_default": False}},
            "worker_roster": {
                "A1": {
                    f"{skill}_{modality}": 0
                    for skill in SKILL_COLUMNS
                    for modality in allowed_modalities
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
                writer.writerow(["23.01.2026", "Board", "Alice", "A1"])

            worker_management.worker_skill_json_roster.clear()
            with patch("data_manager.worker_management.load_worker_skill_json", return_value={}):
                csv_result = build_working_hours_from_medweb(csv_path, target_date, config)

            csv_df = csv_result[self.modality]
            gap_rows = csv_df[csv_df["tasks"].isin(["Board A", "Board B"])].sort_values(by="start_time").reset_index(drop=True)

            self.assertEqual(len(gap_rows), 2)
            self.assertTrue(all("gap" in str(value) for value in gap_rows["row_type"]))
            self.assertEqual(gap_rows.iloc[0]["start_time"].strftime("%H:%M"), "09:00")
            self.assertEqual(gap_rows.iloc[0]["end_time"].strftime("%H:%M"), "10:00")
            self.assertFalse(bool(gap_rows.iloc[0]["counts_for_hours"]))
            self.assertEqual(gap_rows.iloc[1]["start_time"].strftime("%H:%M"), "14:00")
            self.assertEqual(gap_rows.iloc[1]["end_time"].strftime("%H:%M"), "15:00")
            self.assertFalse(bool(gap_rows.iloc[1]["counts_for_hours"]))
        finally:
            worker_management.worker_skill_json_roster.clear()
            os.unlink(csv_path)

    def test_apply_worker_plan_keeps_multiple_full_gap_rows(self) -> None:
        worker_name = "Alice (A1)"
        skill_key = SKILL_COLUMNS[0]
        active_skills = {skill: (1 if skill == skill_key else 0) for skill in SKILL_COLUMNS}
        blocking_skills = {skill: -1 for skill in SKILL_COLUMNS}

        shifts = [
            {
                "start_time": "08:00",
                "end_time": "16:00",
                "modifier": 1.0,
                "counts_for_hours": True,
                "task": "Shift A",
                "row_type": "shift",
                "modalities": {
                    self.modality: {
                        "skills": active_skills,
                    }
                },
            },
            {
                "start_time": "09:00",
                "end_time": "09:30",
                "modifier": 1.0,
                "counts_for_hours": False,
                "task": "Break A",
                "row_type": "gap",
                "modalities": {
                    self.modality: {
                        "skills": blocking_skills,
                    }
                },
            },
            {
                "start_time": "14:00",
                "end_time": "14:30",
                "modifier": 1.0,
                "counts_for_hours": False,
                "task": "Break B",
                "row_type": "gap",
                "modalities": {
                    self.modality: {
                        "skills": blocking_skills,
                    }
                },
            },
        ]

        rows = routes._build_rows_from_plan(worker_name, shifts, self.modality)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(1 for row in rows if row["row_type"] == "gap"), 2)

        with patch.object(schedule_crud, "backup_dataframe"):
            success, _, error = schedule_crud.replace_worker_schedule(
                self.modality,
                worker_name,
                rows,
                use_staged=False,
            )

        self.assertTrue(success, msg=error)

        df = schedule_crud.modality_data[self.modality]["working_hours_df"]
        self.assertIsNotNone(df)
        worker_rows = df[df["PPL"] == worker_name].sort_values(by=["start_time", "end_time"]).reset_index(drop=True)
        self.assertEqual(len(worker_rows), 5)

        gap_rows = worker_rows[worker_rows["row_type"] == "gap_segment"].reset_index(drop=True)
        self.assertEqual(len(gap_rows), 2)
        self.assertEqual(gap_rows.iloc[0]["tasks"], "Break A")
        self.assertEqual(gap_rows.iloc[0]["start_time"].strftime("%H:%M"), "09:00")
        self.assertEqual(gap_rows.iloc[0]["end_time"].strftime("%H:%M"), "09:30")
        self.assertEqual(gap_rows.iloc[1]["tasks"], "Break B")
        self.assertEqual(gap_rows.iloc[1]["start_time"].strftime("%H:%M"), "14:00")
        self.assertEqual(gap_rows.iloc[1]["end_time"].strftime("%H:%M"), "14:30")
        shift_rows = worker_rows[worker_rows["row_type"] == "shift_segment"].reset_index(drop=True)
        self.assertEqual(len(shift_rows), 3)


if __name__ == "__main__":
    unittest.main()
