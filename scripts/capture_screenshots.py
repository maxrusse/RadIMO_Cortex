"""
Capture full-page screenshots for RadIMO training documentation using Playwright.

Default flow:
1) Prepare deterministic demo data via scripts/apply_demo_data.py.
2) Start local Flask server on 127.0.0.1:5050.
3) Capture stateful scene screenshots into _docs/screenshots/<timestamped_dir>.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "config.yaml").open("r", encoding="utf-8") as _config_file:
    APP_CONFIG = yaml.safe_load(_config_file) or {}

ADMIN_PASSWORD = str(APP_CONFIG.get("admin_password", ""))
ADMIN_PROTECTION_ENABLED = bool(APP_CONFIG.get("admin_access_protection_enabled", True))
ASSIGNMENT_CLICK_PLAN = [
    ("/api/ct/notfall", 24),
    ("/api/ct/notfall/strict", 8),
    ("/api/mr/notfall", 16),
    ("/api/mr/privat", 20),
    ("/api/mr/privat/strict", 8),
    ("/api/xray/privat", 18),
    ("/api/xray/privat/strict", 8),
    ("/api/mammo/privat", 14),
    ("/api/mammo/privat/strict", 6),
]


SCENES_TRAINING: list[dict[str, str]] = [
    {
        "name": "01_dashboard_ct_overview",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "purpose": "CT dashboard baseline with skill buttons and hints.",
    },
    {
        "name": "02_dashboard_ct_after_assignments",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "action": "dashboard_assignments",
        "purpose": "Dashboard after normal and strict assignments (result + last assignment visible).",
    },
    {
        "name": "03_dashboard_ct_strict_focus",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "action": "dashboard_strict",
        "purpose": "Dashboard strict-only assignment example for no-fallback training.",
    },
    {
        "name": "04_by_skill_abd_onco_overview",
        "path": "/by-skill?skill=aou",
        "wait_for": "#buttonGrid",
        "purpose": "Skill-centric routing view for AOU.",
    },
    {
        "name": "05_by_skill_abd_onco_special_task",
        "path": "/by-skill?skill=aou",
        "wait_for": "#buttonGrid",
        "action": "by_skill_special_task",
        "purpose": "Special task assignment (Organ Seg) from skill view.",
    },
    {
        "name": "06_timetable_ct_notfall_filtered",
        "path": "/timetable?modality=ct&skill=notfall",
        "wait_for": "#timeline-grid",
        "purpose": "Timetable filtered to CT + Notfall for targeted schedule review.",
    },
    {
        "name": "07_upload_master_status_loaded",
        "path": "/upload",
        "wait_for": "#master-status",
        "purpose": "Admin upload page with loaded Master CSV status.",
    },
    {
        "name": "08_skill_roster_selected_worker",
        "path": "/skill-roster",
        "wait_for": "#workerListContainer",
        "action": "skill_roster_select_worker",
        "purpose": "Skill roster detail panel for a selected worker.",
    },
    {
        "name": "09_prep_today_filtered",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "action": "prep_today_filtered",
        "purpose": "Today prep view with modality/skill filters and hide-zero enabled.",
    },
    {
        "name": "10_prep_today_quick_edit_mode",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "action": "prep_today_edit_mode",
        "purpose": "Today prep in quick-edit mode for in-day adjustment training.",
    },
    {
        "name": "11_prep_tomorrow_filtered",
        "path": "/prep-tomorrow",
        "wait_for": "#table-body-tomorrow",
        "action": "prep_tomorrow_filtered",
        "purpose": "Tomorrow prep with focused filters and staged target date context.",
    },
    {
        "name": "12_worker_load_simple",
        "path": "/worker-load",
        "wait_for": "#tbody-global",
        "purpose": "Worker load simple mode (global + modality + skill totals).",
    },
    {
        "name": "13_worker_load_advanced_relative",
        "path": "/worker-load",
        "wait_for": "#tbody-global",
        "action": "worker_load_advanced_relative",
        "purpose": "Worker load advanced mode with relative coloring and filters.",
    },
    {
        "name": "14_button_weights_normal",
        "path": "/button-weights",
        "wait_for": "#weightMatrixBody",
        "purpose": "Weight matrix in normal mode including special task weights.",
    },
    {
        "name": "15_button_weights_strict",
        "path": "/button-weights",
        "wait_for": "#weightMatrixBody",
        "action": "button_weights_strict",
        "purpose": "Weight matrix strict mode for specialist-only routing configuration.",
    },
]

SCENES_TUTORIAL: list[dict[str, str]] = [
    {
        "name": "01_step_dashboard_ct_open",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "purpose": "Step 1: Open CT dashboard and identify assignment controls.",
    },
    {
        "name": "02_step_dashboard_ct_assign_notfall",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "action": "dashboard_assign_notfall_once",
        "purpose": "Step 2: Trigger one Notfall assignment from modality dashboard.",
    },
    {
        "name": "03_step_dashboard_ct_assign_privat_strict",
        "path": "/?modality=ct",
        "wait_for": "#buttonGrid",
        "action": "dashboard_assign_privat_strict_once",
        "purpose": "Step 3: Trigger strict Privat assignment (no fallback).",
    },
    {
        "name": "04_step_skill_view_notfall_open",
        "path": "/by-skill?skill=notfall",
        "wait_for": "#buttonGrid",
        "purpose": "Step 4: Switch to skill-centric dashboard.",
    },
    {
        "name": "05_step_skill_view_notfall_assign_ct",
        "path": "/by-skill?skill=notfall",
        "wait_for": "#buttonGrid",
        "action": "by_skill_assign_ct_once",
        "purpose": "Step 5: Assign from skill dashboard via CT button.",
    },
    {
        "name": "06_step_timetable_ct_notfall",
        "path": "/timetable?modality=ct&skill=notfall",
        "wait_for": "#timeline-grid",
        "purpose": "Step 6: Verify schedule timeline for CT + Notfall.",
    },
    {
        "name": "07_step_upload_status",
        "path": "/upload",
        "wait_for": "#master-status",
        "purpose": "Step 7: Confirm Master CSV status in admin upload page.",
    },
    {
        "name": "08_step_skill_roster_select_worker",
        "path": "/skill-roster",
        "wait_for": "#workerListContainer",
        "action": "skill_roster_select_worker",
        "purpose": "Step 8: Open worker detail in Skill Matrix.",
    },
    {
        "name": "09_step_prep_today_open",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "purpose": "Step 9: Open Change Today view.",
    },
    {
        "name": "10_step_prep_today_apply_filters",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "action": "prep_today_filtered",
        "purpose": "Step 10: Apply modality/skill filters and hide-zero.",
    },
    {
        "name": "11_step_prep_today_quick_edit",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "action": "prep_today_edit_mode",
        "purpose": "Step 11: Enter Quick Edit mode for in-day changes.",
    },
    {
        "name": "12_step_prep_today_add_worker_modal",
        "path": "/prep-today",
        "wait_for": "#table-body-today",
        "action": "prep_today_open_add_worker_modal",
        "purpose": "Step 12: Open Add Worker dialog (today).",
    },
    {
        "name": "13_step_prep_tomorrow_open",
        "path": "/prep-tomorrow",
        "wait_for": "#table-body-tomorrow",
        "purpose": "Step 13: Open Prep Tomorrow view.",
    },
    {
        "name": "14_step_prep_tomorrow_apply_filters",
        "path": "/prep-tomorrow",
        "wait_for": "#table-body-tomorrow",
        "action": "prep_tomorrow_filtered",
        "purpose": "Step 14: Apply tomorrow filters to focus on work package.",
    },
    {
        "name": "15_step_prep_tomorrow_add_worker_modal",
        "path": "/prep-tomorrow",
        "wait_for": "#table-body-tomorrow",
        "action": "prep_tomorrow_open_add_worker_modal",
        "purpose": "Step 15: Open Add Worker dialog (tomorrow staging).",
    },
    {
        "name": "16_step_worker_load_simple",
        "path": "/worker-load",
        "wait_for": "#tbody-global",
        "purpose": "Step 16: Read simple load monitor totals.",
    },
    {
        "name": "17_step_worker_load_advanced",
        "path": "/worker-load",
        "wait_for": "#tbody-global",
        "action": "worker_load_advanced",
        "purpose": "Step 17: Switch to advanced load matrix.",
    },
    {
        "name": "18_step_worker_load_advanced_relative_filtered",
        "path": "/worker-load",
        "wait_for": "#tbody-global",
        "action": "worker_load_advanced_relative",
        "purpose": "Step 18: Apply relative color mode and filters in advanced view.",
    },
    {
        "name": "19_step_button_weights_normal",
        "path": "/button-weights",
        "wait_for": "#weightMatrixBody",
        "purpose": "Step 19: Review normal button weights.",
    },
    {
        "name": "20_step_button_weights_strict",
        "path": "/button-weights",
        "wait_for": "#weightMatrixBody",
        "action": "button_weights_strict",
        "purpose": "Step 20: Switch to strict weights for specialist-only routing.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture RadIMO screenshots.")
    parser.add_argument(
        "--scene-profile",
        choices=["training", "tutorial"],
        default="training",
        help="Scene pack to capture.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for local Flask app.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        help="Port for local Flask app.",
    )
    parser.add_argument(
        "--target-date",
        default=date.today().isoformat(),
        help="Target date for demo prep (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--preload-date",
        default=None,
        help="Preload date for demo prep (YYYY-MM-DD). Default: target + 1 day.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output folder for PNG files.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1920,
        help="Viewport width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="Viewport height.",
    )
    parser.add_argument(
        "--startup-timeout-sec",
        type=float,
        default=20.0,
        help="Server readiness timeout.",
    )
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Skip running scripts/apply_demo_data.py.",
    )
    parser.add_argument(
        "--no-simulate-clicks",
        action="store_true",
        help="Skip dummy assignment clicks before screenshots.",
    )
    return parser.parse_args()


def _wait_for_health(base_url: str, timeout_sec: float) -> None:
    deadline = time.time() + timeout_sec
    health_url = f"{base_url}/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Server did not become ready: {health_url}")


def _prepare_demo(py_exe: str, target_date: str, preload_date: str | None) -> None:
    cmd = [py_exe, str(ROOT / "scripts" / "apply_demo_data.py"), "--target-date", target_date]
    if preload_date:
        cmd.extend(["--preload-date", preload_date])
    subprocess.run(cmd, cwd=ROOT, check=True)


def _http_request(
    opener: urllib.request.OpenerDirector,
    url: str,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, dict | None]:
    req = urllib.request.Request(url=url, method=method, data=body)
    req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=10) as resp:
            raw = resp.read()
            data = json.loads(raw.decode("utf-8")) if raw else None
            return resp.status, data
    except urllib.error.HTTPError as e:
        raw = e.read()
        data = None
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                data = None
        return e.code, data


def _login_http_session(opener: urllib.request.OpenerDirector, base_url: str) -> None:
    if not ADMIN_PROTECTION_ENABLED or not ADMIN_PASSWORD:
        return

    body = urllib.parse.urlencode({"password": ADMIN_PASSWORD}).encode("utf-8")
    req = urllib.request.Request(
        url=f"{base_url}/login?modality=ct",
        method="POST",
        data=body,
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with opener.open(req, timeout=10) as resp:
        resp.read()


def _simulate_clicks(opener: urllib.request.OpenerDirector, base_url: str) -> None:
    # Make runs reproducible for screenshots by resetting usage counters first.
    reset_status, _ = _http_request(opener, f"{base_url}/api/usage-stats/reset", method="POST")
    if reset_status not in (200, 204):
        print(f"Warning: usage reset returned {reset_status}")

    success = 0
    failed = 0
    for path, count in ASSIGNMENT_CLICK_PLAN:
        for _ in range(count):
            status, payload = _http_request(opener, f"{base_url}{path}")
            if status == 200 and payload and payload.get("selected_person"):
                success += 1
            else:
                failed += 1

    stats_status, stats_payload = _http_request(opener, f"{base_url}/api/usage-stats/current")
    print(
        f"Simulated clicks: success={success}, failed={failed}, "
        f"stats_status={stats_status}, has_stats={bool(stats_payload)}"
    )


def _load_server_state(opener: urllib.request.OpenerDirector, base_url: str, preload_date: str) -> None:
    load_status, load_payload = _http_request(opener, f"{base_url}/load-today-from-master", method="POST")
    preload_status, preload_payload = _http_request(
        opener,
        f"{base_url}/preload-from-master",
        method="POST",
        body=json.dumps({"target_date": preload_date}).encode("utf-8"),
    )
    print(
        "Server load state: "
        f"load_today={load_status} success={bool(load_payload and load_payload.get('success'))}, "
        f"preload={preload_status} success={bool(preload_payload and preload_payload.get('success'))}"
    )


def _wait_for_rows(page: Any, selector: str) -> None:
    page.wait_for_selector(selector, timeout=60_000)
    page.wait_for_timeout(300)


def _click_if_exists(page: Any, selector: str, timeout_ms: int = 5_000) -> bool:
    locator = page.locator(selector)
    if locator.count() < 1:
        return False
    locator.first.click(timeout=timeout_ms)
    page.wait_for_timeout(250)
    return True


def _run_js_if_available(page: Any, fn_name: str, arg_literal: str | None = None) -> bool:
    if arg_literal is None:
        script = f"(() => (typeof {fn_name} === 'function' ? ({fn_name}(), true) : false))()"
    else:
        script = f"(() => (typeof {fn_name} === 'function' ? ({fn_name}({arg_literal}), true) : false))()"
    result = page.evaluate(script)
    page.wait_for_timeout(250)
    return bool(result)


def _wait_for_result_text(page: Any, timeout_ms: int = 10_000) -> None:
    try:
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#result');
                return Boolean(el && el.textContent && el.textContent.trim().length > 0);
            }""",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(350)


