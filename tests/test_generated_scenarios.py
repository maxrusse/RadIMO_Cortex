import json
import unittest
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from balancer import get_next_available_worker
from config import SKILL_COLUMNS, allowed_modalities
from data_manager import global_worker_data, modality_data, worker_management
from data_manager.csv_parser import build_working_hours_from_medweb
from lib.utils import normalize_skill_value
from state_manager import get_state


def _serialize_time(value: Any) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, str):
        return value[:5]
    return ""


def _build_row_signature(row: pd.Series) -> str:
    parts = []
    for skill in SKILL_COLUMNS:
        normalized = normalize_skill_value(row.get(skill, 0))
        if normalized != "0":
            parts.append(f"{skill}:{normalized}")
    return "|".join(parts)

def _normalize_modality_summary(df: pd.DataFrame | None) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "row_count": 0,
            "shift_segment_count": 0,
            "gap_segment_count": 0,
            "workers": [],
            "rows": [],
        }

    local_df = df.copy()
    local_df["start_key"] = local_df["start_time"].apply(_serialize_time)
    local_df["end_key"] = local_df["end_time"].apply(_serialize_time)
    local_df = local_df.sort_values(
        by=["PPL", "row_type", "start_key", "end_key", "tasks"]
    ).reset_index(drop=True)

    rows = []
    for _, row in local_df.iterrows():
        rows.append({
            "ppl": str(row.get("PPL", "")),
            "row_type": str(row.get("row_type", "")),
            "start": _serialize_time(row.get("start_time")),
            "end": _serialize_time(row.get("end_time")),
            "tasks": str(row.get("tasks", "")),
            "counts_for_hours": bool(row.get("counts_for_hours", True)),
            "skill_signature": _build_row_signature(row),
        })

    row_types = local_df["row_type"].astype(str)
    return {
        "row_count": int(len(local_df)),
        "shift_segment_count": int((row_types == "shift_segment").sum()),
        "gap_segment_count": int((row_types == "gap_segment").sum()),
        "workers": sorted(set(local_df["PPL"].astype(str).tolist())),
        "rows": rows,
    }

def _prepare_balancer_state(modality_dfs: dict[str, pd.DataFrame]) -> None:
    for mod in allowed_modalities:
        df = modality_dfs.get(mod)
        if df is None:
            df = pd.DataFrame()
        modality_data[mod]["working_hours_df"] = df.copy()
        modality_data[mod]["skill_counts"] = {skill: {} for skill in SKILL_COLUMNS}
        if not df.empty and "PPL" in df.columns:
            for worker in sorted(set(df["PPL"].dropna().astype(str).tolist())):
                for skill in SKILL_COLUMNS:
                    modality_data[mod]["skill_counts"][skill][worker] = 0

    global_worker_data["weighted_counts"] = {}
    for mod in allowed_modalities:
        global_worker_data["assignments_per_mod"][mod] = {}

    get_state().invalidate_work_hours_cache()


def _run_assignment_checks(
    assignment_checks: list[dict[str, Any]],
    target_date: date,
    modality_dfs: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    if not assignment_checks:
        return []

    _prepare_balancer_state(modality_dfs)
    results = []
    for check in assignment_checks:
        at_time = datetime.strptime(check.get("time", "09:00"), "%H:%M").time()
        current_dt = datetime.combine(target_date, at_time)
        result = get_next_available_worker(
            current_dt=current_dt,
            role=check["role"],
            modality=check["modality"],
            allow_overflow=bool(check.get("allow_overflow", True)),
        )
        selected_person = None
        selected_skill = None
        selected_modality = None
        if result:
            selected_row, selected_skill, selected_modality = result
            selected_person = str(selected_row.get("PPL", ""))
        results.append({
            "label": check.get("label", ""),
            "role": check["role"],
            "modality": check["modality"],
            "allow_overflow": bool(check.get("allow_overflow", True)),
            "time": check.get("time", "09:00"),
            "selected_person": selected_person,
            "selected_skill": selected_skill,
            "selected_modality": selected_modality,
        })
    return results


class TestGeneratedScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.generated_root = cls.repo_root / "test_data" / "generated"
        if cls.generated_root.exists():
            cls.scenario_dirs = sorted(
                path for path in cls.generated_root.iterdir()
                if path.is_dir() and (path / "expected_summary.json").exists()
            )
        else:
            cls.scenario_dirs = []

    def test_generated_scenarios_match_expected(self) -> None:
        self.assertTrue(
            self.scenario_dirs,
            "No generated scenarios found under test_data/generated. "
            "Run: python scripts/gen_test_data.py --scenario all",
        )

        for scenario_dir in self.scenario_dirs:
            with self.subTest(scenario=scenario_dir.name):
                expected_summary = json.loads(
                    (scenario_dir / "expected_summary.json").read_text(encoding="utf-8")
                )
                config_overlay = yaml.safe_load(
                    (scenario_dir / "config.overlay.yaml").read_text(encoding="utf-8")
                )
                roster_fixture = json.loads(
                    (scenario_dir / "worker_skill_roster.json").read_text(encoding="utf-8")
                )
                target_date = date.fromisoformat(expected_summary["target_date"])

                worker_management.worker_skill_json_roster.clear()
                worker_management.worker_skill_json_roster.update(roster_fixture)
                modality_dfs = build_working_hours_from_medweb(
                    csv_path=str(scenario_dir / "master_medweb.csv"),
                    target_date=datetime.combine(target_date, time(0, 0)),
                    config=config_overlay,
                )

                actual_summary = {
                    "scenario": scenario_dir.name,
                    "target_date": target_date.isoformat(),
                    "modalities": {
                        mod: _normalize_modality_summary(modality_dfs.get(mod))
                        for mod in allowed_modalities
                    },
                    "assignment_checks": _run_assignment_checks(
                        assignment_checks=expected_summary.get("assignment_checks", []),
                        target_date=target_date,
                        modality_dfs=modality_dfs,
                    ),
                }
                self.assertEqual(actual_summary, expected_summary)


if __name__ == "__main__":
    unittest.main()
