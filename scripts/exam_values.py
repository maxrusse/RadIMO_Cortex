#!/usr/bin/env python3
"""Export and import examination values (Skill×Modality weights) to/from CSV.

This standalone script allows admins to:
1. EXPORT: Generate CSV showing exam values from config
2. IMPORT: Generate YAML template entries from CSV to paste into config.yaml

Usage:
    # Export current values to CSV
    python exam_values.py export --config config.yaml --output exam_values.csv

    # Import from CSV - auto-detects format and minimizes config
    python exam_values.py import --input exam_values.csv --config config.yaml --output template.yaml

CSV Formats (auto-detected on import):
    Single format: type,name,weight (skill weights + modality factors)
    Combi format:  skill,ct,mr,... (combined Skill×Modality values)

Notes:
- Default weight = skill.weight × modality.factor
- Import uses smart decomposition to minimize config changes
- Prefers base weight/factor updates over individual overrides
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml


DEFAULT_SKILLS = [
    "Notfall", "Privat", "Gyn", "Päd", "MSK",
    "Abdomen", "Chest", "Cardvask", "Uro"
]
DEFAULT_MODALITIES = ["ct", "mr", "xray", "mammo"]
TOLERANCE = 0.005


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

    if modality in overrides and skill in overrides[modality]:
        return float(overrides[modality][skill])

    return get_skill_weight(skill, config) * get_modality_factor(modality, config)


def format_value(value: float) -> str:
    """Format float value, stripping trailing zeros."""
    return f"{value:.3f}".rstrip('0').rstrip('.')


# =============================================================================
# EXPORT
# =============================================================================

def export_to_csv(config_path: Path, output_path: Path) -> None:
    """Export exam values from config to CSV (combi format)."""
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

    print(f"Exported {len(skills)} skills × {len(modalities)} modalities to {output_path}")


# =============================================================================
# IMPORT
# =============================================================================

def detect_csv_format(fieldnames: List[str]) -> str:
    """Detect CSV format: 'single' or 'combi'."""
    if set(fieldnames) == {"type", "name", "weight"}:
        return "single"
    if "skill" in [f.lower() for f in fieldnames]:
        return "combi"
    raise SystemExit(f"Unknown CSV format. Headers: {fieldnames}")


def import_single_format(
    rows: List[Dict[str, str]],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Import from single-format CSV (skill weights + modality factors)."""
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
            continue

        if row_type == "skill":
            skill_weights[name] = weight
        elif row_type == "modality":
            modality_factors[name] = weight

    # Find changes from current config
    skill_changes = {
        s: w for s, w in skill_weights.items()
        if abs(w - get_skill_weight(s, config)) > TOLERANCE
    }
    modality_changes = {
        m: f for m, f in modality_factors.items()
        if abs(f - get_modality_factor(m, config)) > TOLERANCE
    }

    return {
        "skill_weights": skill_changes,
        "modality_factors": modality_changes,
        "overrides": {}
    }


def import_combi_format(
    rows: List[Dict[str, str]],
    fieldnames: List[str],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Import from combi-format CSV with smart decomposition."""
    modalities = [col for col in fieldnames if col.lower() != "skill"]

    # Parse values into matrix
    matrix: Dict[str, Dict[str, float]] = {}
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

    # Use first modality as reference (factor = 1.0) to derive skill weights
    ref_modality = modalities[0]

    # Derive skill weights from reference column
    derived_skill_weights: Dict[str, float] = {}
    for skill in skills:
        if ref_modality in matrix.get(skill, {}):
            derived_skill_weights[skill] = matrix[skill][ref_modality]

    # Derive modality factors from ratios
    derived_modality_factors: Dict[str, float] = {ref_modality: 1.0}

    for modality in modalities[1:]:
        ratios = []
        for skill in skills:
            if skill in derived_skill_weights and derived_skill_weights[skill] > 0:
                if modality in matrix.get(skill, {}):
                    ratio = matrix[skill][modality] / derived_skill_weights[skill]
                    ratios.append(ratio)

        if ratios:
            ratios.sort()
            derived_modality_factors[modality] = ratios[len(ratios) // 2]

    # Find overrides (values that can't be explained by base weights)
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

    # Find changes from current config
    skill_changes = {
        s: w for s, w in derived_skill_weights.items()
        if abs(w - get_skill_weight(s, config)) > TOLERANCE
    }
    modality_changes = {
        m: f for m, f in derived_modality_factors.items()
        if abs(f - get_modality_factor(m, config)) > TOLERANCE
    }

    return {
        "skill_weights": skill_changes,
        "modality_factors": modality_changes,
        "overrides": overrides
    }


def import_from_csv(input_path: Path, output_path: Path, config_path: Path | None) -> None:
    """Import exam values from CSV and generate minimal config template."""
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

    # Auto-detect and process
    csv_format = detect_csv_format(fieldnames)

    if csv_format == "single":
        changes = import_single_format(rows, config)
    else:
        changes = import_combi_format(rows, fieldnames, config)

    # Build minimal result
    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(input_path),
    }

    has_changes = False

    if changes["skill_weights"]:
        has_changes = True
        result["skills"] = {
            skill: {"weight": float(f"{w:.3f}")}
            for skill, w in changes["skill_weights"].items()
        }

    if changes["modality_factors"]:
        has_changes = True
        result["modalities"] = {
            mod: {"factor": float(f"{f:.3f}")}
            for mod, f in changes["modality_factors"].items()
        }

    if changes["overrides"]:
        has_changes = True
        result["skill_modality_overrides"] = {
            mod: {sk: float(f"{v:.3f}") for sk, v in skills_dict.items()}
            for mod, skills_dict in changes["overrides"].items()
        }

    if not has_changes:
        result["notes"] = "No changes needed - all values match current config"
    else:
        parts = []
        if changes["skill_weights"]:
            parts.append(f"{len(changes['skill_weights'])} skill weights")
        if changes["modality_factors"]:
            parts.append(f"{len(changes['modality_factors'])} modality factors")
        if changes["overrides"]:
            n = sum(len(v) for v in changes["overrides"].values())
            parts.append(f"{n} overrides")
        result["notes"] = f"Merge into config.yaml: {', '.join(parts)}"

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, sort_keys=False, allow_unicode=True)

    print(f"Processed: {input_path}")
    if has_changes:
        print(f"Changes: {result['notes'].replace('Merge into config.yaml: ', '')}")
    else:
        print("No changes needed")
    print(f"Written to {output_path}")


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export/import examination values (Skill×Modality weights)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Export current values
    python exam_values.py export -c config.yaml -o exam_values.csv

    # Import and generate minimal config template
    python exam_values.py import -i exam_values.csv -c config.yaml -o template.yaml
"""
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export
    export_parser = subparsers.add_parser("export", help="Export exam values to CSV")
    export_parser.add_argument("--config", "-c", default="config.yaml", help="Path to config.yaml")
    export_parser.add_argument("--output", "-o", default="exam_values.csv", help="Output CSV file")

    # Import
    import_parser = subparsers.add_parser("import", help="Import from CSV to YAML template")
    import_parser.add_argument("--input", "-i", required=True, help="Input CSV file")
    import_parser.add_argument("--output", "-o", default="exam_values_template.yaml", help="Output YAML file")
    import_parser.add_argument("--config", "-c", default=None, help="Existing config.yaml for comparison")

    args = parser.parse_args()

    if args.command == "export":
        export_to_csv(Path(args.config), Path(args.output))
    elif args.command == "import":
        import_from_csv(
            Path(args.input),
            Path(args.output),
            Path(args.config) if args.config else None
        )


if __name__ == "__main__":
    main()
