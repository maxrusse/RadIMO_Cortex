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


@pytest.mark.parametrize('path', ['/prep-today', '/prep-tomorrow', '/worker-load'])
def test_unlocked_header_fits_narrow_viewport(page, path):
    p = page(path, sysadmin=True)
    p.set_viewport_size({'width': 768, 'height': 900})
    assert p.locator('button.app-header__session').inner_text() == 'Sysadmin abmelden'
    assert p.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    controls = p.locator('.app-header__actions a, .app-header__actions button, .system-menu summary')
    for index in range(controls.count()):
        control = controls.nth(index)
        if control.is_visible():
            box = control.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 768
            assert control.evaluate('''el=>{const r=el.getBoundingClientRect();
                return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}''')


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_headers_follow_page_and_horizontal_table_scrolling(page, tab, path):
    p = page(path)
    seed_schedule(p, tab)
    table = p.locator(f'#edit-table-{tab}')
    wrapper = table.locator('..')
    floating = p.locator(f'.prep-floating-header[data-table="edit-table-{tab}"]')
    assert not floating.is_visible()
    p.evaluate('window.scrollTo(0,600)')
    floating.wait_for(state='visible')
    assert 0 <= floating.bounding_box()['y'] <= 1
    assert floating.locator('thead tr').count() == 2
    save_preview(p, 'headers-scrolled-' + tab)
    wrapper.evaluate("el=>{el.style.maxWidth='400px';el.scrollLeft=100;}")
    p.wait_for_function('''tab=>{
      const wrapper=document.getElementById('edit-table-'+tab).parentElement;
      const header=document.querySelector('.prep-floating-header[data-table="edit-table-'+tab+'"]');
      return wrapper.scrollLeft > 0 && Math.abs(wrapper.scrollLeft-header.scrollLeft)<1;
    }''', arg=tab)
    for index in (0,1,-1):
        actual=table.locator('thead tr').first.locator('th').nth(index).bounding_box()
        copy=floating.locator('thead tr').first.locator('th').nth(index).bounding_box()
        assert abs(actual['x']-copy['x']) < 2
        assert abs(actual['width']-copy['width']) < 2
    wrapper.evaluate('el=>{el.scrollLeft=0}')
    p.wait_for_function("""tab => document.querySelector(`.prep-floating-header[data-table="edit-table-${tab}"]`).scrollLeft === 0""", arg=tab)
    previous=p.evaluate('tab=>sortState[tab].direction',tab)
    floating.locator('th.sortable.sort-asc, th.sortable.sort-desc').first.click()
    p.wait_for_function('''({tab,previous})=>sortState[tab].direction!==previous''', arg={'tab':tab,'previous':previous})
    p.evaluate('window.scrollTo(0,0)')
    floating.wait_for(state='hidden')


