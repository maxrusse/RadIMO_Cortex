"""Append-only request change history, shared safely by Gunicorn workers."""
import fcntl
import ipaddress
import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import current_app, g, has_request_context, request, session


def audit_now():
    from config import TIMEZONE
    return datetime.now(ZoneInfo(TIMEZONE))


ASSIGNMENT_ENDPOINTS = {'routes.assign_worker_api', 'routes.assign_worker_strict_api'}
EXCLUDED_ENDPOINTS = {
    'routes.login', 'routes.access_login',
    'routes.resolve_live_task_preview', 'routes.resolve_prep_task_preview',
}
ACTION_LABELS = {
    'update_live_row': 'Heute: Zeile bearbeiten',
    'update_prep_row': 'Planung: Zeile bearbeiten',
    'apply_live_worker_plan': 'Heute: Mitarbeiterplan speichern',
    'create_live_worker_plan': 'Heute: Mitarbeiter anlegen',
    'apply_prep_worker_plan': 'Planung: Mitarbeiterplan speichern',
    'create_prep_worker_plan': 'Planung: Mitarbeiter anlegen',
    'add_live_gap_batch': 'Heute: Abwesenheit eintragen',
    'add_staged_gap_batch': 'Planung: Abwesenheit eintragen',
    'assign_worker_api': 'Mitarbeiter zuweisen',
    'assign_worker_strict_api': 'Mitarbeiter strikt zuweisen',
    'assign_worker_strict_manual_api': 'Mitarbeiter manuell zuweisen',
    'manual_adjustments_api': 'Last manuell korrigieren',
    'admin_config_general_update': 'Allgemeine Einstellungen speichern',
    'admin_files_upload': 'Verwaltete Datei ersetzen',
    'admin_files_restore': 'Datei aus Sicherung wiederherstellen',
    'admin_files_reload': 'Datei neu laden',
    'admin_runtime_reload': 'Anwendung neu laden',
    'skill_roster_api': 'Mitarbeiterfähigkeiten speichern',
    'button_weights_api': 'Zuweisungsgewichte speichern',
    'import_new_skill_roster_api': 'Neue Mitarbeiter importieren',
    'import_csv_skill_roster_worker_api': 'Mitarbeiter aus CSV übernehmen',
    'edit_info': 'Hinweistexte bearbeiten',
    'upload_master_csv': 'Master-CSV hochladen',
    'preload_from_master': 'Planung aus Master-CSV vorbereiten',
    'load_today_from_master': 'Heute aus Master-CSV neu aufbauen',
    'export_usage_stats': 'Nutzungsstatistik exportieren',
    'reset_usage_stats': 'Nutzungsstatistik zurücksetzen',
    'daily_reset': 'Automatischer Tageswechsel',
}