def _action_dashboard_assignments(page: Any) -> None:
    _click_if_exists(page, "#skill-btn-notfall")
    _click_if_exists(page, "#skill-btn-privat")
    _click_if_exists(page, "div[data-skill-slug='privat'] .skill-strict-btn")
    _wait_for_result_text(page)


def _action_dashboard_strict(page: Any) -> None:
    _click_if_exists(page, "div[data-skill-slug='privat'] .skill-strict-btn")
    _click_if_exists(page, "div[data-skill-slug='notfall'] .skill-strict-btn")
    _wait_for_result_text(page)


def _action_dashboard_assign_notfall_once(page: Any) -> None:
    _click_if_exists(page, "#skill-btn-notfall")
    _wait_for_result_text(page)


def _action_dashboard_assign_privat_strict_once(page: Any) -> None:
    _click_if_exists(page, "div[data-skill-slug='privat'] .skill-strict-btn")
    _wait_for_result_text(page)


def _action_by_skill_special_task(page: Any) -> None:
    if page.get_by_role("button", name="Organ Seg").count() > 0:
        page.get_by_role("button", name="Organ Seg").first.click(timeout=8_000)
    else:
        _click_if_exists(page, ".modality-button-wrapper .modality-main-btn")
    _wait_for_result_text(page)


