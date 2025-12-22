# Standard library imports
from datetime import datetime, timedelta
from typing import Optional, Any, Tuple

# Third-party imports
import pandas as pd

# Local imports
from config import (
    BALANCER_SETTINGS,
    SKILL_COLUMNS,
    EXCLUSION_RULES,
    ROLE_MAP,
    MODALITY_FALLBACK_CHAIN,
    default_modality,
    selection_logger,
    get_skill_modality_weight,
    coerce_float
)
from utils import (
    get_local_berlin_now,
    compute_shift_window,
    is_now_in_shift,
    skill_value_to_numeric
)
from data_manager import (
    get_canonical_worker_id,
    global_worker_data,
    modality_data,
    save_state
)

# -----------------------------------------------------------
# Helper functions to compute global totals across modalities
# -----------------------------------------------------------
def get_global_weighted_count(canonical_id):
    """Get single global weighted count for a worker (consolidated across all modalities)."""
    return global_worker_data['weighted_counts'].get(canonical_id, 0.0)

def get_global_assignments(canonical_id):
    totals = {skill: 0 for skill in SKILL_COLUMNS}
    totals['total'] = 0
    # We need to access allowed_modalities. Importing directly might cause circular import issues
    # if not careful, but data_manager already imports it from config. 
    # Let's iterate over keys of modality_data which should match allowed_modalities.
    for mod in modality_data.keys():
        mod_assignments = global_worker_data['assignments_per_mod'][mod].get(canonical_id, {})
        for skill in SKILL_COLUMNS:
            totals[skill] += mod_assignments.get(skill, 0)
        totals['total'] += mod_assignments.get('total', 0)
    return totals

def _get_or_create_assignments(modality: str, canonical_id: str) -> dict:
    assignments = global_worker_data['assignments_per_mod'][modality]
    if canonical_id not in assignments:
        assignments[canonical_id] = {skill: 0 for skill in SKILL_COLUMNS}
        assignments[canonical_id]['total'] = 0
    return assignments[canonical_id]

def update_global_assignment(person: str, role: str, modality: str) -> str:
    canonical_id = get_canonical_worker_id(person)
    # Get the modifier (default 1.0). Values < 1 mean less work capacity (counts more toward load)
    modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
    modifier = coerce_float(modifier, 1.0)
    modifier = modifier if modifier > 0 else 1.0
    
    weight = get_skill_modality_weight(role, modality) * (1.0 / modifier)

    # Update single global weighted count (consolidated across all modalities)
    global_worker_data['weighted_counts'][canonical_id] = \
        global_worker_data['weighted_counts'].get(canonical_id, 0.0) + weight

    assignments = _get_or_create_assignments(modality, canonical_id)
    assignments[role] += 1
    assignments['total'] += 1

    # Persist state after every assignment to prevent data loss on restart
    save_state()

    return canonical_id