@pytest.mark.parametrize('mod_rules,skill_rules', [
    ({'valid_skills':['NOTFALL']}, {}),
    ({'valid_skills':['notfall'],'hidden_skills':['NOTFALL']}, {}),
    ({'valid_skills':['notfall']}, {'valid_modalities':['XRAY']}),
    ({'valid_skills':['notfall']}, {'hidden_modalities':['XRAY']}),
])
def test_coverage_visibility_matches_live_buttons_exactly(page,monkeypatch,mod_rules,skill_rules):
    from unittest.mock import patch
    import routes
    from app import app
    p=page('/prep-today')
    p.evaluate('''({mod,skill})=>{
        Object.assign(MODALITY_SETTINGS.xray,mod);
        SKILL_SETTINGS.notfall=skill;
    }''', {'mod':mod_rules,'skill':skill_rules})
    monkeypatch.setitem(routes.MODALITY_SETTINGS,'xray', {**routes.MODALITY_SETTINGS['xray'],**mod_rules})
    monkeypatch.setitem(routes.SKILL_SETTINGS,'notfall', {**routes.SKILL_SETTINGS['notfall'],**skill_rules})
    with patch.object(routes,'is_access_protection_enabled',return_value=False):
        response=app.test_client().get('/?modality=xray')
    assert response.status_code==200
    visible='id="skill-btn-notfall"' in response.get_data(as_text=True)
    assert p.evaluate("isCoverageButtonVisible('notfall','xray')") == visible


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_floating_header_cannot_reorder_worker_while_modal_is_open(page,tab,path):
    p=page(path)
    seed_schedule(p,tab)
    p.evaluate('() => {updatePrepOverlayTop(); window.scrollTo(0,600);}')
    floating=p.locator(f'.prep-floating-header[data-table="edit-table-{tab}"]')
    floating.wait_for(state='visible')
    p.evaluate('tab=>openEditModal(tab,15)',tab)
    assert p.locator('#edit-modal').is_visible()
    p.wait_for_function("getComputedStyle(document.getElementById('edit-modal')).top === '0px'")
    assert not floating.is_visible()
    expected=p.evaluate('editPlanDraft.worker')
    p.evaluate("tab=>{sortEntries(tab,'worker');sortEntries(tab,'worker');}",tab)
    assert p.evaluate('tab=>entriesData[tab][currentEditEntry.groupIdx].worker',tab)==expected
    p.evaluate('''async () => {window.confirm=()=>false; await deleteShiftFromModal(0);}''')
    assert p.evaluate('editPlanDraft.worker')==expected
    assert p.evaluate('editPlanDraft.shifts.length')==1
    p.evaluate('closeModal(true)')
    floating.wait_for(state='visible')
    p.evaluate("document.getElementById('break-popup').classList.add('show')")
    assert not floating.is_visible()
    p.evaluate("tab=>{sortEntries(tab,'worker');sortEntries(tab,'worker');}",tab)
    assert p.evaluate('tab=>entriesData[tab][0].worker',tab).startswith('Synthetic 00')
    p.evaluate("document.getElementById('break-popup').classList.remove('show')")
    floating.wait_for(state='visible')
    p.evaluate("tab=>{sortEntries(tab,'worker');sortEntries(tab,'worker');}",tab)
    assert p.evaluate('tab=>entriesData[tab][0].worker',tab).startswith('Synthetic 34')


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_dialog_masks_body_controls_when_opened_immediately_after_scroll(page,tab,path):
    p=page(path)
    seed_schedule(p,tab)
    top=p.evaluate('''tab=>{
      window.scrollTo(0,0); updatePrepOverlayTop();
      window.scrollTo(0,600); openEditModal(tab,15);
      return getComputedStyle(document.getElementById('edit-modal')).top;
    }''',tab)
    assert top=='0px'
    hit_tests=p.locator(f'#edit-table-{tab} tbody .row-action').evaluate_all('''buttons=>{
      const visible=buttons.filter(button=>{const r=button.getBoundingClientRect();
        return r.top+r.height/2>=0 && r.top+r.height/2<innerHeight;});
      return {checked:visible.length,exposed:visible.filter(button=>{const r=button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}).length};
    }''')
    assert hit_tests['checked']>0
    assert hit_tests['exposed']==0


@pytest.mark.parametrize('tab,path', [('today','/prep-today'), ('tomorrow','/prep-tomorrow')])
def test_header_resynchronizes_after_modal_resize_and_cancel(page,tab,path):
    p=page(path)
    seed_schedule(p,tab)
    table=p.locator(f'#edit-table-{tab}')
    wrapper=table.locator('..')
    wrapper.evaluate("el=>{el.style.maxWidth='400px';el.scrollLeft=100;}")
    p.evaluate('window.scrollTo(0,600)')
    floating=p.locator(f'.prep-floating-header[data-table="edit-table-{tab}"]')
    floating.wait_for(state='visible')
    p.evaluate('tab=>openEditModal(tab,15)',tab)
    floating.wait_for(state='hidden')
    p.set_viewport_size({'width':900,'height':900})
    p.evaluate('closeModal(true)')
    floating.wait_for(state='visible')
    p.wait_for_function('''tab=>{
      const source=document.getElementById('edit-table-'+tab).parentElement;
      const clone=document.querySelector('.prep-floating-header[data-table="edit-table-'+tab+'"]');
      return source.scrollLeft>0 && source.scrollLeft===clone.scrollLeft;
    }''',arg=tab)
    first=table.locator('thead th').first.bounding_box()
    cloned=floating.locator('thead th').first.bounding_box()
    assert abs(first['x']-cloned['x'])<2