def _action_by_skill_assign_ct_once(page: Any) -> None:
    _click_if_exists(page, "#mod-btn-ct")
    _wait_for_result_text(page)


def _action_skill_roster_select_worker(page: Any) -> None:
    _wait_for_rows(page, ".worker-item")
    _click_if_exists(page, ".worker-item")
    page.wait_for_selector("#workerDetailContent", timeout=10_000)
    page.wait_for_timeout(400)


def _action_prep_today_filtered(page: Any) -> None:
    _wait_for_rows(page, "#table-body-today tr")
    _click_if_exists(page, "#content-today .filter-bar .filter-btn[data-modality='ct']")
    _click_if_exists(page, "#content-today .filter-bar .filter-btn[data-skill='notfall']")
    _click_if_exists(page, "#filter-hide-zero-today")
    page.wait_for_timeout(700)


def _action_prep_today_edit_mode(page: Any) -> None:
    _wait_for_rows(page, "#table-body-today tr")
    _click_if_exists(page, "#edit-mode-btn-today")
    page.wait_for_timeout(700)


def _action_prep_today_open_add_worker_modal(page: Any) -> None:
    _wait_for_rows(page, "#table-body-today tr")
    opened = _run_js_if_available(page, "openAddWorkerModal", "'today'")
    if not opened:
        _click_if_exists(page, "#content-today button[onclick*=\"openAddWorkerModal('today')\"]")
    page.wait_for_selector("#edit-modal", timeout=10_000)
    page.wait_for_timeout(700)


