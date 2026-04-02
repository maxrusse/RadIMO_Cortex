"""
Worker management module for handling worker IDs, skill rosters, and worker data.

This module provides functions for:
- Canonical worker ID mapping
- Skill roster loading/saving (JSON)
- Worker-skill-modality combination management
- Skill roster merging (YAML + JSON)
"""
import copy
from typing import Dict, Any, List, Iterable, Mapping, Optional, Tuple

import pandas as pd

from config import (
    allowed_modalities,
    SKILL_COLUMNS,
    MODALITY_SETTINGS,
    allowed_modalities_map,
    skill_columns_map,
    BALANCER_SETTINGS,
    WORKER_SKILL_ROSTER_PATH,
    selection_logger,
)
from lib.utils import is_weighted_skill, normalize_skill_value
from state_manager import StateManager

# Get state references
_state = StateManager.get_instance()
global_worker_data = _state.global_worker_data
worker_skill_json_roster = _state.worker_skill_json_roster


def get_canonical_worker_id(worker_name: Optional[str]) -> str:
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


def invalidate_work_hours_cache(modality: Optional[str] = None) -> None:
    """Invalidate the work hours cache when modality data changes.

    Args:
        modality: Specific modality to invalidate, or None for all modalities.
    """
    _state.invalidate_work_hours_cache(modality)


def get_all_workers_by_canonical_id() -> Dict[str, List[str]]:
    """Get mapping of canonical IDs to all name variations."""
    canonical_to_variations: Dict[str, List[str]] = {}
    for name, canonical in global_worker_data['worker_ids'].items():
        canonical_to_variations.setdefault(canonical, []).append(name)
    return canonical_to_variations


def build_worker_name_mapping(roster: Dict[str, Any]) -> Dict[str, str]:
    """
    Build a mapping from worker IDs to display names.

    For each worker in the roster, returns the best available display name:
    1. full_name field from roster if present
    2. Longest name variation from global_worker_data (usually the full name)
    3. The worker ID itself as fallback

    Args:
        roster: The skill roster dictionary

    Returns:
        Dict mapping worker_id -> display_name
    """
    name_mapping = {}
    canonical_to_variations = get_all_workers_by_canonical_id()

    for worker_id in roster.keys():
        # First priority: full_name in roster entry
        if isinstance(roster[worker_id], dict) and 'full_name' in roster[worker_id]:
            name_mapping[worker_id] = roster[worker_id]['full_name']
            continue

        # Second priority: longest variation from global worker data
        variations = canonical_to_variations.get(worker_id, [])
        if variations:
            # Prefer the longest name (usually "Dr. Name (ID)")
            name_mapping[worker_id] = max(variations, key=len)
            continue

        # Fallback: use the ID itself
        name_mapping[worker_id] = worker_id

    return name_mapping


def load_worker_skill_json() -> Dict[str, Any]:
    """Load worker skill roster from JSON file."""
    from data_manager.json_manager import load_json, migrate_file_to_data_dir

    # Migrate from old location if needed (root level worker_skill_roster.json)
    import os
    old_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'worker_skill_roster.json')
    if os.path.exists(old_path) and not os.path.exists(WORKER_SKILL_ROSTER_PATH):
        migrate_file_to_data_dir(old_path, WORKER_SKILL_ROSTER_PATH)
        selection_logger.info("Migrated worker_skill_roster.json to data/ folder")

    data = load_json(WORKER_SKILL_ROSTER_PATH, default={})

    # Update global cache
    worker_skill_json_roster.clear()
    worker_skill_json_roster.update(data)

    if data:
        selection_logger.info(f"Loaded worker skill roster: {len(data)} workers")
    else:
        selection_logger.info("No worker skill roster found, using empty roster")

    return data


def save_worker_skill_json(roster_data: Dict[str, Any], *, create_backup: bool = True) -> bool:
    """Save worker skill roster to JSON file with optional backup."""
    from data_manager.json_manager import save_json

    success = save_json(
        WORKER_SKILL_ROSTER_PATH,
        roster_data,
        create_backup=create_backup,
    )

    if success:
        selection_logger.info(f"Saved worker skill roster: {len(roster_data)} workers")
        # Update global cache
        worker_skill_json_roster.clear()
        worker_skill_json_roster.update(roster_data)
    else:
        selection_logger.error("Failed to save worker skill roster")

    return success


