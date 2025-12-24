#!/usr/bin/env python3
"""Export and import examination values (Skill×Modality weights) to/from CSV.

This standalone script allows admins to:
1. EXPORT: Generate CSV showing exam values from config
2. IMPORT: Generate YAML template entries from CSV to paste into config.yaml

Modes:
- auto:   Smart mode - export combi, import auto-detects format (default)
- single: Export/import skill weights and modality factors separately
- combi:  Export/import combined Skill×Modality values

Usage:
    # Export in combi mode (default) - combined values
    python exam_values.py export --config config.yaml --output exam_values.csv

    # Export in single mode - separate skill weights and modality factors
    python exam_values.py export --mode single --config config.yaml --output exam_values.csv

    # Import with smart detection to minimize config
    python exam_values.py import --input exam_values.csv --config config.yaml --output template.yaml

Notes:
- Default weight = skill.weight × modality.factor
- skill_modality_overrides in config.yaml can override specific combinations
- Import analyzes patterns to minimize config (prefer base weights over overrides)
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


DEFAULT_SKILLS = [
    "Notfall", "Privat", "Gyn", "Päd", "MSK",
    "Abdomen", "Chest", "Cardvask", "Uro"
]
DEFAULT_MODALITIES = ["ct", "mr", "xray", "mammo"]
TOLERANCE = 0.005  # Tolerance for float comparison


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load config.yaml and return parsed dict."""
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise SystemExit(f"Failed to parse YAML: {e}")


def get_skills(config: Dict[str, Any]) -> List[str]:
    """Extract skill names from config, preserving order."""
    skills_config = config.get("skills", {})
    if skills_config:
        sorted_skills = sorted(
            skills_config.items(),
            key=lambda x: x[1].get("display_order", 999)
        )
        return [s[0] for s in sorted_skills]
    return DEFAULT_SKILLS


def get_modalities(config: Dict[str, Any]) -> List[str]:
    """Extract modality keys from config."""
    modalities_config = config.get("modalities", {})
    if modalities_config:
        return list(modalities_config.keys())
    return DEFAULT_MODALITIES


def get_skill_weight(skill: str, config: Dict[str, Any]) -> float:
    """Get skill weight from config."""
    return config.get("skills", {}).get(skill, {}).get("weight", 1.0)


def get_modality_factor(modality: str, config: Dict[str, Any]) -> float:
    """Get modality factor from config."""
    return config.get("modalities", {}).get(modality, {}).get("factor", 1.0)


def calculate_exam_value(skill: str, modality: str, config: Dict[str, Any]) -> float:
    """Calculate the exam value (weight) for a Skill×Modality combination."""
    overrides = config.get("skill_modality_overrides", {})

    # Check for explicit override first
    if modality in overrides and skill in overrides[modality]:
        return float(overrides[modality][skill])

    # Calculate default: skill.weight × modality.factor
    return get_skill_weight(skill, config) * get_modality_factor(modality, config)


def format_value(value: float) -> str:
    """Format float value, stripping trailing zeros."""
    return f"{value:.3f}".rstrip('0').rstrip('.')


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def export_single_mode(config_path: Path, output_path: Path) -> None:
    """Export skill weights and modality factors separately (single mode).

    CSV format:
        type,name,weight
        skill,Notfall,1.1
        skill,MSK,0.8
        modality,ct,1.0
        modality,mr,1.2
    """
    config = load_config(config_path)
    skills = get_skills(config)
    modalities = get_modalities(config)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["type", "name", "weight"])

        # Skill weights
        for skill in skills:
            weight = get_skill_weight(skill, config)
            writer.writerow(["skill", skill, format_value(weight)])

        # Modality factors
        for modality in modalities:
            factor = get_modality_factor(modality, config)
            writer.writerow(["modality", modality, format_value(factor)])

    print(f"Exported {len(skills)} skill weights + {len(modalities)} modality factors")
    print(f"Mode: single (separate weights and factors)")
    print(f"Written to {output_path}")


def export_combi_mode(config_path: Path, output_path: Path) -> None:
    """Export combined Skill×Modality values (combi mode).

    CSV format: skill as rows, modalities as columns
    """
    config = load_config(config_path)
    skills = get_skills(config)
    modalities = get_modalities(config)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["skill"] + modalities)

        for skill in skills:
            row = [skill]
            for modality in modalities:
                value = calculate_exam_value(skill, modality, config)
                row.append(format_value(value))
            writer.writerow(row)

    print(f"Exported {len(skills)} skills × {len(modalities)} modalities")
    print(f"Mode: combi (combined Skill×Modality values)")
    print(f"Written to {output_path}")


# =============================================================================
# IMPORT FUNCTIONS
# =============================================================================

def detect_csv_format(fieldnames: List[str]) -> str:
    """Detect CSV format: 'single' or 'combi'."""
    if set(fieldnames) == {"type", "name", "weight"}:
        return "single"
    if "skill" in [f.lower() for f in fieldnames]:
        return "combi"
    raise SystemExit(f"Unknown CSV format. Headers: {fieldnames}")


