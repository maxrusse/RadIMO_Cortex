# Standard library imports
import logging
from datetime import datetime, time, timedelta, date
from typing import Any, List, Optional, Tuple, Dict
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
# Helper for Config Normalization
# -----------------------------------------------------------
def normalize_modality_fallback_entries(
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

# -----------------------------------------------------------
# TIME / DATE HELPERS
# -----------------------------------------------------------
TIME_FORMAT = '%H:%M'

def get_local_berlin_now() -> datetime:
    tz = pytz.timezone("Europe/Berlin")
    aware_now = datetime.now(tz)
    naive_now = aware_now.replace(tzinfo=None)
    return naive_now

def parse_time_range(time_range: str) -> Tuple[time, time]:
    """
    Parse a time range string into start and end time objects.
    Example: "08:00-16:00" -> (time(8,0), time(16,0))
    """
    start_str, end_str = time_range.split('-')
    start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
    end_time   = datetime.strptime(end_str.strip(), '%H:%M').time()
    return start_time, end_time

def compute_shift_window(
    start_time: time, end_time: time, reference_dt: datetime
) -> Tuple[datetime, datetime]:
    """Return normalized start/end datetimes for a shift (handles overnight)."""
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    ref_minutes = reference_dt.hour * 60 + reference_dt.minute

    overnight = end_minutes <= start_minutes
    if overnight:
        end_minutes += 24 * 60
        # If we're in the early-morning portion, the shift actually started yesterday.
        reference_date = (
            reference_dt.date() - timedelta(days=1)
            if ref_minutes < (end_minutes - 24 * 60)
            else reference_dt.date()
        )
    else:
        reference_date = reference_dt.date()

    start_dt = datetime.combine(reference_date, start_time)
    end_dt = start_dt + timedelta(minutes=end_minutes - start_minutes)
    return start_dt, end_dt

def is_now_in_shift(start_time: time, end_time: time, current_dt: datetime) -> bool:
    """Check whether ``current_dt`` falls inside the given shift window."""
    start_dt, end_dt = compute_shift_window(start_time, end_time, current_dt)
    return start_dt <= current_dt <= end_dt

def calculate_shift_duration_hours(start_time: time, end_time: time) -> float:
    """Calculate shift duration in hours, supporting overnight shifts."""
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
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

def get_next_workday(from_date: Optional[datetime] = None) -> datetime:
    """
    Calculate next workday.
    - If Friday: return Monday
    - Otherwise: return next day
    - Skips weekends
    """
    if from_date is None:
        from_date = get_local_berlin_now()

    # If datetime, convert to date
    if hasattr(from_date, 'date'):
        current_date = from_date.date()
    else:
        current_date = from_date

    # Calculate next day
    next_day = current_date + timedelta(days=1)

    # If next day is Saturday (5) or Sunday (6), move to Monday
    while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_day += timedelta(days=1)

    return datetime.combine(next_day, time(0, 0))

# -----------------------------------------------------------
# Data Validation
# -----------------------------------------------------------
def validate_excel_structure(df: pd.DataFrame, required_columns: List[str], skill_columns: List[str]) -> Tuple[bool, str]:
    """Validate uploaded Excel structure."""
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
    for skill in skill_columns:
        if skill in df.columns:
            if not pd.api.types.is_numeric_dtype(df[skill]):
                return False, f"Spalte '{skill}' sollte numerisch sein"

    return True, ""

# -----------------------------------------------------------
# Normalization Helpers
# -----------------------------------------------------------
WEIGHTED_SKILL_MARKER = 'w'

def normalize_skill_value(value: Any) -> Any:
    """Normalize skill values and convert old data format (``2`` -> ``'w'``)."""
    if value is None:
        return 0

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() == WEIGHTED_SKILL_MARKER:
            return WEIGHTED_SKILL_MARKER
        if cleaned == '':
            return 0
        try:
            parsed = int(float(cleaned))
        except ValueError:
            return 0
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0

    # Convert old data format: 2 was used for weighted skills before 'w' was introduced
    if parsed == 2:
        return WEIGHTED_SKILL_MARKER
    return parsed

def skill_value_to_numeric(value: Any) -> int:
    """Convert skill values to numeric form for comparisons (``'w'`` -> 1)."""
    if value == WEIGHTED_SKILL_MARKER:
        return 1
    try:
        parsed = int(float(value))
        return 1 if parsed == 2 else parsed
    except (TypeError, ValueError):
        return 0

def is_weighted_skill(value: Any) -> bool:
    """Check whether a skill value represents a weighted/assisted assignment."""
    if value == WEIGHTED_SKILL_MARKER:
        return True
    try:
        return int(float(value)) == 2
    except (TypeError, ValueError):
        return False
