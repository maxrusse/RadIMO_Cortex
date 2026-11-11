"""Sysadmin boundaries must hold at the API as well as in page navigation."""
import io
from unittest.mock import patch

import pytest

from app import app
from config import APP_CONFIG, _build_app_config
import routes


@pytest.fixture
def admin_client():
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    return client


def unlock(client):
    return client.post('/sysadmin/login', data={'password': 'test-log-password', 'next': '/admin/settings'})


@pytest.mark.parametrize('path', ['/admin/settings', '/admin/settings/advanced', '/admin/tools', '/admin/files', '/admin/logs', '/status'])
def test_admin_alone_cannot_open_sysadmin_pages(admin_client, path, monkeypatch):
    monkeypatch.setitem(APP_CONFIG, 'admin_access_protection_enabled', False)
    response = admin_client.get(path)
    assert response.status_code == 302
    assert '/sysadmin/login' in response.location
    assert admin_client.get(response.location).status_code == 200
    assert 'Sysadmin-Zugang' in admin_client.get(response.location).get_data(as_text=True)


@pytest.mark.parametrize('operation', ['manifest', 'download', 'upload', 'restore', 'reload', 'general', 'runtime'])
def test_all_sensitive_apis_require_sysadmin(admin_client, operation):
    with patch.object(routes, '_replace_config_file') as replace, patch.object(routes, '_schedule_gunicorn_reload') as reload:
        if operation == 'manifest':
            response = admin_client.get('/api/admin/files/manifest')
        elif operation == 'download':
            response = admin_client.get('/api/admin/files/download?target=config')
        elif operation == 'upload':
            response = admin_client.post('/api/admin/files/upload', data={'target':'config','file':(io.BytesIO(b'sysadmin_password: attack'), 'config.yaml')})
        elif operation == 'general':
            response = admin_client.post('/api/admin/config/general', json={'sysadmin_password':'attack'})
        elif operation == 'runtime':
            response = admin_client.post('/api/admin/runtime/reload', json={'confirmation':'reload'})
        else:
            response = admin_client.post('/api/admin/files/'+operation, json={'target':'managed_backup','source':'admin_files','name':'config_20261111_120000.yaml'})
        assert response.status_code == 401
        replace.assert_not_called(); reload.assert_not_called()


def test_legacy_password_migration_and_new_password_precedence(admin_client, monkeypatch):
    assert unlock(admin_client).location.endswith('/admin/settings')
    assert admin_client.get('/admin/settings').status_code == 200
    monkeypatch.setitem(APP_CONFIG, 'sysadmin_password', 'new-system-secret')
    assert admin_client.get('/admin/settings').status_code == 302
    assert admin_client.post('/sysadmin/login', data={'password':'test-log-password'}).status_code == 200
    assert admin_client.post('/sysadmin/login', data={'password':'new-system-secret','next':'/admin/tools'}).location.endswith('/admin/tools')
    assert admin_client.get('/admin/tools').status_code == 200
    admin_client.post('/sysadmin/logout')
    assert admin_client.get('/admin/settings').status_code == 302


def test_sysadmin_is_yaml_only_and_not_in_normal_settings(admin_client):
    unlock(admin_client)
    html = admin_client.get('/admin/settings').get_data(as_text=True)
    assert 'name="log_password"' not in html and 'name="sysadmin_password"' not in html
    assert 'id="full-config-editor"' not in html
    assert admin_client.get('/admin/settings/advanced').status_code == 200
    assert 'id="full-config-editor"' in admin_client.get('/admin/settings/advanced').get_data(as_text=True)
    for key in ('log_password','sysadmin_password'):
        assert admin_client.post('/api/admin/config/general',json={key:'new'}).status_code == 400


def test_admin_upload_and_planning_remain_accessible_without_sysadmin(admin_client):
    assert admin_client.get('/upload').status_code == 200
    for path in ('/prep-today','/prep-tomorrow','/api/prep-next-day/prepared-days'):
        assert admin_client.get(path).status_code == 200
    result=admin_client.get('/api/prep-next-day/prepared-days').get_json()
    assert set(result)=={'staged_days'}
    assert all(set(item)=={'target_date','is_canonical'} for item in result['staged_days'])


def test_login_cannot_redirect_outside_application(admin_client):
    response=admin_client.post('/sysadmin/login',data={'password':'test-log-password','next':'https://example.invalid/'})
    assert response.location.endswith('/admin/logs')


def test_sysadmin_password_validation_and_unset_password(admin_client,monkeypatch):
    assert _build_app_config({})['sysadmin_password']==''
    with pytest.raises(ValueError,match='sysadmin_password'):
        _build_app_config({'sysadmin_password':123})
    monkeypatch.setitem(APP_CONFIG,'sysadmin_password','')
    monkeypatch.setitem(APP_CONFIG,'log_password','')
    assert admin_client.get('/api/admin/files/manifest').status_code==401
    assert admin_client.post('/sysadmin/login',data={'password':''}).status_code==200


@pytest.mark.parametrize('session_flags', [
    {'admin_logged_in': True}, {'access_granted': True}, {},
])
def test_logout_locks_sysadmin_for_every_session_type(admin_client, monkeypatch, session_flags):
    monkeypatch.setitem(APP_CONFIG, 'admin_access_protection_enabled', False)
    with admin_client.session_transaction() as session:
        session.clear()
        session.update(session_flags)
    unlock(admin_client)
    assert admin_client.get('/admin/settings').status_code == 200
    admin_client.get('/logout')
    with admin_client.session_transaction() as session:
        assert not session.get('logs_access')
    assert admin_client.get('/admin/settings').status_code == 302


def test_sysadmin_login_requires_both_levels_for_admin_tools():
    client=app.test_client()
    assert client.post('/sysadmin/login',data={'password':'test-log-password','next':'/admin/tools'}).status_code==302
    with patch.object(routes,'is_admin_protection_enabled',return_value=True):
        assert '/login?' in client.get('/admin/tools').location


@pytest.mark.parametrize('valid', [True, False])
def test_audit_recognizes_only_current_sysadmin_tokens(tmp_path, monkeypatch, valid):
    monkeypatch.setitem(APP_CONFIG, 'admin_access_protection_enabled', False)
    monkeypatch.setitem(APP_CONFIG, 'change_history_enabled', True)
    monkeypatch.setattr(routes, 'LOG_ROOT', tmp_path)
    client = app.test_client()
    with client.session_transaction() as session:
        session['logs_access'] = routes._log_password_fingerprint() if valid else 'expired'
    with patch.object(routes, '_schedule_gunicorn_reload', return_value=4321) as reload:
        response = client.post('/api/admin/runtime/reload', json={'confirmation': 'reload'})
        assert response.status_code == (202 if valid else 401)
        assert reload.call_count == int(valid)
    entries, count = routes.read_entries(tmp_path / 'changes.jsonl')
    assert count == 1
    assert entries[0]['actor_role'] == ('sysadmin' if valid else 'shared / unverified')
