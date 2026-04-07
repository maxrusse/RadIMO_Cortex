"""
Schedule CRUD operations module.

This module handles:
- Row-level schedule updates (update, add, delete)
- Gap rows (independent entries that override shift availability)
- Worker tracking reconciliation
- Overlapping shift resolution
"""
from datetime import datetime, time, date
from typing import Optional, Dict, List, Tuple

import pandas as pd

from config import (
    allowed_modalities,
    SKILL_COLUMNS,
    selection_logger,
)
from lib.utils import (
    TIME_FORMAT,
    is_weighted_skill,
    normalize_skill_value,
    get_next_workday,
    subtract_intervals,
    merge_intervals,
    strip_builder_fields,
    coerce_bool,
)
from state_manager import StateManager
from data_manager.file_ops import _calculate_total_work_hours, backup_dataframe

# Get state references
_state = StateManager.get_instance()
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data
staged_modality_data = _state.staged_modality_data


def _validate_row_index(df: pd.DataFrame, row_index: int) -> bool:
    """Validate that row_index exists in DataFrame."""
    if df is None:
        return False
    return row_index in df.index


def _ensure_row_type_column(df: pd.DataFrame) -> None:
    if df is None:
        return
    if 'row_type' not in df.columns:
        df['row_type'] = 'shift_segment'
    else:
        df['row_type'] = df['row_type'].fillna('shift_segment').apply(
            lambda value: 'gap_segment'
            if _is_gap_row_type(value)
            else ('shift_segment' if str(value).strip().lower() in {'shift', 'shift_segment'} else value)
        )


def _is_gap_row_type(value: Optional[str]) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {'gap', 'gap_segment'}


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _minutes_to_time(value: int) -> time:
    hours = value // 60
    minutes = value % 60
    return time(hours, minutes)


def _coerce_time_value(value: Optional[object]) -> Optional[time]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, str):
        if not value.strip():
            return None
        return datetime.strptime(value, TIME_FORMAT).time()
    return None


def _is_valid_time_window(start: Optional[time], end: Optional[time]) -> bool:
    if start is None or end is None:
        return False
    return _time_to_minutes(end) > _time_to_minutes(start)