def build_valid_skills_map() -> Dict[str, List[str]]:
    """Build map of valid skills per modality (for filtering in UI)."""
    return {
        mod: settings.get('valid_skills', SKILL_COLUMNS)
        for mod, settings in MODALITY_SETTINGS.items()
    }


def normalize_skill_mod_key(key: str) -> str:
    """
    Normalize skill_modality key to canonical format: "skill_modality".

    Accepts both "skill_modality" and "modality_skill" formats.
    Returns canonical "skill_modality" format with case-insensitive matching.

    Examples:
        "mdh_ct" -> "mdh_ct"
        "ct_mdh" -> "mdh_ct"
        "MSK-HAUT_CT" -> "mdh_ct"  (case-insensitive)
        "notfall_mr" -> "notfall_mr"
    """
    if '_' not in key:
        return key

    parts = key.split('_', 1)
    if len(parts) != 2:
        return key

    part1_lower, part2_lower = parts[0].lower(), parts[1].lower()

    # Check if part1 is a skill and part2 is a modality
    skill1 = skill_columns_map.get(part1_lower)
    mod2 = allowed_modalities_map.get(part2_lower)
    if skill1 and mod2:
        return f"{skill1}_{mod2}"  # skill_modality format

    # Check if part1 is a modality and part2 is a skill (reversed)
    mod1 = allowed_modalities_map.get(part1_lower)
    skill2 = skill_columns_map.get(part2_lower)
    if mod1 and skill2:
        return f"{skill2}_{mod1}"  # Normalize to skill_modality

    # Unknown format - return as-is
    return key


def _build_skill_mod_map(
    default_value: Any,
    skills: Iterable[str] = SKILL_COLUMNS,
    modalities: Iterable[str] = allowed_modalities,
) -> Dict[str, Any]:
    return {f"{skill}_{mod}": default_value for skill in skills for mod in modalities}


def build_disabled_worker_entry() -> Dict[str, Any]:
    """
    Create a new worker entry with all Skill x Modality combinations disabled (-1).

    Format: {"skill_modality": -1, ...} (flat structure)
    Example: {"mdh_ct": -1, "mdh_mr": -1, "notfall_ct": -1, ...}
    """
    return _build_skill_mod_map(-1)


def build_passive_worker_entry() -> Dict[str, Any]:
    """
    Create a new worker entry with all Skill x Modality combinations passive (0).

    Format: {"skill_modality": 0, ...} (flat structure)
    """
    return _build_skill_mod_map(0)


def _load_medweb_csv_dataframe(csv_path: str) -> pd.DataFrame:
    """Load a Medweb CSV using the encodings/ separators we support."""
    read_attempts = [
        {'sep': ',', 'encoding': 'utf-8'},
        {'sep': ',', 'encoding': 'latin1'},
        {'sep': ';', 'encoding': 'utf-8'},
        {'sep': ';', 'encoding': 'latin1'},
    ]

    csv_df: Optional[pd.DataFrame] = None
    last_error: Optional[Exception] = None
    for kwargs in read_attempts:
        try:
            csv_df = pd.read_csv(csv_path, **kwargs)
            break
        except Exception as exc:
            last_error = exc

    if csv_df is None:
        raise ValueError(f"Fehler beim Laden der CSV: {last_error}")

    return csv_df


