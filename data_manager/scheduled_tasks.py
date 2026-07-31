"""
Scheduled tasks module for daily reset and preload operations.

This module handles:
- Daily reset at configured time (07:30 default)
- Next workday preload from master CSV
- Staged data clearing
"""
import os
import json
from datetime import datetime, time, date
from typing import Any, Dict, Optional, Union

from config import (
    APP_CONFIG,
    FLOW_SNAPSHOT_LOGGER,
    allowed_modalities,
    UPLOAD_FOLDER,
    selection_logger,
)
from lib.utils import (
    get_local_now,
    get_next_workday,
)
from state_manager import StateManager

# Get state references
_state = StateManager.get_instance()
lock = _state.lock
global_worker_data = _state.global_worker_data
modality_data = _state.modality_data
staged_modality_data = _state.staged_modality_data


def _parse_reset_time(reset_time_str: str) -> time:
    try:
        reset_hour, reset_min = map(int, reset_time_str.split(':'))
    except ValueError:
        return time(7, 30)
    return time(reset_hour, reset_min)


def _snapshot_flow_counters(day_closed: date) -> None:
    """Write a daily flow snapshot before counters are reset."""
    flow_cross_pool = global_worker_data.get('flow_cross_pool', {}) or {}
    total_cross_pool = 0.0
    normalized_flow: Dict[str, Dict[str, float]] = {}

    for requested_key, targets in flow_cross_pool.items():
        if not isinstance(targets, dict):
            continue
        normalized_targets: Dict[str, float] = {}
        for assigned_key, count in targets.items():
            try:
                normalized_count = float(count)
            except (TypeError, ValueError):
                continue
            if normalized_count <= 0:
                continue
            normalized_targets[str(assigned_key)] = round(normalized_count, 2)
            total_cross_pool += normalized_count
        if normalized_targets:
            normalized_flow[str(requested_key)] = normalized_targets

    snapshot_payload = {
        'event': 'daily_flow_snapshot',
        'window': 'since_daily_reset',
        'snapshot_date': day_closed.isoformat(),
        'created_at': get_local_now().isoformat(),
        'last_reset_date': (
            global_worker_data['last_reset_date'].isoformat()
            if global_worker_data.get('last_reset_date')
            else None
        ),
        'total_cross_pool': round(total_cross_pool, 2),
        'flow_cross_pool': normalized_flow,
    }
    FLOW_SNAPSHOT_LOGGER.info(json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True))


def check_and_perform_daily_reset() -> None:
    """
    Perform a single global daily reset at the configured reset time.

    Uses atomic check-and-set with locking to prevent race conditions when
    multiple threads/requests trigger this simultaneously at 07:30.

    This is ONE global reset (not per-modality) that:
    1. Resets global weighted counts
    2. Resets all modality counters
    3. Loads the dated staged snapshot for the day becoming live
    """
    # Import here to avoid circular imports
    from data_manager.worker_management import invalidate_work_hours_cache
    from data_manager.file_ops import (
        archive_live_day_snapshot,
        archive_staged_day_snapshot,
        backup_dataframe,
        initialize_data_from_unified,
    )
    from data_manager.state_persistence import save_state

    now = get_local_now()
    today = now.date()

    reset_time_str = APP_CONFIG.get('scheduler', {}).get('daily_reset_time', '07:30')
    reset_time = _parse_reset_time(reset_time_str)

    # Quick check without lock to avoid unnecessary locking on most requests
    if global_worker_data['last_reset_date'] == today:
        return
    if now.time() < reset_time:
        return

    # Atomic check-and-set with lock to prevent multiple threads from resetting
    with lock:
        # Double-check after acquiring lock (another thread may have just reset)
        if global_worker_data['last_reset_date'] == today:
            return

        selection_logger.info("Starting global daily reset for all modalities")

        # Invalidate all work hours caches at start of reset
        invalidate_work_hours_cache()

        day_closed = global_worker_data.get('last_reset_date') or today
        _snapshot_flow_counters(day_closed)
        archive_live_day_snapshot(day_closed, suffix='eod')

        # Mark reset date FIRST (atomic check-and-set pattern)
        # This prevents other threads from entering even if we fail midway
        global_worker_data['last_reset_date'] = today

        # Reset global weighted counts
        global_worker_data['weighted_counts'] = {}
        global_worker_data['flow_cross_pool'] = {}
        global_worker_data['distribution_stats'] = {}
        global_worker_data['recent_distributions'] = []
        global_worker_data['daily_load_events'] = []
        global_worker_data['manual_weight_totals'] = {}
        global_worker_data['manual_weight_adjustments'] = []

        # Reset per-modality tracking
        for mod, d in modality_data.items():
            d['last_reset_date'] = today
            global_worker_data['assignments_per_mod'][mod] = {}

        try:
            staged_day_path = os.path.join(
                UPLOAD_FOLDER,
                "backups",
                "staged_days",
                f"Cortex_ALL_staged_{today.isoformat()}.json",
            )

            loaded_today = False
            if os.path.exists(staged_day_path):
                archive_staged_day_snapshot(today, suffix='bod')
                loaded_today = initialize_data_from_unified(
                    staged_day_path,
                    context="daily reset staged snapshot",
                )

            if loaded_today:
                backup_dataframe(allowed_modalities[0])
            else:
                selection_logger.error(
                    "Daily reset aborted live schedule activation for %s because the staged snapshot was missing or could not be loaded",
                    today.isoformat(),
                )
        except Exception as exc:
            selection_logger.error("Error during daily reset for unified schedule: %s", exc)

        selection_logger.info("Global daily reset completed.")

    # Save state OUTSIDE the lock to prevent blocking I/O
    save_state()


