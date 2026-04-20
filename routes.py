"""Flask routes for the RadIMO Cortex app."""

from __future__ import annotations

# Standard library imports
import io
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from collections import deque
from typing import Any, Callable, Optional
import zipfile
import yaml

# Third-party imports
from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
import pandas as pd

# Local imports
from config import (
    APP_CONFIG,
    MODALITY_SETTINGS,
    SKILL_SETTINGS,
    allowed_modalities,
    SKILL_COLUMNS,
    SKILL_TEMPLATES,
    SPECIAL_TASKS,
    SPECIAL_TASKS_MAP,
    get_special_task_weight,
    get_skill_modality_weight,
    modality_labels,
    MASTER_CSV_PATH,
    UPLOAD_FOLDER,
    WORKER_SKILL_ROSTER_PATH,
    selection_logger,
    SKILL_ROSTER_AUTO_IMPORT,
    normalize_modality,
    normalize_skill,
    is_no_overflow,
    get_specialist_fallback_targets,
    is_strict_button_visible,
    is_special_task_strict_button_visible,
    reload_runtime_config,
    load_button_weights,
    save_button_weights
)
from lib import usage_logger
from lib.utils import (
    get_local_now,
    get_next_workday,
    get_weekday_name_german,
    format_time_value,
    build_worker_sort_key,
    normalize_skill_value,
    skill_value_to_numeric,
    skill_value_to_display,
    strip_builder_fields,
    coerce_bool,
)
from data_manager import (
    modality_data,
    staged_modality_data,
    global_worker_data,
    lock,
    save_state,
    get_canonical_worker_id,
    load_worker_skill_json,
    save_worker_skill_json,
    build_working_hours_from_medweb,
    build_valid_skills_map,
    build_worker_name_mapping,
    auto_populate_skill_roster,
    auto_populate_skill_roster_from_csv,
    get_missing_csv_worker_candidates,
    import_csv_worker_to_skill_roster,
    load_staged_dataframe,
    reload_staged_data_from_disk,
    backup_dataframe,
    persist_live_backup,
    initialize_data_from_unified,
    update_schedule_row,
    add_worker_to_schedule,
    delete_worker_from_schedule,
    replace_worker_schedule,
    add_gap_to_schedule,
    add_gap_to_schedule_batch,
    remove_gap_from_schedule,
    update_gap_in_schedule,
    preload_next_workday,
    extract_modalities_from_skill_overrides,
)
from data_manager.csv_parser import compute_time_ranges, parse_gap_times
from data_manager.worker_management import (
    apply_skill_overrides,
    expand_skill_overrides,
    get_all_workers_by_canonical_id,
    get_worker_skill_mod_combinations,
)
from state_manager import StateManager
from balancer import (
    get_next_available_worker,
    update_global_assignment,
    get_global_assignments,
    get_global_weighted_count,
    get_modality_weighted_count,
    calculate_global_work_hours_now,
    BALANCER_SETTINGS
)

# Create Blueprint
routes = Blueprint('routes', __name__)

LOG_ROOT = Path('logs')
LOG_SOURCE_DEFINITIONS: dict[str, dict[str, str]] = {
    'gunicorn': {
        'label': 'Gunicorn',
        'filename': 'gunicorn.log',
    },
    'selection': {
        'label': 'RadIMO',
        'filename': 'selection.log',
    },
    'flow': {
        'label': 'Flow balance',
        'filename': 'flow_balance.log',
    },
}
LOG_SOURCE_ALIASES = {
    'radimo': 'selection',
    'app': 'selection',
    'radimo-app': 'selection',
    'gunicorn-log': 'gunicorn',
    'selection-log': 'selection',
    'flow-log': 'flow',
}
FLOW_UNRESOLVED_TARGET = '__unresolved__'
FLOW_UNRESOLVED_LABEL = 'Other / unresolved generalist'
VALID_WORKER_THRESHOLD_HOURS = 1.0


def _build_task_roles() -> list[dict[str, Any]]:
    medweb_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
    task_roles = []
    for rule in medweb_rules:
        rule_type = rule.get('type', 'shift')
        hours_counting_config = APP_CONFIG.get('balancer', {}).get('hours_counting', {})
        if 'counts_for_hours' in rule:
            counts_for_hours = rule['counts_for_hours']
        elif rule_type == 'gap':
            counts_for_hours = hours_counting_config.get('gap_default', False)
        else:
            counts_for_hours = hours_counting_config.get('shift_default', True)

        skill_overrides = rule.get('skill_overrides', {})
        modalities_list = extract_modalities_from_skill_overrides(skill_overrides)
        task_roles.append({
            'name': rule.get('label', rule.get('match', '')),
            'type': rule_type,
            'modalities': modalities_list,
            'times': rule.get('times', {}),
            'gaps': rule.get('gaps', {}),
            'skill_overrides': skill_overrides,
            'modifier': rule.get('modifier', 1.0),
            'counts_for_hours': counts_for_hours,
            'allow_roster_exclusion_override': bool(rule.get('allow_roster_exclusion_override', False)),
        })
    return task_roles


def _get_task_role_by_name(task_name: str) -> Optional[dict[str, Any]]:
    normalized_name = str(task_name or '').strip()
    if not normalized_name:
        return None
    for task_role in _build_task_roles():
        if str(task_role.get('name', '')).strip() == normalized_name:
            return task_role
    return None


def _resolve_preview_target_date(use_staged: bool, payload: dict[str, Any]) -> date:
    if not use_staged:
        return get_local_now().date()

    raw_target_date = payload.get('target_date')
    if raw_target_date not in (None, ''):
        return date.fromisoformat(str(raw_target_date))

    current_target = _get_staged_target_date()
    if current_target is not None:
        return current_target
    return get_next_workday().date()


def _build_shift_skill_combinations(current_shift: dict[str, Any]) -> Optional[dict[str, Any]]:
    modalities_payload = (current_shift or {}).get('modalities') or {}
    if not isinstance(modalities_payload, dict) or not modalities_payload:
        return None

    combinations: dict[str, Any] = {}
    found_any = False
    for modality in allowed_modalities:
        mod_payload = modalities_payload.get(modality, {}) or {}
        skill_payload = mod_payload.get('skills', {}) or {}
        for skill in SKILL_COLUMNS:
            combo_key = f"{skill}_{modality}"
            if skill in skill_payload:
                combinations[combo_key] = normalize_skill_value(skill_payload.get(skill))
                found_any = True
    return combinations if found_any else None


