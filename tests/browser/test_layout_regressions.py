"""Rendered-page checks for navigation, workload rows and schedule editors."""
import json
import mimetypes
import os
from pathlib import Path
import re

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]
CONFIG = {
    'skills': ['aou', 'gyn', 'privat', 'notfall'],
    'modalities': ['ct', 'mr', 'xray'],
    'modality_settings': {
        'ct': {'label': 'CT'}, 'mr': {'label': 'MR'},
        'xray': {'label': 'X-RAY', 'valid_skills': ['notfall']},
    },
    'skill_settings': {}, 'initial_tab': 'today',
    'task_roles': [{'name': 'Dienst', 'type': 'shift', 'times': {'default': '08:00-16:00'}}],
}


@pytest.fixture
def page():
    from app import app
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.add_init_script('window.fetch = () => new Promise(() => {});')

        def open_page(path, sysadmin=False):
            if sysadmin:
                from routes import _log_password_fingerprint
                with client.session_transaction() as session:
                    session['logs_access'] = _log_password_fingerprint()
            response = client.get(path)
            assert response.status_code == 200
            config = {**CONFIG, 'initial_tab': 'tomorrow' if path == '/prep-tomorrow' else 'today'}
            html = re.sub(r'(<script id="page-config"[^>]*>).*?(</script>)',
                          lambda m: m[1] + json.dumps(config) + m[2],
                          response.get_data(as_text=True), flags=re.S)

            def serve(route):
                target = route.request.url.split('radimo.test', 1)[1].split('?', 1)[0]
                if target.startswith('/static/'):
                    file = ROOT / target.lstrip('/')
                    data = file.read_bytes()
                    if file.name == 'prep_next_day.actions.js':
                        data = data.split(b'// Initialize edit mode UI and load current tab (lazy loading)')[0]
                    if file.name == 'worker_load_monitor.js':
                        data = data.split(b"document.addEventListener('DOMContentLoaded'")[0]
                    route.fulfill(body=data, content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
                else:
                    route.fulfill(body=html, content_type='text/html')
            page.route('http://radimo.test/**', serve)
            page.goto('http://radimo.test' + path)
            return page
        yield open_page
        browser.close()


def save_preview(page, name):
    destination = os.environ.get('RADIMO_UI_SCREENSHOTS')
    if destination:
        folder = Path(destination); folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / (name + '.png')))


def seed_schedule(page, tab, count=35):
    page.evaluate('''({tab,count}) => {
        tableFilters[tab] = {modality:'',skill:'',hideZero:false};
        entriesData[tab] = Array.from({length:count}, (_,i) => ({worker:`Synthetic ${String(i).padStart(2,'0')} (T${i})`,
          tableShiftsArray:[{start_time:'08:00',end_time:'16:00',task:'Dienst',modifier:1,training:true,
            modalities:Object.fromEntries(MODALITIES.map(m=>[m,{row_index:i,modifier:1,skills:Object.fromEntries(SKILLS.map(s=>[s,0]))}]))}]}));
        renderTableHeader(tab); renderTable(tab);
    }''', {'tab': tab, 'count': count})


@pytest.mark.parametrize('path', ['/prep-today', '/prep-tomorrow', '/worker-load'])
def test_administration_menu_is_above_page_content(page, path):
    p = page(path)
    p.locator('.system-menu summary').click()
    save_preview(p, 'menu-' + path.strip('/'))
    links = p.locator('.system-menu__panel a')
    for i in range(links.count()):
        assert links.nth(i).evaluate('''el => {const r=el.getBoundingClientRect();
          return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}''')