def _action_prep_tomorrow_filtered(page: Any) -> None:
    _wait_for_rows(page, "#table-body-tomorrow tr")
    _click_if_exists(page, "#content-tomorrow .filter-bar .filter-btn[data-modality='mr']")
    _click_if_exists(page, "#content-tomorrow .filter-bar .filter-btn[data-skill='privat']")
    _click_if_exists(page, "#filter-hide-zero-tomorrow")
    page.wait_for_timeout(700)


def _action_prep_tomorrow_open_add_worker_modal(page: Any) -> None:
    _wait_for_rows(page, "#table-body-tomorrow tr")
    opened = _run_js_if_available(page, "openAddWorkerModal", "'tomorrow'")
    if not opened:
        _click_if_exists(page, "#content-tomorrow button[onclick*=\"openAddWorkerModal('tomorrow')\"]")
    page.wait_for_selector("#edit-modal", timeout=10_000)
    page.wait_for_timeout(700)


def _action_worker_load_advanced(page: Any) -> None:
    _wait_for_rows(page, "#tbody-global tr")
    _click_if_exists(page, ".mode-btn[data-mode='advanced']")
    page.wait_for_timeout(650)


def _action_worker_load_advanced_relative(page: Any) -> None:
    _wait_for_rows(page, "#tbody-global tr")
    _click_if_exists(page, ".mode-btn[data-mode='advanced']")
    _click_if_exists(page, ".color-btn[data-color='relative']")
    _click_if_exists(page, "#filter-bar .filter-btn[data-modality='ct']")
    _click_if_exists(page, "#filter-bar .filter-btn[data-skill='notfall']")
    _click_if_exists(page, "#filter-hide-zero")
    page.wait_for_timeout(700)