def build_day_plan_rows(rows: List[dict], target_date: date) -> List[dict]:
    if not rows:
        return []

    rows_by_worker: Dict[str, List[dict]] = {}
    for order, row in enumerate(rows):
        normalized = dict(row)
        row_type_value = normalized.get('row_type') or 'shift'
        if isinstance(row_type_value, str):
            row_type_value = row_type_value.strip().lower() or 'shift'
        normalized['_was_segment'] = row_type_value == 'shift_segment'
        normalized['row_type'] = 'gap' if row_type_value in {'gap', 'gap_segment'} else 'shift'
        normalized['PPL'] = normalized.get('PPL', '')
        normalized['start_time'] = _coerce_time_value(normalized.get('start_time'))
        normalized['end_time'] = _coerce_time_value(normalized.get('end_time'))
        training = coerce_bool(normalized.get('training'))
        normalized['training'] = False if normalized['row_type'] == 'gap' else (training if training is not None else True)

        if normalized.get('_order') is None:
            if normalized.get('start_time') is not None:
                normalized['_order'] = _time_to_minutes(normalized['start_time'])
            else:
                normalized['_order'] = order

        if not _is_valid_time_window(normalized.get('start_time'), normalized.get('end_time')):
            selection_logger.info(
                "Dropping row with invalid time window for '%s' (%s): %s-%s",
                normalized.get('PPL', ''),
                normalized.get('row_type'),
                normalized.get('start_time'),
                normalized.get('end_time'),
            )
            continue

        tasks = normalized.get('tasks')
        if isinstance(tasks, list):
            normalized['tasks'] = ', '.join([task for task in tasks if task])
        elif tasks is None:
            normalized['tasks'] = ''

        if normalized.get('Modifier') is None:
            normalized['Modifier'] = 1.0
        if normalized.get('counts_for_hours') is None:
            normalized['counts_for_hours'] = normalized['row_type'] != 'gap'
        else:
            normalized['counts_for_hours'] = _coerce_bool(normalized['counts_for_hours'])
            if normalized['counts_for_hours'] is None:
                normalized['counts_for_hours'] = normalized['row_type'] != 'gap'

        for skill in SKILL_COLUMNS:
            if normalized['row_type'] == 'gap':
                normalized[skill] = -1
                continue
            if skill in normalized:
                normalized[skill] = normalize_skill_value(normalized[skill])
                if not normalized['training'] and is_weighted_skill(normalized[skill]):
                    normalized[skill] = -1
            else:
                normalized[skill] = 0

        normalized['TIME'] = (
            f"{normalized['start_time'].strftime(TIME_FORMAT)}-"
            f"{normalized['end_time'].strftime(TIME_FORMAT)}"
        )

        rows_by_worker.setdefault(normalized['PPL'], []).append(normalized)

    built_rows: List[dict] = []

    for worker_name, worker_rows in rows_by_worker.items():
        shift_rows = [row for row in worker_rows if not _is_gap_row_type(row.get('row_type'))]
        gap_rows = [row for row in worker_rows if _is_gap_row_type(row.get('row_type'))]

        resolved_shifts = resolve_overlapping_shifts(shift_rows, target_date) if shift_rows else []

        gap_intervals: List[Tuple[int, int]] = []
        for gap_row in gap_rows:
            if gap_row.get('counts_for_hours', False):
                continue
            start = gap_row.get('start_time')
            end = gap_row.get('end_time')
            if start is None or end is None:
                continue
            start_min = _time_to_minutes(start)
            end_min = _time_to_minutes(end)
            if end_min <= start_min:
                continue
            gap_intervals.append((start_min, end_min))
        gap_intervals = merge_intervals(gap_intervals)

        shift_segments: List[dict] = []
        for shift_row in resolved_shifts:
            start = shift_row.get('start_time')
            end = shift_row.get('end_time')
            if start is None or end is None:
                continue
            start_min = _time_to_minutes(start)
            end_min = _time_to_minutes(end)
            if end_min <= start_min:
                continue
            remaining = subtract_intervals((start_min, end_min), gap_intervals)
            for seg_start, seg_end in remaining:
                segment = dict(shift_row)
                segment.pop('_was_segment', None)
                segment.pop('_order', None)
                segment_start = _minutes_to_time(seg_start)
                segment_end = _minutes_to_time(seg_end)
                segment['start_time'] = segment_start
                segment['end_time'] = segment_end
                segment['TIME'] = (
                    f"{segment_start.strftime(TIME_FORMAT)}-"
                    f"{segment_end.strftime(TIME_FORMAT)}"
                )
                segment['shift_duration'] = round((seg_end - seg_start) / 60.0, 4)
                if segment['shift_duration'] <= 0:
                    segment['counts_for_hours'] = False
                segment['row_type'] = 'shift_segment'
                shift_segments.append(segment)

        for gap_row in gap_rows:
            gap_row['row_type'] = 'gap_segment'
            gap_row['shift_duration'] = 0.0
            if gap_row.get('counts_for_hours') is None:
                gap_row['counts_for_hours'] = False
            for skill in SKILL_COLUMNS:
                gap_row[skill] = -1
            gap_row.pop('_was_segment', None)
            gap_row.pop('_order', None)

        built_rows.extend(shift_segments + gap_rows)

    return built_rows


def _recalculate_worker_shift_durations(df: pd.DataFrame, worker_name: str) -> None:
    if df is None or df.empty:
        return
    _ensure_row_type_column(df)
    worker_rows = df[df['PPL'] == worker_name]
    if worker_rows.empty:
        return
    for idx, row in worker_rows[~worker_rows['row_type'].apply(_is_gap_row_type)].iterrows():
        start = row.get('start_time')
        end = row.get('end_time')
        if pd.isna(start) or pd.isna(end):
            df.at[idx, 'shift_duration'] = 0.0
            df.at[idx, 'counts_for_hours'] = False
            continue
        if not _is_valid_time_window(start, end):
            df.at[idx, 'shift_duration'] = 0.0
            df.at[idx, 'counts_for_hours'] = False
            continue
        total_minutes = _time_to_minutes(end) - _time_to_minutes(start)
        df.at[idx, 'shift_duration'] = round(total_minutes / 60.0, 4)
        if total_minutes <= 0:
            df.at[idx, 'counts_for_hours'] = False


