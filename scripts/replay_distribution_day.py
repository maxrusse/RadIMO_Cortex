#!/usr/bin/env python3
"""Replay and analyze RadIMO distribution decisions for a historical day.

This tool boots an isolated temporary RadIMO runtime from a captured bundle
(`config.yaml`, `data/*.json`, `uploads/master_medweb.csv`) and replays the
selected-worker events logged in `selection.log`.

The primary use case is forensic analysis of under-distribution in a target
skill/modality pool such as `mdh_ct` / `mdh_mr`.
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_NAME_ALIASES = {
    "Dorina Korbmacher (DK)": "Dorina Korbmacher (KORB)",
}

REQUEST_RE = re.compile(
    r"Assignment request: modality=(?P<modality>[^,]+), role=(?P<role>[^,]+), "
    r"strict_routing=(?P<strict_routing>True|False), "
    r"strict_weights=(?P<strict_weights>True|False), time=(?P<time>\d{2}:\d{2}:\d{2})"
)
SELECTED_RE = re.compile(
    r"Selected worker: (?P<worker>.+?) using column (?P<skill>[^ ]+) \(modality (?P<modality>[^)]+)\)"
)
WARM_GATE_RE = re.compile(
    r"Warm-start overflow gate: mode=(?P<mode>[^,]+), time_ready=(?P<time_ready>True|False), "
    r"min_ready=(?P<min_ready>True|False), released=(?P<released>True|False)"
)
OVERFLOW_RE = re.compile(
    r"Specialist overflow triggered: specialist_min=(?P<specialist_min>[-0-9.]+), "
    r"generalist_min=(?P<generalist_min>[-0-9.]+), imbalance=(?P<imbalance_pct>[-0-9.]+)% >= (?P<threshold_pct>\d+)%"
)
NO_OVERFLOW_RE = re.compile(r"No-overflow config active for (?P<combo>[a-z0-9_]+), forcing strict mode")
NO_WORKERS_RE = re.compile(r"No workers available")
TIMESTAMP_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} \[")


@dataclass
class AssignmentEvent:
    timestamp: datetime
    request_modality: str
    request_role: str
    strict_routing: bool
    strict_weights: bool
    logged_selected_worker: Optional[str] = None
    selected_skill: Optional[str] = None
    selected_modality: Optional[str] = None
    no_overflow_combo: Optional[str] = None
    warm_start_mode: Optional[str] = None
    warm_start_time_ready: Optional[bool] = None
    warm_start_min_ready: Optional[bool] = None
    warm_start_released: Optional[bool] = None
    overflow_triggered: bool = False
    overflow_specialist_min: Optional[float] = None
    overflow_generalist_min: Optional[float] = None
    overflow_imbalance_pct: Optional[float] = None
    overflow_threshold_pct: Optional[int] = None
    no_worker_available: bool = False
    raw_lines: list[str] = field(default_factory=list)


def _parse_bool(value: str) -> bool:
    return str(value).strip() == "True"


def _parse_timestamp(line: str) -> Optional[datetime]:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M:%S")


def parse_assignment_events(log_path: Path, target_date: date) -> list[AssignmentEvent]:
    events: list[AssignmentEvent] = []
    current: Optional[AssignmentEvent] = None

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stamp = _parse_timestamp(line)
            if stamp is None or stamp.date() != target_date:
                continue

            request_match = REQUEST_RE.search(line)
            if request_match:
                if current is not None:
                    events.append(current)
                current = AssignmentEvent(
                    timestamp=stamp,
                    request_modality=request_match.group("modality"),
                    request_role=request_match.group("role"),
                    strict_routing=_parse_bool(request_match.group("strict_routing")),
                    strict_weights=_parse_bool(request_match.group("strict_weights")),
                    raw_lines=[line],
                )
                continue

            if current is None:
                continue

            current.raw_lines.append(line)

            no_overflow_match = NO_OVERFLOW_RE.search(line)
            if no_overflow_match:
                current.no_overflow_combo = no_overflow_match.group("combo")
                continue

            warm_gate_match = WARM_GATE_RE.search(line)
            if warm_gate_match:
                current.warm_start_mode = warm_gate_match.group("mode")
                current.warm_start_time_ready = _parse_bool(warm_gate_match.group("time_ready"))
                current.warm_start_min_ready = _parse_bool(warm_gate_match.group("min_ready"))
                current.warm_start_released = _parse_bool(warm_gate_match.group("released"))
                continue

            overflow_match = OVERFLOW_RE.search(line)
            if overflow_match:
                current.overflow_triggered = True
                current.overflow_specialist_min = float(overflow_match.group("specialist_min"))
                current.overflow_generalist_min = float(overflow_match.group("generalist_min"))
                current.overflow_imbalance_pct = float(overflow_match.group("imbalance_pct"))
                current.overflow_threshold_pct = int(overflow_match.group("threshold_pct"))
                continue

            selected_match = SELECTED_RE.search(line)
            if selected_match:
                current.logged_selected_worker = selected_match.group("worker")
                current.selected_skill = selected_match.group("skill")
                current.selected_modality = selected_match.group("modality")
                events.append(current)
                current = None
                continue

            if NO_WORKERS_RE.search(line):
                current.no_worker_available = True
                events.append(current)
                current = None

    if current is not None:
        events.append(current)

    return events


def _apply_name_alias(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    return ANALYSIS_NAME_ALIASES.get(name, name)


def _extract_bundle_root(source: Path) -> tuple[Path, Optional[tempfile.TemporaryDirectory[str]]]:
    if source.is_dir():
        return source, None

    if source.name.endswith(".tar.gz"):
        tmp = tempfile.TemporaryDirectory(prefix="radimo_bundle_extract_")
        extract_root = Path(tmp.name)
        import tarfile

        with tarfile.open(source, "r:gz") as tar:
            tar.extractall(extract_root)

        children = [child for child in extract_root.iterdir() if child.is_dir()]
        if len(children) == 1:
            return children[0], tmp
        return extract_root, tmp

    raise ValueError(f"Unsupported bundle source: {source}")


def _find_file(bundle_root: Path, relative_path: str) -> Path:
    candidate = bundle_root / relative_path
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Missing bundle file: {relative_path}")


def _prepare_temp_runtime(bundle_root: Path) -> tempfile.TemporaryDirectory[str]:
    runtime = tempfile.TemporaryDirectory(prefix="radimo_replay_runtime_")
    runtime_root = Path(runtime.name)

    (runtime_root / "data").mkdir(parents=True, exist_ok=True)
    (runtime_root / "uploads" / "backups").mkdir(parents=True, exist_ok=True)
    (runtime_root / "logs").mkdir(parents=True, exist_ok=True)

    for rel in [
        "config.yaml",
        "data/worker_skill_roster.json",
        "data/button_weights.json",
        "data/fairness_state.json",
        "uploads/master_medweb.csv",
    ]:
        source = _find_file(bundle_root, rel)
        target = runtime_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    return runtime


def _clear_runtime_state(config_module: Any, worker_management_module: Any, file_ops_module: Any) -> None:
    global_worker_data = worker_management_module.global_worker_data
    global_worker_data["worker_ids"] = {}
    global_worker_data["weighted_counts"] = {}
    global_worker_data["assignments_per_mod"] = {mod: {} for mod in config_module.allowed_modalities}
    global_worker_data["flow_cross_pool"] = {}
    global_worker_data["last_reset_date"] = None
    global_worker_data["last_preload_date"] = None
    global_worker_data["last_preload_source"] = None

    for mod in config_module.allowed_modalities:
        d = file_ops_module.modality_data[mod]
        d["last_reset_date"] = None


def _load_runtime_modules(runtime_root: Path) -> dict[str, Any]:
    original_cwd = Path.cwd()
    os.chdir(runtime_root)
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        config_module = importlib.import_module("config")
        file_ops_module = importlib.import_module("data_manager.file_ops")
        worker_management_module = importlib.import_module("data_manager.worker_management")
        csv_parser_module = importlib.import_module("data_manager.csv_parser")
        balancer_module = importlib.import_module("balancer")
        return {
            "config": config_module,
            "file_ops": file_ops_module,
            "worker_management": worker_management_module,
            "csv_parser": csv_parser_module,
            "balancer": balancer_module,
            "original_cwd": original_cwd,
        }
    except Exception:
        os.chdir(original_cwd)
        raise


def _load_schedule_from_snapshot_or_csv(
    runtime_root: Path,
    modules: dict[str, Any],
    target_date: date,
    snapshot_path: Optional[Path],
) -> str:
    file_ops_module = modules["file_ops"]
    config_module = modules["config"]
    worker_management_module = modules["worker_management"]

    worker_management_module.load_worker_skill_json()
    if snapshot_path and snapshot_path.exists():
        loaded = file_ops_module.initialize_data_from_unified(str(snapshot_path), context="replay snapshot")
        if not loaded:
            raise ValueError(f"Failed to initialize unified snapshot: {snapshot_path}")
        return "snapshot"

    csv_path = runtime_root / "uploads" / "master_medweb.csv"
    target_dt = datetime.combine(target_date, time(0, 0))
    modality_dfs = modules["csv_parser"].build_working_hours_from_medweb(
        str(csv_path),
        target_dt,
        config_module.APP_CONFIG,
    )
    for modality in config_module.allowed_modalities:
        df = modality_dfs.get(modality)
        if df is None:
            import pandas as pd
            df = pd.DataFrame()
        file_ops_module._set_live_modality_data(modality, df, [], {})
    return "csv"


def _apply_analysis_aliases(modules: dict[str, Any], events: list[AssignmentEvent]) -> None:
    file_ops_module = modules["file_ops"]
    worker_management_module = modules["worker_management"]

    for modality in file_ops_module.modality_data.keys():
        df = file_ops_module.modality_data[modality]["working_hours_df"]
        if df is None or df.empty or "PPL" not in df.columns:
            continue
        aliased = df["PPL"].apply(_apply_name_alias)
        if aliased.equals(df["PPL"]):
            continue
        df = df.copy()
        df["PPL"] = aliased
        file_ops_module.modality_data[modality]["working_hours_df"] = df

    updated_worker_ids: dict[str, str] = {}
    for name, canonical_id in worker_management_module.global_worker_data["worker_ids"].items():
        updated_worker_ids[_apply_name_alias(name)] = canonical_id
    worker_management_module.global_worker_data["worker_ids"] = updated_worker_ids

    for event in events:
        event.logged_selected_worker = _apply_name_alias(event.logged_selected_worker)


def _install_real_person_hours(modules: dict[str, Any]) -> None:
    balancer_module = modules["balancer"]
    file_ops_module = modules["file_ops"]
    worker_management_module = modules["worker_management"]

    def calculate_real_person_hours_now(current_dt: datetime) -> dict[str, float]:
        intervals_by_worker: dict[str, list[tuple[datetime, datetime]]] = {}

        for modality in file_ops_module.modality_data.keys():
            df = file_ops_module.modality_data[modality]["working_hours_df"]
            if df is None or df.empty:
                continue

            working_df = df
            if "counts_for_hours" in working_df.columns:
                working_df = working_df.loc[working_df["counts_for_hours"].fillna(True).astype(bool)]
            gap_mask = importlib.import_module("lib.utils").gap_row_mask(working_df)
            working_df = working_df.loc[~gap_mask]
            if working_df.empty:
                continue

            for _, row in working_df.iterrows():
                worker_name = row.get("PPL")
                if not worker_name:
                    continue
                start_dt, end_dt = importlib.import_module("lib.utils").compute_shift_window(
                    row["start_time"],
                    row["end_time"],
                    current_dt,
                )
                if current_dt <= start_dt:
                    continue
                effective_end = min(end_dt, current_dt)
                if effective_end <= start_dt:
                    continue
                canonical_id = worker_management_module.get_canonical_worker_id(worker_name)
                intervals_by_worker.setdefault(canonical_id, []).append((start_dt, effective_end))

        result: dict[str, float] = {}
        for canonical_id, intervals in intervals_by_worker.items():
            merged: list[list[datetime]] = []
            for start_dt, end_dt in sorted(intervals, key=lambda item: (item[0], item[1])):
                if not merged or start_dt > merged[-1][1]:
                    merged.append([start_dt, end_dt])
                elif end_dt > merged[-1][1]:
                    merged[-1][1] = end_dt
            hours = sum((end_dt - start_dt).total_seconds() / 3600.0 for start_dt, end_dt in merged)
            result[canonical_id] = hours
        return result

    balancer_module.calculate_global_work_hours_now = calculate_real_person_hours_now


def _filter_active_rows(modules: dict[str, Any], modality: str, current_dt: datetime):
    balancer_module = modules["balancer"]
    modality_data = modules["file_ops"].modality_data
    df = modality_data[modality]["working_hours_df"]
    return balancer_module._filter_active_rows(df, current_dt)


def _find_active_selected_row(
    modules: dict[str, Any],
    current_dt: datetime,
    worker: str,
    modality: str,
    skill: str,
):
    active_df = _filter_active_rows(modules, modality, current_dt)
    if active_df is None or active_df.empty:
        return None

    rows = active_df[active_df["PPL"] == worker]
    if rows.empty:
        return None

    if skill in rows.columns:
        preferred = rows[rows[skill].notna()]
        if not preferred.empty:
            rows = preferred

    return rows.iloc[0]


def _build_candidate_pool(
    modules: dict[str, Any],
    current_dt: datetime,
    role: str,
    modality: str,
    allow_overflow: bool,
) -> dict[str, Any]:
    balancer_module = modules["balancer"]
    config_module = modules["config"]
    worker_management_module = modules["worker_management"]
    utils_module = importlib.import_module("lib.utils")

    role_lower = role.lower()
    primary_skill = config_module.ROLE_MAP.get(role_lower, role_lower)
    active_df = _filter_active_rows(modules, modality, current_dt)
    if active_df is None or active_df.empty or primary_skill not in active_df.columns:
        return {
            "primary_skill": primary_skill,
            "eligible_specialists": [],
            "eligible_generalists": [],
            "overflow_released": False,
            "overflow_triggered_by_ratio": False,
        }

    filtered = active_df[
        active_df[primary_skill].apply(lambda value: utils_module.skill_value_to_numeric(value) >= 0)
    ]
    for skill_to_exclude in config_module.EXCLUDE_SKILLS.get(primary_skill, []):
        if skill_to_exclude in filtered.columns:
            filtered = filtered[
                filtered[skill_to_exclude].apply(lambda value: utils_module.skill_value_to_numeric(value) < 1)
            ]

    global_hours = balancer_module.calculate_global_work_hours_now(current_dt)

    def ratio_for(worker_name: str) -> float:
        canonical_id = worker_management_module.get_canonical_worker_id(worker_name)
        hours_worked = global_hours.get(canonical_id, 0.0)
        weighted_count = balancer_module.get_global_weighted_count(canonical_id)
        if hours_worked <= 0:
            return 0.0 if weighted_count <= 0 else float("inf")
        return weighted_count / hours_worked

    specialists_df = filtered[
        filtered[primary_skill].apply(lambda value: utils_module.skill_value_to_numeric(value) == 1)
    ]
    generalists_df = filtered[
        filtered[primary_skill].apply(lambda value: utils_module.skill_value_to_numeric(value) == 0)
    ]

    if not generalists_df.empty:
        end_buffer = config_module.BALANCER_SETTINGS.get("disable_overflow_at_shift_end_minutes", 0)
        generalists_df = balancer_module._filter_near_shift_end(generalists_df, current_dt, end_buffer)

    specialists = []
    for worker_name in specialists_df["PPL"].dropna().unique():
        specialists.append({
            "worker": worker_name,
            "ratio": ratio_for(worker_name),
            "weighted": bool(
                utils_module.is_weighted_skill(
                    specialists_df[specialists_df["PPL"] == worker_name].iloc[0].get(primary_skill)
                )
            ),
        })
    specialists.sort(key=lambda item: (item["ratio"], item["worker"]))

    generalists = []
    for worker_name in generalists_df["PPL"].dropna().unique():
        generalists.append({
            "worker": worker_name,
            "ratio": ratio_for(worker_name),
        })
    generalists.sort(key=lambda item: (item["ratio"], item["worker"]))

    overflow_released = False
    overflow_triggered = False
    if allow_overflow and not specialists_df.empty and not generalists_df.empty:
        overflow_released = balancer_module._overflow_released_by_warm_start(
            specialists_df,
            primary_skill,
            modality,
            current_dt,
        )
        if overflow_released and specialists and generalists:
            min_specialist = min(item["ratio"] for item in specialists)
            min_generalist = min(item["ratio"] for item in generalists)
            if min_generalist < min_specialist:
                specialist_avg = sum(item["ratio"] for item in specialists) / len(specialists)
                generalist_avg = sum(item["ratio"] for item in generalists) / len(generalists)
                baseline = max(specialist_avg, generalist_avg)
                imbalance_pct = 0.0 if baseline <= 0 else ((min_specialist - min_generalist) / baseline) * 100
                overflow_triggered = imbalance_pct >= config_module.BALANCER_SETTINGS.get("imbalance_threshold_pct", 30)

    return {
        "primary_skill": primary_skill,
        "eligible_specialists": specialists,
        "eligible_generalists": generalists,
        "overflow_released": overflow_released,
        "overflow_triggered_by_ratio": overflow_triggered,
    }


def _bootstrap_focused_team(roster_path: Path, skill_modalities: Iterable[str]) -> dict[str, dict[str, Any]]:
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    members: dict[str, dict[str, Any]] = {}
    for worker_id, worker_data in roster.items():
        if not isinstance(worker_data, dict):
            continue
        if any(str(worker_data.get(skill_modality, -1)).strip() in {"1", "w"} for skill_modality in skill_modalities):
            members[worker_id] = {
                "worker_id": worker_id,
                "display_name": worker_data.get("full_name", worker_id),
                "skills": {skill_modality: worker_data.get(skill_modality) for skill_modality in skill_modalities},
            }
    return members


def replay_day(
    bundle_root: Path,
    target_date: date,
    focus_skill: str,
    focus_modalities: list[str],
    output_dir: Path,
    snapshot_path: Optional[Path] = None,
) -> dict[str, Any]:
    runtime = _prepare_temp_runtime(bundle_root)
    runtime_root = Path(runtime.name)
    modules = _load_runtime_modules(runtime_root)
    try:
        schedule_source = _load_schedule_from_snapshot_or_csv(runtime_root, modules, target_date, snapshot_path)
        _clear_runtime_state(modules["config"], modules["worker_management"], modules["file_ops"])

        events = parse_assignment_events(_find_file(bundle_root, "logs/selection.log"), target_date)
        _apply_analysis_aliases(modules, events)
        _install_real_person_hours(modules)
        focus_modality_set = set(focus_modalities)
        focus_skill_modalities = [f"{focus_skill}_{mod}" for mod in focus_modalities]
        focused_team = _bootstrap_focused_team(_find_file(bundle_root, "data/worker_skill_roster.json"), focus_skill_modalities)

        focus_rows: list[dict[str, Any]] = []
        focus_summary: dict[str, dict[str, Any]] = {
            worker_id: {
                **member,
                "actual_total": 0.0,
                "actual_ct": 0.0,
                "actual_mr": 0.0,
                "expected_total": 0.0,
                "expected_ct": 0.0,
                "expected_mr": 0.0,
            }
            for worker_id, member in focused_team.items()
        }

        total_selected_events = 0
        replay_matches = 0
        overflow_generalist_count = 0
        focused_event_count = 0

        for event in events:
            if not event.logged_selected_worker or not event.selected_skill or not event.selected_modality:
                continue

            total_selected_events += 1
            allow_overflow = not event.strict_routing
            predicted_worker = None
            predicted_skill = None
            predicted_modality = None
            pool = None

            if event.request_role == focus_skill and event.request_modality in focus_modality_set:
                focused_event_count += 1
                pool = _build_candidate_pool(
                    modules,
                    event.timestamp,
                    event.request_role,
                    event.request_modality,
                    allow_overflow,
                )
                predicted = modules["balancer"].get_next_available_worker(
                    event.timestamp,
                    role=event.request_role,
                    modality=event.request_modality,
                    allow_overflow=allow_overflow,
                    target_skill_modalities=None,
                )
                if predicted is not None:
                    candidate, predicted_skill, predicted_modality = predicted
                    predicted_candidate = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                    predicted_worker = predicted_candidate.get("PPL")

                eligible_specialists = pool["eligible_specialists"] if pool else []
                if eligible_specialists:
                    expected_share = 1.0 / len(eligible_specialists)
                    modality_key = event.request_modality
                    for specialist in eligible_specialists:
                        worker_id = modules["worker_management"].get_canonical_worker_id(specialist["worker"])
                        if worker_id in focus_summary:
                            focus_summary[worker_id]["expected_total"] += expected_share
                            focus_summary[worker_id][f"expected_{modality_key}"] += expected_share

                selected_row = _find_active_selected_row(
                    modules,
                    event.timestamp,
                    event.logged_selected_worker,
                    event.selected_modality,
                    event.selected_skill,
                )
                selected_skill_numeric = None
                selected_weighted = False
                if selected_row is not None and event.selected_skill in selected_row.index:
                    utils_module = importlib.import_module("lib.utils")
                    selected_skill_numeric = utils_module.skill_value_to_numeric(selected_row.get(event.selected_skill))
                    selected_weighted = bool(utils_module.is_weighted_skill(selected_row.get(event.selected_skill)))
                if selected_skill_numeric == 0:
                    overflow_generalist_count += 1

                selected_worker_id = modules["worker_management"].get_canonical_worker_id(event.logged_selected_worker)
                if selected_worker_id in focus_summary:
                    focus_summary[selected_worker_id]["actual_total"] += 1.0
                    focus_summary[selected_worker_id][f"actual_{event.selected_modality}"] += 1.0

                focus_rows.append({
                    "timestamp": event.timestamp.isoformat(sep=" "),
                    "request_modality": event.request_modality,
                    "request_role": event.request_role,
                    "logged_selected_worker": event.logged_selected_worker,
                    "logged_selected_worker_id": selected_worker_id,
                    "selected_skill": event.selected_skill,
                    "selected_modality": event.selected_modality,
                    "selected_skill_numeric": selected_skill_numeric,
                    "selected_weighted": selected_weighted,
                    "strict_routing": event.strict_routing,
                    "strict_weights": event.strict_weights,
                    "predicted_worker": predicted_worker,
                    "predicted_skill": predicted_skill,
                    "predicted_modality": predicted_modality,
                    "prediction_match": predicted_worker == event.logged_selected_worker and predicted_modality == event.selected_modality,
                    "log_overflow_triggered": event.overflow_triggered,
                    "log_warm_start_released": event.warm_start_released,
                    "pool_overflow_released": pool["overflow_released"] if pool else None,
                    "pool_overflow_triggered": pool["overflow_triggered_by_ratio"] if pool else None,
                    "eligible_specialists": json.dumps(pool["eligible_specialists"], ensure_ascii=False) if pool else "[]",
                    "eligible_generalists": json.dumps(pool["eligible_generalists"], ensure_ascii=False) if pool else "[]",
                    "raw_lines": " | ".join(event.raw_lines),
                })

                if predicted_worker == event.logged_selected_worker and predicted_modality == event.selected_modality:
                    replay_matches += 1

            selected_row = _find_active_selected_row(
                modules,
                event.timestamp,
                event.logged_selected_worker,
                event.selected_modality,
                event.selected_skill,
            )
            utils_module = importlib.import_module("lib.utils")
            shift_modifier = 1.0
            is_weighted = False
            if selected_row is not None:
                shift_modifier = float(selected_row.get("Modifier", 1.0) or 1.0)
                if event.selected_skill in selected_row.index:
                    is_weighted = bool(utils_module.is_weighted_skill(selected_row.get(event.selected_skill)))

            modules["balancer"].update_global_assignment(
                event.logged_selected_worker,
                event.selected_skill,
                event.selected_modality,
                is_weighted=is_weighted,
                strict_mode=event.strict_weights,
                shift_modifier_override=shift_modifier,
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"replay_{target_date.isoformat()}_{focus_skill}.csv"
        json_path = output_dir / f"replay_{target_date.isoformat()}_{focus_skill}.json"

        csv_fields = list(focus_rows[0].keys()) if focus_rows else [
            "timestamp",
            "request_modality",
            "request_role",
            "logged_selected_worker",
            "selected_skill",
            "selected_modality",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(focus_rows)

        summary_payload = {
            "target_date": target_date.isoformat(),
            "focus_skill": focus_skill,
            "focus_modalities": focus_modalities,
            "schedule_source": schedule_source,
            "snapshot_path": str(snapshot_path) if snapshot_path else None,
            "selected_events_total": total_selected_events,
            "focused_events_total": focused_event_count,
            "focused_prediction_matches": replay_matches,
            "focused_overflow_generalist_count": overflow_generalist_count,
            "team_summary": list(focus_summary.values()),
            "focused_events": focus_rows,
        }
        json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "csv_path": str(csv_path),
            "json_path": str(json_path),
            "summary": summary_payload,
        }
    finally:
        original_cwd = modules.get("original_cwd") if isinstance(modules, dict) else None
        if original_cwd is not None:
            os.chdir(original_cwd)
        runtime.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay RadIMO distribution decisions for a historical day")
    parser.add_argument("--bundle", required=True, help="Bundle directory or .tar.gz archive")
    parser.add_argument("--target-date", default="2026-04-08", help="Target date in YYYY-MM-DD")
    parser.add_argument("--focus-skill", default="mdh", help="Primary skill to analyze")
    parser.add_argument("--focus-modalities", nargs="+", default=["ct", "mr"], help="Modalities to analyze")
    parser.add_argument("--snapshot", help="Optional dated snapshot JSON for the target day")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for CSV/JSON reports (default: /tmp/radimo_replay_<date>)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_date = date.fromisoformat(args.target_date)
    bundle_source = Path(args.bundle).expanduser().resolve()
    bundle_root, extracted_tmp = _extract_bundle_root(bundle_source)
    snapshot_path = Path(args.snapshot).expanduser().resolve() if args.snapshot else None
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path("/tmp") / f"radimo_replay_{target_date.isoformat()}"
    )

    try:
        result = replay_day(
            bundle_root=bundle_root,
            target_date=target_date,
            focus_skill=args.focus_skill,
            focus_modalities=list(args.focus_modalities),
            output_dir=output_dir,
            snapshot_path=snapshot_path,
        )
        print(json.dumps({
            "csv_path": result["csv_path"],
            "json_path": result["json_path"],
            "schedule_source": result["summary"]["schedule_source"],
            "focused_events_total": result["summary"]["focused_events_total"],
            "focused_prediction_matches": result["summary"]["focused_prediction_matches"],
            "focused_overflow_generalist_count": result["summary"]["focused_overflow_generalist_count"],
        }, ensure_ascii=False, indent=2))
    finally:
        if extracted_tmp is not None:
            extracted_tmp.cleanup()


if __name__ == "__main__":
    main()
