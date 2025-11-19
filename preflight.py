#!/usr/bin/env python3
"""Operational checklist to run before going live."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Tuple

try:
    import yaml
except ModuleNotFoundError as exc:
    print("PyYAML (yaml) wird benötigt, um die Preflight-Prüfungen zu starten.")
    print("Bitte 'pip install pyyaml' ausführen und den Befehl erneut starten.")
    raise SystemExit(1) from exc

from app import APP_CONFIG, DEFAULT_CONFIG

CheckResult = Tuple[str, str]


def _print_header() -> None:
    print("RadIMO preflight checklist")
    print("============================")


def _run_check(func: Callable[[], CheckResult]) -> CheckResult:
    status, detail = func()
    print(f"[{status}] {detail}")
    return status, detail


def check_config_yaml() -> CheckResult:
    config_path = Path('config.yaml')
    if not config_path.exists():
        return 'WARN', "config.yaml fehlt – es werden ausschließlich Defaults genutzt."
    try:
        with config_path.open('r', encoding='utf-8') as handle:
            yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        return 'ERROR', f"config.yaml ist ungültig: {exc}"
    return 'OK', "config.yaml lässt sich erfolgreich laden."


def check_upload_directory() -> CheckResult:
    uploads = Path('uploads')
    if uploads.exists():
        if uploads.is_dir():
            return 'OK', "uploads/-Verzeichnis ist bereit."
        return 'ERROR', "Ein Pfad namens 'uploads' existiert, ist aber kein Verzeichnis."
    try:
        uploads.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return 'ERROR', f"uploads/-Verzeichnis konnte nicht angelegt werden: {exc}"
    return 'FIXED', "uploads/-Verzeichnis wurde angelegt."


def check_admin_password() -> CheckResult:
    configured = APP_CONFIG.get('admin_password', '')
    if not configured:
        return 'ERROR', "admin_password ist leer – bitte in config.yaml setzen."
    if configured == DEFAULT_CONFIG['admin_password']:
        return 'WARN', "admin_password verwendet noch den Standardwert."
    return 'OK', "admin_password ist gesetzt und weicht vom Standardwert ab."


def main() -> int:
    _print_header()
    checks: List[Callable[[], CheckResult]] = [
        check_config_yaml,
        check_upload_directory,
        check_admin_password,
    ]

    exit_code = 0
    for check in checks:
        status, _ = _run_check(check)
        if status == 'ERROR':
            exit_code = 1

    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
