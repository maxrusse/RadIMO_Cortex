"""
File operations module for backup, restore, and data loading.

This module handles:
- DataFrame backup to JSON
- Loading staged/scheduled data files
- Data initialization from JSON
- File quarantine for corrupted files
"""
import os
import json
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from config import (
    allowed_modalities,
    APP_CONFIG,
    SKILL_COLUMNS,
    UPLOAD_FOLDER,
    SKILL_ROSTER_AUTO_IMPORT,
    selection_logger,
)
from lib.utils import (
    TIME_FORMAT,
    format_time_value,
    get_local_now,
    gap_row_mask,
    parse_time_range,
    calculate_shift_duration_hours,
    validate_excel_structure,
    normalize_skill_value,
    coerce_bool,
)
from data_manager.worker_management import (
    apply_skill_overrides,
    get_canonical_worker_id,
    get_merged_worker_roster,
    get_worker_skill_mod_combinations,
)
from state_manager import StateManager

# Get state references
_state = StateManager.get_instance()
lock = _state.lock
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data
staged_modality_data = _state.staged_modality_data
unified_schedule_paths = _state.unified_schedule_paths

_unified_load_state = {
    'live': False,
    'staged': False,
    'scheduled': False,
}


def _clear_staged_data_state() -> None:
    """Reset in-memory staged state before loading a snapshot from disk."""
    _unified_load_state['staged'] = False
    _unified_load_state['scheduled'] = False

    for mod in allowed_modalities:
        d = staged_modality_data[mod]
        d['working_hours_df'] = None
        d['total_work_hours'] = {}
        d['info_texts'] = []
        d['info_texts_by_skill'] = {}
        d['last_modified'] = None
        d['last_prepped_at'] = None
        d['last_prepped_by'] = None
        d['target_date'] = None


def _get_staged_target_date() -> Optional[date]:
    """Return the currently staged target date if all or one modality has it."""
    for mod in allowed_modalities:
        target_date = staged_modality_data.get(mod, {}).get('target_date')
        if isinstance(target_date, date):
            return target_date
        if isinstance(target_date, str):
            try:
                return date.fromisoformat(target_date)
            except ValueError:
                continue
    return None


def _get_staged_day_snapshot_path(target_date: date) -> str:
    """Return the per-day staged snapshot path for a prep date."""
    backup_dir = os.path.join(UPLOAD_FOLDER, "backups", "staged_days")
    return os.path.join(backup_dir, f"Cortex_ALL_staged_{target_date.isoformat()}.json")


def _get_staged_day_archive_path(target_date: date, suffix: str) -> str:
    """Return an archive copy path for a staged day snapshot."""
    backup_dir = os.path.join(UPLOAD_FOLDER, "backups", "staged_days")
    normalized_suffix = str(suffix or '').strip()
    if normalized_suffix and not normalized_suffix.startswith('_'):
        normalized_suffix = f"_{normalized_suffix}"
    return os.path.join(
        backup_dir,
        f"Cortex_ALL_staged_{target_date.isoformat()}{normalized_suffix}.json",
    )


