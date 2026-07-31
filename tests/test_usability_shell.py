import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import app
from config import _normalize_no_overflow
from data_manager.csv_parser import _select_day_times
from data_manager.worker_management import normalize_skill_mod_key
from routes import get_admin_password


def _admin_client():
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    return client


def test_admin_redirect_preserves_requested_page():
    client = app.test_client()
    response = client.get('/admin/files?section=staged')

    assert response.status_code == 302
    query = parse_qs(urlparse(response.location).query)
    assert query['next'] == ['/admin/files?section=staged']


def test_admin_login_returns_to_safe_requested_page():
    client = app.test_client()
    response = client.post(
        '/login',
        data={'password': get_admin_password(), 'next': '/admin/files?section=staged'},
    )

    assert response.status_code == 302
    assert response.location.endswith('/admin/files?section=staged')


def test_admin_login_rejects_external_next_target():
    client = app.test_client()
    response = client.post(
        '/login',
        data={'password': get_admin_password(), 'next': '//example.invalid/steal'},
    )

    assert response.status_code == 302
    assert response.location.endswith('/prep-today')


def test_shared_shell_has_german_default_and_keyboard_helpers():
    response = _admin_client().get('/')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<html lang="de" data-default-language="de">' in html
    assert 'data-language=' not in html
    assert '/static/js/i18n.js' in html
    assert '/static/js/dialog_focus.js' in html

    with open('static/js/i18n.js', encoding='utf-8') as handle:
        i18n_script = handle.read()
    assert 'document.documentElement.dataset.defaultLanguage' in i18n_script
    assert 'setLanguage(DEFAULT_LANGUAGE)' in i18n_script

    with open('static/js/admin_settings.js', encoding='utf-8') as handle:
        settings_script = handle.read()
    assert 'Object.assign(initialSettings, payload)' in settings_script


def test_language_is_centrally_configured_without_page_switches():
    for client in (app.test_client(), _admin_client()):
        for route in ('/', '/timetable', '/login', '/admin/tools', '/admin/files', '/admin/logs', '/upload', '/status'):
            response = client.get(route)
            if response.status_code == 302:
                continue
            html = response.get_data(as_text=True)
            assert response.status_code == 200, route
            assert 'class="language-toggle"' not in html, route
            assert 'data-language=' not in html, route

    i18n_script = Path('static/js/i18n.js').read_text(encoding='utf-8')
    assert 'localStorage' not in i18n_script
    assert 'setLanguage(DEFAULT_LANGUAGE)' in i18n_script


def test_lesser_used_admin_pages_share_the_operations_console_shell():
    client = _admin_client()
    for route in ('/admin/tools', '/admin/logs', '/admin/files', '/upload', '/status'):
        response = client.get(route)
        html = response.get_data(as_text=True)
        assert response.status_code == 200, route
        assert 'class="ops-shell"' in html, route
        assert 'class="ops-page-head"' in html, route


def test_admin_settings_uses_a_timezone_dropdown_without_legacy_hints():
    html = _admin_client().get('/admin/settings').get_data(as_text=True)

    assert '<select id="timezone" name="timezone" required>' in html
    assert '<option value="Europe/Berlin" selected>Europe/Berlin</option>' in html
    assert '<option value="UTC"' in html
    assert 'IANA name, for example Europe/Berlin.' not in html
    assert 'Password values are intentionally available only' not in html


def test_compact_admin_forms_have_accessible_names_and_local_table_scroll():
    client = _admin_client()

    roster_html = client.get('/skill-roster').get_data(as_text=True)
    assert 'id="workerSearchInput"' in roster_html
    assert 'aria-label="Search workers"' in roster_html

    weights_html = client.get('/button-weights').get_data(as_text=True)
    assert "input.setAttribute('aria-label', `Weight:" in weights_html

    prep_html = client.get('/prep-today').get_data(as_text=True)
    assert '.table-container {' in prep_html
    assert 'overflow-x: auto;' in prep_html
    assert 'width: max-content;' in prep_html
    assert 'data-dialog-close' in prep_html


def test_planning_dialog_focus_and_language_hooks_are_present():
    with open('static/js/prep_next_day.render.js', encoding='utf-8') as handle:
        render_script = handle.read()
    with open('static/js/prep_next_day.actions.js', encoding='utf-8') as handle:
        actions_script = handle.read()
    with open('static/js/i18n.js', encoding='utf-8') as handle:
        i18n_script = handle.read()

    assert "shiftIdx === 0 ? 'data-initial-focus'" in render_script
    assert 'id="add-worker-name-input" data-initial-focus' in render_script
    assert "? hasEditPlanPendingChanges()" in actions_script
    assert 'window.RadimoI18n?.t(lockMessage)' in actions_script
    assert "['Search names or IDs', 'Namen oder IDs suchen']" in i18n_script
    assert "['Shift Load Modifier', 'Lastfaktor']" in i18n_script