def _build_medweb_worker_candidate(
    row: pd.Series,
    *,
    name_col: str,
    personalnummer_col: str,
    code_col: str,
    activity_col: str,
    rules: List[dict],
) -> Optional[Dict[str, Any]]:
    """Build a single worker candidate from a CSV row."""
    activity_desc = row.get(activity_col, '')
    activity_desc = '' if pd.isna(activity_desc) else str(activity_desc).strip()
    matched_rule = _match_csv_activity_rule(activity_desc, rules)
    auto_import_eligible = bool(matched_rule and matched_rule.get('type', 'shift') == 'shift')

    employee_name = row.get(name_col, '')
    employee_personalnummer = row.get(personalnummer_col, '')
    employee_code = row.get(code_col, '')

    if pd.isna(employee_name) and pd.isna(employee_personalnummer) and pd.isna(employee_code):
        return None

    employee_name = '' if pd.isna(employee_name) else str(employee_name).strip()
    employee_personalnummer = '' if pd.isna(employee_personalnummer) else str(employee_personalnummer).strip()
    employee_code = '' if pd.isna(employee_code) else str(employee_code).strip()

    if employee_name and (employee_name.startswith('!') or 'findet nicht statt' in employee_name.lower()):
        return None

    if not employee_name and not employee_personalnummer and not employee_code:
        return None

    worker_code = employee_personalnummer or employee_code
    full_name = (
        f"{employee_name} ({worker_code})"
        if employee_name and worker_code else
        employee_name or worker_code
    )
    worker_id = get_canonical_worker_id(full_name)
    if not worker_id:
        return None

    source_date = row.get('Datum', '')
    source_day_part = row.get('Tageszeit', '')
    source_date = '' if pd.isna(source_date) else str(source_date).strip()
    source_day_part = '' if pd.isna(source_day_part) else str(source_day_part).strip()

    return {
        'worker_id': worker_id,
        'full_name': full_name or worker_id,
        'display_name': full_name or worker_id,
        'employee_name': employee_name,
        'employee_code': employee_code,
        'employee_personalnummer': employee_personalnummer,
        'auto_import_eligible': auto_import_eligible,
        'source_activity': activity_desc,
        'source_date': source_date,
        'source_day_part': source_day_part,
    }