def _write_payload_to_path(payload: dict, target_path: str, mode_label: str) -> None:
    """Write a unified backup payload to the requested path."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    selection_logger.info("Unified %s backup updated at %s", mode_label, target_path)


def archive_staged_day_snapshot(target_date: date, *, suffix: str = 'eod') -> Optional[str]:
    """Copy the dated staged snapshot to an archive path for later comparison."""
    source_path = _get_staged_day_snapshot_path(target_date)
    if not os.path.exists(source_path):
        return None
    archive_path = _get_staged_day_archive_path(target_date, suffix)
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    shutil.copy2(source_path, archive_path)
    selection_logger.info(
        "Archived staged day snapshot from %s to %s",
        source_path,
        archive_path,
    )
    return archive_path


def archive_live_day_snapshot(target_date: date, *, suffix: str = 'eod') -> Optional[str]:
    """Copy the current live unified schedule to a dated archive path."""
    source_path = unified_schedule_paths.get('live')
    if not source_path or not os.path.exists(source_path):
        return None
    archive_path = _get_staged_day_archive_path(target_date, suffix)
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    shutil.copy2(source_path, archive_path)
    selection_logger.info(
        "Archived live day snapshot from %s to %s",
        source_path,
        archive_path,
    )
    return archive_path


def apply_roster_overrides_to_schedule(df: pd.DataFrame, modality: str) -> pd.DataFrame:
    """Reapply roster skill constraints to a schedule DataFrame."""
    if df is None or df.empty or 'PPL' not in df.columns:
        return df

    def _get_override_value(normalized: str) -> str:
        return normalize_skill_value(normalized)

    skill_columns = [skill for skill in SKILL_COLUMNS if skill in df.columns]
    if not skill_columns:
        return df

    worker_roster = get_merged_worker_roster(APP_CONFIG)

    for idx, row in df.iterrows():
        canonical_id = get_canonical_worker_id(row.get('PPL'))
        roster_combinations = get_worker_skill_mod_combinations(canonical_id, worker_roster)
        overrides = {}
        training = coerce_bool(row.get('training'))
        if row.get('row_type') in {'gap', 'gap_segment'}:
            training = False
        elif training is None:
            training = True

        for skill in skill_columns:
            normalized = normalize_skill_value(row.get(skill))
            override_value = _get_override_value(normalized)
            overrides[f"{skill}_{modality}"] = override_value

        final_combinations = apply_skill_overrides(
            roster_combinations,
            overrides,
            training=training,
            ignore_zero_overrides=True,
            exclude_unprocessed_weighted=False,
        )

        for skill in skill_columns:
            key = f"{skill}_{modality}"
            if key in final_combinations:
                df.at[idx, skill] = final_combinations[key]

    return df


def _calculate_total_work_hours(df: pd.DataFrame) -> Dict[str, float]:
    """Calculate total work hours per worker from DataFrame."""
    if df is None or df.empty:
        return {}

    if 'shift_duration' not in df.columns:
        return {}

    if 'row_type' in df.columns:
        gap_mask = gap_row_mask(df)
        df = df[~gap_mask]
        if df.empty:
            return {}

    if 'counts_for_hours' in df.columns:
        # Default to True (count for hours) if value is missing
        hours_df = df[df['counts_for_hours'].fillna(True).astype(bool)]
    else:
        hours_df = df

    if hours_df.empty:
        return {}

    return hours_df.groupby('PPL')['shift_duration'].sum().to_dict()


def _load_dataframe_from_backup_payload(data: dict) -> pd.DataFrame:
    """Load a DataFrame from backup payload data."""
    df = pd.DataFrame(data.get('working_hours', []))

    if df.empty:
        return df

    if 'TIME' in df.columns:
        time_data = df['TIME'].apply(parse_time_range)
        df['start_time'] = time_data.apply(lambda x: x[0])
        df['end_time'] = time_data.apply(lambda x: x[1])
        df['shift_duration'] = df.apply(
            lambda row: calculate_shift_duration_hours(row['start_time'], row['end_time']),
            axis=1
        )

    if 'counts_for_hours' not in df.columns:
        df['counts_for_hours'] = True

    if 'row_type' not in df.columns:
        df['row_type'] = 'shift_segment'
    if 'training' not in df.columns:
        df['training'] = True
    df['training'] = df['training'].apply(coerce_bool)
    df.loc[df['training'].isna(), 'training'] = True
    gap_mask = gap_row_mask(df)
    df.loc[gap_mask, 'shift_duration'] = 0.0
    df.loc[gap_mask, 'training'] = False

    return df


def _build_dataframe_from_records(records: List[dict], modality: str, *, validate: bool) -> pd.DataFrame:
    """Build a schedule DataFrame from raw records."""
    df = pd.DataFrame(records)

    if df.empty:
        return df

    required_columns = ['PPL', 'TIME']
    if validate:
        valid, error_msg = validate_excel_structure(df, required_columns, SKILL_COLUMNS)
        if not valid:
            raise ValueError(error_msg)

    if 'Modifier' not in df.columns:
        df['Modifier'] = 1.0
    else:
        df['Modifier'] = (
            df['Modifier']
            .fillna(1.0)
            .astype(str)
            .str.replace(',', '.')
            .astype(float)
        )

    df['start_time'], df['end_time'] = zip(*df['TIME'].map(parse_time_range))

    for skill in SKILL_COLUMNS:
        if skill not in df.columns:
            df[skill] = 0
        df[skill] = df[skill].fillna(0).apply(normalize_skill_value)

    df = apply_roster_overrides_to_schedule(df, modality)

    df['shift_duration'] = df.apply(
        lambda row: calculate_shift_duration_hours(row['start_time'], row['end_time']),
        axis=1
    )

    if 'row_type' not in df.columns:
        df['row_type'] = 'shift_segment'
    if 'training' not in df.columns:
        df['training'] = True
    df['training'] = df['training'].apply(coerce_bool)
    df.loc[df['training'].isna(), 'training'] = True
    gap_mask = gap_row_mask(df)
    df.loc[gap_mask, 'training'] = False
    df.loc[gap_mask, 'shift_duration'] = 0.0

    col_order = ['PPL', 'row_type', 'training', 'Modifier', 'TIME', 'start_time', 'end_time', 'shift_duration', 'tasks', 'counts_for_hours']
    skill_cols = [skill for skill in SKILL_COLUMNS if skill in df.columns]
    col_order = col_order[:4] + skill_cols + col_order[4:]

    if 'tasks' not in df.columns:
        df['tasks'] = ''
    if 'counts_for_hours' not in df.columns:
        df['counts_for_hours'] = True

    return df[[col for col in col_order if col in df.columns]]


def _set_live_modality_data(modality: str, df: pd.DataFrame, info_texts: list, info_texts_by_skill: Optional[dict] = None) -> None:
    """Apply a DataFrame to live modality data structures."""
    from data_manager.worker_management import invalidate_work_hours_cache, auto_populate_skill_roster

    d = modality_data[modality]
    d['working_hours_df'] = df
    invalidate_work_hours_cache(modality)
    d['worker_modifiers'] = df.groupby('PPL')['Modifier'].first().to_dict() if not df.empty else {}
    d['total_work_hours'] = _calculate_total_work_hours(df)

    d['info_texts'] = info_texts or []
    d['info_texts_by_skill'] = info_texts_by_skill or {}

    if SKILL_ROSTER_AUTO_IMPORT and not df.empty:
        auto_populate_skill_roster({modality: df})


def _set_staged_modality_data(
    modality: str,
    df: pd.DataFrame,
    info_texts: list,
    info_texts_by_skill: Optional[dict] = None,
    *,
    last_modified: Optional[datetime] = None,
    last_prepped_at: Optional[str] = None,
    last_prepped_by: Optional[str] = None,
    target_date: Optional[date] = None,
) -> None:
    """Apply a DataFrame to staged modality data structures."""
    d = staged_modality_data[modality]
    d['working_hours_df'] = df
    d['total_work_hours'] = _calculate_total_work_hours(df)
    d['info_texts'] = info_texts or []
    d['info_texts_by_skill'] = info_texts_by_skill or {}
    d['last_modified'] = last_modified
    if last_prepped_at is not None:
        d['last_prepped_at'] = last_prepped_at
    if last_prepped_by is not None:
        d['last_prepped_by'] = last_prepped_by
    if target_date is not None:
        d['target_date'] = target_date


def _build_unified_payload(use_staged: bool) -> dict:
    """Build a unified backup payload for all modalities."""
    source = staged_modality_data if use_staged else modality_data
    working_hours = []
    info_texts = {}
    info_texts_by_skill = {}
    metadata = {}

    for mod, d in source.items():
        df = d.get('working_hours_df')
        if df is None or df.empty:
            info_texts[mod] = d.get('info_texts', [])
            info_texts_by_skill[mod] = d.get('info_texts_by_skill', {})
            metadata[mod] = {
                'last_modified': None,
                'last_prepped_at': d.get('last_prepped_at'),
                'last_prepped_by': d.get('last_prepped_by'),
                'target_date': d.get('target_date').isoformat() if d.get('target_date') else None,
            }
            continue

        export_df = df.copy()
        if 'TIME' not in export_df.columns and {'start_time', 'end_time'}.issubset(export_df.columns):
            export_df['TIME'] = (
                export_df['start_time'].apply(format_time_value) +
                '-' +
                export_df['end_time'].apply(format_time_value)
            )

        cols_to_backup = [
            col for col in export_df.columns
            if col not in ['start_time', 'end_time', 'shift_duration', 'canonical_id']
        ]
        export_df = export_df[cols_to_backup].copy()
        export_df['modality'] = mod

        working_hours.extend(export_df.to_dict(orient='records'))
        info_texts[mod] = d.get('info_texts', [])
        info_texts_by_skill[mod] = d.get('info_texts_by_skill', {})
        metadata[mod] = {
            'last_modified': d.get('last_modified').isoformat() if d.get('last_modified') else None,
            'last_prepped_at': d.get('last_prepped_at'),
            'last_prepped_by': d.get('last_prepped_by'),
            'target_date': d.get('target_date').isoformat() if d.get('target_date') else None,
        }

    return {
        'working_hours': working_hours,
        'info_texts': info_texts,
        'info_texts_by_skill': info_texts_by_skill,
        'metadata': metadata,
    }


def _write_unified_backup(use_staged: bool) -> None:
    """Write unified schedule backup for all modalities."""
    payload = _build_unified_payload(use_staged)
    if use_staged:
        staged_target_date = _get_staged_target_date()
        if staged_target_date is None:
            raise ValueError("Cannot write staged backup without a target date")
        target_path = _get_staged_day_snapshot_path(staged_target_date)
        mode_label = "staged day snapshot"
    else:
        target_path = unified_schedule_paths['live']
        mode_label = "live"
    _write_payload_to_path(payload, target_path, mode_label)


def _load_unified_backup(file_path: str, use_staged: bool) -> bool:
    """Load a unified backup file into per-modality state."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return False

    records = data.get('working_hours', [])
    info_texts = data.get('info_texts', {})
    info_texts_by_skill = data.get('info_texts_by_skill', {})
    metadata = data.get('metadata', {})
    top_level_target_date = None
    if isinstance(metadata, dict):
        raw_top_level_target_date = metadata.get('target_date')
        if raw_top_level_target_date:
            try:
                top_level_target_date = date.fromisoformat(raw_top_level_target_date)
            except ValueError:
                top_level_target_date = None
    df = pd.DataFrame(records)

    if df.empty and not info_texts and top_level_target_date is None:
        return False

    if 'modality' not in df.columns and not df.empty:
        raise ValueError(f"Unified schedule file missing modality column: {file_path}")

    last_modified = None
    try:
        last_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
    except OSError:
        last_modified = get_local_now()

    for mod in modality_data.keys():
        mod_df = df[df['modality'] == mod].copy() if not df.empty else pd.DataFrame()
        if not mod_df.empty:
            mod_df = mod_df.drop(columns=['modality'], errors='ignore')
            mod_df = _load_dataframe_from_backup_payload({'working_hours': mod_df.to_dict(orient='records')})
        if use_staged:
            mod_metadata = metadata.get(mod, {}) if isinstance(metadata, dict) else {}
            if not isinstance(mod_metadata, dict):
                mod_metadata = {}
            mod_last_modified = mod_metadata.get('last_modified')
            parsed_modified = last_modified
            if mod_last_modified:
                try:
                    parsed_modified = datetime.fromisoformat(mod_last_modified)
                except ValueError:
                    parsed_modified = last_modified
            target_date = top_level_target_date
            raw_target_date = mod_metadata.get('target_date')
            if raw_target_date:
                try:
                    target_date = date.fromisoformat(raw_target_date)
                except ValueError:
                    target_date = top_level_target_date
            _set_staged_modality_data(
                mod,
                mod_df,
                info_texts.get(mod, []),
                info_texts_by_skill.get(mod, {}),
                last_modified=parsed_modified,
                last_prepped_at=mod_metadata.get('last_prepped_at'),
                last_prepped_by=mod_metadata.get('last_prepped_by'),
                target_date=target_date,
            )
        else:
            _set_live_modality_data(mod, mod_df, info_texts.get(mod, []), info_texts_by_skill.get(mod, {}))

    return True