def _parse_target_date(value: Optional[Union[str, date, datetime]]) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def preload_next_workday(csv_path: str, config: dict, target_date: Optional[Union[str, date, datetime]] = None) -> Dict[str, Any]:
    """Load data from master CSV for the target date and save to scheduled files."""
    # Import here to avoid circular imports
    from data_manager.csv_parser import build_working_hours_from_medweb
    from data_manager.file_ops import (
        backup_dataframe,
        load_unified_scheduled_into_staged,
        write_unified_scheduled_file,
    )

    try:
        resolved_date = _parse_target_date(target_date) or get_next_workday().date()
        target_dt = datetime.combine(resolved_date, datetime.min.time())
        date_str = resolved_date.strftime('%Y-%m-%d')

        modality_dfs = build_working_hours_from_medweb(
            csv_path,
            target_dt,
            config
        )

        # Clear unified scheduled file first to prevent stale data
        unified_scheduled_path = _state.unified_schedule_paths['scheduled']
        if os.path.exists(unified_scheduled_path):
            try:
                os.remove(unified_scheduled_path)
                selection_logger.info("Cleared existing unified scheduled file")
            except OSError as e:
                selection_logger.warning("Could not remove existing unified scheduled file: %s", e)

        if not modality_dfs:
            modality_dfs = {}

        saved_modalities = []
        total_workers = 0
        save_error: Optional[str] = None

        try:
            for modality, df in modality_dfs.items():
                if df is None or df.empty:
                    selection_logger.info(f"No rows to preload for {modality} on {date_str}")
                    continue
                saved_modalities.append(modality)
                total_workers += len(df['PPL'].unique())

            write_unified_scheduled_file(modality_dfs, target_date=resolved_date)

            staged_day_path = os.path.join(
                UPLOAD_FOLDER,
                "backups",
                "staged_days",
                f"Cortex_ALL_staged_{date_str}.json",
            )
            if not load_unified_scheduled_into_staged(unified_scheduled_path):
                raise RuntimeError("Unified scheduled file could not be materialized into staged state")
            for modality in allowed_modalities:
                backup_dataframe(modality, use_staged=True)
            if not os.path.exists(staged_day_path):
                raise RuntimeError(f"Staged day snapshot was not written: {staged_day_path}")
        except Exception as exc:
            selection_logger.error("Failed to save unified scheduled file: %s", exc)
            save_error = str(exc)

        if save_error is not None:
            return {
                'success': False,
                'target_date': date_str,
                'message': f'Fehler beim Speichern des Preload: {save_error}'
            }

        if not saved_modalities:
            selection_logger.info(f"No staff entries found for {date_str} - this is expected for some shifts")

        with lock:
            global_worker_data['last_preload_date'] = resolved_date
        from data_manager.state_persistence import save_state
        save_state()

        return {
            'success': True,
            'target_date': date_str,
            'modalities_loaded': saved_modalities,
            'total_workers': total_workers,
            'message': (
                f'Keine Mitarbeiter für {date_str} gefunden - Schichten können leer sein'
                if not saved_modalities
                else f'Preload erfolgreich gespeichert (wird am {date_str} aktiviert)'
            )
        }

    except Exception as exc:
        selection_logger.error(f"Error in preload_next_workday: {exc}", exc_info=True)
        return {
            'success': False,
            'target_date': (_parse_target_date(target_date) or get_next_workday().date()).strftime('%Y-%m-%d'),
            'message': f'Fehler beim Preload: {exc}'
        }
