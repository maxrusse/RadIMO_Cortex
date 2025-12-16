# Flask imports
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

# Standard library imports
import copy
import json
import logging
import os
import re
import shutil
from datetime import datetime, time, timedelta, date
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

# Third-party imports
import pandas as pd
import pytz
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from logging.handlers import RotatingFileHandler

os.makedirs('logs', exist_ok=True)

selection_logger = logging.getLogger('selection')
selection_logger.setLevel(logging.INFO)

handler = RotatingFileHandler('logs/selection.log', maxBytes=10_000_000, backupCount=3)
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
selection_logger.addHandler(handler)


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.static_folder = 'static'
# Set a secret key for sessions (make sure to set a secure key in production)
app.secret_key = 'your-maxsecret-key'


if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Master CSV path for auto-preload
MASTER_CSV_PATH = os.path.join(app.config['UPLOAD_FOLDER'], 'master_medweb.csv')

lock = Lock()

# Scheduler for auto-preload (initialized later after modality_data is loaded)
scheduler = None

# JSON worker skill roster (loaded from worker_skill_overrides.json)
# Takes priority over YAML config.worker_skill_roster
worker_skill_json_roster = {}

# -----------------------------------------------------------
# Global constants & modality-/skill-specific factors
# -----------------------------------------------------------

# Modalities and skills are loaded entirely from config.yaml - no hardcoded defaults

DEFAULT_ADMIN_PASSWORD = 'change_pw_for_live'

DEFAULT_BALANCER = {
    'enabled': True,
    'min_assignments_per_skill': 5,
    'imbalance_threshold_pct': 30,
    'allow_fallback_on_imbalance': True,
}


def _normalize_modality_fallback_entries(
    entries: Any,
    source_modality: str,
    valid_modalities: List[str],
) -> List[Any]:
    normalized: List[Any] = []
    if not isinstance(entries, list):
        return normalized

    valid_set = {m.lower(): m for m in valid_modalities}
    source_key = source_modality.lower()

    def _resolve(value: str) -> Optional[str]:
        key = value.lower()
        if key == source_key:
            return None
        return valid_set.get(key)

    for entry in entries:
        if isinstance(entry, list):
            group: List[str] = []
            seen: set = set()
            for candidate in entry:
                if not isinstance(candidate, str):
                    continue
                resolved = _resolve(candidate)
                if resolved and resolved not in seen:
                    group.append(resolved)
                    seen.add(resolved)
            if group:
                normalized.append(group)
        elif isinstance(entry, str):
            resolved = _resolve(entry)
            if resolved:
                normalized.append(resolved)

    return normalized


def _coerce_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_raw_config() -> Dict[str, Any]:
    try:
        with open('config.yaml', 'r', encoding='utf-8') as config_file:
            return yaml.safe_load(config_file) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        selection_logger.warning("Failed to load config.yaml: %s", exc)
        return {}


