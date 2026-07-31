import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import config as config_module
import data_manager.file_ops as file_ops
import routes
from app import app


def _admin_client():
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    return client


def _valid_config_bytes():
    return Path('config.yaml').read_bytes()


def _valid_live_backup_bytes(label='new'):
    return json.dumps({
        'working_hours': [
            {'modality': 'ct', 'PPL': label, 'TIME': '08:00-16:00'},
        ],
    }).encode('utf-8')


def test_tools_pages_are_integrated_and_admin_protected():
    anonymous = app.test_client()
    assert anonymous.get('/admin/tools').status_code == 302
    assert anonymous.get('/admin/settings').status_code == 302
    assert anonymous.get('/admin/files').status_code == 302
    assert anonymous.get('/admin/logs').status_code == 302

    client = _admin_client()
    for route in ('/admin/tools', '/admin/settings', '/admin/files', '/admin/logs', '/status'):
        response = client.get(route)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '/admin/tools' in html
        assert '/admin/settings' in html
        assert '/admin/files' in html
        assert '/admin/logs' in html
        assert '/status' in html


def test_runtime_reload_is_admin_only_and_requires_explicit_confirmation():
    anonymous = app.test_client()
    assert anonymous.post('/api/admin/runtime/reload', json={'confirmation': 'reload'}).status_code == 302

    client = _admin_client()
    assert client.post('/api/admin/runtime/reload', json={}).status_code == 400

    with patch.object(routes, '_schedule_gunicorn_reload', return_value=4321) as schedule_reload:
        response = client.post('/api/admin/runtime/reload', json={'confirmation': 'reload'})

    assert response.status_code == 202
    assert response.get_json()['master_pid'] == 4321
    schedule_reload.assert_called_once_with()


def test_invalid_config_is_rejected_before_active_file_changes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / 'config.yaml'
        backup_dir = Path(tmp_dir) / 'backups'
        config_path.write_text('modalities: {}\nskills: {}\n', encoding='utf-8')
        original = config_path.read_bytes()

        with patch.object(routes, 'CONFIG_FILE_PATH', config_path), patch.object(
            routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir
        ):
            try:
                routes._replace_config_file(b'modalities:\n  ct: {}\n')
            except ValueError as error:
                assert 'skill' in str(error).lower()
            else:
                raise AssertionError('invalid config should be rejected')

        assert config_path.read_bytes() == original
        assert not backup_dir.exists()


def test_invalid_default_language_is_rejected():
    raw_config = yaml.safe_load(_valid_config_bytes())
    raw_config['default_language'] = 'fr'
    try:
        routes.validate_config_candidate(raw_config)
    except ValueError as error:
        assert 'default_language' in str(error)
    else:
        raise AssertionError('unsupported language should be rejected')


def test_runtime_reload_rejects_invalid_timezone_without_mutating_runtime():
    raw_config = yaml.safe_load(_valid_config_bytes())
    raw_config['timezone'] = 'Not/A_Real_Timezone'
    original_timezone = config_module.TIMEZONE
    original_app_timezone = config_module.APP_CONFIG.get('timezone')

    with patch.object(config_module, '_load_raw_config', return_value=raw_config):
        result = config_module.reload_runtime_config()

    assert result['applied'] is False
    assert result['reason'] == 'invalid_config'
    assert config_module.TIMEZONE == original_timezone
    assert config_module.APP_CONFIG.get('timezone') == original_app_timezone


def test_explicit_config_reload_validates_disk_before_runtime_reload():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / 'config.yaml'
        raw_config = yaml.safe_load(_valid_config_bytes())
        raw_config['timezone'] = 'Not/A_Real_Timezone'
        config_path.write_text(yaml.safe_dump(raw_config), encoding='utf-8')

        with patch.object(routes, 'CONFIG_FILE_PATH', config_path), patch.object(
            routes, 'reload_runtime_config'
        ) as reload_mock:
            response = _admin_client().post('/api/admin/files/reload', json={'target': 'config'})

    assert response.status_code == 400
    assert 'timezone' in response.get_json()['error'].lower()
    reload_mock.assert_not_called()


def test_secret_key_change_is_restart_required_and_not_hot_applied():
    raw_config = yaml.safe_load(_valid_config_bytes())
    original_secret = config_module.APP_CONFIG.get('secret_key')
    raw_config['secret_key'] = f'{original_secret}-changed'

    with patch.object(config_module, '_load_raw_config', return_value=raw_config):
        result = config_module.reload_runtime_config()

    assert result['applied'] is False
    assert result['reason'] == 'secret_key_changed'
    assert config_module.APP_CONFIG.get('secret_key') == original_secret