def _load_unified_scheduled_into_staged(file_path: str) -> bool:
    """Load unified scheduled file into staged modality data."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return False
    except Exception as exc:
        selection_logger.error("Error reading unified scheduled file for staged load: %s", exc)
        return False

    records = data.get('working_hours', [])
    info_texts = data.get('info_texts', {})
    info_texts_by_skill = data.get('info_texts_by_skill', {})
    metadata = data.get('metadata', {}) if isinstance(data, dict) else {}
    raw_target_date = metadata.get('target_date')
    target_date = None
    if raw_target_date:
        try:
            target_date = date.fromisoformat(raw_target_date)
        except ValueError:
            target_date = None
    df = pd.DataFrame(records)

    if df.empty and not info_texts and not target_date:
        return False

    if not df.empty and 'modality' not in df.columns:
        selection_logger.error("Unified scheduled file missing modality column: %s", file_path)
        return False

    try:
        last_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
    except OSError:
        last_modified = get_local_now()

    for mod in allowed_modalities:
        if df.empty:
            mod_df = pd.DataFrame()
        else:
            mod_df = df[df['modality'] == mod].copy()
            mod_df = mod_df.drop(columns=['modality'], errors='ignore')
            mod_df = _load_dataframe_from_backup_payload({'working_hours': mod_df.to_dict(orient='records')})
            mod_df = apply_roster_overrides_to_schedule(mod_df, mod)
        _set_staged_modality_data(
            mod,
            mod_df,
            info_texts.get(mod, []),
            info_texts_by_skill.get(mod, {}),
            last_modified=last_modified,
            target_date=target_date,
        )

    return True


def backup_dataframe(modality: str, use_staged: bool = False) -> None:
    """Backup DataFrame to JSON file."""
    d = staged_modality_data[modality] if use_staged else modality_data[modality]
    if d['working_hours_df'] is not None:
        try:
            if use_staged:
                d['last_modified'] = get_local_now()
                d['last_prepped_at'] = d['last_modified'].strftime('%d.%m.%Y %H:%M')

            payload = _build_unified_payload(use_staged)
            if use_staged:
                staged_target_date = _get_staged_target_date()
                if staged_target_date is not None:
                    day_target_path = _get_staged_day_snapshot_path(staged_target_date)
                    _write_payload_to_path(payload, day_target_path, "staged day snapshot")
            else:
                target_path = unified_schedule_paths['live']
                _write_payload_to_path(payload, target_path, "live")
        except Exception as e:
            mode_label = "staged" if use_staged else "live"
            selection_logger.error(f"Error backing up {mode_label} DataFrame for modality {modality}: {e}")


def persist_live_backup() -> None:
    """Persist the current live schedule snapshot for all modalities."""
    try:
        _write_unified_backup(use_staged=False)
    except Exception as exc:
        selection_logger.error("Error persisting unified live backup: %s", exc)


def load_staged_dataframe(modality: str, target_date: Optional[date] = None) -> bool:
    """
    Load a staged dataframe for a modality from the dated staged snapshot.

    Uses try/except instead of os.path.exists to prevent TOCTOU race conditions
    (file could be deleted between check and open).
    """
    if target_date is not None:
        if reload_staged_data_from_disk(target_date=target_date):
            return staged_modality_data[modality].get('working_hours_df') is not None

    return False


def reload_staged_data_from_disk(target_date: Optional[date] = None) -> bool:
    """Force a reload of staged schedule data from disk.

    Clears the in-memory staged state first so callers can prefer the persisted
    staged backup over any stale process-local cache.
    """
    _clear_staged_data_state()

    if target_date is None:
        return False

    candidate_paths = [_get_staged_day_snapshot_path(target_date)]

    for candidate_path in candidate_paths:
        try:
            if not _load_unified_backup(candidate_path, use_staged=True):
                continue
        except Exception:
            continue

        if target_date is not None:
            loaded_target = _get_staged_target_date()
            if loaded_target != target_date:
                _clear_staged_data_state()
                continue

        if target_date is not None:
            global_worker_data['last_preload_source'] = 'snapshot'
        return True

    return False


def quarantine_file(file_path: str, reason: str) -> Optional[str]:
    """
    Move a defective file to quarantine directory.

    Uses try/except instead of os.path.exists to prevent TOCTOU race condition
    (file could be deleted between check and move).
    """
    if not file_path:
        return None

    invalid_dir = Path(UPLOAD_FOLDER) / 'invalid'
    invalid_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    original = Path(file_path)
    target = invalid_dir / f"{original.stem}_{timestamp}{original.suffix or '.json'}"

    try:
        shutil.move(str(original), str(target))
        selection_logger.warning("Defekte Datei '%s' nach '%s' verschoben (%s)", file_path, target, reason)
        return str(target)
    except FileNotFoundError:
        # File was already deleted - not an error, just log and return
        selection_logger.debug("Datei '%s' existiert nicht mehr (bereits gelöscht)", file_path)
        return None
    except OSError as exc:
        selection_logger.warning("Datei '%s' konnte nicht verschoben werden (%s): %s", file_path, reason, exc)
        return None


def initialize_data(file_path: str, modality: str) -> None:
    """Initialize modality data from JSON file."""
    # Import here to avoid circular imports
    from data_manager.worker_management import (
        invalidate_work_hours_cache,
        auto_populate_skill_roster,
    )

    d = modality_data[modality]
    global_worker_data['assignments_per_mod'][modality] = {}

    with lock:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if 'working_hours' not in data:
                raise ValueError("'working_hours' key not found in JSON")

            df = _build_dataframe_from_records(data['working_hours'], modality, validate=True)

            d['working_hours_df'] = df
            # Invalidate work hours cache when data changes
            invalidate_work_hours_cache(modality)
            d['worker_modifiers'] = df.groupby('PPL')['Modifier'].first().to_dict() if not df.empty else {}
            d['total_work_hours'] = _calculate_total_work_hours(df)

            d['info_texts'] = data.get('info_texts', [])
            d['info_texts_by_skill'] = data.get('info_texts_by_skill', {})

            if SKILL_ROSTER_AUTO_IMPORT and not df.empty:
                auto_populate_skill_roster({modality: df})  # Returns tuple, ignore here

        except Exception as e:
            error_message = f"Fehler beim Laden der JSON-Datei für Modality '{modality}': {str(e)}"
            selection_logger.error(error_message)
            selection_logger.exception("Stack trace:")
            raise ValueError(error_message)


def initialize_data_from_unified(file_path: str, *, context: str = '') -> bool:
    """Initialize all modalities from a unified schedule JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return False
    except Exception as exc:
        selection_logger.error("Failed to read unified schedule file %s (%s): %s", file_path, context, exc)
        return False

    records = data.get('working_hours', [])
    info_texts = data.get('info_texts', {})
    info_texts_by_skill = data.get('info_texts_by_skill', {})

    df = pd.DataFrame(records)
    if df.empty and not info_texts:
        return False

    if 'modality' not in df.columns and not df.empty:
        selection_logger.error("Unified schedule missing modality column (%s)", file_path)
        return False

    with lock:
        for mod in allowed_modalities:
            mod_records = df[df['modality'] == mod].drop(columns=['modality'], errors='ignore')
            records_list = mod_records.to_dict(orient='records')
            try:
                mod_df = _build_dataframe_from_records(records_list, mod, validate=True)
            except Exception as exc:
                selection_logger.error("Failed to initialize modality %s from unified file (%s): %s", mod, context, exc)
                continue
            _set_live_modality_data(mod, mod_df, info_texts.get(mod, []), info_texts_by_skill.get(mod, {}))

    return True


