# Standard library imports
import os
import yaml
import copy
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, List, Tuple, Optional
from utils import (
    coerce_float,
    coerce_int,
    normalize_modality_fallback_entries,
    selection_logger
)

# -----------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

MASTER_CSV_PATH = os.path.join(UPLOAD_FOLDER, 'master_medweb.csv')
STATE_FILE_PATH = os.path.join(UPLOAD_FOLDER, 'fairness_state.json')

os.makedirs('logs', exist_ok=True)
selection_logger.setLevel(logging.INFO)

# Avoid adding multiple handlers if reloaded
if not selection_logger.handlers:
    handler = RotatingFileHandler('logs/selection.log', maxBytes=10_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    selection_logger.addHandler(handler)

# -----------------------------------------------------------
# Default Constants
# -----------------------------------------------------------
DEFAULT_ADMIN_PASSWORD = 'change_pw_for_live'

DEFAULT_BALANCER = {
    'enabled': True,
    'min_assignments_per_skill': 5,
    'imbalance_threshold_pct': 30,
    'allow_fallback_on_imbalance': True,
}

# -----------------------------------------------------------
# Config Loading Logic
# -----------------------------------------------------------
def _load_raw_config() -> Dict[str, Any]:
    try:
        with open('config.yaml', 'r', encoding='utf-8') as config_file:
            return yaml.safe_load(config_file) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        selection_logger.warning("Failed to load config.yaml: %s", exc)
        return {}

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
        values['factor'] = coerce_float(values.get('factor', 1.0))

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
        values['weight'] = coerce_float(values.get('weight', 1.0))
        values.setdefault('optional', False)
        values.setdefault('special', False)
        values.setdefault('always_visible', True)  # Default: always visible
        values['display_order'] = coerce_int(values.get('display_order', 0))
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
            normalized_fallbacks[mod.lower()] = normalize_modality_fallback_entries(
                fallback_list,
                mod,
                list(merged_modalities.keys()),
            )
    config['modality_fallbacks'] = normalized_fallbacks

    # Include medweb_mapping
    config['medweb_mapping'] = raw_config.get('medweb_mapping', {})

    # Include worker_roster
    config['worker_roster'] = raw_config.get('worker_roster', {})

    # Include skill_modality_overrides
    config['skill_modality_overrides'] = raw_config.get('skill_modality_overrides', {})

    # Include shift_times
    config['shift_times'] = raw_config.get('shift_times', {})

    # Include UI colors (needed for prep page)
    config['ui_colors'] = raw_config.get('ui_colors', {})
    config['skill_value_colors'] = raw_config.get('skill_value_colors', {})

    # Skill dashboard behavior
    skill_dashboard_config = raw_config.get('skill_dashboard', {})
    if not isinstance(skill_dashboard_config, dict):
        skill_dashboard_config = {}
    config['skill_dashboard'] = {
        'hide_invalid_combinations': bool(
            skill_dashboard_config.get('hide_invalid_combinations', False)
        )
    }

    # Scheduler settings
    config['scheduler'] = raw_config.get('scheduler', {
        'daily_reset_time': '07:30',
        'auto_preload_time': 14
    })

    # Auto-import toggle for worker skill roster
    config['skill_roster_auto_import'] = bool(
        raw_config.get('skill_roster_auto_import', True)
    )

    return config

def _build_skill_metadata(skills_config: Dict[str, Dict[str, Any]]) -> Tuple[List[str], Dict[str, str], Dict[str, str], List[Dict[str, Any]], Dict[str, float]]:
    ordered_skills = sorted(
        skills_config.items(),
        key=lambda item: (coerce_int(item[1].get('display_order', 0)), item[0])
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
        weights[name] = coerce_float(data.get('weight', 1.0))

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

# -----------------------------------------------------------
# Global Configuration Objects
# -----------------------------------------------------------
APP_CONFIG = _build_app_config()
MODALITY_SETTINGS = APP_CONFIG['modalities']
SKILL_SETTINGS = APP_CONFIG['skills']
SKILL_DASHBOARD_SETTINGS = APP_CONFIG.get('skill_dashboard', {})
SKILL_ROSTER_AUTO_IMPORT = APP_CONFIG.get('skill_roster_auto_import', True)

allowed_modalities = list(MODALITY_SETTINGS.keys())
allowed_modalities_map = {m.lower(): m for m in allowed_modalities}
default_modality = allowed_modalities[0] if allowed_modalities else 'ct'
modality_labels = {
    mod: settings.get('label', mod.upper())
    for mod, settings in MODALITY_SETTINGS.items()
}
modality_factors = {
    mod: settings.get('factor', 1.0)
    for mod, settings in MODALITY_SETTINGS.items()
}

# Load skillxmodality weight overrides
skill_modality_overrides = APP_CONFIG.get('skill_modality_overrides', {})

# Build skill metadata
SKILL_COLUMNS, SKILL_SLUG_MAP, SKILL_FORM_KEYS, SKILL_TEMPLATES, skill_weights = _build_skill_metadata(SKILL_SETTINGS)

# Build dynamic role map from config (slug -> canonical name)
ROLE_MAP = {slug.lower(): name for name, slug in SKILL_SLUG_MAP.items()}

BALANCER_SETTINGS = APP_CONFIG.get('balancer', DEFAULT_BALANCER)

# Exclusion rules and fallback chain
EXCLUSION_RULES = BALANCER_SETTINGS.get('exclusion_rules', {})

RAW_MODALITY_FALLBACKS = APP_CONFIG.get('modality_fallbacks', {})
MODALITY_FALLBACK_CHAIN = {}
for mod in allowed_modalities:
    configured = RAW_MODALITY_FALLBACKS.get(mod, RAW_MODALITY_FALLBACKS.get(mod.lower(), []))
    MODALITY_FALLBACK_CHAIN[mod] = normalize_modality_fallback_entries(
        configured,
        mod,
        allowed_modalities,
    )

# -----------------------------------------------------------
# Helper function
# -----------------------------------------------------------
def get_skill_modality_weight(skill: str, modality: str) -> float:
    """
    Get the weight for a skillxmodality combination.
    """
    # Check for explicit override first
    modality_overrides = skill_modality_overrides.get(modality, {})
    if skill in modality_overrides:
        return coerce_float(modality_overrides[skill], 1.0)

    # Fall back to default calculation: skill_weight x modality_factor
    return skill_weights.get(skill, 1.0) * modality_factors.get(modality, 1.0)


def normalize_modality(modality_value: Optional[str]) -> str:
    if not modality_value:
        return default_modality
    modality_value_lower = modality_value.lower()
    return allowed_modalities_map.get(modality_value_lower, default_modality)


def normalize_skill(skill_name: Optional[str]) -> str:
    if not skill_name:
        return SKILL_COLUMNS[0] if SKILL_COLUMNS else ''
    skill_lower = skill_name.lower().strip()
    for s in SKILL_COLUMNS:
        if s.lower() == skill_lower:
            return s
    return skill_name.strip()

