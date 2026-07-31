#!/usr/bin/env python3
"""Generate slide-ready worker/team load plots for synthetic RadIMO scenarios.

The script supports:
  - a 60-case two-team origin split
  - a realistic CT/MR day map with staggered coverage and mixed shifts

Both modes use the current balancer settings from config.yaml.

Outputs:
  - a combined worker-level line plot
  - a case log CSV
  - a team origin breakdown CSV
  - a JSON summary for traceability
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("/home/dpxuser/work/radimo_cortex_distribution")
DEFAULT_REALISTIC_OUTPUT_DIR = Path("/home/dpxuser/work/radimo_cortex_realistic_day")
DEFAULT_IMBALANCE_OUTPUT_DIR = Path("/home/dpxuser/work/radimo_cortex_imbalance_test")


@dataclass(frozen=True)
class Worker:
    name: str
    team: str


@dataclass(frozen=True)
class RealisticWorker:
    name: str
    group: str
    shift_start_minute: int
    shift_end_minute: int


@dataclass(frozen=True)
class DayCase:
    case_index: int
    phase: str
    origin_group: str
    modality: str
    minute: int
    weight: float


def load_yaml_config(repo_root: Path = REPO_ROOT) -> dict:
    import yaml

    config_path = repo_root / "config.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_balancer_settings(config: Mapping[str, object]) -> dict:
    balancer = config.get("balancer", {})
    return dict(balancer) if isinstance(balancer, Mapping) else {}


def build_origin_sequence(
    total_cases: int,
    origin_totals: Mapping[str, int],
    first_team: str,
    first_run: int,
) -> List[str]:
    """Build a deterministic origin sequence that respects the requested totals."""
    if total_cases <= 0:
        return []
    if not origin_totals:
        raise ValueError("origin_totals must not be empty")
    if sum(origin_totals.values()) != total_cases:
        raise ValueError("origin_totals must sum to total_cases")

    first_team = str(first_team)
    if first_team not in origin_totals:
        raise ValueError(f"first_team '{first_team}' not in origin_totals")

    sequence = [first_team] * min(first_run, origin_totals[first_team], total_cases)
    counts = {team: 0 for team in origin_totals}
    counts[first_team] = len(sequence)

    remaining = {
        team: origin_totals[team] - counts[team]
        for team in origin_totals
    }

    while len(sequence) < total_cases:
        eligible = [team for team, remaining_count in remaining.items() if remaining_count > 0]
        if not eligible:
            break

        def fill_ratio(team: str) -> Tuple[float, int, str]:
            target = origin_totals[team]
            ratio = counts[team] / target if target else 1.0
            # Prefer the team that is furthest behind its target share.
            return (ratio, -remaining[team], team)

        pick = min(eligible, key=fill_ratio)
        sequence.append(pick)
        counts[pick] += 1
        remaining[pick] -= 1

    if len(sequence) != total_cases:
        raise RuntimeError("Failed to build a full origin sequence")
    return sequence


def build_realistic_workers() -> List[RealisticWorker]:
    """Return a small CT/MR roster with staggered shifts."""
    return [
        RealisticWorker("AOU1", "AOU", 0, 495),
        RealisticWorker("CVT1", "CVT", 0, 495),
        RealisticWorker("MDH1", "MDH", 0, 495),
        RealisticWorker("GYN", "GYN", 0, 495),
        RealisticWorker("NOTFALL", "NOTFALL", 0, 495),
        RealisticWorker("Late1", "AOU", 240, 750),
        RealisticWorker("Late2", "CVT", 240, 750),
        RealisticWorker("Late3", "MDH", 240, 750),
    ]


def build_imbalance_test_workers() -> List[RealisticWorker]:
    """Return a two-early-per-group roster for imbalance testing."""
    return [
        RealisticWorker("AOU1", "AOU", 0, 495),
        RealisticWorker("AOU2", "AOU", 0, 495),
        RealisticWorker("CVT1", "CVT", 0, 495),
        RealisticWorker("CVT2", "CVT", 0, 495),
        RealisticWorker("MDH1", "MDH", 0, 495),
        RealisticWorker("MDH2", "MDH", 0, 495),
        RealisticWorker("GYN", "GYN", 0, 495),
        RealisticWorker("NOTFALL", "NOTFALL", 0, 495),
        RealisticWorker("Late1", "AOU", 240, 750),
        RealisticWorker("Late2", "CVT", 240, 750),
        RealisticWorker("Late3", "MDH", 240, 750),
    ]


def build_realistic_day_cases(seed: int = 12345) -> List[DayCase]:
    """Build a realistic CT/MR day with exact totals and phase structure."""
    rng = random.Random(seed)

    phases = [
        {
            "name": "early",
            "start": 0,
            "end": 180,
            "group_counts": {"AOU": 8, "CVT": 8, "MDH": 8, "GYN": 4, "NOTFALL": 2},
            "modality_counts": {"CT": 15, "MR": 15},
            "phase_bias": -0.02,
        },
        {
            "name": "core",
            "start": 180,
            "end": 495,
            "group_counts": {"AOU": 15, "CVT": 15, "MDH": 15, "GYN": 9, "NOTFALL": 6},
            "modality_counts": {"CT": 30, "MR": 30},
            "phase_bias": 0.06,
        },
        {
            "name": "late",
            "start": 495,
            "end": 750,
            "group_counts": {"AOU": 10, "CVT": 10, "MDH": 10, "GYN": 0, "NOTFALL": 0},
            "modality_counts": {"CT": 15, "MR": 15},
            "phase_bias": 0.01,
        },
    ]

    modality_bias = {"CT": -0.04, "MR": 0.04}
    group_bias = {"AOU": 0.05, "CVT": 0.05, "MDH": 0.03, "GYN": 0.02, "NOTFALL": 0.0}

    cases: List[DayCase] = []
    case_index = 1
    for phase in phases:
        group_entries: List[str] = []
        for group, count in phase["group_counts"].items():
            group_entries.extend([group] * int(count))
        modality_entries: List[str] = []
        for modality, count in phase["modality_counts"].items():
            modality_entries.extend([modality] * int(count))
        if len(group_entries) != len(modality_entries):
            raise ValueError(f"Phase {phase['name']} group/modalities mismatch")

        rng.shuffle(group_entries)
        rng.shuffle(modality_entries)
        phase_minutes = sorted(
            rng.randint(phase["start"], phase["end"] - 1)
            for _ in range(len(group_entries))
        )

        for minute, origin_group, modality in zip(phase_minutes, group_entries, modality_entries):
            weight = 1.0 + modality_bias[modality] + phase["phase_bias"] + group_bias[origin_group]
            weight += rng.uniform(-0.05, 0.05)
            weight = max(0.45, round(weight, 2))
            cases.append(
                DayCase(
                    case_index=case_index,
                    phase=phase["name"],
                    origin_group=origin_group,
                    modality=modality,
                    minute=minute,
                    weight=weight,
                )
            )
            case_index += 1

    cases.sort(key=lambda case: (case.minute, case.case_index))
    return cases


def build_imbalance_test_cases(seed: int = 12345) -> List[DayCase]:
    """Build a 15-case day with a fixed team skew and randomised timing/weights."""
    rng = random.Random(seed)
    origin_groups = ["AOU", "CVT", "MDH"]

    # Keep the mix reproducible but still visibly imbalanced for the worker-load plot.
    counts = {"AOU": 6, "CVT": 5, "MDH": 4}

    origin_entries: List[str] = []
    for group in origin_groups:
        origin_entries.extend([group] * counts[group])
    rng.shuffle(origin_entries)

    minute_entries = sorted(rng.sample(range(45, 705), 15))
    case_weights = [round(rng.uniform(0.75, 1.35), 2) for _ in range(15)]
    modality_entries = ["CT" if rng.random() < 0.6 else "MR" for _ in range(15)]

    cases: List[DayCase] = []
    for case_index, (minute, origin_group, modality, weight) in enumerate(
        zip(minute_entries, origin_entries, modality_entries, case_weights),
        start=1,
    ):
        cases.append(
            DayCase(
                case_index=case_index,
                phase="imbalance",
                origin_group=origin_group,
                modality=modality,
                minute=minute,
                weight=weight,
            )
        )

    return cases


def build_random_origin_sequence(
    total_cases: int,
    origin_totals: Mapping[str, int],
    rng: random.Random,
) -> List[str]:
    """Build a randomized origin sequence with the same totals."""
    sequence: List[str] = []
    for team, total in origin_totals.items():
        sequence.extend([team] * int(total))
    if len(sequence) != total_cases:
        raise ValueError("origin_totals must sum to total_cases")
    rng.shuffle(sequence)
    return sequence


def build_worst_case_origin_sequence(
    total_cases: int,
    origin_totals: Mapping[str, int],
    first_team: str = "B",
) -> List[str]:
    """Build a worst-case origin sequence (all of one team, then the other)."""
    if total_cases <= 0:
        return []
    if sum(origin_totals.values()) != total_cases:
        raise ValueError("origin_totals must sum to total_cases")
    first_team = str(first_team)
    if first_team not in origin_totals:
        raise ValueError(f"first_team '{first_team}' not in origin_totals")
    other_teams = [team for team in origin_totals if team != first_team]
    if len(other_teams) != 1:
        raise ValueError("worst-case sequence expects exactly two teams")
    other_team = other_teams[0]
    return [first_team] * int(origin_totals[first_team]) + [other_team] * int(origin_totals[other_team])


def _minute_to_clock_label(minute: int) -> str:
    base_minutes = 7 * 60 + 30 + minute
    hour = (base_minutes // 60) % 24
    minute_in_hour = base_minutes % 60
    return f"{hour:02d}:{minute_in_hour:02d}"


def _choose_worker(worker_names: Sequence[str], loads: Mapping[str, int]) -> str:
    return min(worker_names, key=lambda name: (loads[name], name))


def simulate_distribution(
    origin_sequence: Sequence[str],
    workers_by_team: Mapping[str, Sequence[Worker]],
    balancer_settings: Mapping[str, object],
    *,
    total_day_minutes: int = 540,
    start_buffer_minutes: int = 15,
    end_buffer_minutes: int = 20,
) -> dict:
    """Simulate a RadIMO-like team-aware distribution for a fixed origin sequence."""
    team_names = list(workers_by_team.keys())
    if len(team_names) != 2:
        raise ValueError("This synthetic simulation expects exactly two teams")

    team_a, team_b = team_names
    all_workers = [worker for team in team_names for worker in workers_by_team[team]]
    loads = {worker.name: 0 for worker in all_workers}
    worker_team = {worker.name: worker.team for worker in all_workers}
    worker_series = {worker.name: [] for worker in all_workers}

    min_assignments_per_skill = int(balancer_settings.get("min_assignments_per_skill", 3) or 0)
    imbalance_threshold_pct = float(balancer_settings.get("imbalance_threshold_pct", 20) or 0.0)
    warm_start_release_mode = str(
        balancer_settings.get("warm_start_release_mode", "either")
    ).strip().lower()
    if warm_start_release_mode not in {"either", "both"}:
        warm_start_release_mode = "either"

    case_minutes = total_day_minutes / max(len(origin_sequence), 1)
    rows: List[dict] = []
    origin_matrix = {
        team_a: {team_a: 0, team_b: 0},
        team_b: {team_a: 0, team_b: 0},
    }

    for idx, origin_team in enumerate(origin_sequence, start=1):
        current_minute = (idx - 1) * case_minutes
        minutes_until_end = total_day_minutes - current_minute
        time_ready = (
            current_minute > start_buffer_minutes
            and minutes_until_end > end_buffer_minutes
        )

        specialists = [worker.name for worker in workers_by_team[origin_team]]
        generalists = [
            worker.name
            for team in team_names
            if team != origin_team
            for worker in workers_by_team[team]
        ]

        under_min = [worker for worker in specialists if loads[worker] < min_assignments_per_skill]
        if under_min:
            selected_pool = under_min
            selection_reason = "min_floor"
        else:
            minimum_ready = all(loads[worker] >= min_assignments_per_skill for worker in specialists)
            overflow_released = minimum_ready if warm_start_release_mode == "both" else (time_ready or minimum_ready)

            def ratio(worker_name: str) -> float:
                # Synthetic scenario: equal hours per worker, so ratio collapses to cumulative load.
                return float(loads[worker_name])

            spec_min = min(ratio(worker) for worker in specialists)
            spec_avg = sum(ratio(worker) for worker in specialists) / len(specialists)
            gen_min = min(ratio(worker) for worker in generalists)
            gen_avg = sum(ratio(worker) for worker in generalists) / len(generalists)
            baseline = max(spec_avg, gen_avg)
            imbalance_pct = 0.0
            if baseline > 0 and gen_min < spec_min:
                imbalance_pct = ((spec_min - gen_min) / baseline) * 100.0

            if overflow_released and gen_min < spec_min and imbalance_pct >= imbalance_threshold_pct:
                selected_pool = generalists
                selection_reason = "overflow"
            else:
                selected_pool = specialists
                selection_reason = "specialist"

        chosen_worker = _choose_worker(selected_pool, loads)
        loads[chosen_worker] += 1
        handled_team = worker_team[chosen_worker]
        origin_matrix[origin_team][handled_team] += 1

        for worker_name in worker_series:
            worker_series[worker_name].append(loads[worker_name])

        rows.append(
            {
                "case_index": idx,
                "origin_team": origin_team,
                "handled_team": handled_team,
                "worker": chosen_worker,
                "selection_reason": selection_reason,
                "current_minute": round(current_minute, 2),
                "minutes_until_end": round(minutes_until_end, 2),
                "worker_load_after": loads[chosen_worker],
                "team_a_total_after": sum(loads[w.name] for w in workers_by_team[team_a]),
                "team_b_total_after": sum(loads[w.name] for w in workers_by_team[team_b]),
            }
        )

    team_totals = {
        team: sum(loads[worker.name] for worker in workers_by_team[team])
        for team in team_names
    }
    origin_summary = {
        team: {
            "origin_total": sum(origin_matrix[team].values()),
            "handled_by_own_team": origin_matrix[team][team],
            "handled_by_other_team": sum(
                count for handled_team, count in origin_matrix[team].items() if handled_team != team
            ),
        }
        for team in team_names
    }
    for team in origin_summary:
        total = origin_summary[team]["origin_total"] or 1
        origin_summary[team]["own_share_pct"] = round(
            (origin_summary[team]["handled_by_own_team"] / total) * 100.0, 1
        )
        origin_summary[team]["help_share_pct"] = round(
            (origin_summary[team]["handled_by_other_team"] / total) * 100.0, 1
        )

    return {
        "rows": rows,
        "loads": loads,
        "worker_series": worker_series,
        "origin_matrix": origin_matrix,
        "origin_summary": origin_summary,
        "team_totals": team_totals,
        "settings": {
            "min_assignments_per_skill": min_assignments_per_skill,
            "imbalance_threshold_pct": imbalance_threshold_pct,
            "warm_start_release_mode": warm_start_release_mode,
            "start_buffer_minutes": start_buffer_minutes,
            "end_buffer_minutes": end_buffer_minutes,
            "total_day_minutes": total_day_minutes,
            "case_minutes": round(case_minutes, 2),
        },
    }


def _worker_minutes_active(worker: RealisticWorker, minute: int) -> int:
    if minute < worker.shift_start_minute:
        return 0
    return max(1, minute - worker.shift_start_minute)


def _worker_ratio_realistic(loads: Mapping[str, float], worker: RealisticWorker, minute: int) -> float:
    active_minutes = _worker_minutes_active(worker, minute)
    if active_minutes <= 0:
        return float("inf") if loads[worker.name] > 0 else 0.0
    return float(loads[worker.name]) / (active_minutes / 60.0)


def _choose_worker_realistic(worker_names: Sequence[str], loads: Mapping[str, float], minute: int, roster: Mapping[str, RealisticWorker]) -> str:
    def sort_key(name: str) -> Tuple[float, float, str]:
        worker = roster[name]
        return (_worker_ratio_realistic(loads, worker, minute), loads[name], name)

    return min(worker_names, key=sort_key)


def simulate_realistic_day(
    cases: Sequence[DayCase],
    workers: Sequence[RealisticWorker],
    balancer_settings: Mapping[str, object],
    *,
    total_day_minutes: int = 750,
    start_buffer_minutes: int = 15,
    end_buffer_minutes: int = 20,
) -> dict:
    """Simulate a realistic CT/MR day with staggered shifts and 5 origin groups."""
    roster = {worker.name: worker for worker in workers}
    group_names = sorted({worker.group for worker in workers})
    loads = {worker.name: 0.0 for worker in workers}
    worker_series = {worker.name: [] for worker in workers}
    group_matrix = {
        group: {other_group: 0 for other_group in group_names}
        for group in group_names
    }
    min_assignments_per_skill = float(balancer_settings.get("min_assignments_per_skill", 3) or 0.0)
    imbalance_threshold_pct = float(balancer_settings.get("imbalance_threshold_pct", 20) or 0.0)
    warm_start_release_mode = str(
        balancer_settings.get("warm_start_release_mode", "either")
    ).strip().lower()
    if warm_start_release_mode not in {"either", "both"}:
        warm_start_release_mode = "either"

    rows: List[dict] = []
    for case in sorted(cases, key=lambda item: (item.minute, item.case_index)):
        current_minute = case.minute
        minutes_until_end = total_day_minutes - current_minute
        active_workers = [
            worker for worker in workers
            if worker.shift_start_minute <= current_minute < worker.shift_end_minute
        ]
        if not active_workers:
            active_workers = [
                worker for worker in workers
                if worker.shift_start_minute <= current_minute or worker.shift_end_minute >= current_minute
            ]

        if current_minute < 495:
            specialists = [
                worker
                for worker in active_workers
                if worker.shift_end_minute <= 495 and worker.group == case.origin_group
            ]
            helpers = [worker for worker in active_workers if worker not in specialists]
        else:
            specialists = list(active_workers)
            helpers = []

        if specialists:
            under_min = [worker for worker in specialists if loads[worker.name] < min_assignments_per_skill]
            if under_min:
                selected_pool = under_min
                selection_reason = "min_floor"
            else:
                minimum_ready = all(loads[worker.name] >= min_assignments_per_skill for worker in specialists)
                time_ready = (
                    current_minute > start_buffer_minutes
                    and minutes_until_end > end_buffer_minutes
                )
                overflow_released = minimum_ready if warm_start_release_mode == "both" else (time_ready or minimum_ready)

                spec_min = min(_worker_ratio_realistic(loads, worker, current_minute) for worker in specialists)
                spec_avg = sum(_worker_ratio_realistic(loads, worker, current_minute) for worker in specialists) / len(specialists)
                helper_min = min(_worker_ratio_realistic(loads, worker, current_minute) for worker in helpers) if helpers else float("inf")
                helper_avg = sum(_worker_ratio_realistic(loads, worker, current_minute) for worker in helpers) / len(helpers) if helpers else float("inf")
                baseline = max(spec_avg, helper_avg)
                imbalance_pct = 0.0
                if baseline > 0 and helper_min < spec_min:
                    imbalance_pct = ((spec_min - helper_min) / baseline) * 100.0

                if overflow_released and helpers and helper_min < spec_min and imbalance_pct >= imbalance_threshold_pct:
                    selected_pool = helpers
                    selection_reason = "overflow"
                else:
                    selected_pool = specialists
                    selection_reason = "specialist"
        else:
            selected_pool = active_workers
            selection_reason = "no_specialist"

        chosen_worker = _choose_worker_realistic(
            [worker.name for worker in selected_pool],
            loads,
            current_minute,
            roster,
        )
        loads[chosen_worker] += case.weight
        handled_group = roster[chosen_worker].group
        group_matrix[case.origin_group][handled_group] += 1

        for worker_name in worker_series:
            worker_series[worker_name].append(round(loads[worker_name], 2))

        rows.append(
            {
                "case_index": case.case_index,
                "phase": case.phase,
                "origin_group": case.origin_group,
                "handled_group": handled_group,
                "modality": case.modality,
                "minute": case.minute,
                "time_hhmm": _minute_to_clock_label(case.minute),
                "weight": case.weight,
                "worker": chosen_worker,
                "selection_reason": selection_reason,
                "worker_load_after": round(loads[chosen_worker], 2),
                "current_minute": current_minute,
                "minutes_until_end": minutes_until_end,
            }
        )

    weighted_group_totals = {
        group: round(sum(loads[worker.name] for worker in workers if worker.group == group), 2)
        for group in group_names
    }
    team_case_totals = {
        group: sum(group_matrix[origin_group][group] for origin_group in group_names)
        for group in group_names
    }
    origin_summary = {
        group: {
            "origin_total": sum(group_matrix[group].values()),
            "handled_by_own_group": group_matrix[group][group],
            "handled_by_other_groups": sum(
                count for handled_group, count in group_matrix[group].items() if handled_group != group
            ),
        }
        for group in group_names
    }
    for group in origin_summary:
        total = origin_summary[group]["origin_total"] or 1
        origin_summary[group]["own_share_pct"] = round(
            (origin_summary[group]["handled_by_own_group"] / total) * 100.0, 1
        )
        origin_summary[group]["help_share_pct"] = round(
            (origin_summary[group]["handled_by_other_groups"] / total) * 100.0, 1
        )
        origin_summary[group]["handled_by_own_team"] = origin_summary[group]["handled_by_own_group"]
        origin_summary[group]["handled_by_other_team"] = origin_summary[group]["handled_by_other_groups"]

    settings = {
        "min_assignments_per_skill": min_assignments_per_skill,
        "imbalance_threshold_pct": imbalance_threshold_pct,
        "warm_start_release_mode": warm_start_release_mode,
        "start_buffer_minutes": start_buffer_minutes,
        "end_buffer_minutes": end_buffer_minutes,
        "total_day_minutes": total_day_minutes,
        "worker_count": len(workers),
        "case_count": len(cases),
    }

    return {
        "rows": rows,
        "loads": {name: round(value, 2) for name, value in loads.items()},
        "worker_series": worker_series,
        "origin_matrix": group_matrix,
        "origin_summary": origin_summary,
        "group_totals": team_case_totals,
        "team_totals": team_case_totals,
        "weighted_group_totals": weighted_group_totals,
        "settings": settings,
        "cases": [case.__dict__ for case in cases],
        "workers": [worker.__dict__ for worker in workers],
    }


def simulate_ensemble(
    runs: int,
    total_cases: int,
    origin_totals: Mapping[str, int],
    workers_by_team: Mapping[str, Sequence[Worker]],
    balancer_settings: Mapping[str, object],
    *,
    total_day_minutes: int = 540,
    start_buffer_minutes: int = 15,
    end_buffer_minutes: int = 20,
    seed: int = 12345,
    randomize: bool = True,
) -> dict:
    """Run multiple simulations and collect ensemble statistics."""
    simulations = []
    for run_idx in range(runs):
        rng = random.Random(seed + run_idx)
        if randomize:
            origin_sequence = build_random_origin_sequence(total_cases, origin_totals, rng)
        else:
            origin_sequence = build_origin_sequence(total_cases, origin_totals, first_team="A", first_run=6)
        sim = simulate_distribution(
            origin_sequence,
            workers_by_team,
            balancer_settings,
            total_day_minutes=total_day_minutes,
            start_buffer_minutes=start_buffer_minutes,
            end_buffer_minutes=end_buffer_minutes,
        )
        sim["run_idx"] = run_idx
        sim["origin_sequence"] = origin_sequence
        simulations.append(sim)

    worker_names = [worker.name for team in workers_by_team.values() for worker in team]
    team_names = list(workers_by_team.keys())
    case_count = total_cases

    worker_final_stats = {}
    worker_case_curves = {worker: [] for worker in worker_names}
    for sim in simulations:
        for worker in worker_names:
            worker_case_curves[worker].append(sim["worker_series"][worker])

    for worker in worker_names:
        final_values = [curve[-1] for curve in worker_case_curves[worker]]
        worker_final_stats[worker] = {
            "mean": sum(final_values) / len(final_values),
            "min": min(final_values),
            "max": max(final_values),
        }

    team_final_stats = {}
    for team in team_names:
        totals = [sim["team_totals"][team] for sim in simulations]
        team_final_stats[team] = {
            "mean": sum(totals) / len(totals),
            "min": min(totals),
            "max": max(totals),
        }

    return {
        "simulations": simulations,
        "worker_final_stats": worker_final_stats,
        "team_final_stats": team_final_stats,
        "runs": runs,
        "case_count": case_count,
    }


def simulate_realistic_ensemble(
    runs: int,
    balancer_settings: Mapping[str, object],
    *,
    seed: int = 12345,
    total_day_minutes: int = 750,
    start_buffer_minutes: int = 15,
    end_buffer_minutes: int = 20,
) -> dict:
    simulations = []
    for run_idx in range(runs):
        cases = build_realistic_day_cases(seed=seed + run_idx)
        workers = build_realistic_workers()
        sim = simulate_realistic_day(
            cases,
            workers,
            balancer_settings,
            total_day_minutes=total_day_minutes,
            start_buffer_minutes=start_buffer_minutes,
            end_buffer_minutes=end_buffer_minutes,
        )
        sim["run_idx"] = run_idx
        simulations.append(sim)

    worker_names = [worker.name for worker in build_realistic_workers()]
    group_names = sorted({worker.group for worker in build_realistic_workers()})
    worker_final_stats = {}
    worker_case_curves = {worker: [] for worker in worker_names}
    for sim in simulations:
        for worker in worker_names:
            worker_case_curves[worker].append(sim["worker_series"][worker])
    for worker in worker_names:
        final_values = [curve[-1] for curve in worker_case_curves[worker]]
        worker_final_stats[worker] = {
            "mean": sum(final_values) / len(final_values),
            "min": min(final_values),
            "max": max(final_values),
        }

    team_final_stats = {}
    for group in group_names:
        totals = [sim["team_totals"][group] for sim in simulations]
        team_final_stats[group] = {
            "mean": sum(totals) / len(totals),
            "min": min(totals),
            "max": max(totals),
        }

    return {
        "simulations": simulations,
        "worker_final_stats": worker_final_stats,
        "team_final_stats": team_final_stats,
        "runs": runs,
        "case_count": len(simulations[0]["rows"]) if simulations else 0,
    }


def write_case_log(rows: Sequence[Mapping[str, object]], output_dir: Path) -> Path:
    path = output_dir / "case_log.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    return path


def write_team_summary(simulation: Mapping[str, object], output_dir: Path) -> Path:
    path = output_dir / "team_origin_summary.csv"
    origin_summary = simulation["origin_summary"]
    team_totals = simulation["team_totals"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "team",
                "origin_total",
                "handled_by_own_team",
                "handled_by_other_team",
                "own_share_pct",
                "help_share_pct",
                "total_handled_by_team",
            ]
        )
        for team in origin_summary:
            row = origin_summary[team]
            writer.writerow(
                [
                    team,
                    row["origin_total"],
                    row["handled_by_own_team"],
                    row["handled_by_other_team"],
                    row["own_share_pct"],
                    row["help_share_pct"],
                    team_totals[team],
                ]
            )
    return path


def write_worker_summary(simulation: Mapping[str, object], output_dir: Path) -> Path:
    path = output_dir / "worker_summary.csv"
    loads = simulation["loads"]
    workers = simulation.get("workers", [])
    rows = []
    for worker in workers:
        shift_type = "late" if int(worker["shift_end_minute"]) > 495 else "specialist"
        rows.append(
            {
                "worker": worker["name"],
                "group": worker["group"],
                "shift_type": shift_type,
                "shift_start": _minute_to_clock_label(int(worker["shift_start_minute"])),
                "shift_end": _minute_to_clock_label(int(worker["shift_end_minute"])),
                "final_load": loads.get(worker["name"], 0),
            }
        )
    rows.sort(key=lambda row: (row["group"], row["worker"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["worker", "group", "shift_type", "shift_start", "shift_end", "final_load"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_ensemble_summary(ensemble: Mapping[str, object], output_dir: Path) -> Path:
    path = output_dir / "ensemble_summary.csv"
    worker_stats = ensemble["worker_final_stats"]
    team_stats = ensemble["team_final_stats"]
    runs = ensemble["runs"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["entity", "mean_final", "min_final", "max_final", "runs"])
        for worker, stats in worker_stats.items():
            writer.writerow([worker, round(stats["mean"], 2), stats["min"], stats["max"], runs])
        for team, stats in team_stats.items():
            writer.writerow([f"Team {team}", round(stats["mean"], 2), stats["min"], stats["max"], runs])
    return path


def write_summary_json(
    simulation: Mapping[str, object],
    output_dir: Path,
    *,
    ensemble: Optional[Mapping[str, object]] = None,
) -> Path:
    path = output_dir / "summary.json"
    payload = {
        "settings": simulation["settings"],
        "origin_matrix": simulation["origin_matrix"],
        "origin_summary": simulation["origin_summary"],
        "team_totals": simulation["team_totals"],
        "final_loads": simulation["loads"],
        "rows": simulation["rows"],
    }
    if ensemble:
        payload["ensemble"] = {
            "runs": ensemble.get("runs"),
            "worker_final_stats": ensemble.get("worker_final_stats"),
            "team_final_stats": ensemble.get("team_final_stats"),
        }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def render_plot(
    simulation: Mapping[str, object],
    output_dir: Path,
    *,
    ensemble: Optional[Mapping[str, object]] = None,
) -> Tuple[Path, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    plt.rcParams.update(
        {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#ffffff",
            "savefig.facecolor": "#ffffff",
            "text.color": "#1f1f1f",
            "axes.labelcolor": "#1f1f1f",
            "xtick.color": "#2a2a2a",
            "ytick.color": "#2a2a2a",
            "axes.edgecolor": "#cfd6e1",
            "font.size": 13,
            "axes.titlesize": 22,
            "axes.titleweight": "bold",
            "legend.fontsize": 11,
        }
    )

    worker_series = simulation["worker_series"]
    origin_summary = simulation["origin_summary"]
    final_loads = simulation["loads"]
    settings = simulation["settings"]
    rows = simulation["rows"]
    scenario_label = str(simulation.get("scenario_label") or "")
    has_phases = bool(rows) and any(row.get("phase") for row in rows)
    worker_meta = {worker["name"]: worker for worker in simulation.get("workers", [])}

    worker_order = sorted(worker_series.keys())
    scenario_colors = {
        "A1": "#2f5d8a",
        "A2": "#6fa2d4",
        "B1": "#c47a2c",
        "B2": "#e7a85e",
    }
    realistic_colors = {
        "AOU": "#2f5d8a",
        "CVT": "#2e8b57",
        "MDH": "#c47a2c",
        "GYN": "#8a3ab9",
        "NOTFALL": "#b32d2e",
    }

    def worker_color(worker_name: str) -> str:
        meta = worker_meta.get(worker_name, {})
        group = str(meta.get("group", ""))
        if worker_name in scenario_colors:
            return scenario_colors[worker_name]
        for prefix, color in realistic_colors.items():
            if group == prefix:
                return color
        return "#444444"

    def worker_style(worker_name: str) -> str:
        if worker_name.startswith("Late"):
            return {1: "-", 2: "--", 3: ":"}.get(int(worker_name[-1]) if worker_name[-1].isdigit() else 0, "-")
        if worker_name.endswith("1"):
            return "-"
        if worker_name.endswith("2"):
            return "--"
        return "-"

    fig = plt.figure(figsize=(16, 9), dpi=220)
    gs = GridSpec(2, 1, height_ratios=[3.55, 1.1], hspace=0.42, figure=fig)
    ax = fig.add_subplot(gs[0])
    table_ax = fig.add_subplot(gs[1])
    table_ax.axis("off")

    x_values = list(range(1, len(rows) + 1))
    if ensemble and ensemble.get("simulations"):
        simulations = ensemble["simulations"]
        for worker_name in worker_order:
            color = worker_color(worker_name)
            # Faint individual runs.
            for sim in simulations:
                ax.plot(
                    x_values,
                    sim["worker_series"][worker_name],
                    color=color,
                    linewidth=0.9,
                    alpha=0.07,
                    zorder=1,
                )
            # Median line across runs.
            series_matrix = [sim["worker_series"][worker_name] for sim in simulations]
            med = []
            low = []
            high = []
            for idx in range(len(x_values)):
                values = sorted(series[idx] for series in series_matrix)
                med.append(values[len(values) // 2])
                low.append(values[max(0, int(len(values) * 0.1) - 1)])
                high.append(values[min(len(values) - 1, int(len(values) * 0.9))])
            ax.fill_between(
                x_values,
                low,
                high,
                color=color,
                alpha=0.18,
                linewidth=0,
                zorder=2,
            )
            ax.plot(
                x_values,
                med,
                label=f"{worker_name} median",
                color=color,
                linestyle=worker_style(worker_name),
                linewidth=3.0,
                marker="o",
                markersize=4.0,
                alpha=0.95,
                zorder=3,
            )
    else:
        for worker_name in worker_order:
            ax.plot(
                x_values,
                worker_series[worker_name],
                label=worker_name,
                color=worker_color(worker_name),
                linestyle=worker_style(worker_name),
                linewidth=2.2,
                marker="o",
                markersize=3,
                alpha=0.95,
            )

    if has_phases:
        phase_counts: Dict[str, int] = {}
        phase_order: List[str] = []
        for row in rows:
            phase = str(row.get("phase") or "")
            if not phase:
                continue
            if phase not in phase_counts:
                phase_order.append(phase)
                phase_counts[phase] = 0
            phase_counts[phase] += 1

        phase_colors = {
            "early": "#edf2f7",
            "core": "#f7fafc",
            "late": "#eef6ff",
            "after_hours": "#fef7ec",
        }
        phase_spans: List[Tuple[str, int, int]] = []
        start = 1
        for phase in phase_order:
            count = phase_counts[phase]
            end = start + count - 1
            phase_spans.append((phase, start, end))
            ax.axvspan(start - 0.5, end + 0.5, color=phase_colors.get(phase, "#f5f7fa"), alpha=0.28, zorder=0)
            if end > start:
                ax.axvline(end + 0.5, color="#cfd6e1", linestyle=":", linewidth=1.0, zorder=0.5)
            start = end + 1
    else:
        phase_spans = []

    if has_phases:
        title = "RadIMO Cortex - realistic worker load spread"
        subtitle_settings = dict(settings)
        subtitle_settings["case_count"] = len(rows)
        subtitle = (
            "{runs} random runs | {case_count} cases | CT/MR mixed | "
            "min_assignments_per_skill={min_assignments_per_skill} | "
            "warm_start_release_mode={warm_start_release_mode} | "
            "imbalance_threshold_pct={imbalance_threshold_pct}% | "
            "start_buffer={start_buffer_minutes}m | end_buffer={end_buffer_minutes}m"
        ).format(
            runs=(ensemble["runs"] if ensemble else 1),
            **subtitle_settings,
        )
    else:
        title = "RadIMO Cortex - ensemble load spread per worker"
        subtitle = (
            "{runs} random case orders | min_assignments_per_skill={min_assignments_per_skill} | "
            "warm_start_release_mode={warm_start_release_mode} | "
            "imbalance_threshold_pct={imbalance_threshold_pct}% | "
            "start_buffer={start_buffer_minutes}m | end_buffer={end_buffer_minutes}m"
        ).format(
            runs=(ensemble["runs"] if ensemble else 1),
            **settings,
        )
    if scenario_label:
        subtitle = f"{scenario_label} | {subtitle}"
    ax.set_title(title, fontsize=22, pad=36, color="#1f1f1f")
    ax.text(0.5, 1.012, subtitle, transform=ax.transAxes, ha="center", va="bottom", fontsize=10.5, color="#555555")
    ax.set_xlabel("Falllauf / case order")
    ax.set_ylabel("Kumulative Last")
    ax.grid(True, axis="y", alpha=0.22, color="#b8c2d1")
    ax.set_xlim(1, len(rows))
    ax.set_ylim(0, max(max(series) for series in worker_series.values()) + (3.5 if has_phases else 2.5))
    ax.legend(loc="upper left", ncol=4, frameon=False, labelcolor="#1f1f1f", bbox_to_anchor=(0.0, 1.02))

    if ensemble and ensemble.get("worker_final_stats"):
        worker_stats = ensemble["worker_final_stats"]
        final_load_text = (
            "Final worker loads (mean range over runs): "
            + ", ".join(
                f"{worker} {worker_stats[worker]['mean']:.1f} [{worker_stats[worker]['min']}-{worker_stats[worker]['max']}]"
                for worker in worker_order
            )
        )
    else:
        final_load_text = (
            "Final worker loads: "
            + ", ".join(f"{worker} {final_loads[worker]}" for worker in worker_order)
        )
    if has_phases:
        worker_rows = []
        worker_lookup = {worker["name"]: worker for worker in simulation.get("workers", [])}
        for worker_name in worker_order:
            worker_meta = worker_lookup.get(worker_name, {})
            shift_end = int(worker_meta.get("shift_end_minute", 0))
            shift_type = "late" if shift_end > 495 else "specialist"
            worker_rows.append(
                [
                    worker_name,
                    str(worker_meta.get("group", "")),
                    shift_type,
                    f"{_minute_to_clock_label(int(worker_meta.get('shift_start_minute', 0)))}-{_minute_to_clock_label(int(worker_meta.get('shift_end_minute', 0)))}",
                    f"{final_loads[worker_name]:.2f}",
                ]
            )
        matrix_text = [["User", "Group", "Shift type", "Shift", "Final load"]] + worker_rows
        table_title = "By user / shift window"
        table_fontsize = 10.8
        table_scale = 1.0
        col_labels = matrix_text[0]
        cell_rows = matrix_text[1:]
    else:
        matrix_text = [["Origin group", "Handled by own group", "Handled by other groups", "Origin total", "Own share"]]
        for group in origin_summary:
            row = origin_summary[group]
            matrix_text.append(
                [
                    f"{group}",
                    str(row["handled_by_own_group"]),
                    str(row["handled_by_other_groups"]),
                    str(row["origin_total"]),
                    f"{row['own_share_pct']}%",
                ]
            )
        table_title = "Herkunft vs. tatsächliche Bearbeitung"
        table_fontsize = 12
        table_scale = 1.22
        col_labels = matrix_text[0]
        cell_rows = matrix_text[1:]
    table = table_ax.table(
        cellText=cell_rows,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(table_fontsize)
    table.scale(1, table_scale)
    table_ax.set_title(table_title, fontsize=13, pad=6, color="#1f1f1f")
    for _, cell in table.get_celld().items():
        cell.set_edgecolor("#cfd6e1")
        if cell.get_text() is not None:
            cell.get_text().set_color("#1f1f1f")
    for c in range(len(col_labels)):
        table[(0, c)].set_facecolor("#edf2f7")
        table[(0, c)].get_text().set_fontweight("bold")
    for r in range(1, len(matrix_text)):
        base = "#f8fafc" if r % 2 else "#ffffff"
        for c in range(len(col_labels)):
            table[(r, c)].set_facecolor(base)

    fig.text(
        0.5,
        0.006,
        final_load_text,
        ha="center",
        va="bottom",
        fontsize=14,
        fontweight="bold",
        color="#1f1f1f",
    )

    png_path = output_dir / "worker_load_lines.png"
    pdf_path = output_dir / "worker_load_lines.pdf"
    fig.savefig(png_path, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)
    return png_path, pdf_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cases", type=int, default=60)
    parser.add_argument("--origin-a", type=int, default=40)
    parser.add_argument("--origin-b", type=int, default=20)
    parser.add_argument("--first-a", type=int, default=6)
    parser.add_argument("--total-day-minutes", type=int, default=540)
    parser.add_argument("--start-buffer-minutes", type=int, default=15)
    parser.add_argument("--end-buffer-minutes", type=int, default=20)
    parser.add_argument("--random-runs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument(
        "--scenario",
        choices=["ensemble", "worst_case", "realistic_day", "imbalance_test"],
        default="ensemble",
        help="Choose the origin order to plot.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.scenario == "realistic_day" and args.output_dir == DEFAULT_OUTPUT_DIR:
        args.output_dir = DEFAULT_REALISTIC_OUTPUT_DIR
    if args.scenario == "imbalance_test" and args.output_dir == DEFAULT_OUTPUT_DIR:
        args.output_dir = DEFAULT_IMBALANCE_OUTPUT_DIR
    args.output_dir.mkdir(parents=True, exist_ok=True)

    config = load_yaml_config()
    balancer_settings = get_balancer_settings(config)

    workers_by_team = {
        "A": [Worker("A1", "A"), Worker("A2", "A")],
        "B": [Worker("B1", "B"), Worker("B2", "B")],
    }

    origin_totals = {"A": args.origin_a, "B": args.origin_b}
    if args.scenario == "realistic_day":
        if args.random_runs and args.random_runs > 1:
            ensemble = simulate_realistic_ensemble(
                args.random_runs,
                balancer_settings,
                seed=args.seed,
                total_day_minutes=args.total_day_minutes,
                start_buffer_minutes=args.start_buffer_minutes,
                end_buffer_minutes=args.end_buffer_minutes,
            )
            simulation = ensemble["simulations"][0]
            simulation["scenario_label"] = f"realistic_day_{ensemble['runs']}_runs"
            png_path, pdf_path = render_plot(simulation, args.output_dir, ensemble=ensemble)
            case_csv = write_case_log(simulation["rows"], args.output_dir)
            summary_csv = write_team_summary(simulation, args.output_dir)
            worker_csv = write_worker_summary(simulation, args.output_dir)
            summary_json = write_summary_json(simulation, args.output_dir, ensemble=ensemble)
            ensemble_csv = write_ensemble_summary(ensemble, args.output_dir)
            payload = {
                "png": str(png_path),
                "pdf": str(pdf_path),
                "case_log": str(case_csv),
                "team_summary": str(summary_csv),
                "worker_summary": str(worker_csv),
                "ensemble_summary": str(ensemble_csv),
                "summary_json": str(summary_json),
                "runs": ensemble["runs"],
                "representative_final_loads": simulation["loads"],
                "representative_origin_summary": simulation["origin_summary"],
                "representative_team_totals": simulation["team_totals"],
                "worker_final_stats": ensemble["worker_final_stats"],
                "team_final_stats": ensemble["team_final_stats"],
            }
        else:
            cases = build_realistic_day_cases(seed=args.seed)
            workers = build_realistic_workers()
            simulation = simulate_realistic_day(
                cases,
                workers,
                balancer_settings,
                total_day_minutes=args.total_day_minutes,
                start_buffer_minutes=args.start_buffer_minutes,
                end_buffer_minutes=args.end_buffer_minutes,
            )
            simulation["scenario_label"] = "realistic_day"
            png_path, pdf_path = render_plot(simulation, args.output_dir)
            case_csv = write_case_log(simulation["rows"], args.output_dir)
            summary_csv = write_team_summary(simulation, args.output_dir)
            worker_csv = write_worker_summary(simulation, args.output_dir)
            summary_json = write_summary_json(simulation, args.output_dir)
            payload = {
                "png": str(png_path),
                "pdf": str(pdf_path),
                "case_log": str(case_csv),
                "team_summary": str(summary_csv),
                "worker_summary": str(worker_csv),
                "summary_json": str(summary_json),
                "scenario": args.scenario,
                "final_loads": simulation["loads"],
                "origin_summary": simulation["origin_summary"],
                "team_totals": simulation["team_totals"],
            }
    elif args.scenario == "imbalance_test":
        cases = build_imbalance_test_cases(seed=args.seed)
        workers = build_imbalance_test_workers()
        simulation = simulate_realistic_day(
            cases,
            workers,
            balancer_settings,
            total_day_minutes=args.total_day_minutes,
            start_buffer_minutes=args.start_buffer_minutes,
            end_buffer_minutes=args.end_buffer_minutes,
        )
        simulation["scenario_label"] = "imbalance_test"
        png_path, pdf_path = render_plot(simulation, args.output_dir)
        case_csv = write_case_log(simulation["rows"], args.output_dir)
        summary_csv = write_team_summary(simulation, args.output_dir)
        worker_csv = write_worker_summary(simulation, args.output_dir)
        summary_json = write_summary_json(simulation, args.output_dir)
        payload = {
            "png": str(png_path),
            "pdf": str(pdf_path),
            "case_log": str(case_csv),
            "team_summary": str(summary_csv),
            "worker_summary": str(worker_csv),
            "summary_json": str(summary_json),
            "scenario": args.scenario,
            "final_loads": simulation["loads"],
            "origin_summary": simulation["origin_summary"],
            "team_totals": simulation["team_totals"],
        }
    elif args.scenario == "worst_case":
        origin_sequence = build_worst_case_origin_sequence(args.cases, origin_totals, first_team="B")
        simulation = simulate_distribution(
            origin_sequence,
            workers_by_team,
            balancer_settings,
            total_day_minutes=args.total_day_minutes,
            start_buffer_minutes=args.start_buffer_minutes,
            end_buffer_minutes=args.end_buffer_minutes,
        )
        simulation["scenario_label"] = "worst_case_b_then_a"
        png_path, pdf_path = render_plot(simulation, args.output_dir)
        case_csv = write_case_log(simulation["rows"], args.output_dir)
        summary_csv = write_team_summary(simulation, args.output_dir)
        summary_json = write_summary_json(simulation, args.output_dir)
        payload = {
            "png": str(png_path),
            "pdf": str(pdf_path),
            "case_log": str(case_csv),
            "team_summary": str(summary_csv),
            "summary_json": str(summary_json),
            "scenario": args.scenario,
            "final_loads": simulation["loads"],
            "origin_summary": simulation["origin_summary"],
            "team_totals": simulation["team_totals"],
        }
    elif args.random_runs and args.random_runs > 1:
        ensemble = simulate_ensemble(
            args.random_runs,
            args.cases,
            origin_totals,
            workers_by_team,
            balancer_settings,
            total_day_minutes=args.total_day_minutes,
            start_buffer_minutes=args.start_buffer_minutes,
            end_buffer_minutes=args.end_buffer_minutes,
            seed=args.seed,
            randomize=True,
        )
        simulation = ensemble["simulations"][0]
        simulation["scenario_label"] = f"ensemble_{ensemble['runs']}_runs"
        png_path, pdf_path = render_plot(simulation, args.output_dir, ensemble=ensemble)
        case_csv = write_case_log(simulation["rows"], args.output_dir)
        summary_csv = write_team_summary(simulation, args.output_dir)
        summary_json = write_summary_json(simulation, args.output_dir, ensemble=ensemble)
        ensemble_csv = write_ensemble_summary(ensemble, args.output_dir)
        payload = {
            "png": str(png_path),
            "pdf": str(pdf_path),
            "case_log": str(case_csv),
            "team_summary": str(summary_csv),
            "ensemble_summary": str(ensemble_csv),
            "summary_json": str(summary_json),
            "runs": ensemble["runs"],
            "representative_final_loads": simulation["loads"],
            "representative_origin_summary": simulation["origin_summary"],
            "representative_team_totals": simulation["team_totals"],
            "worker_final_stats": ensemble["worker_final_stats"],
            "team_final_stats": ensemble["team_final_stats"],
        }
    else:
        origin_sequence = build_origin_sequence(
            args.cases,
            origin_totals,
            first_team="A",
            first_run=args.first_a,
        )
        simulation = simulate_distribution(
            origin_sequence,
            workers_by_team,
            balancer_settings,
            total_day_minutes=args.total_day_minutes,
            start_buffer_minutes=args.start_buffer_minutes,
            end_buffer_minutes=args.end_buffer_minutes,
        )
        simulation["scenario_label"] = "deterministic_balanced"
        png_path, pdf_path = render_plot(simulation, args.output_dir)
        case_csv = write_case_log(simulation["rows"], args.output_dir)
        summary_csv = write_team_summary(simulation, args.output_dir)
        summary_json = write_summary_json(simulation, args.output_dir)
        payload = {
            "png": str(png_path),
            "pdf": str(pdf_path),
            "case_log": str(case_csv),
            "team_summary": str(summary_csv),
            "summary_json": str(summary_json),
            "final_loads": simulation["loads"],
            "origin_summary": simulation["origin_summary"],
            "team_totals": simulation["team_totals"],
        }

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