def test_skill_roster_auto_import_reads_live_config_value():
    with patch.dict(file_ops.APP_CONFIG, {'skill_roster_auto_import': False}):
        assert file_ops._skill_roster_auto_import_enabled() is False
    with patch.dict(file_ops.APP_CONFIG, {'skill_roster_auto_import': True}):
        assert file_ops._skill_roster_auto_import_enabled() is True


def test_general_config_patch_preserves_unrelated_yaml_and_comments():
    original = '# header comment\ntimezone: Europe/Berlin\nmodalities:\n  ct: {}\n'
    patched = routes._patch_top_level_yaml_scalars(original, {
        'default_language': 'en',
        'timezone': 'Europe/Zurich',
        'skill_roster_auto_import': False,
    })

    assert '# header comment' in patched
    assert 'modalities:\n  ct: {}' in patched
    parsed = yaml.safe_load(patched)
    assert parsed['default_language'] == 'en'
    assert parsed['timezone'] == 'Europe/Zurich'
    assert parsed['skill_roster_auto_import'] is False


def test_general_settings_api_updates_config_with_backup_and_reload():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / 'config.yaml'
        backup_dir = Path(tmp_dir) / 'backups'
        config_path.write_bytes(_valid_config_bytes())
        payload = {
            'default_language': 'en',
            'timezone': 'Europe/Zurich',
            'worker_name_display_style': 'last_first_id',
            'skill_roster_auto_import': False,
            'access_protection_enabled': True,
            'admin_access_protection_enabled': True,
        }

        with patch.object(routes, 'CONFIG_FILE_PATH', config_path), patch.object(
            routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir
        ), patch.object(routes, 'reload_runtime_config', return_value={
            'applied': True, 'reason': 'applied', 'message': 'Config reload applied'
        }), patch.object(routes, '_build_readiness_payload', return_value=({}, 200)):
            response = _admin_client().post('/api/admin/config/general', json=payload)

        assert response.status_code == 200
        result = response.get_json()
        assert result['success'] is True
        assert result['ready'] is True
        assert Path(result['backup_path']).exists()
        saved = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        for key, value in payload.items():
            assert saved[key] == value


def test_default_language_flows_from_runtime_config_to_html():
    with patch.dict(routes.APP_CONFIG, {'default_language': 'en'}):
        response = _admin_client().get('/admin/settings')

    html = response.get_data(as_text=True)
    assert '<html lang="en" data-default-language="en">' in html
    assert 'id="default-language"' in html
    assert '<option value="en" selected>' in html


def test_shared_shell_has_accessibility_landmarks_and_active_state():
    html = _admin_client().get('/admin/settings').get_data(as_text=True)
    assert 'class="skip-link" href="#main-content"' in html
    assert '<main id="main-content" tabindex="-1">' in html
    assert 'aria-label="Primary navigation"' in html
    assert 'aria-current="page"' in html
    assert 'role="status" aria-live="polite"' in html


def test_config_reload_failure_rolls_back_original_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / 'config.yaml'
        backup_dir = Path(tmp_dir) / 'backups'
        config_path.write_text('original: true\n', encoding='utf-8')
        original = config_path.read_bytes()

        reload_results = [
            {'applied': False, 'reason': 'invalid_config', 'message': 'rejected'},
            {'applied': True, 'reason': 'applied', 'message': 'original restored'},
        ]
        with patch.object(routes, 'CONFIG_FILE_PATH', config_path), patch.object(
            routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir
        ), patch.object(routes, 'reload_runtime_config', side_effect=reload_results):
            try:
                routes._replace_config_file(_valid_config_bytes())
            except ValueError as error:
                assert 'rejected' in str(error)
            else:
                raise AssertionError('failed reload should reject upload')

        assert config_path.read_bytes() == original
        assert list(backup_dir.glob('config_*.yaml'))
        assert not (config_path.parent / '.config.yaml.upload.tmp').exists()