def _combinations_to_modalities(combinations: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for modality in allowed_modalities:
        result[modality] = {}
        for skill in SKILL_COLUMNS:
            result[modality][skill] = skill_value_to_display(
                combinations.get(f"{skill}_{modality}", 0)
            )
    return result


def _resolve_task_preview(
    *,
    worker: str,
    task_name: str,
    training: Optional[bool],
    use_staged: bool,
    target_date: date,
    mode: str = 'new',
    current_shift: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    task_role = _get_task_role_by_name(task_name)
    if task_role is None:
        raise ValueError(f"Unknown task: {task_name}")

    is_gap = str(task_role.get('type', 'shift')).strip().lower() == 'gap'
    resolved_training = False if is_gap else bool(training if training is not None else True)
    modifier = 1.0 if is_gap else float(task_role.get('modifier', 1.0) or 1.0)
    counts_for_hours = bool(task_role.get('counts_for_hours', False if is_gap else True))

    if is_gap:
        gap_times = parse_gap_times(task_role.get('times', {}), get_weekday_name_german(target_date))
        start_time, end_time = gap_times[0] if gap_times else ('12:00', '13:00')
        if not gap_times:
            start_str, end_str = start_time, end_time
        else:
            start_str = start_time.strftime('%H:%M')
            end_str = end_time.strftime('%H:%M')
        excluded = {
            f"{skill}_{modality}": -1
            for modality in allowed_modalities
            for skill in SKILL_COLUMNS
        }
        skills_by_modality = _combinations_to_modalities(excluded)
        return {
            'task': task_name,
            'row_type': 'gap',
            'training': False,
            'modifier': modifier,
            'counts_for_hours': counts_for_hours,
            'start_time': start_str,
            'end_time': end_str,
            'base_skills_by_modality': skills_by_modality,
            'skills_by_modality': skills_by_modality,
        }

    roster = load_worker_skill_json() or {}
    canonical_id = get_canonical_worker_id(worker)
    roster_base = get_worker_skill_mod_combinations(canonical_id, roster)
    shift_base = _build_shift_skill_combinations(current_shift or {}) if mode == 'edit' else None
    base_combinations = dict(roster_base)
    if shift_base:
        base_combinations.update(shift_base)

    skill_overrides = task_role.get('skill_overrides', {}) or {}
    if not skill_overrides:
        raise ValueError(f"Task '{task_name}' has no skill_overrides configured")

    final_combinations = apply_skill_overrides(
        base_combinations,
        skill_overrides,
        training=resolved_training,
        allow_roster_exclusion_override=bool(task_role.get('allow_roster_exclusion_override', False)),
        exclude_unprocessed_weighted=mode != 'edit',
    )

    time_ranges = compute_time_ranges(
        pd.Series(dtype='object'),
        task_role,
        datetime.combine(target_date, datetime.min.time()),
        APP_CONFIG,
    )
    if time_ranges:
        start_time, end_time = time_ranges[0]
        start_str = start_time.strftime('%H:%M')
        end_str = end_time.strftime('%H:%M')
    else:
        start_str = '07:00'
        end_str = '15:00'

    expanded_overrides = expand_skill_overrides(skill_overrides)
    task_controlled_keys_by_modality: dict[str, list[str]] = {}
    for modality in allowed_modalities:
        task_controlled_keys_by_modality[modality] = sorted([
            key.split('_', 1)[0]
            for key in expanded_overrides
            if key.endswith(f"_{modality}")
        ])

    return {
        'task': task_name,
        'row_type': 'shift',
        'training': resolved_training,
        'modifier': modifier,
        'counts_for_hours': counts_for_hours,
        'start_time': start_str,
        'end_time': end_str,
        'base_skills_by_modality': _combinations_to_modalities(base_combinations),
        'skills_by_modality': _combinations_to_modalities(final_combinations),
        'task_controlled_keys_by_modality': task_controlled_keys_by_modality,
    }


def _handle_task_preview(use_staged: bool) -> Any:
    payload = request.get_json(silent=True) or {}
    worker = str(payload.get('worker') or '').strip()
    task_name = str(payload.get('task') or '').strip()
    mode = str(payload.get('mode') or 'new').strip().lower()
    if not worker:
        return jsonify({'error': 'Missing worker'}), 400
    if not task_name:
        return jsonify({'error': 'Missing task'}), 400

    target_date = None
    if use_staged:
        try:
            target_date = _resolve_preview_target_date(True, payload)
        except ValueError:
            return jsonify({'error': 'Invalid target_date. Use YYYY-MM-DD.'}), 400
    else:
        target_date = get_local_now().date()

    try:
        result = _resolve_task_preview(
            worker=worker,
            task_name=task_name,
            training=coerce_bool(payload.get('training')),
            use_staged=use_staged,
            target_date=target_date,
            mode=mode if mode in {'new', 'edit'} else 'new',
            current_shift=payload.get('current_shift') if isinstance(payload.get('current_shift'), dict) else None,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if use_staged:
        result['target_date'] = target_date.isoformat()
    return jsonify(result)
DEFAULT_LOG_SOURCES = ('gunicorn', 'selection')
MAX_LOG_TAIL_LINES = 50_000
ADMIN_FILE_BACKUP_DIR = Path(UPLOAD_FOLDER) / 'backups' / 'admin_files'
STAGED_DAY_DIR = Path(UPLOAD_FOLDER) / 'backups' / 'staged_days'
CONFIG_FILE_PATH = Path('config.yaml')
STAGED_DAY_FILENAME_RE = re.compile(
    r'^Cortex_ALL_staged_(?P<target_date>\d{4}-\d{2}-\d{2})(?P<suffix>(?:_[A-Za-z0-9-]+)*)\.json$'
)

# -----------------------------------------------------------
# Helpers for Routes
# -----------------------------------------------------------

def _file_stat_payload(path: Path) -> dict[str, Any]:
    exists = path.exists()
    stat_result = path.stat() if exists else None
    modified = None
    if exists and stat_result is not None:
        modified = datetime.fromtimestamp(stat_result.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    return {
        'path': str(path),
        'exists': exists,
        'size_bytes': stat_result.st_size if stat_result is not None else None,
        'modified': modified,
    }


def _get_current_staged_target_date() -> Optional[date]:
    for mod in allowed_modalities:
        raw_target = staged_modality_data.get(mod, {}).get('target_date')
        if isinstance(raw_target, date):
            return raw_target
        if isinstance(raw_target, str):
            try:
                return date.fromisoformat(raw_target)
            except ValueError:
                continue
    return None


def _parse_staged_day_filename(filename: str) -> dict[str, Any]:
    match = STAGED_DAY_FILENAME_RE.match(filename or '')
    if not match:
        raise ValueError('Invalid staged day filename')
    target_date = match.group('target_date')
    suffix = match.group('suffix') or ''
    return {
        'target_date': target_date,
        'suffix': suffix[1:] if suffix.startswith('_') else suffix,
        'is_canonical': suffix == '',
    }


def _list_staged_day_files() -> list[dict[str, Any]]:
    if not STAGED_DAY_DIR.exists():
        return []

    current_target = _get_current_staged_target_date()
    entries: list[dict[str, Any]] = []
    for path in sorted(STAGED_DAY_DIR.glob('Cortex_ALL_staged_*.json'), reverse=True):
        try:
            parsed = _parse_staged_day_filename(path.name)
        except ValueError:
            continue
        entries.append({
            'name': path.name,
            'target_date': parsed['target_date'],
            'suffix': parsed['suffix'],
            'is_canonical': parsed['is_canonical'],
            'is_current_target': bool(current_target and current_target.isoformat() == parsed['target_date']),
            'download_url': url_for('routes.admin_files_download', target='staged_day', name=path.name),
            **_file_stat_payload(path),
        })
    return entries


def _build_admin_files_manifest() -> dict[str, Any]:
    state = StateManager.get_instance()
    live_backup_path = Path(state.unified_schedule_paths['live'])
    staged_current_target = _get_current_staged_target_date()

    targets = [
        {
            'key': 'config',
            'label': 'Config YAML',
            'filename': CONFIG_FILE_PATH.name,
            'download_url': url_for('routes.admin_files_download', target='config'),
            **_file_stat_payload(CONFIG_FILE_PATH),
        },
        {
            'key': 'skill_roster',
            'label': 'Skill Roster JSON',
            'filename': Path(WORKER_SKILL_ROSTER_PATH).name,
            'download_url': url_for('routes.admin_files_download', target='skill_roster'),
            **_file_stat_payload(Path(WORKER_SKILL_ROSTER_PATH)),
        },
        {
            'key': 'live_backup',
            'label': 'Live Unified Backup',
            'filename': live_backup_path.name,
            'download_url': url_for('routes.admin_files_download', target='live_backup'),
            **_file_stat_payload(live_backup_path),
        },
    ]

    return {
        'targets': targets,
        'staged_days': _list_staged_day_files(),
        'current_staged_target_date': staged_current_target.isoformat() if staged_current_target else None,
    }


def _ensure_admin_file_backup_dir() -> None:
    ADMIN_FILE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_existing_file(target_path: Path, *, label: Optional[str] = None) -> Optional[Path]:
    if not target_path.exists():
        return None
    _ensure_admin_file_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_label = label or target_path.stem
    backup_path = ADMIN_FILE_BACKUP_DIR / f'{backup_label}_{timestamp}{target_path.suffix}'
    shutil.copy2(target_path, backup_path)
    return backup_path


def _validate_yaml_payload(raw_bytes: bytes) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(raw_bytes.decode('utf-8'))
    except Exception as exc:
        raise ValueError(f'Invalid YAML: {exc}') from exc
    if not isinstance(parsed, dict):
        raise ValueError('Config upload must contain a YAML mapping/object')
    return parsed


def _validate_skill_roster_payload(raw_bytes: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_bytes.decode('utf-8'))
    except Exception as exc:
        raise ValueError(f'Invalid JSON: {exc}') from exc
    if not isinstance(parsed, dict):
        raise ValueError('Skill roster upload must contain a JSON object')
    return parsed


def _validate_unified_backup_payload(raw_bytes: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_bytes.decode('utf-8'))
    except Exception as exc:
        raise ValueError(f'Invalid JSON: {exc}') from exc
    if not isinstance(parsed, dict):
        raise ValueError('Unified backup upload must contain a JSON object')
    working_hours = parsed.get('working_hours')
    if not isinstance(working_hours, list):
        raise ValueError("Unified backup must contain a 'working_hours' list")
    if working_hours and not all(isinstance(row, dict) for row in working_hours):
        raise ValueError('Unified backup working_hours must contain objects')
    if working_hours and any('modality' not in row for row in working_hours):
        raise ValueError("Unified backup working_hours rows must contain 'modality'")
    return parsed


def _replace_config_file(raw_bytes: bytes) -> dict[str, Any]:
    _validate_yaml_payload(raw_bytes)
    backup_path = _backup_existing_file(CONFIG_FILE_PATH, label='config')
    CONFIG_FILE_PATH.write_bytes(raw_bytes)
    reload_result = reload_runtime_config()
    return {
        'message': 'Config file replaced',
        'backup_path': str(backup_path) if backup_path else None,
        'reload': reload_result,
    }


def _replace_skill_roster_file(raw_bytes: bytes) -> dict[str, Any]:
    payload = _validate_skill_roster_payload(raw_bytes)
    if not save_worker_skill_json(payload, create_backup=True):
        raise ValueError('Failed to save skill roster')
    return {
        'message': 'Skill roster replaced',
    }


def _replace_live_backup_file(raw_bytes: bytes) -> dict[str, Any]:
    state = StateManager.get_instance()
    live_path = Path(state.unified_schedule_paths['live'])
    _validate_unified_backup_payload(raw_bytes)
    backup_path = _backup_existing_file(live_path, label='live_backup')
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_bytes(raw_bytes)
    if not initialize_data_from_unified(str(live_path), context='admin_file_upload'):
        raise ValueError('Live backup file replaced, but runtime reload failed')
    return {
        'message': 'Live backup replaced and reloaded',
        'backup_path': str(backup_path) if backup_path else None,
    }


def _replace_staged_day_file(raw_bytes: bytes, target_date_str: str) -> dict[str, Any]:
    parsed_target = date.fromisoformat(target_date_str)
    target_path = STAGED_DAY_DIR / f'Cortex_ALL_staged_{parsed_target.isoformat()}.json'
    _validate_unified_backup_payload(raw_bytes)
    backup_path = _backup_existing_file(target_path, label=f'staged_{parsed_target.isoformat()}')
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(raw_bytes)
    reloaded = False
    current_target = _get_current_staged_target_date()
    if current_target == parsed_target:
        reloaded = reload_staged_data_from_disk(target_date=parsed_target)
    return {
        'message': f'Staged day {parsed_target.isoformat()} replaced',
        'backup_path': str(backup_path) if backup_path else None,
        'reloaded': reloaded,
    }


def _restore_staged_day_file(source_name: str) -> dict[str, Any]:
    source_path = STAGED_DAY_DIR / Path(source_name).name
    if not source_path.exists():
        raise ValueError('Selected staged day snapshot does not exist')
    parsed = _parse_staged_day_filename(source_path.name)
    target_path = STAGED_DAY_DIR / f"Cortex_ALL_staged_{parsed['target_date']}.json"
    backup_path = _backup_existing_file(target_path, label=f"staged_{parsed['target_date']}")
    shutil.copy2(source_path, target_path)
    parsed_target = date.fromisoformat(parsed['target_date'])
    reloaded = False
    if _get_current_staged_target_date() == parsed_target:
        reloaded = reload_staged_data_from_disk(target_date=parsed_target)
    return {
        'message': f"Restored {source_path.name} to active staged snapshot for {parsed['target_date']}",
        'backup_path': str(backup_path) if backup_path else None,
        'reloaded': reloaded,
    }

def _modality_has_active_skills(mod_data: dict) -> bool:
    skills = (mod_data or {}).get('skills', {}) or {}
    for val in skills.values():
        if val is None:
            continue
        if str(val).strip() != '-1':
            return True
    return False


def _plan_modality_should_materialize(shift: dict, mod_data: dict, row_index: Any) -> bool:
    try:
        if row_index is not None and int(row_index) >= 0:
            return True
    except (TypeError, ValueError):
        pass
    explicit = coerce_bool((mod_data or {}).get('materialize'))
    if explicit is not None:
        return explicit
    explicit = coerce_bool((shift or {}).get('materialize'))
    return explicit is True


def _validate_modality(modality: str, data_store: dict) -> Optional[Any]:
    if modality not in data_store:
        return jsonify({'error': 'Invalid modality'}), 400
    return None


def _maybe_reload_runtime_config(*, manual: bool) -> Optional[str]:
    """Best-effort hot reload for config-only changes.

    Unsupported structural edits are ignored. Manual reload paths surface an
    info message; automatic morning/lazy paths keep quiet and continue with the
    current in-memory config.
    """
    outcome = reload_runtime_config()
    if outcome.get('applied'):
        return None

    info_message = (
        "Config changes requiring restart were ignored for this reload: "
        f"{outcome.get('message', 'unknown reason')}"
    )
    if manual:
        selection_logger.info(info_message)
        return info_message

    selection_logger.info(
        "Automatic config reload skipped; keeping current runtime config: %s",
        outcome.get('message', 'unknown reason'),
    )
    return None


def _build_rows_from_plan(worker: str, shifts: list, modality: str) -> list:
    rows = []
    for shift in shifts:
        row_type = shift.get('row_type')
        if row_type is None and shift.get('is_gap_entry'):
            row_type = 'gap_segment'
        row_type = row_type or 'shift_segment'
        is_gap_row = str(row_type).lower() in {'gap', 'gap_segment'}
        training = coerce_bool(shift.get('training'))
        if training is None:
            training = not is_gap_row
        if is_gap_row and shift.get('counts_for_hours') is None:
            shift['counts_for_hours'] = False

        modalities = shift.get('modalities') or {}
        if not modalities:
            continue

        for mod_key, mod_data in modalities.items():
            mod_key = (mod_key or '').lower()
            if mod_key and mod_key != modality:
                continue
            row_index = mod_data.get('row_index') if isinstance(mod_data, dict) else None
            if mod_data and not is_gap_row and not _modality_has_active_skills(mod_data) and not (
                _plan_modality_should_materialize(shift, mod_data, row_index)
            ):
                continue
            skills = mod_data.get('skills', {}) or {}
            if is_gap_row:
                skills = {skill: -1 for skill in SKILL_COLUMNS}

            rows.append(strip_builder_fields({
                'PPL': worker,
                'start_time': shift.get('start_time'),
                'end_time': shift.get('end_time'),
                'Modifier': shift.get('Modifier', shift.get('modifier', 1.0)),
                'counts_for_hours': shift.get('counts_for_hours', not is_gap_row),
                'tasks': shift.get('tasks', shift.get('task', '')),
                'row_type': 'gap' if is_gap_row else row_type,
                'training': training,
                **{skill: skills.get(skill) for skill in SKILL_COLUMNS if skill in skills},
            }))
    return rows


def _handle_update_row(use_staged: bool, log_message: Optional[str] = None) -> Any:
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    updates = data.get('updates', {})
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if snapshot_error:
        return snapshot_error

    data_store = staged_modality_data if use_staged else modality_data
    error = _validate_modality(modality, data_store)
    if error:
        return error

    success, result = update_schedule_row(modality, row_index, updates, use_staged=use_staged)

    if success:
        if log_message:
            selection_logger.info(log_message.format(modality=modality, row_index=row_index))
        # result is {'reindexed': bool} on success
        return jsonify({
            'success': True,
            'schedule_reindexed': result.get('reindexed', False),
            'snapshot_version': _get_snapshot_version(
                use_staged,
                target_date=target_date if use_staged else None,
            ),
        })
    return jsonify({'error': result}), 400


def _handle_apply_worker_plan(use_staged: bool) -> Any:
    data = request.json or {}
    worker = data.get('worker')
    shifts = data.get('shifts', [])
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    if not worker:
        return jsonify({'error': 'Missing worker'}), 400

    worker_revision_error = _check_worker_revision(
        data.get('worker_revision'),
        worker,
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if worker_revision_error:
        return worker_revision_error

    if data.get('worker_revision') in (None, ''):
        snapshot_error = _check_snapshot_version(
            data.get('snapshot_version'),
            use_staged,
            target_date=target_date if use_staged else None,
        )
        if snapshot_error:
            return snapshot_error

    errors = []
    for modality in allowed_modalities:
        rows = _build_rows_from_plan(worker, shifts, modality)

        success, result, error = replace_worker_schedule(modality, worker, rows, use_staged=use_staged)
        if not success:
            errors.append(f"{modality.upper()}: {error}")

    if errors:
        return jsonify({'error': '; '.join(errors)}), 400
    return jsonify({
        'success': True,
        'worker_revision': _get_worker_revision(worker, use_staged),
        'snapshot_version': _get_snapshot_version(
            use_staged,
            target_date=target_date if use_staged else None,
        ),
    })


def _handle_add_worker(
    use_staged: bool,
    post_success: Optional[Callable[[str, str], None]] = None,
) -> Any:
    data = request.json
    modality = data.get('modality')
    worker_data = data.get('worker_data', {})
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if snapshot_error:
        return snapshot_error

    data_store = staged_modality_data if use_staged else modality_data
    error = _validate_modality(modality, data_store)
    if error:
        return error

    ppl_name = worker_data.get('PPL', 'Neuer Worker (NW)')
    success, result, error = add_worker_to_schedule(modality, worker_data, use_staged=use_staged)

    if success:
        if post_success:
            post_success(modality, ppl_name)
        # result is {'row_index': int, 'reindexed': bool} on success
        return jsonify({
            'success': True,
            'row_index': result.get('row_index'),
            'schedule_reindexed': result.get('reindexed', False)
            ,
            'snapshot_version': _get_snapshot_version(
                use_staged,
                target_date=target_date if use_staged else None,
            ),
        })
    return jsonify({'error': error}), 400


def _handle_delete_worker(use_staged: bool, log_message: Optional[str] = None) -> Any:
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    verify_ppl = data.get('verify_ppl')
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if snapshot_error:
        return snapshot_error

    data_store = staged_modality_data if use_staged else modality_data
    error = _validate_modality(modality, data_store)
    if error:
        return error

    success, worker_name, error = delete_worker_from_schedule(
        modality, row_index, use_staged=use_staged, verify_ppl=verify_ppl
    )

    if success:
        if log_message:
            selection_logger.info(log_message.format(modality=modality, worker_name=worker_name))
        return jsonify({
            'success': True,
            'snapshot_version': _get_snapshot_version(
                use_staged,
                target_date=target_date if use_staged else None,
            ),
        })
    return jsonify({'error': error}), 400


def _parse_tasks(value: Any) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        return [task.strip() for task in value.split(',') if task.strip()]
    return []


def _get_counts_for_hours(row: pd.Series, has_column: bool) -> bool:
    if not has_column:
        return True
    value = row.get('counts_for_hours', True)
    if pd.isna(value):
        return True
    return bool(value)


def _df_to_api_response(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []

    data: list[dict[str, Any]] = []
    columns = df.columns
    has_counts_for_hours = 'counts_for_hours' in columns
    has_manual = 'is_manual' in columns
    has_row_type = 'row_type' in columns
    has_training = 'training' in columns
    for idx, row in df.iterrows():
        worker_data = {
            'row_index': int(idx),
            'PPL': row['PPL'],
            'start_time': format_time_value(row.get('start_time')),
            'end_time': format_time_value(row.get('end_time')),
            'Modifier': float(row.get('Modifier', 1.0)) if pd.notnull(row.get('Modifier')) else 1.0,
        }

        for skill in SKILL_COLUMNS:
            worker_data[skill] = skill_value_to_display(row.get(skill, None))

        worker_data['tasks'] = _parse_tasks(row.get('tasks', ''))
        worker_data['counts_for_hours'] = _get_counts_for_hours(row, has_counts_for_hours)
        worker_data['row_type'] = row.get('row_type', 'shift') if has_row_type else 'shift'
        if has_training:
            training_value = coerce_bool(row.get('training'))
            if training_value is not None:
                worker_data['training'] = training_value

        if has_manual:
            worker_data['is_manual'] = bool(row.get('is_manual', False))

        data.append(worker_data)

    return data


def _is_skill_visible_for_modality(skill_name: str, modality: str) -> bool:
    mod_config = MODALITY_SETTINGS.get(modality, {})
    mod_valid_skills = mod_config.get('valid_skills')
    mod_hidden_skills = set(mod_config.get('hidden_skills', []))
    if mod_valid_skills is not None and skill_name not in mod_valid_skills:
        return False
    if skill_name in mod_hidden_skills:
        return False

    skill_config = SKILL_SETTINGS.get(skill_name, {})
    skill_valid_mods = skill_config.get('valid_modalities')
    skill_hidden_mods = set(skill_config.get('hidden_modalities', []))
    if skill_valid_mods is not None and modality not in skill_valid_mods:
        return False
    if modality in skill_hidden_mods:
        return False
    return True


def _get_visible_skill_modality_keys() -> list[str]:
    keys: list[str] = []
    for skill_name in SKILL_COLUMNS:
        for modality in allowed_modalities:
            if _is_skill_visible_for_modality(skill_name, modality):
                keys.append(f"{skill_name}_{modality}")
    return keys


def _get_preferred_display_name(
    canonical_id: str,
    preferred_names: Optional[set[str]] = None,
) -> str:
    candidate_names = set(preferred_names or set())
    candidate_names.update(get_all_workers_by_canonical_id().get(canonical_id, []))
    if candidate_names:
        return max(candidate_names, key=len)
    return canonical_id


def _get_active_display_names_for_modality(modality: str) -> dict[str, str]:
    df = modality_data[modality].get('working_hours_df')
    names_by_canonical: dict[str, set[str]] = {}
    if df is not None and not df.empty and 'PPL' in df.columns:
        for raw_name in df['PPL'].dropna().astype(str).tolist():
            canonical_id = get_canonical_worker_id(raw_name)
            names_by_canonical.setdefault(canonical_id, set()).add(raw_name)
    return {
        canonical_id: _get_preferred_display_name(canonical_id, names)
        for canonical_id, names in names_by_canonical.items()
    }


def _build_combined_skill_counts_view() -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    names_by_canonical: dict[str, set[str]] = {}
    all_canonical_ids: set[str] = set()

    for modality in allowed_modalities:
        modality_display_names = _get_active_display_names_for_modality(modality)
        for canonical_id, display_name in modality_display_names.items():
            names_by_canonical.setdefault(canonical_id, set()).add(display_name)
        all_canonical_ids.update(modality_display_names.keys())
        all_canonical_ids.update(
            (global_worker_data.get('assignments_per_mod', {}).get(modality, {}) or {}).keys()
        )

    display_names = {
        canonical_id: _get_preferred_display_name(canonical_id, names_by_canonical.get(canonical_id))
        for canonical_id in all_canonical_ids
    }

    combined_counts = {skill: {} for skill in SKILL_COLUMNS}
    for canonical_id in all_canonical_ids:
        display_name = display_names[canonical_id]
        for skill in SKILL_COLUMNS:
            total = 0
            for modality in allowed_modalities:
                total += int(
                    (
                        global_worker_data.get('assignments_per_mod', {})
                        .get(modality, {})
                        .get(canonical_id, {})
                        .get(skill, 0)
                    )
                    or 0
                )
            combined_counts[skill][display_name] = total

    return combined_counts, display_names


def _resolve_flow_target_skill(candidate: dict[str, Any], assigned_skill: str) -> Optional[str]:
    assigned_skill = normalize_skill(assigned_skill)
    if assigned_skill in SKILL_COLUMNS:
        assigned_value = skill_value_to_numeric(candidate.get(assigned_skill))
        if assigned_value >= 1:
            return assigned_skill

    for skill_name in SKILL_COLUMNS:
        if skill_value_to_numeric(candidate.get(skill_name)) == 1:
            return skill_name

    return None


def _get_cross_pool_flow_weight(
    requested_skill: str,
    requested_modality: str,
    *,
    use_strict_weights: bool = False,
    work_amount: float = 1.0,
    weight_override: Optional[float] = None,
) -> float:
    base_weight = (
        weight_override
        if weight_override is not None
        else get_skill_modality_weight(requested_skill, requested_modality, strict=use_strict_weights)
    )
    try:
        return max(float(base_weight) * float(work_amount), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_flow_skill_key(raw_skill: Any) -> Optional[str]:
    skill = normalize_skill(raw_skill)
    if skill in SKILL_COLUMNS:
        return skill

    raw_text = str(raw_skill or '').strip().lower()
    if '_' in raw_text:
        maybe_skill = normalize_skill(raw_text.rsplit('_', 1)[0])
        if maybe_skill in SKILL_COLUMNS:
            return maybe_skill
    return None


def _normalize_flow_target_key(raw_skill: Any) -> Optional[str]:
    raw_text = str(raw_skill or '').strip()
    if raw_text == FLOW_UNRESOLVED_TARGET:
        return FLOW_UNRESOLVED_TARGET
    return _normalize_flow_skill_key(raw_skill)


def _record_cross_pool_flow(
    requested_skill: str,
    target_skill: Optional[str],
    amount: float,
) -> bool:
    requested_skill = normalize_skill(requested_skill)
    if requested_skill not in SKILL_COLUMNS:
        selection_logger.warning(
            "Skipping cross-pool flow tracking due to unknown requested skill: requested=%s target=%s",
            requested_skill,
            target_skill,
        )
        return False

    normalized_target = normalize_skill(target_skill) if target_skill else None
    if target_skill is None:
        normalized_target = FLOW_UNRESOLVED_TARGET
        selection_logger.info(
            "Cross-pool flow recorded with unresolved target skill: requested=%s",
            requested_skill,
        )
    elif normalized_target not in SKILL_COLUMNS:
        selection_logger.warning(
            "Skipping cross-pool flow tracking due to unknown target skill: requested=%s target=%s",
            requested_skill,
            normalized_target,
        )
        return False

    try:
        flow_amount = float(amount)
    except (TypeError, ValueError):
        return False

    if flow_amount <= 0 or requested_skill == normalized_target:
        return False

    flow_cross_pool = global_worker_data.setdefault('flow_cross_pool', {})
    requested_bucket = flow_cross_pool.setdefault(requested_skill, {})
    requested_bucket[normalized_target] = float(requested_bucket.get(normalized_target, 0.0)) + flow_amount
    return True


def _get_or_create_distribution_stats() -> dict[str, dict[str, float]]:
    stats = global_worker_data.get('distribution_stats')
    if not isinstance(stats, dict):
        stats = {}
        global_worker_data['distribution_stats'] = stats
    return stats


def _record_distribution_stats(
    *,
    requested_skill: str,
    flow_weight: float,
    overflowed: bool,
    unresolved: bool,
) -> bool:
    requested_skill = normalize_skill(requested_skill)
    if requested_skill not in SKILL_COLUMNS:
        return False
    try:
        normalized_weight = float(flow_weight)
    except (TypeError, ValueError):
        return False
    if normalized_weight <= 0:
        return False

    stats = _get_or_create_distribution_stats()
    bucket = stats.setdefault(requested_skill, {
        'requested_inflow_weight': 0.0,
        'requested_count': 0,
        'inflow_weight': 0.0,
        'overflow_weight': 0.0,
        'unresolved_weight': 0.0,
        'count': 0,
    })
    bucket['inflow_weight'] = float(bucket.get('inflow_weight', 0.0) or 0.0) + normalized_weight
    if overflowed:
        bucket['overflow_weight'] = float(bucket.get('overflow_weight', 0.0) or 0.0) + normalized_weight
    if unresolved:
        bucket['unresolved_weight'] = float(bucket.get('unresolved_weight', 0.0) or 0.0) + normalized_weight
    bucket['count'] = int(bucket.get('count', 0) or 0) + 1
    return True


def _record_distribution_request(
    *,
    requested_skill: str,
    request_weight: float,
) -> bool:
    requested_skill = normalize_skill(requested_skill)
    if requested_skill not in SKILL_COLUMNS:
        return False
    try:
        normalized_weight = float(request_weight)
    except (TypeError, ValueError):
        return False
    if normalized_weight <= 0:
        return False

    stats = _get_or_create_distribution_stats()
    bucket = stats.setdefault(requested_skill, {
        'requested_inflow_weight': 0.0,
        'requested_count': 0,
        'inflow_weight': 0.0,
        'overflow_weight': 0.0,
        'unresolved_weight': 0.0,
        'count': 0,
    })
    bucket['requested_inflow_weight'] = float(bucket.get('requested_inflow_weight', 0.0) or 0.0) + normalized_weight
    bucket['requested_count'] = int(bucket.get('requested_count', 0) or 0) + 1
    return True


def _record_recent_distribution(
    *,
    person: str,
    canonical_id: str,
    requested_skill: str,
    requested_modality: str,
    actual_skill: str,
    actual_modality: str,
    flow_weight: float,
    overflowed: bool,
    unresolved: bool,
    task_label: Optional[str],
) -> None:
    recent_events = global_worker_data.setdefault('recent_distributions', [])
    if not isinstance(recent_events, list):
        recent_events = []
        global_worker_data['recent_distributions'] = recent_events

    recent_events.append({
        'timestamp': get_local_now().isoformat(timespec='seconds'),
        'person': person,
        'canonical_id': canonical_id,
        'requested_skill': normalize_skill(requested_skill) or requested_skill,
        'requested_modality': normalize_modality(requested_modality) or requested_modality,
        'actual_skill': normalize_skill(actual_skill) or actual_skill,
        'actual_modality': normalize_modality(actual_modality) or actual_modality,
        'weight': round(float(flow_weight or 0.0), 4),
        'overflowed': bool(overflowed),
        'unresolved': bool(unresolved),
        'task_label': task_label or '',
    })


def _build_flow_balance_payload() -> dict[str, Any]:
    visible_skills = list(SKILL_COLUMNS) + [FLOW_UNRESOLVED_TARGET]
    skill_labels = {
        skill_name: SKILL_SETTINGS.get(skill_name, {}).get('label', skill_name)
        for skill_name in SKILL_COLUMNS
    }
    skill_labels[FLOW_UNRESOLVED_TARGET] = FLOW_UNRESOLVED_LABEL

    raw_flow = global_worker_data.get('flow_cross_pool', {}) or {}
    distribution_stats = global_worker_data.get('distribution_stats', {}) or {}
    out_totals: dict[str, float] = {skill: 0.0 for skill in visible_skills}
    in_totals: dict[str, float] = {skill: 0.0 for skill in visible_skills}
    out_by_skill: dict[str, list[dict[str, Any]]] = {skill: [] for skill in visible_skills}
    in_by_skill: dict[str, list[dict[str, Any]]] = {skill: [] for skill in visible_skills}
    links: list[dict[str, Any]] = []
    reverse_map: dict[str, dict[str, float]] = {}

    normalized_flow: dict[str, dict[str, float]] = {}
    for raw_requested, raw_targets in raw_flow.items():
        if not isinstance(raw_targets, dict):
            continue

        requested_skill = _normalize_flow_skill_key(raw_requested)
        if requested_skill not in skill_labels:
            continue

        requested_bucket = normalized_flow.setdefault(requested_skill, {})
        for raw_target, raw_amount in raw_targets.items():
            target_skill = _normalize_flow_target_key(raw_target)
            if target_skill not in skill_labels:
                continue
            try:
                amount = float(raw_amount)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            if requested_skill == target_skill:
                continue
            requested_bucket[target_skill] = requested_bucket.get(target_skill, 0.0) + amount

    for requested_skill, target_map in normalized_flow.items():
        for target_skill, amount in target_map.items():
            out_totals[requested_skill] += amount
            in_totals[target_skill] += amount
            reverse_bucket = reverse_map.setdefault(target_skill, {})
            reverse_bucket[requested_skill] = reverse_bucket.get(requested_skill, 0.0) + amount
            links.append({
                'from': requested_skill,
                'to': target_skill,
                'weight': round(amount, 2),
            })

    for requested_skill in visible_skills:
        rows = [
            {'to': target_skill, 'weight': round(amount, 2)}
            for target_skill, amount in normalized_flow.get(requested_skill, {}).items()
            if amount > 0
        ]
        rows.sort(key=lambda item: (-item['weight'], item['to']))
        out_by_skill[requested_skill] = rows

    for target_skill in visible_skills:
        rows = [
            {'from': source_skill, 'weight': round(amount, 2)}
            for source_skill, amount in reverse_map.get(target_skill, {}).items()
            if amount > 0
        ]
        rows.sort(key=lambda item: (-item['weight'], item['from']))
        in_by_skill[target_skill] = rows

    cross_pool_total = round(sum(out_totals.values()), 2)
    total_inflow_weight = round(
        sum(
            float((distribution_stats.get(skill, {}) or {}).get('requested_inflow_weight', 0.0) or 0.0)
            for skill in SKILL_COLUMNS
        ),
        2,
    )
    total_assigned_base_weight = round(
        sum(
            float((distribution_stats.get(skill, {}) or {}).get('inflow_weight', 0.0) or 0.0)
            for skill in SKILL_COLUMNS
        ),
        2,
    )
    unresolved_weight_total = round(
        sum(
            float((distribution_stats.get(skill, {}) or {}).get('unresolved_weight', 0.0) or 0.0)
            for skill in SKILL_COLUMNS
        ),
        2,
    )
    overflow_quote = round(cross_pool_total / total_inflow_weight, 4) if total_inflow_weight > 0 else 0.0
    unresolved_quote = round(unresolved_weight_total / cross_pool_total, 4) if cross_pool_total > 0 else 0.0
    by_requested_skill = {
        skill: {
            'requested_inflow_weight': round(float((distribution_stats.get(skill, {}) or {}).get('requested_inflow_weight', 0.0) or 0.0), 2),
            'requested_count': int((distribution_stats.get(skill, {}) or {}).get('requested_count', 0) or 0),
            'inflow_weight': round(float((distribution_stats.get(skill, {}) or {}).get('requested_inflow_weight', 0.0) or 0.0), 2),
            'assigned_base_weight': round(float((distribution_stats.get(skill, {}) or {}).get('inflow_weight', 0.0) or 0.0), 2),
            'overflow_weight': round(float((distribution_stats.get(skill, {}) or {}).get('overflow_weight', 0.0) or 0.0), 2),
            'unresolved_weight': round(float((distribution_stats.get(skill, {}) or {}).get('unresolved_weight', 0.0) or 0.0), 2),
            'count': int((distribution_stats.get(skill, {}) or {}).get('count', 0) or 0),
        }
        for skill in SKILL_COLUMNS
    }
    for skill_name, metrics in by_requested_skill.items():
        inflow = float(metrics.get('requested_inflow_weight', 0.0) or 0.0)
        overflow = float(metrics.get('overflow_weight', 0.0) or 0.0)
        unresolved = float(metrics.get('unresolved_weight', 0.0) or 0.0)
        metrics['overflow_quote'] = round(overflow / inflow, 4) if inflow > 0 else 0.0
        metrics['unresolved_quote'] = round(unresolved / overflow, 4) if overflow > 0 else 0.0

    return {
        'success': True,
        'skills': visible_skills,
        'skill_labels': skill_labels,
        'links': sorted(links, key=lambda item: (-item['weight'], item['from'], item['to'])),
        'out_by_skill': out_by_skill,
        'in_by_skill': in_by_skill,
        'totals': {
            skill: {
                'out_total': round(out_totals[skill], 2),
                'in_total': round(in_totals[skill], 2),
            }
            for skill in visible_skills
        },
        'grand_totals': {'cross_pool_total': cross_pool_total},
        'summary': {
            'total_inflow_weight': total_inflow_weight,
            'total_assigned_base_weight': total_assigned_base_weight,
            'overflow_weight_total': cross_pool_total,
            'overflow_quote': overflow_quote,
            'unresolved_weight_total': unresolved_weight_total,
            'unresolved_quote': unresolved_quote,
            'by_requested_skill': by_requested_skill,
        },
        'meta': {
            'window': 'since_daily_reset',
            'last_reset_date': (
                global_worker_data['last_reset_date'].isoformat()
                if global_worker_data.get('last_reset_date')
                else None
            ),
        },
    }


def _ensure_next_workday_preloaded() -> None:
    next_day = get_next_workday().date()
    with lock:
        staged_loaded = reload_staged_data_from_disk(target_date=next_day)
        staged_target_date = _get_staged_target_date() if staged_loaded else None
        if staged_target_date is not None:
            global_worker_data['last_preload_date'] = staged_target_date
            global_worker_data['last_preload_source'] = 'snapshot'
            save_state()
            return

    with lock:
        last_preload_date = global_worker_data.get('last_preload_date')
    if last_preload_date == next_day:
        return

    today = get_local_now().date()
    for modality in allowed_modalities:
        staged = staged_modality_data.get(modality, {})
        last_modified = staged.get('last_modified')
        if last_modified and last_modified.date() == today:
            return
    if not os.path.exists(MASTER_CSV_PATH):
        selection_logger.info(f"Lazy preload skipped: No master CSV at {MASTER_CSV_PATH}")
        return

    with lock:
        _maybe_reload_runtime_config(manual=False)

    selection_logger.info(f"Lazy preload triggered from {MASTER_CSV_PATH}")
    result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG)
    if not result.get('success'):
        selection_logger.error(f"Lazy preload failed: {result.get('message')}")
    else:
        with lock:
            global_worker_data['last_preload_date'] = next_day
            global_worker_data['last_preload_source'] = 'csv'
            save_state()


def _get_staged_target_date() -> Optional[date]:
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


def _get_snapshot_version_from_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        return str(os.stat(file_path).st_mtime_ns)
    except OSError:
        return None


def _resolve_snapshot_path(use_staged: bool, target_date: Optional[date] = None) -> Optional[str]:
    state = StateManager.get_instance()
    if use_staged:
        scheduled_path = Path(state.unified_schedule_paths['scheduled'])
        resolved_target = target_date or _get_staged_target_date() or get_next_workday().date()
        staged_path = scheduled_path.parent / 'staged_days' / f'Cortex_ALL_staged_{resolved_target.isoformat()}.json'
        return str(staged_path)

    live_path = Path(state.unified_schedule_paths['live'])
    return str(live_path) if live_path.exists() else str(live_path)


def _get_snapshot_version(use_staged: bool, target_date: Optional[date] = None) -> Optional[str]:
    return _get_snapshot_version_from_path(_resolve_snapshot_path(use_staged, target_date))


def _iter_worker_revision_rows(use_staged: bool) -> list[dict[str, Any]]:
    data_store = staged_modality_data if use_staged else modality_data
    rows: list[dict[str, Any]] = []
    for modality in allowed_modalities:
        df = data_store.get(modality, {}).get('working_hours_df')
        if df is None or df.empty or 'PPL' not in df.columns:
            continue
        columns = df.columns
        has_counts_for_hours = 'counts_for_hours' in columns
        has_row_type = 'row_type' in columns
        has_training = 'training' in columns
        has_manual = 'is_manual' in columns

        for _, row in df.iterrows():
            worker_name = str(row.get('PPL', '')).strip()
            if not worker_name:
                continue
            row_type = row.get('row_type', 'shift') if has_row_type else 'shift'
            normalized_row_type = str(row_type or 'shift').strip().lower()
            is_gap_row = normalized_row_type == 'gap'
            training_value = coerce_bool(row.get('training')) if has_training else None
            if training_value is None:
                training_value = not is_gap_row
            revision_row = {
                'worker': worker_name,
                'modality': modality,
                'start_time': format_time_value(row.get('start_time')),
                'end_time': format_time_value(row.get('end_time')),
                'Modifier': float(row.get('Modifier', 1.0)) if pd.notnull(row.get('Modifier')) else 1.0,
                'tasks': _parse_tasks(row.get('tasks', '')),
                'counts_for_hours': _get_counts_for_hours(row, has_counts_for_hours),
                'row_type': row_type,
                'training': training_value,
                'is_manual': bool(row.get('is_manual', False)) if has_manual else False,
            }
            for skill in SKILL_COLUMNS:
                revision_row[skill] = skill_value_to_display(row.get(skill, None))
            rows.append(revision_row)
    return rows


def _build_worker_revision_map(use_staged: bool) -> dict[str, str]:
    rows_by_worker: dict[str, list[dict[str, Any]]] = {}
    for row in _iter_worker_revision_rows(use_staged):
        worker = row.pop('worker')
        rows_by_worker.setdefault(worker, []).append(row)

    revisions: dict[str, str] = {}
    for worker, rows in rows_by_worker.items():
        canonical_rows = sorted(
            rows,
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True),
        )
        payload = json.dumps(canonical_rows, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        revisions[worker] = hashlib.sha1(payload.encode('utf-8')).hexdigest()
    return revisions


def _get_worker_revision(worker: str, use_staged: bool) -> str:
    worker_name = str(worker or '').strip()
    if not worker_name:
        return ''
    return _build_worker_revision_map(use_staged).get(worker_name, hashlib.sha1(b'[]').hexdigest())


def _ensure_snapshot_file(use_staged: bool, *, target_date: Optional[date] = None) -> Optional[str]:
    snapshot_version = _get_snapshot_version(use_staged, target_date)
    if snapshot_version is not None:
        return snapshot_version

    data_store = staged_modality_data if use_staged else modality_data
    for modality in allowed_modalities:
        if data_store.get(modality, {}).get('working_hours_df') is not None:
            backup_dataframe(modality, use_staged=use_staged)
            return _get_snapshot_version(use_staged, target_date)
    return None


def _parse_request_target_date(data: dict) -> tuple[Optional[date], Optional[Any]]:
    raw_target_date = (data or {}).get('target_date')
    if raw_target_date in (None, ''):
        return None, None
    try:
        return date.fromisoformat(str(raw_target_date)), None
    except ValueError:
        return None, (jsonify({'error': 'Invalid target_date. Use YYYY-MM-DD.'}), 400)


def _prepare_staged_mutation(data: dict) -> tuple[Optional[date], Optional[Any]]:
    target_date, error = _parse_request_target_date(data)
    if error:
        return None, error
    if target_date is None:
        target_date = _get_staged_target_date()
    if target_date is None:
        return None, None

    current_target = _get_staged_target_date()
    if current_target == target_date:
        return target_date, None
    if reload_staged_data_from_disk(target_date=target_date):
        return target_date, None
    return target_date, (
        jsonify({'error': f'Staged schedule for {target_date.isoformat()} is not loaded. Reload the selected date before saving.'}),
        409,
    )


def _check_snapshot_version(expected_version: Any, use_staged: bool, *, target_date: Optional[date] = None) -> Optional[Any]:
    expected = str(expected_version).strip() if expected_version not in (None, '') else None
    current_version = _get_snapshot_version(use_staged, target_date)
    if expected is None:
        if current_version is None:
            _ensure_snapshot_file(use_staged, target_date=target_date)
        return None

    if current_version is not None and expected != current_version:
        return jsonify({
            'error': 'This schedule was updated in another session. Reload before saving.',
            'snapshot_version': current_version,
        }), 409
    return None


def _check_worker_revision(expected_revision: Any, worker: str, use_staged: bool, *, target_date: Optional[date] = None) -> Optional[Any]:
    expected = str(expected_revision).strip() if expected_revision not in (None, '') else None
    if expected is None:
        return None

    current_revision = _get_worker_revision(worker, use_staged)
    if expected != current_revision:
        return jsonify({
            'error': f'{worker} was updated in another session. Reload before saving.',
            'worker_revision': current_revision,
            'worker': worker,
            'snapshot_version': _get_snapshot_version(use_staged, target_date),
        }), 409
    return None


def _format_prep_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%d.%m.%Y %H:%M')
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return datetime.fromisoformat(candidate).strftime('%d.%m.%Y %H:%M')
        except ValueError:
            return candidate
    return str(value)


def _get_prep_last_edit_label() -> str:
    if not allowed_modalities:
        return ''

    staged = staged_modality_data.get(allowed_modalities[0], {})
    last_modified = _format_prep_timestamp(staged.get('last_modified'))
    if last_modified:
        return last_modified

    last_prepped_at = _format_prep_timestamp(staged.get('last_prepped_at'))
    if last_prepped_at:
        return last_prepped_at

    return ''


def _format_prep_loaded_label(target_date_value: date) -> str:
    return f"{get_weekday_name_german(target_date_value)} ({target_date_value.strftime('%d.%m.%Y')})"


def resolve_modality_from_request() -> str:
    return normalize_modality(request.values.get('modality'))


def get_admin_password() -> str:
    """Get the admin password from config."""
    return APP_CONFIG.get("admin_password", "")


def get_access_password() -> str:
    """Get the basic access password from config."""
    return APP_CONFIG.get("access_password", "change_easy_pw")


def is_access_protection_enabled() -> bool:
    """Check if basic access protection is enabled."""
    return APP_CONFIG.get("access_protection_enabled")


def is_admin_protection_enabled() -> bool:
    """Check if admin access protection is enabled."""
    return APP_CONFIG.get("admin_access_protection_enabled")


def has_admin_access() -> bool:
    """Determine if the current session has admin access."""
    if not is_admin_protection_enabled():
        return True
    return session.get('admin_logged_in', False)


def has_basic_access() -> bool:
    """Determine if the current session has basic access (but not admin)."""
    return session.get('access_granted', False) and not session.get('admin_logged_in', False)


def is_authenticated() -> bool:
    """Check if user has any form of authentication (admin or basic)."""
    return session.get('admin_logged_in', False) or session.get('access_granted', False)


def access_required(f: Callable) -> Callable:
    """Decorator that requires basic access authentication for non-admin pages.

    Uses a long-lived session cookie so users don't need to re-login frequently.
    Admin login also grants basic access.
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        # Skip if access protection is disabled
        if not is_access_protection_enabled():
            return f(*args, **kwargs)
        # Admin login also grants access
        if session.get('admin_logged_in') or session.get('access_granted'):
            return f(*args, **kwargs)
        modality = resolve_modality_from_request()
        return redirect(url_for('routes.access_login', modality=modality))
    return decorated


def admin_required(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not has_admin_access():
            modality = resolve_modality_from_request()
            return redirect(url_for('routes.login', modality=modality))
        return f(*args, **kwargs)
    return decorated


def _build_health_payload() -> dict[str, Any]:
    return {
        'status': 'ok',
        'service': 'RadIMO Cortex',
        'timestamp': get_local_now().isoformat(),
    }


def _evaluate_readiness(results: list[dict[str, Any]]) -> tuple[str, int]:
    has_error = any((str(item.get('status', '')).upper() == 'ERROR') for item in results)
    if has_error:
        return 'not_ready', 503
    return 'ready', 200


def _build_readiness_payload(context: str = 'readyz', include_results: bool = True) -> tuple[dict[str, Any], int]:
    try:
        checks = run_operational_checks(context=context, force=True)
        results = checks.get('results', [])
    except Exception as e:
        fallback = [{
            'name': 'Operational Checks',
            'status': 'ERROR',
            'detail': f'Failed to run operational checks: {str(e)}',
        }]
        return {
            'status': 'not_ready',
            'service': 'RadIMO Cortex',
            'timestamp': get_local_now().isoformat(),
            'summary': {'ok': 0, 'warning': 0, 'error': 1},
            'checks': fallback,
        }, 503

    readiness_status, http_status = _evaluate_readiness(results)
    summary = {'ok': 0, 'warning': 0, 'error': 0}
    for item in results:
        status = str(item.get('status', '')).upper()
        if status == 'OK':
            summary['ok'] += 1
        elif status == 'WARNING':
            summary['warning'] += 1
        elif status == 'ERROR':
            summary['error'] += 1

    payload: dict[str, Any] = {
        'status': readiness_status,
        'service': 'RadIMO Cortex',
        'timestamp': checks.get('timestamp', get_local_now().isoformat()),
        'summary': summary,
    }
    if include_results:
        payload['checks'] = results
    return payload, http_status


def _build_probe_badge_context() -> dict[str, Any]:
    admin_template_endpoints = {
        'routes.upload_file',
        'routes.admin_files_page',
        'routes.skill_roster_page',
        'routes.button_weights_page',
        'routes.prep_today',
        'routes.prep_tomorrow',
        'routes.worker_load_monitor',
    }
    show_badges = (
        request.endpoint in {'routes.login', 'routes.access_login'}
        or request.endpoint in admin_template_endpoints
        or bool(session.get('admin_logged_in'))
    )
    badge_context: dict[str, Any] = {
        'show_probe_badges': show_badges,
        'health_badge_status': 'unknown',
        'health_badge_text': 'Unknown',
        'ready_badge_status': 'unknown',
        'ready_badge_text': 'Unknown',
    }
    if not show_badges:
        return badge_context

    badge_context['health_badge_status'] = 'ok'
    badge_context['health_badge_text'] = 'Healthy'
    _, readiness_http = _build_readiness_payload(context='header_badge', include_results=False)
    badge_context['ready_badge_status'] = 'ok' if readiness_http == 200 else 'error'
    badge_context['ready_badge_text'] = 'Ready' if readiness_http == 200 else 'Not Ready'
    return badge_context


def _normalize_log_sources(raw_sources: str | None) -> list[str]:
    if not raw_sources:
        return list(DEFAULT_LOG_SOURCES)

    tokens = [token.strip().lower() for token in re.split(r'[\s,]+', raw_sources) if token.strip()]
    if not tokens:
        return list(DEFAULT_LOG_SOURCES)

    if any(token == 'all' for token in tokens):
        return list(LOG_SOURCE_DEFINITIONS.keys())

    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        source_key = LOG_SOURCE_ALIASES.get(token, token)
        if source_key not in LOG_SOURCE_DEFINITIONS:
            raise ValueError(f'Unknown log source: {token}')
        if source_key in seen:
            continue
        seen.add(source_key)
        normalized.append(source_key)
    return normalized or list(DEFAULT_LOG_SOURCES)


def _log_path(source_key: str) -> Path:
    return LOG_ROOT / LOG_SOURCE_DEFINITIONS[source_key]['filename']


def _rotated_log_paths(base_path: Path) -> list[Path]:
    if not base_path.exists():
        return []

    paths = [base_path]
    stem_prefix = f"{base_path.name}."
    rotated: list[tuple[int, Path]] = []
    for candidate in base_path.parent.glob(f"{base_path.name}.*"):
        suffix = candidate.name[len(stem_prefix):]
        if suffix.isdigit():
            rotated.append((int(suffix), candidate))

    rotated.sort(key=lambda item: item[0])
    paths.extend(path for _, path in rotated)
    return paths


def _read_tail_text(path: Path, lines: int) -> str:
    line_count = max(1, min(int(lines), MAX_LOG_TAIL_LINES))
    with path.open('r', encoding='utf-8', errors='replace') as handle:
        return ''.join(deque(handle, maxlen=line_count))


def _build_logs_archive_payload(source_keys: list[str], scope: str, lines: int) -> tuple[io.BytesIO, str]:
    buffer = io.BytesIO()
    archive_name = f"radimo-logs-{scope}-{get_local_now().strftime('%Y%m%d-%H%M%S')}.zip"

    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for source_key in source_keys:
            meta = LOG_SOURCE_DEFINITIONS[source_key]
            base_path = _log_path(source_key)

            if scope == 'tail':
                if base_path.exists():
                    tail_name = f"{source_key}/{base_path.name}.tail.log"
                    archive.writestr(tail_name, _read_tail_text(base_path, lines))
                else:
                    archive.writestr(
                        f"{source_key}/MISSING.txt",
                        f'{meta["label"]} log file not found at {base_path}\n',
                    )
                continue

            rotated_paths = _rotated_log_paths(base_path)
            if not rotated_paths:
                archive.writestr(
                    f"{source_key}/MISSING.txt",
                    f'{meta["label"]} log file not found at {base_path}\n',
                )
                continue

            for log_path in rotated_paths:
                archive.write(log_path, arcname=f"{source_key}/{log_path.name}")

    buffer.seek(0)
    return buffer, archive_name


# -----------------------------------------------------------
# Route Definitions
# -----------------------------------------------------------

@routes.context_processor
def inject_modality_settings() -> dict[str, Any]:
    context = {
        'modalities': MODALITY_SETTINGS,
        'modality_order': allowed_modalities,
        'modality_labels': modality_labels,
        'skill_definitions': SKILL_TEMPLATES,
        'skill_order': SKILL_COLUMNS,
        'skill_labels': {s['name']: s['label'] for s in SKILL_TEMPLATES},
        'special_tasks': SPECIAL_TASKS,
        # Auth state for templates
        'is_access_protection_enabled': is_access_protection_enabled(),
        'is_admin_protection_enabled': is_admin_protection_enabled(),
        'has_basic_access': has_basic_access(),
        'is_authenticated': is_authenticated(),
    }
    context.update(_build_probe_badge_context())
    return context

@routes.route('/')
@access_required
def index() -> Any:
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    modality_config = MODALITY_SETTINGS.get(modality, {})
    mod_valid_skills = set(modality_config.get('valid_skills', SKILL_COLUMNS))
    mod_hidden_skills = set(modality_config.get('hidden_skills', []))

    visible_skills = []
    for skill_name in SKILL_COLUMNS:
        if skill_name not in mod_valid_skills or skill_name in mod_hidden_skills:
            continue
        skill_config = SKILL_SETTINGS.get(skill_name, {})
        skill_valid_mods = skill_config.get('valid_modalities')
        skill_hidden_mods = set(skill_config.get('hidden_modalities', []))
        if skill_valid_mods is not None and modality not in skill_valid_mods:
            continue
        if modality in skill_hidden_mods:
            continue
        visible_skills.append(skill_name)

    visible_special_tasks = [
        {
            **task,
            'show_strict_button': is_special_task_strict_button_visible(task['slug'], modality),
        }
        for task in SPECIAL_TASKS
        if modality in task['modalities_dashboards']
    ]
    regular_strict_button_skills = [
        skill_name for skill_name in visible_skills
        if is_strict_button_visible(skill_name, modality)
    ]
    dashboard_buttons = sorted(
        [
            {
                'button_type': 'skill',
                'name': skill['name'],
                'slug': skill['slug'],
                'label': skill['label'],
                'tooltip': skill.get('tooltip', skill['label']),
                'special': skill.get('special', False),
                'display_order': skill.get('display_order', 999),
                'show_strict_button': skill['name'] in regular_strict_button_skills,
            }
            for skill in SKILL_TEMPLATES
            if skill['name'] in visible_skills
        ] + [
            {
                **task,
                'button_type': 'special_task',
            }
            for task in visible_special_tasks
        ],
        key=lambda item: (item.get('display_order', 999), item.get('label', ''))
    )

    return render_template(
        'index.html',
        info_texts=d.get('info_texts', []),
        modality=modality,
        visible_skills=visible_skills,
        regular_strict_button_skills=regular_strict_button_skills,
        dashboard_buttons=dashboard_buttons,
        special_tasks=visible_special_tasks,
        is_admin=has_admin_access()
    )

@routes.route('/by-skill')
@access_required
def index_by_skill() -> Any:
    skill = request.args.get('skill', SKILL_COLUMNS[0] if SKILL_COLUMNS else 'Notfall')
    skill = normalize_skill(skill)

    skill_config = SKILL_SETTINGS.get(skill, {})
    skill_valid_mods = skill_config.get('valid_modalities')
    skill_hidden_mods = set(skill_config.get('hidden_modalities', []))

    visible_modalities = []
    for mod in allowed_modalities:
        if skill_valid_mods is not None and mod not in skill_valid_mods:
            continue
        if mod in skill_hidden_mods:
            continue
        mod_config = MODALITY_SETTINGS.get(mod, {})
        mod_valid_skills = mod_config.get('valid_skills')
        mod_hidden_skills = set(mod_config.get('hidden_skills', []))
        if mod_valid_skills is not None and skill not in mod_valid_skills:
            continue
        if skill in mod_hidden_skills:
            continue
        visible_modalities.append(mod)

    special_task_buttons = []
    for task in SPECIAL_TASKS:
        if task['base_skill'] != skill:
            continue
        if skill not in task.get('skill_dashboards', []):
            continue
        # Tasks on skill dashboards just use their label
        task_mods = task.get('modalities_dashboards', [])
        if task_mods:
            # Add button for each visible modality
            for mod in task_mods:
                if mod not in visible_modalities:
                    continue
                special_task_buttons.append({
                    'modality': mod,
                    'label': task.get('label', task['name']),
                    'tooltip': task.get('tooltip', task.get('label', task['name'])),
                    'slug': task['slug'],
                    'button_color': task.get('button_color', '#004892'),
                    'text_color': task.get('text_color', '#ffffff'),
                    'show_strict_button': is_special_task_strict_button_visible(task['slug'], mod),
                })
        else:
            # No modality_dashboards - use first target modality or first visible modality
            target_mods = task.get('target_skill_modalities', [])
            if target_mods:
                # Use first modality from target_skill_modalities
                default_mod = target_mods[0][1] if target_mods[0] else None
            else:
                default_mod = visible_modalities[0] if visible_modalities else None
            special_task_buttons.append({
                'modality': default_mod,
                'label': task.get('label', task['name']),
                'tooltip': task.get('tooltip', task.get('label', task['name'])),
                'slug': task['slug'],
                'button_color': task.get('button_color', '#004892'),
                'text_color': task.get('text_color', '#ffffff'),
                'show_strict_button': (
                    is_special_task_strict_button_visible(task['slug'], default_mod)
                    if default_mod else False
                ),
            })

    default_info_modality = visible_modalities[0] if visible_modalities else (allowed_modalities[0] if allowed_modalities else '')
    info_texts_by_modality = {}
    for mod in allowed_modalities:
        mod_data = modality_data[mod]
        by_skill = mod_data.get('info_texts_by_skill') or {}
        info_texts_by_modality[mod] = by_skill.get(skill, [])
    info_texts = info_texts_by_modality.get(default_info_modality, [])
    regular_strict_button_modalities = [
        mod for mod in visible_modalities
        if is_strict_button_visible(skill, mod)
    ]

    return render_template(
        'index_by_skill.html',
        skill=skill,
        visible_modalities=visible_modalities,
        regular_strict_button_modalities=regular_strict_button_modalities,
        special_task_buttons=special_task_buttons,
        info_texts=info_texts,
        info_texts_by_modality=info_texts_by_modality,
        default_info_modality=default_info_modality,
        is_admin=has_admin_access()
    )

@routes.route('/timetable')
@access_required
def timetable() -> Any:
    modality = request.args.get('modality', 'all')
    skill_filter = request.args.get('skill', 'all')

    data_by_modality: dict[str, list[dict[str, Any]]] = {}
    target_modalities = allowed_modalities if modality == 'all' else [modality]
    for mod in target_modalities:
        df = modality_data[mod]['working_hours_df']
        if df is not None:
            temp_df = df.copy()
            temp_df['_modality'] = mod
            data_by_modality[mod] = _df_to_api_response(temp_df)
        else:
            data_by_modality[mod] = []

    task_roles = _build_task_roles()

    worker_skills = load_worker_skill_json()
    target_weekday_name = get_weekday_name_german(datetime.now().date())

    # Skill slug/color maps for the frontend
    skill_slug_map = {s['name']: s['slug'] for s in SKILL_TEMPLATES}
    skill_color_map = {s['slug']: s['button_color'] for s in SKILL_TEMPLATES}
    modality_color_map = {mod: settings.get('nav_color', '#004892') for mod, settings in MODALITY_SETTINGS.items()}

    return render_template(
        'timetable.html',
        modality=modality,
        skill_filter=skill_filter,
        debug_data=json.dumps(data_by_modality),
        skill_columns=SKILL_COLUMNS,
        skill_slug_map=skill_slug_map,
        skill_color_map=skill_color_map,
        modality_color_map=modality_color_map,
        task_roles=task_roles,
        worker_skills=worker_skills,
        target_weekday_name=target_weekday_name,
        is_admin=has_admin_access()
    )

@routes.route('/skill-roster')
@admin_required
def skill_roster_page() -> Any:
    valid_skills_map = build_valid_skills_map()
    default_w_modifier = BALANCER_SETTINGS.get('default_w_modifier', 1.0)
    modality = resolve_modality_from_request()
    return render_template(
        'skill_roster.html',
        modality=modality,
        valid_skills_map=valid_skills_map,
        default_w_modifier=default_w_modifier,
        is_admin=True
    )

@routes.route('/button-weights')
@admin_required
def button_weights_page() -> Any:
    modality = resolve_modality_from_request()
    valid_skills_map = build_valid_skills_map()
    return render_template('button_weights.html', modality=modality, valid_skills_map=valid_skills_map, is_admin=True)

@routes.route('/api/admin/button_weights', methods=['GET', 'POST'])
@admin_required
def button_weights_api() -> Any:
    if request.method == 'POST':
        data = request.json or {}
        weights = data.get('weights', {})
        if save_button_weights(weights):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to save button weights'}), 400

    weights = load_button_weights()
    return jsonify({
        'success': True,
        'weights': weights,
        'skills': SKILL_COLUMNS,
        'modalities': allowed_modalities,
        'special_tasks': SPECIAL_TASKS,
    })

@routes.route('/api/admin/skill_roster', methods=['GET', 'POST'])
@admin_required
def skill_roster_api() -> Any:
    if request.method == 'POST':
        data = request.json
        roster = data.get('roster')
        if roster is not None:
            save_worker_skill_json(roster)
            return jsonify({'success': True})
        return jsonify({'error': 'No roster data'}), 400
    
    roster = load_worker_skill_json()
    worker_names = build_worker_name_mapping(roster)
    csv_candidates = get_missing_csv_worker_candidates(MASTER_CSV_PATH, APP_CONFIG)
    return jsonify({
        'success': True,
        'roster': roster,
        'worker_names': worker_names,
        'skills': SKILL_COLUMNS,
        'modalities': allowed_modalities,
        'csv_candidates': csv_candidates,
    })

@routes.route('/api/admin/skill_roster/import_new', methods=['POST'])
@admin_required
def import_new_skill_roster_api() -> Any:
    added_count, added_workers = auto_populate_skill_roster_from_csv(MASTER_CSV_PATH, APP_CONFIG)
    return jsonify({
        'success': True,
        'added_count': added_count,
        'added_workers': added_workers
    })

@routes.route('/api/admin/skill_roster/import_csv_worker', methods=['POST'])
@admin_required
def import_csv_skill_roster_worker_api() -> Any:
    data = request.json or {}
    worker_id = str(data.get('worker_id', '')).strip()
    if not worker_id:
        return jsonify({'error': 'Missing worker_id'}), 400

    try:
        candidate = import_csv_worker_to_skill_roster(MASTER_CSV_PATH, APP_CONFIG, worker_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'success': True,
        'worker_id': candidate.get('worker_id', worker_id),
        'display_name': candidate.get('display_name', worker_id),
        'full_name': candidate.get('full_name', worker_id),
        'auto_import_eligible': candidate.get('auto_import_eligible', False),
        'source_activity': candidate.get('source_activity', ''),
        'source_date': candidate.get('source_date', ''),
    })

@routes.route('/login', methods=['GET', 'POST'])
def login() -> Any:
    modality = resolve_modality_from_request()
    error = None
    passwordless = not is_admin_protection_enabled()

    if request.method == 'POST':
        if passwordless:
            # No password required - just proceed
            return redirect(url_for('routes.prep_today'))
        pw = request.form.get('password', '')
        if pw == get_admin_password():
            session['admin_logged_in'] = True
            return redirect(url_for('routes.prep_today'))
        else:
            error = "Falsches Passwort"

    return render_template("login.html", error=error, modality=modality, login_type='admin', passwordless=passwordless)

@routes.route('/logout')
def logout() -> Any:
    """Smart logout that handles both admin and basic auth levels.

    - If admin: clears admin session, redirects to login page
    - If basic access only: clears basic access, redirects to access-login
    - Hierarchy: admin logout takes precedence
    """
    modality = resolve_modality_from_request()

    if session.get('admin_logged_in'):
        # Admin logout - clear admin session, go to login page
        session.pop('admin_logged_in', None)
        return redirect(url_for('routes.login', modality=modality))

    if session.get('access_granted'):
        # Basic access logout - clear access, go to access-login page
        session.pop('access_granted', None)
        return redirect(url_for('routes.access_login', modality=modality))

    # Not logged in at all - just go to index
    return redirect(url_for('routes.index', modality=modality))


@routes.route('/access-login', methods=['GET', 'POST'])
def access_login() -> Any:
    """Basic access login for non-admin pages.

    Uses a permanent session cookie for long-lived access.
    """
    modality = resolve_modality_from_request()
    passwordless = not is_access_protection_enabled()

    # If already authenticated (either as admin or with basic access), redirect to index
    if session.get('admin_logged_in') or session.get('access_granted'):
        return redirect(url_for('routes.index', modality=modality))

    error = None
    if request.method == 'POST':
        if passwordless:
            # No password required - just proceed
            return redirect(url_for('routes.index', modality=modality))
        pw = request.form.get('password', '')
        if pw == get_access_password():
            session.permanent = True  # Use permanent session for long-lived cookie
            session['access_granted'] = True
            return redirect(url_for('routes.index', modality=modality))
        else:
            error = "Falsches Passwort"

    return render_template("login.html", error=error, modality=modality, login_type='access', passwordless=passwordless)


@routes.route('/access-logout')
def access_logout() -> Any:
    """Logout from basic access (keeps admin session if present)."""
    session.pop('access_granted', None)
    modality = resolve_modality_from_request()
    return redirect(url_for('routes.access_login', modality=modality))


@routes.route('/healthz')
def healthz() -> Any:
    return jsonify(_build_health_payload()), 200


@routes.route('/readyz')
def readyz() -> Any:
    payload, http_status = _build_readiness_payload(context='readyz', include_results=True)
    return jsonify(payload), http_status


@routes.route('/status')
def status_page() -> Any:
    health_payload = _build_health_payload()
    readiness_payload, readiness_http_status = _build_readiness_payload(
        context='status_page',
        include_results=True,
    )
    return render_template(
        'status.html',
        health_payload=health_payload,
        readiness_payload=readiness_payload,
        readiness_http_status=readiness_http_status,
        modality=resolve_modality_from_request(),
        is_admin=has_admin_access(),
    )


@routes.route('/admin/logs')
@admin_required
def admin_logs_page() -> Any:
    """Admin page with direct links for log downloads."""
    sources = []
    for source_key, meta in LOG_SOURCE_DEFINITIONS.items():
        base_path = _log_path(source_key)
        sources.append({
            'key': source_key,
            'label': meta['label'],
            'filename': meta['filename'],
            'exists': base_path.exists(),
            'size_bytes': base_path.stat().st_size if base_path.exists() else None,
            'download_tail_url': url_for(
                'routes.download_logs',
                sources=source_key,
                scope='tail',
                lines=2000,
            ),
            'download_full_url': url_for(
                'routes.download_logs',
                sources=source_key,
                scope='full',
            ),
        })

    return render_template(
        'admin_logs.html',
        sources=sources,
        default_tail_url=url_for('routes.download_logs', sources='gunicorn,selection', scope='tail', lines=5000),
        default_full_url=url_for('routes.download_logs', sources='gunicorn,selection', scope='full'),
        is_admin=True,
        active_page='logs',
    )


@routes.route('/admin/logs/download', methods=['GET'])
@admin_required
def download_logs() -> Any:
    """Download RadIMO and Gunicorn logs as a zip archive."""
    try:
        source_keys = _normalize_log_sources(request.args.get('sources'))
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    scope = (request.args.get('scope') or 'tail').strip().lower()
    if scope not in {'tail', 'full'}:
        return jsonify({'success': False, 'error': 'scope must be tail or full'}), 400

    try:
        line_count = int(request.args.get('lines', '5000'))
    except ValueError:
        return jsonify({'success': False, 'error': 'lines must be an integer'}), 400

    line_count = max(1, min(line_count, MAX_LOG_TAIL_LINES))
    archive_buffer, archive_name = _build_logs_archive_payload(source_keys, scope, line_count)
    return send_file(
        archive_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=archive_name,
        max_age=0,
    )


@routes.route('/admin/files')
@admin_required
def admin_files_page() -> Any:
    return render_template(
        'admin_files.html',
        manifest=_build_admin_files_manifest(),
        is_admin=True,
        active_page='files',
    )


@routes.route('/api/admin/files/manifest', methods=['GET'])
@admin_required
def admin_files_manifest() -> Any:
    return jsonify({
        'success': True,
        'manifest': _build_admin_files_manifest(),
    })


@routes.route('/api/admin/files/download', methods=['GET'])
@admin_required
def admin_files_download() -> Any:
    target = (request.args.get('target') or '').strip().lower()
    if target == 'config':
        file_path = CONFIG_FILE_PATH
    elif target == 'skill_roster':
        file_path = Path(WORKER_SKILL_ROSTER_PATH)
    elif target == 'live_backup':
        file_path = Path(StateManager.get_instance().unified_schedule_paths['live'])
    elif target == 'staged_day':
        file_name = Path(request.args.get('name') or '').name
        if not file_name:
            return jsonify({'success': False, 'error': 'Missing staged day file name'}), 400
        file_path = STAGED_DAY_DIR / file_name
    else:
        return jsonify({'success': False, 'error': 'Unknown download target'}), 400

    if not file_path.exists():
        return jsonify({'success': False, 'error': 'Requested file does not exist'}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_path.name,
        max_age=0,
    )


@routes.route('/api/admin/files/upload', methods=['POST'])
@admin_required
def admin_files_upload() -> Any:
    target = (request.form.get('target') or '').strip().lower()
    uploaded_file = request.files.get('file')
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    raw_bytes = uploaded_file.read()
    if not raw_bytes:
        return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

    try:
        if target == 'config':
            result = _replace_config_file(raw_bytes)
        elif target == 'skill_roster':
            result = _replace_skill_roster_file(raw_bytes)
        elif target == 'live_backup':
            result = _replace_live_backup_file(raw_bytes)
        elif target == 'staged_day':
            target_date_str = (request.form.get('target_date') or '').strip()
            if not target_date_str:
                return jsonify({'success': False, 'error': 'Missing target_date for staged day upload'}), 400
            result = _replace_staged_day_file(raw_bytes, target_date_str)
        else:
            return jsonify({'success': False, 'error': 'Unknown upload target'}), 400
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        selection_logger.error("Admin file upload failed for %s: %s", target, exc)
        return jsonify({'success': False, 'error': str(exc)}), 500

    return jsonify({
        'success': True,
        **result,
        'manifest': _build_admin_files_manifest(),
    })


@routes.route('/api/admin/files/restore', methods=['POST'])
@admin_required
def admin_files_restore() -> Any:
    data = request.get_json(silent=True) or {}
    target = str(data.get('target', '')).strip().lower()

    try:
        if target == 'staged_day':
            source_name = str(data.get('name', '')).strip()
            if not source_name:
                return jsonify({'success': False, 'error': 'Missing staged day file name'}), 400
            result = _restore_staged_day_file(source_name)
        elif target == 'live_backup':
            live_path = Path(StateManager.get_instance().unified_schedule_paths['live'])
            if not live_path.exists():
                return jsonify({'success': False, 'error': 'Live backup file does not exist'}), 404
            if not initialize_data_from_unified(str(live_path), context='admin_file_restore'):
                raise ValueError('Failed to reload live state from current live backup')
            result = {'message': 'Live state reloaded from current live backup'}
        else:
            return jsonify({'success': False, 'error': 'Unknown restore target'}), 400
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        selection_logger.error("Admin file restore failed for %s: %s", target, exc)
        return jsonify({'success': False, 'error': str(exc)}), 500

    return jsonify({
        'success': True,
        **result,
        'manifest': _build_admin_files_manifest(),
    })


@routes.route('/api/edit_info', methods=['POST'])
@admin_required
def edit_info() -> Any:
    """Update info texts for a specific modality"""
    try:
        data = request.get_json()
        modality = normalize_modality(data.get('modality', ''))
        info_text = data.get('info_text', '')

        if not modality or modality not in allowed_modalities:
            return jsonify({"success": False, "error": "Ungültige Modalität"}), 400

        skill = data.get('skill')

        # Split info_text by newlines and filter out empty lines
        info_texts = [line.strip() for line in info_text.split('\n') if line.strip()]

        # Update either modality-wide or modality×skill scoped info texts
        if skill:
            skill = normalize_skill(skill)
            if skill not in SKILL_COLUMNS:
                return jsonify({"success": False, "error": "Ungültiger Skill"}), 400
            by_skill = modality_data[modality].setdefault('info_texts_by_skill', {})
            by_skill[skill] = info_texts
            selection_logger.info(f"Info texts updated for {modality}/{skill} by admin")
        else:
            modality_data[modality]['info_texts'] = info_texts
            selection_logger.info(f"Info texts updated for {modality} by admin")

        # Save the updated state and backup
        save_state()
        backup_dataframe(modality)

        return jsonify({
            "success": True,
            "info_texts": info_texts,
            "skill": skill,
            "message": "Info-Texte erfolgreich gespeichert"
        })
    except Exception as e:
        selection_logger.error(f"Error updating info texts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@routes.route('/api/master-csv-status')
def master_csv_status() -> Any:
    if os.path.exists(MASTER_CSV_PATH):
        stat = os.stat(MASTER_CSV_PATH)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
        return jsonify({
            'exists': True,
            'filename': 'master_medweb.csv',
            'modified': modified,
            'size': stat.st_size
        })
    return jsonify({'exists': False})

@routes.route('/upload-master-csv', methods=['POST'])
@admin_required
def upload_master_csv() -> Any:
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({"error": "Bitte CSV-Datei hochladen"}), 400

    try:
        file.save(MASTER_CSV_PATH)
        selection_logger.info(f"Master CSV uploaded: {MASTER_CSV_PATH}")
        return jsonify({
            "success": True,
            "message": "Master-CSV erfolgreich hochgeladen"
        })
    except Exception as e:
        return jsonify({"error": f"Upload fehlgeschlagen: {str(e)}"}), 500


@routes.route('/preload-from-master', methods=['POST'])
@admin_required
def preload_from_master() -> Any:
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst hochladen."}), 400

    reload_info = None
    payload = request.get_json(silent=True) or {}
    target_date = payload.get('target_date') or request.form.get('target_date')
    force_csv_raw = payload.get('force_csv')
    if force_csv_raw is None:
        force_csv_raw = request.form.get('force_csv')
    force_csv = str(force_csv_raw).lower() in {'1', 'true', 'yes', 'on'}
    parsed_target_date = None

    if target_date:
        try:
            parsed_target_date = date.fromisoformat(target_date)
        except ValueError:
            return jsonify({"error": "Ungültiges Datum. Bitte YYYY-MM-DD nutzen."}), 400
        earliest_allowed = get_next_workday().date()
        if parsed_target_date < earliest_allowed:
            return jsonify({"error": f"Prep-Datum muss ab {earliest_allowed.isoformat()} liegen."}), 400
    requested_date = parsed_target_date or _get_staged_target_date() or get_next_workday().date()

    if not force_csv:
        loaded_saved_staged = False
        with lock:
            loaded_saved_staged = reload_staged_data_from_disk(target_date=requested_date)

        if loaded_saved_staged:
            staged_target_date = _get_staged_target_date()
            if staged_target_date is not None and (target_date is None or staged_target_date.isoformat() == target_date):
                with lock:
                    global_worker_data['last_preload_date'] = staged_target_date
                    global_worker_data['last_preload_source'] = 'snapshot'
                    save_state()
                result = {
                    'success': True,
                    'target_date': staged_target_date.isoformat(),
                    'modalities_loaded': allowed_modalities,
                    'total_workers': 0,
                    'message': f'Gespeicherte Staging-Daten für {staged_target_date.strftime("%Y-%m-%d")} geladen',
                }
                return jsonify(result)

    with lock:
        reload_info = _maybe_reload_runtime_config(manual=True)
    result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG, target_date=requested_date)

    if result['success']:

        with lock:
            target_date_obj = requested_date
            global_worker_data['last_preload_date'] = target_date_obj
            global_worker_data['last_preload_source'] = 'csv'
            save_state()

        if reload_info:
            result = dict(result)
            result['info_message'] = reload_info
            result['message'] = f"{result.get('message', '')} | {reload_info}"

        return jsonify(result)
    return jsonify(result), 400


@routes.route('/upload', methods=['GET'])
@admin_required
def upload_file() -> Any:
    """Admin dashboard page for CSV management and statistics."""
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    combined_skill_counts, _ = _build_combined_skill_counts_view()
    all_worker_names = set()
    for skill in SKILL_COLUMNS:
        all_worker_names.update(combined_skill_counts[skill].keys())

    sum_counts = {}
    global_counts = {}
    global_weighted_counts = {}
    for worker in all_worker_names:
        total = sum(combined_skill_counts[skill].get(worker, 0) for skill in SKILL_COLUMNS)
        sum_counts[worker] = total

        canonical = get_canonical_worker_id(worker)
        global_counts[worker] = get_global_assignments(canonical)
        global_weighted_counts[worker] = get_global_weighted_count(canonical)

    combined_workers = sorted(all_worker_names, key=build_worker_sort_key)
    modality_stats = {}
    for worker in combined_workers:
        modality_stats[worker] = {
            skill: combined_skill_counts[skill].get(worker, 0)
            for skill in SKILL_COLUMNS
        }
        modality_stats[worker]['total'] = sum_counts.get(worker, 0)

    debug_info = (
        d['working_hours_df'].to_html(index=True)
        if d['working_hours_df'] is not None else "Keine Daten verfügbar"
    )

    checks = run_operational_checks('admin_view', force=True)

    return render_template(
        'upload.html',
        debug_info=debug_info,
        modality=modality,
        skill_counts=combined_skill_counts,
        sum_counts=sum_counts,
        global_counts=global_counts,
        global_weighted_counts=global_weighted_counts,
        combined_workers=combined_workers,
        modality_stats=modality_stats,
        operational_checks=checks,
        scheduler_config=APP_CONFIG.get('scheduler', {}),
        is_admin=True
    )

def _check_config_file() -> dict[str, str]:
    """Check if APP_CONFIG is loaded."""
    if APP_CONFIG:
        return {'status': 'OK', 'detail': 'APP_CONFIG is loaded and available'}
    return {'status': 'ERROR', 'detail': 'APP_CONFIG is not loaded or empty'}


def _check_scheduler() -> dict[str, str]:
    """Check scheduler configuration."""
    scheduler_conf = APP_CONFIG.get('scheduler', {})
    reset_time = scheduler_conf.get('daily_reset_time', '07:30')
    return {'status': 'OK', 'detail': f'Resets at {reset_time}, lazy preload on demand'}


def _check_admin_password() -> dict[str, str]:
    """Check admin password configuration."""
    admin_pw = get_admin_password()
    if not admin_pw:
        return {'status': 'WARNING', 'detail': 'Admin password is not set in config.yaml'}
    if admin_pw == 'change_pw_for_live':
        return {'status': 'WARNING', 'detail': 'Admin password is still set to default value - change for production!'}
    return {'status': 'OK', 'detail': 'Admin password is configured'}


def _check_upload_folder() -> dict[str, str]:
    """Check upload folder exists and is writable."""
    upload_folder = 'uploads'
    if not os.path.exists(upload_folder):
        return {'status': 'WARNING', 'detail': f'Upload folder "{upload_folder}" does not exist (will be created on upload)'}
    if not os.access(upload_folder, os.W_OK):
        return {'status': 'ERROR', 'detail': f'Upload folder "{upload_folder}" is not writable'}
    has_master_csv = os.path.exists(os.path.join(upload_folder, 'master_medweb.csv'))
    csv_status = "Master CSV present" if has_master_csv else "No Master CSV"
    return {'status': 'OK', 'detail': f'Upload folder "{upload_folder}" is writable ({csv_status})'}


def _check_modalities() -> dict[str, str]:
    """Check modality configuration."""
    modality_count = len(allowed_modalities)
    if modality_count == 0:
        return {'status': 'ERROR', 'detail': 'No modalities configured in config.yaml'}
    return {'status': 'OK', 'detail': f'{modality_count} modalities configured: {", ".join(allowed_modalities)}'}


def _check_skills() -> dict[str, str]:
    """Check skill configuration."""
    skill_count = len(SKILL_COLUMNS)
    if skill_count == 0:
        return {'status': 'ERROR', 'detail': 'No skills configured in config.yaml'}
    return {'status': 'OK', 'detail': f'{skill_count} skills configured: {", ".join(SKILL_COLUMNS)}'}


def _check_worker_data() -> dict[str, str]:
    """Check worker data is loaded."""
    total_workers = 0
    for mod in allowed_modalities:
        d = modality_data.get(mod, {})
        if d.get('working_hours_df') is not None:
            total_workers += len(d['working_hours_df']['PPL'].unique())

    if total_workers == 0:
        return {'status': 'WARNING', 'detail': 'No worker data loaded - upload Master CSV and use Load Today'}
    return {'status': 'OK', 'detail': f'{total_workers} workers loaded across all modalities'}


def run_operational_checks(context: str = 'unknown', force: bool = False) -> dict[str, Any]:
    """Run all operational checks and return results."""
    checks = [
        ('Config File', _check_config_file),
        ('Scheduler', _check_scheduler),
        ('Admin Password', _check_admin_password),
        ('Upload Folder', _check_upload_folder),
        ('Modalities', _check_modalities),
        ('Skills', _check_skills),
        ('Worker Data', _check_worker_data),
    ]

    results = []
    for name, check_fn in checks:
        try:
            result = check_fn()
            results.append({'name': name, **result})
        except Exception as e:
            results.append({'name': name, 'status': 'ERROR', 'detail': f'Failed to check {name.lower()}: {str(e)}'})

    return {
        'results': results,
        'context': context,
        'timestamp': get_local_now().isoformat()
    }

@routes.route('/load-today-from-master', methods=['POST'])
@admin_required
def load_today_from_master() -> Any:
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst CSV hochladen."}), 400

    try:
        with lock:
            reload_info = _maybe_reload_runtime_config(manual=True)

        target_date = get_local_now()

        # Debug: Check CSV content before parsing
        try:
            vendor_mapping = APP_CONFIG.get('medweb_mapping', {})
            cols = vendor_mapping.get('columns', {
                'date': 'Datum',
                'activity': 'Beschreibung der Aktivität'
            })
            date_col = cols.get('date', 'Datum')
            activity_col = cols.get('activity', 'Beschreibung der Aktivität')

            try:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='utf-8')
            except UnicodeDecodeError:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='latin1')
            if date_col not in debug_df.columns:
                try:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='utf-8')
                except UnicodeDecodeError:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='latin1')

            available_dates = debug_df[date_col].unique().tolist() if date_col in debug_df.columns else []
            available_activities = debug_df[activity_col].unique().tolist() if activity_col in debug_df.columns else []
        except Exception as e:
            return jsonify({"error": f"CSV-Lesefehler: {str(e)}"}), 400

        # Acquire lock BEFORE parsing CSV to prevent race conditions
        # when multiple requests overlap - data parsing must be atomic
        with lock:
            modality_dfs = build_working_hours_from_medweb(
                MASTER_CSV_PATH,
                target_date,
                APP_CONFIG
            )

            # ALWAYS reset global state and ALL modalities first to prevent stale data
            # This handles both empty returns and partial modality returns
            global_worker_data['weighted_counts'] = {}
            global_worker_data['flow_cross_pool'] = {}
            global_worker_data['distribution_stats'] = {}
            global_worker_data['recent_distributions'] = []

            for modality in allowed_modalities:
                d = modality_data[modality]
                d['working_hours_df'] = None
                d['info_texts'] = []
                global_worker_data['assignments_per_mod'][modality] = {}

            if not modality_dfs:
                # No staff entries found - this is OK, not all shifts have staff (balancer handles this)
                mapping_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
                rule_matches = [r.get('match', '') for r in mapping_rules[:10]]
                matched_activities = []
                for activity in available_activities:
                    for rule in mapping_rules:
                        if rule.get('match', '').lower() in str(activity).lower():
                            matched_activities.append(activity)
                            break

                selection_logger.info(f"No staff entries found for {target_date.strftime('%d.%m.%Y')} - this is expected for some shifts")

                # Persist cleared state
                save_state()
                persist_live_backup()

                message = f"Keine Mitarbeiter für {target_date.strftime('%d.%m.%Y')} gefunden - Schichten können leer sein"
                if reload_info:
                    message = f"{message} | {reload_info}"

                return jsonify({
                    "success": True,
                    "message": message,
                    "modalities_loaded": [],
                    "total_workers": 0,
                    "workers_added_to_roster": 0,
                    "info_message": reload_info,
                    "info": {
                        "target_date": target_date.strftime('%d.%m.%Y'),
                        "dates_in_csv": available_dates[:10],
                        "activities_in_csv": available_activities[:10],
                        "mapping_rules": rule_matches,
                        "matched_activities": matched_activities[:10],
                    }
                })

            # Now populate modalities that have data (others remain cleared)
            for modality, df in modality_dfs.items():
                d = modality_data[modality]
                d['working_hours_df'] = df

                if df is None or df.empty:
                    continue

                d['info_texts'] = []

        # Persist state OUTSIDE the lock to prevent blocking I/O
        save_state()
        persist_live_backup()

        workers_added = 0
        if APP_CONFIG.get('skill_roster_auto_import', True):
            workers_added, _ = auto_populate_skill_roster(modality_dfs)

        message = f"Heute ({target_date.strftime('%d.%m.%Y')}) aus Master-CSV geladen"
        if reload_info:
            message = f"{message} | {reload_info}"

        return jsonify({
            "success": True,
            "message": message,
            "modalities_loaded": list(modality_dfs.keys()),
            "total_workers": sum(len(df) for df in modality_dfs.values()),
            "workers_added_to_roster": workers_added,
            "info_message": reload_info,
        })

    except Exception as e:
        return jsonify({"error": f"Fehler: {str(e)}"}), 500

def _render_prep_page(initial_tab: str) -> Any:
    staged_target_date = _get_staged_target_date()
    if initial_tab == 'tomorrow' and staged_target_date is None:
        _ensure_next_workday_preloaded()
        staged_target_date = _get_staged_target_date()
    prep_min_date = get_next_workday().date()
    next_day = staged_target_date or prep_min_date
    next_day_dt = next_day if isinstance(next_day, datetime) else datetime.combine(next_day, datetime.min.time())
    target_date_str = next_day_dt.strftime('%Y-%m-%d')
    target_date_german = next_day_dt.strftime('%d.%m.%Y')
    target_weekday_name = get_weekday_name_german(next_day_dt.date())
    prep_loaded_label = _format_prep_loaded_label(next_day_dt.date())
    prep_last_edit_label = _get_prep_last_edit_label()

    roster = load_worker_skill_json()
    if roster is None:
        roster = {}
    worker_list = list(roster.keys())
    worker_names = build_worker_name_mapping(roster)

    task_roles = _build_task_roles()

    worker_skills = load_worker_skill_json()

    # Quick break config with defaults
    quick_break_config = APP_CONFIG.get('balancer', {}).get('quick_break', {})
    quick_break = {
        'duration_minutes': quick_break_config.get('duration_minutes', 30),
        'gap_type': quick_break_config.get('gap_type', 'Break')
    }

    return render_template(
        'prep_next_day.html',
        target_date=target_date_str,
        target_date_german=target_date_german,
        target_weekday_name=target_weekday_name,
        prep_min_date=prep_min_date.strftime('%Y-%m-%d'),
        prep_loaded_label=prep_loaded_label,
        prep_last_edit_label=prep_last_edit_label,
        is_next_day=True,
        initial_tab=initial_tab,
        skills=SKILL_COLUMNS,
        skill_settings=SKILL_SETTINGS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_settings=MODALITY_SETTINGS,
        worker_list=worker_list,
        worker_names=worker_names,
        worker_skills=worker_skills,
        task_roles=task_roles,
        skill_value_colors=APP_CONFIG.get('skill_value_colors', {}),
        ui_colors=APP_CONFIG.get('ui_colors', {}),
        quick_break=quick_break,
        is_admin=True
    )


@routes.route('/prep-today')
@admin_required
def prep_today() -> Any:
    return _render_prep_page('today')


@routes.route('/prep-tomorrow')
@admin_required
def prep_tomorrow() -> Any:
    return _render_prep_page('tomorrow')

@routes.route('/api/prep-next-day/data', methods=['GET'])
@admin_required
def get_prep_data() -> Any:
    result = {}
    requested_target_date = None
    raw_target_date = request.args.get('target_date')
    if raw_target_date:
        try:
            requested_target_date = date.fromisoformat(raw_target_date)
        except ValueError:
            return jsonify({'error': 'Invalid target_date. Use YYYY-MM-DD.'}), 400
    staged_target_date = requested_target_date or _get_staged_target_date()
    if staged_target_date is None:
        _ensure_next_workday_preloaded()
        staged_target_date = _get_staged_target_date()

    # Acquire lock to prevent race conditions when reading/writing staged data
    with lock:
        if requested_target_date is not None and _get_staged_target_date() != requested_target_date:
            load_staged_dataframe(allowed_modalities[0], target_date=requested_target_date)
        staged_rebuilt = False
        for modality in allowed_modalities:
            if staged_modality_data[modality]['working_hours_df'] is None:
                if not load_staged_dataframe(modality, target_date=staged_target_date):
                    if staged_target_date is not None and not staged_rebuilt:
                        preload_result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG, target_date=staged_target_date)
                        staged_rebuilt = bool(preload_result.get('success'))
                        if staged_rebuilt:
                            load_staged_dataframe(modality, target_date=staged_target_date)
                    elif modality_data[modality]['working_hours_df'] is not None:
                        staged_modality_data[modality]['working_hours_df'] = modality_data[modality]['working_hours_df'].copy()
                        staged_modality_data[modality]['info_texts'] = modality_data[modality]['info_texts'].copy()
                        backup_dataframe(modality, use_staged=True)

            df = staged_modality_data[modality].get('working_hours_df')
            result[modality] = _df_to_api_response(df)

        last_prepped_at = staged_modality_data[allowed_modalities[0]].get('last_prepped_at')
        last_modified = staged_modality_data[allowed_modalities[0]].get('last_modified')
        target_date = staged_modality_data[allowed_modalities[0]].get('target_date')
        prep_last_edit_label = _get_prep_last_edit_label()

    target_date_obj = None
    if isinstance(target_date, date):
        target_date_obj = target_date
    elif isinstance(target_date, str):
        try:
            target_date_obj = date.fromisoformat(target_date)
        except ValueError:
            target_date_obj = None
    if target_date_obj is None:
        target_date_obj = get_next_workday().date()

    return jsonify({
        'modalities': result,
        'last_prepped_at': last_prepped_at,
        'last_modified': _format_prep_timestamp(last_modified),
        'prep_loaded_label': _format_prep_loaded_label(target_date_obj),
        'prep_last_edit_label': prep_last_edit_label,
        'prep_load_source': global_worker_data.get('last_preload_source'),
        'snapshot_version': _ensure_snapshot_file(True, target_date=target_date_obj),
        'worker_revisions': _build_worker_revision_map(True),
        'target_date': target_date_obj.isoformat(),
        'target_weekday_name': get_weekday_name_german(target_date_obj),
    })

@routes.route('/api/prep-next-day/update-row', methods=['POST'])
@admin_required
def update_prep_row() -> Any:
    return _handle_update_row(use_staged=True)


@routes.route('/api/prep-next-day/apply-worker-plan', methods=['POST'])
@admin_required
def apply_prep_worker_plan() -> Any:
    return _handle_apply_worker_plan(use_staged=True)

@routes.route('/api/prep-next-day/resolve-task-preview', methods=['POST'])
@admin_required
def resolve_prep_task_preview() -> Any:
    return _handle_task_preview(use_staged=True)

@routes.route('/api/prep-next-day/add-worker', methods=['POST'])
@admin_required
def add_prep_worker() -> Any:
    return _handle_add_worker(use_staged=True)

@routes.route('/api/prep-next-day/delete-worker', methods=['POST'])
@admin_required
def delete_prep_worker() -> Any:
    return _handle_delete_worker(use_staged=True)

@routes.route('/api/live-schedule/data', methods=['GET'])
@admin_required
def get_live_data() -> Any:
    result = {}
    for modality in allowed_modalities:
        df = modality_data[modality].get('working_hours_df')
        result[modality] = _df_to_api_response(df)
    return jsonify({
        'modalities': result,
        'snapshot_version': _ensure_snapshot_file(False),
        'worker_revisions': _build_worker_revision_map(False),
    })

@routes.route('/api/live-schedule/update-row', methods=['POST'])
@admin_required
def update_live_row() -> Any:
    return _handle_update_row(
        use_staged=False,
        log_message="Live schedule updated for {modality}, row {row_index} (no counter reset)",
    )


@routes.route('/api/live-schedule/apply-worker-plan', methods=['POST'])
@admin_required
def apply_live_worker_plan() -> Any:
    return _handle_apply_worker_plan(use_staged=False)

@routes.route('/api/live-schedule/resolve-task-preview', methods=['POST'])
@admin_required
def resolve_live_task_preview() -> Any:
    return _handle_task_preview(use_staged=False)

@routes.route('/api/live-schedule/add-worker', methods=['POST'])
@admin_required
def add_live_worker() -> Any:
    def _post_add(modality: str, ppl_name: str) -> None:
        selection_logger.info(f"Worker {ppl_name} added to LIVE {modality} schedule (no counter reset)")

    return _handle_add_worker(use_staged=False, post_success=_post_add)

@routes.route('/api/live-schedule/delete-worker', methods=['POST'])
@admin_required
def delete_live_worker() -> Any:
    return _handle_delete_worker(
        use_staged=False,
        log_message="Worker {worker_name} deleted from LIVE {modality} schedule (no counter reset)",
    )

@routes.route('/api/live-schedule/add-gap', methods=['POST'])
@admin_required
def add_live_gap() -> Any:
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_counts_for_hours = data.get('gap_counts_for_hours')
    snapshot_error = _check_snapshot_version(data.get('snapshot_version'), False)

    if snapshot_error:
        return snapshot_error

    error = _validate_modality(modality, modality_data)
    if error:
        return error

    success, action, error = add_gap_to_schedule(
        modality,
        row_index,
        gap_type,
        gap_start,
        gap_end,
        use_staged=False,
        gap_counts_for_hours=gap_counts_for_hours
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(False),
        })
    return jsonify({'error': error}), 400


@routes.route('/api/live-schedule/add-gap-batch', methods=['POST'])
@admin_required
def add_live_gap_batch() -> Any:
    data = request.json or {}
    row_index_map = data.get('row_index_map', {})
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_counts_for_hours = data.get('gap_counts_for_hours')
    snapshot_error = _check_snapshot_version(data.get('snapshot_version'), False)

    if snapshot_error:
        return snapshot_error

    if not isinstance(row_index_map, dict) or not row_index_map:
        return jsonify({'error': 'row_index_map is required'}), 400

    success, action, error = add_gap_to_schedule_batch(
        row_index_map,
        gap_type,
        gap_start,
        gap_end,
        use_staged=False,
        gap_counts_for_hours=gap_counts_for_hours
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(False),
        })
    return jsonify({'error': error}), 400

@routes.route('/api/prep-next-day/add-gap', methods=['POST'])
@admin_required
def add_staged_gap() -> Any:
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_counts_for_hours = data.get('gap_counts_for_hours')
    target_date, staged_error = _prepare_staged_mutation(data)
    if staged_error:
        return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        True,
        target_date=target_date,
    )

    if snapshot_error:
        return snapshot_error

    error = _validate_modality(modality, staged_modality_data)
    if error:
        return error

    success, action, error = add_gap_to_schedule(
        modality,
        row_index,
        gap_type,
        gap_start,
        gap_end,
        use_staged=True,
        gap_counts_for_hours=gap_counts_for_hours
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(True, target_date=target_date),
        })
    return jsonify({'error': error}), 400


@routes.route('/api/prep-next-day/add-gap-batch', methods=['POST'])
@admin_required
def add_staged_gap_batch() -> Any:
    data = request.json or {}
    row_index_map = data.get('row_index_map', {})
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_counts_for_hours = data.get('gap_counts_for_hours')
    target_date, staged_error = _prepare_staged_mutation(data)
    if staged_error:
        return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        True,
        target_date=target_date,
    )

    if snapshot_error:
        return snapshot_error

    if not isinstance(row_index_map, dict) or not row_index_map:
        return jsonify({'error': 'row_index_map is required'}), 400

    success, action, error = add_gap_to_schedule_batch(
        row_index_map,
        gap_type,
        gap_start,
        gap_end,
        use_staged=True,
        gap_counts_for_hours=gap_counts_for_hours
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(True, target_date=target_date),
        })
    return jsonify({'error': error}), 400


def _handle_remove_gap(use_staged: bool) -> Any:
    """Handle gap removal for both live and staged schedules."""
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_activity = data.get('gap_activity')
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if snapshot_error:
        return snapshot_error

    data_store = staged_modality_data if use_staged else modality_data
    error = _validate_modality(modality, data_store)
    if error:
        return error

    if gap_start is None or gap_end is None:
        return jsonify({'error': 'gap_start and gap_end are required'}), 400

    gap_match = {'start': gap_start, 'end': gap_end, 'activity': gap_activity}
    success, action, error = remove_gap_from_schedule(
        modality,
        row_index,
        None,
        use_staged=use_staged,
        gap_match=gap_match
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(
                use_staged,
                target_date=target_date if use_staged else None,
            ),
        })
    return jsonify({'error': error}), 400


def _handle_update_gap(use_staged: bool) -> Any:
    """Handle gap updates for both live and staged schedules."""
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')
    gap_activity = data.get('gap_activity')
    new_start = data.get('new_start')
    new_end = data.get('new_end')
    new_activity = data.get('new_activity')
    new_counts_for_hours = data.get('new_counts_for_hours')
    target_date = None
    if use_staged:
        target_date, staged_error = _prepare_staged_mutation(data)
        if staged_error:
            return staged_error
    snapshot_error = _check_snapshot_version(
        data.get('snapshot_version'),
        use_staged,
        target_date=target_date if use_staged else None,
    )
    if snapshot_error:
        return snapshot_error

    data_store = staged_modality_data if use_staged else modality_data
    error = _validate_modality(modality, data_store)
    if error:
        return error

    if gap_start is None or gap_end is None:
        return jsonify({'error': 'gap_start and gap_end are required'}), 400

    gap_match = {'start': gap_start, 'end': gap_end, 'activity': gap_activity}
    success, action, error = update_gap_in_schedule(
        modality,
        row_index,
        None,
        new_start,
        new_end,
        new_activity,
        use_staged=use_staged,
        new_counts_for_hours=new_counts_for_hours,
        gap_match=gap_match
    )

    if success:
        return jsonify({
            'success': True,
            'action': action,
            'snapshot_version': _get_snapshot_version(
                use_staged,
                target_date=target_date if use_staged else None,
            ),
        })
    return jsonify({'error': error}), 400


@routes.route('/api/live-schedule/remove-gap', methods=['POST'])
@admin_required
def remove_live_gap() -> Any:
    """Remove a gap from a live schedule shift."""
    return _handle_remove_gap(use_staged=False)


@routes.route('/api/prep-next-day/remove-gap', methods=['POST'])
@admin_required
def remove_staged_gap() -> Any:
    """Remove a gap from a staged schedule shift."""
    return _handle_remove_gap(use_staged=True)


@routes.route('/api/live-schedule/update-gap', methods=['POST'])
@admin_required
def update_live_gap() -> Any:
    """Update a gap in a live schedule shift."""
    return _handle_update_gap(use_staged=False)


@routes.route('/api/prep-next-day/update-gap', methods=['POST'])
@admin_required
def update_staged_gap() -> Any:
    """Update a gap in a staged schedule shift."""
    return _handle_update_gap(use_staged=True)


def _assign_worker(
    modality: str,
    role: str,
    allow_overflow: bool = True,
    *,
    use_strict_weights: bool = False,
) -> Any:
    try:
        now = get_local_now()

        special_task = SPECIAL_TASKS_MAP.get(role.lower())
        task_work_amount = 1.0
        task_label = None
        fallback_targets = None
        target_skill_modalities = None
        if special_task:
            role = special_task['base_skill']
            task_label = special_task.get('label')
            if allow_overflow and not special_task.get('allow_overflow', True):
                allow_overflow = False
            # Get explicit routing targets if defined
            target_skill_modalities = special_task.get('target_skill_modalities') or None

        # Check if this skill×modality combo has overflow disabled
        canonical_skill = normalize_skill(role)
        if not target_skill_modalities:
            fallback_targets = get_specialist_fallback_targets(canonical_skill, modality)
            if fallback_targets:
                selection_logger.info(
                    "Specialist fallback route active for %s_%s -> %s",
                    canonical_skill,
                    modality,
                    [f"{s}_{m}" for s, m in fallback_targets],
                )
        if allow_overflow and is_no_overflow(canonical_skill, modality):
            allow_overflow = False
            selection_logger.info(
                "No-overflow config active for %s_%s, forcing strict mode",
                canonical_skill,
                modality,
            )

        strict_routing = not allow_overflow
        selection_logger.info(
            "Assignment request: modality=%s, role=%s, strict_routing=%s, strict_weights=%s, time=%s",
            modality,
            role,
            strict_routing,
            use_strict_weights,
            now.strftime('%H:%M:%S'),
        )

        # Store response data to return after releasing lock
        response_data = None
        state_modified = False
        requested_weight_override = None
        if special_task:
            requested_weight_override = get_special_task_weight(
                special_task['slug'],
                modality,
                strict=use_strict_weights,
            )
        request_flow_weight = _get_cross_pool_flow_weight(
            canonical_skill,
            modality,
            use_strict_weights=use_strict_weights,
            work_amount=task_work_amount,
            weight_override=requested_weight_override,
        )

        with lock:
            _record_distribution_request(
                requested_skill=canonical_skill,
                request_weight=request_flow_weight,
            )

            # 1) Special task explicit targets: use configured specialist pools directly.
            if target_skill_modalities:
                result = get_next_available_worker(
                    now,
                    role=role,
                    modality=modality,
                    allow_overflow=allow_overflow,
                    target_skill_modalities=target_skill_modalities,
                )
            # 2) Skill fallback route:
            #    - Try primary specialists first (1/w only)
            #    - Only if primary is empty, try fallback specialist groups
            elif fallback_targets:
                result = get_next_available_worker(
                    now,
                    role=role,
                    modality=modality,
                    allow_overflow=False,
                    target_skill_modalities=None,
                )
                if result is None:
                    merged_targets = [(canonical_skill, modality)]
                    for target in fallback_targets:
                        if target not in merged_targets:
                            merged_targets.append(target)
                    result = get_next_available_worker(
                        now,
                        role=role,
                        modality=modality,
                        allow_overflow=allow_overflow,
                        target_skill_modalities=merged_targets,
                    )
            else:
                result = get_next_available_worker(
                    now,
                    role=role,
                    modality=modality,
                    allow_overflow=allow_overflow,
                    target_skill_modalities=None,
                )

            if result is not None:
                candidate, used_column, source_modality = result
                actual_modality = source_modality or modality
                d = modality_data[actual_modality]

                candidate = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                if "PPL" not in candidate:
                    raise ValueError("Candidate row is missing the 'PPL' field")
                person = candidate['PPL']

                actual_skill = candidate.get('__skill_source')
                if not actual_skill and isinstance(used_column, str):
                    actual_skill = used_column
                if not actual_skill:
                    actual_skill = role
                if special_task:
                    actual_skill = canonical_skill

                selection_logger.info(
                    "Selected worker: %s using column %s (modality %s)",
                    person,
                    actual_skill,
                    actual_modality,
                )

                # Check if this is a weighted ('w') assignment.
                # Shift modifier is always applied; W stream only for weighted assignments.
                is_weighted = candidate.get('__is_weighted', False)
                weight_override = None
                if special_task:
                    weight_override = get_special_task_weight(
                        special_task['slug'],
                        actual_modality,
                        strict=use_strict_weights,
                    )
                candidate_shift_modifier = candidate.get('Modifier', 1.0)
                canonical_id = update_global_assignment(
                    person,
                    actual_skill,
                    actual_modality,
                    is_weighted,
                    strict_mode=use_strict_weights,
                    work_amount=task_work_amount,
                    weight_override=weight_override,
                    shift_modifier_override=candidate_shift_modifier,
                )
                flow_target_skill = _resolve_flow_target_skill(candidate, actual_skill)
                flow_weight = _get_cross_pool_flow_weight(
                    canonical_skill,
                    modality,
                    use_strict_weights=use_strict_weights,
                    work_amount=task_work_amount,
                    weight_override=weight_override,
                )
                _record_cross_pool_flow(
                    requested_skill=canonical_skill,
                    target_skill=flow_target_skill,
                    amount=flow_weight,
                )
                normalized_flow_target = _normalize_flow_target_key(flow_target_skill)
                overflowed = normalized_flow_target != canonical_skill
                unresolved = normalized_flow_target == FLOW_UNRESOLVED_TARGET
                _record_distribution_stats(
                    requested_skill=canonical_skill,
                    flow_weight=flow_weight,
                    overflowed=overflowed,
                    unresolved=unresolved,
                )
                _record_recent_distribution(
                    person=person,
                    canonical_id=canonical_id,
                    requested_skill=canonical_skill,
                    requested_modality=modality,
                    actual_skill=actual_skill,
                    actual_modality=actual_modality,
                    flow_weight=flow_weight,
                    overflowed=overflowed,
                    unresolved=unresolved,
                    task_label=task_label,
                )
                state_modified = True

                # Record skill-modality usage for analytics
                usage_logger.record_skill_modality_usage(actual_skill, actual_modality)

                # Check if it's time for scheduled export (7:30 AM)
                usage_logger.check_and_export_at_scheduled_time()

                response_data = {
                    "selected_person": person,
                    "canonical_id": canonical_id,
                    "source_modality": actual_modality,
                    "skill_used": actual_skill,
                    "is_weighted": is_weighted,
                    "task_label": task_label,
                }
            else:
                selection_logger.warning("No available worker found")
                return jsonify({"error": "No available worker found"}), 404

        # Persist state OUTSIDE the lock to prevent blocking I/O
        if state_modified:
            save_state()

        return jsonify(response_data)

    except Exception as e:
        selection_logger.error(f"Error selecting worker: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@routes.route('/api/<modality>/<role>', methods=['GET'])
@access_required
def assign_worker_api(modality: str, role: str) -> Any:
    modality = normalize_modality(modality)
    error = _validate_modality(modality, modality_data)
    if error:
        return error
    return _assign_worker(modality, role)

@routes.route('/api/<modality>/<role>/strict', methods=['GET'])
@access_required
def assign_worker_strict_api(modality: str, role: str) -> Any:
    modality = normalize_modality(modality)
    error = _validate_modality(modality, modality_data)
    if error:
        return error
    return _assign_worker(modality, role, allow_overflow=False, use_strict_weights=True)

# Usage Statistics API Endpoints

@routes.route('/api/usage-stats/current', methods=['GET'])
@admin_required
def get_current_usage_stats() -> Any:
    """Get current daily usage statistics for skill-modality combinations."""
    stats = usage_logger.get_current_usage_stats()

    # Convert to list format for easier consumption
    stats_list = [
        {
            'skill': skill,
            'modality': modality,
            'count': count
        }
        for (skill, modality), count in sorted(stats.items())
    ]

    return jsonify({
        'date': get_local_now().strftime('%Y-%m-%d'),
        'total_combinations': len(stats_list),
        'total_usages': sum(s['count'] for s in stats_list),
        'stats': stats_list
    })

@routes.route('/api/usage-stats/export', methods=['POST'])
@admin_required
def export_usage_stats() -> Any:
    """Manually trigger export of current usage statistics to CSV (wide format)."""
    try:
        csv_path = usage_logger.export_current_usage()
        if csv_path:
            return jsonify({
                'success': True,
                'message': 'Usage statistics exported successfully (appended to CSV)',
                'file_path': str(csv_path),
                'date': datetime.now().strftime('%Y-%m-%d'),
                'note': 'Data appended as new row in wide format CSV'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No usage data to export'
            })
    except Exception as e:
        selection_logger.error(f"Error exporting usage stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@routes.route('/api/usage-stats/reset', methods=['POST'])
@admin_required
def reset_usage_stats() -> Any:
    """Reset current usage statistics (use with caution)."""
    try:
        usage_logger.reset_daily_usage()
        return jsonify({
            'success': True,
            'message': 'Usage statistics reset successfully'
        })
    except Exception as e:
        selection_logger.error(f"Error resetting usage stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@routes.route('/api/usage-stats/file', methods=['GET'])
@admin_required
def get_usage_stats_file_info() -> Any:
    """Get information about the usage statistics CSV file."""
    try:
        csv_path = usage_logger.USAGE_STATS_FILE

        if not csv_path.exists():
            return jsonify({
                'success': True,
                'exists': False,
                'message': 'No usage statistics file exists yet'
            })

        # Read dates from the CSV
        import csv
        dates = []
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'date' in row:
                    dates.append(row['date'])

        return jsonify({
            'success': True,
            'exists': True,
            'filename': csv_path.name,
            'path': str(csv_path),
            'size_bytes': csv_path.stat().st_size,
            'total_days': len(dates),
            'dates': dates,
            'date_range': {
                'first': dates[0] if dates else None,
                'last': dates[-1] if dates else None
            }
        })
    except Exception as e:
        selection_logger.error(f"Error getting usage stats file info: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# FLOW BALANCE MONITOR
# =============================================================================

@routes.route('/flow-balance')
@admin_required
def flow_balance_page() -> Any:
    return redirect(url_for('routes.worker_load_monitor', mode='flow'))


@routes.route('/api/flow-balance/data', methods=['GET'])
@admin_required
def get_flow_balance_data() -> Any:
    return jsonify(_build_flow_balance_payload())


# =============================================================================
# BALANCE SUMMARY
# =============================================================================

@routes.route('/balance-summary')
@admin_required
def balance_summary_page() -> Any:
    load_monitor_config = dict(APP_CONFIG.get('worker_load_monitor', {}))
    modality = resolve_modality_from_request()
    return render_template(
        'balance_summary.html',
        modality=modality,
        skills=SKILL_COLUMNS,
        skill_settings=SKILL_SETTINGS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_settings=MODALITY_SETTINGS,
        load_monitor_config=load_monitor_config,
        ui_colors=APP_CONFIG.get('ui_colors', {}),
        is_admin=True,
    )


# =============================================================================
# WORKER LOAD MONITOR
# =============================================================================

@routes.route('/worker-load')
@admin_required
def worker_load_monitor() -> Any:
    """Worker load monitoring page with simple/advanced views."""
    load_monitor_config = dict(APP_CONFIG.get('worker_load_monitor', {}))
    modality = resolve_modality_from_request()
    initial_mode = (request.args.get('mode') or '').strip().lower()
    if initial_mode not in {'simple', 'advanced-weight', 'advanced-count', 'flow', 'recent'}:
        initial_mode = (load_monitor_config.get('default_view') or 'simple').strip().lower()
    if initial_mode not in {'simple', 'advanced-weight', 'advanced-count', 'flow', 'recent'}:
        initial_mode = 'simple'

    skill_modality_weights = {
        mod: {
            skill: round(float(get_skill_modality_weight(skill, mod)), 4)
            for skill in SKILL_COLUMNS
        }
        for mod in allowed_modalities
    }

    return render_template(
        'worker_load_monitor.html',
        modality=modality,
        skills=SKILL_COLUMNS,
        skill_settings=SKILL_SETTINGS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_settings=MODALITY_SETTINGS,
        load_monitor_config=load_monitor_config,
        initial_mode=initial_mode,
        skill_modality_weights=skill_modality_weights,
        ui_colors=APP_CONFIG.get('ui_colors', {}),
        is_admin=True
    )


@routes.route('/api/worker-load/data', methods=['GET'])
@admin_required
def get_worker_load_data() -> Any:
    """API endpoint returning all worker load data for monitoring."""
    current_dt = get_local_now()
    global_hours_map = calculate_global_work_hours_now(current_dt)

    # Collect all unique workers across all modalities
    all_workers = {}  # canonical_id -> {name, shift_info, modality_data}

    for modality in allowed_modalities:
        d = modality_data[modality]
        df = d.get('working_hours_df')
        if df is None or df.empty:
            continue

        mod_assignments = global_worker_data.get('assignments_per_mod', {}).get(modality, {}) or {}

        for idx, row in df.iterrows():
            worker_name = row['PPL']
            canonical_id = get_canonical_worker_id(worker_name)

            if canonical_id not in all_workers:
                hours_worked_now = round(float(global_hours_map.get(canonical_id, 0.0)), 4)
                global_weight = round(float(get_global_weighted_count(canonical_id)), 4)
                all_workers[canonical_id] = {
                    'name': worker_name,
                    'canonical_id': canonical_id,
                    'modalities': {},
                    'skills': {},
                    'skill_weights': {},
                    'hours_worked_now': hours_worked_now,
                    'weight_per_hour': round(global_weight / hours_worked_now, 4) if hours_worked_now > 0 else 0.0,
                    'global_weight': global_weight,
                    'global_assignments': {}
                }
            elif len(str(worker_name)) > len(str(all_workers[canonical_id]['name'])):
                all_workers[canonical_id]['name'] = worker_name

            # Store modality-specific data
            mod_data = {
                'start_time': row['start_time'].strftime('%H:%M') if pd.notnull(row.get('start_time')) else '',
                'end_time': row['end_time'].strftime('%H:%M') if pd.notnull(row.get('end_time')) else '',
                'modifier': float(row.get('Modifier', 1.0)) if pd.notnull(row.get('Modifier')) else 1.0,
                'skills': {},
                'skill_counts': {},
                'assignment_total': 0,
                'weighted_total': 0.0
            }

            # Collect skill values and counts for this modality
            for skill in SKILL_COLUMNS:
                skill_val = row.get(skill, None)
                mod_data['skills'][skill] = skill_value_to_display(skill_val)
                count = int(mod_assignments.get(canonical_id, {}).get(skill, 0) or 0)
                mod_data['skill_counts'][skill] = count
                mod_data['assignment_total'] += count

            all_workers[canonical_id]['modalities'][modality] = mod_data

    # Add global weighted counts and assignments
    for canonical_id, worker_data in all_workers.items():
        worker_data['global_weight'] = round(float(get_global_weighted_count(canonical_id)), 4)
        worker_data['global_assignments'] = get_global_assignments(canonical_id)
        hours_worked_now = round(float(global_hours_map.get(canonical_id, 0.0)), 4)
        worker_data['hours_worked_now'] = hours_worked_now
        worker_data['weight_per_hour'] = round(worker_data['global_weight'] / hours_worked_now, 4) if hours_worked_now > 0 else 0.0

        # Aggregate per-skill totals across modalities
        for skill in SKILL_COLUMNS:
            total_count = 0
            total_weight = 0.0
            for mod_key, mod_data in worker_data['modalities'].items():
                count = mod_data['skill_counts'].get(skill, 0)
                total_count += count
                if count > 0:
                    total_weight += count * get_skill_modality_weight(skill, mod_key)
            worker_data['skills'][skill] = total_count
            worker_data['skill_weights'][skill] = round(total_weight, 4)

        for modality in list(worker_data['modalities'].keys()):
            worker_data['modalities'][modality]['weighted_total'] = round(
                get_modality_weighted_count(canonical_id, modality),
                4,
            )

    # Calculate per-modality weighted totals
    modality_weights = {}
    for modality in allowed_modalities:
        modality_weights[modality] = {}
        for canonical_id, worker_data in all_workers.items():
            if modality in worker_data['modalities']:
                modality_weights[modality][canonical_id] = worker_data['modalities'][modality]['weighted_total']

    # Calculate per-skill weighted totals across modalities
    skill_weights = {skill: {} for skill in SKILL_COLUMNS}
    for canonical_id, worker_data in all_workers.items():
        for skill in SKILL_COLUMNS:
            skill_weights[skill][canonical_id] = worker_data['skill_weights'].get(skill, 0.0)

    # Get max weight for relative color coding
    max_weight = max((w['global_weight'] for w in all_workers.values()), default=0.0)
    max_weight_per_hour = max((w.get('weight_per_hour', 0.0) for w in all_workers.values()), default=0.0)
    valid_workers = [
        worker for worker in all_workers.values()
        if float(worker.get('hours_worked_now', 0.0) or 0.0) >= VALID_WORKER_THRESHOLD_HOURS
    ]
    valid_workers.sort(key=lambda worker: float(worker.get('weight_per_hour', 0.0) or 0.0))

    def _serialize_worker_summary(worker: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not worker:
            return None
        return {
            'canonical_id': worker.get('canonical_id'),
            'name': worker.get('name'),
            'hours_worked_now': round(float(worker.get('hours_worked_now', 0.0) or 0.0), 4),
            'global_weight': round(float(worker.get('global_weight', 0.0) or 0.0), 4),
            'weight_per_hour': round(float(worker.get('weight_per_hour', 0.0) or 0.0), 4),
        }

    skill_summary: dict[str, dict[str, Any]] = {}
    for skill in SKILL_COLUMNS:
        weight_total = 0.0
        hours_total = 0.0
        active_worker_count = 0
        for worker in all_workers.values():
            skill_weight = float(worker.get('skill_weights', {}).get(skill, 0.0) or 0.0)
            if skill_weight <= 0:
                continue
            weight_total += skill_weight
            hours_total += float(worker.get('hours_worked_now', 0.0) or 0.0)
            active_worker_count += 1
        skill_summary[skill] = {
            'weight_total': round(weight_total, 4),
            'hours_total': round(hours_total, 4),
            'weight_per_hour': round(weight_total / hours_total, 4) if hours_total > 0 else 0.0,
            'active_worker_count': active_worker_count,
        }

    modality_summary: dict[str, dict[str, Any]] = {}
    for modality in allowed_modalities:
        weight_total = 0.0
        hours_total = 0.0
        active_worker_count = 0
        for worker in all_workers.values():
            mod_data = worker.get('modalities', {}).get(modality)
            if not mod_data:
                continue
            mod_weight = float(mod_data.get('weighted_total', 0.0) or 0.0)
            mod_assignments = int(mod_data.get('assignment_total', 0) or 0)
            if mod_weight <= 0 and mod_assignments <= 0:
                continue
            weight_total += mod_weight
            hours_total += float(worker.get('hours_worked_now', 0.0) or 0.0)
            active_worker_count += 1
        modality_summary[modality] = {
            'weight_total': round(weight_total, 4),
            'hours_total': round(hours_total, 4),
            'weight_per_hour': round(weight_total / hours_total, 4) if hours_total > 0 else 0.0,
            'active_worker_count': active_worker_count,
        }

    return jsonify({
        'success': True,
        'workers': list(all_workers.values()),
        'modality_weights': modality_weights,
        'skill_weights': skill_weights,
        'max_weight': max_weight,
        'max_weight_per_hour': max_weight_per_hour,
        'skills': SKILL_COLUMNS,
        'modalities': allowed_modalities,
        'config': APP_CONFIG.get('worker_load_monitor', {}),
        'summary': {
            'valid_worker_threshold_hours': VALID_WORKER_THRESHOLD_HOURS,
            'global': {
                'max_worker_per_hour': _serialize_worker_summary(valid_workers[-1] if valid_workers else None),
                'min_worker_per_hour': _serialize_worker_summary(valid_workers[0] if valid_workers else None),
            },
            'skills_per_hour': skill_summary,
            'modalities_per_hour': modality_summary,
        },
    })


@routes.route('/api/worker-load/recent-distributions', methods=['GET'])
@admin_required
def get_worker_load_recent_distributions() -> Any:
    recent_events = global_worker_data.get('recent_distributions', []) or []
    if not isinstance(recent_events, list):
        recent_events = []
    events = list(reversed(recent_events))
    return jsonify({
        'success': True,
        'events': events,
        'items': events,
        'count': len(events),
        'limit': len(events),
    })
