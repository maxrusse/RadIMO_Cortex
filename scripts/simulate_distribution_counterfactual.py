#!/usr/bin/env python3
"""Counterfactual full-day replay for RadIMO distribution analysis.

This tool replays a historical day from a runtime bundle and applies the
current selector logic to every logged assignment request in timestamp order.
Unlike the forensic focus report, this script advances the simulated global
state with the predicted worker, not the logged worker.

Use it to inspect edge cases that only show up in deployed live state:
- "What would this day look like with the current balancer logic?"
- "How does the end-of-day fairness table change after a balancer fix?"
- "Which requests move between workers after a policy change?"
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import replay_distribution_day as replay  # noqa: E402


def _simulate_day(
    bundle_root: Path,
    target_date: date,
    snapshot_path: Optional[Path],
) -> dict[str, Any]:
    runtime = replay._prepare_temp_runtime(bundle_root)
    runtime_root = Path(runtime.name)
    modules = replay._load_runtime_modules(runtime_root)
    try:
        schedule_source = replay._load_schedule_from_snapshot_or_csv(runtime_root, modules, target_date, snapshot_path)
        replay._clear_runtime_state(modules["config"], modules["worker_management"], modules["file_ops"])

        events = replay.parse_assignment_events(replay._find_file(bundle_root, "logs/selection.log"), target_date)
        replay._apply_analysis_aliases(modules, events)
        replay._install_real_person_hours(modules)

        utils = __import__("lib.utils", fromlist=["dummy"])
        canonical = modules["worker_management"].get_canonical_worker_id
        balancer = modules["balancer"]
        file_ops = modules["file_ops"]

        logged_counts: Counter[str] = Counter()
        simulated_counts: Counter[str] = Counter()
        transitions: list[dict[str, Any]] = []
        transition_count = 0

        for event in events:
            if not event.logged_selected_worker or not event.selected_skill or not event.selected_modality:
                continue

            predicted = balancer.get_next_available_worker(
                event.timestamp,
                role=event.request_role,
                modality=event.request_modality,
                allow_overflow=not event.strict_routing,
                target_skill_modalities=None,
            )

            chosen_name = event.logged_selected_worker
            chosen_skill = event.selected_skill
            chosen_modality = event.selected_modality
            if predicted is not None:
                candidate, predicted_skill, predicted_modality = predicted
                candidate_dict = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                chosen_name = candidate_dict["PPL"]
                chosen_skill = candidate_dict.get("__skill_source") or predicted_skill or event.selected_skill
                chosen_modality = predicted_modality or event.selected_modality
                if chosen_skill not in modules["config"].SKILL_COLUMNS:
                    chosen_skill = event.selected_skill

            row = replay._find_active_selected_row(
                modules,
                event.timestamp,
                chosen_name,
                chosen_modality,
                chosen_skill,
            )
            shift_modifier = 1.0
            is_weighted = False
            if row is not None:
                shift_modifier = float(row.get("Modifier", 1.0) or 1.0)
                if chosen_skill in row.index:
                    is_weighted = bool(utils.is_weighted_skill(row.get(chosen_skill)))

            balancer.update_global_assignment(
                chosen_name,
                chosen_skill,
                chosen_modality,
                is_weighted=is_weighted,
                strict_mode=event.strict_weights,
                shift_modifier_override=shift_modifier,
            )

            logged_cid = canonical(event.logged_selected_worker)
            simulated_cid = canonical(chosen_name)
            logged_counts[logged_cid] += 1
            simulated_counts[simulated_cid] += 1

            if logged_cid != simulated_cid:
                transition_count += 1
                transitions.append(
                    {
                        "timestamp": event.timestamp.isoformat(sep=" "),
                        "request_role": event.request_role,
                        "request_modality": event.request_modality,
                        "logged_worker": event.logged_selected_worker,
                        "simulated_worker": chosen_name,
                        "simulated_skill": chosen_skill,
                        "simulated_modality": chosen_modality,
                    }
                )

        end_ts = max((event.timestamp for event in events if event.logged_selected_worker), default=None)
        hours_map = balancer.calculate_global_work_hours_now(end_ts) if end_ts else {}

        canonical_ids = set(logged_counts.keys()) | set(simulated_counts.keys()) | set(hours_map.keys())
        display_for_canonical: dict[str, str] = {}
        for modality_data in file_ops.modality_data.values():
            df = modality_data.get("working_hours_df")
            if df is None or df.empty or "PPL" not in df.columns:
                continue
            for _, row in df.iterrows():
                worker = str(row.get("PPL", "")).strip()
                if worker and worker.lower() != "nan":
                    aliased = replay._apply_name_alias(worker)
                    display_for_canonical.setdefault(canonical(aliased), aliased)

        end_rows = []
        for cid in sorted(canonical_ids):
            hours = float(hours_map.get(cid, 0.0) or 0.0)
            weighted = float(balancer.get_global_weighted_count(cid) or 0.0)
            simulated = int(simulated_counts[cid])
            logged = int(logged_counts[cid])
            ratio = weighted / hours if hours > 0 else None
            if hours > 0 or weighted > 0 or simulated > 0 or logged > 0:
                end_rows.append(
                    {
                        "canonical_id": cid,
                        "name": display_for_canonical.get(cid, cid),
                        "logged_assignments": logged,
                        "simulated_assignments": simulated,
                        "hours": round(hours, 2),
                        "weighted": round(weighted, 2),
                        "ratio": round(ratio, 3) if ratio is not None else None,
                    }
                )

        end_rows.sort(
            key=lambda row: (
                row["ratio"] is None,
                row["ratio"] if row["ratio"] is not None else float("inf"),
                row["name"],
            )
        )

        return {
            "target_date": target_date.isoformat(),
            "schedule_source": schedule_source,
            "snapshot_path": str(snapshot_path) if snapshot_path else None,
            "transition_count": transition_count,
            "end_timestamp": end_ts.isoformat(sep=" ") if end_ts else None,
            "end_rows": end_rows,
            "transitions": transitions,
        }
    finally:
        original_cwd = modules.get("original_cwd") if isinstance(modules, dict) else None
        if original_cwd is not None:
            import os
            os.chdir(original_cwd)
        runtime.cleanup()


def _write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"counterfactual_{result['target_date']}.json"
    csv_path = output_dir / f"counterfactual_{result['target_date']}_endstate.csv"
    transitions_path = output_dir / f"counterfactual_{result['target_date']}_transitions.csv"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "canonical_id",
                "name",
                "logged_assignments",
                "simulated_assignments",
                "hours",
                "weighted",
                "ratio",
            ],
        )
        writer.writeheader()
        writer.writerows(result["end_rows"])

    with transitions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "request_role",
                "request_modality",
                "logged_worker",
                "simulated_worker",
                "simulated_skill",
                "simulated_modality",
            ],
        )
        writer.writeheader()
        writer.writerows(result["transitions"])

    print(json_path)
    print(csv_path)
    print(transitions_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path, help="Bundle directory or .tar.gz archive")
    parser.add_argument("--target-date", required=True, help="Target date in YYYY-MM-DD")
    parser.add_argument("--snapshot", type=Path, default=None, help="Optional unified snapshot JSON for the target day")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for JSON/CSV outputs")
    args = parser.parse_args()

    bundle_root, extracted_tmp = replay._extract_bundle_root(args.bundle)
    try:
        result = _simulate_day(bundle_root, date.fromisoformat(args.target_date), args.snapshot)
        _write_outputs(result, args.output_dir)
    finally:
        if extracted_tmp is not None:
            extracted_tmp.cleanup()


if __name__ == "__main__":
    main()
