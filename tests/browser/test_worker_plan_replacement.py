"""Regression checks for replacing every row in an existing worker's popup."""
import copy
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def popup():
    config = {
        'skills': ['aou', 'cvt', 'mdh'], 'modalities': ['ct', 'mr', 'xray'],
        'worker_names': {'Synthetic (TEST)': 'Synthetic'},
        'task_roles': [
            {'name': 'Dienst', 'type': 'shift', 'counts_for_hours': True,
             'times': {'default': '08:00-16:00'}},
            {'name': 'Anderer Dienst', 'type': 'shift', 'counts_for_hours': True,
             'times': {'default': '09:00-17:00'}},
            {'name': 'Urlaub', 'type': 'gap', 'times': {'default': '08:00-16:00'}},
        ],
    }
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.set_content('<script id="page-config" type="application/json">'
                         + json.dumps(config) + '</script><div id="edit-modal">'
                         '<div id="modal-title"></div><div id="modal-content"></div>'
                         '<button id="modal-save-button"></button></div>')
        page.evaluate('''() => {
            window.messages = []; window.confirm = () => true;
            window.RadimoUI = {text: (en, de) => de, notify: (type, text) => messages.push({type, text})};
            window.pending = [];
            window.fetch = () => new Promise(resolve => pending.push(resolve));
            window.deliver = (index, value = 1, ok = true) => pending[index]({ok,
                json: async () => ({task: 'Dienst', row_type: 'shift', start_time: '08:00',
                    end_time: '16:00', modifier: 1, training: true, counts_for_hours: true,
                    skills_by_modality: Object.fromEntries(['ct', 'mr', 'xray'].map(m =>
                        [m, {aou: value, cvt: value, mdh: value}]))})});
        }''')
        for name in ('worker_name_utils.js', 'prep_next_day.config.js',
                     'prep_next_day.state.js', 'prep_next_day.render.js'):
            page.add_script_tag(path=str(ROOT / 'static/js' / name))
        actions = (ROOT / 'static/js/prep_next_day.actions.js').read_text()
        # No application startup polling: every network response is controlled.
        page.add_script_tag(content=actions.split('// Initialize edit mode UI and load current tab (lazy loading)')[0])
        page.evaluate('''() => {
            window.sent = [];
            postJsonWithSnapshot = async (tab, url, payload) => {sent.push(payload); return {success:true}};
            loadData = async () => {};
            window.setup = (kind = 'gap', tab = 'today') => {
                currentEditEntry = null; editPlanDraft = null; sent = []; pending = []; messages = [];
                const make = (gap, index) => ({start_time: index ? '12:00' : '08:00',
                    end_time: index ? '16:00' : '12:00', modifier:1, training:!gap,
                    counts_for_hours:!gap, task:gap?'Urlaub':'Dienst',
                    row_type:gap?'gap':'shift', is_gap_entry:gap,
                    modalities:Object.fromEntries(MODALITIES.map(m => [m,
                        {row_index:index, skills:{aou:gap?-1:1,cvt:gap?-1:1,mdh:gap?-1:1}}]))});
                const rows = kind === 'mixed' ? [make(true,0), make(false,1)] : [make(kind==='gap',0)];
                entriesData[tab] = [{worker:'Synthetic (TEST)', tableShiftsArray:rows}];
                currentTab = tab; openEditModal(tab,0);
            };
            window.setSkills = (prefix, value) => {
                for (const m of MODALITIES) for (const skill of SKILLS) {
                    const el = document.getElementById(`${prefix}-${m}-skill-${skill}`);
                    el.value = value; el.dispatchEvent(new Event('change'));
                }
            };
        }''')
        yield page
        browser.close()