def _coerce_bool(value: Optional[object]) -> Optional[bool]:
    """Normalize various truthy/falsey inputs into a bool or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'true', '1', 'yes', 'y'}
    return bool(value)


def _get_schedule_data_dict(modality: str, use_staged: bool) -> dict:
    """Get the appropriate data dict (staged or live)."""
    if use_staged:
        return staged_modality_data[modality]
    return modality_data[modality]


def _get_staged_target_date() -> date:
    """Resolve the target date for staged prep data."""
    for mod_data in staged_modality_data.values():
        target_date = mod_data.get('target_date')
        if isinstance(target_date, date):
            return target_date
        if isinstance(target_date, str):
            try:
                return date.fromisoformat(target_date)
            except ValueError:
                continue
    return get_next_workday().date()


def _get_active_worker_names(df: Optional[pd.DataFrame]) -> set:
    """Get set of active worker names from DataFrame."""
    if df is None or df.empty or 'PPL' not in df.columns:
        return set()
    return {str(name).strip() for name in df['PPL'].dropna()}


def resolve_overlapping_shifts(shifts: List[dict], target_date: date) -> List[dict]:
    """
    Resolve overlapping shifts for the same worker. Same-day operations only.

    Later shifts take priority over earlier ones (based on input order). When overlaps
    occur, earlier shifts are trimmed to remove the overlap, allowing edited shifts
    to "win" while keeping non-overlapping time intact.

    Args:
        shifts: List of shift dicts with 'PPL', 'start_time', 'end_time', etc.
        target_date: The target date for datetime calculations

    Returns:
        List of resolved shifts without overlaps
    """
    if not shifts or len(shifts) <= 1:
        return shifts

    def _build_shift_segment(base_shift: dict, start_min: int, end_min: int) -> Optional[dict]:
        if end_min <= start_min:
            return None
        duration_hours = round((end_min - start_min) / 60.0, 4)
        if duration_hours < 0.1:
            return None
        segment = base_shift.copy()
        segment['start_time'] = _minutes_to_time(start_min)
        segment['end_time'] = _minutes_to_time(end_min)
        segment['shift_duration'] = duration_hours
        if 'TIME' in segment:
            segment['TIME'] = (
                f"{segment['start_time'].strftime(TIME_FORMAT)}-"
                f"{segment['end_time'].strftime(TIME_FORMAT)}"
            )
        segment.pop('_order', None)
        return segment

    # Group shifts by worker
    shifts_by_worker: Dict[str, List[dict]] = {}
    for order, shift in enumerate(shifts):
        worker = shift.get('PPL', '')
        shift_copy = shift.copy()
        if shift_copy.get('_order') is None:
            start_time = shift_copy.get('start_time')
            if isinstance(start_time, time):
                shift_copy['_order'] = _time_to_minutes(start_time)
            else:
                shift_copy['_order'] = order
        shifts_by_worker.setdefault(worker, []).append(shift_copy)

    result_shifts = []

    for worker, worker_shifts in shifts_by_worker.items():
        if len(worker_shifts) <= 1:
            for shift in worker_shifts:
                shift.pop('_order', None)
            result_shifts.extend(worker_shifts)
            continue

        ordered_shifts = sorted(worker_shifts, key=lambda s: s.get('_order', 0))
        resolved: List[dict] = []

        for current_shift in ordered_shifts:
            current_start = current_shift.get('start_time')
            current_end = current_shift.get('end_time')
            if current_start is None or current_end is None:
                continue
            current_start_dt = datetime.combine(target_date, current_start)
            current_end_dt = datetime.combine(target_date, current_end)
            if current_end_dt <= current_start_dt:
                continue
            current_start_min = _time_to_minutes(current_start)
            current_end_min = _time_to_minutes(current_end)

            updated_resolved: List[dict] = []
            for existing_shift in resolved:
                existing_start = existing_shift.get('start_time')
                existing_end = existing_shift.get('end_time')
                if existing_start is None or existing_end is None:
                    continue
                existing_start_min = _time_to_minutes(existing_start)
                existing_end_min = _time_to_minutes(existing_end)
                remaining = subtract_intervals(
                    (existing_start_min, existing_end_min),
                    [(current_start_min, current_end_min)],
                )
                for seg_start, seg_end in remaining:
                    segment = _build_shift_segment(existing_shift, seg_start, seg_end)
                    if segment is not None:
                        updated_resolved.append(segment)

            resolved = updated_resolved
            current_segment = _build_shift_segment(current_shift, current_start_min, current_end_min)
            if current_segment is not None:
                resolved.append(current_segment)
                selection_logger.debug(
                    f"Shift for {worker}: {current_segment['start_time'].strftime(TIME_FORMAT)}-"
                    f"{current_segment['end_time'].strftime(TIME_FORMAT)} "
                    f"(duration: {current_segment['shift_duration']:.2f}h)"
                )
            else:
                selection_logger.info(
                    f"Removed zero-duration shift for {worker} "
                    f"(was {current_shift['start_time'].strftime(TIME_FORMAT)}-"
                    f"{current_shift['end_time'].strftime(TIME_FORMAT)})"
                )

        result_shifts.extend(resolved)

    return result_shifts


def reconcile_live_worker_tracking(modality: Optional[str] = None) -> None:
    """
    Reconcile live worker tracking data after edits/deletions.

    Ensures skill_counts, weighted counts, and global assignment tracking
    only include workers currently present in the live schedules.
    """
    # Import here to avoid circular imports
    from data_manager.worker_management import get_canonical_worker_id

    active_workers_by_mod = {}
    active_canon_by_mod = {}
    all_active_canon = set()

    for mod in allowed_modalities:
        df = modality_data[mod].get('working_hours_df')
        active_workers = _get_active_worker_names(df)
        active_workers_by_mod[mod] = active_workers
        active_canon = {get_canonical_worker_id(name) for name in active_workers}
        active_canon_by_mod[mod] = active_canon
        all_active_canon.update(active_canon)

    modalities_to_reconcile = [modality] if modality else allowed_modalities

    for mod in modalities_to_reconcile:
        d = modality_data[mod]
        active_workers = active_workers_by_mod.get(mod, set())
        df = d.get('working_hours_df')

        new_skill_counts = {}
        for skill in SKILL_COLUMNS:
            counts = d['skill_counts'].get(skill, {})
            new_skill_counts[skill] = {name: counts.get(name, 0) for name in active_workers}
        d['skill_counts'] = new_skill_counts
        if df is None or df.empty:
            d['worker_modifiers'] = {}
            d['total_work_hours'] = {}
        else:
            d['worker_modifiers'] = df.groupby('PPL')['Modifier'].first().to_dict()
            d['total_work_hours'] = _calculate_total_work_hours(df)

        current_assignments = global_worker_data['assignments_per_mod'].get(mod, {})
        active_canon = active_canon_by_mod.get(mod, set())
        cleaned_assignments = {}
        for canonical_id in active_canon:
            if canonical_id in current_assignments:
                cleaned_assignments[canonical_id] = current_assignments[canonical_id]
            else:
                cleaned_assignments[canonical_id] = {skill: 0 for skill in SKILL_COLUMNS}
                cleaned_assignments[canonical_id]['total'] = 0
        global_worker_data['assignments_per_mod'][mod] = cleaned_assignments

    global_worker_data['weighted_counts'] = {
        canonical_id: global_worker_data['weighted_counts'].get(canonical_id, 0.0)
        for canonical_id in all_active_canon
    }


def _update_schedule_row(modality: str, row_index: int, updates: dict, use_staged: bool) -> tuple:
    """Update a single row in the schedule.

    Returns:
        (success: bool, error_or_info: str or dict)
        On success: (True, {'reindexed': bool}) - reindexed=True if DataFrame was rebuilt
        On failure: (False, error_message)
    """
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']
    _ensure_row_type_column(df)

    if not _validate_row_index(df, row_index):
        return False, 'Invalid row index'

    try:
        if 'PPL' in updates:
            return False, 'Worker renames are only allowed in the skill roster'
        worker_name = df.at[row_index, 'PPL']
        worker_rows = df[df['PPL'] == worker_name].copy()
        rows_with_index = [(idx, row.to_dict()) for idx, row in worker_rows.iterrows()]

        for idx, row in rows_with_index:
            if idx != row_index:
                continue
            for col, value in updates.items():
                if col in ['start_time', 'end_time']:
                    row[col] = datetime.strptime(value, TIME_FORMAT).time()
                elif col in SKILL_COLUMNS:
                    row[col] = normalize_skill_value(value)
                elif col == 'Modifier':
                    row[col] = float(value)
                elif col == 'tasks':
                    if isinstance(value, list):
                        row['tasks'] = ', '.join(value)
                    else:
                        row['tasks'] = value
                elif col == 'counts_for_hours':
                    coerced = _coerce_bool(value)
                    row['counts_for_hours'] = coerced if coerced is not None else False
                elif col == 'training':
                    coerced = _coerce_bool(value)
                    row['training'] = coerced if coerced is not None else (not _is_gap_row_type(row.get('row_type')))
                    if _is_gap_row_type(row.get('row_type')):
                        row['training'] = False
                elif col == 'row_type':
                    row['row_type'] = value
                    if _is_gap_row_type(value) and 'counts_for_hours' not in updates:
                        row['counts_for_hours'] = False
                    if _is_gap_row_type(value):
                        row['training'] = False
                    elif 'training' not in updates:
                        row['training'] = True
            break

        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        raw_rows = []
        updated_row = None
        for idx, row in rows_with_index:
            if idx == row_index:
                updated_row = row
            else:
                raw_rows.append(row)
        if updated_row is not None:
            existing_orders = []
            for row in raw_rows:
                if row.get('_order') is not None:
                    existing_orders.append(row['_order'])
                    continue
                start_time = row.get('start_time')
                if isinstance(start_time, time):
                    existing_orders.append(_time_to_minutes(start_time))
            max_order = max(existing_orders, default=0)
            updated_row['_order'] = max_order + 1
            raw_rows.append(updated_row)
        success, info, error = _replace_worker_schedule(
            modality,
            worker_name,
            raw_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, error
        return True, info

    except ValueError as e:
        return False, f'Invalid time format: {e}'
    except Exception as e:
        return False, str(e)


def update_schedule_row(modality: str, row_index: int, updates: dict, use_staged: bool) -> tuple:
    """Public wrapper for updating a schedule row."""
    return _update_schedule_row(modality, row_index, updates, use_staged)


def _add_worker_to_schedule(modality: str, worker_data: dict, use_staged: bool) -> tuple:
    """Add a new worker row to the schedule.

    Returns:
        (success: bool, row_index_or_info: int or dict, error: str or None)
        On success: (True, {'row_index': int, 'reindexed': bool}, None)
        On failure: (False, None, error_message)
    """
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    try:
        ppl_name = worker_data.get('PPL', 'Neuer Worker (NW)')
        row_type = worker_data.get('row_type', 'shift')
        if _is_gap_row_type(row_type):
            row_type = 'gap'
        training = _coerce_bool(worker_data.get('training'))
        new_row = {
            'PPL': ppl_name,
            'start_time': datetime.strptime(worker_data.get('start_time', '07:00'), TIME_FORMAT).time(),
            'end_time': datetime.strptime(worker_data.get('end_time', '15:00'), TIME_FORMAT).time(),
            'Modifier': float(worker_data.get('Modifier', 1.0)),
            'row_type': row_type,
            'training': False if row_type == 'gap' else (training if training is not None else True),
        }

        # Only add TIME if the existing df has TIME column (for consistency)
        if df is not None and 'TIME' in df.columns:
            new_row['TIME'] = f"{new_row['start_time'].strftime(TIME_FORMAT)}-{new_row['end_time'].strftime(TIME_FORMAT)}"

        for skill in SKILL_COLUMNS:
            default_value = -1 if row_type == 'gap' else 0
            new_row[skill] = normalize_skill_value(worker_data.get(skill, default_value))

        tasks = worker_data.get('tasks', [])
        if isinstance(tasks, list):
            new_row['tasks'] = ', '.join(tasks)
        else:
            new_row['tasks'] = tasks or ''

        start_dt = datetime.combine(datetime.today(), new_row['start_time'])
        end_dt = datetime.combine(datetime.today(), new_row['end_time'])
        # Same-day only: duration is 0 if end <= start
        if end_dt > start_dt and row_type != 'gap':
            new_row['shift_duration'] = (end_dt - start_dt).total_seconds() / 3600
        else:
            new_row['shift_duration'] = 0.0

        counts_for_hours = worker_data.get('counts_for_hours', row_type != 'gap')
        coerced = _coerce_bool(counts_for_hours)
        new_row['counts_for_hours'] = coerced if coerced is not None else row_type != 'gap'
        existing_rows = []
        if df is not None and not df.empty:
            existing_rows = df[df['PPL'] == ppl_name].to_dict('records')
        raw_rows = existing_rows + [new_row]

        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        success, info, error = _replace_worker_schedule(
            modality,
            ppl_name,
            raw_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, None, error

        new_df = data_dict['working_hours_df']
        new_idx = None
        if new_df is not None and not new_df.empty:
            if row_type == 'gap':
                row_type_mask = new_df['row_type'].apply(_is_gap_row_type)
            else:
                row_type_mask = ~new_df['row_type'].apply(_is_gap_row_type)
            matches = new_df[
                (new_df['PPL'] == ppl_name) &
                row_type_mask &
                (new_df['start_time'] == new_row['start_time']) &
                (new_df['end_time'] == new_row['end_time']) &
                (new_df['tasks'] == new_row['tasks'])
            ]
            if not matches.empty:
                new_idx = int(matches.index[-1])

        return True, {'row_index': new_idx, 'reindexed': info.get('reindexed', False)}, None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def add_worker_to_schedule(modality: str, worker_data: dict, use_staged: bool) -> tuple:
    """Public wrapper for adding a worker to a schedule."""
    return _add_worker_to_schedule(modality, worker_data, use_staged)


def _replace_worker_schedule(
    modality: str,
    worker_name: str,
    rows: list,
    use_staged: bool,
    target_date: Optional[date] = None,
) -> tuple:
    """Replace all schedule rows for a worker with the provided rows."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    try:
        df, info = _build_replaced_worker_schedule_df(
            modality,
            worker_name,
            rows,
            use_staged,
            target_date=target_date,
        )
        data_dict['working_hours_df'] = df

        if not use_staged:
            reconcile_live_worker_tracking(modality)

        backup_dataframe(modality, use_staged=use_staged)
        return True, info, None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def _build_replaced_worker_schedule_df(
    modality: str,
    worker_name: str,
    rows: list,
    use_staged: bool,
    target_date: Optional[date] = None,
) -> Tuple[pd.DataFrame, dict]:
    """Build a replacement schedule DataFrame for a worker without persisting it."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    current_df = data_dict['working_hours_df']
    current_df = current_df if current_df is not None else pd.DataFrame()
    original_worker_count = 0 if current_df.empty else len(current_df[current_df['PPL'] == worker_name])

    if current_df.empty:
        df = pd.DataFrame()
    else:
        df = current_df[current_df['PPL'] != worker_name].reset_index(drop=True)

    target_date = target_date or (_get_staged_target_date() if use_staged else datetime.today().date())
    raw_rows = []
    for worker_data in rows:
        row_copy = strip_builder_fields(worker_data)
        row_copy['PPL'] = worker_name
        raw_rows.append(row_copy)
    plan_rows = build_day_plan_rows(raw_rows, target_date)

    if plan_rows:
        new_df = pd.DataFrame(plan_rows)
        df = pd.concat([df, new_df], ignore_index=True)

    if use_staged:
        if 'is_manual' not in df.columns:
            df['is_manual'] = False
        df.loc[df['PPL'] == worker_name, 'is_manual'] = True

    reindexed = original_worker_count != len(plan_rows)
    return df, {'reindexed': reindexed}


def replace_worker_schedule(modality: str, worker_name: str, rows: list, use_staged: bool) -> tuple:
    """Public wrapper for replacing a worker schedule."""
    return _replace_worker_schedule(modality, worker_name, rows, use_staged)


def _delete_worker_from_schedule(modality: str, row_index: int, use_staged: bool, verify_ppl: Optional[str] = None) -> tuple:
    """Delete a worker row from the schedule."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    try:
        row_index_int = int(row_index)
    except (TypeError, ValueError):
        return False, None, 'Invalid row index'

    if not _validate_row_index(df, row_index_int):
        return False, None, 'Invalid row index'

    try:
        worker_name = df.loc[row_index_int, 'PPL']

        if verify_ppl and str(worker_name) != str(verify_ppl):
            return False, None, 'Row mismatch: Schedule has changed. Please reload.'

        remaining_rows = df.drop(index=row_index_int).reset_index(drop=True)
        worker_rows = remaining_rows[remaining_rows['PPL'] == worker_name].to_dict('records')
        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        success, _, error = _replace_worker_schedule(
            modality,
            worker_name,
            worker_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, None, error
        return True, worker_name, None

    except Exception as e:
        return False, None, str(e)


def delete_worker_from_schedule(
    modality: str,
    row_index: int,
    use_staged: bool,
    verify_ppl: Optional[str] = None,
) -> tuple:
    """Public wrapper for deleting a worker from a schedule."""
    return _delete_worker_from_schedule(modality, row_index, use_staged, verify_ppl=verify_ppl)


def _add_gap_to_schedule(
    modality: str,
    row_index: int,
    gap_type: str,
    gap_start: str,
    gap_end: str,
    use_staged: bool,
    gap_counts_for_hours: Optional[bool] = None,
) -> tuple:
    """Add a gap intent row for a worker (canonicalized to gap segments on rebuild)."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        _ensure_row_type_column(df)
        worker_name = df.loc[row_index, 'PPL']

        gap_start_time = datetime.strptime(gap_start, TIME_FORMAT).time()
        gap_end_time = datetime.strptime(gap_end, TIME_FORMAT).time()

        if gap_start_time >= gap_end_time:
            return False, None, 'Gap start time must be before gap end time'

        normalized_gap_counts = _coerce_bool(gap_counts_for_hours)
        if normalized_gap_counts is None:
            normalized_gap_counts = False

        gap_row = {
            'PPL': worker_name,
            'start_time': gap_start_time,
            'end_time': gap_end_time,
            'Modifier': 1.0,
            'tasks': gap_type,
            'counts_for_hours': normalized_gap_counts,
            'row_type': 'gap',
        }
        for skill in SKILL_COLUMNS:
            gap_row[skill] = -1

        existing_rows = df[df['PPL'] == worker_name].to_dict('records')
        raw_rows = existing_rows + [gap_row]
        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        success, _, error = _replace_worker_schedule(
            modality,
            worker_name,
            raw_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, None, error
        log_prefix = "STAGED: " if use_staged else ""
        selection_logger.info(f"{log_prefix}Added gap ({gap_type}) for {worker_name} {gap_start}-{gap_end}")
        return True, 'gap_added', None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def add_gap_to_schedule(
    modality: str,
    row_index: int,
    gap_type: str,
    gap_start: str,
    gap_end: str,
    use_staged: bool,
    gap_counts_for_hours: Optional[bool] = None,
) -> tuple:
    """Public wrapper for adding a gap to a schedule."""
    return _add_gap_to_schedule(
        modality,
        row_index,
        gap_type,
        gap_start,
        gap_end,
        use_staged,
        gap_counts_for_hours=gap_counts_for_hours,
    )


def add_gap_to_schedule_batch(
    row_index_map: dict,
    gap_type: str,
    gap_start: str,
    gap_end: str,
    use_staged: bool,
    gap_counts_for_hours: Optional[bool] = None,
) -> tuple:
    """Public wrapper for adding a gap to multiple modality rows atomically."""
    return _add_gap_to_schedule_batch(
        row_index_map,
        gap_type,
        gap_start,
        gap_end,
        use_staged,
        gap_counts_for_hours=gap_counts_for_hours,
    )


def _add_gap_to_schedule_batch(
    row_index_map: dict,
    gap_type: str,
    gap_start: str,
    gap_end: str,
    use_staged: bool,
    gap_counts_for_hours: Optional[bool] = None,
) -> tuple:
    """Add a gap intent row for a worker across multiple modalities atomically."""
    if not row_index_map:
        return False, None, 'No schedule rows provided'

    try:
        gap_start_time = datetime.strptime(gap_start, TIME_FORMAT).time()
        gap_end_time = datetime.strptime(gap_end, TIME_FORMAT).time()

        if gap_start_time >= gap_end_time:
            return False, None, 'Gap start time must be before gap end time'

        normalized_gap_counts = _coerce_bool(gap_counts_for_hours)
        if normalized_gap_counts is None:
            normalized_gap_counts = False

        worker_name = None
        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        pending_updates = []
        data_dicts = {
            str(mod).lower(): _get_schedule_data_dict(str(mod).lower(), use_staged)
            for mod in row_index_map.keys()
        }

        for modality, row_index in row_index_map.items():
            modality_key = str(modality or '').lower()
            if modality_key not in data_dicts:
                return False, None, f'Invalid modality: {modality}'
            data_dict = data_dicts[modality_key]
            df = data_dict['working_hours_df']

            try:
                row_index_int = int(row_index)
            except (TypeError, ValueError):
                return False, None, 'Invalid row index'

            if not _validate_row_index(df, row_index_int):
                return False, None, 'Invalid row index'

            row_worker = df.loc[row_index_int, 'PPL']
            if worker_name is None:
                worker_name = row_worker
            elif str(row_worker) != str(worker_name):
                return False, None, 'Row mismatch across modalities'

            gap_row = {
                'PPL': worker_name,
                'start_time': gap_start_time,
                'end_time': gap_end_time,
                'Modifier': 1.0,
                'tasks': gap_type,
                'counts_for_hours': normalized_gap_counts,
                'row_type': 'gap',
            }
            for skill in SKILL_COLUMNS:
                gap_row[skill] = -1

            existing_rows = df[df['PPL'] == worker_name].to_dict('records')
            raw_rows = existing_rows + [gap_row]
            new_df, info = _build_replaced_worker_schedule_df(
                modality,
                worker_name,
                raw_rows,
                use_staged,
                target_date=target_date,
            )
            pending_updates.append((modality_key, new_df, info))

        for modality, new_df, _info in pending_updates:
            data_dict = _get_schedule_data_dict(modality, use_staged)
            data_dict['working_hours_df'] = new_df

        if not use_staged:
            for modality, _, _info in pending_updates:
                reconcile_live_worker_tracking(modality)

        for modality, _, _info in pending_updates:
            backup_dataframe(modality, use_staged=use_staged)

        log_prefix = "STAGED: " if use_staged else ""
        selection_logger.info(
            f"{log_prefix}Added gap ({gap_type}) for {worker_name} {gap_start}-{gap_end} across {len(pending_updates)} modalities"
        )
        return True, {'reindexed': any(info.get('reindexed') for _, _, info in pending_updates)}, None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def _remove_gap_from_schedule(
    modality: str,
    row_index: int,
    gap_index: Optional[int],
    use_staged: bool,
    gap_match: Optional[dict] = None,
) -> tuple:
    """Remove a gap intent row from a worker's schedule."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        _ensure_row_type_column(df)
        worker_name = df.loc[row_index, 'PPL']

        if not gap_match:
            return False, None, 'Gap match criteria required'

        match_start = gap_match.get('start')
        match_end = gap_match.get('end')
        match_activity = gap_match.get('activity')

        if not match_start or not match_end:
            return False, None, 'Gap start and end are required'

        start_time = datetime.strptime(match_start, TIME_FORMAT).time()
        end_time = datetime.strptime(match_end, TIME_FORMAT).time()

        gap_candidates = df[
            (df['PPL'] == worker_name) &
            (df['row_type'].apply(_is_gap_row_type)) &
            (df['start_time'] == start_time) &
            (df['end_time'] == end_time)
        ]

        if match_activity:
            gap_candidates = gap_candidates[gap_candidates['tasks'] == match_activity]

        if gap_candidates.empty:
            return False, None, 'Gap not found for removal'

        gap_row_idx = gap_candidates.index[0]
        removed_gap = df.loc[gap_row_idx]
        remaining_rows = df.drop(index=gap_row_idx).reset_index(drop=True)
        worker_rows = remaining_rows[remaining_rows['PPL'] == worker_name].to_dict('records')
        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        success, _, error = _replace_worker_schedule(
            modality,
            worker_name,
            worker_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, None, error
        log_prefix = "STAGED: " if use_staged else ""
        selection_logger.info(
            f"{log_prefix}Removed gap [{removed_gap.get('tasks', 'unknown')}] "
            f"({match_start}-{match_end}) for {worker_name}"
        )
        return True, 'gap_removed', None

    except Exception as e:
        return False, None, str(e)


def remove_gap_from_schedule(
    modality: str,
    row_index: int,
    gap_index: Optional[int],
    use_staged: bool,
    gap_match: Optional[dict] = None,
) -> tuple:
    """Public wrapper for removing a gap from a schedule."""
    return _remove_gap_from_schedule(modality, row_index, gap_index, use_staged, gap_match=gap_match)


def _update_gap_in_schedule(
    modality: str,
    row_index: int,
    gap_index: Optional[int],
    new_start: Optional[str],
    new_end: Optional[str],
    new_activity: Optional[str],
    use_staged: bool,
    new_counts_for_hours: Optional[bool] = None,
    gap_match: Optional[dict] = None,
) -> tuple:
    """Update a gap intent row in a worker's schedule."""
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        _ensure_row_type_column(df)
        worker_name = df.loc[row_index, 'PPL']

        if not gap_match:
            return False, None, 'Gap match criteria required'

        match_start = gap_match.get('start')
        match_end = gap_match.get('end')
        match_activity = gap_match.get('activity')

        if not match_start or not match_end:
            return False, None, 'Gap start and end are required'

        start_time = datetime.strptime(match_start, TIME_FORMAT).time()
        end_time = datetime.strptime(match_end, TIME_FORMAT).time()

        gap_candidates = df[
            (df['PPL'] == worker_name) &
            (df['row_type'].apply(_is_gap_row_type)) &
            (df['start_time'] == start_time) &
            (df['end_time'] == end_time)
        ]
        if match_activity:
            gap_candidates = gap_candidates[gap_candidates['tasks'] == match_activity]
        if gap_candidates.empty:
            return False, None, 'Gap not found for update'

        gap_row_idx = gap_candidates.index[0]

        if new_start is not None:
            df.at[gap_row_idx, 'start_time'] = datetime.strptime(new_start, TIME_FORMAT).time()
        if new_end is not None:
            df.at[gap_row_idx, 'end_time'] = datetime.strptime(new_end, TIME_FORMAT).time()
        if new_activity is not None:
            df.at[gap_row_idx, 'tasks'] = new_activity
        normalized_gap_counts = _coerce_bool(new_counts_for_hours)
        if normalized_gap_counts is not None:
            df.at[gap_row_idx, 'counts_for_hours'] = normalized_gap_counts

        worker_rows = df[df['PPL'] == worker_name].to_dict('records')
        target_date = _get_staged_target_date() if use_staged else datetime.today().date()
        success, _, error = _replace_worker_schedule(
            modality,
            worker_name,
            worker_rows,
            use_staged=use_staged,
            target_date=target_date,
        )
        if not success:
            return False, None, error
        log_prefix = "STAGED: " if use_staged else ""
        selection_logger.info(
            f"{log_prefix}Updated gap ({match_start}-{match_end}) for {worker_name}"
        )
        return True, 'gap_updated', None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def update_gap_in_schedule(
    modality: str,
    row_index: int,
    gap_index: Optional[int],
    new_start: Optional[str],
    new_end: Optional[str],
    new_activity: Optional[str],
    use_staged: bool,
    new_counts_for_hours: Optional[bool] = None,
    gap_match: Optional[dict] = None,
) -> tuple:
    """Public wrapper for updating a gap in a schedule."""
    return _update_gap_in_schedule(
        modality,
        row_index,
        gap_index,
        new_start,
        new_end,
        new_activity,
        use_staged,
        new_counts_for_hours=new_counts_for_hours,
        gap_match=gap_match,
    )
