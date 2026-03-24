# Standard library imports
import logging
import re
from datetime import datetime, time, timedelta, date
from typing import Any, List, Optional, Tuple, Union
import pytz
import pandas as pd

# -----------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------
# We'll expose the logger so other modules can use it
selection_logger = logging.getLogger('selection')

# -----------------------------------------------------------
# Type Coercion Helpers
# -----------------------------------------------------------
def coerce_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

# -----------------------------------------------------------
# TIME / DATE HELPERS
# -----------------------------------------------------------
TIME_FORMAT = '%H:%M'

# Import timezone from config (circular import safe - uses lazy import)
def _get_configured_timezone() -> str:
    """Lazy-load timezone to avoid circular import."""
    try:
        from config import TIMEZONE
        return TIMEZONE
    except ImportError:
        return "Europe/Berlin"

def get_local_now() -> datetime:
    """Get current local time in configured timezone (defaults to Europe/Berlin)."""
    tz = pytz.timezone(_get_configured_timezone())
    return datetime.now(tz).replace(tzinfo=None)


def parse_time_range(time_range: str) -> Tuple[time, time]:
    """
    Parse a time range string into start and end time objects.
    Example: "08:00-16:00" -> (time(8,0), time(16,0))
    """
    start_str, end_str = time_range.split('-')
    start_time = datetime.strptime(start_str.strip(), TIME_FORMAT).time()
    end_time = datetime.strptime(end_str.strip(), TIME_FORMAT).time()
    return start_time, end_time


def format_time_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime(TIME_FORMAT)
    return str(value)


_WORKER_SORT_TITLES = {
    'dr', 'dr.', 'pd', 'pd.', 'prof', 'prof.', 'med', 'dent',
    'dipl', 'dipl.', 'ing', 'ing.', 'dipl-ing', 'dipl.-ing',
}
_WORKER_SORT_PARTICLES = {
    'von', 'van', 'de', 'del', 'der', 'den', 'zu', 'zum', 'zur',
}


def build_worker_sort_key(name: Any) -> str:
    """Build a surname-like sort key from the visible worker label."""
    raw = '' if name is None else str(name).strip()
    if not raw:
        return ''

    # Remove trailing canonical code like "Name (ABC)".
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', raw).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if not cleaned:
        return raw.casefold()

    tokens = []
    for token in cleaned.split(' '):
        normalized = token.strip().strip('.,;:()[]{}').casefold()
        if not normalized:
            continue
        if normalized in _WORKER_SORT_TITLES:
            continue
        if normalized in _WORKER_SORT_PARTICLES:
            continue
        tokens.append(token.strip().strip('.,;:()[]{}'))

    if not tokens:
        fallback = cleaned.casefold()
        return f"{fallback}|{fallback}"

    last = tokens[-1].casefold()
    first = ' '.join(tokens[:-1]).casefold()
    full = ' '.join(tokens).casefold()
    return f"{last}|{first}|{full}"


def strip_builder_fields(row: dict) -> dict:
    cleaned = dict(row)
    for key in ('shift_duration', 'TIME', 'row_index', 'is_manual'):
        cleaned.pop(key, None)
    return cleaned


def gap_row_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or 'row_type' not in df.columns:
        return pd.Series(False, index=df.index if df is not None else pd.Index([]))
    return df['row_type'].fillna('shift_segment').astype(str).str.lower().isin({'gap', 'gap_segment'})

def compute_shift_window(
    start_time: time, end_time: time, reference_dt: datetime
) -> Tuple[datetime, datetime]:
    """Return start/end datetimes for a shift on the same day as reference_dt."""
    reference_date = reference_dt.date()
    start_dt = datetime.combine(reference_date, start_time)
    end_dt = datetime.combine(reference_date, end_time)
    return start_dt, end_dt

def is_now_in_shift(start_time: time, end_time: time, current_dt: datetime) -> bool:
    """Check whether ``current_dt`` falls inside the given shift window."""
    start_dt, end_dt = compute_shift_window(start_time, end_time, current_dt)
    return start_dt <= current_dt <= end_dt

def calculate_shift_duration_hours(start_time: time, end_time: time) -> float:
    """Calculate shift duration in hours (same-day shifts only, end must be after start)."""
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    # Same-day only: if end <= start, treat as invalid (0 hours)
    if end_minutes <= start_minutes:
        return 0.0
    return (end_minutes - start_minutes) / 60.0

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

