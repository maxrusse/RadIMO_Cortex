"""Shared schedule state for the data-manager package.

Runtime functions live in their owning modules.  The package root exposes only
the initialized shared state used across those modules.
"""

from config import SKILL_COLUMNS, UPLOAD_FOLDER, allowed_modalities
from state_manager import StateManager


_state = StateManager.get_instance()
_state.initialize(allowed_modalities, SKILL_COLUMNS, UPLOAD_FOLDER)

lock = _state.lock
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data
staged_modality_data = _state.staged_modality_data
worker_skill_json_roster = _state.worker_skill_json_roster


__all__ = [
    'lock',
    'global_worker_data',
    'modality_data',
    'staged_modality_data',
    'worker_skill_json_roster',
]
