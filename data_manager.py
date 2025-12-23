# Standard library imports
import os
import json
import copy
import shutil
import logging
from threading import Lock
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time, timedelta, date
from pathlib import Path

# Third-party imports
import pandas as pd

# Local imports
from config import (
    APP_CONFIG,
    MODALITY_SETTINGS,
    SKILL_SETTINGS,
    allowed_modalities,
    SKILL_COLUMNS,
    normalize_modality_fallback_entries,
    allowed_modalities_map,
    default_modality,
    SKILL_ROSTER_AUTO_IMPORT,
    selection_logger,
    UPLOAD_FOLDER,
    MASTER_CSV_PATH,
    STATE_FILE_PATH,
    normalize_modality
)
from utils import (
    TIME_FORMAT,
    get_local_berlin_now,
    parse_time_range,
    compute_shift_window,
    calculate_shift_duration_hours,
    validate_excel_structure,
    normalize_skill_value,
    skill_value_to_numeric,
    get_weekday_name_german,
    get_next_workday,
    coerce_float
)

# -----------------------------------------------------------
# Global State & Locks
# -----------------------------------------------------------
lock = Lock()

# Global worker data structure for cross-modality tracking
global_worker_data = {
    'worker_ids': {},  # Map of worker name variations to canonical ID
    # Single global weighted counts (consolidated across all modalities):
    'weighted_counts': {},  # {worker_id: count}
    'assignments_per_mod': {mod: {} for mod in allowed_modalities},
    'last_reset_date': None  # Global reset date tracker
}

# Modality active data (Live)
modality_data = {}
for mod in allowed_modalities:
    modality_data[mod] = {
        'working_hours_df': None,
        'info_texts': [],
        'total_work_hours': {},
        'worker_modifiers': {},
        'draw_counts': {},
        'skill_counts': {skill: {} for skill in SKILL_COLUMNS},
        'WeightedCounts': {},
        'last_uploaded_filename': f"Cortex_{mod.upper()}.xlsx",
        'default_file_path': os.path.join(UPLOAD_FOLDER, f"Cortex_{mod.upper()}.xlsx"),
        'scheduled_file_path': os.path.join(UPLOAD_FOLDER, f"Cortex_{mod.upper()}_scheduled.xlsx"),
        'last_reset_date': None
    }

# Staged data (Next Day Prep)
staged_modality_data = {}
for mod in allowed_modalities:
    staged_modality_data[mod] = {
        'working_hours_df': None,
        'info_texts': [],
        'total_work_hours': {},
        'worker_modifiers': {},
        'last_uploaded_filename': f"Cortex_{mod.upper()}_staged.xlsx",
        'staged_file_path': os.path.join(UPLOAD_FOLDER, "backups", f"Cortex_{mod.upper()}_staged.xlsx"),
        'last_modified': None,
        'last_prepped_at': None,
        'last_prepped_by': None
    }

# JSON worker skill roster (loaded dynamically)
worker_skill_json_roster = {}

# -----------------------------------------------------------
# Worker ID & Skill Roster Helpers
# -----------------------------------------------------------
def get_canonical_worker_id(worker_name: str) -> str:
    """Map worker name variations to a single canonical identifier."""
    worker_name = '' if worker_name is None else str(worker_name)
    worker_key = worker_name.strip()

    if worker_key in global_worker_data['worker_ids']:
        return global_worker_data['worker_ids'][worker_key]

    canonical_id = worker_key
    abk_match = worker_key.split('(')
    if len(abk_match) > 1 and ')' in abk_match[1]:
        abbreviation = abk_match[1].split(')')[0].strip()
        if abbreviation:
            canonical_id = abbreviation

    canonical_id = canonical_id or worker_key
    global_worker_data['worker_ids'][worker_key] = canonical_id
    return canonical_id


def get_all_workers_by_canonical_id():
    canonical_to_variations = {}
    for name, canonical in global_worker_data['worker_ids'].items():
        if canonical not in canonical_to_variations:
            canonical_to_variations[canonical] = []
        canonical_to_variations[canonical].append(name)
    return canonical_to_variations


