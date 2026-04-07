# -*- coding: utf-8 -*-
from __future__ import annotations

# Standard library imports
from datetime import datetime
from typing import Optional

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
    compute_shift_window,
    is_now_in_shift,
    skill_value_to_numeric,
    is_weighted_skill,
    gap_row_mask,
)
from data_manager import (
    get_canonical_worker_id,
    get_roster_modifier_raw,
    global_worker_data,
    modality_data,
)
from state_manager import get_state

# -----------------------------------------------------------
# Helper functions to compute global totals across modalities
# -----------------------------------------------------------
def get_global_weighted_count(canonical_id: str) -> float:
    """Get single global weighted count for a worker (consolidated across all modalities)."""
    return global_worker_data['weighted_counts'].get(canonical_id, 0.0)


def get_modality_weighted_count(canonical_id: str, modality: str) -> float:
    """Compute weighted count for a worker in a specific modality.

    Calculated from assignments_per_mod using skill×modality weights.
    This replaces the broken WeightedCounts structure that was never populated.
    """
    assignments = global_worker_data['assignments_per_mod'].get(modality, {}).get(canonical_id, {})
    if not assignments:
        return 0.0

    total_weight = 0.0
    for skill in SKILL_COLUMNS:
        count = assignments.get(skill, 0)
        if count > 0:
            weight = get_skill_modality_weight(skill, modality)
            total_weight += count * weight
    return total_weight


def get_global_assignments(canonical_id: str) -> dict[str, int]:
    """Get aggregated assignment counts for a worker across all modalities."""
    totals = {skill: 0 for skill in SKILL_COLUMNS}
    totals['total'] = 0
    for mod in modality_data.keys():
        mod_assignments = global_worker_data['assignments_per_mod'][mod].get(canonical_id, {})
        for skill in SKILL_COLUMNS:
            totals[skill] += mod_assignments.get(skill, 0)
        totals['total'] += mod_assignments.get('total', 0)
    return totals

def _get_or_create_assignments(modality: str, canonical_id: str) -> dict:
    """Get or create assignment tracking dict for a worker in a modality.

    Note: modality must be validated before calling this function.
    All modalities are pre-initialized in global_worker_data at module load.
    """
    assignments = global_worker_data['assignments_per_mod'][modality]
    if canonical_id not in assignments:
        assignments[canonical_id] = {skill: 0 for skill in SKILL_COLUMNS}
        assignments[canonical_id]['total'] = 0
    return assignments[canonical_id]

def update_global_assignment(
    person: str,
    role: str,
    modality: str,
    is_weighted: bool = False,
    strict_mode: bool = False,
    work_amount: float = 1.0,
    weight_override: Optional[float] = None,
    shift_modifier_override: Optional[float] = None,
) -> str:
    """
    Record a worker assignment and update global weighted counts.

    IMPORTANT: This function modifies global state and must be called while holding
    the global lock. The caller is responsible for calling save_state() after
    releasing the lock to persist changes (prevents blocking I/O under lock).

    Args:
        person: Worker name (PPL field)
        role: Skill/role assigned (e.g., 'Notfall', 'MSK')
        modality: Modality assigned (e.g., 'ct', 'mr')
        is_weighted: If True (skill='w'), also apply worker's 'w' modifier streams.
                     If False (skill=1 or 0), only shift modifier applies.
        strict_mode: If True, apply strict button weight multiplier.
        work_amount: Optional multiplier for special-task work balance.
        weight_override: Optional fixed weight override for special tasks.
        shift_modifier_override: Optional per-assignment shift modifier from
            the active schedule row (preferred over pooled worker-level cache).

    Returns:
        Canonical worker ID
    """
    canonical_id = get_canonical_worker_id(person)

    # Shift modifier applies to ALL assignments (0, 1, w).
    # Active-row value is preferred; pooled cache is fallback.
    shift_modifier = coerce_float(shift_modifier_override, 1.0)
    if shift_modifier == 1.0:
        pooled_shift_modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
        shift_modifier = coerce_float(pooled_shift_modifier, 1.0)
    shift_modifier = shift_modifier if shift_modifier > 0 else 1.0

    # For weighted ('w') assignments, also apply W streams:
    # roster_w_modifier × default_w_modifier.
    if is_weighted:
        roster_modifier_raw = get_roster_modifier_raw(canonical_id)
        roster_modifier = coerce_float(roster_modifier_raw, 1.0)

        default_w_modifier = BALANCER_SETTINGS.get('default_w_modifier', 1.0)
        default_w_modifier = coerce_float(default_w_modifier, 1.0)

        w_modifier = roster_modifier * default_w_modifier
        w_modifier = w_modifier if w_modifier > 0 else 1.0
    else:
        w_modifier = 1.0

    # Combined modifier: shift applies to all, W stream only for weighted assignments.
    combined_modifier = shift_modifier * w_modifier
    base_weight = (
        weight_override
        if weight_override is not None
        else get_skill_modality_weight(role, modality, strict=strict_mode)
    )
    weight = base_weight * (1.0 / combined_modifier)
    weight *= work_amount

    # Update single global weighted count (consolidated across all modalities)
    global_worker_data['weighted_counts'][canonical_id] = \
        global_worker_data['weighted_counts'].get(canonical_id, 0.0) + weight

    assignments = _get_or_create_assignments(modality, canonical_id)
    if role not in assignments:
        selection_logger.warning(
            "Unknown role '%s' for modality '%s' when updating assignments; initializing counter.",
            role,
            modality,
        )
        assignments[role] = 0
    assignments[role] += 1
    assignments['total'] += 1

    # NOTE: save_state() is NOT called here to avoid blocking I/O under lock.
    # The caller must call save_state() after releasing the lock.

    return canonical_id

