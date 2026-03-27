"""
Prepare deterministic demo data for local UI/screenshot workflows.

This script:
1) Writes uploads/master_medweb.csv with rich rows for target + preload date.
2) Writes a deterministic demo worker roster into data/worker_skill_roster.json.
3) Copies demo button weights to data/button_weights.json.
4) Optionally triggers load-today + preload-next-day via Flask test client.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
UPLOADS_DIR = ROOT / "uploads"
DATA_DIR = ROOT / "data"
MASTER_CSV_PATH = UPLOADS_DIR / "master_medweb.csv"
BUTTON_WEIGHTS_PATH = DATA_DIR / "button_weights.json"
WORKER_ROSTER_PATH = DATA_DIR / "worker_skill_roster.json"

DEMO_WEIGHTS_PATH = ROOT / "test_data" / "demo" / "button_weights_demo.json"
SKILLS = ["notfall", "privat", "gyn", "mhd", "aou", "cvt"]
MODALITIES = ["ct", "mr", "xray"]


DEMO_ACTIVITY_PLAN: list[tuple[str, list[str]]] = [
    ("Assistent Notfall", ["KM15", "HB16", "LV08"]),
    ("UNZ Assistent", ["MS11"]),
    ("OA CT", ["AK18"]),
    ("OA MR", ["CP20", "TN31"]),
    ("SBZ: SBZ Privatpatienten", ["TY33"]),
    ("OA / FA Chir", ["ER14", "FH19"]),
    ("Chir Assistent", ["XR41", "YK42"]),
    ("Assistent Gyn", ["MG17"]),
    ("SBZ: Abdomen/Onko/Uro", ["OB22"]),
    ("SBZ: Cardio/Vask/Thorax", ["PK12"]),
    ("SBZ: Abdomen/Onko/Uro", ["QL10"]),
    ("SBZ: Muskel-Skelett/Hals/Derma", ["RM13"]),
    ("SBZ: Muskel-Skelett/Hals/Derma", ["ST27"]),
    ("SBZ Spät Assistent", ["UV09"]),
    ("3. Dienst", ["WX07"]),
]

# Weekday-aware gap activities guarantee visible split/blocked schedule rows.
GAP_BY_WEEKDAY = {
    0: "Mult. Myelom Board (Mo 15:30)",
    1: "Emphysem-Board, Di 16:00 Uhr",
    2: "ILD-Board (Mi 15:00, 14-tägig)",
    3: "Uro-Board (Do 14:30)",
    4: "IPOK (Fr 13 Uhr, Konf.raum 5)",
    5: "SBZ Geräteassistenz",
    6: "SBZ Geräteassistenz",
}


def _next_workday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate

# Worker IDs are stable and map to realistic mixed skill distributions.
DEMO_WORKERS: list[dict[str, Any]] = [
    {
        "id": "KM15",
        "name": "Dr. Kora Meier (KM15)",
        "overrides": {"notfall_ct": 1, "notfall_mr": 1, "notfall_xray": 1, "privat_ct": -1},
    },
    {
        "id": "HB16",
        "name": "Dr. Hannes Berg (HB16)",
        "overrides": {"notfall_ct": 1, "notfall_mr": 1, "notfall_xray": 1},
    },
    {
        "id": "LV08",
        "name": "Dr. Lara Vogt (LV08)",
        "overrides": {"notfall_ct": 1, "notfall_mr": 1, "notfall_xray": 1},
    },
    {
        "id": "MS11",
        "name": "Dr. Milo Stein (MS11)",
        "overrides": {"notfall_ct": 1, "notfall_mr": 1, "notfall_xray": 1},
    },
    {"id": "AK18", "name": "Dr. Andrea Krause (AK18)", "overrides": {"privat_ct": 1}},
    {"id": "CP20", "name": "Dr. Claudia Peters (CP20)", "overrides": {"privat_mr": 1}},
    {"id": "TN31", "name": "Dr. Theo Noll (TN31)", "overrides": {"privat_mr": 1}},
    {"id": "TY33", "name": "Dr. Tilda Young (TY33)", "overrides": {"privat_ct": 1, "privat_mr": 1}},
    {"id": "ER14", "name": "Dr. Eva Richter (ER14)", "overrides": {"privat_xray": 1}},
    {"id": "FH19", "name": "Dr. Felix Hartmann (FH19)", "overrides": {"privat_xray": 1}},
    {
        "id": "XR41",
        "name": "Dr. Xenia Reuter (XR41)",
        "overrides": {"gyn_xray": 1, "aou_xray": 1, "cvt_xray": 1, "mhd_xray": 1, "notfall_xray": -1},
    },
    {
        "id": "YK42",
        "name": "Dr. Yann Kiefer (YK42)",
        "overrides": {"gyn_xray": 1, "aou_xray": 1, "cvt_xray": 1, "mhd_xray": 1, "notfall_xray": -1},
    },
    {
        "id": "MG17",
        "name": "Dr. Mara Grimm (MG17)",
        "modifier": 0.7,
        "overrides": {"gyn_ct": 1, "gyn_mr": 1, "gyn_xray": -1, "notfall_ct": -1},
    },
    {
        "id": "OB22",
        "name": "Dr. Olivia Brandt (OB22)",
        "modifier": 0.6,
        "overrides": {"aou_ct": 1, "aou_mr": "w"},
    },
    {"id": "PK12", "name": "Dr. Paul Koch (PK12)", "overrides": {"cvt_ct": 1, "cvt_mr": 1}},
    {"id": "QL10", "name": "Dr. Quentin Lang (QL10)", "overrides": {"aou_ct": 1, "aou_mr": 1}},
    {"id": "RM13", "name": "Dr. Rina Maurer (RM13)", "overrides": {"mhd_ct": 1, "mhd_mr": 1}},
    {"id": "ST27", "name": "Dr. Sven Thaler (ST27)", "overrides": {"mhd_ct": 1, "mhd_mr": 1, "mhd_xray": 1}},
    {"id": "UV09", "name": "Dr. Ute Vogler (UV09)", "overrides": {"notfall_mr": 0, "notfall_xray": 0}},
    {"id": "WX07", "name": "Dr. Willem Xander (WX07)", "overrides": {"notfall_xray": 1}},
    {
        "id": "GP40",
        "name": "Dr. Greta Pause (GP40)",
        "overrides": {"notfall_ct": -1, "notfall_mr": -1, "notfall_xray": -1},
    },
]


def _resolve_demo_weights() -> Path:
    if DEMO_WEIGHTS_PATH.exists():
        return DEMO_WEIGHTS_PATH
    raise FileNotFoundError(
        "Missing demo button weights. Expected: "
        f"{DEMO_WEIGHTS_PATH}"
    )


def _skill_modality_keys() -> list[str]:
    return [f"{skill}_{modality}" for skill in SKILLS for modality in MODALITIES]


def _build_worker_entry(*, full_name: str, modifier: float | None, overrides: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {key: 0 for key in _skill_modality_keys()}
    entry["full_name"] = full_name
    if modifier is not None:
        entry["modifier"] = float(modifier)
    for key, value in overrides.items():
        if key in entry:
            entry[key] = value
    return entry


def _build_worker_catalog() -> dict[str, dict[str, Any]]:
    return {w["id"]: w for w in DEMO_WORKERS}


def _gap_activity_for_day(day: date) -> str:
    return GAP_BY_WEEKDAY.get(day.weekday(), "SBZ Geräteassistenz")


def _write_demo_master_csv(target: date, preload: date) -> dict[str, int]:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    worker_catalog = _build_worker_catalog()
    rows: list[list[str]] = []

    # Activities intentionally map to rules already present in config.yaml.
    for current_day in (target, preload):
        ds = current_day.strftime("%d.%m.%Y")
        for activity, worker_ids in DEMO_ACTIVITY_PLAN:
            for worker_id in worker_ids:
                worker = worker_catalog[worker_id]
                rows.append([ds, activity, worker["name"], worker_id, "VM"])

        # Add one split-shift gap worker and one standalone gap worker.
        day_gap = _gap_activity_for_day(current_day)
        rows.append([ds, day_gap, worker_catalog["PK12"]["name"], "PK12", "VM"])
        rows.append([ds, day_gap, worker_catalog["GP40"]["name"], "GP40", "VM"])

    with MASTER_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Datum",
                "Beschreibung der Aktivität",
                "Name des Mitarbeiters",
                "Code des Mitarbeiters",
                "Tageszeit",
            ]
        )
        writer.writerows(rows)

    return {"row_count": len(rows), "worker_count": len(worker_catalog)}


def _write_demo_roster() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    roster: dict[str, dict[str, Any]] = {}
    for worker in DEMO_WORKERS:
        roster[worker["id"]] = _build_worker_entry(
            full_name=worker["name"],
            modifier=worker.get("modifier"),
            overrides=worker.get("overrides", {}),
        )
    WORKER_ROSTER_PATH.write_text(
        json.dumps(roster, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return len(roster)


def _copy_demo_weights() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    src = _resolve_demo_weights()
    shutil.copy2(src, BUTTON_WEIGHTS_PATH)
    return src


def _load_demo_state(preload: date) -> dict[str, Any]:
    from app import app

    with app.test_client() as client:
        load_today_resp = client.post("/load-today-from-master")
        preload_resp = client.post(
            "/preload-from-master",
            json={"target_date": preload.isoformat()},
        )
        return {
            "load_today": {
                "status_code": load_today_resp.status_code,
                "body": load_today_resp.get_json(silent=True),
            },
            "preload": {
                "status_code": preload_resp.status_code,
                "body": preload_resp.get_json(silent=True),
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare deterministic demo data.")
    parser.add_argument(
        "--target-date",
        type=str,
        default=date.today().isoformat(),
        help="Target date (YYYY-MM-DD) for today's live load.",
    )
    parser.add_argument(
        "--preload-date",
        type=str,
        default=None,
        help="Preload date (YYYY-MM-DD) for staged next day. Default: next workday after target.",
    )
    parser.add_argument(
        "--no-load",
        action="store_true",
        help="Do not call /load-today-from-master and /preload-from-master.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = date.fromisoformat(args.target_date)
    preload = (
        date.fromisoformat(args.preload_date)
        if args.preload_date
        else _next_workday(target)
    )
    if preload <= target:
        raise ValueError("preload-date must be after target-date")

    csv_stats = _write_demo_master_csv(target=target, preload=preload)
    roster_count = _write_demo_roster()
    weights_src = _copy_demo_weights()

    result: dict[str, Any] = {
        "master_csv_path": str(MASTER_CSV_PATH.relative_to(ROOT)),
        "master_csv_rows": csv_stats["row_count"],
        "button_weights_path": str(BUTTON_WEIGHTS_PATH.relative_to(ROOT)),
        "button_weights_source": str(weights_src.relative_to(ROOT)),
        "worker_roster_path": str(WORKER_ROSTER_PATH.relative_to(ROOT)),
        "worker_roster_size": roster_count,
        "target_date": target.isoformat(),
        "preload_date": preload.isoformat(),
    }

    if not args.no_load:
        result["load_result"] = _load_demo_state(preload=preload)

    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