def import_single_mode(
    rows: List[Dict[str, str]],
    config: Dict[str, Any],
    input_path: Path
) -> Dict[str, Any]:
    """Import from single-mode CSV (skill weights + modality factors)."""
    skill_weights: Dict[str, float] = {}
    modality_factors: Dict[str, float] = {}

    for row in rows:
        row_type = row.get("type", "").strip().lower()
        name = row.get("name", "").strip()
        weight_str = row.get("weight", "").strip()

        if not name or not weight_str:
            continue

        try:
            weight = float(weight_str)
        except ValueError:
            print(f"Warning: Invalid weight '{weight_str}' for {name}, skipping")
            continue

        if row_type == "skill":
            skill_weights[name] = weight
        elif row_type == "modality":
            modality_factors[name] = weight

    # Build result - only include changes from current config
    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(input_path),
        "mode": "single",
    }

    # Check which skill weights changed
    skills_changed = {}
    for skill, new_weight in skill_weights.items():
        current = get_skill_weight(skill, config)
        if abs(new_weight - current) > TOLERANCE:
            skills_changed[skill] = new_weight

    # Check which modality factors changed
    modalities_changed = {}
    for modality, new_factor in modality_factors.items():
        current = get_modality_factor(modality, config)
        if abs(new_factor - current) > TOLERANCE:
            modalities_changed[modality] = new_factor

    if skills_changed:
        result["skill_weight_updates"] = {
            "notes": "Update these in config.yaml under skills.<name>.weight",
            "changes": skills_changed
        }

    if modalities_changed:
        result["modality_factor_updates"] = {
            "notes": "Update these in config.yaml under modalities.<name>.factor",
            "changes": modalities_changed
        }

    if not skills_changed and not modalities_changed:
        result["notes"] = "No changes detected - all values match current config"
    else:
        result["notes"] = (
            f"Found {len(skills_changed)} skill weight changes, "
            f"{len(modalities_changed)} modality factor changes"
        )

    print(f"Mode: single")
    print(f"Skill weight changes: {len(skills_changed)}")
    print(f"Modality factor changes: {len(modalities_changed)}")

    return result


def import_combi_mode(
    rows: List[Dict[str, str]],
    fieldnames: List[str],
    config: Dict[str, Any],
    input_path: Path
) -> Dict[str, Any]:
    """Import from combi-mode CSV with smart detection to minimize config.

    Strategy:
    1. Try to find optimal skill weights and modality factors that explain the data
    2. Only generate overrides for values that can't be explained by base weights
    """
    modalities = [col for col in fieldnames if col.lower() != "skill"]

    # Parse all values into a matrix
    matrix: Dict[str, Dict[str, float]] = {}  # skill -> modality -> value
    skills = []

    for row in rows:
        skill = row.get("skill", "").strip()
        if not skill:
            continue
        skills.append(skill)
        matrix[skill] = {}

        for modality in modalities:
            val_str = row.get(modality, "").strip()
            if val_str:
                try:
                    matrix[skill][modality] = float(val_str)
                except ValueError:
                    pass

    if not skills or not modalities:
        raise SystemExit("No valid data in CSV")

    # Try to decompose into skill weights × modality factors
    # Use first modality as reference (factor = 1.0) to derive skill weights
    ref_modality = modalities[0]

    # Derive skill weights from reference modality column
    derived_skill_weights: Dict[str, float] = {}
    for skill in skills:
        if ref_modality in matrix.get(skill, {}):
            derived_skill_weights[skill] = matrix[skill][ref_modality]

    # Derive modality factors by comparing ratios across all skills
    derived_modality_factors: Dict[str, float] = {ref_modality: 1.0}

    for modality in modalities[1:]:
        ratios = []
        for skill in skills:
            if skill in derived_skill_weights and derived_skill_weights[skill] > 0:
                if modality in matrix.get(skill, {}):
                    ratio = matrix[skill][modality] / derived_skill_weights[skill]
                    ratios.append(ratio)

        if ratios:
            # Use median ratio as the modality factor (robust to outliers)
            ratios.sort()
            derived_modality_factors[modality] = ratios[len(ratios) // 2]

    # Calculate what can be explained by derived weights/factors
    # and what needs overrides
    overrides: Dict[str, Dict[str, float]] = {}

    for skill in skills:
        skill_weight = derived_skill_weights.get(skill, 1.0)
        for modality in modalities:
            if modality not in matrix.get(skill, {}):
                continue

            actual = matrix[skill][modality]
            expected = skill_weight * derived_modality_factors.get(modality, 1.0)

            if abs(actual - expected) > TOLERANCE:
                if modality not in overrides:
                    overrides[modality] = {}
                overrides[modality][skill] = actual

    # Compare derived values to current config to find what changed
    skill_weight_changes = {}
    for skill, weight in derived_skill_weights.items():
        current = get_skill_weight(skill, config)
        if abs(weight - current) > TOLERANCE:
            skill_weight_changes[skill] = weight

    modality_factor_changes = {}
    for modality, factor in derived_modality_factors.items():
        current = get_modality_factor(modality, config)
        if abs(factor - current) > TOLERANCE:
            modality_factor_changes[modality] = factor

    # Build result
    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(input_path),
        "mode": "combi (smart decomposition)",
    }

    # Summarize what we found
    total_overrides = sum(len(v) for v in overrides.values())
    total_cells = len(skills) * len(modalities)

    result["analysis"] = {
        "total_cells": total_cells,
        "explained_by_base_weights": total_cells - total_overrides,
        "requires_overrides": total_overrides,
        "reference_modality": f"{ref_modality} (factor=1.0)",
    }

    # Include changes if any
    if skill_weight_changes:
        result["skill_weight_updates"] = {
            "notes": "Update in config.yaml: skills.<name>.weight",
            "changes": {k: float(f"{v:.3f}") for k, v in skill_weight_changes.items()}
        }

    if modality_factor_changes:
        result["modality_factor_updates"] = {
            "notes": "Update in config.yaml: modalities.<name>.factor",
            "changes": {k: float(f"{v:.3f}") for k, v in modality_factor_changes.items()}
        }

    if overrides:
        result["skill_modality_overrides"] = {
            mod: {sk: float(f"{v:.3f}") for sk, v in skills_dict.items()}
            for mod, skills_dict in overrides.items()
        }
        result["overrides_notes"] = (
            "These values cannot be explained by skill.weight × modality.factor. "
            "Copy to config.yaml under skill_modality_overrides."
        )

    if not skill_weight_changes and not modality_factor_changes and not overrides:
        result["notes"] = "No changes needed - all values match current config"
    else:
        parts = []
        if skill_weight_changes:
            parts.append(f"{len(skill_weight_changes)} skill weights")
        if modality_factor_changes:
            parts.append(f"{len(modality_factor_changes)} modality factors")
        if overrides:
            parts.append(f"{total_overrides} overrides")
        result["notes"] = f"Changes: {', '.join(parts)}"

    print(f"Mode: combi (smart decomposition)")
    print(f"Reference modality: {ref_modality} (factor=1.0)")
    print(f"Skill weight changes: {len(skill_weight_changes)}")
    print(f"Modality factor changes: {len(modality_factor_changes)}")
    print(f"Overrides needed: {total_overrides} / {total_cells} cells")

    return result