def _action_button_weights_strict(page: Any) -> None:
    _wait_for_rows(page, "#weightMatrixBody tr")
    _click_if_exists(page, "#mode-strict")
    page.wait_for_timeout(500)


def _write_manifest(out_dir: Path, manifest: list[dict[str, str]], scene_profile: str) -> None:
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    lines = [
        "# Screenshot Manifest",
        "",
        "Generated by `scripts/capture_screenshots.py` for documentation and user training.",
        f"",
        f"Scene profile: `{scene_profile}`",
        "",
    ]
    for item in manifest:
        lines.append(f"- `{item['file']}`: {item['purpose']} (route: `{item['path']}`)")
    lines.append("")
    lines.append(f"Total scenes: {len(manifest)}")
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _capture_pages(
    *,
    base_url: str,
    out_dir: Path,
    width: int,
    height: int,
    scenes: list[dict[str, str]],
    scene_profile: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    action_handlers: dict[str, Callable[[Any], None]] = {
        "dashboard_assignments": _action_dashboard_assignments,
        "dashboard_strict": _action_dashboard_strict,
        "dashboard_assign_notfall_once": _action_dashboard_assign_notfall_once,
        "dashboard_assign_privat_strict_once": _action_dashboard_assign_privat_strict_once,
        "by_skill_special_task": _action_by_skill_special_task,
        "by_skill_assign_ct_once": _action_by_skill_assign_ct_once,
        "skill_roster_select_worker": _action_skill_roster_select_worker,
        "prep_today_filtered": _action_prep_today_filtered,
        "prep_today_edit_mode": _action_prep_today_edit_mode,
        "prep_today_open_add_worker_modal": _action_prep_today_open_add_worker_modal,
        "prep_tomorrow_filtered": _action_prep_tomorrow_filtered,
        "prep_tomorrow_open_add_worker_modal": _action_prep_tomorrow_open_add_worker_modal,
        "worker_load_advanced": _action_worker_load_advanced,
        "worker_load_advanced_relative": _action_worker_load_advanced_relative,
        "button_weights_strict": _action_button_weights_strict,
    }
    manifest: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        if ADMIN_PROTECTION_ENABLED and ADMIN_PASSWORD:
            page.goto(f"{base_url}/login?modality=ct", wait_until="networkidle", timeout=60_000)
            password_input = page.locator("input[name='password']")
            if password_input.count() > 0:
                password_input.first.fill(ADMIN_PASSWORD)
                page.locator("button[type='submit']").first.click(timeout=10_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(300)

        for scene in scenes:
            name = scene["name"]
            path = scene["path"]
            wait_for = scene.get("wait_for")
            action = scene.get("action")
            purpose = scene["purpose"]

            page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=60_000)
            if wait_for:
                _wait_for_rows(page, wait_for)

            if action and action in action_handlers:
                action_handlers[action](page)

            page.wait_for_timeout(350)
            target = out_dir / f"{name}.png"
            page.screenshot(path=str(target), full_page=True)
            print(f"{target} ({target.stat().st_size} bytes)")
            manifest.append(
                {
                    "file": target.name,
                    "path": path,
                    "purpose": purpose,
                    "action": action or "",
                }
            )

        context.close()
        browser.close()
    _write_manifest(out_dir=out_dir, manifest=manifest, scene_profile=scene_profile)


def main() -> int:
    args = parse_args()
    py_exe = sys.executable
    base_url = f"http://{args.host}:{args.port}"
    if args.scene_profile == "tutorial":
        scenes = SCENES_TUTORIAL
        default_output_dir = ROOT.parent / "_docs" / "screenshots" / f"radimo_cortex_playwright_tutorial_{date.today().isoformat()}"
    else:
        scenes = SCENES_TRAINING
        default_output_dir = ROOT.parent / "_docs" / "screenshots" / f"radimo_cortex_playwright_training_{date.today().isoformat()}"
    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir
    target_dt = date.fromisoformat(args.target_date)
    preload_date = args.preload_date or (target_dt + timedelta(days=1)).isoformat()
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    if not args.skip_prepare:
        _prepare_demo(
            py_exe=py_exe,
            target_date=args.target_date,
            preload_date=preload_date,
        )

    server_cmd = [py_exe, "-m", "flask", "--app", "app", "run", "--host", args.host, "--port", str(args.port)]
    server_proc = subprocess.Popen(server_cmd, cwd=ROOT)
    try:
        _wait_for_health(base_url=base_url, timeout_sec=args.startup_timeout_sec)
        _login_http_session(opener, base_url=base_url)
        _load_server_state(opener=opener, base_url=base_url, preload_date=preload_date)
        if not args.no_simulate_clicks:
            _simulate_clicks(opener=opener, base_url=base_url)
        _capture_pages(
            scene_profile=args.scene_profile,
            scenes=scenes,
            base_url=base_url,
            out_dir=out_dir,
            width=args.width,
            height=args.height,
        )
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait(timeout=5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
