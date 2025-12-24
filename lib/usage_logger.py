"""
Usage logging for skill-modality combination tracking.

Tracks daily usage statistics for each skill-modality combination to monitor
tool usage patterns and compare against actual work entries from other data sources.
"""

import csv
import logging
import os
from datetime import datetime, date, time
from pathlib import Path
from typing import Dict, Tuple, List, Set
from collections import defaultdict
import threading

from config import SKILL_COLUMNS, allowed_modalities

logger = logging.getLogger(__name__)

# Directory for usage statistics CSV files
USAGE_STATS_DIR = Path("logs/usage_stats")
USAGE_STATS_DIR.mkdir(parents=True, exist_ok=True)

# Single CSV file for all usage statistics (wide format)
USAGE_STATS_FILE = USAGE_STATS_DIR / "usage_stats.csv"

# Daily usage tracking: {(skill, modality): count}
_daily_usage: Dict[Tuple[str, str], int] = defaultdict(int)
_current_date: date = date.today()
_lock = threading.Lock()


def record_skill_modality_usage(skill: str, modality: str) -> None:
    """
    Record a single usage of a skill-modality combination.

    Args:
        skill: The skill name (e.g., 'Notfall', 'Privat', 'MSK')
        modality: The modality name (e.g., 'ct', 'mr', 'xray', 'mammo')
    """
    global _current_date

    with _lock:
        today = date.today()

        # Check if we need to export and reset for a new day
        if today != _current_date:
            logger.info(f"Date changed from {_current_date} to {today}, exporting previous day's data")
            _export_and_reset(export_date=_current_date)
            _current_date = today

        # Record the usage
        key = (skill, modality)
        _daily_usage[key] += 1

        logger.debug(f"Recorded usage: skill={skill}, modality={modality}, daily_count={_daily_usage[key]}")


def _get_all_skill_modality_columns() -> List[str]:
    """
    Get all possible skill-modality column names in a consistent order.

    Returns:
        List of column names in format 'skill_modality' (e.g., 'Notfall_ct')
    """
    columns = []
    for skill in SKILL_COLUMNS:
        for modality in allowed_modalities:
            columns.append(f"{skill}_{modality}")

    return columns


def _export_and_reset(export_date: date = None) -> None:
    """
    Export current usage data to CSV in wide format (one row per day) and reset counters.

    Args:
        export_date: Date to use for the export (defaults to current_date)
    """
    global _daily_usage

    if export_date is None:
        export_date = _current_date

    if not _daily_usage:
        logger.info(f"No usage data to export for {export_date}")
        return

    try:
        # Get all possible skill-modality columns
        all_columns = _get_all_skill_modality_columns()

        # Check if file exists to determine if we need headers
        file_exists = USAGE_STATS_FILE.exists()

        # Prepare row data
        row_data = {'date': export_date.strftime('%Y-%m-%d')}

        # Add all skill-modality counts (0 if not used)
        # Iterate over skills and modalities directly to avoid parsing issues
        # with skill names that contain underscores
        for skill in SKILL_COLUMNS:
            for modality in allowed_modalities:
                column = f"{skill}_{modality}"
                row_data[column] = _daily_usage.get((skill, modality), 0)

        # Write to CSV
        with open(USAGE_STATS_FILE, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['date'] + all_columns
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            # Write header if new file
            if not file_exists:
                writer.writeheader()

            # Write data row
            writer.writerow(row_data)

        total_usage = sum(_daily_usage.values())
        logger.info(f"Exported usage data for {export_date} to {USAGE_STATS_FILE} ({total_usage} total assignments)")

        # Reset counters
        _daily_usage.clear()
        logger.info("Usage counters reset for new day")

    except Exception as e:
        logger.error(f"Failed to export usage statistics: {e}", exc_info=True)


def export_current_usage() -> Path:
    """
    Manually trigger export of current usage data without resetting.
    Useful for end-of-day exports or manual backups.

    Note: In wide format, this appends the current day's data to the CSV file.
    If data for the current date already exists in the file, this will add a duplicate row.

    Returns:
        Path to the exported CSV file, or None if no data to export
    """
    with _lock:
        if not _daily_usage:
            logger.info("No usage data to export")
            return None

        try:
            # Get all possible skill-modality columns
            all_columns = _get_all_skill_modality_columns()

            # Check if file exists to determine if we need headers
            file_exists = USAGE_STATS_FILE.exists()

            # Prepare row data
            row_data = {'date': _current_date.strftime('%Y-%m-%d')}

            # Add all skill-modality counts (0 if not used)
            # Iterate over skills and modalities directly to avoid parsing issues
            # with skill names that contain underscores
            for skill in SKILL_COLUMNS:
                for modality in allowed_modalities:
                    column = f"{skill}_{modality}"
                    row_data[column] = _daily_usage.get((skill, modality), 0)

            # Write to CSV
            with open(USAGE_STATS_FILE, 'a', newline='', encoding='utf-8') as f:
                fieldnames = ['date'] + all_columns
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                # Write header if new file
                if not file_exists:
                    writer.writeheader()

                # Write data row
                writer.writerow(row_data)

            total_usage = sum(_daily_usage.values())
            logger.info(f"Exported usage data for {_current_date} to {USAGE_STATS_FILE} ({total_usage} total assignments)")
            return USAGE_STATS_FILE

        except Exception as e:
            logger.error(f"Failed to export usage statistics: {e}", exc_info=True)
            return None


def reset_daily_usage() -> None:
    """
    Reset daily usage counters without exporting.
    Use with caution - typically you want export_and_reset() instead.
    """
    global _daily_usage

    with _lock:
        count = len(_daily_usage)
        _daily_usage.clear()
        logger.info(f"Reset {count} usage counter(s)")


def get_current_usage_stats() -> Dict[Tuple[str, str], int]:
    """
    Get current usage statistics without modifying them.

    Returns:
        Dictionary of {(skill, modality): count}
    """
    with _lock:
        return dict(_daily_usage)


def check_and_export_at_scheduled_time() -> bool:
    """
    Check if it's time for the scheduled export (7:30 AM) and export if needed.
    Should be called periodically (e.g., with each assignment request).

    Returns:
        True if export was triggered, False otherwise
    """
    global _current_date

    now = datetime.now()
    current_time = now.time()
    today = now.date()

    # Check if we've crossed 7:30 AM
    scheduled_time = time(7, 30)

    with _lock:
        # If it's a new day and we're past 7:30 AM, or if it's past 7:30 and we haven't exported yet
        if today > _current_date:
            # New day detected, export previous day's data
            logger.info(f"New day detected, exporting data from {_current_date}")
            _export_and_reset(export_date=_current_date)
            _current_date = today
            return True
        elif today == _current_date and current_time >= scheduled_time:
            # Same day, check if we need a scheduled export
            # This is primarily for consistency, main export happens at date change
            pass

    return False


def get_usage_csv_path() -> Path:
    """
    Get the path to the usage stats CSV file.

    Note: In wide format, there is a single CSV file containing all dates.

    Returns:
        Path object for the CSV file
    """
    return USAGE_STATS_FILE