def test_compact_workload_has_one_table_row_per_worker(page):
    p = page('/worker-load')
    p.evaluate('''() => {workersData = ['Anna','Berta','Clara'].map((name,i)=>({name,canonical_id:name,
      hours_worked_now:8,global_weight:10+i,balance_weight:10+i,weight_per_hour:1.25}));
      document.body.classList.add('mode-simple'); renderGlobalTable();}''')
    save_preview(p, 'workload-compact')
    rows = p.locator('#tbody-global tr.worker-row')
    assert rows.count() == 3
    boxes = [rows.nth(i).bounding_box() for i in range(3)]
    assert all(rows.nth(i).evaluate('el=>getComputedStyle(el).display') == 'table-row' for i in range(3))
    assert all(boxes[i+1]['y'] >= boxes[i]['y'] + boxes[i]['height'] - 1 for i in range(2))


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_schedule_shows_full_table_and_compact_accessible_actions(page, tab, path):
    p = page(path)
    seed_schedule(p, tab)
    save_preview(p, 'schedule-' + tab)
    table = p.locator(f'#edit-table-{tab}')
    wrapper = table.locator('..')
    assert table.locator('tbody tr').count() == 35
    assert wrapper.evaluate('el=>el.scrollHeight <= el.clientHeight+1')
    assert wrapper.evaluate('el=>getComputedStyle(el).maxHeight') == 'none'
    actions = table.locator('tbody .action-cell').first
    buttons = actions.locator('button')
    assert buttons.count() == 2
    assert buttons.nth(0).get_attribute('aria-label') == 'Bearbeiten'
    assert buttons.nth(1).get_attribute('aria-label') == 'Alle Einträge löschen'
    assert actions.bounding_box()['width'] < 85
    assert actions.evaluate('el=>getComputedStyle(el).position') == 'sticky'
    assert buttons.nth(0).inner_text().strip() == ''
    p.evaluate("() => {window.actionCalls=[]; openEditModal=(...args)=>actionCalls.push(['edit',...args]); deleteWorkerEntries=(...args)=>actionCalls.push(['delete',...args]);}")
    buttons.nth(0).click(); buttons.nth(1).click()
    assert p.evaluate('actionCalls') == [['edit',tab,0],['delete',tab,0]]
    table.locator('tbody tr').last.scroll_into_view_if_needed()
    assert table.locator('tbody tr').last.is_visible()


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_coverage_warns_only_for_existing_assignment_buttons(page, tab, path):
    p = page(path)
    seed_schedule(p, tab, 1)
    groups = p.locator(f'#coverage-gaps-{tab} .prep-coverage__group')
    assert groups.count() == 3
    xray = groups.filter(has_text='X-RAY')
    assert 'notfall' in xray.inner_text()
    assert all(skill not in xray.inner_text() for skill in ('aou','gyn','privat'))
    p.evaluate('''tab => {
      MODALITY_SETTINGS.ct.hidden_skills=['gyn'];
      SKILL_SETTINGS.privat={valid_modalities:['ct']};
      SKILL_SETTINGS.aou={hidden_modalities:['mr']};
      entriesData[tab][0].tableShiftsArray[0].modalities.xray.skills.notfall='w';
      renderCoverageGaps(tab);
    }''', tab)
    assert groups.filter(has_text='X-RAY').count() == 0
    assert 'gyn' not in groups.filter(has_text='CT').inner_text()
    assert 'privat' not in groups.filter(has_text='MR').inner_text()
    assert 'aou' not in groups.filter(has_text='MR').inner_text()


def test_yaml_editor_is_separate_and_loads_only_after_expansion(page):
    p = page('/admin/settings', sysadmin=True)
    assert p.locator('#general-settings-form').count() == 1
    assert p.locator('#full-config-editor, input[name="sysadmin_password"], input[name="log_password"]').count() == 0
    p = page('/admin/settings/advanced', sysadmin=True)
    assert p.locator('#general-settings-form').count() == 0
    assert p.locator('#full-config-editor').count() == 1
    p.evaluate("() => {window.requests=[];window.fetch=async (url, options)=>{requests.push(url);return {ok:true,text:async()=> 'sysadmin_password: synthetic\\n'}};}")
    assert p.evaluate('requests.length') == 0
    p.locator('#advanced-config summary').click()
    p.wait_for_function('document.getElementById("full-config-editor").disabled === false')
    assert p.evaluate('requests') == ['/api/admin/files/download?target=config']
    assert p.locator('#save-full-config').is_disabled()
    p.locator('#advanced-config-ack').check()
    assert p.locator('#save-full-config').is_enabled()