def load_worker_skill_json() -> Dict[str, Any]:
    """
    Load worker skill overrides from JSON file.
    Single file - no staged/live separation for skill roster.
    """
    filename = 'worker_skill_roster.json'
    try:
        with open(filename, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
            selection_logger.info(f"Loaded worker skill roster: {len(data)} workers")
            return data
    except FileNotFoundError:
        selection_logger.info(f"No {filename} found, using empty roster")
        return {}
    except Exception as exc:
        selection_logger.warning(f"Failed to load {filename}: {exc}")
        return {}


def save_worker_skill_json(roster_data: Dict[str, Any]) -> bool:
    """
    Save worker skill overrides to JSON file.
    Single file - no staged/live separation for skill roster.
    """
    filename = 'worker_skill_roster.json'
    try:
        with open(filename, 'w', encoding='utf-8') as json_file:
            json.dump(roster_data, json_file, indent=2, ensure_ascii=False)
        selection_logger.info(f"Saved worker skill roster: {len(roster_data)} workers")
        return True
    except Exception as exc:
        selection_logger.error(f"Failed to save {filename}: {exc}")
        return False


def auto_populate_skill_roster(modality_dfs: Dict[str, pd.DataFrame]) -> int:
    """
    Auto-populate skill roster with workers from loaded CSV data.
    Only adds new workers, doesn't modify existing entries.

    Args:
        modality_dfs: Dict of modality -> DataFrame with worker data

    Returns:
        Number of new workers added
    """
    # Load current roster
    roster = load_worker_skill_json()
    added_count = 0

    for modality, df in modality_dfs.items():
        if df is None or df.empty:
            continue

        for _, row in df.iterrows():
            worker_id = row.get('canonical_id', row.get('PPL', ''))
            if not worker_id or worker_id in roster:
                continue  # Skip if no ID or already exists

            # Create new roster entry with skills from CSV
            default_skills = {}
            for skill in SKILL_COLUMNS:
                if skill in row:
                    default_skills[skill] = int(row[skill])

            roster[worker_id] = {
                'default': default_skills,
                # Modality-specific overrides can be added manually later
            }
            added_count += 1
            selection_logger.info(f"Auto-added worker {worker_id} to skill roster with skills: {default_skills}")

    # Save updated roster
    if added_count > 0:
        save_worker_skill_json(roster)

    return added_count


def get_merged_worker_roster(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get merged worker skill roster from YAML config and JSON overrides.
    JSON takes priority over YAML.
    """
    # Start with YAML config
    yaml_roster = config.get('worker_skill_roster', {})

    # Merge with JSON roster (JSON has priority)
    merged = copy.deepcopy(yaml_roster)

    for worker_id, worker_data in worker_skill_json_roster.items():
        if worker_id in merged:
            # Merge worker data (JSON overrides YAML)
            for key, value in worker_data.items():
                if isinstance(value, dict) and key in merged[worker_id]:
                    # Deep merge for default/modality-specific sections
                    merged[worker_id][key].update(value)
                else:
                    merged[worker_id][key] = value
        else:
            # New worker only in JSON
            merged[worker_id] = copy.deepcopy(worker_data)

    return merged


def _build_app_config() -> Dict[str, Any]:
    raw_config = _load_raw_config()
    config: Dict[str, Any] = {
        'admin_password': raw_config.get('admin_password', DEFAULT_ADMIN_PASSWORD)
    }

    # Load modalities directly from config.yaml (no hardcoded defaults)
    merged_modalities: Dict[str, Dict[str, Any]] = {}
    user_modalities = raw_config.get('modalities') or {}
    if isinstance(user_modalities, dict):
        for key, mod_data in user_modalities.items():
            if isinstance(mod_data, dict):
                merged_modalities[key] = dict(mod_data)

    # Set sensible defaults for any missing modality properties
    for key, values in merged_modalities.items():
        values.setdefault('label', key.upper())
        values.setdefault('nav_color', '#004892')
        values.setdefault('hover_color', values['nav_color'])
        values.setdefault('background_color', '#f0f0f0')
        values['factor'] = _coerce_float(values.get('factor', 1.0))

    config['modalities'] = merged_modalities

    # Load skills directly from config.yaml (no hardcoded defaults)
    merged_skills: Dict[str, Dict[str, Any]] = {}
    user_skills = raw_config.get('skills') or {}
    if isinstance(user_skills, dict):
        for key, skill_data in user_skills.items():
            if isinstance(skill_data, dict):
                merged_skills[key] = dict(skill_data)

    # Set sensible defaults for any missing properties
    for key, values in merged_skills.items():
        values.setdefault('label', key)
        values.setdefault('button_color', '#004892')
        values.setdefault('text_color', '#ffffff')
        values['weight'] = _coerce_float(values.get('weight', 1.0))
        values.setdefault('optional', False)
        values.setdefault('special', False)
        values.setdefault('always_visible', True)  # Default: always visible
        values['display_order'] = _coerce_int(values.get('display_order', 0))
        slug = values.get('slug') or key.lower().replace(' ', '_')
        values['slug'] = slug
        values.setdefault('form_key', slug)

    config['skills'] = merged_skills

    balancer_settings: Dict[str, Any] = copy.deepcopy(DEFAULT_BALANCER)
    user_balancer = raw_config.get('balancer')
    if isinstance(user_balancer, dict):
        for key, value in user_balancer.items():
            balancer_settings[key] = value
    config['balancer'] = balancer_settings

    modality_fallbacks = raw_config.get('modality_fallbacks')
    normalized_fallbacks: Dict[str, List[Any]] = {}
    if isinstance(modality_fallbacks, dict):
        for mod, fallback_list in modality_fallbacks.items():
            normalized_fallbacks[mod.lower()] = _normalize_modality_fallback_entries(
                fallback_list,
                mod,
                list(merged_modalities.keys()),
            )
    config['modality_fallbacks'] = normalized_fallbacks

    # Include medweb_mapping (activity -> modality/skill mapping rules)
    medweb_mapping = raw_config.get('medweb_mapping', {})
    config['medweb_mapping'] = medweb_mapping

    # Include worker_roster
    worker_roster = raw_config.get('worker_roster', {})
    config['worker_roster'] = worker_roster

    # Include skill_modality_overrides
    skill_modality_overrides = raw_config.get('skill_modality_overrides', {})
    config['skill_modality_overrides'] = skill_modality_overrides

    # Include shift_times (from config.yaml)
    config['shift_times'] = raw_config.get('shift_times', {})

    # Skill dashboard behavior
    skill_dashboard_config = raw_config.get('skill_dashboard', {})
    if not isinstance(skill_dashboard_config, dict):
        skill_dashboard_config = {}
    config['skill_dashboard'] = {
        'hide_invalid_combinations': bool(
            skill_dashboard_config.get('hide_invalid_combinations', False)
        )
    }

    return config


APP_CONFIG = _build_app_config()
MODALITY_SETTINGS = APP_CONFIG['modalities']
SKILL_SETTINGS = APP_CONFIG['skills']
SKILL_DASHBOARD_SETTINGS = APP_CONFIG.get('skill_dashboard', {})
allowed_modalities = list(MODALITY_SETTINGS.keys())
default_modality = allowed_modalities[0] if allowed_modalities else 'ct'
modality_labels = {
    mod: settings.get('label', mod.upper())
    for mod, settings in MODALITY_SETTINGS.items()
}
modality_factors = {
    mod: settings.get('factor', 1.0)
    for mod, settings in MODALITY_SETTINGS.items()
}

# Load skill×modality weight overrides (optional)
# Allows specific skill+modality combinations to have custom weights
# instead of the default skill_weight × modality_factor calculation
skill_modality_overrides = APP_CONFIG.get('skill_modality_overrides', {})


def _build_skill_metadata(skills_config: Dict[str, Dict[str, Any]]) -> Tuple[List[str], Dict[str, str], Dict[str, str], List[Dict[str, Any]], Dict[str, float]]:
    ordered_skills = sorted(
        skills_config.items(),
        key=lambda item: (_coerce_int(item[1].get('display_order', 0)), item[0])
    )

    columns: List[str] = []
    slug_map: Dict[str, str] = {}
    form_keys: Dict[str, str] = {}
    templates: List[Dict[str, Any]] = []
    weights: Dict[str, float] = {}

    for name, data in ordered_skills:
        slug = data.get('slug') or name.lower().replace(' ', '_')
        form_key = data.get('form_key') or slug

        columns.append(name)
        slug_map[name] = slug
        form_keys[name] = form_key
        weights[name] = _coerce_float(data.get('weight', 1.0))

        templates.append({
            'name': name,
            'label': data.get('label', name),
            'slug': slug,
            'form_key': form_key,
            'button_color': data.get('button_color', '#004892'),
            'text_color': data.get('text_color', '#ffffff'),
            'optional': bool(data.get('optional', False)),
            'special': bool(data.get('special', False)),
            'always_visible': bool(data.get('always_visible', False)),
        })

    return columns, slug_map, form_keys, templates, weights


SKILL_COLUMNS, SKILL_SLUG_MAP, SKILL_FORM_KEYS, SKILL_TEMPLATES, skill_weights = _build_skill_metadata(SKILL_SETTINGS)

# Build dynamic role map from config (slug -> canonical name)
# This allows URL-friendly lowercase names like 'herz' to map to 'Herz'
ROLE_MAP = {slug.lower(): name for name, slug in SKILL_SLUG_MAP.items()}


def get_skill_modality_weight(skill: str, modality: str) -> float:
    """
    Get the weight for a skill×modality combination.

    First checks skill_modality_overrides for an explicit value.
    If not found, falls back to: skill_weight × modality_factor

    Args:
        skill: The skill name (e.g., 'Notfall', 'Herz')
        modality: The modality name (e.g., 'ct', 'mr', 'xray')

    Returns:
        The combined weight for this skill×modality combination
    """
    # Check for explicit override first
    modality_overrides = skill_modality_overrides.get(modality, {})
    if skill in modality_overrides:
        return _coerce_float(modality_overrides[skill], 1.0)

    # Fall back to default calculation: skill_weight × modality_factor
    return skill_weights.get(skill, 1.0) * modality_factors.get(modality, 1.0)


BALANCER_SETTINGS = APP_CONFIG.get('balancer', DEFAULT_BALANCER)

# Time format constant for consistent time string parsing
TIME_FORMAT = '%H:%M'

# Load exclusion routing configuration
EXCLUSION_RULES = BALANCER_SETTINGS.get('exclusion_rules', {})

RAW_MODALITY_FALLBACKS = APP_CONFIG.get('modality_fallbacks', {})
MODALITY_FALLBACK_CHAIN = {}
for mod in allowed_modalities:
    configured = RAW_MODALITY_FALLBACKS.get(mod, RAW_MODALITY_FALLBACKS.get(mod.lower(), []))
    MODALITY_FALLBACK_CHAIN[mod] = _normalize_modality_fallback_entries(
        configured,
        mod,
        allowed_modalities,
    )

# -----------------------------------------------------------
# NEW: Global worker data structure for cross-modality tracking
# -----------------------------------------------------------
global_worker_data = {
    'worker_ids': {},  # Map of worker name variations to canonical ID
    # Modality-specific weighted counts and assignments:
    'weighted_counts_per_mod': {mod: {} for mod in allowed_modalities},
    'assignments_per_mod': {mod: {} for mod in allowed_modalities},
    'last_reset_date': None  # Global reset date tracker
}

# -----------------------------------------------------------
# Global state: one "data bucket" per modality.
# -----------------------------------------------------------
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
        'last_uploaded_filename': f"Cortex_{mod.upper()}.xlsx",  # e.g. Cortex_CT.xlsx
        'default_file_path': os.path.join(app.config['UPLOAD_FOLDER'], f"Cortex_{mod.upper()}.xlsx"),
        'scheduled_file_path': os.path.join(app.config['UPLOAD_FOLDER'], f"Cortex_{mod.upper()}_scheduled.xlsx"),
        'last_reset_date': None
    }

# -----------------------------------------------------------
# State Persistence: Save/Load fairness state to prevent data loss on restart
# -----------------------------------------------------------
STATE_FILE_PATH = os.path.join(app.config['UPLOAD_FOLDER'], 'fairness_state.json')

def save_state():
    """
    Persist fairness algorithm state to disk.
    Saves draw_counts, WeightedCounts, global_worker_data, and last_reset_date.
    Called after every assignment to ensure state is not lost on restart.
    """
    try:
        state = {
            'global_worker_data': {
                'worker_ids': global_worker_data['worker_ids'],
                'weighted_counts_per_mod': global_worker_data['weighted_counts_per_mod'],
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
    """
    Load fairness algorithm state from disk on startup.
    Restores draw_counts, WeightedCounts, global_worker_data, and last_reset_date.
    """
    if not os.path.exists(STATE_FILE_PATH):
        selection_logger.info("No saved state found, starting fresh")
        return

    try:
        with open(STATE_FILE_PATH, 'r') as f:
            state = json.load(f)

        # Restore global_worker_data
        if 'global_worker_data' in state:
            gwd = state['global_worker_data']
            global_worker_data['worker_ids'] = gwd.get('worker_ids', {})
            global_worker_data['weighted_counts_per_mod'] = gwd.get('weighted_counts_per_mod', {mod: {} for mod in allowed_modalities})
            global_worker_data['assignments_per_mod'] = gwd.get('assignments_per_mod', {mod: {} for mod in allowed_modalities})

            last_reset_str = gwd.get('last_reset_date')
            if last_reset_str:
                global_worker_data['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()

        # Restore modality_data counters
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
# Staged data: separate structure for next-day planning
# -----------------------------------------------------------
staged_modality_data = {}
for mod in allowed_modalities:
    staged_modality_data[mod] = {
        'working_hours_df': None,
        'info_texts': [],
        'total_work_hours': {},
        'worker_modifiers': {},
        'last_uploaded_filename': f"Cortex_{mod.upper()}_staged.xlsx",
        'staged_file_path': os.path.join(app.config['UPLOAD_FOLDER'], "backups", f"Cortex_{mod.upper()}_staged.xlsx"),
        'last_modified': None
    }


@app.context_processor
def inject_modality_settings():
    return {
        'modalities': MODALITY_SETTINGS,
        'modality_order': allowed_modalities,
        'modality_labels': modality_labels,
        'skill_definitions': SKILL_TEMPLATES,
        'skill_order': SKILL_COLUMNS,
        'skill_labels': {s['name']: s['label'] for s in SKILL_TEMPLATES},
    }


def normalize_modality(modality_value: Optional[str]) -> str:
    if not modality_value:
        return default_modality
    modality_value = modality_value.lower()
    return modality_value if modality_value in allowed_modalities else default_modality


def resolve_modality_from_request() -> str:
    return normalize_modality(request.values.get('modality'))


def normalize_skill(skill_value: Optional[str]) -> str:
    """Validate and normalize skill parameter"""
    if not skill_value:
        return SKILL_COLUMNS[0] if SKILL_COLUMNS else 'Notfall'
    # Try exact match first
    if skill_value in SKILL_COLUMNS:
        return skill_value
    # Try case-insensitive match
    skill_value_title = skill_value.title()
    if skill_value_title in SKILL_COLUMNS:
        return skill_value_title
    # Default to first skill
    return SKILL_COLUMNS[0] if SKILL_COLUMNS else 'Notfall'


WEIGHTED_SKILL_MARKER = 'w'


def normalize_skill_value(value: Any) -> Any:
    """Normalize skill values and convert legacy weighted marker ``2`` to ``'w'``."""

    if value is None:
        return 0

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() == WEIGHTED_SKILL_MARKER:
            return WEIGHTED_SKILL_MARKER
        if cleaned == '':
            return 0
        try:
            parsed = int(float(cleaned))
        except ValueError:
            return 0
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0

    if parsed == 2:
        return WEIGHTED_SKILL_MARKER
    return parsed


def skill_value_to_numeric(value: Any) -> int:
    """Convert skill values to numeric form for comparisons (``'w'`` → 1)."""

    if value == WEIGHTED_SKILL_MARKER:
        return 1
    try:
        parsed = int(float(value))
        return 1 if parsed == 2 else parsed
    except (TypeError, ValueError):
        return 0


def is_weighted_skill(value: Any) -> bool:
    """Check whether a skill value represents a weighted/assisted assignment."""

    if value == WEIGHTED_SKILL_MARKER:
        return True
    try:
        return int(float(value)) == 2
    except (TypeError, ValueError):
        return False


def get_available_modalities_for_skill(skill: str) -> dict:
    """Return modalities to display for the given skill (currently all remain visible)."""
    return {modality: True for modality in allowed_modalities}

# -----------------------------------------------------------
# TIME / DATE HELPERS (unchanged)
# -----------------------------------------------------------
def get_local_berlin_now() -> datetime:
    tz = pytz.timezone("Europe/Berlin")
    aware_now = datetime.now(tz)
    naive_now = aware_now.replace(tzinfo=None)
    return naive_now

def parse_time_range(time_range: str) -> Tuple[time, time]:
    """
    Parse a time range string into start and end time objects.

    Args:
        time_range: Time range in format "HH:MM-HH:MM" (e.g., "08:00-16:00")

    Returns:
        Tuple of (start_time, end_time) as datetime.time objects

    Raises:
        ValueError: If time_range format is invalid

    Example:
        >>> start, end = parse_time_range("08:00-16:00")
        >>> start
        datetime.time(8, 0)
    """
    start_str, end_str = time_range.split('-')
    start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
    end_time   = datetime.strptime(end_str.strip(), '%H:%M').time()
    return start_time, end_time


def _compute_shift_window(
    start_time: time, end_time: time, reference_dt: datetime
) -> Tuple[datetime, datetime]:
    """Return normalized start/end datetimes for a shift.

    Handles overnight shifts (e.g., 22:00-06:00) by rolling the end time into
    the next day and anchoring the start date relative to the provided
    ``reference_dt`` so checks work for both the evening and early-morning
    portions of the shift.
    """

    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    ref_minutes = reference_dt.hour * 60 + reference_dt.minute

    overnight = end_minutes <= start_minutes
    if overnight:
        end_minutes += 24 * 60  # push end into the next day
        # If we're in the early-morning portion, the shift actually started
        # yesterday.
        reference_date = (
            reference_dt.date() - timedelta(days=1)
            if ref_minutes < (end_minutes - 24 * 60)
            else reference_dt.date()
        )
    else:
        reference_date = reference_dt.date()

    start_dt = datetime.combine(reference_date, start_time)
    end_dt = start_dt + timedelta(minutes=end_minutes - start_minutes)
    return start_dt, end_dt


def _is_now_in_shift(start_time: time, end_time: time, current_dt: datetime) -> bool:
    """Check whether ``current_dt`` falls inside the given shift window."""

    start_dt, end_dt = _compute_shift_window(start_time, end_time, current_dt)
    return start_dt <= current_dt <= end_dt


def _filter_active_rows(df: Optional[pd.DataFrame], current_dt: datetime) -> Optional[pd.DataFrame]:
    """Return only rows active at ``current_dt`` (supports overnight shifts)."""

    if df is None or df.empty:
        return df

    active_mask = df.apply(
        lambda row: _is_now_in_shift(row['start_time'], row['end_time'], current_dt),
        axis=1
    )
    active_df = df[active_mask].copy()
    for skill in SKILL_COLUMNS:
        if skill in active_df.columns:
            active_df[skill] = active_df[skill].apply(skill_value_to_numeric)
    return active_df


def _calculate_shift_duration_hours(start_time: time, end_time: time) -> float:
    """Calculate shift duration in hours, supporting overnight shifts."""

    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
    return (end_minutes - start_minutes) / 60.0

# -----------------------------------------------------------
# Worker identification helper functions (NEW)
# -----------------------------------------------------------
def get_canonical_worker_id(worker_name: str) -> str:
    """
    Get the canonical worker ID from any name variation.

    Maps worker name variations (e.g., "Full Name (ABK)" and "ABK") to a single
    canonical identifier for consistent tracking across the system.

    Args:
        worker_name: Worker name in any format (abbreviated or full)

    Returns:
        Canonical worker ID (usually the abbreviated form)

    Example:
        >>> get_canonical_worker_id("John Doe (JD)")
        "JD"
        >>> get_canonical_worker_id("JD")
        "JD"
    """
    if worker_name in global_worker_data['worker_ids']:
        return global_worker_data['worker_ids'][worker_name]
    
    canonical_id = worker_name
    abk_match = worker_name.strip().split('(')
    if len(abk_match) > 1 and ')' in abk_match[1]:
        abbreviation = abk_match[1].split(')')[0].strip()
        canonical_id = abbreviation  # Use abbreviation as canonical ID
    
    global_worker_data['worker_ids'][worker_name] = canonical_id
    return canonical_id

def get_all_workers_by_canonical_id():
    """
    Get a mapping of canonical worker IDs to all their name variations.
    """
    canonical_to_variations = {}
    for name, canonical in global_worker_data['worker_ids'].items():
        if canonical not in canonical_to_variations:
            canonical_to_variations[canonical] = []
        canonical_to_variations[canonical].append(name)
    return canonical_to_variations

# -----------------------------------------------------------
# Medweb CSV Ingestion (Config-Driven)
# -----------------------------------------------------------

def match_mapping_rule(activity_desc: str, rules: list) -> Optional[dict]:
    """Find first matching rule for activity description."""
    if not activity_desc:
        return None
    activity_lower = activity_desc.lower()
    for rule in rules:
        match_str = rule.get('match', '')
        if match_str.lower() in activity_lower:
            return rule
    return None

def apply_roster_overrides(
    base_skills: dict,
    canonical_id: str,
    modality: str,
    worker_roster: dict
) -> dict:
    """
    Apply per-worker skill overrides from worker_skill_roster.

    Priority (highest to lowest):
    1. Day Edit (same day / prep next day) - handled separately, always wins
    2. medweb + roster merge (this function)

    Roster rules:
    - roster -1 = ALWAYS wins (worker excluded from this skill)
    - roster 0/1 = NO effect (roster cannot upgrade, only restrict)
    - medweb defines the assignment, roster can only exclude with -1

    Examples:
    | medweb | roster | result | reason                              |
    |--------|--------|--------|-------------------------------------|
    |   1    |   1    |   1    | assigned                            |
    |   1    |   0    |   1    | assigned (roster can't downgrade)   |
    |   1    |  -1    |  -1    | roster -1 ALWAYS wins (excluded)    |
    |   0    |   1    |   0    | not assigned (roster can't upgrade) |
    |   0    |   0    |   0    | not assigned                        |
    |   0    |  -1    |  -1    | roster -1 ALWAYS wins (excluded)    |
    """
    if canonical_id not in worker_roster:
        return base_skills.copy()

    final_skills = base_skills.copy()

    def merge_skill(base_val: int, roster_val: int) -> int:
        # -1 from roster ALWAYS wins (worker cannot do this skill)
        if roster_val == -1:
            return -1
        # Roster 0 or 1 cannot change medweb assignment
        # Only -1 can override, everything else keeps medweb value
        return base_val

    # Apply default overrides (only -1 matters)
    if 'default' in worker_roster[canonical_id]:
        for skill, roster_val in worker_roster[canonical_id]['default'].items():
            if skill in final_skills:
                final_skills[skill] = merge_skill(final_skills[skill], roster_val)

    # Apply modality-specific overrides (only -1 matters, takes precedence)
    if modality in worker_roster[canonical_id]:
        for skill, roster_val in worker_roster[canonical_id][modality].items():
            if skill in final_skills:
                # Modality-specific -1 can override even if default was different
                final_skills[skill] = merge_skill(final_skills[skill], roster_val)

    return final_skills

def compute_time_ranges(
    row: pd.Series,
    rule: dict,
    target_date: datetime,
    config: dict
) -> List[Tuple[time, time]]:
    """
    Compute start/end times based on shift and date.
    Uses shift_times from config.yaml.
    """
    shift_name = rule.get('shift', 'Fruehdienst')
    shift_config = config.get('shift_times', {}).get(shift_name, {})

    if not shift_config:
        # Default fallback
        return [(time(7, 0), time(15, 0))]

    # Check for special days (Friday)
    is_friday = target_date.weekday() == 4

    if is_friday and 'friday' in shift_config:
        time_str = shift_config['friday']
    else:
        time_str = shift_config.get('default', '07:00-15:00')

    # Parse "07:00-15:00"
    try:
        start_str, end_str = time_str.split('-')
        start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
        end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
        return [(start_time, end_time)]
    except Exception:
        return [(time(7, 0), time(15, 0))]

def build_ppl_from_row(row: pd.Series) -> str:
    """Build PPL string from medweb CSV row."""
    name = str(row.get('Name des Mitarbeiters', 'Unknown'))
    code = str(row.get('Code des Mitarbeiters', 'UNK'))
    return f"{name} ({code})"

def get_weekday_name_german(target_date: date) -> str:
    """
    Get German weekday name for a date.

    Returns: Montag, Dienstag, Mittwoch, Donnerstag, Freitag, Samstag, Sonntag
    """
    weekday_names = [
        "Montag", "Dienstag", "Mittwoch", "Donnerstag",
        "Freitag", "Samstag", "Sonntag"
    ]
    return weekday_names[target_date.weekday()]

def parse_duration(duration_str: str) -> timedelta:
    """
    Parse duration string to timedelta.

    Examples:
        "1h30m" → timedelta(hours=1, minutes=30)
        "2h" → timedelta(hours=2)
        "30m" → timedelta(minutes=30)
    """
    hours = 0
    minutes = 0

    # Match hours
    h_match = re.search(r'(\d+)h', duration_str)
    if h_match:
        hours = int(h_match.group(1))

    # Match minutes
    m_match = re.search(r'(\d+)m', duration_str)
    if m_match:
        minutes = int(m_match.group(1))

    return timedelta(hours=hours, minutes=minutes)

def apply_exclusions_to_shifts(
    work_shifts: List[dict],
    exclusions: List[dict],
    target_date: date
) -> List[dict]:
    """
    Apply time exclusions to work shifts (split/truncate as needed).

    Args:
        work_shifts: List of shift dicts with start_time, end_time
        exclusions: List of exclusion dicts with start_time, end_time
        target_date: Date for datetime calculations

    Returns:
        List of modified shift dicts with exclusions applied
    """
    if not exclusions:
        return work_shifts

    result_shifts = []

    for shift in work_shifts:
        shift_start = shift['start_time']
        shift_end = shift['end_time']

        # Convert to datetime for comparison
        shift_start_dt = datetime.combine(target_date, shift_start)
        shift_end_dt = datetime.combine(target_date, shift_end)
        if shift_end_dt < shift_start_dt:
            shift_end_dt += timedelta(days=1)

        # Collect all exclusion periods that overlap with this shift
        overlapping_exclusions = []
        for excl in exclusions:
            excl_start = excl['start_time']
            excl_end = excl['end_time']

            excl_start_dt = datetime.combine(target_date, excl_start)
            excl_end_dt = datetime.combine(target_date, excl_end)
            if excl_end_dt < excl_start_dt:
                excl_end_dt += timedelta(days=1)

            # Check for overlap
            if excl_start_dt < shift_end_dt and excl_end_dt > shift_start_dt:
                overlapping_exclusions.append((excl_start_dt, excl_end_dt))

        if not overlapping_exclusions:
            # No exclusions, keep shift as-is
            result_shifts.append(shift)
            continue

        # Sort exclusions by start time
        overlapping_exclusions.sort(key=lambda x: x[0])

        # Split shift at exclusion boundaries
        current_start = shift_start_dt
        for excl_start_dt, excl_end_dt in overlapping_exclusions:
            # Add segment before exclusion (if any)
            if current_start < excl_start_dt:
                segment_start = current_start.time()
                segment_end = excl_start_dt.time()
                segment_timedelta = excl_start_dt - current_start

                # Minimum 6 minutes (360 seconds) - use timedelta for precision
                if segment_timedelta >= timedelta(minutes=6):
                    result_shifts.append({
                        **shift,
                        'start_time': segment_start,
                        'end_time': segment_end,
                        'shift_duration': segment_timedelta.total_seconds() / 3600
                    })

            # Move current_start to after exclusion
            current_start = max(current_start, excl_end_dt)

        # Add remaining segment after all exclusions (if any)
        if current_start < shift_end_dt:
            segment_start = current_start.time()
            segment_end = shift_end_dt.time()
            segment_timedelta = shift_end_dt - current_start

            # Minimum 6 minutes (360 seconds) - use timedelta for precision
            if segment_timedelta >= timedelta(minutes=6):
                result_shifts.append({
                    **shift,
                    'start_time': segment_start,
                    'end_time': segment_end,
                    'shift_duration': segment_timedelta.total_seconds() / 3600
                })

    return result_shifts

def build_working_hours_from_medweb(
    csv_path: str,
    target_date: datetime,
    config: dict
) -> Dict[str, pd.DataFrame]:
    """
    Parse medweb CSV and build working_hours_df for each modality.

    Returns:
        {
            'ct': DataFrame(PPL, start_time, end_time, shift_duration, Modifier, Normal, Notfall, ...),
            'mr': DataFrame(...),
            'xray': DataFrame(...)
        }
    """
    # Load CSV - try UTF-8 first (modern default), then latin1 (legacy)
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

    # Parse date column - handle both string and datetime formats robustly
    def parse_german_date(date_val):
        """Parse German date format DD.MM.YYYY robustly."""
        if pd.isna(date_val):
            return None
        date_str = str(date_val).strip()
        # Try German format first
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        # Fallback to pandas
        try:
            return pd.to_datetime(date_str, dayfirst=True).date()
        except Exception:
            return None

    medweb_df['Datum_parsed'] = medweb_df['Datum'].apply(parse_german_date)
    target_date_obj = target_date.date() if hasattr(target_date, 'date') else target_date

    # Debug: log date parsing results
    parsed_dates = medweb_df['Datum_parsed'].dropna().unique().tolist()
    selection_logger.debug(f"CSV dates parsed: {parsed_dates}, target: {target_date_obj}, type: {type(target_date_obj)}")

    day_df = medweb_df[medweb_df['Datum_parsed'] == target_date_obj]

    if day_df.empty:
        selection_logger.warning(f"No rows found for date {target_date_obj}. Available: {parsed_dates}")
        return {}

    # Get mapping config
    mapping_rules = config.get('medweb_mapping', {}).get('rules', [])
    worker_roster = get_merged_worker_roster(config)

    selection_logger.debug(f"Found {len(day_df)} rows for target date, {len(mapping_rules)} mapping rules")

    # Get weekday name for exclusion schedule lookup
    weekday_name = get_weekday_name_german(target_date_obj)

    # Prepare data structures
    rows_per_modality = {mod: [] for mod in allowed_modalities}
    exclusions_per_worker = {}  # {canonical_id: [{start_time, end_time, activity}, ...]}
    unmatched_activities = []

    # FIRST PASS: Process each activity (collect work shifts AND exclusions)
    for _, row in day_df.iterrows():
        activity_desc = str(row.get('Beschreibung der Aktivität', ''))

        # Match rule
        rule = match_mapping_rule(activity_desc, mapping_rules)
        if not rule:
            unmatched_activities.append(activity_desc)
            continue  # Not Cortex-relevant or not mapped

        # Build PPL and get canonical ID (needed for both work and exclusions)
        ppl_str = build_ppl_from_row(row)
        canonical_id = get_canonical_worker_id(ppl_str)

        # Check if this is a time exclusion (board, meeting, etc.)
        if rule.get('exclusion', False):
            # Get schedule for this exclusion
            schedule = rule.get('schedule', {})

            # Check if exclusion applies to today's weekday
            if weekday_name not in schedule:
                # Exclusion doesn't apply today, skip
                continue

            # Parse time range from schedule
            time_range_str = schedule[weekday_name]
            try:
                start_str, end_str = time_range_str.split('-')
                excl_start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
                excl_end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
            except Exception as e:
                selection_logger.warning(
                    f"Could not parse exclusion time range '{time_range_str}' for {activity_desc}: {e}"
                )
                continue

            # Apply prep_time if configured
            prep_time = rule.get('prep_time', {})
            if prep_time:
                # Extend exclusion start backwards (prep before)
                if 'before' in prep_time:
                    prep_before = parse_duration(prep_time['before'])
                    excl_start_dt = datetime.combine(target_date.date(), excl_start_time)
                    excl_start_dt -= prep_before
                    excl_start_time = excl_start_dt.time()

                # Extend exclusion end forwards (cleanup after)
                if 'after' in prep_time:
                    prep_after = parse_duration(prep_time['after'])
                    excl_end_dt = datetime.combine(target_date.date(), excl_end_time)
                    excl_end_dt += prep_after
                    excl_end_time = excl_end_dt.time()

            # Store exclusion for this worker
            if canonical_id not in exclusions_per_worker:
                exclusions_per_worker[canonical_id] = []

            exclusions_per_worker[canonical_id].append({
                'start_time': excl_start_time,
                'end_time': excl_end_time,
                'activity': activity_desc
            })

            selection_logger.info(
                f"Time exclusion for {ppl_str} ({weekday_name}): "
                f"{excl_start_time.strftime('%H:%M')}-{excl_end_time.strftime('%H:%M')} "
                f"({activity_desc})"
            )
            continue  # Don't add to work shifts

        # Normal work activity (not exclusion)
        # Support both single modality and multi-modality (sub-specialty teams)
        target_modalities = []

        if 'modalities' in rule:
            # Multi-modality support (e.g., MSK team across xray, ct, mr)
            raw_modalities = rule['modalities']
            if isinstance(raw_modalities, list):
                target_modalities = [normalize_modality(m) for m in raw_modalities]
            else:
                # Single modality in 'modalities' field (edge case)
                target_modalities = [normalize_modality(raw_modalities)]
        elif 'modality' in rule:
            # Backward compatible: single modality
            target_modalities = [normalize_modality(rule['modality'])]
        else:
            # No modality specified, skip
            continue

        # Filter to only allowed modalities
        target_modalities = [m for m in target_modalities if m in allowed_modalities]

        if not target_modalities:
            continue

        # Base skills from rule (same for all modalities)
        base_skills = {s: 0 for s in SKILL_COLUMNS}
        base_skills.update(rule.get('base_skills', {}))

        # Compute time ranges (same for all modalities)
        time_ranges = compute_time_ranges(row, rule, target_date, config)

        # Create entries for EACH target modality
        for modality in target_modalities:
            # Apply roster overrides (config > worker mapping) per modality
            final_skills = apply_roster_overrides(
                base_skills, canonical_id, modality, worker_roster
            )

            # Add row(s) for each time range in this modality
            for start_time, end_time in time_ranges:
                # Calculate shift duration
                start_dt = datetime.combine(target_date.date(), start_time)
                end_dt = datetime.combine(target_date.date(), end_time)
                if end_dt < start_dt:
                    end_dt += pd.Timedelta(days=1)
                duration_hours = (end_dt - start_dt).seconds / 3600

                # Get modifier from rule config (default 1.0)
                # Modifier range: 0.5, 0.75, 1.0, 1.25, 1.5 (lower = less capacity, counts more toward load)
                rule_modifier = rule.get('modifier', 1.0)

                rows_per_modality[modality].append({
                    'PPL': ppl_str,
                    'canonical_id': canonical_id,
                    'start_time': start_time,
                    'end_time': end_time,
                    'shift_duration': duration_hours,
                    'Modifier': rule_modifier,
                    'tasks': '',  # Initialize empty tasks column
                    **final_skills
                })

    # SECOND PASS: Apply exclusions to split/truncate shifts
    if exclusions_per_worker:
        selection_logger.info(
            f"Applying time exclusions for {len(exclusions_per_worker)} workers on {weekday_name}"
        )

        for modality in rows_per_modality:
            if not rows_per_modality[modality]:
                continue

            # Group shifts by worker
            shifts_by_worker = {}
            for shift in rows_per_modality[modality]:
                worker_id = shift['canonical_id']
                if worker_id not in shifts_by_worker:
                    shifts_by_worker[worker_id] = []
                shifts_by_worker[worker_id].append(shift)

            # Apply exclusions per worker and rebuild shift list
            new_shifts = []
            for worker_id, worker_shifts in shifts_by_worker.items():
                if worker_id in exclusions_per_worker:
                    # Apply exclusions to this worker's shifts
                    worker_shifts = apply_exclusions_to_shifts(
                        worker_shifts,
                        exclusions_per_worker[worker_id],
                        target_date_obj
                    )
                new_shifts.extend(worker_shifts)

            rows_per_modality[modality] = new_shifts

    # Log unmatched activities for debugging
    if unmatched_activities:
        selection_logger.debug(f"Unmatched activities (not in mapping rules): {set(unmatched_activities)}")

    # Convert to DataFrames
    result = {}
    for modality, rows in rows_per_modality.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        # Remove canonical_id column (used internally only)
        if 'canonical_id' in df.columns:
            df = df.drop(columns=['canonical_id'])
        result[modality] = df

    selection_logger.info(f"Loaded {sum(len(df) for df in result.values())} workers across {list(result.keys())}")
    return result

def get_next_workday(from_date: Optional[datetime] = None) -> datetime:
    """
    Calculate next workday.
    - If Friday: return Monday
    - Otherwise: return next day
    - Skips weekends
    """
    if from_date is None:
        from_date = get_local_berlin_now()

    # If datetime, convert to date
    if hasattr(from_date, 'date'):
        current_date = from_date.date()
    else:
        current_date = from_date

    # Calculate next day
    next_day = current_date + timedelta(days=1)

    # If next day is Saturday (5) or Sunday (6), move to Monday
    while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_day += timedelta(days=1)

    return datetime.combine(next_day, time(0, 0))

def auto_preload_job():
    """
    Background job that runs daily at 7:30 AM to preload next workday.
    Uses master CSV if available.
    """
    try:
        if not os.path.exists(MASTER_CSV_PATH):
            selection_logger.warning(f"Auto-preload skipped: No master CSV at {MASTER_CSV_PATH}")
            return

        selection_logger.info(f"Starting auto-preload from {MASTER_CSV_PATH}")

        result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG)

        if result['success']:
            selection_logger.info(
                f"Auto-preload successful: {result['target_date']}, "
                f"modalities={result['modalities_loaded']}, "
                f"workers={result['total_workers']}"
            )
        else:
            selection_logger.error(f"Auto-preload failed: {result['message']}")

    except Exception as e:
        selection_logger.error(f"Auto-preload exception: {str(e)}", exc_info=True)

def preload_next_workday(csv_path: str, config: dict) -> dict:
    """
    Preload schedule for next workday from medweb CSV.

    CRITICAL: This function ONLY saves the schedule to scheduled files.
    It does NOT update modality_data in memory to avoid wiping the current day's schedule.
    The memory update happens later via check_and_perform_daily_reset when the date actually changes.

    Returns:
        {
            'success': bool,
            'target_date': str,
            'modalities_loaded': list,
            'total_workers': int,
            'message': str
        }
    """
    try:
        # Calculate next workday
        next_day = get_next_workday()

        # Parse medweb CSV
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

        # CRITICAL FIX: Do NOT update modality_data directly.
        # Instead, save to the scheduled file path for the daily reset logic to pick up later.
        saved_modalities = []
        total_workers = 0

        for modality, df in modality_dfs.items():
            d = modality_data[modality]
            target_path = d['scheduled_file_path']

            try:
                # Prepare DataFrame for Excel export (reconstruct TIME column)
                export_df = df.copy()
                export_df['TIME'] = export_df['start_time'].apply(lambda x: x.strftime('%H:%M')) + '-' + \
                                    export_df['end_time'].apply(lambda x: x.strftime('%H:%M'))

                # Save to scheduled file path
                with pd.ExcelWriter(target_path, engine='openpyxl') as writer:
                    export_df.to_excel(writer, sheet_name='Tabelle1', index=False)

                selection_logger.info(f"Scheduled file saved for {modality} at {target_path}")
                saved_modalities.append(modality)
                total_workers += len(df['PPL'].unique())

            except Exception as e:
                selection_logger.error(f"Failed to save scheduled file for {modality}: {str(e)}")
                # Continue with other modalities even if one fails

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
        return {
            'success': False,
            'target_date': get_next_workday().strftime('%Y-%m-%d'),
            'message': f'Fehler beim Preload: {str(e)}'
        }

def validate_excel_structure(df: pd.DataFrame, required_columns) -> (bool, str):
    # Rename column "PP" to "Privat" if it exists
    if "PP" in df.columns:
        df.rename(columns={"PP": "Privat"}, inplace=True)

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        return False, f"Fehlende Spalten: {', '.join(missing_columns)}"

    # Example format checks:
    if 'TIME' in df.columns:
        try:
            df['TIME'].apply(parse_time_range)
        except Exception as e:
            return False, f"Falsches Zeitformat in Spalte 'TIME': {str(e)}"

    if 'Modifier' in df.columns:
        try:
            df['Modifier'].astype(str).str.replace(',', '.').astype(float)
        except Exception as e:
            return False, f"Modifier-Spalte ungültiges Format: {str(e)}"

    # Check integer columns for core skills
    for skill in SKILL_COLUMNS:
        if skill in df.columns:
            if not pd.api.types.is_numeric_dtype(df[skill]):
                return False, f"Spalte '{skill}' sollte numerisch sein"

    return True, ""



# -----------------------------------------------------------
# Helper functions to compute global totals across modalities
# -----------------------------------------------------------
def get_global_weighted_count(canonical_id):
    total = 0.0
    for mod in allowed_modalities:
        total += global_worker_data['weighted_counts_per_mod'][mod].get(canonical_id, 0.0)
    return total

def get_global_assignments(canonical_id):
    totals = {skill: 0 for skill in SKILL_COLUMNS}
    totals['total'] = 0
    for mod in allowed_modalities:
        mod_assignments = global_worker_data['assignments_per_mod'][mod].get(canonical_id, {})
        for skill in SKILL_COLUMNS:
            totals[skill] += mod_assignments.get(skill, 0)
        totals['total'] += mod_assignments.get('total', 0)
    return totals

# -----------------------------------------------------------
# Modality-specific work hours & weighted calculations
# -----------------------------------------------------------
def calculate_work_hours_now(current_dt: datetime, modality: str) -> dict:
    d = modality_data[modality]
    if d['working_hours_df'] is None:
        return {}
    df_copy = d['working_hours_df'].copy()

    def _calc(row):
        start_dt, end_dt = _compute_shift_window(row['start_time'], row['end_time'], current_dt)
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


# -----------------------------------------------------------
# Data Initialization per modality (based on uploaded Excel)
# -----------------------------------------------------------
def initialize_data(file_path: str, modality: str):
    d = modality_data[modality]
    # Reset all counters for this modality - complete reset
    d['draw_counts'] = {}
    d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
    d['WeightedCounts'] = {}

    # Also reset global counters specific to this modality
    global_worker_data['weighted_counts_per_mod'][modality] = {}
    global_worker_data['assignments_per_mod'][modality] = {}

    with lock:
        try:
            excel_file = pd.ExcelFile(file_path)
            if 'Tabelle1' not in excel_file.sheet_names:
                raise ValueError("Blatt 'Tabelle1' nicht gefunden")

            df = pd.read_excel(excel_file, sheet_name='Tabelle1')

            # Define required columns
            required_columns = ['PPL', 'TIME']
            # Validate Excel structure
            valid, error_msg = validate_excel_structure(df, required_columns)
            if not valid:
                raise ValueError(error_msg)

            # Handle Modifier column
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

            # Parse TIME into start and end times
            df['start_time'], df['end_time'] = zip(*df['TIME'].map(parse_time_range))

            # Ensure all configured skills exist as integer columns
            for skill in SKILL_COLUMNS:
                if skill not in df.columns:
                    df[skill] = 0
                df[skill] = df[skill].fillna(0).astype(int)

            # Compute shift_duration using the working logic:
            df['shift_duration'] = df.apply(
                lambda row: _calculate_shift_duration_hours(row['start_time'], row['end_time']),
                axis=1
            )

            # Compute canonical ID for each worker
            df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

            # Set column order as desired (include tasks column)
            col_order = ['PPL', 'canonical_id', 'Modifier', 'TIME', 'start_time', 'end_time', 'shift_duration', 'tasks']
            skill_cols = [skill for skill in SKILL_COLUMNS if skill in df.columns]
            col_order = col_order[:4] + skill_cols + col_order[4:]
            # Ensure tasks column exists
            if 'tasks' not in df.columns:
                df['tasks'] = ''
            df = df[[col for col in col_order if col in df.columns]]

            # Save the DataFrame and compute auxiliary data
            d['working_hours_df'] = df
            d['worker_modifiers'] = df.groupby('PPL')['Modifier'].first().to_dict()
            d['total_work_hours'] = df.groupby('PPL')['shift_duration'].sum().to_dict()
            unique_workers = df['PPL'].unique()
            d['draw_counts'] = {w: 0 for w in unique_workers}

            # Initialize skill counts for all workers
            d['skill_counts'] = {}
            for skill in SKILL_COLUMNS:
                if skill in df.columns:
                    d['skill_counts'][skill] = {w: 0 for w in unique_workers}
                else:
                    d['skill_counts'][skill] = {}

            d['WeightedCounts'] = {w: 0.0 for w in unique_workers}

            # Load info texts from Tabelle2 (if available)
            if 'Tabelle2' in excel_file.sheet_names:
                d['info_texts'] = pd.read_excel(excel_file, sheet_name='Tabelle2')['Info'].tolist()
            else:
                d['info_texts'] = []

        except Exception as e:
            error_message = f"Fehler beim Laden der Excel-Datei für Modality '{modality}': {str(e)}"
            selection_logger.error(error_message)
            selection_logger.exception("Stack trace:")
            raise ValueError(error_message)


def quarantine_excel(file_path: str, reason: str) -> Optional[str]:
    """Move a problematic Excel file into uploads/invalid for later inspection."""
    if not file_path or not os.path.exists(file_path):
        return None
    invalid_dir = Path(app.config['UPLOAD_FOLDER']) / 'invalid'
    invalid_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    original = Path(file_path)
    target = invalid_dir / f"{original.stem}_{timestamp}{original.suffix or '.xlsx'}"
    try:
        shutil.move(str(original), str(target))
        selection_logger.warning(
            "Defekte Excel '%s' nach '%s' verschoben (%s)", file_path, target, reason
        )
        return str(target)
    except OSError as exc:
        selection_logger.warning(
            "Excel '%s' konnte nicht verschoben werden (%s): %s", file_path, reason, exc
        )
        return None


def attempt_initialize_data(
    file_path: str,
    modality: str,
    *,
    remove_on_failure: bool = False,
    context: str = ''
) -> bool:
    """Wrapper around ``initialize_data`` that optionally quarantines bad files."""
    try:
        initialize_data(file_path, modality)
        return True
    except Exception as exc:
        selection_logger.error(
            "Fehler beim Initialisieren der Datei %s für %s (%s): %s",
            file_path,
            modality,
            context or 'runtime',
            exc,
        )
        if remove_on_failure:
            quarantine_excel(file_path, f"{context or 'runtime'}: {exc}")
        return False



# -----------------------------------------------------------
# Active Data Filtering and Weighted-Selection Logic
# -----------------------------------------------------------
def _get_effective_assignment_load(
    worker: str,
    column: str,
    modality: str,
    skill_counts: Optional[dict] = None,
) -> float:
    """Return the worker's current load for the balancer logic.

    A worker may appear "fresh" for the active column even though they have been
    helping another modality via fallback assignments.  To avoid sending the same
    person every time, we combine the local skill counter with the global weighted
    total across all modalities.  The global total already includes the
    weight/modifier math from ``update_global_assignment`` and therefore reflects
    the true amount of recent work performed by the canonical worker ID.
    """

    if skill_counts is None:
        skill_counts = modality_data[modality]['skill_counts'].get(column, {})

    local_count = skill_counts.get(worker, 0)
    canonical_id = get_canonical_worker_id(worker)
    global_weighted_total = get_global_weighted_count(canonical_id)

    # Using max() ensures that any work performed elsewhere (tracked via the
    # weighted total) counts against the minimum-balancer checks.
    return max(float(local_count), float(global_weighted_total))


def _apply_minimum_balancer(filtered_df: pd.DataFrame, column: str, modality: str) -> pd.DataFrame:
    """
    Two-phase balancer to ensure fair initial distribution:

    Phase 1 (No-Overflow Mode): Until ALL ACTIVE workers (skill >= 1) FOR THIS SKILL
    have at least min_required WEIGHTED assignments, restrict selection to only workers
    below the threshold.

    IMPORTANT:
    - Only counts workers with skill value >= 1 (active workers)
    - Workers with skill value 0 (passive) are NOT counted toward minimums
    - Uses WEIGHTED assignments (not raw counts) via _get_effective_assignment_load
    - Only checks workers who have worked today (in skill_counts)

    Phase 2 (Normal Mode): Once all ACTIVE workers with this skill have the minimum
    weighted assignments, return all currently active workers and allow normal weighted
    selection with overflow based on hours worked.

    Example: If min_required=3.0 (weighted):
    - Worker A (skill=1): 2.5 weighted → below minimum
    - Worker B (skill=1): 3.5 weighted → above minimum
    - Worker C (skill=0): 0 weighted → NOT counted (passive worker)
    → Phase 1 active (Worker A still below)
    """
    if filtered_df.empty or not BALANCER_SETTINGS.get('enabled', True):
        return filtered_df
    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)
    if min_required <= 0:
        return filtered_df

    skill_counts = modality_data[modality]['skill_counts'].get(column, {})
    if not skill_counts:
        return filtered_df

    # Get the full working_hours_df to check skill values
    working_hours_df = modality_data[modality].get('working_hours_df')
    if working_hours_df is None or column not in working_hours_df.columns:
        return filtered_df

    # Check only ACTIVE workers (skill >= 1) who have this skill
    # Passive workers (skill = 0) should NOT be counted toward minimums
    any_below_minimum = False
    for worker in skill_counts.keys():
        # Check if this worker has skill >= 1 (active) for this column
        worker_rows = working_hours_df[working_hours_df['PPL'] == worker]
        if worker_rows.empty:
            continue

        # Get skill value for this worker (take first row if multiple shifts)
        skill_value = skill_value_to_numeric(worker_rows[column].iloc[0])
        if skill_value < 1:
            # Passive worker (0) or excluded (-1), skip from minimum checks
            continue

        # This is an active worker, check their weighted assignment load
        count = _get_effective_assignment_load(worker, column, modality, skill_counts)
        if count < min_required:
            any_below_minimum = True
            break

    # Phase 2: If ALL ACTIVE workers have at least min_required, return full pool (normal mode)
    if not any_below_minimum:
        return filtered_df

    # Phase 1: Some active workers still below minimum, restrict to only those below threshold
    # This ensures no-overflow behavior until everyone has the minimum
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
    """
    Check if fallback should be triggered based on workload imbalance.

    Uses work-hour-adjusted ratios (weighted_assignments / hours_worked_so_far)
    to handle overlapping shifts correctly. This ensures imbalance detection
    is consistent with worker selection logic.
    """
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

    # Calculate work hours till now for each worker
    current_dt = get_local_berlin_now()
    hours_map = calculate_work_hours_now(current_dt, modality)

    # Calculate weighted ratios (assignments per hour worked)
    worker_ratios = []
    for worker in filtered_df['PPL'].unique():
        canonical_id = get_canonical_worker_id(worker)
        weighted_assignments = get_global_weighted_count(canonical_id)
        hours_worked = hours_map.get(canonical_id, 0)

        # Skip workers who haven't started their shift yet
        if hours_worked <= 0:
            continue

        # Protection against division by zero (should not happen here, but safe)
        if hours_worked > 0:
            ratio = weighted_assignments / hours_worked
        else:
            ratio = weighted_assignments * 2  # Fallback: high number
        worker_ratios.append(ratio)

    if len(worker_ratios) < 2:
        return False

    max_ratio = max(worker_ratios)
    min_ratio = min(worker_ratios)
    if max_ratio == 0:
        return False

    # Calculate imbalance based on ratios (consistent with worker selection)
    imbalance = (max_ratio - min_ratio) / max_ratio
    return imbalance >= (threshold_pct / 100.0)


def _attempt_column_selection(active_df: pd.DataFrame, column: str, modality: str, is_primary: bool = True):
    """
    Select workers from a specific skill column.

    Skill values:
    - 1 = Active (available for primary and fallback)
    - 0 = Passive (only available in fallback, not for primary requests)
    - -1 = Excluded (has skill but NOT available in fallback)

    Args:
        is_primary: True if selecting for primary skill, False if selecting for fallback
    """
    if column not in active_df.columns:
        return None

    # Filter based on primary vs fallback mode
    if is_primary:
        # Primary selection: only workers with value >= 1 (active workers)
        filtered_df = active_df[active_df[column] >= 1]
    else:
        # Fallback selection: workers with value >= 0 (includes passive, excludes -1)
        filtered_df = active_df[active_df[column] >= 0]

    if filtered_df.empty:
        return None
    balanced_df = _apply_minimum_balancer(filtered_df, column, modality)
    result_df = balanced_df if not balanced_df.empty else filtered_df
    result_df = result_df.copy()
    result_df['__skill_source'] = column
    return result_df


def get_next_available_worker(
    current_dt: datetime,
    role='normal',
    modality=default_modality,
    allow_fallback: bool = True,
):
    """
    Get next available worker using exclusion-based routing.

    Two-level fallback:
    1. Primary: Workers with requested skill>=0 (not -1) EXCEPT those with excluded skills=1
    2. Fallback: Workers with requested skill>=0 (ignore exclusions)
    3. None: No workers available
    """
    return _get_worker_exclusion_based(current_dt, role, modality, allow_fallback)


def _get_worker_exclusion_based(
    current_dt: datetime,
    role: str,
    modality: str,
    allow_fallback: bool,
):
    """
    Exclusion-based routing: Filter by requested skill, exclude based on rules.

    Two-level fallback:
    1. Primary: Workers with requested skill>=0 (not -1) EXCEPT those with excluded skills=1
    2. Fallback: Workers with requested skill>=0 (ignore exclusions)
    3. None: No workers available

    Example: Request Herz, exclude Chest=1 workers
      Level 1: Workers with Herz>=0 AND Chest<1 → Pick lowest ratio
      Level 2: Workers with Herz>=0 (any Chest value) → Pick lowest ratio
    """
    # Map role slug to canonical skill name (e.g., 'herz' -> 'Herz')
    role_lower = role.lower()
    if role_lower not in ROLE_MAP:
        role_lower = 'normal'
    primary_skill = ROLE_MAP[role_lower]

    # Get exclusion rules for this skill
    skill_exclusions = EXCLUSION_RULES.get(primary_skill, {})
    exclude_skills = skill_exclusions.get('exclude_skills', [])

    # Build modality search order
    modality_search = [modality] + MODALITY_FALLBACK_CHAIN.get(modality, [])

    # Flatten modality groups
    flat_modality_search = []
    for entry in modality_search:
        if isinstance(entry, list):
            flat_modality_search.extend(entry)
        else:
            flat_modality_search.append(entry)

    # Remove duplicates while preserving order
    seen_modalities = set()
    unique_modality_search = []
    for mod in flat_modality_search:
        if mod not in seen_modalities and mod in modality_data:
            seen_modalities.add(mod)
            unique_modality_search.append(mod)

    selection_logger.info(
        "Exclusion-based routing for skill %s: filter %s>=0, exclude %s=1, modalities=%s",
        primary_skill,
        primary_skill,
        exclude_skills if exclude_skills else 'none',
        unique_modality_search,
    )

    # Level 1: Try with exclusions
    candidate_pool_excluded = []

    for target_modality in unique_modality_search:
        d = modality_data[target_modality]
        if d['working_hours_df'] is None:
            continue

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            continue

        # FIRST: Filter to workers with requested skill >= 0 (exclude -1)
        if primary_skill not in active_df.columns:
            continue

        skill_filtered = active_df[active_df[primary_skill] >= 0]
        if skill_filtered.empty:
            continue

        # SECOND: Apply exclusion filter (remove workers with excluded skills=1)
        filtered_workers = skill_filtered
        for skill_to_exclude in exclude_skills:
            if skill_to_exclude in filtered_workers.columns:
                # Exclude workers with this skill active (value >= 1)
                filtered_workers = filtered_workers[filtered_workers[skill_to_exclude] < 1]

        if filtered_workers.empty:
            continue

        # Apply minimum balancer
        balanced_df = _apply_minimum_balancer(filtered_workers, primary_skill, target_modality)
        result_df = balanced_df if not balanced_df.empty else filtered_workers

        # Calculate ratios
        hours_map = calculate_work_hours_now(current_dt, target_modality)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            h = hours_map.get(canonical_id, 0)
            w = get_global_weighted_count(canonical_id)
            return w / max(h, 0.5) if h > 0 else w

        available_workers = result_df['PPL'].unique()
        if len(available_workers) == 0:
            continue

        # Get best worker for this modality
        best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
        candidate = result_df[result_df['PPL'] == best_person].iloc[0].copy()
        candidate['__modality_source'] = target_modality
        candidate['__selection_ratio'] = weighted_ratio(best_person)

        ratio = candidate.get('__selection_ratio', float('inf'))
        candidate_pool_excluded.append((ratio, candidate, primary_skill, target_modality))

    # If we found candidates with exclusions, use them
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

    # Level 2: Fallback to skill-based selection (ignore exclusions)
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
        d = modality_data[target_modality]
        if d['working_hours_df'] is None:
            continue

        active_df = _filter_active_rows(d['working_hours_df'], current_dt)
        if active_df is None or active_df.empty:
            continue

        # Try workers with requested skill>=0 (no exclusions)
        if primary_skill not in active_df.columns:
            continue

        # Filter to workers with skill>=0 (includes active and passive, excludes -1)
        skill_filtered = active_df[active_df[primary_skill] >= 0]

        if skill_filtered.empty:
            continue

        # Apply minimum balancer
        balanced_df = _apply_minimum_balancer(skill_filtered, primary_skill, target_modality)
        result_df = balanced_df if not balanced_df.empty else skill_filtered

        # Calculate ratios
        hours_map = calculate_work_hours_now(current_dt, target_modality)

        def weighted_ratio(person):
            canonical_id = get_canonical_worker_id(person)
            h = hours_map.get(canonical_id, 0)
            w = get_global_weighted_count(canonical_id)
            return w / max(h, 0.5) if h > 0 else w

        available_workers = result_df['PPL'].unique()
        if len(available_workers) == 0:
            continue

        # Get best worker for this modality
        best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
        candidate = result_df[result_df['PPL'] == best_person].iloc[0].copy()
        candidate['__modality_source'] = target_modality
        candidate['__selection_ratio'] = weighted_ratio(best_person)

        ratio = candidate.get('__selection_ratio', float('inf'))
        candidate_pool_fallback.append((ratio, candidate, primary_skill, target_modality))

    # If we found candidates in fallback, use them
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

    # Level 3: No workers available
    selection_logger.info(
        "No workers available for skill %s (tried exclusion-based and skill-based fallback)",
        primary_skill,
    )
    return None


# -----------------------------------------------------------
# Daily Reset: check (for every modality) at >= 07:30
# -----------------------------------------------------------
def check_and_perform_daily_reset():
    now = get_local_berlin_now()
    today = now.date()
    
    if global_worker_data['last_reset_date'] != today and now.time() >= time(7, 30):
        should_reset_global = any(
            os.path.exists(modality_data[mod]['scheduled_file_path']) 
            for mod in allowed_modalities
        )
        if should_reset_global:
            global_worker_data['last_reset_date'] = today
            save_state()  # Persist reset date to disk
            selection_logger.info("Performed global reset based on modality scheduled uploads.")
        
    for mod, d in modality_data.items():
        if d['last_reset_date'] == today:
            continue
        if now.time() >= time(7, 30):
            if os.path.exists(d['scheduled_file_path']):
                # Reset all counters for this modality before initializing new data
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
                    backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_file = os.path.join(backup_dir, os.path.basename(d['scheduled_file_path']))
                    try:
                        shutil.move(d['scheduled_file_path'], backup_file)
                    except OSError as exc:
                        selection_logger.warning(
                            "Scheduled Datei %s konnte nicht verschoben werden: %s",
                            d['scheduled_file_path'],
                            exc,
                        )
                    else:
                        selection_logger.info(
                            "Scheduled daily file loaded and moved to backup for modality %s.",
                            mod,
                        )
                    backup_dataframe(mod)
                    selection_logger.info(
                        "Live-backup updated for modality %s after daily reset.",
                        mod,
                    )
                else:
                    selection_logger.warning(
                        "Scheduled file for %s war defekt und wurde entfernt.",
                        mod,
                    )

            else:
                selection_logger.info(f"No scheduled file found for modality {mod}. Keeping old data.")
            d['last_reset_date'] = today
            global_worker_data['weighted_counts_per_mod'][mod] = {}
            global_worker_data['assignments_per_mod'][mod] = {}
            save_state()  # Persist reset to disk
            
@app.before_request
def before_request():
    check_and_perform_daily_reset()

# -----------------------------------------------------------
# Helper for low-duplication global update
# -----------------------------------------------------------
def _get_or_create_assignments(modality: str, canonical_id: str) -> dict:
    assignments = global_worker_data['assignments_per_mod'][modality]
    if canonical_id not in assignments:
        assignments[canonical_id] = {skill: 0 for skill in SKILL_COLUMNS}
        assignments[canonical_id]['total'] = 0
    return assignments[canonical_id]

def update_global_assignment(person: str, role: str, modality: str) -> str:
    canonical_id = get_canonical_worker_id(person)
    # Get the modifier (default 1.0). Values < 1 mean less work capacity (counts more toward load)
    # Modifier range: 0.5, 0.75, 1.0, 1.25, 1.5
    modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
    modifier = _coerce_float(modifier, 1.0)
    # Use helper that checks for skill×modality overrides first
    # Note: skill='w' is just a visual marker - weight is controlled by Modifier field
    weight = get_skill_modality_weight(role, modality) * modifier

    global_worker_data['weighted_counts_per_mod'][modality][canonical_id] = \
        global_worker_data['weighted_counts_per_mod'][modality].get(canonical_id, 0.0) + weight

    assignments = _get_or_create_assignments(modality, canonical_id)
    assignments[role] += 1
    assignments['total'] += 1

    # Persist state after every assignment to prevent data loss on restart
    save_state()

    return canonical_id

# -----------------------------------------------------------
# Helper: Live Backup of DataFrame (with staging support)
# -----------------------------------------------------------
def backup_dataframe(modality: str, use_staged: bool = False):
    """
    Writes the current working_hours_df for the given modality to a backup Excel file.
    The backup file will include:
      - "Tabelle1": containing the working_hours_df data without extra columns.
      - "Tabelle2": containing the info_texts (if available).

    This version removes the columns 'start_time', 'end_time', and 'shift_duration'.

    Args:
        modality: The modality to back up
        use_staged: If True, back up staged data. If False, back up live data.
    """
    d = staged_modality_data[modality] if use_staged else modality_data[modality]
    if d['working_hours_df'] is not None:
        backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
        os.makedirs(backup_dir, exist_ok=True)
        suffix = "_staged" if use_staged else "_live"
        backup_file = os.path.join(backup_dir, f"Cortex_{modality.upper()}{suffix}.xlsx")
        try:
            # Remove unwanted columns from backup
            cols_to_backup = [col for col in d['working_hours_df'].columns
                              if col not in ['start_time', 'end_time', 'shift_duration', 'canonical_id']]
            df_backup = d['working_hours_df'][cols_to_backup].copy()

            with pd.ExcelWriter(backup_file, engine='openpyxl') as writer:
                # Write the filtered DataFrame into sheet "Tabelle1"
                df_backup.to_excel(writer, sheet_name='Tabelle1', index=False)
                # If info_texts are available, write them into sheet "Tabelle2"
                if d.get('info_texts'):
                    df_info = pd.DataFrame({'Info': d['info_texts']})
                    df_info.to_excel(writer, sheet_name='Tabelle2', index=False)

            mode_label = "staged" if use_staged else "live"
            selection_logger.info(f"{mode_label.capitalize()} backup updated for modality {modality} at {backup_file}")

            # Update last_modified timestamp for staged data
            if use_staged:
                d['last_modified'] = get_local_berlin_now()
        except Exception as e:
            mode_label = "staged" if use_staged else "live"
            selection_logger.info(f"Error backing up {mode_label} DataFrame for modality {modality}: {e}")


def load_staged_dataframe(modality: str) -> bool:
    """
    Load staged data from file into staged_modality_data structure.

    Returns:
        True if loaded successfully, False otherwise
    """
    d = staged_modality_data[modality]
    staged_file = d['staged_file_path']

    if not os.path.exists(staged_file):
        selection_logger.info(f"No staged file found for {modality}: {staged_file}")
        return False

    try:
        # Load staged data directly from Excel file
        with pd.ExcelFile(staged_file, engine='openpyxl') as xls:
            if 'Tabelle1' in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name='Tabelle1')

                # Parse TIME column and add start_time, end_time, shift_duration
                if 'TIME' in df.columns:
                    time_data = df['TIME'].apply(parse_time_range)
                    df['start_time'] = time_data.apply(lambda x: x[0])
                    df['end_time'] = time_data.apply(lambda x: x[1])

                    # Calculate shift_duration
                    df['shift_duration'] = df.apply(
                        lambda row: _calculate_shift_duration_hours(row['start_time'], row['end_time']),
                        axis=1
                    )

                # Add canonical_id
                if 'PPL' in df.columns:
                    df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

                d['working_hours_df'] = df
                d['total_work_hours'] = df.groupby('PPL')['shift_duration'].sum().to_dict() if 'shift_duration' in df.columns else {}

                # Load info texts if available
                if 'Tabelle2' in xls.sheet_names:
                    df_info = pd.read_excel(xls, sheet_name='Tabelle2')
                    if 'Info' in df_info.columns:
                        d['info_texts'] = df_info['Info'].tolist()

                d['last_modified'] = datetime.fromtimestamp(os.path.getmtime(staged_file))
                selection_logger.info(f"Loaded staged data for {modality} from {staged_file}")
                return True
    except Exception as e:
        selection_logger.error(f"Error loading staged data for {modality}: {e}")
        return False

    return False


# -----------------------------------------------------------
# Shared helpers for schedule CRUD operations (used by both live and staged APIs)
# -----------------------------------------------------------

def _get_schedule_data_dict(modality: str, use_staged: bool) -> dict:
    """
    Get the appropriate data dictionary for a modality (live or staged).
    """
    if use_staged:
        return staged_modality_data[modality]
    return modality_data[modality]


def _validate_row_index(df: pd.DataFrame, row_index: int) -> bool:
    """
    Validate that row_index exists in the DataFrame.
    Uses DataFrame index instead of position for safety.
    """
    if df is None:
        return False
    return row_index in df.index


def _df_to_api_response(df: pd.DataFrame) -> list:
    """
    Convert a working_hours DataFrame to API response format.
    Uses to_dict('records') for better performance than iterrows.
    """
    if df is None or df.empty:
        return []

    data = []
    for idx in df.index:
        row = df.loc[idx]
        worker_data = {
            'row_index': int(idx),
            'PPL': row['PPL'],
            'start_time': row['start_time'].strftime(TIME_FORMAT) if pd.notnull(row.get('start_time')) else '',
            'end_time': row['end_time'].strftime(TIME_FORMAT) if pd.notnull(row.get('end_time')) else '',
            'Modifier': float(row.get('Modifier', 1.0)) if pd.notnull(row.get('Modifier')) else 1.0,
        }

        # Add all skill columns
        for skill in SKILL_COLUMNS:
            value = row.get(skill, 0)
            worker_data[skill] = normalize_skill_value(value) if pd.notnull(value) else 0

        # Add tasks (stored as comma-separated string or list)
        tasks_val = row.get('tasks', '')
        if isinstance(tasks_val, list):
            worker_data['tasks'] = tasks_val
        elif isinstance(tasks_val, str) and tasks_val:
            worker_data['tasks'] = [t.strip() for t in tasks_val.split(',') if t.strip()]
        else:
            worker_data['tasks'] = []

        data.append(worker_data)

    return data


def _update_schedule_row(modality: str, row_index: int, updates: dict, use_staged: bool) -> tuple:
    """
    Update a single worker row in working_hours_df.

    Args:
        modality: The modality to update
        row_index: The DataFrame index of the row to update
        updates: Dictionary of column -> value updates
        use_staged: If True, update staged data. If False, update live data.

    Returns:
        (success: bool, error_message: str or None)
    """
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, 'Invalid row index'

    try:
        for col, value in updates.items():
            if col in ['start_time', 'end_time']:
                # Parse time string
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

                # Update TIME column
                if 'TIME' in df.columns:
                    df.at[row_index, 'TIME'] = f"{start.strftime(TIME_FORMAT)}-{end.strftime(TIME_FORMAT)}"

        backup_dataframe(modality, use_staged=use_staged)
        return True, None

    except ValueError as e:
        return False, f'Invalid time format: {e}'
    except Exception as e:
        return False, str(e)


def _add_worker_to_schedule(modality: str, worker_data: dict, use_staged: bool) -> tuple:
    """
    Add a new worker row to working_hours_df.

    Args:
        modality: The modality to add worker to
        worker_data: Dictionary with worker data (PPL, start_time, end_time, skills, etc.)
        use_staged: If True, add to staged data. If False, add to live data.

    Returns:
        (success: bool, row_index: int or None, error_message: str or None)
    """
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

        # Add TIME column
        new_row['TIME'] = f"{new_row['start_time'].strftime(TIME_FORMAT)}-{new_row['end_time'].strftime(TIME_FORMAT)}"

        # Add skill columns
        for skill in SKILL_COLUMNS:
            new_row[skill] = normalize_skill_value(worker_data.get(skill, 0))

        # Add tasks
        tasks = worker_data.get('tasks', [])
        if isinstance(tasks, list):
            new_row['tasks'] = ', '.join(tasks)
        else:
            new_row['tasks'] = tasks or ''

        # Calculate shift_duration
        start_dt = datetime.combine(datetime.today(), new_row['start_time'])
        end_dt = datetime.combine(datetime.today(), new_row['end_time'])
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        new_row['shift_duration'] = (end_dt - start_dt).seconds / 3600

        # Append to DataFrame
        if df is None or df.empty:
            data_dict['working_hours_df'] = pd.DataFrame([new_row])
        else:
            data_dict['working_hours_df'] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        backup_dataframe(modality, use_staged=use_staged)

        new_idx = len(data_dict['working_hours_df']) - 1
        return True, new_idx, None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


def _delete_worker_from_schedule(modality: str, row_index: int, use_staged: bool) -> tuple:
    """
    Delete a worker row from working_hours_df.

    Args:
        modality: The modality to delete from
        row_index: The DataFrame index of the row to delete
        use_staged: If True, delete from staged data. If False, delete from live data.

    Returns:
        (success: bool, worker_name: str or None, error_message: str or None)
    """
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        worker_name = df.loc[row_index, 'PPL']
        data_dict['working_hours_df'] = df.drop(index=row_index).reset_index(drop=True)
        backup_dataframe(modality, use_staged=use_staged)
        return True, worker_name, None

    except Exception as e:
        return False, None, str(e)


def _add_gap_to_schedule(modality: str, row_index: int, gap_type: str, gap_start: str, gap_end: str, use_staged: bool) -> tuple:
    """
    Add a gap (time exclusion) to a worker's shift.
    The gap punches out time from the worker's shift.
    - If gap covers entire shift: delete the row
    - If gap at start: move start_time forward
    - If gap at end: move end_time backward
    - If gap in middle: split into two rows

    Args:
        modality: The modality to update
        row_index: The DataFrame index of the row to add gap to
        gap_type: Type of gap (e.g., 'custom', 'Board', etc.)
        gap_start: Gap start time in HH:MM format
        gap_end: Gap end time in HH:MM format
        use_staged: If True, modify staged data. If False, modify live data.

    Returns:
        (success: bool, action: str or None, error_message: str or None)
        action is one of: 'deleted', 'start_adjusted', 'end_adjusted', 'split'
    """
    data_dict = _get_schedule_data_dict(modality, use_staged)
    df = data_dict['working_hours_df']

    if not _validate_row_index(df, row_index):
        return False, None, 'Invalid row index'

    try:
        row = df.loc[row_index].copy()
        worker_name = row['PPL']

        # Parse times
        gap_start_time = datetime.strptime(gap_start, TIME_FORMAT).time()
        gap_end_time = datetime.strptime(gap_end, TIME_FORMAT).time()

        # Validate gap times
        if gap_start_time >= gap_end_time:
            return False, None, 'Gap start time must be before gap end time'

        shift_start = row['start_time']
        shift_end = row['end_time']

        # Convert to comparable datetime for calculations
        base_date = datetime.today()
        shift_start_dt = datetime.combine(base_date, shift_start)
        shift_end_dt = datetime.combine(base_date, shift_end)
        gap_start_dt = datetime.combine(base_date, gap_start_time)
        gap_end_dt = datetime.combine(base_date, gap_end_time)

        # Check if gap is within shift
        if gap_end_dt <= shift_start_dt or gap_start_dt >= shift_end_dt:
            return False, None, 'Gap is outside worker shift times'

        log_prefix = "STAGED: " if use_staged else ""

        # Case 1: Gap covers entire shift
        if gap_start_dt <= shift_start_dt and gap_end_dt >= shift_end_dt:
            data_dict['working_hours_df'] = df.drop(index=row_index).reset_index(drop=True)
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) covers entire shift for {worker_name} - row deleted")
            return True, 'deleted', None

        # Case 2: Gap at start of shift
        elif gap_start_dt <= shift_start_dt < gap_end_dt < shift_end_dt:
            df.at[row_index, 'start_time'] = gap_end_time
            df.at[row_index, 'TIME'] = f"{gap_end_time.strftime(TIME_FORMAT)}-{shift_end.strftime(TIME_FORMAT)}"
            new_start_dt = datetime.combine(base_date, gap_end_time)
            df.at[row_index, 'shift_duration'] = (shift_end_dt - new_start_dt).seconds / 3600
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) at start for {worker_name}: new start {gap_end_time}")
            return True, 'start_adjusted', None

        # Case 3: Gap at end of shift
        elif shift_start_dt < gap_start_dt < shift_end_dt and gap_end_dt >= shift_end_dt:
            df.at[row_index, 'end_time'] = gap_start_time
            df.at[row_index, 'TIME'] = f"{shift_start.strftime(TIME_FORMAT)}-{gap_start_time.strftime(TIME_FORMAT)}"
            new_end_dt = datetime.combine(base_date, gap_start_time)
            df.at[row_index, 'shift_duration'] = (new_end_dt - shift_start_dt).seconds / 3600
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) at end for {worker_name}: new end {gap_start_time}")
            return True, 'end_adjusted', None

        # Case 4: Gap in middle - split into two rows
        else:
            # Update original row to end at gap start
            df.at[row_index, 'end_time'] = gap_start_time
            df.at[row_index, 'TIME'] = f"{shift_start.strftime(TIME_FORMAT)}-{gap_start_time.strftime(TIME_FORMAT)}"
            new_end_dt = datetime.combine(base_date, gap_start_time)
            df.at[row_index, 'shift_duration'] = (new_end_dt - shift_start_dt).seconds / 3600

            # Create new row starting after gap
            new_row = row.to_dict()
            new_row['start_time'] = gap_end_time
            new_row['end_time'] = shift_end
            new_row['TIME'] = f"{gap_end_time.strftime(TIME_FORMAT)}-{shift_end.strftime(TIME_FORMAT)}"
            new_start_dt = datetime.combine(base_date, gap_end_time)
            new_row['shift_duration'] = (shift_end_dt - new_start_dt).seconds / 3600

            # Append new row
            data_dict['working_hours_df'] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            backup_dataframe(modality, use_staged=use_staged)
            selection_logger.info(f"{log_prefix}Gap ({gap_type}) in middle for {worker_name}: split into two shifts")
            return True, 'split', None

    except ValueError as e:
        return False, None, f'Invalid time format: {e}'
    except Exception as e:
        return False, None, str(e)


# -----------------------------------------------------------
# Startup: initialize each modality – zuerst das aktuelle Live-Backup, dann das Default-File
# -----------------------------------------------------------
for mod, d in modality_data.items():
    backup_dir  = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
    backup_path = os.path.join(backup_dir, f"Cortex_{mod.upper()}_live.xlsx")

    loaded = False

    if os.path.exists(backup_path):
        if attempt_initialize_data(
            backup_path,
            mod,
            remove_on_failure=True,
            context=f"startup backup {mod.upper()}",
        ):
            selection_logger.info(
                f"Initialized {mod.upper()} modality from live-backup: {backup_path}"
            )
            loaded = True
        else:
            selection_logger.info(
                f"Live-backup für {mod.upper()} war defekt und wurde entfernt."
            )

    if not loaded and os.path.exists(d['default_file_path']):
        if attempt_initialize_data(
            d['default_file_path'],
            mod,
            remove_on_failure=True,
            context=f"startup default {mod.upper()}",
        ):
            selection_logger.info(
                f"Initialized {mod.upper()} modality from default file: {d['default_file_path']}"
            )
            loaded = True
        else:
            selection_logger.info(
                f"Default-File für {mod.upper()} war defekt und wurde entfernt."
            )

    if not loaded:
        selection_logger.info(
            f"Kein verwendbares File für {mod.upper()} gefunden – starte leer."
        )
        d['working_hours_df'] = None
        d['info_texts'] = []
        d['total_work_hours'] = {}
        d['worker_modifiers'] = {}
        d['draw_counts'] = {}
        d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
        d['WeightedCounts'] = {}
        d['last_reset_date'] = None

# -----------------------------------------------------------
# Routes
# -----------------------------------------------------------
@app.route('/')
def index():
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    # Button visibility controlled by config (skill×modality):
    # Per modality: valid_skills (positive), hidden_skills (negative)
    # Per skill: valid_modalities (positive), hidden_modalities (negative)
    modality_config = MODALITY_SETTINGS.get(modality, {})
    mod_valid_skills = set(modality_config.get('valid_skills', SKILL_COLUMNS))
    mod_hidden_skills = set(modality_config.get('hidden_skills', []))

    visible_skills = []
    for skill_name in SKILL_COLUMNS:
        # Check modality-level filter
        if skill_name not in mod_valid_skills or skill_name in mod_hidden_skills:
            continue
        # Check skill-level filter
        skill_config = SKILL_SETTINGS.get(skill_name, {})
        skill_valid_mods = skill_config.get('valid_modalities')
        skill_hidden_mods = set(skill_config.get('hidden_modalities', []))
        if skill_valid_mods is not None and modality not in skill_valid_mods:
            continue
        if modality in skill_hidden_mods:
            continue
        visible_skills.append(skill_name)

    return render_template(
        'index.html',
        info_texts=d.get('info_texts', []),
        modality=modality,
        visible_skills=visible_skills,
        is_admin=session.get('admin_logged_in', False)
    )


@app.route('/by-skill')
def index_by_skill():
    """
    Skill-based view: navigate by skill, see all modalities as buttons.
    Visibility controlled by config (skill×modality filters).
    """
    skill = request.args.get('skill', SKILL_COLUMNS[0] if SKILL_COLUMNS else 'Notfall')
    skill = normalize_skill(skill)

    # Button visibility controlled by config (skill×modality):
    # Per skill: valid_modalities (positive), hidden_modalities (negative)
    # Per modality: valid_skills (positive), hidden_skills (negative)
    skill_config = SKILL_SETTINGS.get(skill, {})
    skill_valid_mods = skill_config.get('valid_modalities')
    skill_hidden_mods = set(skill_config.get('hidden_modalities', []))

    visible_modalities = []
    for mod in allowed_modalities:
        # Check skill-level filter
        if skill_valid_mods is not None and mod not in skill_valid_mods:
            continue
        if mod in skill_hidden_mods:
            continue
        # Check modality-level filter
        mod_config = MODALITY_SETTINGS.get(mod, {})
        mod_valid_skills = mod_config.get('valid_skills')
        mod_hidden_skills = set(mod_config.get('hidden_skills', []))
        if mod_valid_skills is not None and skill not in mod_valid_skills:
            continue
        if skill in mod_hidden_skills:
            continue
        visible_modalities.append(mod)

    # Get info texts from first modality (they're typically the same)
    info_texts = []
    if allowed_modalities:
        first_modality = allowed_modalities[0]
        info_texts = modality_data[first_modality].get('info_texts', [])

    return render_template(
        'index_by_skill.html',
        skill=skill,
        visible_modalities=visible_modalities,
        info_texts=info_texts
    )


def get_admin_password():
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("admin_password", "")
    except Exception as e:
        selection_logger.info("Error loading config.yaml:", e)
        return ""

def run_operational_checks(context: str = 'unknown', force: bool = False) -> dict:
    """
    Run operational readiness checks for the system.

    Args:
        context: Context string describing where checks are being run from
        force: Force re-run even if cached (currently always runs)

    Returns:
        Dictionary with:
        - results: list of check results (name, status, detail)
        - context: the context string
        - timestamp: ISO format timestamp
    """
    results = []
    now = get_local_berlin_now().isoformat()

    # Check 1: Config file exists and is readable
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        results.append({
            'name': 'Config File',
            'status': 'OK',
            'detail': 'config.yaml is readable and valid YAML'
        })
    except Exception as e:
        results.append({
            'name': 'Config File',
            'status': 'ERROR',
            'detail': f'Failed to load config.yaml: {str(e)}'
        })

    # Check 2: Admin password is set (not default)
    try:
        admin_pw = get_admin_password()
        if not admin_pw:
            results.append({
                'name': 'Admin Password',
                'status': 'WARNING',
                'detail': 'Admin password is not set in config.yaml'
            })
        elif admin_pw == 'change_pw_for_live':
            results.append({
                'name': 'Admin Password',
                'status': 'WARNING',
                'detail': 'Admin password is still set to default value - change for production!'
            })
        else:
            results.append({
                'name': 'Admin Password',
                'status': 'OK',
                'detail': 'Admin password is configured'
            })
    except Exception as e:
        results.append({
            'name': 'Admin Password',
            'status': 'ERROR',
            'detail': f'Failed to check admin password: {str(e)}'
        })

    # Check 3: Upload folder exists and is writable
    try:
        upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            results.append({
                'name': 'Upload Folder',
                'status': 'WARNING',
                'detail': f'Upload folder "{upload_folder}" does not exist (will be created on upload)'
            })
        elif not os.access(upload_folder, os.W_OK):
            results.append({
                'name': 'Upload Folder',
                'status': 'ERROR',
                'detail': f'Upload folder "{upload_folder}" is not writable'
            })
        else:
            file_count = len([f for f in os.listdir(upload_folder) if f.endswith('.xlsx')])
            results.append({
                'name': 'Upload Folder',
                'status': 'OK',
                'detail': f'Upload folder "{upload_folder}" is writable ({file_count} Excel files found)'
            })
    except Exception as e:
        results.append({
            'name': 'Upload Folder',
            'status': 'ERROR',
            'detail': f'Failed to check upload folder: {str(e)}'
        })

    # Check 4: Modalities configured
    try:
        modality_count = len(allowed_modalities)
        if modality_count == 0:
            results.append({
                'name': 'Modalities',
                'status': 'ERROR',
                'detail': 'No modalities configured in config.yaml'
            })
        else:
            results.append({
                'name': 'Modalities',
                'status': 'OK',
                'detail': f'{modality_count} modalities configured: {", ".join(allowed_modalities)}'
            })
    except Exception as e:
        results.append({
            'name': 'Modalities',
            'status': 'ERROR',
            'detail': f'Failed to check modalities: {str(e)}'
        })

    # Check 5: Skills configured
    try:
        skill_count = len(SKILL_COLUMNS)
        if skill_count == 0:
            results.append({
                'name': 'Skills',
                'status': 'ERROR',
                'detail': 'No skills configured in config.yaml'
            })
        else:
            results.append({
                'name': 'Skills',
                'status': 'OK',
                'detail': f'{skill_count} skills configured: {", ".join(SKILL_COLUMNS)}'
            })
    except Exception as e:
        results.append({
            'name': 'Skills',
            'status': 'ERROR',
            'detail': f'Failed to check skills: {str(e)}'
        })

    # Check 6: Worker data loaded
    try:
        total_workers = 0
        for mod in allowed_modalities:
            d = modality_data.get(mod, {})
            if d.get('working_hours_df') is not None:
                total_workers += len(d['working_hours_df']['PPL'].unique())

        if total_workers == 0:
            results.append({
                'name': 'Worker Data',
                'status': 'WARNING',
                'detail': 'No worker data loaded - upload an Excel file to get started'
            })
        else:
            results.append({
                'name': 'Worker Data',
                'status': 'OK',
                'detail': f'{total_workers} workers loaded across all modalities'
            })
    except Exception as e:
        results.append({
            'name': 'Worker Data',
            'status': 'ERROR',
            'detail': f'Failed to check worker data: {str(e)}'
        })

    return {
        'results': results,
        'context': context,
        'timestamp': now
    }

# --- Create a decorator to protect admin routes:
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            # redirect to login page and pass current modality if needed
            modality = resolve_modality_from_request()
            return redirect(url_for('login', modality=modality))
        return f(*args, **kwargs)
    return decorated

# --- Add a login route:
@app.route('/login', methods=['GET', 'POST'])
def login():
    modality = resolve_modality_from_request()
    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == get_admin_password():
            session['admin_logged_in'] = True
            return redirect(url_for('upload_file', modality=modality))
        else:
            error = "Falsches Passwort"
    return render_template("login.html", error=error, modality=modality)


@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    modality = resolve_modality_from_request()
    return redirect(url_for('index', modality=modality))


@app.route('/api/master-csv-status')
def master_csv_status():
    """Check if master CSV exists and return info."""
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


@app.route('/upload-master-csv', methods=['POST'])
@admin_required
def upload_master_csv():
    """
    Upload master CSV (saves without processing).
    The CSV contains data for a whole month.
    """
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


@app.route('/preload-from-master', methods=['POST'])
@admin_required
def preload_from_master():
    """
    Preload next workday from the already-uploaded master CSV.
    No file upload needed.
    """
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst hochladen."}), 400

    result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG)

    if result['success']:
        return jsonify(result)
    return jsonify(result), 400


@app.route('/upload', methods=['GET', 'POST'])
@admin_required
def upload_file():
    """
    Medweb CSV upload route (config-driven).
    Replaces old Excel per-modality upload.
    """
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({"error": "Keine Datei ausgewählt"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Keine Datei ausgewählt"}), 400
        if not file.filename.lower().endswith('.csv'):
            return jsonify({"error": "Ungültiger Dateityp. Bitte eine CSV-Datei hochladen."}), 400

        target_date_str = request.form.get('target_date')
        if not target_date_str:
            return jsonify({"error": "Bitte Zieldatum angeben"}), 400

        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
        except Exception:
            return jsonify({"error": "Ungültiges Datumsformat"}), 400

        # Save CSV temporarily
        csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'medweb_temp.csv')
        try:
            file.save(csv_path)

            # Parse medweb CSV (CPU intensive, do outside lock)
            modality_dfs = build_working_hours_from_medweb(
                csv_path,
                target_date,
                APP_CONFIG
            )

            if not modality_dfs:
                return jsonify({"error": f"Keine Cortex-Daten für {target_date.strftime('%Y-%m-%d')} gefunden"}), 400

            # CRITICAL: Acquire lock before modifying global state
            with lock:
                # Reset all counters and apply to modality_data
                for modality, df in modality_dfs.items():
                    d = modality_data[modality]

                    # Reset counters
                    d['draw_counts'] = {}
                    d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
                    d['WeightedCounts'] = {}
                    global_worker_data['weighted_counts_per_mod'][modality] = {}
                    global_worker_data['assignments_per_mod'][modality] = {}

                    # Load DataFrame
                    d['working_hours_df'] = df

                    # Initialize counters
                    for worker in df['PPL'].unique():
                        d['draw_counts'][worker] = 0
                        d['WeightedCounts'][worker] = 0.0
                        for skill in SKILL_COLUMNS:
                            if skill not in d['skill_counts']:
                                d['skill_counts'][skill] = {}
                            d['skill_counts'][skill][worker] = 0

                    # Set info texts (empty for now, can be extended)
                    d['info_texts'] = []
                    d['last_uploaded_filename'] = f"medweb_{target_date.strftime('%Y%m%d')}.csv"

                # Persist state after reset
                save_state()

            # Save to master CSV for auto-preload (outside lock, I/O operation)
            shutil.copy2(csv_path, MASTER_CSV_PATH)
            selection_logger.info(f"Master CSV updated: {MASTER_CSV_PATH}")

            # Clean up temp file
            os.remove(csv_path)

            return jsonify({
                "success": True,
                "message": f"Medweb CSV erfolgreich geladen für {target_date.strftime('%Y-%m-%d')}",
                "modalities_loaded": list(modality_dfs.keys()),
                "total_workers": sum(len(df) for df in modality_dfs.values())
            })

        except Exception as e:
            if os.path.exists(csv_path):
                os.remove(csv_path)
            return jsonify({"error": f"Fehler beim Verarbeiten der CSV: {str(e)}"}), 500

    # GET method: Show upload page with stats
    # Get first modality for display
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    # Compute combined stats across all modalities
    all_worker_names = set()
    combined_skill_counts = {skill: {} for skill in SKILL_COLUMNS}

    for mod_key in allowed_modalities:
        mod_d = modality_data[mod_key]
        for skill in SKILL_COLUMNS:
            for worker, count in mod_d['skill_counts'].get(skill, {}).items():
                all_worker_names.add(worker)
                if worker not in combined_skill_counts[skill]:
                    combined_skill_counts[skill][worker] = 0
                combined_skill_counts[skill][worker] += count

    # Compute sum counts and global counts
    sum_counts = {}
    global_counts = {}
    global_weighted_counts = {}
    for worker in all_worker_names:
        total = sum(combined_skill_counts[skill].get(worker, 0) for skill in SKILL_COLUMNS)
        sum_counts[worker] = total

        canonical = get_canonical_worker_id(worker)
        global_counts[worker] = get_global_assignments(canonical)
        global_weighted_counts[worker] = get_global_weighted_count(canonical)

    # Build combined stats table
    combined_workers = sorted(all_worker_names)
    modality_stats = {}
    for worker in combined_workers:
        modality_stats[worker] = {
            skill: combined_skill_counts[skill].get(worker, 0)
            for skill in SKILL_COLUMNS
        }
        modality_stats[worker]['total'] = sum_counts.get(worker, 0)

    # Debug info from first loaded modality
    debug_info = (
        d['working_hours_df'].to_html(index=True)
        if d['working_hours_df'] is not None else "Keine Daten verfügbar"
    )

    # Run operational checks
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
    )


@app.route('/load-today-from-master', methods=['POST'])
@admin_required
def load_today_from_master():
    """
    Load today's schedule from the already-uploaded master CSV.
    No file upload needed - uses stored master_medweb.csv.
    Resets counters for today.
    """
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst CSV hochladen."}), 400

    try:
        # Use TODAY's date
        target_date = get_local_berlin_now()

        # Debug: Check CSV content before parsing
        try:
            # Try UTF-8 first (default for modern CSVs), then latin1
            try:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='utf-8')
            except UnicodeDecodeError:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='latin1')
            if 'Datum' not in debug_df.columns:
                # Try semicolon separator
                try:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='utf-8')
                except UnicodeDecodeError:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='latin1')

            available_dates = debug_df['Datum'].unique().tolist() if 'Datum' in debug_df.columns else []
            available_activities = debug_df['Beschreibung der Aktivität'].unique().tolist() if 'Beschreibung der Aktivität' in debug_df.columns else []
        except Exception as e:
            return jsonify({"error": f"CSV-Lesefehler: {str(e)}"}), 400

        # Parse medweb CSV
        modality_dfs = build_working_hours_from_medweb(
            MASTER_CSV_PATH,
            target_date,
            APP_CONFIG
        )

        if not modality_dfs:
            # Better error message with debug info
            # Check what mapping rules exist
            mapping_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
            rule_matches = [r.get('match', '') for r in mapping_rules[:10]]

            # Check which activities would match rules
            matched_activities = []
            for activity in available_activities:
                for rule in mapping_rules:
                    if rule.get('match', '').lower() in str(activity).lower():
                        matched_activities.append(activity)
                        break

            return jsonify({
                "error": f"Keine Cortex-Daten für {target_date.strftime('%d.%m.%Y')} gefunden",
                "debug": {
                    "target_date": target_date.strftime('%d.%m.%Y'),
                    "dates_in_csv": available_dates[:10],
                    "activities_in_csv": available_activities[:10],
                    "mapping_rules": rule_matches,
                    "matched_activities": matched_activities[:10],
                    "hint": "Prüfen Sie ob Datum und Aktivitäten mit Mapping-Regeln übereinstimmen"
                }
            }), 400

        # Reset counters and apply to modality_data
        with lock:
            for modality, df in modality_dfs.items():
                d = modality_data[modality]

                # Reset counters
                d['draw_counts'] = {}
                d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
                d['WeightedCounts'] = {}
                global_worker_data['weighted_counts_per_mod'][modality] = {}
                global_worker_data['assignments_per_mod'][modality] = {}

                # Load DataFrame
                d['working_hours_df'] = df

                # Initialize counters
                for worker in df['PPL'].unique():
                    d['draw_counts'][worker] = 0
                    d['WeightedCounts'][worker] = 0.0
                    for skill in SKILL_COLUMNS:
                        if skill not in d['skill_counts']:
                            d['skill_counts'][skill] = {}
                        d['skill_counts'][skill][worker] = 0

                d['info_texts'] = []
                d['last_uploaded_filename'] = f"master_{target_date.strftime('%Y%m%d')}.csv"

            save_state()

        # Auto-populate skill roster with workers from CSV
        workers_added = auto_populate_skill_roster(modality_dfs)

        selection_logger.info(
            f"Loaded today ({target_date.strftime('%d.%m.%Y')}) from master CSV. "
            f"Modalities: {list(modality_dfs.keys())}, New workers in roster: {workers_added}"
        )

        return jsonify({
            "success": True,
            "message": f"Heute ({target_date.strftime('%d.%m.%Y')}) aus Master-CSV geladen",
            "modalities_loaded": list(modality_dfs.keys()),
            "total_workers": sum(len(df) for df in modality_dfs.values()),
            "workers_added_to_roster": workers_added
        })

    except Exception as e:
        return jsonify({"error": f"Fehler: {str(e)}"}), 500


@app.route('/prep-next-day')
@admin_required
def prep_next_day():
    """
    Next day prep/edit page.
    Shows editable table for tomorrow's schedule.
    Can be used for both normal prep and force refresh scenarios.
    """
    next_day = get_next_workday()

    # Get worker list from skill roster for autocomplete
    roster = load_worker_skill_json()
    if roster is None:
        roster = {}
    worker_list = list(roster.keys())

    # Build task/role list from medweb_mapping rules (non-exclusion only)
    # These are the roles like "CT Assistent", "MR Spätdienst", etc.
    medweb_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
    task_roles = []
    for rule in medweb_rules:
        if not rule.get('exclusion'):  # Only non-exclusion rules = actual roles
            task_role = {
                'name': rule.get('match', ''),
                'modality': rule.get('modality'),  # Single modality
                'modalities': rule.get('modalities', []),  # Multiple modalities
                'shift': rule.get('shift', 'Fruehdienst'),
                'base_skills': rule.get('base_skills', {}),
                'modifier': rule.get('modifier', 1.0)  # Workload modifier (0.5-1.5 range)
            }
            # If single modality, convert to list for consistency
            if task_role['modality'] and not task_role['modalities']:
                task_role['modalities'] = [task_role['modality']]
            task_roles.append(task_role)

    # Get exclusion rules for "gap" functionality (boards, meetings, etc.)
    exclusion_rules = [r for r in medweb_rules if r.get('exclusion')]

    # Worker skills from JSON roster (used to prefill skills in UI)
    worker_skills = load_worker_skill_json()

    return render_template(
        'prep_next_day.html',
        target_date=next_day.strftime('%Y-%m-%d'),
        target_date_german=next_day.strftime('%d.%m.%Y'),
        is_next_day=True,
        skills=SKILL_COLUMNS,
        skill_settings=SKILL_SETTINGS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_settings=MODALITY_SETTINGS,
        shift_times=APP_CONFIG.get('shift_times', {}),
        medweb_mapping=APP_CONFIG.get('medweb_mapping', {}),
        worker_list=worker_list,
        worker_skills=worker_skills,
        task_roles=task_roles,
        exclusion_rules=exclusion_rules
    )


@app.route('/api/prep-next-day/data', methods=['GET'])
@admin_required
def get_prep_data():
    """
    Get staged working_hours_df data for all modalities (for next-day planning).
    Returns data in format suitable for edit table.
    """
    result = {}

    for modality in allowed_modalities:
        # Try to load staged data if not already loaded
        if staged_modality_data[modality]['working_hours_df'] is None:
            # Try to load from staged file
            if not load_staged_dataframe(modality):
                # If no staged data, copy from live as starting point
                if modality_data[modality]['working_hours_df'] is not None:
                    staged_modality_data[modality]['working_hours_df'] = modality_data[modality]['working_hours_df'].copy()
                    staged_modality_data[modality]['info_texts'] = modality_data[modality]['info_texts'].copy()
                    # Save the initial staged copy
                    backup_dataframe(modality, use_staged=True)

        df = staged_modality_data[modality].get('working_hours_df')
        result[modality] = _df_to_api_response(df)

    return jsonify(result)


@app.route('/api/prep-next-day/update-row', methods=['POST'])
@admin_required
def update_prep_row():
    """
    Update a single worker row in STAGED working_hours_df (next-day planning).
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    updates = data.get('updates', {})

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, error = _update_schedule_row(modality, row_index, updates, use_staged=True)

    if success:
        return jsonify({'success': True})
    return jsonify({'error': error}), 400


@app.route('/api/prep-next-day/add-worker', methods=['POST'])
@admin_required
def add_prep_worker():
    """
    Add a new worker row to STAGED working_hours_df (next-day planning).
    """
    data = request.json
    modality = data.get('modality')
    worker_data = data.get('worker_data', {})

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, row_index, error = _add_worker_to_schedule(modality, worker_data, use_staged=True)

    if success:
        return jsonify({'success': True, 'row_index': row_index})
    return jsonify({'error': error}), 400


@app.route('/api/prep-next-day/delete-worker', methods=['POST'])
@admin_required
def delete_prep_worker():
    """
    Delete a worker row from STAGED working_hours_df (next-day planning).
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, worker_name, error = _delete_worker_from_schedule(modality, row_index, use_staged=True)

    if success:
        return jsonify({'success': True})
    return jsonify({'error': error}), 400


# =============================================================================
# LIVE SCHEDULE APIs (Change Today - immediate effect, NO counter reset)
# =============================================================================

@app.route('/api/live-schedule/data', methods=['GET'])
@admin_required
def get_live_data():
    """
    Get LIVE working_hours_df data for all modalities.
    Unlike prep-next-day, this returns currently active schedule data.
    """
    result = {}

    for modality in allowed_modalities:
        df = modality_data[modality].get('working_hours_df')
        result[modality] = _df_to_api_response(df)

    return jsonify(result)


@app.route('/api/live-schedule/update-row', methods=['POST'])
@admin_required
def update_live_row():
    """
    Update a single worker row in LIVE working_hours_df.
    IMPORTANT: Does NOT reset counters - changes apply immediately.
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    updates = data.get('updates', {})

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, error = _update_schedule_row(modality, row_index, updates, use_staged=False)

    if success:
        selection_logger.info(f"Live schedule updated for {modality}, row {row_index} (no counter reset)")
        return jsonify({'success': True})
    return jsonify({'error': error}), 400


@app.route('/api/live-schedule/add-worker', methods=['POST'])
@admin_required
def add_live_worker():
    """
    Add a new worker row to LIVE working_hours_df.
    IMPORTANT: Does NOT reset counters - worker is added immediately.
    Initializes counter for new worker at 0.
    """
    data = request.json
    modality = data.get('modality')
    worker_data = data.get('worker_data', {})

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    ppl_name = worker_data.get('PPL', 'Neuer Worker (NW)')
    success, row_index, error = _add_worker_to_schedule(modality, worker_data, use_staged=False)

    if success:
        # Initialize counter for new worker at 0 (don't reset existing counters)
        d = modality_data[modality]
        if ppl_name not in d['draw_counts']:
            d['draw_counts'][ppl_name] = 0
        if ppl_name not in d['WeightedCounts']:
            d['WeightedCounts'][ppl_name] = 0.0
        for skill in SKILL_COLUMNS:
            if skill not in d['skill_counts']:
                d['skill_counts'][skill] = {}
            if ppl_name not in d['skill_counts'][skill]:
                d['skill_counts'][skill][ppl_name] = 0

        selection_logger.info(f"Worker {ppl_name} added to LIVE {modality} schedule (no counter reset)")
        return jsonify({'success': True, 'row_index': row_index})

    return jsonify({'error': error}), 400


@app.route('/api/live-schedule/delete-worker', methods=['POST'])
@admin_required
def delete_live_worker():
    """
    Delete a worker row from LIVE working_hours_df.
    IMPORTANT: Does NOT reset counters for remaining workers.
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, worker_name, error = _delete_worker_from_schedule(modality, row_index, use_staged=False)

    if success:
        selection_logger.info(f"Worker {worker_name} deleted from LIVE {modality} schedule (no counter reset)")
        return jsonify({'success': True})

    return jsonify({'error': error}), 400


@app.route('/api/live-schedule/add-gap', methods=['POST'])
@admin_required
def add_live_gap():
    """
    Add a gap (time exclusion) to a worker's shift in LIVE data.
    The gap punches out time from the worker's shift.
    - If gap covers entire shift: delete the row
    - If gap at start: move start_time forward
    - If gap at end: move end_time backward
    - If gap in middle: split into two rows
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, action, error = _add_gap_to_schedule(modality, row_index, gap_type, gap_start, gap_end, use_staged=False)

    if success:
        return jsonify({'success': True, 'action': action})
    return jsonify({'error': error}), 400


@app.route('/api/prep-next-day/add-gap', methods=['POST'])
@admin_required
def add_staged_gap():
    """
    Add a gap (time exclusion) to a worker's shift in STAGED data.
    Same logic as live gap but operates on staged_modality_data.
    """
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, action, error = _add_gap_to_schedule(modality, row_index, gap_type, gap_start, gap_end, use_staged=True)

    if success:
        return jsonify({'success': True, 'action': action})
    return jsonify({'error': error}), 400


@app.route('/api/<modality>/<role>', methods=['GET'])
def assign_worker_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role)


@app.route('/api/<modality>/<role>/strict', methods=['GET'])
def assign_worker_strict_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role, allow_fallback=False)

def _assign_worker(modality: str, role: str, allow_fallback: bool = True):
    try:
        requested_data = modality_data[modality]
        now = get_local_berlin_now()
        selection_logger.info(
            "Assignment request: modality=%s, role=%s, strict=%s, time=%s",
            modality,
            role,
            not allow_fallback,
            now.strftime('%H:%M:%S'),
        )

        with lock:
            result = get_next_available_worker(
                now,
                role=role,
                modality=modality,
                allow_fallback=allow_fallback,
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

                selection_logger.info(
                    "Selected worker: %s using column %s (modality %s)",
                    person,
                    actual_skill,
                    actual_modality,
                )

                d['draw_counts'][person] = d['draw_counts'].get(person, 0) + 1
                if actual_skill in SKILL_COLUMNS:
                    if actual_skill not in d['skill_counts']:
                        d['skill_counts'][actual_skill] = {}
                    if person not in d['skill_counts'][actual_skill]:
                        d['skill_counts'][actual_skill][person] = 0
                    d['skill_counts'][actual_skill][person] += 1

                    # Get skill value for this worker
                    skill_value = skill_value_to_numeric(candidate.get(actual_skill, 0))

                    # Determine if modifier should apply
                    # Modifier range: 0.5, 0.75, 1.0, 1.25, 1.5 (lower = less capacity)
                    modifier = 1.0
                    modifier_active_only = BALANCER_SETTINGS.get('modifier_applies_to_active_only', False)

                    if modifier_active_only:
                        # Only apply modifier if skill value is 1 or 2 (active/weighted)
                        if skill_value >= 1:
                            modifier = candidate.get('Modifier', 1.0)
                    else:
                        # Apply modifier regardless of skill value (old behavior)
                        modifier = candidate.get('Modifier', 1.0)

                    if person not in d['WeightedCounts']:
                        d['WeightedCounts'][person] = 0.0

                    # Calculate weight with skill×modality factor and modifier
                    # Note: skill='w' is just a visual marker - weight is controlled by Modifier
                    local_weight = get_skill_modality_weight(actual_skill, actual_modality) * modifier
                    d['WeightedCounts'][person] += local_weight

                canonical_id = update_global_assignment(person, actual_skill, actual_modality)
                
                skill_counts = {}
                for skill in SKILL_COLUMNS:
                    if skill in d['skill_counts']:
                        skill_counts[skill] = {
                            w: skill_value_to_numeric(v) for w, v in d['skill_counts'][skill].items()
                        }
                    else:
                        skill_counts[skill] = {}

                worker_pool = set()
                for skill in SKILL_COLUMNS:
                    worker_pool.update(skill_counts.get(skill, {}).keys())

                sum_counts = {}
                for w in worker_pool:
                    total = 0
                    for skill in SKILL_COLUMNS:
                        total += skill_counts[skill].get(w, 0)
                    sum_counts[w] = total

                global_stats = {}
                for worker in sum_counts.keys():
                    global_stats[worker] = get_global_assignments(get_canonical_worker_id(worker))

                result_data = {
                    "Draw Time": now.strftime('%H:%M:%S'),
                    "Assigned Person": person,
                    "Summe": sum_counts,
                    "Global": global_stats,
                    "modality_used": actual_modality,
                    "skill_used": actual_skill,
                    "modality_requested": modality,
                    "fallback_allowed": allow_fallback,
                    "strict_request": not allow_fallback,
                }
                for skill in SKILL_COLUMNS:
                    result_data[skill] = skill_counts.get(skill, {})
            else:
                d = requested_data
                empty_counts = {w: 0 for w in d['draw_counts']}
                skill_counts = {skill: empty_counts.copy() for skill in SKILL_COLUMNS}
                sum_counts = {w: 0 for w in d['draw_counts']}

                message = (
                    "Bitte nochmal klicken"
                    if allow_fallback
                    else "Keine Person in dieser Gruppe verfügbar"
                )

                result_data = {
                    "Draw Time": now.strftime('%H:%M:%S'),
                    "Assigned Person": message,
                    "Summe": sum_counts,
                    "Global": {},
                    "modality_requested": modality,
                    "modality_used": None,
                    "skill_used": None,
                    "fallback_allowed": allow_fallback,
                    "strict_request": not allow_fallback,
                }
                for skill in SKILL_COLUMNS:
                    result_data[skill] = skill_counts.get(skill, {})
        return jsonify(result_data)
    except Exception as e:
        app.logger.exception("Error in _assign_worker")
        return jsonify({"error": str(e)}), 500

@app.route('/api/edit_info', methods=['POST'])
@admin_required
def edit_info():
    """
    Update info texts for a modality.
    Accepts JSON body: {"modality": "ct", "info_text": "Line 1\\nLine 2"}
    """
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

        modality = data.get('modality')
        if modality not in modality_data:
            return jsonify({'success': False, 'error': 'Invalid modality'}), 400

        new_info = data.get('info_text', '')
        d = modality_data[modality]
        d['info_texts'] = [line.strip() for line in new_info.splitlines() if line.strip()]
        selection_logger.info(f"Updated info_texts for {modality}: {d['info_texts']}")

        return jsonify({
            'success': True,
            'info_texts': d['info_texts']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500







@app.route('/api/quick_reload', methods=['GET'])
def quick_reload():
    # Check if this is a skill-based view request
    skill_param = request.args.get('skill')

    if skill_param:
        # Skill-based view: all modality buttons always visible (config-based)
        checks = run_operational_checks('reload', force=True)
        return jsonify({
            "available_modalities": {mod: True for mod in allowed_modalities},
            "operational_checks": checks,
        })

    # Modality-based view
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    now = get_local_berlin_now()
    checks = run_operational_checks('reload', force=True)

    # Button visibility handled by template (valid_skills/hidden_skills in config)
    available_buttons = {entry['slug']: True for entry in SKILL_TEMPLATES}
            
    # Rebuild per-skill counts:
    skill_counts = {}
    for skill in SKILL_COLUMNS:
        skill_counts[skill] = d['skill_counts'].get(skill, {})

    # Summation per worker
    sum_counts = {}
    worker_pool = set()
    for skill in SKILL_COLUMNS:
        worker_pool.update(skill_counts.get(skill, {}).keys())

    for worker in worker_pool:
        total = 0
        for s in SKILL_COLUMNS:
            total += int(skill_counts[s].get(worker, 0))
        sum_counts[worker] = total

    # Global assignments per worker:
    global_stats = {}
    for worker in sum_counts.keys():
        cid = get_canonical_worker_id(worker)
        global_stats[worker] = get_global_assignments(cid)
        
    # Also compute global weighted counts:
    global_weighted_counts = {}
    for worker in sum_counts.keys():
        canonical = get_canonical_worker_id(worker)
        global_weighted_counts[worker] = get_global_weighted_count(canonical)

    payload = {
        "Draw Time": now.strftime("%H:%M:%S"),
        "Assigned Person": None,
        "Summe": sum_counts,
        "Global": global_stats,
        "GlobalWeighted": global_weighted_counts,
        "available_buttons": available_buttons,
        "operational_checks": checks,
    }
    for skill in SKILL_COLUMNS:
        payload[skill] = skill_counts.get(skill, {})

    return jsonify(payload)


# ============================================================================
# Worker Skill Roster Management API
# ============================================================================

@app.route('/api/admin/skill_roster', methods=['GET'])
@admin_required
def get_skill_roster():
    """Get worker skill roster (single file, no staging)."""
    global worker_skill_json_roster
    try:
        # Load roster
        roster = load_worker_skill_json()
        worker_skill_json_roster = roster  # Update in-memory copy

        # Get available skills and modalities from config
        config = _build_app_config()
        skills = list(config.get('skills', {}).keys())
        modalities = list(config.get('modalities', {}).keys())

        return jsonify({
            'success': True,
            'roster': roster,
            'skills': skills,
            'modalities': modalities
        })
    except Exception as exc:
        selection_logger.error(f"Error getting skill roster: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/admin/skill_roster', methods=['POST'])
@admin_required
def save_skill_roster():
    """Save worker skill roster (single file, immediate effect)."""
    global worker_skill_json_roster
    try:
        data = request.get_json()
        if not data or 'roster' not in data:
            return jsonify({'success': False, 'error': 'No roster data provided'}), 400

        roster_data = data['roster']

        # Validate roster structure (basic validation)
        if not isinstance(roster_data, dict):
            return jsonify({'success': False, 'error': 'Roster must be a dictionary'}), 400

        # Save to JSON file
        if save_worker_skill_json(roster_data):
            worker_skill_json_roster = roster_data  # Update in-memory copy
            selection_logger.info(f"Worker skill roster saved: {len(roster_data)} workers")

            return jsonify({
                'success': True,
                'message': f'Roster saved ({len(roster_data)} workers)'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save roster'}), 500

    except Exception as exc:
        selection_logger.error(f"Error saving skill roster: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/admin/skill_roster/reload', methods=['POST'])
@admin_required
def reload_skill_roster():
    """Reload worker skill roster from JSON file."""
    global worker_skill_json_roster
    try:
        roster = load_worker_skill_json()
        worker_skill_json_roster = roster
        return jsonify({
            'success': True,
            'message': f'Roster reloaded ({len(roster)} workers)'
        })
    except Exception as exc:
        selection_logger.error(f"Error reloading roster: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/skill_roster')
@admin_required
def skill_roster_page():
    """Admin page for managing worker skill roster (planning mode)."""
    # Build valid_skills map: modality -> list of valid skills (or all skills if not specified)
    valid_skills_map = {}
    for mod, settings in MODALITY_SETTINGS.items():
        if 'valid_skills' in settings:
            valid_skills_map[mod] = settings['valid_skills']
        else:
            valid_skills_map[mod] = SKILL_COLUMNS  # All skills valid

    return render_template(
        'skill_roster.html',
        skills=SKILL_COLUMNS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_labels={k: v.get('label', k.upper()) for k, v in MODALITY_SETTINGS.items()},
        valid_skills_map=valid_skills_map
    )


def _format_time(t):
    """Format time object to string for JSON serialization."""
    return t.strftime('%H:%M:%S') if pd.notnull(t) else ""

def _prepare_df_for_timetable(df, mod):
    """Prepare DataFrame for timetable JSON output."""
    if df is None or df.empty:
        return None
    df_copy = df.copy()
    df_copy['_modality'] = mod
    df_copy['start_time'] = df_copy['start_time'].apply(_format_time)
    df_copy['end_time'] = df_copy['end_time'].apply(_format_time)
    return df_copy

# Pre-computed timetable constants (static after config load)
_TIMETABLE_SKILL_DEFS = [
    {'label': SKILL_SETTINGS[s].get('label', s), 'button_color': SKILL_SETTINGS[s].get('button_color', '#ccc')}
    for s in SKILL_COLUMNS
]
_TIMETABLE_SKILL_COLORS = {SKILL_SLUG_MAP[s]: SKILL_SETTINGS[s].get('button_color', '#ccc') for s in SKILL_COLUMNS}
_TIMETABLE_MOD_COLORS = {k: v.get('nav_color', '#666') for k, v in MODALITY_SETTINGS.items()}
_TIMETABLE_MOD_LABELS = {k: v.get('label', k.upper()) for k, v in MODALITY_SETTINGS.items()}

@app.route('/timetable')
def timetable():
    requested = request.args.get('modality', 'all').lower()
    modality = 'all' if requested == 'all' else resolve_modality_from_request()

    if modality == 'all':
        frames = [_prepare_df_for_timetable(modality_data[m]['working_hours_df'], m) for m in allowed_modalities]
        frames = [f for f in frames if f is not None]
        debug_data = pd.concat(frames, ignore_index=True).to_json(orient='records') if frames else "[]"
    else:
        df = _prepare_df_for_timetable(modality_data[modality]['working_hours_df'], modality)
        debug_data = df.to_json(orient='records') if df is not None else "[]"

    return render_template(
        'timetable.html',
        debug_data=debug_data,
        modality=modality,
        skills=SKILL_COLUMNS,
        skill_columns=SKILL_COLUMNS,
        skill_slug_map=SKILL_SLUG_MAP,
        skill_color_map=_TIMETABLE_SKILL_COLORS,
        skill_definitions=_TIMETABLE_SKILL_DEFS,
        modalities=MODALITY_SETTINGS,
        modality_order=list(MODALITY_SETTINGS.keys()),
        modality_labels=_TIMETABLE_MOD_LABELS,
        modality_color_map=_TIMETABLE_MOD_COLORS
    )


app.config['DEBUG'] = True

# Initialize worker skill JSON roster
def init_worker_skill_roster():
    """Load worker skill overrides from JSON on startup."""
    global worker_skill_json_roster
    worker_skill_json_roster = load_worker_skill_json()


# Initialize scheduler for auto-preload
def init_scheduler():
    """Initialize and start background scheduler for auto-preload."""
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler()
        # Run daily at 7:30 AM (Berlin time)
        scheduler.add_job(
            auto_preload_job,
            CronTrigger(hour=7, minute=30, timezone='Europe/Berlin'),
            id='auto_preload',
            name='Auto-preload next workday',
            replace_existing=True
        )
        scheduler.start()
        selection_logger.info("Scheduler started: Auto-preload will run daily at 7:30 AM")

# Initialize worker skill roster from JSON
init_worker_skill_roster()

# Load persisted state on startup to restore fairness counters
load_state()
selection_logger.info("Fairness state loaded from disk")

# Start scheduler when app starts
init_scheduler()

if __name__ == '__main__':
    app.run()

    
    