#!/usr/bin/env python3
"""
Standalone script for Weight Roster CSV Import/Export.

Usage:
    python scripts/roster_csv_tool.py export [output.csv]
    python scripts/roster_csv_tool.py import <input.csv> [--mode replace|merge|add_only]
    python scripts/roster_csv_tool.py validate <input.csv>
    python scripts/roster_csv_tool.py preview

CSV Format:
    Worker,Notfall_ct,Privat_ct,Gyn_ct,...,Notfall_mr,Privat_mr,...
    Dr. Müller (CT1),1,0,0,...,0,0,...

Values:
    1  = Active (primary skill)
    0  = Passive (fallback/helper)
    -1 = Excluded (cannot do)
    w  = Weighted/Assisted (learning, uses modifier)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pandas as pd
except ImportError:
    print("Error: pandas is required. Install with: pip install pandas")
    sys.exit(1)

# Default configuration (can be overridden)
DEFAULT_ROSTER_FILE = 'worker_skill_roster.json'
DEFAULT_SKILLS = ['Notfall', 'Privat', 'Gyn', 'Päd', 'MSK', 'Abdomen', 'Chest', 'Cardvask', 'Uro']
DEFAULT_MODALITIES = ['ct', 'mr', 'xray', 'mammo']


def load_config() -> Tuple[List[str], List[str]]:
    """Try to load skills and modalities from config.yaml, fall back to defaults."""
    try:
        import yaml
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            skills = list(config.get('skills', {}).keys()) or DEFAULT_SKILLS
            modalities = list(config.get('modalities', {}).keys()) or DEFAULT_MODALITIES
            return skills, modalities
    except Exception:
        pass

    return DEFAULT_SKILLS, DEFAULT_MODALITIES


def load_roster(roster_path: str = DEFAULT_ROSTER_FILE) -> Dict[str, Any]:
    """Load roster from JSON file."""
    if not os.path.exists(roster_path):
        print(f"Warning: Roster file not found: {roster_path}")
        return {}

    with open(roster_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_roster(roster: Dict[str, Any], roster_path: str = DEFAULT_ROSTER_FILE) -> bool:
    """Save roster to JSON file."""
    try:
        with open(roster_path, 'w', encoding='utf-8') as f:
            json.dump(roster, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving roster: {e}")
        return False


def parse_value(raw_value) -> int:
    """Parse a roster cell value to numeric representation."""
    if pd.isna(raw_value):
        return 0

    if isinstance(raw_value, (int, float)):
        val = int(raw_value)
        if val in (1, 0, -1, 2):
            return val
        raise ValueError(f"Invalid numeric value: {raw_value}")

    str_val = str(raw_value).strip().lower()
    if str_val in ('', 'nan', 'none'):
        return 0
    if str_val == 'w':
        return 2
    if str_val in ('1', '0', '-1', '2'):
        return int(str_val)

    raise ValueError(f"Invalid value: {raw_value}")


def format_value(value: int) -> str:
    """Format numeric value for CSV output."""
    if value == 2:
        return 'w'
    return str(value)


def export_to_csv(output_path: Optional[str] = None, roster_path: str = DEFAULT_ROSTER_FILE) -> str:
    """Export roster JSON to CSV format."""
    skills, modalities = load_config()
    roster = load_roster(roster_path)

    if not roster:
        print("Error: Roster is empty or not found")
        sys.exit(1)

    # Build columns
    columns = ['Worker']
    for mod in modalities:
        for skill in skills:
            columns.append(f"{skill}_{mod}")

    # Build rows
    rows = []
    for worker_name, worker_data in roster.items():
        row = {'Worker': worker_name}

        # Handle hierarchical format: {mod: {skill: value}}
        if worker_data and isinstance(next(iter(worker_data.values()), None), dict):
            for mod in modalities:
                mod_skills = worker_data.get(mod, {})
                for skill in skills:
                    col_name = f"{skill}_{mod}"
                    value = mod_skills.get(skill, 0)
                    row[col_name] = format_value(value)
        else:
            # Flat format: {skill_mod: value}
            for mod in modalities:
                for skill in skills:
                    col_name = f"{skill}_{mod}"
                    value = worker_data.get(col_name, 0)
                    row[col_name] = format_value(value)

        rows.append(row)

    df = pd.DataFrame(rows, columns=columns)

    # Generate output path if not provided
    if output_path is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f'worker_skill_roster_{timestamp}.csv'

    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"Exported {len(rows)} workers to: {output_path}")
    print(f"Columns: {len(columns)} (Worker + {len(columns)-1} skill×modality combinations)")

    return output_path


def import_from_csv(csv_path: str, merge_mode: str = 'replace', roster_path: str = DEFAULT_ROSTER_FILE) -> Dict[str, int]:
    """Import roster from CSV to JSON format."""
    skills, modalities = load_config()

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    # Try different encodings
    df = None
    for encoding in ['utf-8-sig', 'utf-8', 'latin1', 'cp1252']:
        try:
            df = pd.read_csv(csv_path, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    if df is None:
        print("Error: Could not read CSV file with any encoding")
        sys.exit(1)

    if 'Worker' not in df.columns:
        print("Error: CSV must have 'Worker' column")
        sys.exit(1)

    # Load existing roster based on merge mode
    existing_roster = load_roster(roster_path) if merge_mode != 'replace' else {}
    new_roster = {} if merge_mode == 'replace' else existing_roster.copy()

    stats = {'added': 0, 'updated': 0, 'skipped': 0, 'errors': 0}

    for _, row in df.iterrows():
        worker_name = str(row['Worker']).strip()
        if not worker_name or worker_name == 'nan':
            continue

        if merge_mode == 'add_only' and worker_name in existing_roster:
            stats['skipped'] += 1
            continue

        is_update = worker_name in existing_roster

        # Build hierarchical structure
        worker_data = {}
        for mod in modalities:
            worker_data[mod] = {}
            for skill in skills:
                col_name = f"{skill}_{mod}"
                if col_name in row.index:
                    try:
                        value = parse_value(row[col_name])
                        worker_data[mod][skill] = value
                    except ValueError as e:
                        print(f"  Warning: {worker_name}.{col_name}: {e}")
                        worker_data[mod][skill] = 0
                        stats['errors'] += 1
                else:
                    worker_data[mod][skill] = 0

        new_roster[worker_name] = worker_data

        if is_update:
            stats['updated'] += 1
        else:
            stats['added'] += 1

    if save_roster(new_roster, roster_path):
        print(f"Import complete:")
        print(f"  Added:   {stats['added']}")
        print(f"  Updated: {stats['updated']}")
        if stats['skipped']:
            print(f"  Skipped: {stats['skipped']}")
        if stats['errors']:
            print(f"  Errors:  {stats['errors']}")

    return stats


def validate_csv(csv_path: str) -> bool:
    """Validate a CSV file before import."""
    skills, modalities = load_config()

    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        return False

    # Try to read the file
    df = None
    for encoding in ['utf-8-sig', 'utf-8', 'latin1', 'cp1252']:
        try:
            df = pd.read_csv(csv_path, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    if df is None:
        print("Error: Could not read file")
        return False

    print(f"File: {csv_path}")
    print(f"Workers: {len(df)}")

    # Check Worker column
    if 'Worker' not in df.columns:
        print("Error: Missing 'Worker' column")
        return False

    # Check columns
    expected_cols = set()
    for mod in modalities:
        for skill in skills:
            expected_cols.add(f"{skill}_{mod}")

    found_cols = set(df.columns) - {'Worker'}
    missing = expected_cols - found_cols
    extra = found_cols - expected_cols

    print(f"Expected columns: {len(expected_cols)}")
    print(f"Found columns: {len(found_cols & expected_cols)}")

    if missing:
        print(f"Missing columns ({len(missing)}): {list(missing)[:5]}...")
    if extra:
        print(f"Extra columns (ignored): {list(extra)[:5]}...")

    # Validate values
    errors = []
    for col in found_cols & expected_cols:
        for idx, val in df[col].items():
            try:
                parse_value(val)
            except ValueError:
                worker = df.at[idx, 'Worker']
                errors.append(f"{worker}.{col}: '{val}'")

    if errors:
        print(f"\nInvalid values ({len(errors)}):")
        for err in errors[:10]:
            print(f"  {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
        return False

    print("\nValidation: PASSED")
    return True


def show_preview(roster_path: str = DEFAULT_ROSTER_FILE):
    """Show a preview of the roster data."""
    skills, modalities = load_config()
    roster = load_roster(roster_path)

    if not roster:
        print("Roster is empty or not found")
        return

    print(f"Roster: {roster_path}")
    print(f"Workers: {len(roster)}")
    print(f"Skills: {skills}")
    print(f"Modalities: {modalities}")
    print(f"Total combinations: {len(skills) * len(modalities)} per worker")
    print()

    # Show first 5 workers
    print("Preview (first 5 workers):")
    print("-" * 60)

    for i, (worker_name, worker_data) in enumerate(roster.items()):
        if i >= 5:
            break

        print(f"\n{worker_name}:")

        if worker_data and isinstance(next(iter(worker_data.values()), None), dict):
            for mod in modalities:
                mod_skills = worker_data.get(mod, {})
                active = [s for s, v in mod_skills.items() if v == 1]
                weighted = [s for s, v in mod_skills.items() if v == 2]
                if active or weighted:
                    parts = []
                    if active:
                        parts.append(f"active: {', '.join(active)}")
                    if weighted:
                        parts.append(f"weighted: {', '.join(weighted)}")
                    print(f"  {mod}: {'; '.join(parts)}")


def main():
    parser = argparse.ArgumentParser(
        description='Weight Roster CSV Import/Export Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Export command
    export_parser = subparsers.add_parser('export', help='Export roster to CSV')
    export_parser.add_argument('output', nargs='?', help='Output CSV file path')
    export_parser.add_argument('--roster', default=DEFAULT_ROSTER_FILE, help='Roster JSON file')

    # Import command
    import_parser = subparsers.add_parser('import', help='Import roster from CSV')
    import_parser.add_argument('input', help='Input CSV file path')
    import_parser.add_argument('--mode', choices=['replace', 'merge', 'add_only'],
                               default='replace', help='Merge mode (default: replace)')
    import_parser.add_argument('--roster', default=DEFAULT_ROSTER_FILE, help='Roster JSON file')

    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate a CSV file')
    validate_parser.add_argument('input', help='CSV file to validate')

    # Preview command
    preview_parser = subparsers.add_parser('preview', help='Preview roster data')
    preview_parser.add_argument('--roster', default=DEFAULT_ROSTER_FILE, help='Roster JSON file')

    args = parser.parse_args()

    if args.command == 'export':
        export_to_csv(args.output, args.roster)
    elif args.command == 'import':
        import_from_csv(args.input, args.mode, args.roster)
    elif args.command == 'validate':
        sys.exit(0 if validate_csv(args.input) else 1)
    elif args.command == 'preview':
        show_preview(args.roster)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