def calculate_work_hours_now(current_dt: datetime, modality: str) -> dict[str, float]:
    """
    Calculate cumulative work hours for all workers up to current_dt.

    Uses TTL cache (~1 minute) to avoid recalculating on every assignment.
    Cache key is based on modality and minute-truncated timestamp.
    """
    # Round to minute for cache key (cache valid for same minute)
    cache_minute = current_dt.replace(second=0, microsecond=0)
    cache_key = f"work_hours:{modality}:{cache_minute.isoformat()}"

    state = get_state()
    cached = state.work_hours_cache.get(cache_key)
    if cached is not None:
        return cached

    d = modality_data[modality]
    if d['working_hours_df'] is None:
        return {}

    df = d['working_hours_df']

    # Filter without copy - use boolean indexing on original
    gap_mask = gap_row_mask(df)

    if 'counts_for_hours' in df.columns:
        hours_mask = df['counts_for_hours'].fillna(True).astype(bool)
        df_filtered = df.loc[hours_mask & ~gap_mask]
    else:
        df_filtered = df.loc[~gap_mask]

    if df_filtered.empty:
        return {}

    def _calc(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        if current_dt < start_dt:
            return 0.0
        if current_dt >= end_dt:
            return (end_dt - start_dt).total_seconds() / 3600.0
        return (current_dt - start_dt).total_seconds() / 3600.0

    # Calculate hours directly - avoid adding column to original DataFrame
    work_hours = df_filtered.apply(_calc, axis=1)

    hours_by_canonical = {}
    all_workers = df_filtered['PPL'].dropna().unique().tolist()
    for worker in all_workers:
        canonical_id = get_canonical_worker_id(worker)
        hours_by_canonical[canonical_id] = 0.0

    # Aggregate by PPL using calculated series
    for idx, hours in work_hours.items():
        worker = df_filtered.loc[idx, 'PPL']
        if pd.notna(worker):
            canonical_id = get_canonical_worker_id(worker)
            hours_by_canonical[canonical_id] = hours_by_canonical.get(canonical_id, 0) + hours

    # Cache the result
    state.work_hours_cache.set(cache_key, hours_by_canonical)

    return hours_by_canonical


def calculate_global_work_hours_now(current_dt: datetime) -> dict[str, float]:
    """
    Calculate cumulative work hours for all workers across ALL modalities up to current_dt.

    This aggregates hours from all modalities to provide a consistent basis for
    comparing against global weighted counts. Uses caching via calculate_work_hours_now.

    Returns dict: {canonical_id: total_hours_across_all_modalities}
    """
    global_hours = {}

    for mod in modality_data.keys():
        mod_hours = calculate_work_hours_now(current_dt, mod)
        for canonical_id, hours in mod_hours.items():
            global_hours[canonical_id] = global_hours.get(canonical_id, 0.0) + hours

    return global_hours


def _filter_active_rows(df: Optional[pd.DataFrame], current_dt: datetime) -> Optional[pd.DataFrame]:
    """Return only rows active at ``current_dt`` (same-day shifts only).

    Note: Skill values are NOT converted to numeric here to preserve 'w' marker.
    Use skill_value_to_numeric() for comparisons, is_weighted_skill() to check for 'w'.

    Returns a view (not a copy) for performance. Do not modify the returned DataFrame.
    """
    if df is None or df.empty:
        return df

    gap_mask = gap_row_mask(df)

    active_mask = df.apply(
        lambda row: is_now_in_shift(row['start_time'], row['end_time'], current_dt),
        axis=1
    )
    # Return view without copy - callers only read from this
    return df.loc[active_mask & ~gap_mask]

def _filter_near_shift_end(df: pd.DataFrame, current_dt: datetime, buffer_minutes: int) -> pd.DataFrame:
    """
    Filter out workers who are within buffer_minutes of their shift end.
    Used to prevent overflow assignments near end of shift.

    Returns a view (not a copy) for performance. Do not modify the returned DataFrame.
    """
    if df is None or df.empty or buffer_minutes <= 0:
        return df

    def is_not_near_shift_end(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        minutes_until_end = (end_dt - current_dt).total_seconds() / 60
        return minutes_until_end > buffer_minutes

    mask = df.apply(is_not_near_shift_end, axis=1)
    return df.loc[mask]

def _filter_near_shift_start(df: pd.DataFrame, current_dt: datetime, buffer_minutes: int) -> pd.DataFrame:
    """
    Filter out workers who are within buffer_minutes of their shift start.
    Used to prevent overflow assignments at beginning of shift.

    Returns a view (not a copy) for performance. Do not modify the returned DataFrame.
    """
    if df is None or df.empty or buffer_minutes <= 0:
        return df

    def is_not_near_shift_start(row):
        start_dt, end_dt = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        minutes_since_start = (current_dt - start_dt).total_seconds() / 60
        return minutes_since_start > buffer_minutes

    mask = df.apply(is_not_near_shift_start, axis=1)
    return df.loc[mask]

def _get_effective_assignment_load(
    worker: str,
    column: str,
    modality: str,
) -> float:
    """
    Get effective assignment load for minimum balancer.

    Uses weighted counts consistently to avoid comparing different units.
    Returns max of modality-specific weighted count and global weighted count.
    """
    canonical_id = get_canonical_worker_id(worker)

    # Use weighted counts consistently (both are in weighted units)
    modality_weighted = get_modality_weighted_count(canonical_id, modality)
    global_weighted = get_global_weighted_count(canonical_id)

    return max(modality_weighted, global_weighted)

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

        count = _get_effective_assignment_load(worker, column, modality)
        if count < min_required:
            any_below_minimum = True
            break

    if not any_below_minimum:
        return filtered_df

    prioritized = filtered_df[
        filtered_df['PPL'].apply(
            lambda worker: _get_effective_assignment_load(worker, column, modality)
            < min_required
        )
    ]

    if prioritized.empty:
        return filtered_df
    return prioritized


def _specialist_minimum_ready(specialists_df: pd.DataFrame, column: str, modality: str) -> bool:
    """
    Check whether all active specialists reached the minimum assignment threshold.

    Returns True when:
    - no specialists are active, or
    - min_assignments_per_skill <= 0, or
    - every active specialist has effective load >= min_assignments_per_skill.
    """
    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)
    if min_required <= 0 or specialists_df is None or specialists_df.empty:
        return True

    for worker in specialists_df['PPL'].dropna().unique():
        if _get_effective_assignment_load(worker, column, modality) < min_required:
            return False
    return True


def _specialist_start_window_ready(specialists_df: pd.DataFrame, current_dt: datetime) -> bool:
    """
    Check whether all active specialists are past the configured start buffer.

    Uses disable_overflow_at_shift_start_minutes as the time gate input.
    Returns True when no start buffer is configured.
    """
    start_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_start_minutes', 0)
    if start_buffer <= 0 or specialists_df is None or specialists_df.empty:
        return True

    for _, row in specialists_df.iterrows():
        start_dt, _ = compute_shift_window(row['start_time'], row['end_time'], current_dt)
        minutes_since_start = (current_dt - start_dt).total_seconds() / 60
        if minutes_since_start <= start_buffer:
            return False
    return True


def _overflow_released_by_warm_start(
    specialists_df: pd.DataFrame,
    column: str,
    modality: str,
    current_dt: datetime,
) -> bool:
    """
    Decide whether overflow is allowed under warm-start release policy.

    warm_start_release_mode:
      - 'either': release overflow when time gate OR min-count gate is ready
      - 'both': release overflow only when both gates are ready
    """
    mode = str(BALANCER_SETTINGS.get('warm_start_release_mode', 'either')).strip().lower()
    if mode not in {'either', 'both'}:
        mode = 'either'

    time_ready = _specialist_start_window_ready(specialists_df, current_dt)
    minimum_ready = _specialist_minimum_ready(specialists_df, column, modality)

    if mode == 'both':
        released = time_ready and minimum_ready
    else:
        released = time_ready or minimum_ready

    selection_logger.info(
        "Warm-start overflow gate: mode=%s, time_ready=%s, min_ready=%s, released=%s",
        mode,
        time_ready,
        minimum_ready,
        released,
    )
    return released


def _overflow_released_for_merged_specialists(
    specialist_rows: list[dict],
    primary_skill: str,
    modality: str,
    current_dt: datetime,
) -> bool:
    """
    Warm-start overflow gate for merged specialist pools.

    Evaluates:
    - time gate: all merged specialists past shift-start buffer
    - count gate: all merged specialists at/above min_assignments_per_skill
    - mode gate: warm_start_release_mode (either|both)
    """
    mode = str(BALANCER_SETTINGS.get('warm_start_release_mode', 'either')).strip().lower()
    if mode not in {'either', 'both'}:
        mode = 'either'

    start_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_start_minutes', 0)
    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)

    if not specialist_rows:
        return True

    time_ready = True
    if start_buffer > 0:
        for row in specialist_rows:
            start_dt, _ = compute_shift_window(row['start_time'], row['end_time'], current_dt)
            minutes_since_start = (current_dt - start_dt).total_seconds() / 60
            if minutes_since_start <= start_buffer:
                time_ready = False
                break

    minimum_ready = True
    if min_required > 0:
        for row in specialist_rows:
            worker = row.get('PPL')
            if not worker:
                continue
            if _get_effective_assignment_load(worker, primary_skill, modality) < min_required:
                minimum_ready = False
                break

    released = (time_ready and minimum_ready) if mode == 'both' else (time_ready or minimum_ready)
    selection_logger.info(
        "Merged warm-start gate: mode=%s, time_ready=%s, min_ready=%s, released=%s",
        mode,
        time_ready,
        minimum_ready,
        released,
    )
    return released

