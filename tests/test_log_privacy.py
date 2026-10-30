from pathlib import Path
from unittest.mock import patch

from flask import Flask
import pytest

from config import APP_CONFIG, _build_app_config
import routes
from lib.change_audit import append_entry, read_entries, record_daily_reset
from tests.test_change_audit import make_client


@pytest.fixture
def client():
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.secret_key = 'test'
    app.register_blueprint(routes.routes)
    return app.test_client()


def test_log_password_is_required_even_for_admin_and_when_admin_protection_is_off(client, monkeypatch):
    monkeypatch.setitem(APP_CONFIG, 'admin_access_protection_enabled', False)
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    assert client.get('/admin/logs').status_code == 302
    assert client.get('/admin/logs/download').status_code == 302
    assert client.get('/api/admin/logs/tail').status_code == 401
    assert client.post('/logs/login', data={'password': 'wrong'}).status_code == 200
    assert client.get('/admin/logs').status_code == 302


def test_log_login_download_password_rotation_and_logout(client, tmp_path, monkeypatch):
    monkeypatch.setattr(routes, 'LOG_ROOT', tmp_path)
    (tmp_path / 'selection.log').write_text('2026-10-30 10:00:00 test\n')
    assert client.post('/logs/login', data={'password': 'test-log-password'}).status_code == 302
    page = client.get('/admin/logs')
    assert page.status_code == 200
    assert 'no-store' in page.headers['Cache-Control']
    assert 'Sicher aufbewahren und nach der Auswertung löschen.' in page.get_data(as_text=True)
    assert client.get('/api/admin/logs/tail?source=selection').status_code == 200
    assert client.get('/admin/logs/download?sources=selection').status_code == 200
    with client.session_transaction() as session:
        assert not session.get('admin_logged_in')
    monkeypatch.setitem(APP_CONFIG, 'log_password', 'new-password')
    assert client.get('/admin/logs').status_code == 302
    client.post('/logs/login', data={'password': 'new-password'})
    client.post('/logs/logout')
    assert client.get('/admin/logs').status_code == 302


def test_empty_password_never_grants_log_access(client, monkeypatch):
    monkeypatch.setitem(APP_CONFIG, 'log_password', '')
    client.post('/logs/login', data={'password': ''})
    assert client.get('/admin/logs').status_code == 302


def test_disabled_history_excludes_requests_and_daily_reset(tmp_path, monkeypatch):
    monkeypatch.setitem(APP_CONFIG, 'change_history_enabled', False)
    path = tmp_path / 'changes.jsonl'
    assert make_client(path).post('/edit', json={'worker': 'test'}).status_code == 200
    assert not path.exists()
    with patch('lib.change_audit.append_entry') as append:
        from datetime import date
        record_daily_reset(date.today(), True)
        append.assert_not_called()
    monkeypatch.setitem(APP_CONFIG, 'change_history_enabled', True)
    make_client(path).post('/edit', json={})
    assert read_entries(path)[1] == 1


def test_legacy_address_metadata_removed_on_append_and_read(tmp_path):
    path = tmp_path / 'changes.jsonl'
    entry = {'timestamp': '2026-10-30T10:00:00', 'date': '2026-10-30',
             'actor_role': 'admin', 'outcome': 'success',
             'client_ip': 'obsolete', 'result': {'peer_ip': 'obsolete'}}
    append_entry(path, entry)
    assert 'obsolete' not in path.read_text()
    import json
    path.write_text(json.dumps(entry) + '\n')
    assert 'obsolete' not in json.dumps(read_entries(path))


def test_log_config_defaults():
    config = _build_app_config({})
    assert config['log_retention_days'] == 100
    assert config['change_history_enabled'] is True
    assert config['log_password'] == ''


def test_password_settings_never_echo_secret_and_blank_preserves_it(tmp_path, monkeypatch):
    config = tmp_path / 'config.yaml'
    config.write_text('log_password: old\n')
    monkeypatch.setattr(routes, 'CONFIG_FILE_PATH', config)
    with patch.object(routes, '_replace_config_file', return_value={}):
        result = routes._replace_general_config_settings({'log_password': 'new\\secret'})
        assert 'log_password' not in result['settings']
    assert 'new\\\\secret' in routes._patch_top_level_yaml_scalars('log_password: old\n', {'log_password': 'new\\secret'})
    with patch.object(routes, '_replace_config_file') as replace:
        routes._replace_general_config_settings({'log_password': ''})
        assert b'log_password: old' in replace.call_args.args[0]
    for days in [0, -1, True, 1.5, 'invalid', 999999999]:
        with pytest.raises(ValueError):
            routes._replace_general_config_settings({'log_retention_days': days})


@pytest.mark.parametrize('days', [0, -1, True, 'invalid', 1.5, 999999999])
def test_full_yaml_config_rejects_invalid_retention(days):
    with pytest.raises(ValueError):
        _build_app_config({'log_retention_days': days})


def test_loading_legacy_state_persists_address_removal(tmp_path, monkeypatch):
    import json
    from data_manager import state_persistence
    state_file = tmp_path / 'state.json'
    state_file.write_text(json.dumps({'global_worker_data': {
        'manual_weight_adjustments': [{'client_ip': 'obsolete', 'peer_ip': 'obsolete', 'reason': 'retain'}]
    }}))
    monkeypatch.setattr(state_persistence, 'STATE_FILE_PATH', str(state_file))
    monkeypatch.setattr(state_persistence, 'global_worker_data', {'last_reset_date': None, 'last_preload_date': None})
    monkeypatch.setattr(state_persistence, 'allowed_modalities', [])
    state_persistence.load_state()
    assert 'obsolete' not in state_file.read_text()
    assert 'retain' in state_file.read_text()
