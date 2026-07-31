#!/usr/bin/env python
# ruff: noqa: E402
"""
Generate deterministic scenario-based test data for parser and assignment tests.

Outputs are written to test_data/generated/<scenario>/:
  - master_medweb.csv
  - worker_skill_roster.json
  - config.overlay.yaml
  - expected_summary.json
  - README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balancer import get_next_available_worker
from config import SKILL_COLUMNS, allowed_modalities
from data_manager import global_worker_data, modality_data
import data_manager.worker_management as worker_management
from data_manager.csv_parser import build_working_hours_from_medweb
from lib.utils import normalize_skill_value
from state_manager import get_state

GENERATED_ROOT = ROOT / "test_data" / "generated"

CSV_COLUMNS = {
    "date": "Datum",
    "activity": "Beschreibung der Aktivität",
    "employee_name": "Name des Mitarbeiters",
    "employee_personalnummer": "Personalnummer",
}


def _canonical_skill(slug: str) -> str:
    lookup = {skill.lower(): skill for skill in SKILL_COLUMNS}
    if slug.lower() in lookup:
        return lookup[slug.lower()]
    raise ValueError(f"Skill '{slug}' not found in current SKILL_COLUMNS: {SKILL_COLUMNS}")


def _skill_mod(skill_slug: str, modality: str) -> str:
    return f"{_canonical_skill(skill_slug)}_{modality}"


def _build_roster_entry(
    full_name: str,
    *,
    default_value: Any = 0,
    overrides: dict[str, Any] | None = None,
    modifier: float = 1.0,
) -> dict[str, Any]:
    entry = {
        f"{skill}_{mod}": default_value
        for skill in SKILL_COLUMNS
        for mod in allowed_modalities
    }
    if overrides:
        for key, value in overrides.items():
            entry[key] = value
    entry["full_name"] = full_name
    entry["modifier"] = modifier
    return entry


def _format_german_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


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


def _build_expected_summary(
    scenario_name: str,
    target_date: date,
    modality_dfs: dict[str, pd.DataFrame],
    assignment_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scenario": scenario_name,
        "target_date": target_date.isoformat(),
        "modalities": {
            mod: _normalize_modality_summary(modality_dfs.get(mod))
            for mod in allowed_modalities
        },
        "assignment_checks": _run_assignment_checks(
            assignment_checks=assignment_checks,
            target_date=target_date,
            modality_dfs=modality_dfs,
        ),
    }


def _build_overlay_config(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "medweb_mapping": {
            "columns": dict(CSV_COLUMNS),
            "rules": rules,
        },
        "balancer": {
            "hours_counting": {
                "shift_default": True,
                "gap_default": False,
            }
        },
        "worker_roster": {},
    }


def _scenario_definitions() -> dict[str, dict[str, Any]]:
    return {
        "baseline_multimodality": {
            "description": "Baseline multi-modality shifts without overlaps or gaps.",
            "rows": [
                {"code": "BM01", "name": "Dr. Base CT", "activity": "Baseline CT Notfall"},
                {"code": "BM02", "name": "Dr. Base MR", "activity": "Baseline MR Privat"},
                {"code": "BM03", "name": "Dr. Base XR", "activity": "Baseline XRAY Kinder"},
                {"code": "BM04", "name": "Dr. Base CT Gyn", "activity": "Baseline CT Gyn"},
            ],
            "rules": [
                {
                    "match": "Baseline CT Notfall",
                    "type": "shift",
                    "label": "Baseline CT Notfall",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("notfall", "ct"): 1},
                },
                {
                    "match": "Baseline MR Privat",
                    "type": "shift",
                    "label": "Baseline MR Privat",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("privat", "mr"): 1},
                },
                {
                    "match": "Baseline XRAY Kinder",
                    "type": "shift",
                    "label": "Baseline XRAY Kinder",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("kinder", "xray"): 1},
                },
                {
                    "match": "Baseline CT Gyn",
                    "type": "shift",
                    "label": "Baseline CT Gyn",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("gyn", "ct"): 1},
                },
            ],
            "roster": {
                "BM01": _build_roster_entry(
                    "Dr. Base CT (BM01)",
                    overrides={_skill_mod("notfall", "ct"): 1},
                ),
                "BM02": _build_roster_entry(
                    "Dr. Base MR (BM02)",
                    overrides={_skill_mod("privat", "mr"): 1},
                ),
                "BM03": _build_roster_entry(
                    "Dr. Base XR (BM03)",
                    overrides={_skill_mod("kinder", "xray"): 1},
                ),
                "BM04": _build_roster_entry(
                    "Dr. Base CT Gyn (BM04)",
                    overrides={_skill_mod("gyn", "ct"): 1},
                ),
            },
            "assignment_checks": [],
        },
        "overlap_with_gap": {
            "description": "Overlapping shifts with a standalone gap intent for one worker.",
            "rows": [
                {"code": "GW01", "name": "Dr. Gap Worker", "activity": "Overlap Shift A"},
                {"code": "GW01", "name": "Dr. Gap Worker", "activity": "Overlap Shift B"},
                {"code": "GW01", "name": "Dr. Gap Worker", "activity": "Board Gap"},
            ],
            "rules": [
                {
                    "match": "Overlap Shift A",
                    "type": "shift",
                    "label": "Overlap Shift A",
                    "times": {"default": "08:00-12:00"},
                    "skill_overrides": {_skill_mod("notfall", "ct"): 1},
                },
                {
                    "match": "Overlap Shift B",
                    "type": "shift",
                    "label": "Overlap Shift B",
                    "times": {"default": "10:00-14:00"},
                    "skill_overrides": {_skill_mod("notfall", "ct"): 1},
                },
                {
                    "match": "Board Gap",
                    "type": "gap",
                    "label": "Board Gap",
                    "times": {"default": "09:30-10:00"},
                    "counts_for_hours": False,
                },
            ],
            "roster": {
                "GW01": _build_roster_entry(
                    "Dr. Gap Worker (GW01)",
                    overrides={_skill_mod("notfall", "ct"): 1},
                )
            },
            "assignment_checks": [],
        },
        "weighted_worker": {
            "description": "Weighted and regular workers on the same skill/modality pool.",
            "rows": [
                {"code": "WW01", "name": "Dr. Weighted Worker", "activity": "Weighted Abd Shift"},
                {"code": "RW01", "name": "Dr. Regular Worker", "activity": "Regular Abd Shift"},
            ],
            "rules": [
                {
                    "match": "Weighted Abd Shift",
                    "type": "shift",
                    "label": "Weighted Abd Shift",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("aou", "ct"): 1},
                },
                {
                    "match": "Regular Abd Shift",
                    "type": "shift",
                    "label": "Regular Abd Shift",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("aou", "ct"): 1},
                },
            ],
            "roster": {
                "WW01": _build_roster_entry(
                    "Dr. Weighted Worker (WW01)",
                    overrides={_skill_mod("aou", "ct"): "w"},
                    modifier=0.7,
                ),
                "RW01": _build_roster_entry(
                    "Dr. Regular Worker (RW01)",
                    overrides={_skill_mod("aou", "ct"): 1},
                ),
            },
            "assignment_checks": [],
        },
        "fallback_and_no_overflow": {
            "description": "Strict specialist-only and overflow fallback assignment checks.",
            "rows": [
                {"code": "PS01", "name": "Dr. Privat Specialist", "activity": "Privat Specialist Shift"},
                {"code": "GG01", "name": "Dr. Gyn Generalist", "activity": "Generalist Support Shift"},
            ],
            "rules": [
                {
                    "match": "Privat Specialist Shift",
                    "type": "shift",
                    "label": "Privat Specialist Shift",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {_skill_mod("privat", "ct"): 1},
                },
                {
                    "match": "Generalist Support Shift",
                    "type": "shift",
                    "label": "Generalist Support Shift",
                    "times": {"default": "08:00-16:00"},
                    "skill_overrides": {"all": 0},
                },
            ],
            "roster": {
                "PS01": _build_roster_entry(
                    "Dr. Privat Specialist (PS01)",
                    default_value=-1,
                    overrides={_skill_mod("privat", "ct"): 1},
                ),
                "GG01": _build_roster_entry(
                    "Dr. Gyn Generalist (GG01)",
                    default_value=0,
                ),
            },
            "assignment_checks": [
                {
                    "label": "strict_privat_ct",
                    "role": "privat",
                    "modality": "ct",
                    "allow_overflow": False,
                    "time": "09:00",
                },
                {
                    "label": "overflow_gyn_ct",
                    "role": "gyn",
                    "modality": "ct",
                    "allow_overflow": True,
                    "time": "09:00",
                },
                {
                    "label": "strict_gyn_ct_no_specialist",
                    "role": "gyn",
                    "modality": "ct",
                    "allow_overflow": False,
                    "time": "09:00",
                },
            ],
        },
    }


def _write_scenario_readme(
    scenario_dir: Path,
    scenario_name: str,
    description: str,
) -> None:
    content = f"""# {scenario_name}

