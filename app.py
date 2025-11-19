from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask import session
import pandas as pd
from datetime import datetime, time
import pytz
import os
import copy
from threading import Lock

import pandas as pd
import pytz
import yaml
from functools import wraps
from typing import Dict, Any, Optional

import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, List, Optional, Tuple

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

lock = Lock()

# -----------------------------------------------------------
# Global constants & modality-/skill-specific factors
# -----------------------------------------------------------

DEFAULT_FALLBACK_CHAIN = {
    'Normal': [],
    'Notfall': ['Normal'],
    'Herz': ['Notfall', 'Normal'],
    'Privat': ['Notfall', 'Normal'],
    'Msk': ['Notfall', 'Normal'],
    'Chest': ['Notfall', 'Normal']
}

DEFAULT_SKILLS = {
    "Normal": {
        "label": "Normal",
        "button_color": "#004892",
        "text_color": "#ffffff",
        "weight": 1.0,
        "optional": False,
        "special": False,
        "always_visible": True,
        "fallback": [],
    },
    "Notfall": {
        "label": "Notfall",
        "button_color": "#dc3545",
        "text_color": "#ffffff",
        "weight": 1.1,
        "optional": False,
        "special": False,
        "always_visible": True,
        "fallback": ["Normal"],
    },
    "Privat": {
        "label": "Privat",
        "button_color": "#ffc107",
        "text_color": "#333333",
        "weight": 1.2,
        "optional": True,
        "special": False,
        "always_visible": True,
        "fallback": ["Notfall", "Normal"],
    },
    "Herz": {
        "label": "Herz",
        "button_color": "#28a745",
        "text_color": "#ffffff",
        "weight": 1.2,
        "optional": True,
        "special": True,
        "always_visible": False,
        "fallback": ["Notfall", "Normal"],
    },
    "Msk": {
        "label": "Msk",
        "button_color": "#9c27b0",
        "text_color": "#ffffff",
        "weight": 0.8,
        "optional": True,
        "special": True,
        "always_visible": False,
        "fallback": ["Notfall", "Normal"],
    },
    "Chest": {
        "label": "Chest",
        "button_color": "#ff9800",
        "text_color": "#ffffff",
        "weight": 0.8,
        "optional": True,
        "special": True,
        "always_visible": False,
        "fallback": ["Notfall", "Normal"],
    },
}

DEFAULT_MODALITIES = {
    'ct': {
        'label': 'CT',
        'nav_color': '#1a5276',
        'hover_color': '#153f5b',
        'background_color': '#e6f2fa',
        'factor': 1.0,
    },
    'mr': {
        'label': 'MR',
        'nav_color': '#777777',
        'hover_color': '#555555',
        'background_color': '#f9f9f9',
        'factor': 1.2,
    },
    'xray': {
        'label': 'XRAY',
        'nav_color': '#239b56',
        'hover_color': '#1d7a48',
        'background_color': '#e0f2e9',
        'factor': 0.33,
    },
}

DEFAULT_CONFIG = {
    'admin_password': 'change_pw_for_live',
    'modalities': DEFAULT_MODALITIES,
    'skills': DEFAULT_SKILLS,
    'modality_fallbacks': {},
    'balancer': {}
}

DEFAULT_BALANCER = {
    'enabled': True,
    'min_assignments_per_skill': 5,
    'imbalance_threshold_pct': 30,
    'allow_fallback_on_imbalance': True,
    'fallback_chain': DEFAULT_FALLBACK_CHAIN
}


def _normalize_skill_fallback_entries(entries: Any) -> List[Any]:
    """Normalize fallback tiers to support strings or nested groups."""

    normalized: List[Any] = []
    if not isinstance(entries, list):
        return normalized

    for entry in entries:
        if isinstance(entry, list):
            group: List[str] = []
            seen: set = set()
            for candidate in entry:
                if isinstance(candidate, str) and candidate not in seen:
                    group.append(candidate)
                    seen.add(candidate)
            if group:
                normalized.append(group)
        elif isinstance(entry, str):
            normalized.append(entry)

    return normalized


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