def get_missing_csv_worker_candidates(csv_path: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return unique workers found in the CSV that are not already present in the roster.

    The list includes people from any CSV activity row, so it can be used for a
    manual import picker. Each candidate also reports whether the current auto-import
    rules would classify at least one of their rows as a shift.
    """
    vendor_mapping = config.get('medweb_mapping', {})
    rules = vendor_mapping.get('rules', [])
    cols = vendor_mapping.get('columns', {
        'employee_name': 'Name des Mitarbeiters',
        'employee_personalnummer': 'Personalnummer',
        'employee_code': 'Code des Mitarbeiters',
        'activity': 'Beschreibung der Aktivität',
    })
    name_col = cols.get('employee_name', 'Name des Mitarbeiters')
    personalnummer_col = cols.get('employee_personalnummer', 'Personalnummer')
    code_col = cols.get('employee_code', 'Code des Mitarbeiters')
    activity_col = cols.get('activity', 'Beschreibung der Aktivität')

    import os
    if not os.path.exists(csv_path):
        selection_logger.info("CSV candidate scan skipped because %s does not exist", csv_path)
        return []

    csv_df = _load_medweb_csv_dataframe(csv_path)
    roster = load_worker_skill_json()
    candidates: Dict[str, Dict[str, Any]] = {}

    for _, row in csv_df.iterrows():
        candidate = _build_medweb_worker_candidate(
            row,
            name_col=name_col,
            personalnummer_col=personalnummer_col,
            code_col=code_col,
            activity_col=activity_col,
            rules=rules,
        )
        if candidate is None:
            continue
        worker_id = candidate['worker_id']
        if worker_id in roster:
            continue
        existing = candidates.get(worker_id)
        if existing is None:
            candidates[worker_id] = candidate
            continue
        if candidate['auto_import_eligible'] and not existing['auto_import_eligible']:
            existing['auto_import_eligible'] = True
            existing['source_activity'] = candidate['source_activity']
            existing['source_date'] = candidate['source_date']
            existing['source_day_part'] = candidate['source_day_part']

    return sorted(candidates.values(), key=lambda item: (item.get('display_name', '').lower(), item.get('worker_id', '').lower()))


def import_csv_worker_to_skill_roster(csv_path: str, config: Dict[str, Any], worker_id: str) -> Dict[str, Any]:
    """
    Import a single CSV worker into the skill roster using a passive baseline.

    Returns the imported candidate metadata.
    """
    worker_id = '' if worker_id is None else str(worker_id).strip()
    if not worker_id:
        raise ValueError("Missing worker_id")

    candidates = get_missing_csv_worker_candidates(csv_path, config)
    candidate = next((item for item in candidates if item.get('worker_id') == worker_id), None)
    if candidate is None:
        raise ValueError(f"Worker {worker_id} not found in CSV candidates")

    roster = load_worker_skill_json()
    if worker_id in roster:
        return candidate

    entry = build_passive_worker_entry()
    if candidate.get('full_name'):
        entry['full_name'] = candidate['full_name']
    roster[worker_id] = entry
    save_worker_skill_json(roster)
    return candidate


def ensure_workers_in_skill_roster(worker_names: Iterable[str]) -> Tuple[int, List[str]]:
    """
    Ensure the provided worker names exist in the JSON skill roster.

    Missing workers are added as lightweight metadata-only entries so
    shift-level overrides can activate them later without overwriting
    config/YAML roster definitions for the same worker.
    Existing workers are left unchanged, except that their full_name is
    backfilled when missing.
    """
    roster = load_worker_skill_json()
    added_count = 0
    added_workers: List[str] = []
    roster_updated = False

    for worker_name in worker_names:
        full_name = '' if worker_name is None else str(worker_name).strip()
        if not full_name:
            continue

        worker_id = get_canonical_worker_id(full_name)
        if not worker_id:
            continue

        if worker_id in roster:
            if isinstance(roster[worker_id], dict) and 'full_name' not in roster[worker_id]:
                roster[worker_id]['full_name'] = full_name
                roster_updated = True
            continue

        entry = {'full_name': full_name}
        roster[worker_id] = entry
        added_count += 1
        added_workers.append(worker_id)
        roster_updated = True
        selection_logger.info(
            "Auto-added synthetic worker %s (%s) to skill roster as metadata-only seed",
            worker_id,
            full_name,
        )

    if roster_updated:
        save_worker_skill_json(roster)

    return added_count, added_workers


def get_roster_modifier(canonical_id: str) -> float:
    """
    Get worker's 'w' modifier from skill roster.

    Returns the 'modifier' field from the worker's roster entry.
    This modifier is only applied to 'w' (weighted/training) assignments.
    Defaults to balancer default_w_modifier if not set.

    Args:
        canonical_id: Worker's canonical ID

    Returns:
        Modifier value (float), defaults to balancer default
    """
    # Ensure roster is loaded
    if not worker_skill_json_roster:
        load_worker_skill_json()

    worker_data = worker_skill_json_roster.get(canonical_id, {})
    default_modifier = BALANCER_SETTINGS.get('default_w_modifier', 1.0)
    modifier = worker_data.get('modifier', default_modifier)

    try:
        modifier = float(modifier)
        if modifier <= 0:
            modifier = default_modifier
    except (TypeError, ValueError):
        modifier = default_modifier

    return modifier


def get_roster_modifier_raw(canonical_id: str) -> Optional[float]:
    """
    Get worker's explicit roster 'modifier' value without default fallback.

    Returns None when no explicit roster modifier is set (or value is invalid).
    This is useful when callers need to combine roster modifier with
    balancer.default_w_modifier explicitly.

    Args:
        canonical_id: Worker's canonical ID

    Returns:
        Explicit roster modifier as float, or None
    """
    if not worker_skill_json_roster:
        load_worker_skill_json()

    worker_data = worker_skill_json_roster.get(canonical_id, {})
    if 'modifier' not in worker_data:
        return None

    raw_modifier = worker_data.get('modifier')
    try:
        modifier = float(raw_modifier)
        if modifier <= 0:
            return None
        return modifier
    except (TypeError, ValueError):
        return None


def auto_populate_skill_roster(modality_dfs: Dict[str, pd.DataFrame]) -> tuple:
    """
    Auto-populate skill roster with new workers found in uploaded schedules.

    New workers are added with all skills passive (0) by default.
    Uses canonical_id (derived from PPL if not present) to ensure consistent worker IDs.
    Stores full_name alongside the canonical ID for display purposes.

    Returns:
        Tuple of (added_count, list of added worker IDs)
    """
    roster = load_worker_skill_json()
    added_count = 0
    added_workers = []
    roster_updated = False

    for modality, df in modality_dfs.items():
        if df is None or df.empty:
            continue

        for _, row in df.iterrows():
            # Always derive canonical_id from PPL to ensure consistent IDs
            # The canonical_id is typically the abbreviation/code extracted from "Name (Code)"
            ppl_value = row.get('PPL', '')
            if pd.isna(ppl_value) or not str(ppl_value).strip():
                continue

            full_name = str(ppl_value).strip()
            # Use get_canonical_worker_id to extract consistent ID (e.g., "ABC" from "Name (ABC)")
            worker_id = get_canonical_worker_id(full_name)
            if not worker_id or worker_id in roster:
                # If worker exists, update full_name if not already set
                if worker_id in roster and 'full_name' not in roster[worker_id]:
                    roster[worker_id]['full_name'] = full_name
                    roster_updated = True
                continue

            entry = build_passive_worker_entry()
            entry['full_name'] = full_name
            roster[worker_id] = entry
            added_count += 1
            added_workers.append(worker_id)
            roster_updated = True
            selection_logger.info(
                "Auto-added worker %s (%s) to skill roster with all skills passive",
                worker_id,
                full_name,
            )

    if added_count > 0 or roster_updated:
        save_worker_skill_json(roster)

    return added_count, added_workers


def _match_csv_activity_rule(activity_desc: str, rules: List[dict]) -> Optional[dict]:
    """Return the first matching CSV activity rule, mirroring parser order."""
    if not activity_desc:
        return None

    activity_lower = activity_desc.lower()
    for rule in rules:
        match_str = str(rule.get('match', '')).strip()
        if match_str and match_str.lower() in activity_lower:
            return rule
    return None


def auto_populate_skill_roster_from_csv(csv_path: str, config: Dict[str, Any]) -> tuple:
    """
    Auto-populate skill roster with workers found in shift-managed CSV rows.

    New workers are added with all skills disabled (-1) by default. Gap rows,
    board-style activities, and unmatched CSV rows are ignored.
    Existing workers are preserved, but their full_name is filled if missing.

    Returns:
        Tuple of (added_count, list of added worker IDs)
    """
    vendor_mapping = config.get('medweb_mapping', {})
    rules = vendor_mapping.get('rules', [])
    cols = vendor_mapping.get('columns', {
        'employee_name': 'Name des Mitarbeiters',
        'employee_personalnummer': 'Personalnummer',
        'employee_code': 'Code des Mitarbeiters',
        'activity': 'Beschreibung der Aktivität',
    })
    name_col = cols.get('employee_name', 'Name des Mitarbeiters')
    personalnummer_col = cols.get('employee_personalnummer', 'Personalnummer')
    code_col = cols.get('employee_code', 'Code des Mitarbeiters')
    activity_col = cols.get('activity', 'Beschreibung der Aktivität')

    read_attempts = [
        {'sep': ',', 'encoding': 'utf-8'},
        {'sep': ',', 'encoding': 'latin1'},
        {'sep': ';', 'encoding': 'utf-8'},
        {'sep': ';', 'encoding': 'latin1'},
    ]

    csv_df: Optional[pd.DataFrame] = None
    last_error: Optional[Exception] = None
    for kwargs in read_attempts:
        try:
            csv_df = pd.read_csv(csv_path, **kwargs)
            break
        except Exception as exc:
            last_error = exc

    if csv_df is None:
        raise ValueError(f"Fehler beim Laden der CSV: {last_error}")

    if (
        name_col not in csv_df.columns
        or code_col not in csv_df.columns
        or activity_col not in csv_df.columns
    ):
        raise ValueError(
            "CSV missing worker columns: expected "
            f"'{name_col}', '{code_col}', and '{activity_col}'"
        )

    roster = load_worker_skill_json()
    added_count = 0
    added_workers: List[str] = []
    roster_updated = False

    for _, row in csv_df.iterrows():
        activity_desc = row.get(activity_col, '')
        activity_desc = '' if pd.isna(activity_desc) else str(activity_desc).strip()
        matched_rule = _match_csv_activity_rule(activity_desc, rules)
        if not matched_rule or matched_rule.get('type', 'shift') != 'shift':
            continue

        employee_name = row.get(name_col, '')
        employee_code = row.get(code_col, '')

        employee_personalnummer = row.get(personalnummer_col, '')
        if pd.isna(employee_name) and pd.isna(employee_personalnummer) and pd.isna(employee_code):
            continue

        employee_name = '' if pd.isna(employee_name) else str(employee_name).strip()
        employee_personalnummer = '' if pd.isna(employee_personalnummer) else str(employee_personalnummer).strip()
        employee_code = '' if pd.isna(employee_code) else str(employee_code).strip()

        if not employee_name and not employee_personalnummer and not employee_code:
            continue

        worker_code = employee_personalnummer or employee_code
        full_name = (
            f"{employee_name} ({worker_code})"
            if employee_name and worker_code else
            employee_name or worker_code
        )
        worker_id = get_canonical_worker_id(full_name)
        if not worker_id:
            continue

        if worker_id in roster:
            if 'full_name' not in roster[worker_id] and full_name:
                roster[worker_id]['full_name'] = full_name
                roster_updated = True
            continue

        entry = build_disabled_worker_entry()
        if full_name:
            entry['full_name'] = full_name
        roster[worker_id] = entry
        added_count += 1
        added_workers.append(worker_id)
        roster_updated = True
        selection_logger.info(
            "Auto-added worker %s (%s) to skill roster from CSV with all skills disabled",
            worker_id,
            full_name,
        )

    if added_count > 0 or roster_updated:
        save_worker_skill_json(roster)

    return added_count, added_workers


def get_merged_worker_roster(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge YAML config roster with JSON roster.

    JSON roster has field-level priority for the same worker, but missing JSON
    keys do not erase YAML-defined values. This keeps lightweight synthetic
    worker seeds or partial JSON edits from deleting config-defined exclusions.
    """
    # Start with YAML config
    yaml_roster = config.get('worker_roster', {})
    merged = copy.deepcopy(yaml_roster)

    # Ensure JSON is loaded
    if not worker_skill_json_roster:
        load_worker_skill_json()

    # JSON roster overrides YAML per field for each worker.
    for worker_id, worker_data in worker_skill_json_roster.items():
        existing = merged.get(worker_id)
        if isinstance(existing, dict) and isinstance(worker_data, dict):
            merged_entry = copy.deepcopy(existing)
            for key, value in worker_data.items():
                merged_entry[key] = copy.deepcopy(value)
            merged[worker_id] = merged_entry
        else:
            merged[worker_id] = copy.deepcopy(worker_data)

    return merged


def get_worker_skill_mod_combinations(
    canonical_id: str,
    worker_roster: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Get worker's Skill x Modality combinations from roster.

    Returns flat dict: {"skill_modality": value, ...}
    Normalizes keys to canonical "skill_modality" format.
    Missing workers default to -1 (excluded) until explicitly enabled in the roster.
    Missing combinations for known workers still default to 0 (passive).
    """
    if canonical_id not in worker_roster:
        # Worker not in roster -> all combinations = -1 (excluded)
        return _build_skill_mod_map(-1)

    worker_data = worker_roster[canonical_id]
    result = _build_skill_mod_map(0)

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
        - Full keys: "mdh_ct": 1 -> {"mdh_ct": 1}
        - all shortcut: "all": -1 -> all skill_modality combos = -1
        - Skill shortcut: "mdh": 1 -> mdh_ct, mdh_mr, mdh_xray, mdh_mammo = 1
        - Modality shortcut: "ct": 1 -> notfall_ct, mdh_ct, privat_ct, etc. = 1

    Args:
        rule_overrides: Raw skill_overrides dict from config

    Returns:
        Expanded dict with full skill_modality keys (canonical names)
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

        # Check if key is a skill shortcut (e.g., "mdh")
        canonical_skill = skill_columns_map.get(key_lower)
        if canonical_skill:
            for mod in allowed_modalities:
                expanded[f"{canonical_skill}_{mod}"] = value
            continue

        # Check if key is a modality shortcut (e.g., "ct" or "CT")
        canonical_mod = allowed_modalities_map.get(key_lower)
        if canonical_mod:
            for skill in SKILL_COLUMNS:
                expanded[f"{skill}_{canonical_mod}"] = value
            continue

        # Otherwise, it's a full skill_modality key - normalize it
        normalized_key = normalize_skill_mod_key(key)
        expanded[normalized_key] = value

    return expanded


def apply_skill_overrides(
    roster_combinations: dict,
    rule_overrides: dict,
    *,
    allow_roster_exclusion_override: bool = False,
    ignore_zero_overrides: bool = False,
    exclude_unprocessed_weighted: bool = True,
) -> dict:
    """
    Apply CSV rule skill_overrides to roster Skill x Modality combinations.

    First expands shortcuts (all, skill-only, mod-only), then applies.

    Priority rules:
    - Roster -1 (hard exclude) always wins and cannot be overridden unless
      allow_roster_exclusion_override=True and override value is 1 or w.
    - Roster 'w' (weighted/training):
      - Override 1 or w → 'w' (worker stays weighted)
      - Override 0 → -1 (not assigned to team, excluded) unless ignore_zero_overrides=True
      - Override -1 → -1 (explicit exclusion)
      - No override → -1 (not on any shift, excluded) unless exclude_unprocessed_weighted=False
    - Roster 1 or 0 → use override value (normal override)

    Args:
        roster_combinations: Worker's baseline skill x modality combinations
        rule_overrides: CSV rule overrides (e.g., {"mdh_ct": 1, "all": -1})
        allow_roster_exclusion_override: Allow overriding roster -1 with 1/w.
        ignore_zero_overrides: Skip overrides with value 0.
        exclude_unprocessed_weighted: Convert unprocessed roster 'w' values to -1.

    Returns:
        Final skill x modality combinations
    """
    final = roster_combinations.copy()

    # Expand shortcuts first
    expanded_overrides = expand_skill_overrides(rule_overrides)

    # Track which keys have been processed by an override
    processed_keys = set()

    for key, override_value in expanded_overrides.items():
        if key in final:
            processed_keys.add(key)
            roster_value = normalize_skill_value(final[key])
            override_value = normalize_skill_value(override_value)

            if ignore_zero_overrides and override_value == '0':
                continue

            # Roster -1 (hard exclude) always wins
            if roster_value == '-1':
                if allow_roster_exclusion_override and override_value in {'1', 'w'}:
                    final[key] = override_value
                continue  # Keep -1, ignore override

            # Roster 'w' (weighted/training) special handling
            if is_weighted_skill(roster_value):
                if override_value in {'1', 'w'}:
                    # CSV assigns as specialist/weighted → keep as weighted
                    final[key] = 'w'
                else:
                    # CSV assigns as 0 (helper) or -1 (exclude) → exclude
                    # Weighted workers are only included when explicitly assigned
                    final[key] = '-1'
                continue

            # Normal override for roster 1 or 0
            final[key] = override_value

    # Handle roster 'w' values that were NOT processed by any override
    # These workers are not on any shift for this skill → exclude them
    if exclude_unprocessed_weighted:
        for key, value in final.items():
            if key not in processed_keys and is_weighted_skill(value):
                final[key] = '-1'

    return final


def extract_modalities_from_skill_overrides(skill_overrides: dict) -> List[str]:
    """
    Extract unique modalities from skill_overrides keys.

    Handles all key formats:
    - "all" → all modalities
    - Skill shortcut (e.g., "mdh") → all modalities
    - Modality shortcut (e.g., "ct") → just that modality
    - Full key (e.g., "mdh_ct") → extract modality from key

    Returns list of unique canonical modalities found.
    """
    modalities = set()

    for key in skill_overrides.keys():
        key_lower = key.lower()

        # "all" shortcut → all modalities
        if key_lower == 'all':
            return list(allowed_modalities)

        # Skill-only shortcut (e.g., "mdh") → all modalities
        if skill_columns_map.get(key_lower):
            modalities.update(allowed_modalities)
            continue

        # Modality-only shortcut (e.g., "ct") → just that modality
        canonical_mod = allowed_modalities_map.get(key_lower)
        if canonical_mod:
            modalities.add(canonical_mod)
            continue

        # Full "skill_modality" key → extract modality
        normalized = normalize_skill_mod_key(key)
        if '_' in normalized:
            parts = normalized.split('_', 1)
            if len(parts) == 2:
                mod = parts[1]
                if mod in allowed_modalities:
                    modalities.add(mod)

    return list(modalities)