def load_unified_live_backup(file_path: str) -> bool:
    """Load live data from unified backup file."""
    if _unified_load_state['live']:
        return True

    if _load_unified_backup(file_path, use_staged=False):
        _unified_load_state['live'] = True
        return True

    return False


def load_unified_scheduled_into_staged(file_path: str) -> bool:
    """Public wrapper to load unified scheduled data into staged state."""
    return _load_unified_scheduled_into_staged(file_path)


def write_unified_scheduled_file(modality_dfs: dict, *, target_date: Optional[date] = None) -> None:
    """Write unified scheduled file from modality DataFrames."""
    records = []
    info_texts = {}
    info_texts_by_skill = {}
    for mod, df in modality_dfs.items():
        if df is None or df.empty:
            continue
        export_df = df.copy()
        start_times = export_df['start_time'].apply(lambda value: value.strftime(TIME_FORMAT))
        end_times = export_df['end_time'].apply(lambda value: value.strftime(TIME_FORMAT))
        export_df['TIME'] = start_times + '-' + end_times

        cols_to_export = [
            col for col in export_df.columns
            if col not in ['start_time', 'end_time', 'shift_duration', 'canonical_id']
        ]
        export_df = export_df[cols_to_export]
        export_df['modality'] = mod
        records.extend(export_df.to_dict(orient='records'))
        info_texts[mod] = []
        info_texts_by_skill[mod] = {}

    payload = {
        'working_hours': records,
        'info_texts': info_texts,
        'info_texts_by_skill': info_texts_by_skill,
        'metadata': {
            'target_date': target_date.isoformat() if target_date else None,
        },
    }

    target_path = unified_schedule_paths['scheduled']
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    selection_logger.info("Unified scheduled file saved at %s", target_path)


def attempt_initialize_data(
    file_path: str,
    modality: str,
    *,
    remove_on_failure: bool = False,
    context: str = ''
) -> bool:
    """Attempt to initialize data with error handling."""
    try:
        initialize_data(file_path, modality)
        return True
    except Exception as exc:
        selection_logger.error(
            "Fehler beim Initialisieren der Datei %s für %s (%s): %s",
            file_path, modality, context or 'runtime', exc,
        )
        if remove_on_failure:
            quarantine_file(file_path, f"{context or 'runtime'}: {exc}")
        return False