@pytest.fixture
def save_and_reload(tmp_path, monkeypatch):
    import routes
    from config import allowed_modalities, SKILL_COLUMNS
    from data_manager import file_ops
    from state_manager import StateManager

    state = StateManager.get_instance()
    original_live = copy.deepcopy(state.modality_data)
    original_staged = copy.deepcopy(state.staged_modality_data)
    original_global = copy.deepcopy(state.global_worker_data)
    original_paths = dict(state.unified_schedule_paths)
    monkeypatch.setattr(file_ops, 'UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(file_ops, '_skill_roster_auto_import_enabled', lambda: False)
    monkeypatch.setattr(routes, 'LOG_ROOT', tmp_path / 'logs')
    monkeypatch.setattr(routes, 'STAGED_DAY_DIR', tmp_path / 'backups/staged_days')
    state.unified_schedule_paths['live'] = str(tmp_path / 'backups/Cortex_ALL_live.json')
    state.unified_schedule_paths['scheduled'] = str(tmp_path / 'backups/Cortex_ALL_scheduled.json')
    app = Flask(__name__)
    app.secret_key = 'test'
    app.register_blueprint(routes.routes)
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True

    def persist(payload, tab):
        staged = tab == 'tomorrow'
        store = state.staged_modality_data if staged else state.modality_data
        for modality in allowed_modalities:
            row = {'PPL': 'Synthetic (TEST)', 'start_time': datetime.strptime('08:00', '%H:%M').time(),
                   'end_time': datetime.strptime('16:00', '%H:%M').time(), 'Modifier': 1,
                   'tasks': 'Urlaub', 'row_type': 'gap_segment', 'counts_for_hours': False,
                   'training': False, **{skill: -1 for skill in SKILL_COLUMNS}}
            store[modality].update(working_hours_df=pd.DataFrame([row]), target_date=date(2026, 11, 2))
        if staged:
            payload = {**payload, 'target_date': '2026-11-02'}
        endpoint = '/api/prep-next-day/apply-worker-plan' if staged else '/api/live-schedule/apply-worker-plan'
        response = client.post(endpoint, json=payload)
        assert response.status_code == 200, response.get_json()
        path = (tmp_path / 'backups/staged_days/Cortex_ALL_staged_2026-11-02.json'
                if staged else Path(state.unified_schedule_paths['live']))
        assert file_ops._load_unified_backup(str(path), use_staged=staged)
        return {mod: store[mod]['working_hours_df'] for mod in allowed_modalities}

    yield persist
    for destination, original in ((state.modality_data, original_live),
                                  (state.staged_modality_data, original_staged),
                                  (state.global_worker_data, original_global),
                                  (state.unified_schedule_paths, original_paths)):
        destination.clear()
        destination.update(original)
    state.invalidate_work_hours_cache()


def test_replacement_sequences_preserve_every_skill_value_after_save_and_reload(popup, save_and_reload):
    page = popup
    # Also exercise adding the replacement before deleting the original rows.
    for tab in ('today', 'tomorrow'):
        for kind in ('gap', 'shift', 'mixed'):
            for order in ('delete_first', 'add_first'):
                for timing in ('before_add', 'after_add'):
                    for value in ('-1', '0', 'w', '1'):
                        context = (tab, kind, order, timing, value)
                        page.evaluate('([kind,tab]) => setup(kind,tab)', [kind, tab])
                        if order == 'delete_first':
                            page.evaluate('async () => {while(editPlanDraft.shifts.length) await deleteShiftFromModal(0)}')
                        page.evaluate('() => deliver(pending.length-1)')
                        page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
                        if timing == 'before_add':
                            page.evaluate('v => setSkills("modal-add",v)', value)
                        page.evaluate('() => addShiftFromModal()')
                        if order == 'add_first':
                            page.evaluate('async () => {while(editPlanDraft.shifts.length>1) await deleteShiftFromModal(0)}')
                        if timing == 'after_add':
                            page.evaluate('v => setSkills("edit-shift-0",v)', value)
                        page.evaluate('() => saveModalChanges()')
                        payload = page.evaluate('() => sent[0]')
                        assert payload and len(payload['shifts']) == 1, context
                        assert len(payload['shifts'][0]['modalities']) == 3, context
                        frames = save_and_reload(payload, tab)
                        for frame in frames.values():
                            assert len(frame) == 1, context
                            for skill in ('aou', 'cvt', 'mdh'):
                                assert str(frame.iloc[0][skill]) == value, context


def test_pending_or_failed_preview_cannot_add_uninitialized_shift(popup):
    page = popup
    page.evaluate('() => setup()')
    page.evaluate('() => deleteShiftFromModal(0)')
    assert page.locator('#modal-add-submit').is_disabled()
    assert page.locator('#modal-add-ct-skill-aou').is_disabled()
    page.evaluate('() => addShiftFromModal()')
    assert page.evaluate('editPlanDraft.shifts.length') == 0
    page.evaluate('() => deliver(pending.length-1,1,false)')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "failed"')
    assert page.locator('#modal-add-submit').is_disabled()
    page.evaluate('() => addShiftFromModal()')
    assert page.evaluate('editPlanDraft.shifts.length') == 0
    page.locator('#modal-add-preview-retry').evaluate('el => el.click()')
    page.evaluate('() => deliver(pending.length-1)')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    assert page.locator('#modal-add-submit').is_enabled()


def test_old_form_and_out_of_order_preview_cannot_overwrite_manual_skills(popup):
    page = popup
    page.evaluate('() => setup()')  # pending[0] belongs to the original form.
    page.evaluate('() => deleteShiftFromModal(0)')  # pending[1] belongs to its replacement.
    page.evaluate('() => {onModalTaskChange()}')  # pending[2] is the latest request.
    page.evaluate('() => deliver(2,"w")')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    page.evaluate('() => setSkills("modal-add","0")')
    page.evaluate('() => {deliver(0,1);deliver(1,-1)}')
    assert page.locator('#modal-add-ct-skill-aou').input_value() == '0'
    assert page.locator('#modal-add-submit').is_enabled()


def test_training_toggle_keeps_manual_base_skills_and_times(popup):
    page = popup
    page.evaluate('() => setup()')
    page.evaluate('() => deliver(0)')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    page.evaluate('''() => {setSkills('modal-add','w');
        document.getElementById('modal-add-start').value='09:30';
        document.getElementById('modal-add-training').checked=false;
        onModalAddTrainingChange(false);}''')
    assert page.locator('#modal-add-ct-skill-aou').input_value() == '-1'
    page.evaluate('''() => {document.getElementById('modal-add-training').checked=true;
        onModalAddTrainingChange(true);}''')
    assert page.locator('#modal-add-ct-skill-aou').input_value() == 'w'
    assert page.locator('#modal-add-start').input_value() == '09:30'
    assert page.evaluate('pending.length') == 1


def test_preview_for_deleted_shift_cannot_change_replacement_at_same_index(popup):
    page = popup
    page.evaluate('() => setup("shift")')
    page.evaluate('() => {window.oldPreview=refreshEditShiftFromPreview(0,"Dienst")}')
    page.evaluate('() => deleteShiftFromModal(0)')
    page.evaluate('() => deliver(2)')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    page.evaluate('() => {setSkills("modal-add","w");addShiftFromModal()}')
    page.evaluate('() => deliver(1,-1)')
    page.evaluate('() => oldPreview')
    assert page.evaluate('editPlanDraft.shifts[0].modalities.ct.skills.aou') == 'w'


def test_late_existing_shift_preview_preserves_newer_manual_edit(popup):
    page = popup
    page.evaluate('() => setup("shift")')
    page.evaluate('() => {window.oldPreview=refreshEditShiftFromPreview(0,"Dienst")}')
    page.evaluate('() => setSkills("edit-shift-0","w")')
    page.evaluate('() => deliver(1,-1)')
    page.evaluate('() => oldPreview')
    assert page.evaluate('editPlanDraft.shifts[0].modalities.ct.skills.aou') == 'w'


def test_gap_to_work_task_reenables_training_without_old_gap_values(popup):
    page = popup
    page.evaluate('() => setup()')
    page.evaluate('''() => {const task=document.getElementById('modal-add-task');
        task.value=Array.from(task.options).find(option=>option.dataset.type==='gap').value;
        onModalTaskChange();}''')
    assert page.locator('#modal-add-training').is_disabled()
    assert not page.locator('#modal-add-training').is_checked()
    page.evaluate('''() => {document.getElementById('modal-add-task').value='Dienst';onModalTaskChange()}''')
    page.evaluate('() => deliver(pending.length-1,"w")')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    assert page.locator('#modal-add-training').is_enabled()
    assert page.locator('#modal-add-training').is_checked()
    assert page.locator('#modal-add-ct-skill-aou').input_value() == 'w'


def test_saved_passive_worker_gets_explicit_filter_feedback(popup):
    page = popup
    page.evaluate('() => setup()')
    page.evaluate('() => deleteShiftFromModal(0)')
    page.evaluate('() => deliver(pending.length-1)')
    page.wait_for_function('document.getElementById("modal-add-task").dataset.previewState === "ready"')
    page.evaluate('() => {setSkills("modal-add","0");addShiftFromModal()}')
    page.evaluate('''() => {loadData = async () => {
        dataLoaded.today = true;
        entriesData.today = [{worker:sent[0].worker,tableShiftsArray:sent[0].shifts}];
    }}''')
    page.evaluate('() => saveModalChanges()')
    assert page.evaluate('sent[0].shifts.length') == 1
    assert 'durch die aktuellen Filter ausgeblendet' in page.evaluate('messages[messages.length-1].text')