def _write_predefined_config(final_config: Dict[str, Any], output_path: str = 'config.predefined.yaml') -> None:
    """Persist the fully merged configuration so operators can reuse it."""
    try:
        with open(output_path, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(final_config, handle, sort_keys=False, allow_unicode=True)
    except Exception as exc:
        selection_logger.warning("Unable to write %s: %s", output_path, exc)


def ensure_predefined_config(final_config: Dict[str, Any], output_path: str = 'config.predefined.yaml') -> bool:
    """
    Ensure the predefined configuration on disk matches ``final_config``.

    Returns ``True`` when the existing file already matches (no rewrite was
    necessary) and ``False`` when the file had to be created or updated.
    """
    disk_config = None
    try:
        with open(output_path, 'r', encoding='utf-8') as existing:
            disk_config = yaml.safe_load(existing) or {}
    except FileNotFoundError:
        disk_config = None
    except Exception as exc:
        selection_logger.warning("Unable to read %s: %s", output_path, exc)
        disk_config = None

    if disk_config == final_config:
        return True

    _write_predefined_config(final_config, output_path)
    return False


def _build_app_config() -> Dict[str, Any]:
    raw_config = _load_raw_config()
    config: Dict[str, Any] = {
        'admin_password': raw_config.get('admin_password', DEFAULT_CONFIG['admin_password'])
    }

    merged_modalities: Dict[str, Dict[str, Any]] = {
        key: dict(values)
        for key, values in DEFAULT_MODALITIES.items()
    }
    user_modalities = raw_config.get('modalities') or {}
    if isinstance(user_modalities, dict):
        for key, override in user_modalities.items():
            base = merged_modalities.get(key, {}).copy()
            if isinstance(override, dict):
                base.update(override)
            merged_modalities[key] = base

    for key, values in merged_modalities.items():
        values.setdefault('label', key.upper())
        values.setdefault('nav_color', '#004892')
        values.setdefault('hover_color', values['nav_color'])
        values.setdefault('background_color', '#f0f0f0')
        values['factor'] = _coerce_float(values.get('factor', 1.0))

    config['modalities'] = merged_modalities

    merged_skills: Dict[str, Dict[str, Any]] = {
        key: dict(values)
        for key, values in DEFAULT_SKILLS.items()
    }
    user_skills = raw_config.get('skills') or {}
    if isinstance(user_skills, dict):
        for key, override in user_skills.items():
            base = merged_skills.get(key, {}).copy()
            if isinstance(override, dict):
                base.update(override)
            merged_skills[key] = base

    for key, values in merged_skills.items():
        values.setdefault('label', key)
        values.setdefault('button_color', '#004892')
        values.setdefault('text_color', '#ffffff')
        values['weight'] = _coerce_float(values.get('weight', 1.0))
        values.setdefault('optional', False)
        values.setdefault('special', False)
        values.setdefault('always_visible', False)
        fallback_value = values.get('fallback', DEFAULT_FALLBACK_CHAIN.get(key, []))
        values['fallback'] = _normalize_skill_fallback_entries(fallback_value)
        values['display_order'] = _coerce_int(values.get('display_order', 0))
        slug = values.get('slug') or key.lower().replace(' ', '_')
        values['slug'] = slug
        values.setdefault('form_key', slug)

    config['skills'] = merged_skills

    balancer_settings: Dict[str, Any] = copy.deepcopy(DEFAULT_BALANCER)
    user_balancer = raw_config.get('balancer')
    if isinstance(user_balancer, dict):
        for key, value in user_balancer.items():
            if key == 'fallback_chain' and isinstance(value, dict):
                merged_fallback = {}
                all_skills = set(DEFAULT_FALLBACK_CHAIN) | set(value)
                for skill in all_skills:
                    merged_fallback[skill] = _normalize_skill_fallback_entries(
                        list(DEFAULT_FALLBACK_CHAIN.get(skill, []))
                    )

                for skill, overrides in value.items():
                    if isinstance(overrides, list):
                        merged_fallback[skill] = _normalize_skill_fallback_entries(overrides)
                    else:
                        merged_fallback[skill] = merged_fallback.get(skill, [])

                balancer_settings['fallback_chain'] = merged_fallback
            else:
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
    return config


APP_CONFIG = _build_app_config()
ensure_predefined_config(APP_CONFIG)
MODALITY_SETTINGS = APP_CONFIG['modalities']
SKILL_SETTINGS = APP_CONFIG['skills']
allowed_modalities = list(MODALITY_SETTINGS.keys()) or list(DEFAULT_MODALITIES.keys())
default_modality = allowed_modalities[0] if allowed_modalities else 'ct'
modality_labels = {
    mod: settings.get('label', mod.upper())
    for mod, settings in MODALITY_SETTINGS.items()
}
modality_factors = {
    mod: settings.get('factor', 1.0)
    for mod, settings in MODALITY_SETTINGS.items()
}


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
BALANCER_SETTINGS = APP_CONFIG.get('balancer', DEFAULT_BALANCER)
raw_balancer_chain = BALANCER_SETTINGS.get('fallback_chain', DEFAULT_FALLBACK_CHAIN)
BALANCER_FALLBACK_CHAIN = {}
if isinstance(raw_balancer_chain, dict):
    for skill, entries in raw_balancer_chain.items():
        BALANCER_FALLBACK_CHAIN[skill] = _normalize_skill_fallback_entries(entries)
else:
    BALANCER_FALLBACK_CHAIN = {k: _normalize_skill_fallback_entries(v) for k, v in DEFAULT_FALLBACK_CHAIN.items()}

BALANCER_SETTINGS['fallback_chain'] = BALANCER_FALLBACK_CHAIN
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
        'last_uploaded_filename': f"SBZ_{mod.upper()}.xlsx",  # e.g. SBZ_CT.xlsx
        'default_file_path': os.path.join(app.config['UPLOAD_FOLDER'], f"SBZ_{mod.upper()}.xlsx"),
        'scheduled_file_path': os.path.join(app.config['UPLOAD_FOLDER'], f"SBZ_{mod.upper()}_scheduled.xlsx"),
        'last_reset_date': None
    }