def calculate_work_hours_now(current_dt: datetime, modality: str) -> dict:
    d = modality_data[modality]
    if d['working_hours_df'] is None:
        return {}
    df_copy = d['working_hours_df'].copy()

    if 'counts_for_hours' in df_copy.columns:
        df_copy = df_copy[df_copy['counts_for_hours'] == True].copy()

    if df_copy.empty:
        return {}

    def _calc(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        if current_dt < start_dt:
            return 0.0
        if current_dt >= end_dt:
            return (end_dt - start_dt).total_seconds() / 3600.0
        return (current_dt - start_dt).total_seconds() / 3600.0

    df_copy['work_hours_now'] = df_copy.apply(_calc, axis=1)

    hours_by_canonical = {}
    hours_by_worker = df_copy.groupby('PPL')['work_hours_now'].sum().to_dict()

    for worker, hours in hours_by_worker.items():
        canonical_id = get_canonical_worker_id(worker)
        hours_by_canonical[canonical_id] = hours_by_canonical.get(canonical_id, 0) + hours

    return hours_by_canonical

def _filter_active_rows(df: Optional[pd.DataFrame], current_dt: datetime) -> Optional[pd.DataFrame]:
    """Return only rows active at ``current_dt`` (supports overnight shifts)."""
    if df is None or df.empty:
        return df

    active_mask = df.apply(
        lambda row: is_now_in_shift(row['start_time'], row['end_time'], current_dt),
        axis=1
    )
    active_df = df[active_mask].copy()
    for skill in SKILL_COLUMNS:
        if skill in active_df.columns:
            active_df[skill] = active_df[skill].apply(skill_value_to_numeric)
    return active_df

def _filter_near_shift_end(df: pd.DataFrame, current_dt: datetime, buffer_minutes: int) -> pd.DataFrame:
    """
    Filter out workers who are within buffer_minutes of their shift end.
    Used to prevent overflow assignments near end of shift.
    """
    if df is None or df.empty or buffer_minutes <= 0:
        return df

    def is_not_near_shift_end(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        minutes_until_end = (end_dt - current_dt).total_seconds() / 60
        return minutes_until_end > buffer_minutes

    mask = df.apply(is_not_near_shift_end, axis=1)
    return df[mask].copy()

def _get_effective_assignment_load(
    worker: str,
    column: str,
    modality: str,
    skill_counts: Optional[dict] = None,
) -> float:
    if skill_counts is None:
        skill_counts = modality_data[modality]['skill_counts'].get(column, {})

    local_count = skill_counts.get(worker, 0)
    canonical_id = get_canonical_worker_id(worker)
    global_weighted_total = get_global_weighted_count(canonical_id)

    return max(float(local_count), float(global_weighted_total))

def _apply_minimum_balancer(filtered_df: pd.DataFrame, column: str, modality: str) -> pd.DataFrame:
    if filtered_df.empty or not BALANCER_SETTINGS.get('enabled', True):
        return filtered_df
    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)
    if min_required <= 0:
        return filtered_df

    skill_counts = modality_data[modality]['skill_counts'].get(column, {})
    if not skill_counts:
        return filtered_df

    working_hours_df = modality_data[modality].get('working_hours_df')
    if working_hours_df is None or column not in working_hours_df.columns:
        return filtered_df

    any_below_minimum = False
    for worker in skill_counts.keys():
        worker_rows = working_hours_df[working_hours_df['PPL'] == worker]
        if worker_rows.empty:
            continue

        skill_value = skill_value_to_numeric(worker_rows[column].iloc[0])
        if skill_value < 1:
            continue

        count = _get_effective_assignment_load(worker, column, modality, skill_counts)
        if count < min_required:
            any_below_minimum = True
            break

    if not any_below_minimum:
        return filtered_df

    prioritized = filtered_df[
        filtered_df['PPL'].apply(
            lambda worker: _get_effective_assignment_load(worker, column, modality, skill_counts)
            < min_required
        )
    ]

    if prioritized.empty:
        return filtered_df
    return prioritized

def _should_balance_via_fallback(filtered_df: pd.DataFrame, column: str, modality: str) -> bool:
    if not isinstance(column, str):
        return False
    if filtered_df.empty or not BALANCER_SETTINGS.get('enabled', True):
        return False
    if not BALANCER_SETTINGS.get('allow_fallback_on_imbalance', True):
        return False

    threshold_pct = float(BALANCER_SETTINGS.get('imbalance_threshold_pct', 0))
    if threshold_pct <= 0:
        return False

    skill_counts = modality_data[modality]['skill_counts'].get(column, {})
    if not skill_counts:
        return False

    current_dt = get_local_berlin_now()
    hours_map = calculate_work_hours_now(current_dt, modality)

    worker_ratios = []
    for worker in filtered_df['PPL'].unique():
        canonical_id = get_canonical_worker_id(worker)
        weighted_assignments = get_global_weighted_count(canonical_id)
        hours_worked = hours_map.get(canonical_id, 0)

        if hours_worked <= 0:
            continue

        if hours_worked > 0:
            ratio = weighted_assignments / hours_worked
        else:
            ratio = weighted_assignments * 2
        worker_ratios.append(ratio)

    if len(worker_ratios) < 2:
        return False

    max_ratio = max(worker_ratios)
    min_ratio = min(worker_ratios)
    if max_ratio == 0:
        return False

    imbalance = (max_ratio - min_ratio) / max_ratio
    return imbalance >= (threshold_pct / 100.0)

def _get_worker_exclusion_based(
    current_dt: datetime,
    role: str,
    modality: str,
    allow_fallback: bool,
):
    role_lower = role.lower()
    if role_lower not in ROLE_MAP:
        role_lower = 'normal'
    primary_skill = ROLE_MAP[role_lower]

    skill_exclusions = EXCLUSION_RULES.get(primary_skill, {})
    exclude_skills = skill_exclusions.get('exclude_skills', [])

    modality_search = [modality] + MODALITY_FALLBACK_CHAIN.get(modality, [])

    flat_modality_search = []
    for entry in modality_search:
        if isinstance(entry, list):
            flat_modality_search.extend(entry)
        else:
            flat_modality_search.append(entry)

    seen_modalities = set()
    unique_modality_search = []
    for mod in flat_modality_search:
        if mod not in seen_modalities and mod in modality_data:
            seen_modalities.add(mod)
            unique_modality_search.append(mod)

    # Get shift-end buffer config (0 = disabled)
    shift_end_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_end_minutes', 0)

    selection_logger.info(
        "Exclusion-based routing for skill %s: filter %s>=0, exclude %s=1, modalities=%s, shift_end_buffer=%d",
        primary_skill,
        primary_skill,
        exclude_skills if exclude_skills else 'none',
        unique_modality_search,
        shift_end_buffer,
    )

    candidate_pool_excluded = []

    for target_modality in unique_modality_search:
        is_overflow = (target_modality != modality)
        d = modality_data[target_modality]
        if d['working_hours_df'] is None:
            continue

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            continue

        # For overflow modalities, filter out workers near shift end
        if is_overflow and shift_end_buffer > 0:
            active_df = _filter_near_shift_end(active_df, current_dt, shift_end_buffer)
            if active_df.empty:
                selection_logger.debug(
                    "Overflow modality %s: all workers filtered out (near shift end)",
                    target_modality
                )
                continue

        if primary_skill not in active_df.columns:
            continue

        skill_filtered = active_df[active_df[primary_skill] >= 0]
        if skill_filtered.empty:
            continue

        filtered_workers = skill_filtered
        for skill_to_exclude in exclude_skills:
            if skill_to_exclude in filtered_workers.columns:
                filtered_workers = filtered_workers[filtered_workers[skill_to_exclude] < 1]

        if filtered_workers.empty:
            continue

        balanced_df = _apply_minimum_balancer(filtered_workers, primary_skill, target_modality)
        result_df = balanced_df if not balanced_df.empty else filtered_workers

        hours_map = calculate_work_hours_now(current_dt, target_modality)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            h = hours_map.get(canonical_id, 0)
            w = get_global_weighted_count(canonical_id)
            return w / max(h, 0.5) if h > 0 else w

        available_workers = result_df['PPL'].unique()
        if len(available_workers) == 0:
            continue

        best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
        candidate = result_df[result_df['PPL'] == best_person].iloc[0].copy()
        candidate['__modality_source'] = target_modality
        candidate['__selection_ratio'] = weighted_ratio(best_person)

        ratio = candidate.get('__selection_ratio', float('inf'))
        candidate_pool_excluded.append((ratio, candidate, primary_skill, target_modality))

    if candidate_pool_excluded:
        ratio, candidate, used_skill, source_modality = min(candidate_pool_excluded, key=lambda item: item[0])

        selection_logger.info(
            "Exclusion routing: Selected from pool of %d candidates (%s>=0, excluded %s=1): person=%s, modality=%s, ratio=%.4f",
            len(candidate_pool_excluded),
            primary_skill,
            exclude_skills if exclude_skills else 'none',
            candidate.get('PPL', 'unknown'),
            source_modality,
            ratio,
        )

        return candidate, used_skill, source_modality

    if not allow_fallback:
        selection_logger.info(
            "No workers available with exclusions for skill %s, and fallback disabled",
            primary_skill,
        )
        return None

    selection_logger.info(
        "No workers available with exclusions for skill %s, falling back to skill-based selection",
        primary_skill,
    )

    candidate_pool_fallback = []

    for target_modality in unique_modality_search:
        is_overflow = (target_modality != modality)
        d = modality_data[target_modality]
        if d['working_hours_df'] is None:
            continue

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            continue

        # For overflow modalities, filter out workers near shift end
        if is_overflow and shift_end_buffer > 0:
            active_df = _filter_near_shift_end(active_df, current_dt, shift_end_buffer)
            if active_df.empty:
                selection_logger.debug(
                    "Fallback overflow modality %s: all workers filtered out (near shift end)",
                    target_modality
                )
                continue

        if primary_skill not in active_df.columns:
            continue

        skill_filtered = active_df[active_df[primary_skill] >= 0]
        if skill_filtered.empty:
            continue

        balanced_df = _apply_minimum_balancer(skill_filtered, primary_skill, target_modality)
        result_df = balanced_df if not balanced_df.empty else skill_filtered

        hours_map = calculate_work_hours_now(current_dt, target_modality)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            h = hours_map.get(canonical_id, 0)
            w = get_global_weighted_count(canonical_id)
            return w / max(h, 0.5) if h > 0 else w

        available_workers = result_df['PPL'].unique()
        if len(available_workers) == 0:
            continue

        best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
        candidate = result_df[result_df['PPL'] == best_person].iloc[0].copy()
        candidate['__modality_source'] = target_modality
        candidate['__selection_ratio'] = weighted_ratio(best_person)

        ratio = candidate.get('__selection_ratio', float('inf'))
        candidate_pool_fallback.append((ratio, candidate, primary_skill, target_modality))

    if candidate_pool_fallback:
        ratio, candidate, used_skill, source_modality = min(candidate_pool_fallback, key=lambda item: item[0])

        selection_logger.info(
            "Fallback routing: Selected from pool of %d candidates (skill %s>=0): person=%s, modality=%s, ratio=%.4f",
            len(candidate_pool_fallback),
            primary_skill,
            candidate.get('PPL', 'unknown'),
            source_modality,
            ratio,
        )

        return candidate, used_skill, source_modality

    selection_logger.info(
        "No workers available for skill %s (tried exclusion-based and skill-based fallback)",
        primary_skill,
    )
    return None

def get_next_available_worker(
    current_dt: datetime,
    role='normal',
    modality=default_modality,
    allow_fallback: bool = True,
):
    return _get_worker_exclusion_based(current_dt, role, modality, allow_fallback)