{description}

## Files

- `master_medweb.csv`: parser input CSV
- `worker_skill_roster.json`: deterministic roster fixture
- `config.overlay.yaml`: medweb mapping + parser overlay config
- `expected_summary.json`: normalized expected parser + assignment summary

## Quick Validation

```bash
python scripts/gen_test_data.py --scenario {scenario_name} --run-tests
```
"""
    scenario_dir.joinpath("README.md").write_text(content, encoding="utf-8")


def _generate_one_scenario(
    scenario_name: str,
    scenario_def: dict[str, Any],
    target_date: date,
) -> dict[str, Any]:
    scenario_dir = GENERATED_ROOT / scenario_name
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    overlay = _build_overlay_config(scenario_def["rules"])
    roster = scenario_def["roster"]

    csv_path = scenario_dir / "master_medweb.csv"
    roster_path = scenario_dir / "worker_skill_roster.json"
    overlay_path = scenario_dir / "config.overlay.yaml"
    expected_path = scenario_dir / "expected_summary.json"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            lineterminator="\n",
            fieldnames=[
                CSV_COLUMNS["date"],
                CSV_COLUMNS["activity"],
                CSV_COLUMNS["employee_name"],
                CSV_COLUMNS["employee_personalnummer"],
            ],
        )
        writer.writeheader()
        for row in scenario_def["rows"]:
            writer.writerow({
                CSV_COLUMNS["date"]: _format_german_date(target_date),
                CSV_COLUMNS["activity"]: row["activity"],
                CSV_COLUMNS["employee_name"]: row["name"],
                CSV_COLUMNS["employee_personalnummer"]: row["code"],
            })

    roster_path.write_text(
        json.dumps(roster, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    overlay_path.write_text(
        yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    worker_management.worker_skill_json_roster.clear()
    worker_management.worker_skill_json_roster.update(roster)
    modality_dfs = build_working_hours_from_medweb(
        csv_path=str(csv_path),
        target_date=datetime.combine(target_date, time(0, 0)),
        config=overlay,
    )

    summary = _build_expected_summary(
        scenario_name=scenario_name,
        target_date=target_date,
        modality_dfs=modality_dfs,
        assignment_checks=scenario_def.get("assignment_checks", []),
    )
    expected_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    _write_scenario_readme(
        scenario_dir=scenario_dir,
        scenario_name=scenario_name,
        description=scenario_def["description"],
    )
    return {
        "scenario": scenario_name,
        "target_date": target_date.isoformat(),
        "path": str(scenario_dir.relative_to(ROOT)),
    }


def _run_generated_tests() -> int:
    cmd = [sys.executable, "-m", "unittest", "tests.test_generated_scenarios"]
    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate scenario-based test data fixtures.")
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario name to generate, or 'all' (default).",
    )
    parser.add_argument(
        "--target-date",
        default="2026-01-23",
        help="Target date (YYYY-MM-DD) used in generated CSV rows.",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run generated scenario integration tests after generation.",
    )
    args = parser.parse_args()

    try:
        target_date = date.fromisoformat(args.target_date)
    except ValueError:
        print(f"Invalid --target-date: {args.target_date}. Use YYYY-MM-DD.", file=sys.stderr)
        return 2

    scenarios = _scenario_definitions()
    if args.scenario == "all":
        selected = sorted(scenarios.keys())
    else:
        if args.scenario not in scenarios:
            print(
                f"Unknown scenario '{args.scenario}'. Available: {', '.join(sorted(scenarios.keys()))}",
                file=sys.stderr,
            )
            return 2
        selected = [args.scenario]

    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario_name in selected:
        result = _generate_one_scenario(
            scenario_name=scenario_name,
            scenario_def=scenarios[scenario_name],
            target_date=target_date,
        )
        results.append(result)
        print(f"Generated {result['path']}")

    index_payload = {
        "target_date": target_date.isoformat(),
        "scenarios": results,
    }
    GENERATED_ROOT.joinpath("index.json").write_text(
        json.dumps(index_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {GENERATED_ROOT.joinpath('index.json').relative_to(ROOT)}")

    if args.run_tests:
        return _run_generated_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