@app.context_processor
def inject_modality_settings():
    return {
        'modalities': MODALITY_SETTINGS,
        'modality_order': allowed_modalities,
        'modality_labels': modality_labels,
        'skill_definitions': SKILL_TEMPLATES,
    }


def normalize_modality(modality_value: Optional[str]) -> str:
    if not modality_value:
        return default_modality
    modality_value = modality_value.lower()
    return modality_value if modality_value in allowed_modalities else default_modality


def resolve_modality_from_request() -> str:
    return normalize_modality(request.values.get('modality'))

# -----------------------------------------------------------
# TIME / DATE HELPERS (unchanged)
# -----------------------------------------------------------
def get_local_berlin_now() -> datetime:
    tz = pytz.timezone("Europe/Berlin")
    aware_now = datetime.now(tz)
    naive_now = aware_now.replace(tzinfo=None)
    return naive_now

def parse_time_range(time_range: str):
    start_str, end_str = time_range.split('-')
    start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
    end_time   = datetime.strptime(end_str.strip(), '%H:%M').time()
    return start_time, end_time

# -----------------------------------------------------------
# Worker identification helper functions (NEW)
# -----------------------------------------------------------
def get_canonical_worker_id(worker_name):
    """
    Get the canonical worker ID from any name variation.
    If not found, create a new canonical ID.
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
        start_dt = datetime.combine(current_dt.date(), row['start_time'])
        end_dt   = datetime.combine(current_dt.date(), row['end_time'])
        if current_dt.time() < row['start_time']:
            return 0.0
        elif current_dt.time() >= row['end_time']:
            return (end_dt - start_dt).total_seconds() / 3600.0
        else:
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
                lambda row: (
                    datetime.combine(datetime.min, row['end_time']) -
                    datetime.combine(datetime.min, row['start_time'])
                ).total_seconds() / 3600.0,
                axis=1
            )

            # Compute canonical ID for each worker
            df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

            # Set column order as desired
            col_order = ['PPL', 'canonical_id', 'Modifier', 'TIME', 'start_time', 'end_time', 'shift_duration']
            skill_cols = [skill for skill in SKILL_COLUMNS if skill in df.columns]
            col_order = col_order[:4] + skill_cols + col_order[4:]
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
    if filtered_df.empty or not BALANCER_SETTINGS.get('enabled', True):
        return filtered_df
    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)
    if min_required <= 0:
        return filtered_df

    skill_counts = modality_data[modality]['skill_counts'].get(column, {})
    if not skill_counts:
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

    worker_counts = [
        _get_effective_assignment_load(worker, column, modality, skill_counts)
        for worker in filtered_df['PPL'].unique()
    ]
    if len(worker_counts) < 2:
        return False

    max_count = max(worker_counts)
    min_count = min(worker_counts)
    if max_count == 0:
        return False

    imbalance = (max_count - min_count) / max_count
    return imbalance >= (threshold_pct / 100.0)


def _attempt_column_selection(active_df: pd.DataFrame, column: str, modality: str):
    if column not in active_df.columns:
        return None
    filtered_df = active_df[active_df[column] > 0]
    if filtered_df.empty:
        return None
    balanced_df = _apply_minimum_balancer(filtered_df, column, modality)
    result_df = balanced_df if not balanced_df.empty else filtered_df
    result_df = result_df.copy()
    result_df['__skill_source'] = column
    return result_df


def _try_configured_fallback(active_df: pd.DataFrame, current_column: str, modality: str):
    fallback_chain = BALANCER_FALLBACK_CHAIN.get(current_column, [])
    for fallback in fallback_chain:
        if isinstance(fallback, list):
            combined_frames = []
            for fallback_column in fallback:
                result = _attempt_column_selection(active_df, fallback_column, modality)
                if result is not None:
                    combined_frames.append(result)
            if combined_frames:
                merged = pd.concat(combined_frames, ignore_index=True)
                if 'PPL' in merged.columns:
                    merged = merged.drop_duplicates(subset=['PPL'])
                return merged, fallback
        else:
            result = _attempt_column_selection(active_df, fallback, modality)
            if result is not None:
                return result, fallback
    return None, current_column


def get_active_df_for_role(active_df: pd.DataFrame, role: str, modality: str):
    role_map = {
        'normal':  'Normal',
        'notfall': 'Notfall',
        'herz':    'Herz',
        'privat':  'Privat',
        'msk':     'Msk',
        'chest':   'Chest'
    }
    role_lower = role.lower()
    if role_lower not in role_map:
        role_lower = 'normal'
    primary_column = role_map[role_lower]

    selection = _attempt_column_selection(active_df, primary_column, modality)
    if selection is not None:
        filtered_df = selection
        used_column = primary_column
    else:
        filtered_df = None
        used_column = primary_column

    if filtered_df is None:
        filtered_df, used_column = _try_configured_fallback(active_df, primary_column, modality)

    if filtered_df is None:
        filtered_df = _attempt_column_selection(active_df, 'Normal', modality)
        used_column = 'Normal'

    if filtered_df is None:
        return active_df.iloc[0:0], primary_column

    if isinstance(used_column, str) and _should_balance_via_fallback(filtered_df, used_column, modality):
        fallback_df, fallback_column = _try_configured_fallback(active_df, used_column, modality)
        if fallback_df is not None:
            filtered_df = fallback_df
            used_column = fallback_column

    return filtered_df, used_column

def _select_worker_for_modality(current_dt: datetime, role='normal', modality=default_modality):
    d = modality_data[modality]
    if d['working_hours_df'] is None:
        selection_logger.info(f"No working hours data for modality {modality}")
        return None

    tnow = current_dt.time()
    active_df = d['working_hours_df'][
        (d['working_hours_df']['start_time'] <= tnow) &
        (d['working_hours_df']['end_time']   >= tnow)
    ]

    if active_df.empty:
        selection_logger.info(f"No active workers at time {tnow} for modality {modality}")
        return None

    filtered_df, used_column = get_active_df_for_role(active_df, role, modality)
    
    if filtered_df.empty:
        selection_logger.info(f"No workers found for role {role} (using column {used_column}) at time {tnow}")
        return None

    worker_count = len(filtered_df['PPL'].unique())
    selection_logger.info(
        "Found %s workers for role %s (column %s) in modality %s",
        worker_count,
        role,
        used_column,
        modality,
    )

    hours_map = calculate_work_hours_now(current_dt, modality)

    def weighted_ratio(person):
        canonical_id = get_canonical_worker_id(person)
        h = hours_map.get(canonical_id, 0)
        w = get_global_weighted_count(canonical_id)
        return w / h if h > 0 else w

    available_workers = filtered_df['PPL'].unique()

    if len(available_workers) == 0:
        selection_logger.info(f"No workers available after filtering for {used_column}")
        return None

    best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
    candidate = filtered_df[filtered_df['PPL'] == best_person].iloc[0].copy()
    candidate['__modality_source'] = modality
    candidate['__selection_ratio'] = weighted_ratio(best_person)
    selection_logger.info(f"Selected candidate: {best_person}")
    return candidate, used_column


def get_next_available_worker(current_dt: datetime, role='normal', modality=default_modality):
    visited = set()

    def _attempt_modality(target_modality: str):
        if target_modality in visited or target_modality not in modality_data:
            return None
        visited.add(target_modality)
        result = _select_worker_for_modality(current_dt, role, target_modality)
        if result is None:
            return None
        candidate, used_column = result
        return candidate, used_column, target_modality

    search_order = [modality] + MODALITY_FALLBACK_CHAIN.get(modality, [])

    for entry in search_order:
        if isinstance(entry, list):
            candidate_pool = []
            for target_modality in entry:
                attempt = _attempt_modality(target_modality)
                if attempt is None:
                    continue
                candidate, used_column, source_modality = attempt
                ratio = candidate.get('__selection_ratio', float('inf'))
                candidate_pool.append((ratio, candidate, used_column, source_modality))
            if candidate_pool:
                ratio, candidate, used_column, source_modality = min(candidate_pool, key=lambda item: item[0])
                if source_modality != modality:
                    selection_logger.info(
                        "Fallback modality %s used for role %s (requested %s)",
                        source_modality,
                        role,
                        modality,
                    )
                return candidate, used_column, source_modality
        else:
            attempt = _attempt_modality(entry)
            if attempt is not None:
                candidate, used_column, source_modality = attempt
                if source_modality != modality:
                    selection_logger.info(
                        "Fallback modality %s used for role %s (requested %s)",
                        source_modality,
                        role,
                        modality,
                    )
                return candidate, used_column, source_modality

    selection_logger.info(
        "No workers available for role %s across modality fallback chain starting with %s",
        role,
        modality,
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
    # Get the modifier (default 1.0). Values > 1 mean more work, < 1 mean less work.
    modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
    modifier = _coerce_float(modifier, 1.0)
    weight = skill_weights.get(role, 1.0) * modifier * modality_factors.get(modality, 1.0)

    global_worker_data['weighted_counts_per_mod'][modality][canonical_id] = \
        global_worker_data['weighted_counts_per_mod'][modality].get(canonical_id, 0.0) + weight

    assignments = _get_or_create_assignments(modality, canonical_id)
    assignments[role] += 1
    assignments['total'] += 1

    return canonical_id

# -----------------------------------------------------------
# Helper: Live Backup of DataFrame
# -----------------------------------------------------------
def backup_dataframe(modality: str):
    """
    Writes the current working_hours_df for the given modality to a live backup Excel file.
    The backup file will include:
      - "Tabelle1": containing the working_hours_df data without extra columns.
      - "Tabelle2": containing the info_texts (if available).
      
    This version removes the columns 'start_time', 'end_time', and 'shift_duration'.
    """
    d = modality_data[modality]
    if d['working_hours_df'] is not None:
        backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f"SBZ_{modality.upper()}_live.xlsx")
        try:
            # Remove unwanted columns from backup
            cols_to_backup = [col for col in d['working_hours_df'].columns
                              if col not in ['start_time', 'end_time', 'shift_duration']]
            df_backup = d['working_hours_df'][cols_to_backup].copy()
            
            with pd.ExcelWriter(backup_file, engine='openpyxl') as writer:
                # Write the filtered DataFrame into sheet "Tabelle1"
                df_backup.to_excel(writer, sheet_name='Tabelle1', index=False)
                # If info_texts are available, write them into sheet "Tabelle2"
                if d.get('info_texts'):
                    df_info = pd.DataFrame({'Info': d['info_texts']})
                    df_info.to_excel(writer, sheet_name='Tabelle2', index=False)
            selection_logger.info(f"Live backup updated for modality {modality} at {backup_file}")
        except Exception as e:
            selection_logger.info(f"Error backing up DataFrame for modality {modality}: {e}")


# -----------------------------------------------------------
# Startup: initialize each modality – zuerst das aktuelle Live-Backup, dann das Default-File
# -----------------------------------------------------------
for mod, d in modality_data.items():
    backup_dir  = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
    backup_path = os.path.join(backup_dir, f"SBZ_{mod.upper()}_live.xlsx")

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

    # Determine available specialties based on currently active working hours
    available_specialties = {SKILL_SLUG_MAP[skill]: False for skill in SKILL_COLUMNS}
    if d['working_hours_df'] is not None:
        tnow = get_local_berlin_now().time()
        active_df = d['working_hours_df'][
            (d['working_hours_df']['start_time'] <= tnow) &
            (d['working_hours_df']['end_time'] >= tnow)
        ]
        for skill in SKILL_COLUMNS:
            slug = SKILL_SLUG_MAP[skill]
            available_specialties[slug] = bool(
                (skill in active_df.columns) and (active_df[skill].sum() > 0)
            )

    for entry in SKILL_TEMPLATES:
        if entry['always_visible']:
            available_specialties[entry['slug']] = True

    return render_template(
        'index.html',
        available_specialties=available_specialties,
        info_texts=d.get('info_texts', []),
        modality=modality
    )

def get_admin_password():
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("admin_password", "")
    except Exception as e:
        selection_logger.info("Error loading config.yaml:", e)
        return ""

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


@app.route('/upload', methods=['GET', 'POST'])
@admin_required
def upload_file():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({"error": "Keine Datei ausgewählt"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Keine Datei ausgewählt"}), 400
        if not file.filename.endswith('.xlsx'):
            return jsonify({"error": "Ungültiger Dateityp"}), 400
        scheduled = request.form.get('scheduled_upload', '0')
        file_path = None
        try:
            if scheduled == '1':
                file.save(d['scheduled_file_path'])
                return redirect(url_for('upload_file', modality=modality))
            else:
                # For immediate uploads, reset all counters BEFORE loading the file
                d['draw_counts'] = {}
                d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
                d['WeightedCounts'] = {}
                global_worker_data['weighted_counts_per_mod'][modality] = {}
                global_worker_data['assignments_per_mod'][modality] = {}
                
                # Now save and load the file
                file_path = d['default_file_path']
                file.save(file_path)
                d['last_uploaded_filename'] = os.path.basename(file_path)
                initialize_data(file_path, modality)
                # Update live backup on new upload
                backup_dataframe(modality)
                return redirect(url_for('upload_file', modality=modality))
        except Exception as e:
            if file_path:
                quarantine_excel(file_path, f"upload {modality}: {e}")
            return jsonify({"error": f"Fehler beim Hochladen der Datei: {e}"}), 500

    # GET method: Prepare data for the upload page
    # 1. Debug info table from working_hours_df.
    debug_info = (
        d['working_hours_df'].to_html(index=True)
        if d['working_hours_df'] is not None else "Keine Daten verfügbar"
    )

    # 2. Prepare JSON for timeline usage.
    if d['working_hours_df'] is not None:
        df_for_json = d['working_hours_df'].copy()
        df_for_json['start_time'] = df_for_json['start_time'].apply(
            lambda t: t.strftime('%H:%M:%S') if pd.notnull(t) else ""
        )
        df_for_json['end_time'] = df_for_json['end_time'].apply(
            lambda t: t.strftime('%H:%M:%S') if pd.notnull(t) else ""
        )
        debug_data = df_for_json.to_json(orient='records')
    else:
        debug_data = "[]"

    # 3. Compute per‑skill counts and summed counts per worker.
    skill_counts = {skill: d['skill_counts'].get(skill, {}) for skill in SKILL_COLUMNS}
    worker_names = set()
    for skill in SKILL_COLUMNS:
        worker_names.update(skill_counts.get(skill, {}).keys())

    sum_counts = {}
    for worker in worker_names:
        total = sum(skill_counts[skill].get(worker, 0) for skill in SKILL_COLUMNS)
        sum_counts[worker] = total

    # 4. Compute global assignments and weighted counts.
    global_counts = {}
    global_weighted_counts = {}
    for worker in worker_names:
        canonical = get_canonical_worker_id(worker)
        global_counts[worker] = get_global_assignments(canonical)
        global_weighted_counts[worker] = get_global_weighted_count(canonical)

    # 5. Build the combined stats for a unified table.
    combined_workers = sorted(set(sum_counts.keys()) | set(global_counts.keys()))
    modality_stats = {}
    for worker in combined_workers:
        modality_stats[worker] = {
            skill: skill_counts.get(skill, {}).get(worker, 0)
            for skill in SKILL_COLUMNS
        }
        modality_stats[worker]['total'] = sum(
            modality_stats[worker][skill] for skill in SKILL_COLUMNS
        )

    # 6. Get info texts.
    info_texts = d.get('info_texts', [])

    # 7. Re-run the operational checks so admins immediately see the latest status.
    checks = run_operational_checks('admin_view', force=True)

    return render_template(
        'upload.html',
        debug_info=debug_info,
        debug_data=debug_data,
        modality=modality,
        skill_counts=skill_counts,
        sum_counts=sum_counts,     
        global_counts=global_counts,
        global_weighted_counts=global_weighted_counts,
        combined_workers=combined_workers,
        modality_stats=modality_stats,
        info_texts=info_texts,
        operational_checks=checks,
    )


@app.route('/api/<modality>/<role>', methods=['GET'])
def assign_worker_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role)

def _assign_worker(modality: str, role: str):
    try:
        requested_data = modality_data[modality]
        now = get_local_berlin_now()
        selection_logger.info(f"Assignment request: modality={modality}, role={role}, time={now.strftime('%H:%M:%S')}")

        with lock:
            result = get_next_available_worker(now, role=role, modality=modality)
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
                    modifier = candidate.get('Modifier', 1.0)
                    if person not in d['WeightedCounts']:
                        d['WeightedCounts'][person] = 0.0
                    d['WeightedCounts'][person] += (
                        skill_weights.get(actual_skill, 1.0)
                        * modifier
                        * modality_factors.get(actual_modality, 1.0)
                    )

                canonical_id = update_global_assignment(person, actual_skill, actual_modality)
                
                skill_counts = {}
                for skill in SKILL_COLUMNS:
                    if skill in d['skill_counts']:
                        skill_counts[skill] = {w: int(v) for w, v in d['skill_counts'][skill].items()}
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
                }
                for skill in SKILL_COLUMNS:
                    result_data[skill] = skill_counts.get(skill, {})
            else:
                d = requested_data
                empty_counts = {w: 0 for w in d['draw_counts']}
                skill_counts = {skill: empty_counts.copy() for skill in SKILL_COLUMNS}
                sum_counts = {w: 0 for w in d['draw_counts']}

                result_data = {
                    "Draw Time": now.strftime('%H:%M:%S'),
                    "Assigned Person": "Bitte nochmal klicken",
                    "Summe": sum_counts,
                    "Global": {},
                    "modality_requested": modality,
                    "modality_used": None,
                    "skill_used": None,
                }
                for skill in SKILL_COLUMNS:
                    result_data[skill] = skill_counts.get(skill, {})
        return jsonify(result_data)
    except Exception as e:
        app.logger.exception("Error in _assign_worker")
        return jsonify({"error": str(e)}), 500

@app.route('/edit_info', methods=['POST'])
def edit_info():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    new_info = request.form.get('info_text', '')
    d['info_texts'] = [line.strip() for line in new_info.splitlines() if line.strip()]
    selection_logger.info(f"Updated info_texts for {modality}: {d['info_texts']}")
    return redirect(url_for('upload_file', modality=modality))

@app.route('/download')
def download_file():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    return send_from_directory(app.config['UPLOAD_FOLDER'], d['last_uploaded_filename'], as_attachment=True)

@app.route('/download_latest')
def download_latest():
    modality = resolve_modality_from_request()
    backup_dataframe(modality)  # always ensure the latest backup is current
    backup_file = os.path.join(app.config['UPLOAD_FOLDER'], "backups", f"SBZ_{modality.upper()}_live.xlsx")
    if os.path.exists(backup_file):
        return send_from_directory(
            os.path.join(app.config['UPLOAD_FOLDER'], "backups"),
            os.path.basename(backup_file),
            as_attachment=True
        )
    else:
        return jsonify({"error": "Backup file unavailable."}), 404

@app.route('/edit', methods=['POST'])
def edit_entry():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    idx_str = request.form.get('index')
    person  = request.form['person']
    time_str= request.form['time']
    modifier_str = request.form.get('modifier', '1.0').strip().replace(',', '.')
    new_modifier = float(modifier_str) if modifier_str else 1.0

    with lock:
        if d['working_hours_df'] is None:
            return redirect(url_for('upload_file', modality=modality))

        if idx_str:
            idx = int(idx_str)
            if 0 <= idx < len(d['working_hours_df']):
                old_person = d['working_hours_df'].at[idx, 'PPL']
                old_canonical = get_canonical_worker_id(old_person)
                new_canonical = get_canonical_worker_id(person)
                
                d['working_hours_df'].at[idx, 'PPL'] = person
                d['working_hours_df'].at[idx, 'canonical_id'] = new_canonical
                d['working_hours_df'].at[idx, 'TIME'] = time_str
                d['working_hours_df'].at[idx, 'Modifier'] = new_modifier
                d['worker_modifiers'][person] = new_modifier

                # Ensure all SKILL_COLUMNS exist in the dataframe
                for skill in SKILL_COLUMNS:
                    form_key = SKILL_FORM_KEYS.get(skill, skill.lower())
                    val_str = request.form.get(form_key, '0').strip()
                    new_val = int(val_str) if val_str else 0
                    
                    # Add column if it doesn't exist
                    if skill not in d['working_hours_df'].columns:
                        d['working_hours_df'][skill] = 0
                        
                    d['working_hours_df'].at[idx, skill] = new_val

                if person != old_person:
                    d['draw_counts'][person] = d['draw_counts'].get(person, 0) + d['draw_counts'].pop(old_person, 0)
                    for skill in SKILL_COLUMNS:
                        # Ensure both old and new persons exist in all skill dictionaries
                        if skill not in d['skill_counts']:
                            d['skill_counts'][skill] = {}
                        if old_person not in d['skill_counts'][skill]:
                            d['skill_counts'][skill][old_person] = 0
                        if person not in d['skill_counts'][skill]:
                            d['skill_counts'][skill][person] = 0
                            
                        d['skill_counts'][skill][person] = d['skill_counts'][skill].get(person, 0) + d['skill_counts'][skill].pop(old_person, 0)
                    d['WeightedCounts'][person] = d['WeightedCounts'].get(person, 0) + d['WeightedCounts'].pop(old_person, 0)
                
        else:
            # This is for adding a new row - similar fixes needed here
            canonical_id = get_canonical_worker_id(person)
            data_dict = {
                'PPL': person,
                'canonical_id': canonical_id,
                'TIME': time_str,
                'Modifier': new_modifier,
            }
            for skill in SKILL_COLUMNS:
                form_key = SKILL_FORM_KEYS.get(skill, skill.lower())
                val_str = request.form.get(form_key, '0').strip()
                data_dict[skill] = int(val_str) if val_str else 0
            new_row = pd.DataFrame([data_dict])
            
            # Add missing columns to working_hours_df if needed
            for skill in SKILL_COLUMNS:
                if skill not in d['working_hours_df'].columns:
                    d['working_hours_df'][skill] = 0
                    
            d['working_hours_df'] = pd.concat([d['working_hours_df'], new_row], ignore_index=True)
            if person not in d['draw_counts']:
                d['draw_counts'][person] = 0
            for skill in SKILL_COLUMNS:
                if skill not in d['skill_counts']:
                    d['skill_counts'][skill] = {}
                if person not in d['skill_counts'][skill]:
                    d['skill_counts'][skill][person] = 0
            if person not in d['WeightedCounts']:
                d['WeightedCounts'][person] = 0.0
            d['worker_modifiers'][person] = new_modifier

        d['working_hours_df']['start_time'], d['working_hours_df']['end_time'] = zip(*d['working_hours_df']['TIME'].map(parse_time_range))
        d['working_hours_df']['shift_duration'] = d['working_hours_df'].apply(
            lambda row: (datetime.combine(datetime.min, row['end_time']) - datetime.combine(datetime.min, row['start_time'])).total_seconds() / 3600.0,
            axis=1
        )
        d['total_work_hours'] = d['working_hours_df'].groupby('PPL')['shift_duration'].sum().to_dict()
        
        # Update live backup after editing
        backup_dataframe(modality)

    return redirect(url_for('upload_file', modality=modality))
@app.route('/delete', methods=['POST'])
def delete_entry():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    idx = int(request.form['index'])
    with lock:
        if d['working_hours_df'] is not None and 0 <= idx < len(d['working_hours_df']):
            d['working_hours_df'].at[idx, 'TIME'] = '00:00-00:00'
            d['working_hours_df'].at[idx, 'start_time'], d['working_hours_df'].at[idx, 'end_time'] = parse_time_range('00:00-00:00')
            d['working_hours_df']['shift_duration'] = d['working_hours_df'].apply(
                lambda row: (datetime.combine(datetime.min, row['end_time']) - datetime.combine(datetime.min, row['start_time'])).total_seconds() / 3600.0,
                axis=1
            )
            d['total_work_hours'] = d['working_hours_df'].groupby('PPL')['shift_duration'].sum().to_dict()
            # Update live backup after deletion
            backup_dataframe(modality)
    return redirect(url_for('upload_file', modality=modality))

@app.route('/get_entry', methods=['GET'])
def get_entry():
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    idx = request.args.get('index', type=int)
    if d['working_hours_df'] is not None and idx is not None and 0 <= idx < len(d['working_hours_df']):
        entry = d['working_hours_df'].iloc[idx]

        # Start building the response with core fields:
        resp = {
            'person':   entry.get('PPL', ''),       # or entry['PPL'] if guaranteed to exist
            'time':     entry.get('TIME', '00:00-00:00'),
            'modifier': entry.get('Modifier', 1.0)
        }

        # Convert skill columns to int safely:
        for skill in SKILL_COLUMNS:
            form_key = SKILL_FORM_KEYS.get(skill, skill.lower())
            if skill in entry:
                val = entry[skill]
                if pd.isna(val):
                    val = 0
                try:
                    resp[form_key] = int(val)
                except (ValueError, TypeError):
                    resp[form_key] = 0
            else:
                resp[form_key] = 0

        return jsonify(resp)

    # If index is out of range or DataFrame is empty:
    return jsonify({"error": "Ungültiger Index"}), 400



@app.route('/api/quick_reload', methods=['GET'])
def quick_reload():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    now = get_local_berlin_now()
    checks = run_operational_checks('reload', force=True)
    
    # Determine available buttons based on currently active working hours
    available_buttons = {SKILL_SLUG_MAP[skill]: False for skill in SKILL_COLUMNS}
    if d['working_hours_df'] is not None:
        tnow = now.time()
        active_df = d['working_hours_df'][
            (d['working_hours_df']['start_time'] <= tnow) &
            (d['working_hours_df']['end_time'] >= tnow)
        ]
        for skill in SKILL_COLUMNS:
            slug = SKILL_SLUG_MAP[skill]
            available_buttons[slug] = bool((skill in active_df.columns) and (active_df[skill].sum() > 0))

    for entry in SKILL_TEMPLATES:
        if entry['always_visible']:
            available_buttons[entry['slug']] = True
            
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


@app.route('/timetable')
def timetable():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    if d['working_hours_df'] is not None:
        df_for_json = d['working_hours_df'].copy()
        df_for_json['start_time'] = df_for_json['start_time'].apply(lambda t: t.strftime('%H:%M:%S') if pd.notnull(t) else "")
        df_for_json['end_time'] = df_for_json['end_time'].apply(lambda t: t.strftime('%H:%M:%S') if pd.notnull(t) else "")
        debug_data = df_for_json.to_json(orient='records')
    else:
        debug_data = "[]"
    return render_template('timetable.html', debug_data=debug_data, modality=modality)







app.config['DEBUG'] = True

if __name__ == '__main__':
    app.run()

    
    