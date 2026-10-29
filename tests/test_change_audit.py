from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from flask import Blueprint, Flask, jsonify

from lib.change_audit import append_entry, attach_schedule_change, install_audit, read_entries


def sample_entry(**values):
    return {'timestamp': '2026-10-29T12:00:00+01:00', 'date': '2026-10-29',
            'actor_role': 'admin', 'outcome': 'success', **values}


def make_client(path):
    app = Flask(__name__)
    app.secret_key = 'test'
    blueprint = Blueprint('routes', __name__)
    install_audit(blueprint, lambda: path)

    @blueprint.route('/edit', methods=['POST'])
    def edit():
        before = pd.DataFrame([{'PPL': 'Test', 'Modifier': 1.0}])
        after = pd.DataFrame([{'PPL': 'Test', 'Modifier': 1.5}])
        attach_schedule_change('Test', 'ct', before, after, False)
        return jsonify(success=True)

    @blueprint.route('/fail', methods=['POST'])
    def fail():
        return jsonify(error='Conflict'), 409

    @blueprint.route('/preview', methods=['POST'], endpoint='resolve_live_task_preview')
    def preview():
        return jsonify(success=True)

    @blueprint.route('/read')
    def read():
        return jsonify(success=True)

    @blueprint.route('/assign', endpoint='assign_worker_api')
    def assign():
        return jsonify(worker='Test')

    app.register_blueprint(blueprint)
    return app.test_client()