def _get_worker_exclusion_based(
    current_dt: datetime,
    role: str,
    modality: str,
    allow_overflow: bool,
):
    """
    Specialist-first assignment with pooled worker overflow.

    Strategy:
    1. Filter workers in requested modality by skill>=0 (excludes skill=-1)
    2. Apply exclusion rules (e.g., notfall_ct team won't get mammo_gyn)
    3. Split into specialists (skill=1/'w') and generalists (skill=0)
    4. Try specialists first, overflow to generalists only if all specialists overloaded
    5. Retry: if exclusions filter out everyone, retry without exclusions (if overflow enabled)
    """
    role_lower = role.lower()
    if role_lower not in ROLE_MAP:
        role_lower = 'normal'
    primary_skill = ROLE_MAP[role_lower]

    # Get exclusion list and overflow settings
    exclude_skills = EXCLUDE_SKILLS.get(primary_skill, [])
    imbalance_threshold_pct = BALANCER_SETTINGS.get('imbalance_threshold_pct', 30)
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

        # Calculate workload ratios using GLOBAL hours (across all modalities)
        # to be consistent with global weighted counts - both are now in the same units
        global_hours_map = calculate_global_work_hours_now(current_dt)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            # Use global hours to match global weighted counts (consistent units)
            hours_worked = global_hours_map.get(canonical_id, 0.0)
            weighted_count = get_global_weighted_count(canonical_id)
            if hours_worked <= 0:
                return 0.0 if weighted_count <= 0 else float('inf')
            return weighted_count / hours_worked

        # Split into specialists (skill=1 or 'w') and generalists (skill=0)
        # 'w' workers use their personal modifier, skill=1 workers do not
        specialists_df = filtered_workers[
            filtered_workers[primary_skill].apply(lambda v: skill_value_to_numeric(v) == 1)
        ]
        generalists_all = filtered_workers[
            filtered_workers[primary_skill].apply(lambda v: skill_value_to_numeric(v) == 0)
        ]

        # Apply shift END buffer to generalists (overflow pool).
        # Shift START behavior is handled by warm-start release policy
        # (time/count, either/both).
        # Keep original generalists_all for fallback if no specialists available.
        generalists_df = generalists_all
        if not generalists_df.empty:
            if shift_end_buffer > 0:
                generalists_df = _filter_near_shift_end(generalists_df, current_dt, shift_end_buffer)

        # Strategy: Try specialists first, overflow to generalists if needed
        if not specialists_df.empty:
            # Apply minimum balancer to specialists
            balanced_specialists = _apply_minimum_balancer(specialists_df, primary_skill, modality)
            specialists_to_check = balanced_specialists if not balanced_specialists.empty else specialists_df

            specialist_workers = specialists_to_check['PPL'].unique()
            specialist_ratios = {p: weighted_ratio(p) for p in specialist_workers}
            if not specialist_ratios:
                selection_logger.warning(
                    "No specialist ratios computed for skill %s in modality %s",
                    primary_skill,
                    modality,
                )
            else:
                # Check if should overflow to generalists based on imbalance
                overflow_triggered = False
                if allow_overflow and not generalists_df.empty and imbalance_threshold_pct > 0:
                    warm_start_released = _overflow_released_by_warm_start(
                        specialists_df=specialists_to_check,
                        column=primary_skill,
                        modality=modality,
                        current_dt=current_dt,
                    )
                    if warm_start_released:
                        # Calculate min ratios for both pools
                        min_specialist_ratio = min(specialist_ratios.values())

                        generalist_workers = generalists_df['PPL'].unique()
                        generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}
                        if generalist_ratios:
                            min_generalist_ratio = min(generalist_ratios.values())
                        else:
                            min_generalist_ratio = None

                        # Check if specialists are imbalanced compared to generalists
                        if min_generalist_ratio is not None and min_generalist_ratio < min_specialist_ratio:
                            specialist_avg = (
                                sum(specialist_ratios.values()) / len(specialist_ratios)
                                if specialist_ratios
                                else 0
                            )
                            generalist_avg = (
                                sum(generalist_ratios.values()) / len(generalist_ratios)
                                if generalist_ratios
                                else 0
                            )
                            imbalance_baseline = max(specialist_avg, generalist_avg)
                            if imbalance_baseline <= 0:
                                imbalance_pct = 0.0
                            else:
                                imbalance_pct = ((min_specialist_ratio - min_generalist_ratio) / imbalance_baseline) * 100
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

        if not allow_overflow:
            selection_logger.info(
                "Overflow disabled for skill %s in modality %s; skipping generalists",
                primary_skill,
                modality,
            )
            return None

        # Use generalists if: (1) no specialists, OR (2) overflow triggered
        # If no buffer-filtered generalists but specialists_df is empty, fallback to all generalists
        generalists_to_use = generalists_df
        if generalists_to_use.empty and specialists_df.empty and not generalists_all.empty:
            # No specialists available - ignore shift buffers and use any generalist
            generalists_to_use = generalists_all
            selection_logger.info(
                "No specialists available for skill %s - ignoring shift buffers for generalists",
                primary_skill,
            )

        if not generalists_to_use.empty:
            balanced_generalists = _apply_minimum_balancer(generalists_to_use, primary_skill, modality)
            generalists_to_check = balanced_generalists if not balanced_generalists.empty else generalists_to_use

            generalist_workers = generalists_to_check['PPL'].unique()
            generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}
            if not generalist_ratios:
                selection_logger.warning(
                    "No generalist ratios computed for skill %s in modality %s",
                    primary_skill,
                    modality,
                )
                return None

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

    # Level 2: Retry without exclusions if overflow enabled
    if not allow_overflow:
        selection_logger.info(
            "No workers available with exclusions for skill %s, overflow disabled",
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


def _get_worker_multi_target(
    current_dt: datetime,
    target_skill_modalities: list,
    allow_overflow: bool,
    overflow_role: Optional[str] = None,
    overflow_modality: Optional[str] = None,
):
    """
    Find worker across multiple skill_modality combinations.

    Searches all specified (skill, modality) pairs and picks the worker
    with the lowest workload ratio from any matching pool. Only considers
    specialists (skill=1 or 'w'), no generalist overflow.

    Args:
        current_dt: Current datetime
        target_skill_modalities: List of (skill, modality) tuples to search
        allow_overflow: Whether overflow to primary-skill generalists is allowed
        overflow_role: Primary role for overflow pool (skill=0 in overflow_modality)
        overflow_modality: Modality for overflow pool

    Returns:
        Tuple of (candidate_row, skill_used, modality) or None
    """
    if not target_skill_modalities:
        return None

    selection_logger.info(
        "Multi-target search across: %s",
        [f"{s}_{m}" for s, m in target_skill_modalities],
    )

    # Calculate workload ratios using global hours
    global_hours_map = calculate_global_work_hours_now(current_dt)

    def weighted_ratio(person):
        canonical_id = get_canonical_worker_id(person)
        hours_worked = global_hours_map.get(canonical_id, 0.0)
        weighted_count = get_global_weighted_count(canonical_id)
        if hours_worked <= 0:
            return 0.0 if weighted_count <= 0 else float('inf')
        return weighted_count / hours_worked

    # Collect all specialist candidates across all skill_modality combinations
    all_candidates = []

    for skill, modality in target_skill_modalities:
        if modality not in modality_data:
            continue

        d = modality_data[modality]
        if d['working_hours_df'] is None:
            continue

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            continue

        if skill not in active_df.columns:
            continue

        # Only consider specialists (skill=1 or 'w') for multi-target
        specialists_df = active_df[
            active_df[skill].apply(lambda v: skill_value_to_numeric(v) == 1)
        ]

        if specialists_df.empty:
            continue

        # Add candidates from this skill_modality combination
        for _, row in specialists_df.iterrows():
            person = row.get('PPL')
            if not person:
                continue
            ratio = weighted_ratio(person)
            all_candidates.append({
                'row': row,
                'person': person,
                'skill': skill,
                'modality': modality,
                'ratio': ratio,
                'is_weighted': is_weighted_skill(row.get(skill)),
            })

    # Build overflow pool (primary skill generalists in requested modality)
    generalists_all = pd.DataFrame()
    generalists_df = pd.DataFrame()
    imbalance_threshold_pct = BALANCER_SETTINGS.get('imbalance_threshold_pct', 30)
    shift_end_buffer = BALANCER_SETTINGS.get('disable_overflow_at_shift_end_minutes', 0)
    if allow_overflow and overflow_role and overflow_modality in modality_data:
        d = modality_data[overflow_modality]
        if d['working_hours_df'] is not None:
            active_df = _filter_active_rows(d['working_hours_df'], current_dt)
            if active_df is not None and not active_df.empty and overflow_role in active_df.columns:
                generalists_all = active_df[
                    active_df[overflow_role].apply(lambda v: skill_value_to_numeric(v) == 0)
                ]
                generalists_df = generalists_all
                if not generalists_df.empty and shift_end_buffer > 0:
                    generalists_df = _filter_near_shift_end(generalists_df, current_dt, shift_end_buffer)

    # If no specialists at all, optionally use overflow pool.
    if not all_candidates:
        if not allow_overflow:
            selection_logger.info(
                "No specialists available for multi-target search: %s",
                [f"{s}_{m}" for s, m in target_skill_modalities],
            )
            return None

        generalists_to_use = generalists_df
        if generalists_to_use.empty and not generalists_all.empty:
            generalists_to_use = generalists_all

        if generalists_to_use.empty:
            selection_logger.info(
                "No specialists or overflow generalists available for multi-target search: %s",
                [f"{s}_{m}" for s, m in target_skill_modalities],
            )
            return None

        generalist_workers = generalists_to_use['PPL'].dropna().unique()
        generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}
        if not generalist_ratios:
            return None

        best_generalist = min(generalist_workers, key=lambda p: generalist_ratios[p])
        candidate = generalists_to_use[generalists_to_use['PPL'] == best_generalist].iloc[0].copy()
        candidate['__modality_source'] = overflow_modality or default_modality
        candidate['__selection_ratio'] = generalist_ratios[best_generalist]
        candidate['__is_weighted'] = False
        candidate['__skill_source'] = overflow_role or ''
        selection_logger.info(
            "Multi-target overflow selected generalist: person=%s, skill=%s=0, ratio=%.4f",
            best_generalist,
            overflow_role,
            generalist_ratios[best_generalist],
        )
        return candidate, (overflow_role or ''), (overflow_modality or default_modality)

    # Best specialist candidate from merged targets
    best_specialist = min(all_candidates, key=lambda c: c['ratio'])
    specialist_rows = []
    seen_specialists = set()
    for c in all_candidates:
        person = c.get('person')
        if person in seen_specialists:
            continue
        seen_specialists.add(person)
        row_dict = c['row'].to_dict() if hasattr(c['row'], 'to_dict') else dict(c['row'])
        specialist_rows.append(row_dict)

    # Evaluate overflow after merged specialist fallback.
    overflow_triggered = False
    if allow_overflow and not generalists_df.empty and imbalance_threshold_pct > 0 and overflow_role and overflow_modality:
        warm_start_released = _overflow_released_for_merged_specialists(
            specialist_rows=specialist_rows,
            primary_skill=overflow_role,
            modality=overflow_modality,
            current_dt=current_dt,
        )
        if warm_start_released:
            specialist_min_ratio = best_specialist['ratio']
            generalist_workers = generalists_df['PPL'].dropna().unique()
            generalist_ratios = {p: weighted_ratio(p) for p in generalist_workers}
            if generalist_ratios:
                min_generalist_ratio = min(generalist_ratios.values())
                if min_generalist_ratio < specialist_min_ratio:
                    specialist_avg = sum(c['ratio'] for c in all_candidates) / len(all_candidates)
                    generalist_avg = sum(generalist_ratios.values()) / len(generalist_ratios)
                    imbalance_baseline = max(specialist_avg, generalist_avg)
                    imbalance_pct = 0.0 if imbalance_baseline <= 0 else (
                        (specialist_min_ratio - min_generalist_ratio) / imbalance_baseline
                    ) * 100
                    if imbalance_pct >= imbalance_threshold_pct:
                        overflow_triggered = True
                        best_generalist = min(generalist_workers, key=lambda p: generalist_ratios[p])
                        candidate = generalists_df[generalists_df['PPL'] == best_generalist].iloc[0].copy()
                        candidate['__modality_source'] = overflow_modality
                        candidate['__selection_ratio'] = generalist_ratios[best_generalist]
                        candidate['__is_weighted'] = False
                        candidate['__skill_source'] = overflow_role
                        selection_logger.info(
                            "Multi-target overflow triggered: specialist_min=%.4f, generalist_min=%.4f, imbalance=%.1f%% >= %d%%, selected=%s",
                            specialist_min_ratio,
                            min_generalist_ratio,
                            imbalance_pct,
                            imbalance_threshold_pct,
                            best_generalist,
                        )
                        return candidate, overflow_role, overflow_modality

    # Default: use merged specialist candidate
    candidate = best_specialist['row'].copy()
    candidate['__modality_source'] = best_specialist['modality']
    candidate['__selection_ratio'] = best_specialist['ratio']
    candidate['__is_weighted'] = best_specialist['is_weighted']
    candidate['__skill_source'] = best_specialist['skill']

    selection_logger.info(
        "Multi-target selected specialist: person=%s, skill=%s, modality=%s, weighted=%s, ratio=%.4f, overflow_triggered=%s",
        best_specialist['person'],
        best_specialist['skill'],
        best_specialist['modality'],
        best_specialist['is_weighted'],
        best_specialist['ratio'],
        overflow_triggered,
    )

    return candidate, best_specialist['skill'], best_specialist['modality']


def get_next_available_worker(
    current_dt: datetime,
    role='normal',
    modality=default_modality,
    allow_overflow: bool = True,
    target_skill_modalities=None,
):
    """
    Get the next available worker for a skill assignment.

    Args:
        current_dt: Current datetime
        role: Skill name to assign
        modality: Modality context (used if target_skill_modalities not provided)
        allow_overflow: Whether to allow overflow to generalists
        target_skill_modalities: Optional list of (skill, modality) tuples to search across.
                                If provided, searches all specified combinations and picks
                                the worker with the lowest workload ratio.
    """
    if target_skill_modalities:
        return _get_worker_multi_target(
            current_dt,
            target_skill_modalities,
            allow_overflow,
            overflow_role=role,
            overflow_modality=modality,
        )
    return _get_worker_exclusion_based(current_dt, role, modality, allow_overflow)