def clean(value):
    """Keep structured change details while excluding credentials recursively."""
    if isinstance(value, dict):
        return {
            str(key): ('[redacted]' if any(word in str(key).lower() for word in
                       ('password', 'secret', 'token', 'cookie', 'authorization')) else clean(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def target_label(entry):
    changes = entry.get('changes')
    values = changes if isinstance(changes, dict) else {}
    values = {**entry.get('parameters', {}), **values}
    parts = []
    for label, keys in (
        ('Mitarbeiter', ('worker', 'verify_ppl', 'worker_id')),
        ('Modalität', ('modality',)), ('Datum', ('target_date',)),
        ('Ziel', ('target',)), ('Aufgabe', ('role',)),
    ):
        for key in keys:
            value = values.get(key)
            if isinstance(value, (str, int, float)) and value != '':
                parts.append(f'{label}: {value}')
                break
    return ' · '.join(parts)


def client_identity():
    """Trust forwarding headers only from explicitly trusted proxy networks."""
    peer = request.remote_addr or ''
    networks = []
    for item in current_app.config.get('AUDIT_TRUSTED_PROXIES', '127.0.0.1/32,::1/128').split(','):
        if not item.strip():
            continue
        try:
            networks.append(ipaddress.ip_network(item.strip()))
        except ValueError:
            current_app.logger.error('Ignoring invalid audit proxy network: %r', item)

    def trusted(address):
        try:
            return any(ipaddress.ip_address(address) in network for network in networks)
        except ValueError:
            return False

    client = peer
    if trusted(peer):
        chain = request.headers.get('X-Forwarded-For', '').split(',')
        for address in reversed(chain):
            address = address.strip()
            try:
                ipaddress.ip_address(address)
            except ValueError:
                break
            client = address
            if not trusted(address):
                break
    return {'client_ip': client, 'peer_ip': peer}


def append_entry(path, entry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(clean(entry), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    with path.open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0, os.SEEK_END)
        if stream.tell():
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b'\n':
                stream.write(b'\n')  # Preserve, but isolate a torn final record.
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def attach_schedule_change(worker, modality, before, after, use_staged):
    """Attach the persisted worker rows while still inside the mutation lock."""
    if not has_request_context() or not hasattr(g, 'change_audit'):
        return

    def rows(frame):
        if frame is None or frame.empty or 'PPL' not in frame:
            return []
        return clean(frame.loc[frame['PPL'] == worker].to_dict('records'))

    try:
        g.change_audit.setdefault('schedule_changes', []).append({
            'worker': str(worker), 'modality': modality,
            'schedule': 'planned' if use_staged else 'live',
            'before': rows(before), 'after': rows(after),
        })
    except Exception:
        # Persistence has already succeeded: an audit serialization failure must
        # never trigger a rollback of memory after the saved file was committed.
        current_app.logger.exception('Schedule change details could not be captured')
        g.change_audit['schedule_capture_failed'] = True


def record_daily_reset(day, loaded):
    try:
        now = audit_now()
        append_entry(Path('logs/changes.jsonl'), {
            'id': uuid4().hex, 'timestamp': now.isoformat(timespec='milliseconds'),
            'date': now.date().isoformat(), 'action': 'daily_reset',
            'action_label': ACTION_LABELS['daily_reset'], 'actor_role': 'system',
            'client_ip': '', 'peer_ip': '', 'method': 'SYSTEM', 'path': '',
            'parameters': {}, 'query': {}, 'changes': {'target_date': day.isoformat()},
            'uploads': [], 'status': None, 'outcome': 'success' if loaded else 'partial',
            'result': {'counters_reset': True, 'staged_schedule_activated': loaded},
        })
    except Exception:
        logging.getLogger(__name__).exception('Daily reset history write failed')


def read_entries(path, day=None, limit=50, offset=0):
    """Read one fixed snapshot in two passes, retaining only the requested page."""
    try:
        with Path(path).open('rb') as stream:
            snapshot_size = os.fstat(stream.fileno()).st_size

            def matching_entries():
                stream.seek(0)
                while stream.tell() < snapshot_size:
                    line = stream.readline(snapshot_size - stream.tell())
                    if not line.endswith(b'\n'):
                        break  # A writer may still be completing this record.
                    try:
                        entry = json.loads(line.decode('utf-8', errors='replace'))
                    except ValueError:
                        continue
                    if not isinstance(entry, dict) or not all(
                        isinstance(entry.get(key), str)
                        for key in ('timestamp', 'date', 'actor_role', 'outcome')
                    ) or (day and entry['date'] != day):
                        continue
                    entry = {'action': 'Änderung', 'parameters': {}, 'query': {},
                             'changes': {}, 'uploads': [], 'result': None, **entry}
                    yield entry

            total = sum(1 for _ in matching_entries())
            start, stop = max(0, total - offset - limit), max(0, total - offset)
            entries = []
            for index, entry in enumerate(matching_entries()):
                if index >= stop:
                    break
                if index >= start:
                    entries.append(entry)
            return list(reversed(entries)), total
    except FileNotFoundError:
        return [], 0


def install_audit(blueprint, path_provider):
    @blueprint.before_request
    def prepare_change_audit():
        endpoint = request.endpoint
        if not endpoint or endpoint in EXCLUDED_ENDPOINTS:
            return
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'} and not (
            request.method == 'GET' and endpoint in ASSIGNMENT_ENDPOINTS
        ):
            return
        g.change_audit = {
            'id': uuid4().hex,
            'action': endpoint.removeprefix('routes.'),
            'action_label': ACTION_LABELS.get(endpoint.removeprefix('routes.'), 'Änderung'),
            'method': request.method,
            'path': request.path,
            **client_identity(),
            'actor_role': ('admin' if session.get('admin_logged_in') else
                           'basic' if session.get('access_granted') else 'shared / unverified'),
            'parameters': clean(dict(request.view_args or {})),
            'query': clean(request.args.to_dict(flat=False)),
            'changes': clean(request.get_json(silent=True) if request.is_json
                             else request.form.to_dict(flat=False)),
            'uploads': [{'field': key, 'filename': item.filename}
                        for key, item in request.files.items()],
        }

    @blueprint.after_request
    def finish_change_audit(response):
        entry = getattr(g, 'change_audit', None)
        if entry is None:
            return response
        try:
            now = audit_now()
            result = response.get_json(silent=True) if response.is_json else None
            failed = response.status_code >= 400 or (
                isinstance(result, dict) and (result.get('success') is False or bool(result.get('error')))
            )
            entry.update({
                'timestamp': now.isoformat(timespec='milliseconds'), 'date': now.date().isoformat(),
                'status': response.status_code,
                'outcome': 'failed' if failed else 'redirected' if response.status_code >= 300 else 'success',
                'result': clean(result),
                'target_label': target_label(entry),
            })
            append_entry(path_provider(), entry)
        except Exception:
            current_app.logger.exception('Change history write failed')
            response.headers['X-Change-History-Status'] = 'write-failed'
        return response
