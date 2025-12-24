# Standard library imports
from datetime import datetime, timedelta
from typing import Optional, Any, Tuple

# Third-party imports
import pandas as pd

# Local imports
from config import (
    BALANCER_SETTINGS,
    SKILL_COLUMNS,
    EXCLUDE_SKILLS,
    ROLE_MAP,
    default_modality,
    selection_logger,
    get_skill_modality_weight,
    coerce_float
)
from lib.utils import (
    get_local_berlin_now,
    compute_shift_window,
    is_now_in_shift,
    skill_value_to_numeric,
    is_weighted_skill,
    WEIGHTED_SKILL_MARKER
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

def update_global_assignment(person: str, role: str, modality: str, is_weighted: bool = False) -> str:
    """
    Record a worker assignment and update global weighted counts.

    Args:
        person: Worker name (PPL field)
        role: Skill/role assigned (e.g., 'Notfall', 'MSK')
        modality: Modality assigned (e.g., 'ct', 'mr')
        is_weighted: If True (skill='w'), apply worker's personal modifier.
                     If False (skill=1 or 0), use modifier=1.0 (no adjustment).

    Returns:
        Canonical worker ID
    """
    canonical_id = get_canonical_worker_id(person)

    # Only apply personal modifier for weighted ('w') assignments
    # skill=1 (regular specialist) and skill=0 (generalist) use modifier=1.0
    if is_weighted:
        modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
        modifier = coerce_float(modifier, 1.0)
        modifier = modifier if modifier > 0 else 1.0
    else:
        modifier = 1.0

    weight = get_skill_modality_weight(role, modality) * (1.0 / modifier)

    # Update single global weighted count (consolidated across all modalities)
    global_worker_data['weighted_counts'][canonical_id] = \
        global_worker_data['weighted_counts'].get(canonical_id, 0.0) + weight

    assignments = _get_or_create_assignments(modality, canonical_id)
    # Only increment if role is a valid skill column (prevents KeyError)
    if role in SKILL_COLUMNS:
        assignments[role] = assignments.get(role, 0) + 1
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
    """Return only rows active at ``current_dt`` (supports overnight shifts).

    Note: Skill values are NOT converted to numeric here to preserve 'w' marker.
    Use skill_value_to_numeric() for comparisons, is_weighted_skill() to check for 'w'.
    """
    if df is None or df.empty:
        return df

    active_mask = df.apply(
        lambda row: is_now_in_shift(row['start_time'], row['end_time'], current_dt),
        axis=1
    )
    active_df = df[active_mask].copy()
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

def _filter_near_shift_start(df: pd.DataFrame, current_dt: datetime, buffer_minutes: int) -> pd.DataFrame:
    """
    Filter out workers who are within buffer_minutes of their shift start.
    Used to prevent overflow assignments at beginning of shift.
    """
    if df is None or df.empty or buffer_minutes <= 0:
        return df

    def is_not_near_shift_start(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        minutes_since_start = (current_dt - start_dt).total_seconds() / 60
        return minutes_since_start > buffer_minutes

    mask = df.apply(is_not_near_shift_start, axis=1)
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

        ratio = weighted_assignments / hours_worked
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
    """
    Specialist-first assignment with pooled worker overflow.

    Strategy:
    1. Filter workers in requested modality by skill>=0 (excludes skill=-1)
    2. Apply exclusion rules (e.g., notfall_ct team won't get mammo_gyn)
    3. Split into specialists (skill=1/'w') and generalists (skill=0)
    4. Try specialists first, overflow to generalists only if all specialists overloaded
    5. Fallback: if exclusions filter out everyone, retry without exclusions
    """
    role_lower = role.lower()
    if role_lower not in ROLE_MAP:
        role_lower = 'normal'
    primary_skill = ROLE_MAP[role_lower]

    # Get exclusion list and overflow settings
    exclude_skills = EXCLUDE_SKILLS.get(primary_skill, [])
    imbalance_threshold_pct = BALANCER_SETTINGS.get('imbalance_threshold_pct', 30)
    shift_start_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_start_minutes', 0)
    shift_end_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_end_minutes', 0)

    selection_logger.info(
        "Specialist-first routing for skill %s in modality %s: exclude %s=1, imbalance_threshold=%d%%",
        primary_skill,
        modality,
        exclude_skills if exclude_skills else 'none',
        imbalance_threshold_pct,
    )

    # Helper function to try selection with given filters
    def try_selection(apply_exclusions: bool):
        if modality not in modality_data:
            return None

        d = modality_data[modality]
        if d['working_hours_df'] is None:
            return None

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            return None

        if primary_skill not in active_df.columns:
            return None

        # Filter by skill >= 0 (excludes skill=-1), handling 'w' as specialist
        # 'w' is treated as skill=1 for filtering, but preserved for modifier logic
        skill_filtered = active_df[
            active_df[primary_skill].apply(lambda v: skill_value_to_numeric(v) >= 0)
        ]
        if skill_filtered.empty:
            return None

        # Apply shift start/end buffers (per-worker per-shift)
        if shift_start_buffer > 0:
            skill_filtered = _filter_near_shift_start(skill_filtered, current_dt, shift_start_buffer)
        if shift_end_buffer > 0:
            skill_filtered = _filter_near_shift_end(skill_filtered, current_dt, shift_end_buffer)
        if skill_filtered.empty:
            return None

        # Apply exclusion rules if requested
        filtered_workers = skill_filtered
        if apply_exclusions:
            for skill_to_exclude in exclude_skills:
                if skill_to_exclude in filtered_workers.columns:
                    # Exclude workers where skill_to_exclude >= 1 (including 'w')
                    filtered_workers = filtered_workers[
                        filtered_workers[skill_to_exclude].apply(lambda v: skill_value_to_numeric(v) < 1)
                    ]
            if filtered_workers.empty:
                return None

        # Calculate workload ratios
        hours_map = calculate_work_hours_now(current_dt, modality)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            h = hours_map.get(canonical_id, 0)
            w = get_global_weighted_count(canonical_id)
            # Use floor of 0.5 hours to prevent division by very small values
            # and to handle workers with zero hours consistently
            return w / max(h, 0.5)

        # Split into specialists (skill=1 or 'w') and generalists (skill=0)
        # 'w' workers use their personal modifier, skill=1 workers do not
        specialists_df = filtered_workers[
            filtered_workers[primary_skill].apply(lambda v: skill_value_to_numeric(v) == 1)
        ]
        generalists_df = filtered_workers[
            filtered_workers[primary_skill].apply(lambda v: skill_value_to_numeric(v) == 0)
        ]

        # Strategy: Try specialists first, overflow to generalists if needed
        if not specialists_df.empty:
            # Apply minimum balancer to specialists
            balanced_specialists = _apply_minimum_balancer(specialists_df, primary_skill, modality)
            specialists_to_check = balanced_specialists if not balanced_specialists.empty else specialists_df

            specialist_workers = specialists_to_check['PPL'].unique()
            specialist_ratios = {p: weighted_ratio(p) for p in specialist_workers}

            # Check if should overflow to generalists based on imbalance
            overflow_triggered = False
            if not generalists_df.empty and imbalance_threshold_pct > 0:
                # Calculate min ratios for both pools
                min_specialist_ratio = min(specialist_ratios.values())

                generalist_workers = generalists_df['PPL'].unique()
                generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}
                min_generalist_ratio = min(generalist_ratios.values())

                # Check if specialists are imbalanced compared to generalists
                if min_generalist_ratio < min_specialist_ratio and min_specialist_ratio > 0:
                    imbalance_pct = ((min_specialist_ratio - min_generalist_ratio) / min_specialist_ratio) * 100
                    if imbalance_pct >= imbalance_threshold_pct:
                        overflow_triggered = True
                        selection_logger.info(
                            "Specialist overflow triggered: specialist_min=%.4f, generalist_min=%.4f, imbalance=%.1f%% >= %d%%",
                            min_specialist_ratio,
                            min_generalist_ratio,
                            imbalance_pct,
                            imbalance_threshold_pct,
                        )

            # If overflow not triggered, use specialist with lowest ratio
            if not overflow_triggered:
                best_specialist = min(specialist_workers, key=lambda p: specialist_ratios[p])
                candidate = specialists_to_check[specialists_to_check['PPL'] == best_specialist].iloc[0].copy()
                candidate['__modality_source'] = modality
                candidate['__selection_ratio'] = specialist_ratios[best_specialist]
                # Track if this is a weighted ('w') assignment - affects modifier usage
                candidate['__is_weighted'] = is_weighted_skill(candidate.get(primary_skill))

                selection_logger.info(
                    "Selected specialist: person=%s, skill=%s=%s, weighted=%s, ratio=%.4f",
                    candidate.get('PPL', 'unknown'),
                    primary_skill,
                    candidate.get(primary_skill, '?'),
                    candidate['__is_weighted'],
                    specialist_ratios[best_specialist],
                )

                return candidate, primary_skill, modality

        # Use generalists if: (1) no specialists, OR (2) overflow triggered
        if not generalists_df.empty:
            balanced_generalists = _apply_minimum_balancer(generalists_df, primary_skill, modality)
            generalists_to_check = balanced_generalists if not balanced_generalists.empty else generalists_df

            generalist_workers = generalists_to_check['PPL'].unique()
            generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}

            best_generalist = min(generalist_workers, key=lambda p: generalist_ratios[p])
            candidate = generalists_to_check[generalists_to_check['PPL'] == best_generalist].iloc[0].copy()
            candidate['__modality_source'] = modality
            candidate['__selection_ratio'] = generalist_ratios[best_generalist]
            # Generalists (skill=0) never use weighted modifier
            candidate['__is_weighted'] = False

            selection_logger.info(
                "Selected generalist (pooled): person=%s, skill=%s=0, ratio=%.4f",
                candidate.get('PPL', 'unknown'),
                primary_skill,
                generalist_ratios[best_generalist],
            )

            return candidate, primary_skill, modality

        return None

    # Level 1: Try with exclusions
    result = try_selection(apply_exclusions=True)
    if result:
        return result

    # Level 2: Fallback without exclusions if enabled
    if not allow_fallback:
        selection_logger.info(
            "No workers available with exclusions for skill %s, fallback disabled",
            primary_skill,
        )
        return None

    selection_logger.info(
        "No workers with exclusions, retrying without exclusion filters",
    )

    result = try_selection(apply_exclusions=False)
    if result:
        return result

    selection_logger.info(
        "No workers available for skill %s in modality %s",
        primary_skill,
        modality,
    )
    return None

def get_next_available_worker(
    current_dt: datetime,
    role='normal',
    modality=default_modality,
    allow_fallback: bool = True,
):
    return _get_worker_exclusion_based(current_dt, role, modality, allow_fallback)