def load_worker_skill_json() -> Dict[str, Any]:
    filename = 'worker_skill_roster.json'
    try:
        with open(filename, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
            # Update global cache
            worker_skill_json_roster.clear()
            worker_skill_json_roster.update(data)
            selection_logger.info(f"Loaded worker skill roster: {len(data)} workers")
            return data
    except FileNotFoundError:
        selection_logger.info(f"No {filename} found, using empty roster")
        worker_skill_json_roster.clear()
        return {}
    except Exception as exc:
        selection_logger.warning(f"Failed to load {filename}: {exc}")
        return {}


def save_worker_skill_json(roster_data: Dict[str, Any]) -> bool:
    filename = 'worker_skill_roster.json'
    try:
        with open(filename, 'w', encoding='utf-8') as json_file:
            json.dump(roster_data, json_file, indent=2, ensure_ascii=False)
        selection_logger.info(f"Saved worker skill roster: {len(roster_data)} workers")
        return True
    except Exception as exc:
        selection_logger.error(f"Failed to save {filename}: {exc}")
        return False


def build_valid_skills_map() -> Dict[str, List[str]]:
    """Build map of valid skills per modality (for filtering in UI)."""
    valid_skills_map: Dict[str, List[str]] = {}
    for mod, settings in MODALITY_SETTINGS.items():
        if 'valid_skills' in settings:
            valid_skills_map[mod] = settings['valid_skills']
        else:
            valid_skills_map[mod] = SKILL_COLUMNS
    return valid_skills_map


def normalize_skill_mod_key(key: str) -> str:
    """
    Normalize skill_modality key to canonical format: "skill_modality".

    Accepts both "skill_modality" and "modality_skill" formats.
    Returns canonical "skill_modality" format.

    Examples:
        "MSK_ct" → "MSK_ct"
        "ct_MSK" → "MSK_ct"
        "Notfall_mr" → "Notfall_mr"
        "mr_Notfall" → "Notfall_mr"
    """
    if '_' not in key:
        return key

    parts = key.split('_', 1)
    if len(parts) != 2:
        return key

    part1, part2 = parts

    # Check if part1 is a skill and part2 is a modality
    if part1 in SKILL_COLUMNS and part2 in allowed_modalities:
        return f"{part1}_{part2}"  # Already canonical

    # Check if part1 is a modality and part2 is a skill (reversed)
    if part1 in allowed_modalities and part2 in SKILL_COLUMNS:
        return f"{part2}_{part1}"  # Normalize to skill_modality

    # Unknown format - return as-is
    return key


def build_disabled_worker_entry() -> Dict[str, Any]:
    """
    Create a new worker entry with all Skill×Modality combinations disabled (-1).

    Format: {"skill_modality": -1, ...} (flat structure)
    Example: {"MSK_ct": -1, "MSK_mr": -1, "Notfall_ct": -1, ...}
    """
    entry: Dict[str, Any] = {}
    for skill in SKILL_COLUMNS:
        for mod in allowed_modalities:
            key = f"{skill}_{mod}"
            entry[key] = -1
    return entry


def auto_populate_skill_roster(modality_dfs: Dict[str, pd.DataFrame]) -> int:
    """
    Auto-populate skill roster with new workers found in uploaded schedules.

    New workers are added with all skills disabled (-1) by default.
    """
    roster = load_worker_skill_json()
    added_count = 0

    for modality, df in modality_dfs.items():
        if df is None or df.empty:
            continue

        for _, row in df.iterrows():
            raw_worker_id = row.get('canonical_id', row.get('PPL', ''))
            worker_id = str(raw_worker_id).strip() if pd.notna(raw_worker_id) else ''
            if not worker_id or worker_id in roster:
                continue

            roster[worker_id] = build_disabled_worker_entry()
            added_count += 1
            selection_logger.info(
                "Auto-added worker %s to skill roster with all skills disabled",
                worker_id,
            )

    if added_count > 0:
        save_worker_skill_json(roster)

    return added_count


def get_merged_worker_roster(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge YAML config roster with JSON roster.

    JSON roster has priority and completely overrides YAML entries for the same worker.
    Format: {worker_id: {'default': {skills}, 'ct': {overrides}, ...}}
    """
    # Start with YAML config
    yaml_roster = config.get('worker_roster', {})
    merged = copy.deepcopy(yaml_roster)

    # Ensure JSON is loaded
    if not worker_skill_json_roster:
        load_worker_skill_json()

    # JSON roster completely overrides YAML for each worker
    for worker_id, worker_data in worker_skill_json_roster.items():
        merged[worker_id] = copy.deepcopy(worker_data)

    return merged

# -----------------------------------------------------------
# State Persistence
# -----------------------------------------------------------
def save_state():
    try:
        state = {
            'global_worker_data': {
                'worker_ids': global_worker_data['worker_ids'],
                'weighted_counts': global_worker_data['weighted_counts'],
                'assignments_per_mod': global_worker_data['assignments_per_mod'],
                'last_reset_date': global_worker_data['last_reset_date'].isoformat() if global_worker_data['last_reset_date'] else None
            },
            'modality_data': {}
        }

        for mod in allowed_modalities:
            d = modality_data[mod]
            state['modality_data'][mod] = {
                'draw_counts': d['draw_counts'],
                'skill_counts': d['skill_counts'],
                'WeightedCounts': d['WeightedCounts'],
                'last_reset_date': d['last_reset_date'].isoformat() if d['last_reset_date'] else None,
                'last_uploaded_filename': d['last_uploaded_filename']
            }

        with open(STATE_FILE_PATH, 'w') as f:
            json.dump(state, f, indent=2)

        selection_logger.debug("State saved successfully")
    except Exception as e:
        selection_logger.error(f"Failed to save state: {str(e)}", exc_info=True)

def load_state():
    if not os.path.exists(STATE_FILE_PATH):
        selection_logger.info("No saved state found, starting fresh")
        return

    try:
        with open(STATE_FILE_PATH, 'r') as f:
            state = json.load(f)

        if 'global_worker_data' in state:
            gwd = state['global_worker_data']
            global_worker_data['worker_ids'] = gwd.get('worker_ids', {})
            if 'weighted_counts' in gwd:
                global_worker_data['weighted_counts'] = gwd.get('weighted_counts', {})
            elif 'weighted_counts_per_mod' in gwd:
                old_per_mod = gwd.get('weighted_counts_per_mod', {})
                migrated_counts = {}
                for mod_counts in old_per_mod.values():
                    for worker_id, count in mod_counts.items():
                        migrated_counts[worker_id] = migrated_counts.get(worker_id, 0.0) + count
                global_worker_data['weighted_counts'] = migrated_counts
            else:
                global_worker_data['weighted_counts'] = {}
            global_worker_data['assignments_per_mod'] = gwd.get('assignments_per_mod', {mod: {} for mod in allowed_modalities})

            last_reset_str = gwd.get('last_reset_date')
            if last_reset_str:
                global_worker_data['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()

        if 'modality_data' in state:
            for mod in allowed_modalities:
                if mod in state['modality_data']:
                    mod_state = state['modality_data'][mod]
                    modality_data[mod]['draw_counts'] = mod_state.get('draw_counts', {})
                    modality_data[mod]['skill_counts'] = mod_state.get('skill_counts', {skill: {} for skill in SKILL_COLUMNS})
                    modality_data[mod]['WeightedCounts'] = mod_state.get('WeightedCounts', {})
                    modality_data[mod]['last_uploaded_filename'] = mod_state.get('last_uploaded_filename', f"Cortex_{mod.upper()}.xlsx")

                    last_reset_str = mod_state.get('last_reset_date')
                    if last_reset_str:
                        modality_data[mod]['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()

        selection_logger.info("State loaded successfully from disk")
    except Exception as e:
        selection_logger.error(f"Failed to load state: {str(e)}", exc_info=True)

# -----------------------------------------------------------
# Core Data Calculators
# -----------------------------------------------------------
def _calculate_total_work_hours(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}

    if 'shift_duration' not in df.columns:
        return {}

    if 'counts_for_hours' in df.columns:
        hours_df = df[df['counts_for_hours'] == True]
    else:
        hours_df = df

    if hours_df.empty:
        return {}

    return hours_df.groupby('PPL')['shift_duration'].sum().to_dict()

# -----------------------------------------------------------
# File Operations (Backup, Loading)
# -----------------------------------------------------------
def backup_dataframe(modality: str, use_staged: bool = False):
    d = staged_modality_data[modality] if use_staged else modality_data[modality]
    if d['working_hours_df'] is not None:
        backup_dir = os.path.join(UPLOAD_FOLDER, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        suffix = "_staged" if use_staged else "_live"
        backup_file = os.path.join(backup_dir, f"Cortex_{modality.upper()}{suffix}.xlsx")
        try:
            df_backup = d['working_hours_df'].copy()

            if 'TIME' not in df_backup.columns and {'start_time', 'end_time'}.issubset(df_backup.columns):
                def _fmt_time(value):
                    if pd.isna(value):
                        return ''
                    return value.strftime(TIME_FORMAT) if hasattr(value, 'strftime') else str(value)

                df_backup['TIME'] = (
                    df_backup['start_time'].apply(_fmt_time) +
                    '-' +
                    df_backup['end_time'].apply(_fmt_time)
                )

            cols_to_backup = [
                col for col in df_backup.columns
                if col not in ['start_time', 'end_time', 'shift_duration', 'canonical_id']
            ]
            df_backup = df_backup[cols_to_backup].copy()

            with pd.ExcelWriter(backup_file, engine='openpyxl') as writer:
                df_backup.to_excel(writer, sheet_name='Tabelle1', index=False)
                if d.get('info_texts'):
                    df_info = pd.DataFrame({'Info': d['info_texts']})
                    df_info.to_excel(writer, sheet_name='Tabelle2', index=False)

            mode_label = "staged" if use_staged else "live"
            selection_logger.info(f"{mode_label.capitalize()} backup updated for modality {modality} at {backup_file}")

            if use_staged:
                d['last_modified'] = get_local_berlin_now()
                d['last_prepped_at'] = d['last_modified'].strftime('%d.%m.%Y %H:%M')
        except Exception as e:
            mode_label = "staged" if use_staged else "live"
            selection_logger.info(f"Error backing up {mode_label} DataFrame for modality {modality}: {e}")


def load_staged_dataframe(modality: str) -> bool:
    d = staged_modality_data[modality]
    staged_file = d['staged_file_path']
    scheduled_file = modality_data[modality]['scheduled_file_path']

    file_to_load = None
    if os.path.exists(staged_file):
        file_to_load = staged_file
    elif os.path.exists(scheduled_file):
        selection_logger.info(f"No staged file for {modality}, falling back to scheduled file: {scheduled_file}")
        file_to_load = scheduled_file
    else:
        selection_logger.info(f"No staged or scheduled file found for {modality}")
        return False

    try:
        with pd.ExcelFile(file_to_load, engine='openpyxl') as xls:
            if 'Tabelle1' in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name='Tabelle1')

                if 'TIME' in df.columns:
                    time_data = df['TIME'].apply(parse_time_range)
                    df['start_time'] = time_data.apply(lambda x: x[0])
                    df['end_time'] = time_data.apply(lambda x: x[1])
                    df['shift_duration'] = df.apply(
                        lambda row: calculate_shift_duration_hours(row['start_time'], row['end_time']),
                        axis=1
                    )

                if 'PPL' in df.columns:
                    df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

                if 'counts_for_hours' not in df.columns:
                    df['counts_for_hours'] = True

                d['working_hours_df'] = df
                d['total_work_hours'] = _calculate_total_work_hours(df)

                if 'Tabelle2' in xls.sheet_names:
                    df_info = pd.read_excel(xls, sheet_name='Tabelle2')
                    if 'Info' in df_info.columns:
                        d['info_texts'] = df_info['Info'].tolist()

                d['last_modified'] = datetime.fromtimestamp(os.path.getmtime(file_to_load))
                selection_logger.info(f"Loaded staged data for {modality} from {file_to_load}")
                return True
    except Exception as e:
        selection_logger.error(f"Error loading staged data for {modality}: {e}")
        return False

    return False

# -----------------------------------------------------------
# Data Loading & Initialization
# -----------------------------------------------------------
def initialize_data(file_path: str, modality: str):
    d = modality_data[modality]
    d['draw_counts'] = {}
    d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
    d['WeightedCounts'] = {}
    global_worker_data['assignments_per_mod'][modality] = {}

    with lock:
        try:
            excel_file = pd.ExcelFile(file_path)
            if 'Tabelle1' not in excel_file.sheet_names:
                raise ValueError("Blatt 'Tabelle1' nicht gefunden")

            df = pd.read_excel(excel_file, sheet_name='Tabelle1')
            required_columns = ['PPL', 'TIME']
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
                df[skill] = df[skill].fillna(0).astype(int)

            df['shift_duration'] = df.apply(
                lambda row: calculate_shift_duration_hours(row['start_time'], row['end_time']),
                axis=1
            )

            df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

            col_order = ['PPL', 'canonical_id', 'Modifier', 'TIME', 'start_time', 'end_time', 'shift_duration', 'tasks', 'counts_for_hours']
            skill_cols = [skill for skill in SKILL_COLUMNS if skill in df.columns]
            col_order = col_order[:4] + skill_cols + col_order[4:]

            if 'tasks' not in df.columns:
                df['tasks'] = ''
            if 'counts_for_hours' not in df.columns:
                df['counts_for_hours'] = True
            
            df = df[[col for col in col_order if col in df.columns]]

            d['working_hours_df'] = df
            d['worker_modifiers'] = df.groupby('PPL')['Modifier'].first().to_dict()
            d['total_work_hours'] = _calculate_total_work_hours(df)
            unique_workers = df['PPL'].unique()
            d['draw_counts'] = {w: 0 for w in unique_workers}

            d['skill_counts'] = {}
            for skill in SKILL_COLUMNS:
                if skill in df.columns:
                    d['skill_counts'][skill] = {w: 0 for w in unique_workers}
                else:
                    d['skill_counts'][skill] = {}

            d['WeightedCounts'] = {w: 0.0 for w in unique_workers}

            if 'Tabelle2' in excel_file.sheet_names:
                d['info_texts'] = pd.read_excel(excel_file, sheet_name='Tabelle2')['Info'].tolist()
            else:
                d['info_texts'] = []

            if SKILL_ROSTER_AUTO_IMPORT:
                auto_populate_skill_roster({modality: df})

        except Exception as e:
            error_message = f"Fehler beim Laden der Excel-Datei für Modality '{modality}': {str(e)}"
            selection_logger.error(error_message)
            selection_logger.exception("Stack trace:")
            raise ValueError(error_message)

def quarantine_excel(file_path: str, reason: str) -> Optional[str]:
    if not file_path or not os.path.exists(file_path):
        return None
    invalid_dir = Path(UPLOAD_FOLDER) / 'invalid'
    invalid_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    original = Path(file_path)
    target = invalid_dir / f"{original.stem}_{timestamp}{original.suffix or '.xlsx'}"
    try:
        shutil.move(str(original), str(target))
        selection_logger.warning("Defekte Excel '%s' nach '%s' verschoben (%s)", file_path, target, reason)
        return str(target)
    except OSError as exc:
        selection_logger.warning("Excel '%s' konnte nicht verschoben werden (%s): %s", file_path, reason, exc)
        return None

def attempt_initialize_data(
    file_path: str,
    modality: str,
    *,
    remove_on_failure: bool = False,
    context: str = ''
) -> bool:
    try:
        initialize_data(file_path, modality)
        return True
    except Exception as exc:
        selection_logger.error(
            "Fehler beim Initialisieren der Datei %s für %s (%s): %s",
            file_path, modality, context or 'runtime', exc,
        )
        if remove_on_failure:
            quarantine_excel(file_path, f"{context or 'runtime'}: {exc}")
        return False

# -----------------------------------------------------------
# CRUD Schedule Operations (Shared)
# -----------------------------------------------------------
def _validate_row_index(df: pd.DataFrame, row_index: int) -> bool:
    if df is None:
        return False
    return row_index in df.index

def _get_schedule_data_dict(modality: str, use_staged: bool) -> dict:
    if use_staged:
        return staged_modality_data[modality]
    return modality_data[modality]

def _update_schedule_row(modality: str, row_index: int, updates: dict, use_staged: bool) -> tuple:
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, 'Invalid row index'

    try:
        for col, value in updates.items():
            if col in ['start_time', 'end_time']:
                df.at[row_index, col] = datetime.strptime(value, TIME_FORMAT).time()
            elif col in SKILL_COLUMNS:
                df.at[row_index, col] = normalize_skill_value(value)
            elif col == 'Modifier':
                df.at[row_index, col] = float(value)
            elif col == 'PPL':
                df.at[row_index, col] = value
                df.at[row_index, 'canonical_id'] = get_canonical_worker_id(value)
            elif col == 'tasks':
                if isinstance(value, list):
                    df.at[row_index, 'tasks'] = ', '.join(value)
                else:
                    df.at[row_index, 'tasks'] = value
            elif col == 'gaps':
                df.at[row_index, 'gaps'] = value
            elif col == 'counts_for_hours':
                df.at[row_index, 'counts_for_hours'] = bool(value)
        
        if use_staged and 'is_manual' in df.columns:
            df.at[row_index, 'is_manual'] = True

        # Recalculate shift_duration if times changed
        if 'start_time' in updates or 'end_time' in updates:
            start = df.at[row_index, 'start_time']
            end = df.at[row_index, 'end_time']
            if pd.notnull(start) and pd.notnull(end):
                start_dt = datetime.combine(datetime.today(), start)
                end_dt = datetime.combine(datetime.today(), end)
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                df.at[row_index, 'shift_duration'] = (end_dt - start_dt).seconds / 3600

                if 'TIME' in df.columns:
                    df.at[row_index, 'TIME'] = f"{start.strftime(TIME_FORMAT)}-{end.strftime(TIME_FORMAT)}"

            # Resolve any overlapping shifts for this worker (later shift wins)
            worker_name = df.at[row_index, 'PPL']
            worker_shifts = df[df['PPL'] == worker_name]
            if len(worker_shifts) > 1:
                resolved_df = resolve_overlapping_shifts_df(df)
                if len(resolved_df) != len(df):
                    selection_logger.info(
                        f"Resolved overlapping shifts for {worker_name} after edit: "
                        f"{len(df)} -> {len(resolved_df)} rows"
                    )
                data_dict['working_hours_df'] = resolved_df

        backup_dataframe(modality, use_staged=use_staged)
        return True, None

    except ValueError as e:
        return False, f'Invalid time format: {e}'
    except Exception as e:
        return False, str(e)

def _add_worker_to_schedule(modality: str, worker_data: dict, use_staged: bool) -> tuple:
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    try:
        ppl_name = worker_data.get('PPL', 'Neuer Worker (NW)')
        new_row = {
            'PPL': ppl_name,
            'canonical_id': get_canonical_worker_id(ppl_name),
            'start_time': datetime.strptime(worker_data.get('start_time', '07:00'), TIME_FORMAT).time(),
            'end_time': datetime.strptime(worker_data.get('end_time', '15:00'), TIME_FORMAT).time(),
            'Modifier': float(worker_data.get('Modifier', 1.0)),
        }

        new_row['TIME'] = f"{new_row['start_time'].strftime(TIME_FORMAT)}-{new_row['end_time'].strftime(TIME_FORMAT)}"

        for skill in SKILL_COLUMNS:
            new_row[skill] = normalize_skill_value(worker_data.get(skill, 0))

        tasks = worker_data.get('tasks', [])
        if isinstance(tasks, list):
            new_row['tasks'] = ', '.join(tasks)
        else:
            new_row['tasks'] = tasks or ''

        start_dt = datetime.combine(datetime.today(), new_row['start_time'])
        end_dt = datetime.combine(datetime.today(), new_row['end_time'])
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        new_row['shift_duration'] = (end_dt - start_dt).seconds / 3600

        new_row['counts_for_hours'] = worker_data.get('counts_for_hours', True)

        if df is None or df.empty:
            data_dict['working_hours_df'] = pd.DataFrame([new_row])
        else:
            data_dict['working_hours_df'] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        if use_staged:
            if 'is_manual' not in data_dict['working_hours_df'].columns:
                data_dict['working_hours_df']['is_manual'] = False
            new_row_idx = len(data_dict['working_hours_df']) - 1
            data_dict['working_hours_df'].at[new_row_idx, 'is_manual'] = True

        # Resolve any overlapping shifts for this worker (later shift wins)
        df = data_dict['working_hours_df']
        worker_shifts = df[df['PPL'] == ppl_name]
        if len(worker_shifts) > 1:
            resolved_df = resolve_overlapping_shifts_df(df)
            if len(resolved_df) != len(df):
                selection_logger.info(
                    f"Resolved overlapping shifts for {ppl_name} after add: "
                    f"{len(df)} -> {len(resolved_df)} rows"
                )
            data_dict['working_hours_df'] = resolved_df

        backup_dataframe(modality, use_staged=use_staged)
        new_idx = len(data_dict['working_hours_df']) - 1
        return True, new_idx, None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)

def _delete_worker_from_schedule(modality: str, row_index: int, use_staged: bool, verify_ppl: Optional[str] = None) -> tuple:
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
        gap_id = df.loc[row_index_int, 'gap_id'] if 'gap_id' in df.columns else None

        if verify_ppl and str(worker_name) != str(verify_ppl):
            return False, None, 'Row mismatch: Schedule has changed. Please reload.'

        if gap_id and pd.notnull(gap_id):
            # Delete all rows sharing the same gap_id
            data_dict['working_hours_df'] = df[df['gap_id'] != gap_id].reset_index(drop=True)
            selection_logger.info(f"Deleted linked gap rows for ID {gap_id}")
        else:
            data_dict['working_hours_df'] = df.drop(index=row_index_int).reset_index(drop=True)
            
        backup_dataframe(modality, use_staged=use_staged)
        return True, worker_name, None

    except Exception as e:
        return False, None, str(e)

def _add_gap_to_schedule(modality: str, row_index: int, gap_type: str, gap_start: str, gap_end: str, use_staged: bool) -> tuple:
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if df is not None:
        if 'gaps' not in df.columns:
            df['gaps'] = None
        if 'gap_id' not in df.columns:
            df['gap_id'] = None
        if use_staged and 'is_manual' not in df.columns:
            df['is_manual'] = False

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        row = df.loc[row_index].copy()
        worker_name = row['PPL']

        def parse_gap_list(raw_val):
            if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
                return []
            if isinstance(raw_val, list):
                return raw_val
            if isinstance(raw_val, str):
                try:
                    return json.loads(raw_val)
                except Exception:
                    return []
            return []

        def merge_gap(existing: list, new_gap: dict) -> list:
            merged = existing.copy() if existing else []
            for g in merged:
                if (
                    g.get('start') == new_gap.get('start') and
                    g.get('end') == new_gap.get('end') and
                    g.get('activity') == new_gap.get('activity')
                ):
                    return merged
            merged.append(new_gap)
            return merged

        gap_start_time = datetime.strptime(gap_start, TIME_FORMAT).time()
        gap_end_time = datetime.strptime(gap_end, TIME_FORMAT).time()

        if gap_start_time >= gap_end_time:
            return False, None, 'Gap start time must be before gap end time'

        shift_start = row['start_time']
        shift_end = row['end_time']

        base_date = datetime.today()
        shift_start_dt = datetime.combine(base_date, shift_start)
        shift_end_dt = datetime.combine(base_date, shift_end)
        gap_start_dt = datetime.combine(base_date, gap_start_time)
        gap_end_dt = datetime.combine(base_date, gap_end_time)

        gap_entry = {
            'start': gap_start_time.strftime(TIME_FORMAT),
            'end': gap_end_time.strftime(TIME_FORMAT),
            'activity': gap_type,
        }

        if gap_end_dt <= shift_start_dt or gap_start_dt >= shift_end_dt:
            return False, None, 'Gap is outside worker shift times'

        log_prefix = "STAGED: " if use_staged else ""

        if gap_start_dt <= shift_start_dt and gap_end_dt >= shift_end_dt:
            # Case 1: Gap covers entire shift
            if gap_id and 'gap_id' in df.columns:
                 data_dict['working_hours_df'] = df[df['gap_id'] != gap_id].reset_index(drop=True)
            else:
                 data_dict['working_hours_df'] = df.drop(index=row_index).reset_index(drop=True)
            
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) covers entire shift for {worker_name} - row(s) deleted")
            return True, 'deleted', None

        elif gap_start_dt <= shift_start_dt < gap_end_dt < shift_end_dt:
            df.at[row_index, 'start_time'] = gap_end_time
            df.at[row_index, 'TIME'] = f"{gap_end_time.strftime(TIME_FORMAT)}-{shift_end.strftime(TIME_FORMAT)}"
            new_start_dt = datetime.combine(base_date, gap_end_time)
            df.at[row_index, 'shift_duration'] = (shift_end_dt - new_start_dt).seconds / 3600
            df.at[row_index, 'gaps'] = json.dumps(merge_gap(parse_gap_list(row.get('gaps')), gap_entry))
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) at start for {worker_name}: new start {gap_end_time}")
            return True, 'start_adjusted', None

        elif shift_start_dt < gap_start_dt < shift_end_dt and gap_end_dt >= shift_end_dt:
            df.at[row_index, 'end_time'] = gap_start_time
            df.at[row_index, 'TIME'] = f"{shift_start.strftime(TIME_FORMAT)}-{gap_start_time.strftime(TIME_FORMAT)}"
            new_end_dt = datetime.combine(base_date, gap_start_time)
            df.at[row_index, 'shift_duration'] = (new_end_dt - shift_start_dt).seconds / 3600
            df.at[row_index, 'gaps'] = json.dumps(merge_gap(parse_gap_list(row.get('gaps')), gap_entry))
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) at end for {worker_name}: new end {gap_start_time}")
            return True, 'end_adjusted', None

        else:
            # Case 4: Gap in middle - SPLIT into two rows
            new_gap_id = f"gap_{worker_name}_{datetime.now().strftime('%H%M%S')}"
            
            df.at[row_index, 'end_time'] = gap_start_time
            df.at[row_index, 'TIME'] = f"{shift_start.strftime(TIME_FORMAT)}-{gap_start_time.strftime(TIME_FORMAT)}"
            new_end_dt = datetime.combine(base_date, gap_start_time)
            df.at[row_index, 'shift_duration'] = (new_end_dt - shift_start_dt).seconds / 3600
            df.at[row_index, 'gap_id'] = new_gap_id
            if use_staged:
                df.at[row_index, 'is_manual'] = True

            new_row = row.to_dict()
            new_row['start_time'] = gap_end_time
            new_row['end_time'] = shift_end
            new_row['TIME'] = f"{gap_end_time.strftime(TIME_FORMAT)}-{shift_end.strftime(TIME_FORMAT)}"
            new_start_dt = datetime.combine(base_date, gap_end_time)
            new_row['shift_duration'] = (shift_end_dt - new_start_dt).seconds / 3600
            new_row['gap_id'] = new_gap_id
            if use_staged:
                new_row['is_manual'] = True

            serialized_gaps = json.dumps(merge_gap(parse_gap_list(row.get('gaps')), gap_entry))
            df.at[row_index, 'gaps'] = serialized_gaps
            new_row['gaps'] = serialized_gaps

            data_dict['working_hours_df'] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) in middle for {worker_name}: split into two shifts with ID {new_gap_id}")
            return True, 'split', None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def check_and_perform_daily_reset():
    now = get_local_berlin_now()
    today = now.date()
    
    reset_time_str = APP_CONFIG.get('scheduler', {}).get('daily_reset_time', '07:30')
    try:
        reset_hour, reset_min = map(int, reset_time_str.split(':'))
        reset_time = time(reset_hour, reset_min)
    except Exception:
        reset_time = time(7, 30)

    if global_worker_data['last_reset_date'] != today and now.time() >= reset_time:
        should_reset_global = any(
            os.path.exists(modality_data[mod]['scheduled_file_path']) 
            for mod in allowed_modalities
        )
        if should_reset_global:
            global_worker_data['last_reset_date'] = today
            # Reset global weighted counts on daily reset
            global_worker_data['weighted_counts'] = {}
            save_state()
            selection_logger.info("Performed global reset based on modality scheduled uploads.")
        
    for mod, d in modality_data.items():
        if d['last_reset_date'] == today:
            continue
        if now.time() >= time(7, 30):
            if os.path.exists(d['scheduled_file_path']):
                d['draw_counts'] = {}
                d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
                d['WeightedCounts'] = {}

                context = f"daily reset {mod.upper()}"
                success = attempt_initialize_data(
                    d['scheduled_file_path'],
                    mod,
                    remove_on_failure=True,
                    context=context,
                )
                if success:
                    backup_dir = os.path.join(UPLOAD_FOLDER, "backups")
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_file = os.path.join(backup_dir, os.path.basename(d['scheduled_file_path']))
                    try:
                        shutil.move(d['scheduled_file_path'], backup_file)
                    except OSError as exc:
                        selection_logger.warning("Scheduled Datei %s konnte nicht verschoben werden: %s", d['scheduled_file_path'], exc)
                    else:
                        selection_logger.info("Scheduled daily file loaded and moved to backup for modality %s.", mod)
                    backup_dataframe(mod)
                    selection_logger.info("Live-backup updated for modality %s after daily reset.", mod)
                else:
                    selection_logger.warning("Scheduled file for %s war defekt und wurde entfernt.", mod)

            else:
                selection_logger.info(f"No scheduled file found for modality {mod}. Keeping old data.")
            d['last_reset_date'] = today
            global_worker_data['assignments_per_mod'][mod] = {}
            save_state()

# -----------------------------------------------------------
# Complex CSV Loading Logic (from medweb)
# -----------------------------------------------------------
def match_mapping_rule(activity_desc: str, rules: list) -> Optional[dict]:
    if not activity_desc:
        return None
    activity_lower = activity_desc.lower()
    for rule in rules:
        match_str = rule.get('match', '')
        if match_str.lower() in activity_lower:
            return rule
    return None

def get_worker_skill_mod_combinations(canonical_id: str, worker_roster: dict) -> dict:
    """
    Get worker's Skill×Modality combinations from roster.

    Returns flat dict: {"skill_modality": value, ...}
    Normalizes keys to canonical "skill_modality" format.
    Missing combinations default to 0 (passive).
    """
    if canonical_id not in worker_roster:
        # Worker not in roster → all combinations = 0 (passive)
        result = {}
        for skill in SKILL_COLUMNS:
            for mod in allowed_modalities:
                result[f"{skill}_{mod}"] = 0
        return result

    worker_data = worker_roster[canonical_id]
    result = {}

    # Initialize all combinations to 0
    for skill in SKILL_COLUMNS:
        for mod in allowed_modalities:
            result[f"{skill}_{mod}"] = 0

    # Apply roster values (normalize keys)
    for key, value in worker_data.items():
        normalized_key = normalize_skill_mod_key(key)
        if normalized_key in result:
            result[normalized_key] = value

    return result


def expand_skill_overrides(rule_overrides: dict) -> dict:
    """
    Expand skill_overrides shortcuts to full skill_modality combinations.

    Supports:
        - Full keys: "MSK_ct": 1 → {"MSK_ct": 1}
        - all shortcut: "all": -1 → all skill_modality combos = -1
        - Skill shortcut: "MSK": 1 → MSK_ct, MSK_mr, MSK_xray, MSK_mammo = 1
        - Modality shortcut: "ct": 1 → Notfall_ct, MSK_ct, Privat_ct, etc. = 1

    Args:
        rule_overrides: Raw skill_overrides dict from config

    Returns:
        Expanded dict with full skill_modality keys
    """
    expanded = {}

    for key, value in rule_overrides.items():
        key_lower = key.lower()

        # Check for "all" shortcut
        if key_lower == 'all':
            for skill in SKILL_COLUMNS:
                for mod in allowed_modalities:
                    expanded[f"{skill}_{mod}"] = value
            continue

        # Check if key is a skill shortcut (e.g., "MSK" → MSK_ct, MSK_mr, ...)
        if key in SKILL_COLUMNS:
            for mod in allowed_modalities:
                expanded[f"{key}_{mod}"] = value
            continue

        # Check if key is a modality shortcut (e.g., "ct" → Notfall_ct, MSK_ct, ...)
        if key_lower in allowed_modalities:
            for skill in SKILL_COLUMNS:
                expanded[f"{skill}_{key_lower}"] = value
            continue

        # Otherwise, it's a full skill_modality key - normalize it
        normalized_key = normalize_skill_mod_key(key)
        expanded[normalized_key] = value

    return expanded


def apply_skill_overrides(roster_combinations: dict, rule_overrides: dict) -> dict:
    """
    Apply CSV rule skill_overrides to roster Skill×Modality combinations.

    First expands shortcuts (all, skill-only, mod-only), then applies.
    Roster -1 (hard exclude) always wins and cannot be overridden.

    Args:
        roster_combinations: Worker's baseline skill×modality combinations
        rule_overrides: CSV rule overrides (e.g., {"MSK_ct": 1, "all": -1})

    Returns:
        Final skill×modality combinations
    """
    final = roster_combinations.copy()

    # Expand shortcuts first
    expanded_overrides = expand_skill_overrides(rule_overrides)

    for key, override_value in expanded_overrides.items():
        if key in final:
            # Roster -1 (hard exclude) always wins
            if final[key] == -1:
                continue  # Keep -1, ignore override

            # Apply override
            final[key] = override_value

    return final

def compute_time_ranges(row: pd.Series, rule: dict, target_date: datetime, config: dict) -> List[Tuple[time, time]]:
    """
    Compute time ranges from rule's inline 'times' field.

    Structure supports day-specific times:
        times:
            default: "07:00-15:00"
            Montag: "08:00-16:00"
            Freitag: "07:00-13:00"
    """
    times_config = rule.get('times', {})

    if not times_config:
        # No times specified - use default
        return [(time(7, 0), time(15, 0))]

    # Get German weekday name for day-specific lookup
    weekday_name = get_weekday_name_german(target_date)

    # Check for day-specific time first, then 'friday' alias, then default
    if weekday_name in times_config:
        time_str = times_config[weekday_name]
    elif weekday_name == 'Freitag' and 'friday' in times_config:
        time_str = times_config['friday']
    else:
        time_str = times_config.get('default', '07:00-15:00')

    try:
        start_str, end_str = time_str.split('-')
        start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
        end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
        return [(start_time, end_time)]
    except Exception:
        return [(time(7, 0), time(15, 0))]


def extract_modalities_from_skill_overrides(skill_overrides: dict) -> List[str]:
    """
    Extract unique modalities from skill_overrides keys.

    Keys are in format "Skill_modality" (e.g., "MSK_ct", "Notfall_mr").
    Returns list of unique modalities found.
    """
    modalities = set()
    for key in skill_overrides.keys():
        normalized = normalize_skill_mod_key(key)
        if '_' in normalized:
            parts = normalized.split('_', 1)
            if len(parts) == 2:
                mod = parts[1].lower()
                if mod in allowed_modalities:
                    modalities.add(mod)
    return list(modalities)


def parse_gap_times(times_config: dict, weekday_name: str) -> List[Tuple[time, time]]:
    """
    Parse gap times for a specific weekday.

    Uses unified 'times' field (same as shifts).
    Supports both single string and array formats:
        times:
            Montag: "10:00-11:00"              # Single time
            Dienstag:                          # Array format
                - "10:00-11:00"
                - "14:00-15:00"
            default: "09:00-10:00"             # Optional default

    Returns list of (start_time, end_time) tuples.
    """
    if not times_config:
        return []

    # Check for day-specific times first, then default
    if weekday_name in times_config:
        day_times = times_config[weekday_name]
    elif 'default' in times_config:
        day_times = times_config['default']
    else:
        return []

    gaps = []

    # Handle both single string and array formats
    if isinstance(day_times, str):
        time_ranges = [day_times]
    elif isinstance(day_times, list):
        time_ranges = day_times
    else:
        return []

    for time_range_str in time_ranges:
        try:
            start_str, end_str = time_range_str.split('-')
            start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
            end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
            gaps.append((start_time, end_time))
        except Exception as e:
            selection_logger.warning(f"Could not parse gap time range '{time_range_str}': {e}")
            continue

    return gaps

def build_ppl_from_row(row: pd.Series, cols: Optional[dict] = None) -> str:
    name_col = cols.get('employee_name', 'Name des Mitarbeiters') if cols else 'Name des Mitarbeiters'
    code_col = cols.get('employee_code', 'Code des Mitarbeiters') if cols else 'Code des Mitarbeiters'
    name = str(row.get(name_col, 'Unknown'))
    code = str(row.get(code_col, 'UNK'))
    return f"{name} ({code})"

def apply_exclusions_to_shifts(work_shifts: List[dict], exclusions: List[dict], target_date: date) -> List[dict]:
    if not exclusions:
        return work_shifts

    result_shifts = []

    for shift in work_shifts:
        shift_start = shift['start_time']
        shift_end = shift['end_time']

        shift_start_dt = datetime.combine(target_date, shift_start)
        shift_end_dt = datetime.combine(target_date, shift_end)
        if shift_end_dt < shift_start_dt:
            shift_end_dt += timedelta(days=1)

        overlapping_exclusions = []
        for excl in exclusions:
            excl_start = excl['start_time']
            excl_end = excl['end_time']

            excl_start_dt = datetime.combine(target_date, excl_start)
            excl_end_dt = datetime.combine(target_date, excl_end)
            if excl_end_dt < excl_start_dt:
                excl_end_dt += timedelta(days=1)

            if excl_start_dt < shift_end_dt and excl_end_dt > shift_start_dt:
                overlapping_exclusions.append((excl_start_dt, excl_end_dt))

        if not overlapping_exclusions:
            result_shifts.append(shift)
            continue

        overlapping_exclusions.sort(key=lambda x: x[0])

        current_start = shift_start_dt
        for excl_start_dt, excl_end_dt in overlapping_exclusions:
            if current_start < excl_start_dt:
                segment_start = current_start.time()
                segment_end = excl_start_dt.time()
                segment_timedelta = excl_start_dt - current_start

                if segment_timedelta >= timedelta(minutes=6):
                    result_shifts.append({
                        **shift,
                        'start_time': segment_start,
                        'end_time': segment_end,
                        'shift_duration': segment_timedelta.total_seconds() / 3600
                    })

            current_start = max(current_start, excl_end_dt)

        if current_start < shift_end_dt:
            segment_start = current_start.time()
            segment_end = shift_end_dt.time()
            segment_timedelta = shift_end_dt - current_start

            if segment_timedelta >= timedelta(minutes=6):
                result_shifts.append({
                    **shift,
                    'start_time': segment_start,
                    'end_time': segment_end,
                    'shift_duration': segment_timedelta.total_seconds() / 3600
                })

    return result_shifts


def resolve_overlapping_shifts(shifts: List[dict], target_date: date) -> List[dict]:
    """
    Resolve overlapping shifts for the same worker.

    When two shifts overlap, the later shift wins:
    - Prior shift's end time is cropped to the beginning of the later shift
    - If a shift is completely covered by a later shift, it's removed
    - Shifts are sorted by start time first, then processed

    Args:
        shifts: List of shift dicts with 'PPL', 'start_time', 'end_time', etc.
        target_date: The target date for datetime calculations

    Returns:
        List of resolved shifts without overlaps
    """
    if not shifts or len(shifts) <= 1:
        return shifts

    # Group shifts by worker
    shifts_by_worker: Dict[str, List[dict]] = {}
    for shift in shifts:
        worker = shift.get('PPL', '')
        if worker not in shifts_by_worker:
            shifts_by_worker[worker] = []
        shifts_by_worker[worker].append(shift)

    result_shifts = []

    for worker, worker_shifts in shifts_by_worker.items():
        if len(worker_shifts) <= 1:
            result_shifts.extend(worker_shifts)
            continue

        # Sort by start time (earlier first)
        sorted_shifts = sorted(
            worker_shifts,
            key=lambda s: datetime.combine(target_date, s['start_time'])
        )

        resolved = []
        for i, current_shift in enumerate(sorted_shifts):
            current_start = current_shift['start_time']
            current_end = current_shift['end_time']

            current_start_dt = datetime.combine(target_date, current_start)
            current_end_dt = datetime.combine(target_date, current_end)
            if current_end_dt < current_start_dt:
                current_end_dt += timedelta(days=1)

            # Check all later shifts to see if they overlap
            for j in range(i + 1, len(sorted_shifts)):
                later_shift = sorted_shifts[j]
                later_start = later_shift['start_time']

                later_start_dt = datetime.combine(target_date, later_start)
                if later_start_dt < current_start_dt:
                    later_start_dt += timedelta(days=1)

                # If later shift starts before current ends, crop current end
                if later_start_dt < current_end_dt:
                    current_end_dt = later_start_dt
                    current_end = later_start

            # If shift still has positive duration, add it
            if current_end_dt > current_start_dt:
                duration_hours = (current_end_dt - current_start_dt).total_seconds() / 3600

                # Only add if duration is meaningful (at least 6 minutes)
                if duration_hours >= 0.1:
                    resolved_shift = current_shift.copy()
                    resolved_shift['end_time'] = current_end
                    resolved_shift['shift_duration'] = duration_hours

                    # Update TIME field if present
                    if 'TIME' in resolved_shift or 'start_time' in resolved_shift:
                        resolved_shift['TIME'] = f"{current_start.strftime('%H:%M')}-{current_end.strftime('%H:%M')}"

                    resolved.append(resolved_shift)
                    selection_logger.debug(
                        f"Shift for {worker}: {current_start.strftime('%H:%M')}-{current_end.strftime('%H:%M')} "
                        f"(duration: {duration_hours:.2f}h)"
                    )
                else:
                    selection_logger.info(
                        f"Removed zero-duration shift for {worker} "
                        f"(was {current_shift['start_time'].strftime('%H:%M')}-{current_shift['end_time'].strftime('%H:%M')})"
                    )

        result_shifts.extend(resolved)

    return result_shifts


def resolve_overlapping_shifts_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resolve overlapping shifts in a DataFrame.

    When two shifts overlap for the same worker, the later shift wins:
    - Prior shift's end time is cropped to the beginning of the later shift
    - Gaps (missing time) always win - they are not filled

    Args:
        df: DataFrame with 'PPL', 'start_time', 'end_time' columns

    Returns:
        DataFrame with resolved shifts (no overlaps)
    """
    if df is None or df.empty:
        return df

    if 'PPL' not in df.columns or 'start_time' not in df.columns or 'end_time' not in df.columns:
        return df

    # Use today as base date for datetime calculations
    base_date = datetime.today().date()

    # Convert to list of dicts for processing
    shifts = df.to_dict('records')

    # Resolve overlaps
    resolved_shifts = resolve_overlapping_shifts(shifts, base_date)

    if not resolved_shifts:
        return pd.DataFrame(columns=df.columns)

    # Convert back to DataFrame
    result_df = pd.DataFrame(resolved_shifts)

    # Preserve column order from original
    cols = [c for c in df.columns if c in result_df.columns]
    extra_cols = [c for c in result_df.columns if c not in cols]
    result_df = result_df[cols + extra_cols]

    return result_df


def build_working_hours_from_medweb(
    csv_path: str,
    target_date: datetime,
    config: dict
) -> Dict[str, pd.DataFrame]:
    """
    Build working hours DataFrames from medweb CSV.

    New unified structure:
    - Shifts have 'times' (day-specific) and 'skill_overrides' (REQUIRED)
    - Modalities are DERIVED from skill_overrides keys
    - Shifts can have embedded 'gaps' for team-specific gaps
    - Standalone gaps support arrays of times per day
    - Day plan building: later shift ends prior, gaps always win
    - Standalone gaps with no shift create "unavailable" entries
    """
    try:
        try:
            medweb_df = pd.read_csv(csv_path, sep=',', encoding='utf-8')
        except UnicodeDecodeError:
            medweb_df = pd.read_csv(csv_path, sep=',', encoding='latin1')
    except Exception:
        try:
            try:
                medweb_df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                medweb_df = pd.read_csv(csv_path, sep=';', encoding='latin1')
        except Exception as e:
            raise ValueError(f"Fehler beim Laden der CSV: {e}")

    def parse_german_date(date_val):
        if pd.isna(date_val):
            return None
        date_str = str(date_val).strip()
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        try:
            return pd.to_datetime(date_str, dayfirst=True).date()
        except Exception:
            return None

    vendor_mapping = config.get('medweb_mapping', {})
    cols = vendor_mapping.get('columns', {
        'date': 'Datum',
        'activity': 'Beschreibung der Aktivität',
        'employee_name': 'Name des Mitarbeiters',
        'employee_code': 'Code des Mitarbeiters'
    })

    medweb_df['Datum_parsed'] = medweb_df[cols.get('date', 'Datum')].apply(parse_german_date)
    target_date_obj = target_date.date() if hasattr(target_date, 'date') else target_date

    parsed_dates = medweb_df['Datum_parsed'].dropna().unique().tolist()
    selection_logger.debug(f"CSV dates parsed: {parsed_dates}, target: {target_date_obj}, type: {type(target_date_obj)}")

    day_df = medweb_df[medweb_df['Datum_parsed'] == target_date_obj]

    if day_df.empty:
        selection_logger.warning(f"No rows found for date {target_date_obj}. Available: {parsed_dates}")
        return {}

    mapping_rules = vendor_mapping.get('rules', [])
    worker_roster = get_merged_worker_roster(config)

    selection_logger.debug(f"Found {len(day_df)} rows for target date, {len(mapping_rules)} mapping rules")

    weekday_name = get_weekday_name_german(target_date_obj)

    rows_per_modality = {mod: [] for mod in allowed_modalities}
    exclusions_per_worker: Dict[str, List[dict]] = {}
    workers_with_shifts: set = set()
    unmatched_activities = []

    # FIRST PASS: Collect all shifts and gaps for each worker
    for _, row in day_df.iterrows():
        activity_desc = str(row.get(cols.get('activity', 'Beschreibung der Aktivität'), ''))
        rule = match_mapping_rule(activity_desc, mapping_rules)
        if not rule:
            unmatched_activities.append(activity_desc)
            continue

        ppl_str = build_ppl_from_row(row, cols=cols)
        canonical_id = get_canonical_worker_id(ppl_str)
        rule_type = rule.get('type', 'shift')

        # Handle GAP rules (standalone gaps)
        if rule_type == 'gap':
            # Use 'times' field (unified structure)
            times_config = rule.get('times', {})
            gap_times = parse_gap_times(times_config, weekday_name)

            if not gap_times:
                continue

            if canonical_id not in exclusions_per_worker:
                exclusions_per_worker[canonical_id] = []

            for gap_start, gap_end in gap_times:
                exclusions_per_worker[canonical_id].append({
                    'start_time': gap_start,
                    'end_time': gap_end,
                    'activity': activity_desc,
                    'ppl_str': ppl_str
                })

                selection_logger.info(
                    f"Time exclusion for {ppl_str} ({weekday_name}): "
                    f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({activity_desc})"
                )
            continue

        # Handle SHIFT rules
        if rule_type != 'shift':
            continue

        # Get skill_overrides - REQUIRED for shifts
        skill_overrides = rule.get('skill_overrides', {})

        if not skill_overrides:
            selection_logger.warning(
                f"Shift rule '{rule.get('match', '')}' missing skill_overrides - skipping"
            )
            continue

        # Derive modalities from skill_overrides keys (e.g., MSK_ct → ct)
        target_modalities = extract_modalities_from_skill_overrides(skill_overrides)
        target_modalities = [m for m in target_modalities if m in allowed_modalities]

        if not target_modalities:
            selection_logger.warning(
                f"Shift rule '{rule.get('match', '')}' has no valid modalities in skill_overrides - skipping"
            )
            continue

        workers_with_shifts.add(canonical_id)

        # Get worker's Skill×Modality combinations from roster (all combinations)
        roster_combinations = get_worker_skill_mod_combinations(canonical_id, worker_roster)

        # Apply skill_overrides (roster -1 always wins, shortcuts are expanded)
        final_combinations = apply_skill_overrides(roster_combinations, skill_overrides)

        time_ranges = compute_time_ranges(row, rule, target_date, config)

        # Handle embedded gaps in shift rule (team-specific gaps)
        embedded_gaps = rule.get('gaps', {})
        embedded_gap_times = parse_gap_times(embedded_gaps, weekday_name)

        if embedded_gap_times:
            if canonical_id not in exclusions_per_worker:
                exclusions_per_worker[canonical_id] = []

            for gap_start, gap_end in embedded_gap_times:
                exclusions_per_worker[canonical_id].append({
                    'start_time': gap_start,
                    'end_time': gap_end,
                    'activity': f"{activity_desc} (gap)",
                    'ppl_str': ppl_str
                })
                selection_logger.info(
                    f"Embedded gap for {ppl_str} ({weekday_name}): "
                    f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({activity_desc})"
                )

        for modality in target_modalities:
            # Extract skills for THIS modality from combinations
            modality_skills = {}
            for skill in SKILL_COLUMNS:
                combo_key = f"{skill}_{modality}"
                modality_skills[skill] = final_combinations.get(combo_key, 0)

            for start_time, end_time in time_ranges:
                start_dt = datetime.combine(target_date_obj, start_time)
                end_dt = datetime.combine(target_date_obj, end_time)
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                duration_hours = (end_dt - start_dt).total_seconds() / 3600

                rule_modifier = rule.get('modifier', 1.0)
                hours_counting_config = config.get('balancer', {}).get('hours_counting', {})
                if 'counts_for_hours' in rule:
                    counts_for_hours = rule['counts_for_hours']
                else:
                    counts_for_hours = hours_counting_config.get('shift_default', True)

                rows_per_modality[modality].append({
                    'PPL': ppl_str,
                    'canonical_id': canonical_id,
                    'start_time': start_time,
                    'end_time': end_time,
                    'shift_duration': duration_hours,
                    'Modifier': rule_modifier,
                    'tasks': activity_desc,
                    'counts_for_hours': counts_for_hours,
                    **modality_skills
                })

    # SECOND PASS: Create "unavailable" entries for workers with gaps but no shifts
    for canonical_id, exclusions in exclusions_per_worker.items():
        if canonical_id in workers_with_shifts:
            continue  # Will be handled in gap application

        # Worker has only gaps, no shifts → create "unavailable" entry
        for excl in exclusions:
            ppl_str = excl.get('ppl_str', f'Unknown ({canonical_id})')
            gap_start = excl['start_time']
            gap_end = excl['end_time']
            activity = excl['activity']

            start_dt = datetime.combine(target_date_obj, gap_start)
            end_dt = datetime.combine(target_date_obj, gap_end)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            duration_hours = (end_dt - start_dt).total_seconds() / 3600

            # Create an entry in all modalities (or just first one) with all skills = -1
            unavailable_skills = {skill: -1 for skill in SKILL_COLUMNS}

            # Add to first modality (could be all, but one is enough for visibility)
            first_mod = allowed_modalities[0] if allowed_modalities else 'ct'
            rows_per_modality[first_mod].append({
                'PPL': ppl_str,
                'canonical_id': canonical_id,
                'start_time': gap_start,
                'end_time': gap_end,
                'shift_duration': duration_hours,
                'Modifier': 1.0,
                'tasks': f"[Unavailable] {activity}",
                'counts_for_hours': False,
                'gaps': json.dumps([{
                    'start': gap_start.strftime(TIME_FORMAT),
                    'end': gap_end.strftime(TIME_FORMAT),
                    'activity': activity
                }]),
                **unavailable_skills
            })

            selection_logger.info(
                f"Created unavailable entry for {ppl_str} ({weekday_name}): "
                f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({activity})"
            )

    # THIRD PASS: Apply gaps to shifts (gaps always win)
    if exclusions_per_worker:
        selection_logger.info(f"Applying time exclusions for {len(exclusions_per_worker)} workers on {weekday_name}")

        for modality in rows_per_modality:
            if not rows_per_modality[modality]:
                continue

            shifts_by_worker: Dict[str, List[dict]] = {}
            for shift in rows_per_modality[modality]:
                worker_id = shift['canonical_id']
                if worker_id not in shifts_by_worker:
                    shifts_by_worker[worker_id] = []
                shifts_by_worker[worker_id].append(shift)

            new_shifts = []
            for worker_id, worker_shifts in shifts_by_worker.items():
                worker_exclusions = exclusions_per_worker.get(worker_id, [])
                if worker_exclusions and worker_id in workers_with_shifts:
                    worker_shifts = apply_exclusions_to_shifts(
                        worker_shifts,
                        worker_exclusions,
                        target_date_obj
                    )

                    gaps_json = json.dumps([{
                        'start': excl['start_time'].strftime(TIME_FORMAT),
                        'end': excl['end_time'].strftime(TIME_FORMAT),
                        'activity': excl['activity']
                    } for excl in worker_exclusions])

                    for shift in worker_shifts:
                        shift['gaps'] = gaps_json

                new_shifts.extend(worker_shifts)

            rows_per_modality[modality] = new_shifts

    if unmatched_activities:
        selection_logger.debug(f"Unmatched activities: {set(unmatched_activities)}")

    # FOURTH PASS: Resolve overlapping shifts (later shift ends prior)
    for modality in rows_per_modality:
        if rows_per_modality[modality]:
            original_count = len(rows_per_modality[modality])
            rows_per_modality[modality] = resolve_overlapping_shifts(
                rows_per_modality[modality], target_date_obj
            )
            resolved_count = len(rows_per_modality[modality])
            if original_count != resolved_count:
                selection_logger.info(
                    f"Resolved overlapping shifts for {modality}: {original_count} -> {resolved_count} shifts"
                )

    result = {}
    for modality, rows in rows_per_modality.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        if 'canonical_id' in df.columns:
            df = df.drop(columns=['canonical_id'])
        result[modality] = df

    selection_logger.info(f"Loaded {sum(len(df) for df in result.values())} workers across {list(result.keys())}")
    return result

def _get_latest_modality_dfs() -> Dict[str, pd.DataFrame]:
    latest: Dict[str, pd.DataFrame] = {}
    for mod in allowed_modalities:
        staged_df = staged_modality_data.get(mod, {}).get('working_hours_df')
        live_df = modality_data.get(mod, {}).get('working_hours_df')
        df = staged_df if staged_df is not None and not staged_df.empty else live_df
        if df is not None and not df.empty:
            latest[mod] = df
    return latest

def clear_staged_data(modality: Optional[str] = None) -> Dict[str, Any]:
    cleared = []
    modalities_to_clear = [modality] if modality else allowed_modalities

    for mod in modalities_to_clear:
        if mod in staged_modality_data:
            old_df = staged_modality_data[mod].get('working_hours_df')
            row_count = len(old_df) if old_df is not None else 0

            staged_modality_data[mod]['working_hours_df'] = None
            staged_modality_data[mod]['info_texts'] = []
            staged_modality_data[mod]['total_work_hours'] = {}
            staged_modality_data[mod]['worker_modifiers'] = {}
            staged_modality_data[mod]['last_modified'] = None

            if row_count > 0:
                cleared.append({'modality': mod, 'rows_cleared': row_count})

    return {'cleared': cleared, 'total_modalities': len(cleared)}


def preload_next_workday(csv_path: str, config: dict) -> dict:
    """Load data from master CSV for the next workday and save to scheduled files."""
    try:
        next_day = get_next_workday()

        modality_dfs = build_working_hours_from_medweb(
            csv_path,
            next_day,
            config
        )

        if not modality_dfs:
            date_str = next_day.strftime('%Y-%m-%d')
            return {
                'success': False,
                'target_date': date_str,
                'message': f'Keine Cortex-Daten für {date_str} gefunden'
            }

        saved_modalities = []
        total_workers = 0

        for modality, df in modality_dfs.items():
            d = modality_data[modality]
            target_path = d['scheduled_file_path']

            try:
                export_df = df.copy()
                export_df['TIME'] = export_df['start_time'].apply(lambda x: x.strftime(TIME_FORMAT)) + '-' + \
                                    export_df['end_time'].apply(lambda x: x.strftime(TIME_FORMAT))

                with pd.ExcelWriter(target_path, engine='openpyxl') as writer:
                    export_df.to_excel(writer, sheet_name='Tabelle1', index=False)

                selection_logger.info(f"Scheduled file saved for {modality} at {target_path}")
                saved_modalities.append(modality)
                total_workers += len(df['PPL'].unique())

            except Exception as e:
                selection_logger.error(f"Failed to save scheduled file for {modality}: {str(e)}")

        if not saved_modalities:
            return {
                'success': False,
                'target_date': next_day.strftime('%Y-%m-%d'),
                'message': 'Fehler beim Speichern der Preload-Dateien'
            }

        date_str = next_day.strftime('%Y-%m-%d')
        return {
            'success': True,
            'target_date': date_str,
            'modalities_loaded': saved_modalities,
            'total_workers': total_workers,
            'message': f'Preload erfolgreich gespeichert (wird am {date_str} aktiviert)'
        }

    except Exception as e:
        selection_logger.error(f"Error in preload_next_workday: {str(e)}", exc_info=True)
        return {
            'success': False,
            'target_date': get_next_workday().strftime('%Y-%m-%d'),
            'message': f'Fehler beim Preload: {str(e)}'
        }