def import_from_csv(input_path: Path, output_path: Path, config_path: Path | None) -> None:
    """Import exam values from CSV and generate YAML template entries."""
    if not input_path.exists():
        raise SystemExit(f"Input CSV not found: {input_path}")

    config: Dict[str, Any] = {}
    if config_path and config_path.exists():
        config = load_config(config_path)

    with input_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        raise SystemExit("CSV file is empty")

    # Auto-detect format
    csv_format = detect_csv_format(fieldnames)
    print(f"Detected CSV format: {csv_format}")

    if csv_format == "single":
        result = import_single_mode(rows, config, input_path)
    else:
        result = import_combi_mode(rows, fieldnames, config, input_path)

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, allow_unicode=True)

    print(f"Template written to {output_path}")


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export/import examination values (Skill×Modality weights)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  auto    Smart mode - export combi, import auto-detects (default)
  single  Export/import skill weights and modality factors separately
  combi   Export/import combined Skill×Modality values

Examples:
    # Export (auto mode = combi)
    python exam_values.py export -c config.yaml -o exam_values.csv

    # Export separate weights/factors (single mode)
    python exam_values.py export --mode single -c config.yaml -o weights.csv

    # Import (auto-detects CSV format, smart decomposition)
    python exam_values.py import -i exam_values.csv -c config.yaml -o template.yaml
"""
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export subcommand
    export_parser = subparsers.add_parser(
        "export",
        help="Export exam values from config.yaml to CSV"
    )
    export_parser.add_argument(
        "--mode", "-m",
        choices=["auto", "single", "combi"],
        default="auto",
        help="Export mode: auto (smart), single (weights+factors), combi (combined)"
    )
    export_parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)"
    )
    export_parser.add_argument(
        "--output", "-o",
        default="exam_values.csv",
        help="Output CSV file path (default: exam_values.csv)"
    )

    # Import subcommand
    import_parser = subparsers.add_parser(
        "import",
        help="Import exam values from CSV and generate YAML template"
    )
    import_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input CSV file path"
    )
    import_parser.add_argument(
        "--output", "-o",
        default="exam_values_template.yaml",
        help="Output YAML template file (default: exam_values_template.yaml)"
    )
    import_parser.add_argument(
        "--config", "-c",
        default=None,
        help="Optional: existing config.yaml for delta detection"
    )

    args = parser.parse_args()

    if args.command == "export":
        config_path = Path(args.config)
        output_path = Path(args.output)

        if args.mode == "single":
            export_single_mode(config_path, output_path)
        else:  # auto or combi
            export_combi_mode(config_path, output_path)

    elif args.command == "import":
        import_from_csv(
            input_path=Path(args.input),
            output_path=Path(args.output),
            config_path=Path(args.config) if args.config else None
        )


if __name__ == "__main__":
    main()
