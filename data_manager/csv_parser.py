"""
CSV parser module for medweb CSV transformation.

This module handles:
- Medweb CSV parsing and conversion to modality-specific DataFrames
- Multi-pass algorithm: collect shifts, create unavailable entries, add gap intent rows, resolve overlaps
- Skill overrides and time range computation
- Gap handling (standalone and embedded) as independent intent rows (canonicalized to gap segments)
"""
import re
from datetime import datetime, time, date
from typing import Dict, List, Optional, Tuple, Any, Iterable, Set

import pandas as pd

from config import (
    allowed_modalities,
    SKILL_COLUMNS,
    selection_logger,
)
from lib.utils import (
    TIME_FORMAT,
    get_weekday_name_german,
    coerce_bool,
)
from data_manager.worker_management import (
    get_canonical_worker_id,
    get_merged_worker_roster,
    get_worker_skill_mod_combinations,
    apply_skill_overrides,
    extract_modalities_from_skill_overrides,
    ensure_workers_in_skill_roster,
)
from data_manager.schedule_crud import build_day_plan_rows


DEFAULT_SHIFT_RANGE = (time(7, 0), time(15, 0))
GERMAN_TO_ENGLISH_WEEKDAYS = {
    "Montag": "monday",
    "Dienstag": "tuesday",
    "Mittwoch": "wednesday",
    "Donnerstag": "thursday",
    "Freitag": "friday",
    "Samstag": "saturday",
    "Sonntag": "sunday",
}
ENGLISH_TO_GERMAN_WEEKDAYS = {
    english: german for german, english in GERMAN_TO_ENGLISH_WEEKDAYS.items()
}
DEFAULT_SYNTHETIC_WORKDAYS = {"Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"}


def _default_shift_ranges() -> List[Tuple[time, time]]:
    return [DEFAULT_SHIFT_RANGE]


def _time_to_minutes(value: Optional[time]) -> int:
    if value is None:
        return 0
    return value.hour * 60 + value.minute


def _minutes_to_time(minutes: int) -> time:
    hours, mins = divmod(max(0, minutes), 60)
    return time(hour=hours, minute=mins)


def _strip_vm_nm_merge_metadata(row: dict) -> dict:
    cleaned = dict(row)
    for key in (
        '_vm_nm_merge_enabled',
        '_vm_nm_merge_key',
        '_vm_nm_source_day_part',
        '_vm_nm_source_activity',
    ):
        cleaned.pop(key, None)
    return cleaned


def _merge_vm_nm_pair_rows(rows: List[dict]) -> List[dict]:
    """
    Collapse config-driven VM/NM shift rows into a single row when both source
    parts exist for the same worker and source activity.

    This is intentionally conservative:
    - only rows from shift rules whose day-parts declare VMNM participate
    - only rows with both VM and NM source parts merge
    - rows with different source activities remain separate
    """
    if not rows:
        return []

    passthrough: List[dict] = []
    merge_buckets: Dict[Tuple[str, str], List[dict]] = {}

    for row in rows:
        if not row.get('_vm_nm_merge_enabled'):
            passthrough.append(_strip_vm_nm_merge_metadata(row))
            continue

        ppl = str(row.get('PPL', '')).strip()
        activity = str(row.get('_vm_nm_source_activity') or row.get('tasks') or '').strip()
        source_day_part = str(row.get('_vm_nm_source_day_part') or '').upper().strip()
        if not ppl or not activity:
            passthrough.append(_strip_vm_nm_merge_metadata(row))
            continue

        merge_key = str(row.get('_vm_nm_merge_key') or activity).strip().lower()
        bucket_key = (ppl, merge_key, activity)
        bucket = merge_buckets.setdefault(bucket_key, [])
        bucket.append({**row, '_vm_nm_source_day_part': source_day_part})

    merged_rows: List[dict] = passthrough[:]
    for bucket_rows in merge_buckets.values():
        day_parts = {str(row.get('_vm_nm_source_day_part') or '').upper() for row in bucket_rows}
        if not {'VM', 'NM'}.issubset(day_parts):
            merged_rows.extend(_strip_vm_nm_merge_metadata(row) for row in bucket_rows)
            continue

        valid_rows = [
            row for row in bucket_rows
            if isinstance(row.get('start_time'), time) and isinstance(row.get('end_time'), time)
        ]
        if len(valid_rows) < 2:
            merged_rows.extend(_strip_vm_nm_merge_metadata(row) for row in bucket_rows)
            continue

        template = min(valid_rows, key=lambda row: (_time_to_minutes(row['start_time']), _time_to_minutes(row['end_time'])))
        start_min = min(_time_to_minutes(row['start_time']) for row in valid_rows)
        end_min = max(_time_to_minutes(row['end_time']) for row in valid_rows)
        if end_min <= start_min:
            merged_rows.extend(_strip_vm_nm_merge_metadata(row) for row in bucket_rows)
            continue

        merged_row = _strip_vm_nm_merge_metadata(template)
        merged_row['start_time'] = _minutes_to_time(start_min)
        merged_row['end_time'] = _minutes_to_time(end_min)
        merged_row['shift_duration'] = round((end_min - start_min) / 60.0, 4)
        merged_row['TIME'] = (
            f"{merged_row['start_time'].strftime(TIME_FORMAT)}-"
            f"{merged_row['end_time'].strftime(TIME_FORMAT)}"
        )
        merged_rows.append(merged_row)

    return merged_rows