def test_changes_include_ip_role_details_and_persisted_before_after(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    response = client.post('/edit', json={'updates': {'Modifier': 1.5}},
                           environ_base={'REMOTE_ADDR': '192.0.2.8'})
    assert response.status_code == 200
    entries, count = read_entries(path)
    assert count == 1
    entry = entries[0]
    assert entry['client_ip'] == '192.0.2.8'
    assert entry['actor_role'] == 'admin'
    assert entry['outcome'] == 'success'
    assert entry['changes']['updates']['Modifier'] == 1.5
    assert entry['schedule_changes'][0]['before'][0]['Modifier'] == 1
    assert entry['schedule_changes'][0]['after'][0]['Modifier'] == 1.5
    assert datetime.fromisoformat(entry['timestamp']).tzinfo is not None


def test_failed_changes_logged_reads_and_previews_excluded(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    client.get('/read')
    client.post('/preview', json={})
    assert not path.exists()
    client.post('/fail', json={})
    client.get('/assign')
    entries, count = read_entries(path)
    assert count == 2
    assert entries[0]['action'] == 'assign_worker_api'
    assert entries[1]['outcome'] == 'failed'


def test_nested_credentials_are_redacted_in_json_and_form(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    client.post('/edit?token=hidden', json={'config': {'admin_password': 'hidden'},
                                         'list': [{'secret_key': 'hidden'}]})
    client.post('/edit', data={'password': 'hidden', 'worker': 'Test'})
    raw = path.read_text()
    assert 'hidden' not in raw
    assert '[redacted]' in raw
    assert 'Test' in raw


def test_forwarded_ip_requires_trusted_peer_and_uses_rightmost_untrusted_hop(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    headers = {'X-Forwarded-For': '198.51.100.99, 192.0.2.8, 127.0.0.1'}
    client.post('/edit', headers=headers, environ_base={'REMOTE_ADDR': '203.0.113.4'})
    client.post('/edit', headers=headers, environ_base={'REMOTE_ADDR': '127.0.0.1'})
    entries, _ = read_entries(path)
    assert entries[0]['client_ip'] == '192.0.2.8'
    assert entries[1]['client_ip'] == '203.0.113.4'


def test_day_filter_latest_50_pagination_and_corrupt_line(tmp_path):
    path = tmp_path / 'changes.jsonl'
    assert read_entries(path) == ([], 0)
    for index in range(125):
        append_entry(path, sample_entry(id=index, date='2026-10-29' if index < 120 else '2026-10-30'))
    with path.open('a') as stream:
        stream.write('incomplete\n')
    entries, total = read_entries(path, '2026-10-29', offset=50)
    assert total == 120
    assert len(entries) == 50
    assert entries[0]['id'] == 69
    assert entries[-1]['id'] == 20
    assert read_entries(path)[0][0]['id'] == 124


def test_concurrent_append_keeps_complete_records(tmp_path):
    path = tmp_path / 'changes.jsonl'
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: append_entry(path, sample_entry(id=index, payload='ü' * 1000)), range(40)))
    entries, total = read_entries(path)
    assert total == 40
    assert len({entry['id'] for entry in entries}) == 40


def test_write_failure_does_not_disguise_completed_operation(tmp_path):
    client = make_client(tmp_path / 'changes.jsonl')
    with patch('lib.change_audit.append_entry', side_effect=OSError('disk full')):
        response = client.post('/edit', json={})
    assert response.status_code == 200
    assert response.headers['X-Change-History-Status'] == 'write-failed'


def test_snapshot_capture_failure_does_not_fail_saved_change(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    with patch.object(pd.DataFrame, 'to_dict', side_effect=ValueError('bad cell')):
        response = client.post('/edit', json={})
    assert response.status_code == 200
    assert read_entries(path)[0][0]['schedule_capture_failed'] is True


def test_timestamp_failure_preserves_response_and_marks_missing_audit(tmp_path):
    client = make_client(tmp_path / 'changes.jsonl')
    with patch('lib.change_audit.audit_now', side_effect=ValueError('invalid timezone')):
        response = client.post('/edit', json={})
    assert response.status_code == 200
    assert response.headers['X-Change-History-Status'] == 'write-failed'


def test_invalid_proxy_config_fails_closed_without_breaking_edits(tmp_path):
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    client.application.config['AUDIT_TRUSTED_PROXIES'] = 'invalid-network'
    response = client.post('/edit', headers={'X-Forwarded-For': '192.0.2.8'},
                           environ_base={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert read_entries(path)[0][0]['client_ip'] == '127.0.0.1'


def test_corrupt_utf8_invalid_records_and_torn_tail_do_not_hide_new_entries(tmp_path):
    path = tmp_path / 'changes.jsonl'
    path.write_bytes(b'{"timestamp": "\\xff"}\n{}\n{"unfinished":')
    append_entry(path, sample_entry(id='new'))
    entries, total = read_entries(path)
    assert total == 1
    assert entries[0]['id'] == 'new'
    assert read_entries(path, offset=10**9) == ([], 1)


def test_admin_history_render_access_filtering_and_download(tmp_path):
    import routes
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.secret_key = 'test'
    app.register_blueprint(routes.routes)
    path = tmp_path / 'changes.jsonl'
    client = make_client(path)
    client.post('/edit', json={'worker': '<script>alert(1)</script>'})
    admin = app.test_client()
    with patch.object(routes, 'LOG_ROOT', tmp_path), patch('routes.has_admin_access', return_value=True):
        response = admin.get('/admin/logs')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Änderungsverlauf' in html
        assert 'aria-controls="panel-technical"' in html
        assert '<script>alert(1)</script>' not in html
        assert admin.get('/admin/logs?day=2026-99-99').status_code == 400
        assert admin.get('/admin/logs?offset=invalid').status_code == 400
        assert 'Keine Änderungen' in admin.get('/admin/logs?day=2000-01-01').get_data(as_text=True)
        assert admin.get('/admin/logs/download?sources=changes&scope=full').status_code == 200
    with patch('routes.has_admin_access', return_value=False):
        assert admin.get('/admin/logs').status_code == 302


def test_roster_write_failure_is_reported_and_audited_as_failure(tmp_path):
    import routes
    app = Flask(__name__)
    app.secret_key = 'test'
    app.register_blueprint(routes.routes)
    with patch.object(routes, 'LOG_ROOT', tmp_path), \
         patch('routes.has_admin_access', return_value=True), \
         patch('routes.save_worker_skill_json', return_value=False):
        response = app.test_client().post('/api/admin/skill_roster', json={'roster': {}})
    assert response.status_code == 500
    entry = read_entries(tmp_path / 'changes.jsonl')[0][0]
    assert entry['outcome'] == 'failed'