def test_legacy_surfaces_are_not_part_of_the_current_version():
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    removed_routes = {
        '/balance-summary',
        '/flow-balance',
        '/api/flow-balance/data',
        '/api/live-schedule/add-worker',
        '/api/live-schedule/delete-worker',
        '/api/live-schedule/add-gap',
        '/api/live-schedule/remove-gap',
        '/api/live-schedule/update-gap',
        '/api/prep-next-day/add-worker',
        '/api/prep-next-day/delete-worker',
        '/api/prep-next-day/add-gap',
        '/api/prep-next-day/remove-gap',
        '/api/prep-next-day/update-gap',
    }
    assert routes.isdisjoint(removed_routes)
    client = _admin_client()
    for path in removed_routes:
        assert client.get(path).status_code == 404
    assert not Path('templates/admin_files_v2.html').exists()
    assert not Path('templates/admin_logs_v2.html').exists()

    app_source = Path('app.py').read_text(encoding='utf-8')
    file_ops_source = Path('data_manager/file_ops.py').read_text(encoding='utf-8')
    assert 'Cortex_{mod.upper()}_live.json' not in app_source
    assert 'attempt_initialize_data' not in app_source
    assert 'def attempt_initialize_data' not in file_ops_source
    assert 'def initialize_data(' not in file_ops_source
    assert 'def quarantine_file' not in file_ops_source

    assert normalize_skill_mod_key('ct_mdh') == 'ct_mdh'
    assert _normalize_no_overflow(['ct_mdh']) == set()
    assert _select_day_times({'monday': '08:00-12:00'}, 'Montag') is None

    dialog_script = Path('static/js/dialog_focus.js').read_text(encoding='utf-8')
    assert 'element.getClientRects().length > 0' in dialog_script

    assignment_script = Path('static/js/assignment_ui.js').read_text(encoding='utf-8')
    strict_script = Path('static/js/strict_worker_select.js').read_text(encoding='utf-8')
    assert 'Kein passender Mitarbeiter verfügbar. Bitte Normalmodus verwenden.' in assignment_script
    assert 'Server error:' not in assignment_script
    assert 'Server error:' not in strict_script
    assert 'AssignmentUI.request(endpoint)' in Path('templates/index.html').read_text(encoding='utf-8')
    assert 'AssignmentUI.request(endpoint)' in Path('templates/index_by_skill.html').read_text(encoding='utf-8')


def test_admin_files_has_valid_title_and_main_tools_navigation():
    response = _admin_client().get('/admin/files')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<title>RadIMO Cortex | Files</title>' in html
    assert 'href="/admin/tools"' in html
    assert 'href="/admin/logs"' in html
    assert 'href="/status"' in html
    primary_nav = html.split('<nav class="app-nav"', 1)[1].split('</nav>', 1)[0]
    tools_menu = html.split('<details class="system-menu"', 1)[1].split('</details>', 1)[0]
    assert 'href="/timetable?modality=all"' in primary_nav
    assert 'href="/timetable?modality=all"' not in tools_menu


def test_admin_pages_do_not_repeat_the_tools_subnavigation():
    client = _admin_client()
    removed_helper_text = (
        'Safe live-server workflow',
        'Sicherer Live-Server-Ablauf',
        'Live-view visibility and skill × modality mapping for special tasks.',
        'Sichtbarkeit in Live-Ansichten und Skill-×-Modalität-Zuordnung für Sonderaufgaben.',
        'Hard Reload Today</strong> bleibt bewusst separat',
    )
    for path in ('/admin/tools', '/admin/settings', '/admin/files', '/admin/logs', '/upload', '/status'):
        html = client.get(path).get_data(as_text=True)
        assert 'tools-nav' not in html
        assert all(text not in html for text in removed_helper_text)

    assert not Path('templates/partials/tools_nav.html').exists()

    i18n_script = Path('static/js/i18n.js').read_text(encoding='utf-8')
    assert all(text not in i18n_script for text in removed_helper_text)


