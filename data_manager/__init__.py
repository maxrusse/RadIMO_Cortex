"""
Data Manager Package

This package provides data management functionality for the RadIMO Cortex application.
It handles worker schedules, skill rosters, CSV parsing, and state persistence.

The package is organized into the following modules:
- state_persistence: Save/load application state to JSON
- worker_management: Worker IDs, skill rosters, skill-modality combinations
- file_ops: File backup, loading, quarantine operations
- schedule_crud: CRUD operations for schedules (update, add, delete, gap segments)
- csv_parser: Medweb CSV parsing and transformation
- scheduled_tasks: Daily reset, preload, staged data management

All public functions are re-exported here for backwards compatibility.
Existing code using `from data_manager import X` will continue to work.
"""

from config import (
    allowed_modalities,
    SKILL_COLUMNS,
    UPLOAD_FOLDER,
)
from state_manager import StateManager

# Re-export allowed_modalities for backwards compatibility
# (app.py imports it from data_manager)

# -----------------------------------------------------------
# Global State & Locks (via StateManager Singleton)
# -----------------------------------------------------------

# Initialize the StateManager singleton
_state = StateManager.get_instance()
_state.initialize(allowed_modalities, SKILL_COLUMNS, UPLOAD_FOLDER)

# Lock for atomic operations (delegates to StateManager)
lock = _state.lock

# Backward-compatible module-level aliases
# These reference the StateManager's internal dictionaries directly
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data
staged_modality_data = _state.staged_modality_data
worker_skill_json_roster = _state.worker_skill_json_roster

# -----------------------------------------------------------
# Re-exports from submodules for backwards compatibility
# -----------------------------------------------------------

# State persistence
from data_manager.state_persistence import (
    save_state,
    load_state,
)

# Worker management
from data_manager.worker_management import (
    get_canonical_worker_id,
    invalidate_work_hours_cache,
    get_all_workers_by_canonical_id,
    build_worker_name_mapping,
    load_worker_skill_json,
    save_worker_skill_json,
    build_valid_skills_map,
    normalize_skill_mod_key,
    build_disabled_worker_entry,
    get_roster_modifier,
    get_roster_modifier_raw,
    auto_populate_skill_roster,
    auto_populate_skill_roster_from_csv,
    get_merged_worker_roster,
    get_worker_skill_mod_combinations,
    expand_skill_overrides,
    apply_skill_overrides,
    extract_modalities_from_skill_overrides,
)

# File operations
from data_manager.file_ops import (
    apply_roster_overrides_to_schedule,
    backup_dataframe,
    persist_live_backup,
    load_staged_dataframe,
    load_unified_live_backup,
    initialize_data_from_unified,
    load_unified_scheduled_into_staged,
    quarantine_file,
    initialize_data,
    attempt_initialize_data,
)

# Schedule CRUD operations
from data_manager.schedule_crud import (
    reconcile_live_worker_tracking,
    resolve_overlapping_shifts,
    update_schedule_row,
    add_worker_to_schedule,
    delete_worker_from_schedule,
    add_gap_to_schedule,
    replace_worker_schedule,
    remove_gap_from_schedule,
    update_gap_in_schedule,
)

# CSV parser
from data_manager.csv_parser import (
    match_mapping_rule,
    compute_time_ranges,
    parse_gap_times,
    build_ppl_from_row,
    build_working_hours_from_medweb,
)

# Scheduled tasks
from data_manager.scheduled_tasks import (
    check_and_perform_daily_reset,
    preload_next_workday,
)

# -----------------------------------------------------------
# Public API - all exports for backwards compatibility
# -----------------------------------------------------------
__all__ = [
    # Config re-exports
    'allowed_modalities',

    # State
    'lock',
    'global_worker_data',
    'modality_data',
    'staged_modality_data',
    'worker_skill_json_roster',

    # State persistence
    'save_state',
    'load_state',

    # Worker management
    'get_canonical_worker_id',
    'invalidate_work_hours_cache',
    'get_all_workers_by_canonical_id',
    'build_worker_name_mapping',
    'load_worker_skill_json',
    'save_worker_skill_json',
    'build_valid_skills_map',
    'normalize_skill_mod_key',
    'build_disabled_worker_entry',
    'get_roster_modifier',
    'get_roster_modifier_raw',
    'auto_populate_skill_roster',
    'auto_populate_skill_roster_from_csv',
    'get_merged_worker_roster',
    'get_worker_skill_mod_combinations',
    'expand_skill_overrides',
    'apply_skill_overrides',
    'extract_modalities_from_skill_overrides',

    # File operations
    'apply_roster_overrides_to_schedule',
    'backup_dataframe',
    'persist_live_backup',
    'load_staged_dataframe',
    'load_unified_live_backup',
    'initialize_data_from_unified',
    'load_unified_scheduled_into_staged',
    'quarantine_file',
    'initialize_data',
    'attempt_initialize_data',

    # Schedule CRUD
    'reconcile_live_worker_tracking',
    'resolve_overlapping_shifts',
    'update_schedule_row',
    'add_worker_to_schedule',
    'delete_worker_from_schedule',
    'add_gap_to_schedule',
    'replace_worker_schedule',
    'remove_gap_from_schedule',
    'update_gap_in_schedule',

    # CSV parser
    'match_mapping_rule',
    'compute_time_ranges',
    'parse_gap_times',
    'build_ppl_from_row',
    'build_working_hours_from_medweb',

    # Scheduled tasks
    'check_and_perform_daily_reset',
    'preload_next_workday',
]