def test_live_backup_reload_failure_rolls_back_original_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        live_path = Path(tmp_dir) / 'Cortex_ALL_live.json'
        backup_dir = Path(tmp_dir) / 'backups'
        original = _valid_live_backup_bytes('original')
        live_path.write_bytes(original)
        state = SimpleNamespace(unified_schedule_paths={'live': str(live_path)})

        with patch.object(routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir), patch.object(
            routes.StateManager, 'get_instance', return_value=state
        ), patch.object(routes, 'initialize_data_from_unified', side_effect=[False, True]):
            try:
                routes._replace_live_backup_file(_valid_live_backup_bytes('replacement'))
            except ValueError as error:
                assert 'original file was restored' in str(error)
            else:
                raise AssertionError('failed runtime load should reject live backup')

        assert live_path.read_bytes() == original
        assert list(backup_dir.glob('live_backup_*.json'))


def test_staged_restore_reload_failure_rolls_back_original_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_dir = Path(tmp_dir) / 'staged'
        backup_dir = Path(tmp_dir) / 'backups'
        staged_dir.mkdir()
        target_date = routes.date(2026, 7, 23)
        active_path = staged_dir / 'Cortex_ALL_staged_2026-07-23.json'
        archive_path = staged_dir / 'Cortex_ALL_staged_2026-07-23_archive.json'
        original = _valid_live_backup_bytes('original')
        active_path.write_bytes(original)
        archive_path.write_bytes(_valid_live_backup_bytes('archive'))

        with patch.object(routes, 'STAGED_DAY_DIR', staged_dir), patch.object(
            routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir
        ), patch.object(
            routes, '_get_current_staged_target_date', return_value=target_date
        ), patch.object(
            routes, 'reload_staged_data_from_disk', side_effect=[False, True]
        ):
            try:
                routes._restore_staged_day_file(archive_path.name)
            except ValueError as error:
                assert 'original file was restored' in str(error)
            else:
                raise AssertionError('failed staged reload should reject restore')

        assert active_path.read_bytes() == original
        assert list(backup_dir.glob('staged_2026-07-23_*.json'))


def test_config_upload_response_reports_backup_and_runtime_state():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / 'config.yaml'
        backup_dir = Path(tmp_dir) / 'backups'
        config_path.write_bytes(_valid_config_bytes())

        with patch.object(routes, 'CONFIG_FILE_PATH', config_path), patch.object(
            routes, 'ADMIN_FILE_BACKUP_DIR', backup_dir
        ), patch.object(routes, 'reload_runtime_config', return_value={
            'applied': True, 'reason': 'applied', 'message': 'Config reload applied'
        }):
            response = _admin_client().post(
                '/api/admin/files/upload',
                data={
                    'target': 'config',
                    'file': (io.BytesIO(_valid_config_bytes()), 'config.yaml'),
                },
                content_type='multipart/form-data',
            )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['success'] is True
        assert payload['runtime_applied'] is True
        assert payload['restart_required'] is False
        assert Path(payload['backup_path']).exists()


def test_managed_backup_path_rejects_traversal():
    client = _admin_client()
    response = client.get(
        '/api/admin/files/download?target=managed_backup&source=admin_files&name=../config.yaml'
    )
    assert response.status_code == 400
    assert response.get_json()['success'] is False


def test_explicit_config_reload_reports_structural_restart_requirement():
    reload_result = {
        'applied': False,
        'reason': 'modalities_changed',
        'message': 'Configured modalities changed; restart required',
    }
    with patch.object(routes, 'reload_runtime_config', return_value=reload_result), patch.object(
        routes, '_build_admin_files_manifest', return_value={'targets': []}
    ):
        response = _admin_client().post('/api/admin/files/reload', json={'target': 'config'})

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['restart_required'] is True
    assert payload['reload'] == reload_result


def test_files_manifest_exposes_absolute_paths_and_recovery_locations():
    response = _admin_client().get('/api/admin/files/manifest')
    assert response.status_code == 200
    manifest = response.get_json()['manifest']
    assert {'admin_files', 'skill_roster'} <= set(manifest['backup_paths'])
    assert all(Path(item['path']).is_absolute() for item in manifest['targets'])


def test_log_tail_preview_is_read_only_and_bounded():
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_root = Path(tmp_dir)
        (log_root / 'selection.log').write_text('one\ntwo\nthree\n', encoding='utf-8')
        with patch.object(routes, 'LOG_ROOT', log_root):
            response = _admin_client().get('/api/admin/logs/tail?source=selection&lines=2')

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['success'] is True
        assert payload['text'] == 'two\nthree\n'
        assert payload['path'].endswith('selection.log')


def test_log_tail_preview_requires_admin_session():
    response = app.test_client().get('/api/admin/logs/tail?source=selection&lines=20')
    assert response.status_code == 302