def _select_day_times(
    times_config: Dict[str, Any],
    weekday_name: str,
) -> Optional[Any]:
    if weekday_name in times_config:
        return times_config[weekday_name]
    english_day = GERMAN_TO_ENGLISH_WEEKDAYS.get(weekday_name)
    if english_day and english_day in times_config:
        return times_config[english_day]
    if 'default' in times_config:
        return times_config['default']
    return None


def _normalize_time_ranges_input(day_times: Any) -> Optional[List[str]]:
    if isinstance(day_times, str):
        return [day_times]
    if isinstance(day_times, list):
        return day_times
    return None


def _parse_time_ranges(
    time_ranges: Iterable[Any],
    *,
    log_label: str,
) -> List[Tuple[time, time]]:
    parsed_ranges: List[Tuple[time, time]] = []
    for time_range_str in time_ranges:
        if not isinstance(time_range_str, str):
            selection_logger.warning(
                f"Could not parse {log_label} time range '{time_range_str}': expected string"
            )
            continue
        try:
            start_str, end_str = time_range_str.split('-')
            start_time = datetime.strptime(start_str.strip(), TIME_FORMAT).time()
            end_time = datetime.strptime(end_str.strip(), TIME_FORMAT).time()
            parsed_ranges.append((start_time, end_time))
        except ValueError as exc:
            selection_logger.warning(
                f"Could not parse {log_label} time range '{time_range_str}': {exc}"
            )
            continue
    return parsed_ranges


def _normalize_day_part_values(raw_value: Any) -> Set[str]:
    """Normalize CSV/config day-part values to canonical VM/NM tokens."""
    if raw_value is None:
        return set()

    if isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        raw_items = [raw_value]

    normalized: Set[str] = set()
    for item in raw_items:
        if item is None:
            continue
        if isinstance(item, str):
            tokens = re.split(r"[,\s+/|&;]+", item.strip())
        else:
            tokens = [str(item)]

        for token in tokens:
            token_norm = token.strip().lower()
            if not token_norm:
                continue
            if token_norm in {"vm", "vormittag", "morning"}:
                normalized.add("VM")
            elif token_norm in {"nm", "nachmittag", "afternoon"}:
                normalized.add("NM")
            elif token_norm in {"vm+nm", "nm+vm", "vm/nm", "nm/vm", "vmnm", "nmvm", "both", "all", "any"}:
                normalized.update({"VM", "NM"})

    return normalized


def _normalize_day_part_label(raw_value: Any) -> Optional[str]:
    """Normalize day-part values to the internal VM / VMNM / NM helper label."""
    normalized = _normalize_day_part_values(raw_value)
    if not normalized:
        return None
    if normalized == {"VM"}:
        return "VM"
    if normalized == {"NM"}:
        return "NM"
    if normalized == {"VM", "NM"}:
        return "VMNM"
    if "VM" in normalized and "NM" in normalized:
        return "VMNM"
    if "VM" in normalized:
        return "VM"
    if "NM" in normalized:
        return "NM"
    return None


def _normalize_rule_day_part_labels(raw_value: Any) -> Set[str]:
    """Normalize rule day-part declarations to helper labels like VM, VMNM, NM."""
    if raw_value is None:
        return set()

    if isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        raw_items = [raw_value]

    normalized: Set[str] = set()
    for item in raw_items:
        label = _normalize_day_part_label(item)
        if label:
            normalized.add(label)
    return normalized


def _normalize_row_day_part_values(raw_value: Any) -> Set[str]:
    """Normalize Medweb row day-part values for matching.

    Combined VM+NM rows are treated as VM/Früh for rule selection so the
    normal rule wins over the late-only rule. The internal helper label for
    such rows is VMNM.
    """
    day_part_label = _normalize_day_part_label(raw_value)
    if day_part_label == "VMNM":
        return {"VM"}
    normalized = _normalize_day_part_values(raw_value)
    return normalized