def test_dashboard_selectors_use_solid_distinct_active_states():
    header_css = Path('templates/partials/header_styles.html').read_text(encoding='utf-8')
    timetable_js = Path('static/js/timetable.js').read_text(encoding='utf-8')
    timeline_js = Path('static/js/timeline.js').read_text(encoding='utf-8')

    assert 'repeating-linear-gradient' not in header_css
    assert 'box-shadow: 0 0 0 3px #fff, 0 0 0 6px' in header_css
    timetable_template = Path('templates/timetable.html').read_text(encoding='utf-8')
    assert 'buildSkillGradient' not in timeline_js
    assert 'solidBars' not in timetable_js
    assert '--modality-band' not in timeline_js
    assert 'shift-bar--modality-band' not in timetable_template
    assert 'nameCell.title = workerLabel' in timeline_js
    assert 'shift-bar__label' in timeline_js
    assert "bar.classList.add('shift-bar--multi')" in timeline_js
    assert "skillLabel.className = 'shift-bar__skill-label'" in timeline_js


def test_admin_tools_stay_compact_and_reachable_on_narrow_pages():
    client = _admin_client()

    upload_html = client.get('/upload').get_data(as_text=True)
    assert 'class="column workflow-column"' in upload_html
    assert 'class="column upload-column"' in upload_html
    assert '.upload-column {' in upload_html
    assert 'order: 1;' in upload_html

    corrections_html = client.get('/manual-adjustments').get_data(as_text=True)
    assert 'id="manual-worker-filter"' in corrections_html
    assert 'id="manual-adjusted-only"' in corrections_html
    corrections_js = Path('static/js/manual_adjustments.js').read_text(encoding='utf-8')
    assert "manual-worker-filter')?.addEventListener('input', renderWorkers)" in corrections_js
    assert "manual-adjusted-only')?.addEventListener('change', renderWorkers)" in corrections_js

    files_html = client.get('/admin/files').get_data(as_text=True)
    assert 'class="section-jumps"' in files_html
    assert 'href="#managed-files-grid"' in files_html
    assert 'href="#staged-days"' in files_html
    assert 'href="#recoverable-backups"' in files_html

    roster_html = client.get('/skill-roster').get_data(as_text=True)
    assert '.worker-admin-panel {' in roster_html
    assert 'order: -1;' in roster_html

    timetable_html = client.get('/timetable').get_data(as_text=True)
    assert 'Zurück zur Hauptseite' not in timetable_html


def test_page_titles_follow_short_naming_contract():
    client = _admin_client()
    expected_titles = {
        '/login': 'RadIMO Cortex | Admin',
        '/?modality=ct': 'RadIMO Cortex | CT Live',
        '/performance': 'RadIMO Cortex | Analysis',
        '/worker-load': 'RadIMO Cortex | Workload',
        '/prep-today': 'RadIMO Cortex | Today',
        '/prep-tomorrow': 'RadIMO Cortex | Planning',
        '/timetable': 'RadIMO Cortex | Schedule',
        '/manual-adjustments': 'RadIMO Cortex | Corrections',
        '/skill-roster': 'RadIMO Cortex | Skills',
        '/button-weights': 'RadIMO Cortex | Weights',
        '/upload': 'RadIMO Cortex | Import',
        '/admin/tools': 'RadIMO Cortex | Tools',
        '/admin/settings': 'RadIMO Cortex | Settings',
        '/admin/files': 'RadIMO Cortex | Files',
        '/admin/logs': 'RadIMO Cortex | Logs',
        '/status': 'RadIMO Cortex | Status',
    }

    for route, title in expected_titles.items():
        response = client.get(route)
        assert response.status_code == 200, route
        assert f'<title>{title}</title>' in response.get_data(as_text=True), route

    access_response = app.test_client().get('/access-login')
    assert access_response.status_code == 200
    assert '<title>RadIMO Cortex | Access</title>' in access_response.get_data(as_text=True)


def test_primary_navigation_uses_short_names_only():
    html = _admin_client().get('/admin/tools').get_data(as_text=True)

    for label in ('Analysis', 'Workload', 'Today', 'Planning', 'Live', 'Overview', 'Settings', 'Corrections', 'Skills', 'Weights', 'Import', 'Schedule'):
        assert re.search(rf'>\s*{re.escape(label)}\s*<', html)
    for legacy in ('Performance', 'Adjust Weight', 'Skill Matrix', 'Weight Matrix', 'Change Today', 'Prep Tomorrow', 'Timetable', 'Dashboard', 'Files & Recovery'):
        assert not re.search(rf'>\s*{re.escape(legacy)}\s*<', html)