def get_next_workday(from_date: Optional[Union[datetime, date]] = None) -> datetime:
    """
    Calculate next calendar day (no weekend skip).
    """
    if from_date is None:
        current_date = get_local_now().date()
    else:
        current_date = from_date.date() if hasattr(from_date, 'date') else from_date

    next_day = current_date + timedelta(days=1)
    return datetime.combine(next_day, time(0, 0))

# -----------------------------------------------------------
# Data Validation
# -----------------------------------------------------------
def validate_excel_structure(df: pd.DataFrame, required_columns: List[str], skill_columns: List[str]) -> Tuple[bool, str]:
    """Validate DataFrame structure for worker schedule data."""
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

    # Note: Skill columns can contain numeric values (-1, 0, 1) or 'w' for weighted.
    # The normalize_skill_value function handles all normalization, so we don't
    # enforce strict numeric type here. This allows 'w' values in skill columns.

    return True, ""

# -----------------------------------------------------------
# Normalization Helpers
# -----------------------------------------------------------
WEIGHTED_SKILL_MARKER = 'w'
SKILL_VALUE_EXCLUDED = '-1'
SKILL_VALUE_PASSIVE = '0'
SKILL_VALUE_ACTIVE = '1'


def normalize_skill_value(value: Any) -> str:
    """Normalize skill values. Accepts: -1, 0, 1, 'w'."""
    if value is None:
        return SKILL_VALUE_PASSIVE

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() == WEIGHTED_SKILL_MARKER:
            return WEIGHTED_SKILL_MARKER
        if cleaned == '':
            return SKILL_VALUE_PASSIVE
        parsed = _parse_skill_int(cleaned)
    else:
        parsed = _parse_skill_int(value)

    if parsed is None:
        return SKILL_VALUE_PASSIVE

    if parsed <= -1:
        return SKILL_VALUE_EXCLUDED
    if parsed == 0:
        return SKILL_VALUE_PASSIVE
    return SKILL_VALUE_ACTIVE


def _parse_skill_int(value: Any) -> Optional[int]:
    """Parse a skill value into an integer, returning None on failure."""
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def skill_value_to_display(value: Any) -> str:
    """Convert skill values into API-safe display values."""
    return normalize_skill_value(value)

def skill_value_to_numeric(value: Any) -> int:
    """Convert skill values to numeric form for comparisons (``'w'`` -> 1)."""
    if isinstance(value, str) and value.strip().lower() == WEIGHTED_SKILL_MARKER:
        return 1
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0

def is_weighted_skill(value: Any) -> bool:
    """Check whether a skill value represents a weighted/assisted assignment."""
    return isinstance(value, str) and value.strip().lower() == WEIGHTED_SKILL_MARKER


# -----------------------------------------------------------
# Interval Subtraction for Gap Calculations
# -----------------------------------------------------------
def subtract_intervals(base: Tuple[Any, Any], gaps: List[Tuple[Any, Any]]) -> List[Tuple[Any, Any]]:
    """
    Subtract gap intervals from a base interval.

    Used for calculating effective shift duration after gap overlaps.
    Works with any comparable types (integers for minutes, datetime objects, etc.)

    Args:
        base: A tuple (start, end) representing the shift
        gaps: A list of (start, end) tuples representing gaps

    Returns:
        A list of remaining intervals after subtracting gaps
    """
    remaining = [base]
    for gap_start, gap_end in gaps:
        next_remaining = []
        for start, end in remaining:
            if gap_end <= start or gap_start >= end:
                # No overlap
                next_remaining.append((start, end))
                continue
            if gap_start > start:
                # Keep portion before gap
                next_remaining.append((start, gap_start))
            if gap_end < end:
                # Keep portion after gap
                next_remaining.append((gap_end, end))
        remaining = next_remaining
        if not remaining:
            break
    return remaining


def merge_intervals(intervals: List[Tuple[Any, Any]]) -> List[Tuple[Any, Any]]:
    """
    Merge overlapping intervals into non-overlapping segments.

    Works with any comparable types (integers for minutes, datetime objects, etc.)

    Args:
        intervals: A list of (start, end) tuples

    Returns:
        A list of merged non-overlapping intervals, sorted by start time
    """
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
