"""
State persistence module for saving/loading application state to JSON.

This module handles serialization and deserialization of worker data,
modality data, and assignment tracking to/from the STATE_FILE_PATH.
"""
import json
from datetime import datetime

from config import (
    allowed_modalities,
    STATE_FILE_PATH,
    selection_logger,
)
from state_manager import StateManager

# Get state references
_state = StateManager.get_instance()
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data


def save_state():
    """Save current application state to disk."""
    try:
        state = {
            'global_worker_data': {
                'worker_ids': global_worker_data['worker_ids'],
                'weighted_counts': global_worker_data['weighted_counts'],
                'assignments_per_mod': global_worker_data['assignments_per_mod'],
                'flow_cross_pool': global_worker_data.get('flow_cross_pool', {}),
                'distribution_stats': global_worker_data.get('distribution_stats', {}),
                'recent_distributions': global_worker_data.get('recent_distributions', []),
                'daily_load_events': global_worker_data.get('daily_load_events', []),
                'manual_weight_totals': global_worker_data.get('manual_weight_totals', {}),
                'manual_weight_adjustments': global_worker_data.get('manual_weight_adjustments', []),
                'last_reset_date': global_worker_data['last_reset_date'].isoformat() if global_worker_data['last_reset_date'] else None,
                'last_preload_date': global_worker_data['last_preload_date'].isoformat() if global_worker_data['last_preload_date'] else None,
                'last_preload_source': global_worker_data.get('last_preload_source'),
            },
            'modality_data': {}
        }

        for mod in allowed_modalities:
            d = modality_data[mod]
            state['modality_data'][mod] = {
                'last_reset_date': d['last_reset_date'].isoformat() if d['last_reset_date'] else None
            }

        with open(STATE_FILE_PATH, 'w') as f:
            json.dump(state, f, indent=2)

        selection_logger.debug("State saved successfully")
    except Exception as e:
        selection_logger.error(f"Failed to save state: {str(e)}", exc_info=True)


def load_state():
    """Load application state from disk."""
    # Use try/except instead of os.path.exists to prevent TOCTOU race condition
    # (file could be deleted between check and open)
    try:
        with open(STATE_FILE_PATH, 'r') as f:
            state = json.load(f)
    except FileNotFoundError:
        selection_logger.info("No saved state found, starting fresh")
        return
    except json.JSONDecodeError as e:
        selection_logger.error(f"Failed to parse state file: {e}")
        return

    try:
        if 'global_worker_data' in state:
            gwd = state['global_worker_data']
            global_worker_data['worker_ids'] = gwd.get('worker_ids', {})
            global_worker_data['weighted_counts'] = gwd.get('weighted_counts', {})
            global_worker_data['assignments_per_mod'] = gwd.get('assignments_per_mod', {mod: {} for mod in allowed_modalities})
            global_worker_data['flow_cross_pool'] = gwd.get('flow_cross_pool', {})
            global_worker_data['distribution_stats'] = gwd.get('distribution_stats', {})
            global_worker_data['recent_distributions'] = gwd.get('recent_distributions', [])
            global_worker_data['daily_load_events'] = gwd.get('daily_load_events', [])
            global_worker_data['manual_weight_totals'] = gwd.get('manual_weight_totals', {})
            global_worker_data['manual_weight_adjustments'] = gwd.get('manual_weight_adjustments', [])

            last_reset_str = gwd.get('last_reset_date')
            if last_reset_str:
                global_worker_data['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()
            last_preload_str = gwd.get('last_preload_date')
            if last_preload_str:
                global_worker_data['last_preload_date'] = datetime.fromisoformat(last_preload_str).date()
            global_worker_data['last_preload_source'] = gwd.get('last_preload_source')

        if 'modality_data' in state:
            for mod in allowed_modalities:
                if mod in state['modality_data']:
                    mod_state = state['modality_data'][mod]
                    last_reset_str = mod_state.get('last_reset_date')
                    if last_reset_str:
                        modality_data[mod]['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()

        selection_logger.info("State loaded successfully from disk")
    except Exception as e:
        selection_logger.error(f"Failed to load state: {str(e)}", exc_info=True)
