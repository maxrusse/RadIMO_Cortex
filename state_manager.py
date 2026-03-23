# state_manager.py
"""
Centralized state management for RadIMO Cortex.

This module provides a thread-safe Singleton class to manage all global mutable state,
replacing the previous scattered global variables (global_worker_data, modality_data,
staged_modality_data).

Benefits:
- Single source of truth for application state
- Thread-safe access via internal locking
- Easier testing through reset() method
- Supports TTL caching for expensive calculations
"""

import os
import time as time_module
from threading import Lock, RLock
from typing import Dict, Any, Optional


class TTLCache:
    """Simple TTL cache for expensive calculations."""

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # key -> (value, timestamp)
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time_module.time() - timestamp < self.ttl:
                    return value
                # Expired, remove it
                del self._cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        """Set cached value with current timestamp."""
        with self._lock:
            self._cache[key] = (value, time_module.time())

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate specific key or all keys if key is None."""
        with self._lock:
            if key is None:
                self._cache.clear()
            elif key in self._cache:
                del self._cache[key]

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all keys starting with prefix."""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]


class StateManager:
    """
    Singleton class managing all application state.

    Thread-safe access to:
    - global_worker_data: Cross-modality worker tracking
    - modality_data: Live modality schedules and counters
    - staged_modality_data: Next-day prep data
    - worker_skill_json_roster: JSON skill roster cache

    Usage:
        state = StateManager.get_instance()
        state.global_worker_data['weighted_counts']['worker1'] = 1.5
    """

    _instance: Optional['StateManager'] = None
    _instance_lock = Lock()

    def __init__(self):
        """Initialize state structures. Use get_instance() instead of direct init."""
        # Main lock for state modifications
        self._lock = RLock()

        # TTL cache for work hours calculation (1 minute default)
        self.work_hours_cache = TTLCache(ttl_seconds=60.0)

        # Initialize empty state - will be populated by initialize()
        self._global_worker_data: Dict[str, Any] = {}
        self._modality_data: Dict[str, Dict[str, Any]] = {}
        self._staged_modality_data: Dict[str, Dict[str, Any]] = {}
        self._worker_skill_json_roster: Dict[str, Any] = {}

        self._initialized = False

    @classmethod
    def get_instance(cls) -> 'StateManager':
        """Get the singleton instance, creating it if necessary."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check after acquiring lock
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def initialize(self, allowed_modalities: list, skill_columns: list, upload_folder: str) -> None:
        """
        Initialize state structures with configuration.

        Args:
            allowed_modalities: List of valid modality codes (e.g., ['ct', 'mr'])
            skill_columns: List of skill column names
            upload_folder: Base path for file storage
        """
        with self._lock:
            if self._initialized:
                return

            # Global worker data structure
            self._global_worker_data = {
                'worker_ids': {},  # Map of worker name variations to canonical ID
                'weighted_counts': {},  # {worker_id: count}
                'assignments_per_mod': {mod: {} for mod in allowed_modalities},
                'flow_cross_pool': {},  # {requested_skill: {absorbing_main_skill: weighted_amount}}
                'last_reset_date': None,  # Global reset date tracker
                'last_preload_date': None  # Next-workday preload tracker
            }

            # Modality active data (Live)
            self._modality_data = {}
            for mod in allowed_modalities:
                self._modality_data[mod] = {
                    'working_hours_df': None,
                    'info_texts': [],
                    'info_texts_by_skill': {},
                    'total_work_hours': {},
                    'worker_modifiers': {},
                    'skill_counts': {skill: {} for skill in skill_columns},
                    'last_reset_date': None
                }

            self._unified_schedule_paths = {
                'scheduled': os.path.join(upload_folder, "Cortex_ALL_scheduled.json"),
                'staged': os.path.join(upload_folder, "backups", "Cortex_ALL_staged.json"),
                'live': os.path.join(upload_folder, "backups", "Cortex_ALL_live.json"),
                'scheduled_backup': os.path.join(upload_folder, "backups", "Cortex_ALL_scheduled.json"),
            }

            # Staged data (Next Day Prep)
            self._staged_modality_data = {}
            for mod in allowed_modalities:
                self._staged_modality_data[mod] = {
                    'working_hours_df': None,
                    'info_texts': [],
                    'info_texts_by_skill': {},
                    'total_work_hours': {},
                    'worker_modifiers': {},
                    'last_modified': None,
                    'last_prepped_at': None,
                    'last_prepped_by': None,
                    'target_date': None
                }

            self._worker_skill_json_roster = {}
            self._initialized = True

    @property
    def lock(self) -> RLock:
        """Access the state lock for atomic operations."""
        return self._lock

    @property
    def global_worker_data(self) -> Dict[str, Any]:
        """Access global worker data dictionary."""
        return self._global_worker_data

    @property
    def modality_data(self) -> Dict[str, Dict[str, Any]]:
        """Access modality data dictionary."""
        return self._modality_data

    @property
    def staged_modality_data(self) -> Dict[str, Dict[str, Any]]:
        """Access staged modality data dictionary."""
        return self._staged_modality_data

    @property
    def worker_skill_json_roster(self) -> Dict[str, Any]:
        """Access worker skill JSON roster."""
        return self._worker_skill_json_roster

    @property
    def unified_schedule_paths(self) -> Dict[str, str]:
        """Access unified schedule file paths."""
        return self._unified_schedule_paths

    # NOTE: get_canonical_worker_id is intentionally NOT implemented here.
    # Use data_manager.worker_management.get_canonical_worker_id() instead
    # to maintain a single source of truth.

    def invalidate_work_hours_cache(self, modality: Optional[str] = None) -> None:
        """Invalidate work hours cache for a modality or all modalities."""
        if modality:
            self.work_hours_cache.invalidate_prefix(f"work_hours:{modality}:")
        else:
            self.work_hours_cache.invalidate()

# Module-level convenience function to get the singleton instance
def get_state() -> StateManager:
    """Get the StateManager singleton instance."""
    return StateManager.get_instance()