def _normalize_rule_day_parts(rule: dict) -> Optional[Set[str]]:
    raw_value = rule.get("day_parts", rule.get("day_part"))
    if raw_value is None:
        return {"VM", "VMNM", "NM"}
    normalized = _normalize_day_part_values(raw_value)
    return normalized or None


def _extract_row_day_part(row: pd.Series, cols: Optional[dict]) -> Optional[str]:
    if not cols:
        return None
    day_part_col = cols.get("day_part")
    if not day_part_col:
        return None
    value = row.get(day_part_col, None)
    if pd.isna(value):
        return None
    return _normalize_day_part_label(value)


def _rule_matches_day_part(rule: dict, row_day_part: Optional[str]) -> bool:
    if rule.get("day_parts", rule.get("day_part")) is None:
        return True

    allowed_day_parts = _normalize_rule_day_parts(rule)
    if not allowed_day_parts:
        return True

    row_day_parts = _normalize_row_day_part_values(row_day_part)
    if not row_day_parts:
        return False

    return bool(allowed_day_parts.intersection(row_day_parts))


def _normalize_rule_text_filters(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        values = raw_value
    else:
        values = [raw_value]
    normalized: List[str] = []
    for value in values:
        text = str(value).strip().lower()
        if text:
            normalized.append(text)
    return normalized


def _rule_matches_gruppe(rule: dict, gruppe: Optional[str]) -> bool:
    exclude_filters = _normalize_rule_text_filters(rule.get('exclude_gruppe'))
    if not exclude_filters:
        return True
    gruppe_lower = str(gruppe or '').strip().lower()
    if not gruppe_lower:
        return True
    return not any(excluded in gruppe_lower for excluded in exclude_filters)


def match_mapping_rule(
    activity_desc: str,
    rules: List[dict],
    *,
    day_part: Optional[str] = None,
    gruppe: Optional[str] = None,
) -> Optional[dict]:
    """Match activity description against mapping rules.

    When rules declare `day_part`/`day_parts`, the CSV row must match that
    VM/NM value as well. Rules without a day-part filter keep the old
    wildcard behavior.
    """
    if not activity_desc:
        return None
    activity_lower = activity_desc.lower()
    for rule in rules:
        match_str = rule.get('match', '')
        if (
            match_str.lower() in activity_lower
            and _rule_matches_day_part(rule, day_part)
            and _rule_matches_gruppe(rule, gruppe)
        ):
            return rule
    return None


def compute_time_ranges(
    row: pd.Series,
    rule: dict,
    target_date: datetime,
    config: dict,
) -> List[Tuple[time, time]]:
    """
    Compute time ranges from rule's inline 'times' field.

    Structure supports day-specific times with both single string and array formats:
        times:
            default: "07:00-15:00"              # Single time
            Montag: "08:00-16:00"               # Single time for specific day
            Dienstag:                           # Array format for multiple shifts
                - "07:00-12:00"
                - "14:00-18:00"
            Freitag: "07:00-13:00"
    """
    times_config = rule.get('times', {})

    if not times_config:
        # No times specified - use default
        return _default_shift_ranges()

    # Get German weekday name for day-specific lookup
    weekday_name = get_weekday_name_german(target_date)

    # Check for day-specific time first, then default
    day_times = _select_day_times(times_config, weekday_name)
    if day_times is None:
        return _default_shift_ranges()

    # Handle both single string and array formats (aligned with parse_gap_times)
    time_ranges_str = _normalize_time_ranges_input(day_times)
    if time_ranges_str is None:
        return _default_shift_ranges()

    time_ranges = _parse_time_ranges(time_ranges_str, log_label="shift")

    # Return default if no valid time ranges were parsed
    if not time_ranges:
        return _default_shift_ranges()

    return time_ranges


def parse_gap_times(times_config: dict, weekday_name: str) -> List[Tuple[time, time]]:
    """
    Parse gap times for a specific weekday.

    Uses unified 'times' field (same as shifts).
    Supports both single string and array formats:
        times:
            Montag: "10:00-11:00"              # Single time
            Dienstag:                          # Array format
                - "10:00-11:00"
                - "14:00-15:00"
            default: "09:00-10:00"             # Optional default

    Returns list of (start_time, end_time) tuples.
    """
    if not times_config:
        return []

    # Check for day-specific times first, then default
    day_times = _select_day_times(times_config, weekday_name)
    if day_times is None:
        return []

    time_ranges = _normalize_time_ranges_input(day_times)
    if time_ranges is None:
        return []

    return _parse_time_ranges(time_ranges, log_label="gap")


def _effective_rule_segments(
    rule: dict,
    *,
    rule_type: str,
) -> List[dict]:
    """Return normalized effective rule segments for legacy and segmented rules."""
    raw_segments = rule.get('segments')
    if raw_segments is None:
        return [rule]

    if not isinstance(raw_segments, list) or not raw_segments:
        selection_logger.warning(
            "Rule '%s' has invalid segments configuration - skipping segmented expansion",
            rule.get('match', ''),
        )
        return []

    base_skill_overrides = rule.get('skill_overrides', {})
    if base_skill_overrides is None:
        base_skill_overrides = {}
    if not isinstance(base_skill_overrides, dict):
        selection_logger.warning(
            "Rule '%s' has invalid base skill_overrides - expected dict",
            rule.get('match', ''),
        )
        base_skill_overrides = {}

    segments: List[dict] = []
    for idx, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            selection_logger.warning(
                "Rule '%s' segment %s is not a dict - skipping",
                rule.get('match', ''),
                idx,
            )
            continue
        if 'times' not in segment:
            selection_logger.warning(
                "Rule '%s' segment %s missing times - skipping",
                rule.get('match', ''),
                idx,
            )
            continue

        effective_rule = dict(rule)
        effective_rule.pop('segments', None)

        for key in ('times', 'label', 'counts_for_hours', 'modifier', 'gaps', 'day_part', 'day_parts'):
            if key in segment:
                effective_rule[key] = segment[key]

        segment_skill_overrides = segment.get('skill_overrides', {})
        if segment_skill_overrides is None:
            segment_skill_overrides = {}
        if not isinstance(segment_skill_overrides, dict):
            selection_logger.warning(
                "Rule '%s' segment %s has invalid skill_overrides - expected dict",
                rule.get('match', ''),
                idx,
            )
            continue

        if rule_type == 'shift':
            merged_skill_overrides = dict(base_skill_overrides)
            merged_skill_overrides.update(segment_skill_overrides)
            effective_rule['skill_overrides'] = merged_skill_overrides
        elif 'skill_overrides' in segment:
            effective_rule['skill_overrides'] = segment_skill_overrides

        segments.append(effective_rule)

    return segments


def build_ppl_from_row(row: pd.Series, cols: Optional[dict] = None) -> str:
    """Build PPL string from CSV row."""
    name_col = cols.get('employee_name', 'Name des Mitarbeiters') if cols else 'Name des Mitarbeiters'
    personalnummer_col = cols.get('employee_personalnummer', 'Personalnummer') if cols else 'Personalnummer'
    code_col = cols.get('employee_code', 'Code des Mitarbeiters') if cols else 'Code des Mitarbeiters'
    name = '' if pd.isna(row.get(name_col, '')) else str(row.get(name_col, '')).strip()
    if not name:
        name = 'Unknown'
    personalnummer = '' if pd.isna(row.get(personalnummer_col, '')) else str(row.get(personalnummer_col, '')).strip()
    code = '' if pd.isna(row.get(code_col, '')) else str(row.get(code_col, '')).strip()
    worker_id = personalnummer or code or 'UNK'
    return f"{name} ({worker_id})"


def _coerce_bool_like(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'y'}:
            return True
        if normalized in {'false', '0', 'no', 'n'}:
            return False
    return bool(value)


def _normalize_synthetic_weekdays(raw_value: Any) -> Set[str]:
    if raw_value is None:
        return set(DEFAULT_SYNTHETIC_WORKDAYS)
    if isinstance(raw_value, str):
        raw_items = [raw_value]
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        return set()

    result: Set[str] = set()
    for item in raw_items:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in {'all', 'daily', 'everyday'}:
            return set(GERMAN_TO_ENGLISH_WEEKDAYS.keys())
        if lowered in {'workday', 'workdays', 'weekday', 'weekdays'}:
            result.update(DEFAULT_SYNTHETIC_WORKDAYS)
            continue
        if token in GERMAN_TO_ENGLISH_WEEKDAYS:
            result.add(token)
            continue
        german = ENGLISH_TO_GERMAN_WEEKDAYS.get(lowered)
        if german:
            result.add(german)
    return result


def _compute_synthetic_time_ranges(
    entry: dict,
    weekday_name: str,
) -> List[Tuple[time, time]]:
    times_config = entry.get('times', {})
    if not isinstance(times_config, dict) or not times_config:
        return _default_shift_ranges()

    day_times = _select_day_times(times_config, weekday_name)
    if day_times is None:
        return _default_shift_ranges()

    time_ranges = _normalize_time_ranges_input(day_times)
    if time_ranges is None:
        return _default_shift_ranges()

    parsed = _parse_time_ranges(time_ranges, log_label="synthetic shift")
    return parsed or _default_shift_ranges()


def _get_synthetic_worker_names(config: dict) -> List[str]:
    raw_entries = config.get('synthetic_shifts', [])
    if not isinstance(raw_entries, list):
        return []

    worker_names: List[str] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        worker_name = str(entry.get('worker_name') or entry.get('name') or '').strip()
        if worker_name and worker_name not in worker_names:
            worker_names.append(worker_name)
    return worker_names


def build_working_hours_from_medweb(
    csv_path: str,
    target_date: datetime,
    config: dict
) -> Dict[str, pd.DataFrame]:
    """
    Build working hours DataFrames from medweb CSV.

    New unified structure:
    - Shifts have 'times' (day-specific) and 'skill_overrides' (REQUIRED)
    - Modalities are DERIVED from skill_overrides keys
    - Shifts can have embedded 'gaps' for team-specific gaps
    - Standalone gaps support arrays of times per day
    - Day plan building: later shift ends prior, gaps always win
    - Standalone gaps with no shift create "unavailable" entries
    """
    try:
        try:
            medweb_df = pd.read_csv(csv_path, sep=',', encoding='utf-8')
        except UnicodeDecodeError:
            medweb_df = pd.read_csv(csv_path, sep=',', encoding='latin1')
    except Exception:
        try:
            try:
                medweb_df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                medweb_df = pd.read_csv(csv_path, sep=';', encoding='latin1')
        except Exception as e:
            raise ValueError(f"Fehler beim Laden der CSV: {e}")

    def parse_german_date(date_val: Any) -> Optional[date]:
        if pd.isna(date_val):
            return None
        date_str = str(date_val).strip()
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        try:
            return pd.to_datetime(date_str, dayfirst=True).date()
        except Exception as exc:
            selection_logger.warning("Failed to parse date value '%s': %s", date_val, exc)
            return None

    vendor_mapping = config.get('medweb_mapping', {})
    cols = vendor_mapping.get('columns', {
        'date': 'Datum',
        'activity': 'Beschreibung der Aktivität',
        'employee_name': 'Name des Mitarbeiters',
        'employee_personalnummer': 'Personalnummer',
        'employee_code': 'Code des Mitarbeiters'
    })

    medweb_df['Datum_parsed'] = medweb_df[cols.get('date', 'Datum')].apply(parse_german_date)
    target_date_obj = target_date.date() if hasattr(target_date, 'date') else target_date

    parsed_dates = medweb_df['Datum_parsed'].dropna().unique().tolist()
    selection_logger.debug(f"CSV dates parsed: {parsed_dates}, target: {target_date_obj}, type: {type(target_date_obj)}")

    mapping_rules = vendor_mapping.get('rules', [])
    synthetic_worker_names = _get_synthetic_worker_names(config)
    if synthetic_worker_names:
        ensure_workers_in_skill_roster(synthetic_worker_names)
    worker_roster = get_merged_worker_roster(config)

    day_df = medweb_df[medweb_df['Datum_parsed'] == target_date_obj]
    if day_df.empty:
        selection_logger.warning(
            "No Medweb rows found for date %s. Available: %s. Continuing with synthetic shifts only.",
            target_date_obj,
            parsed_dates,
        )

    selection_logger.debug(f"Found {len(day_df)} rows for target date, {len(mapping_rules)} mapping rules")

    weekday_name = get_weekday_name_german(target_date_obj)

    rows_per_modality = {mod: [] for mod in allowed_modalities}
    exclusions_per_worker: Dict[str, List[dict]] = {}
    workers_with_shifts: set = set()
    workers_with_shifts_by_modality: Dict[str, set] = {mod: set() for mod in allowed_modalities}
    unmatched_activities = []

    mergeable_match_strings: Set[str] = set()
    for rule in mapping_rules:
        if str(rule.get('type', 'shift')).strip().lower() != 'shift':
            continue
        day_part_labels = _normalize_rule_day_part_labels(rule.get('day_parts', rule.get('day_part')))
        if 'VMNM' in day_part_labels:
            match_str = str(rule.get('match', '')).strip().lower()
            if match_str:
                mergeable_match_strings.add(match_str)

    # FIRST PASS: Collect all Medweb-derived shifts and gaps for each worker
    for _, row in day_df.iterrows():
        activity_desc = str(row.get(cols.get('activity', 'Beschreibung der Aktivität'), ''))
        row_day_part = _extract_row_day_part(row, cols)
        row_gruppe = row.get('Gruppe', '')
        rule = match_mapping_rule(
            activity_desc,
            mapping_rules,
            day_part=row_day_part,
            gruppe=row_gruppe,
        )
        if not rule:
            unmatched_activities.append(activity_desc)
            continue

        ppl_str = build_ppl_from_row(row, cols=cols)
        canonical_id = get_canonical_worker_id(ppl_str)
        rule_type = rule.get('type', 'shift')
        effective_segments = _effective_rule_segments(rule, rule_type=rule_type)
        if not effective_segments:
            continue

        for effective_rule in effective_segments:
            if not _rule_matches_day_part(effective_rule, row_day_part):
                continue

            segment_rule_type = effective_rule.get('type', rule_type)

            # Handle GAP rules (standalone gaps)
            if segment_rule_type == 'gap':
                gap_times = parse_gap_times(effective_rule.get('times', {}), weekday_name)

                if not gap_times:
                    continue

                hours_counting_config = config.get('balancer', {}).get('hours_counting', {})
                if 'counts_for_hours' in effective_rule:
                    counts_for_hours = effective_rule['counts_for_hours']
                else:
                    counts_for_hours = hours_counting_config.get('gap_default', False)

                if canonical_id not in exclusions_per_worker:
                    exclusions_per_worker[canonical_id] = []

                gap_label = effective_rule.get('label', activity_desc)

                for gap_start, gap_end in gap_times:
                    exclusions_per_worker[canonical_id].append({
                        'start_time': gap_start,
                        'end_time': gap_end,
                        'activity': gap_label,
                        'counts_for_hours': counts_for_hours,
                        'ppl_str': ppl_str
                    })

                    selection_logger.info(
                        f"Time exclusion for {ppl_str} ({weekday_name}): "
                        f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({activity_desc})"
                    )
                continue

            # Handle SHIFT rules
            if segment_rule_type != 'shift':
                continue

            skill_overrides = effective_rule.get('skill_overrides', {})

            if not skill_overrides:
                selection_logger.warning(
                    f"Shift rule '{effective_rule.get('match', '')}' missing skill_overrides - skipping"
                )
                continue

            target_modalities = extract_modalities_from_skill_overrides(skill_overrides)
            target_modalities = [m for m in target_modalities if m in allowed_modalities]

            if not target_modalities:
                selection_logger.warning(
                    f"Shift rule '{effective_rule.get('match', '')}' has no valid modalities in skill_overrides - skipping"
                )
                continue

            workers_with_shifts.add(canonical_id)

            roster_combinations = get_worker_skill_mod_combinations(canonical_id, worker_roster)
            training = coerce_bool(effective_rule.get('training'))
            if training is None:
                training = True
            allow_roster_exclusion_override = coerce_bool(
                effective_rule.get('allow_roster_exclusion_override')
            )
            if allow_roster_exclusion_override is None:
                allow_roster_exclusion_override = False
            final_combinations = apply_skill_overrides(
                roster_combinations,
                skill_overrides,
                training=training,
                allow_roster_exclusion_override=allow_roster_exclusion_override,
            )

            time_ranges = compute_time_ranges(row, effective_rule, target_date, config)

            embedded_gaps = effective_rule.get('gaps', {})
            embedded_gap_times = parse_gap_times(embedded_gaps, weekday_name)

            if embedded_gap_times:
                hours_counting_config = config.get('balancer', {}).get('hours_counting', {})
                if 'counts_for_hours' in effective_rule:
                    counts_for_hours = effective_rule['counts_for_hours']
                else:
                    counts_for_hours = hours_counting_config.get('gap_default', False)

                if canonical_id not in exclusions_per_worker:
                    exclusions_per_worker[canonical_id] = []

                embedded_gap_label = effective_rule.get('label', activity_desc)

                for gap_start, gap_end in embedded_gap_times:
                    exclusions_per_worker[canonical_id].append({
                        'start_time': gap_start,
                        'end_time': gap_end,
                        'activity': f"{embedded_gap_label} (gap)",
                        'counts_for_hours': counts_for_hours,
                        'ppl_str': ppl_str
                    })
                    selection_logger.info(
                        f"Embedded gap for {ppl_str} ({weekday_name}): "
                        f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({embedded_gap_label})"
                    )

            for modality in target_modalities:
                modality_skills = {}
                for skill in SKILL_COLUMNS:
                    combo_key = f"{skill}_{modality}"
                    modality_skills[skill] = final_combinations.get(combo_key, 0)

                for start_time, end_time in time_ranges:
                    start_dt = datetime.combine(target_date_obj, start_time)
                    end_dt = datetime.combine(target_date_obj, end_time)
                    if end_dt <= start_dt:
                        continue
                    duration_hours = (end_dt - start_dt).total_seconds() / 3600

                    rule_modifier = effective_rule.get('modifier', 1.0)
                    hours_counting_config = config.get('balancer', {}).get('hours_counting', {})
                    if 'counts_for_hours' in effective_rule:
                        counts_for_hours = effective_rule['counts_for_hours']
                    else:
                        counts_for_hours = hours_counting_config.get('shift_default', True)

                    task_label = effective_rule.get('label', activity_desc)

                    row_payload = {
                        'PPL': ppl_str,
                        'canonical_id': canonical_id,
                        'start_time': start_time,
                        'end_time': end_time,
                        'shift_duration': duration_hours,
                        'Modifier': rule_modifier,
                        'tasks': task_label,
                        'counts_for_hours': counts_for_hours,
                        'row_type': 'shift',
                        'training': training,
                        **modality_skills
                    }
                    merge_key = str(effective_rule.get('match', '')).strip().lower()
                    if merge_key in mergeable_match_strings:
                        row_payload['_vm_nm_merge_enabled'] = True
                        row_payload['_vm_nm_merge_key'] = merge_key
                        row_payload['_vm_nm_source_day_part'] = str(row_day_part or '').strip().upper()
                        row_payload['_vm_nm_source_activity'] = activity_desc
                    rows_per_modality[modality].append(row_payload)
                    workers_with_shifts_by_modality[modality].add(canonical_id)

    for modality, modality_rows in rows_per_modality.items():
        rows_per_modality[modality] = _merge_vm_nm_pair_rows(modality_rows)

    # Synthetic recurring shifts are injected after Medweb parsing so they use the
    # same shift/gap normalization and roster precedence as CSV-derived rows.
    raw_synthetic_shifts = config.get('synthetic_shifts', [])
    if isinstance(raw_synthetic_shifts, list):
        for entry in raw_synthetic_shifts:
            if not isinstance(entry, dict):
                continue

            worker_name = str(entry.get('worker_name') or entry.get('name') or '').strip()
            if not worker_name:
                selection_logger.warning("Synthetic shift missing worker_name/name - skipping")
                continue

            allowed_weekdays = _normalize_synthetic_weekdays(entry.get('weekdays'))
            if entry.get('weekdays') is not None and not allowed_weekdays:
                selection_logger.warning(
                    "Synthetic shift '%s' has invalid weekdays configuration - skipping",
                    worker_name,
                )
                continue
            if allowed_weekdays and weekday_name not in allowed_weekdays:
                continue

            skill_overrides = entry.get('skill_overrides', {})
            if not isinstance(skill_overrides, dict) or not skill_overrides:
                selection_logger.warning(
                    "Synthetic shift '%s' missing skill_overrides - skipping",
                    worker_name,
                )
                continue

            target_modalities = extract_modalities_from_skill_overrides(skill_overrides)
            target_modalities = [m for m in target_modalities if m in allowed_modalities]
            if not target_modalities:
                selection_logger.warning(
                    "Synthetic shift '%s' has no valid modalities in skill_overrides - skipping",
                    worker_name,
                )
                continue

            canonical_id = get_canonical_worker_id(worker_name)
            roster_combinations = get_worker_skill_mod_combinations(canonical_id, worker_roster)
            training = coerce_bool(entry.get('training'))
            if training is None:
                training = True
            final_combinations = apply_skill_overrides(
                roster_combinations,
                skill_overrides,
                training=training,
            )

            time_ranges = _compute_synthetic_time_ranges(entry, weekday_name)
            task_label = str(entry.get('label') or entry.get('task') or worker_name)

            try:
                rule_modifier = float(entry.get('modifier', 1.0))
            except (TypeError, ValueError):
                rule_modifier = 1.0

            hours_counting_config = config.get('balancer', {}).get('hours_counting', {})
            counts_for_hours = _coerce_bool_like(
                entry.get('counts_for_hours'),
                hours_counting_config.get('shift_default', True),
            )

            workers_with_shifts.add(canonical_id)

            embedded_gaps = entry.get('gaps', {})
            embedded_gap_times = parse_gap_times(embedded_gaps, weekday_name)
            if embedded_gap_times:
                if canonical_id not in exclusions_per_worker:
                    exclusions_per_worker[canonical_id] = []
                gap_counts_for_hours = _coerce_bool_like(
                    entry.get('gap_counts_for_hours'),
                    config.get('balancer', {}).get('hours_counting', {}).get('gap_default', False),
                )
                for gap_start, gap_end in embedded_gap_times:
                    exclusions_per_worker[canonical_id].append({
                        'start_time': gap_start,
                        'end_time': gap_end,
                        'activity': f"{task_label} (gap)",
                        'counts_for_hours': gap_counts_for_hours,
                        'ppl_str': worker_name,
                    })

            for modality in target_modalities:
                modality_skills = {}
                for skill in SKILL_COLUMNS:
                    combo_key = f"{skill}_{modality}"
                    modality_skills[skill] = final_combinations.get(combo_key, 0)

                for start_time, end_time in time_ranges:
                    start_dt = datetime.combine(target_date_obj, start_time)
                    end_dt = datetime.combine(target_date_obj, end_time)
                    if end_dt <= start_dt:
                        continue
                    duration_hours = (end_dt - start_dt).total_seconds() / 3600
                    rows_per_modality[modality].append({
                        'PPL': worker_name,
                        'canonical_id': canonical_id,
                        'start_time': start_time,
                        'end_time': end_time,
                        'shift_duration': duration_hours,
                        'Modifier': rule_modifier,
                        'tasks': task_label,
                        'counts_for_hours': counts_for_hours,
                        'row_type': 'shift',
                        'training': training,
                        **modality_skills,
                    })
                    workers_with_shifts_by_modality[modality].add(canonical_id)

    # SECOND PASS: Create "unavailable" entries for workers with gaps but no shifts
    for canonical_id, exclusions in exclusions_per_worker.items():
        if canonical_id in workers_with_shifts:
            continue  # Will be handled in gap application

        # Worker has only gaps, no shifts -> create "unavailable" entry
        for excl in exclusions:
            ppl_str = excl.get('ppl_str', f'Unknown ({canonical_id})')
            gap_start = excl['start_time']
            gap_end = excl['end_time']
            activity = excl['activity']

            start_dt = datetime.combine(target_date_obj, gap_start)
            end_dt = datetime.combine(target_date_obj, gap_end)
            # Same-day only: skip invalid gaps where end <= start
            if end_dt <= start_dt:
                continue
            duration_hours = (end_dt - start_dt).total_seconds() / 3600
            counts_for_hours = excl.get('counts_for_hours', False)
            # Create an entry in all modalities (or just first one) with all skills = -1
            unavailable_skills = {skill: -1 for skill in SKILL_COLUMNS}

            # Add to first modality (could be all, but one is enough for visibility)
            first_mod = allowed_modalities[0] if allowed_modalities else 'ct'
            rows_per_modality[first_mod].append({
                'PPL': ppl_str,
                'canonical_id': canonical_id,
                'start_time': gap_start,
                'end_time': gap_end,
                'shift_duration': 0.0,
                'Modifier': 1.0,
                'tasks': f"[Unavailable] {activity}",
                'counts_for_hours': counts_for_hours,
                'row_type': 'gap',
                **unavailable_skills
            })

            selection_logger.info(
                f"Created unavailable entry for {ppl_str} ({weekday_name}): "
                f"{gap_start.strftime(TIME_FORMAT)}-{gap_end.strftime(TIME_FORMAT)} ({activity})"
            )

    # THIRD PASS: Add gap intent rows for workers with shifts
    if exclusions_per_worker:
        selection_logger.info(
            f"Adding gap intent rows for {len(exclusions_per_worker)} workers on {weekday_name}"
        )
        for worker_id, exclusions in exclusions_per_worker.items():
            if worker_id not in workers_with_shifts:
                continue

            for modality in rows_per_modality:
                if worker_id not in workers_with_shifts_by_modality.get(modality, set()):
                    continue
                ppl_str = exclusions[0].get('ppl_str', f'Unknown ({worker_id})')
                for excl in exclusions:
                    rows_per_modality[modality].append({
                        'PPL': ppl_str,
                        'canonical_id': worker_id,
                        'start_time': excl['start_time'],
                        'end_time': excl['end_time'],
                        'shift_duration': 0.0,
                        'Modifier': 1.0,
                        'tasks': excl.get('activity', 'Gap'),
                        'counts_for_hours': excl.get('counts_for_hours', False),
                        'row_type': 'gap',
                        **{skill: -1 for skill in SKILL_COLUMNS},
                    })

    if unmatched_activities:
        selection_logger.debug(f"Unmatched activities: {set(unmatched_activities)}")

    # FOURTH PASS: Build canonical day plan per modality
    for modality in rows_per_modality:
        if rows_per_modality[modality]:
            intent_rows = []
            for row in rows_per_modality[modality]:
                cleaned = dict(row)
                cleaned.pop('shift_duration', None)
                cleaned.pop('TIME', None)
                intent_rows.append(cleaned)
            rows_per_modality[modality] = build_day_plan_rows(
                intent_rows,
                target_date_obj,
            )

    result = {}
    for modality, rows in rows_per_modality.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        if 'canonical_id' in df.columns:
            df = df.drop(columns=['canonical_id'])
        result[modality] = df

    selection_logger.info(f"Loaded {sum(len(df) for df in result.values())} workers across {list(result.keys())}")
    return result
