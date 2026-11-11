"""Verify real clipboard contents, including internal plain-HTTP live pages."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def browser():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        yield browser
        browser.close()


def plain_page(browser):
    page = browser.new_page()
    page.route('http://radimo-copy.test/**', lambda route: route.fulfill(
        content_type='text/html', body='<button id="copy">Copy</button><input id="paste"><textarea id="editor"></textarea><span id="liveCopyStatus"></span><div id="liveHistory"></div>'))
    page.goto('http://radimo-copy.test/')
    assert page.evaluate('window.isSecureContext') is False
    assert page.evaluate('typeof navigator.clipboard') == 'undefined'
    page.add_script_tag(path=str(ROOT / 'static/js/clipboard.js'))
    return page


def paste(page):
    target=page.locator('#paste')
    target.fill('')
    target.focus()
    target.press('Control+V')
    return target.input_value()


@pytest.mark.parametrize('modern_rejects', [False, True])
def test_plain_http_fallback_copies_real_text(browser, modern_rejects):
    page=plain_page(browser)
    if modern_rejects:
        page.evaluate('''() => {window.modernCalls=0;Object.defineProperty(navigator,'clipboard',{
          configurable:true,value:{writeText:async()=>{modernCalls++;throw new DOMException('Denied','NotAllowedError')}}});}''')
    page.evaluate("() => {document.getElementById('copy').onclick=async()=>{window.copied=await RadimoClipboard.copy('HTTP_FALLBACK');};}")
    page.locator('#copy').click()
    page.wait_for_function('window.copied === true')
    assert paste(page)=='HTTP_FALLBACK'
    if modern_rejects:
        assert page.evaluate('modernCalls')==1
    assert page.locator('textarea').count()==1


def test_secure_page_prefers_modern_clipboard(browser):
    context=browser.new_context(permissions=['clipboard-read','clipboard-write'])
    page=context.new_page()
    page.route('https://radimo-copy.test/**',lambda route:route.fulfill(content_type='text/html',body='<button id="copy">Copy</button>'))
    page.goto('https://radimo-copy.test/')
    assert page.evaluate('window.isSecureContext') is True
    page.add_script_tag(path=str(ROOT/'static/js/clipboard.js'))
    page.evaluate("() => {window.legacyCalls=0;document.execCommand=()=>{legacyCalls++;return false};document.getElementById('copy').onclick=async()=>{window.copied=await RadimoClipboard.copy('MODERN_COPY')};}")
    page.locator('#copy').click()
    page.wait_for_function('window.copied === true')
    assert page.evaluate('navigator.clipboard.readText()')=='MODERN_COPY'
    assert page.evaluate('legacyCalls')==0
    context.close()


@pytest.mark.parametrize('legacy_throws', [False,True])
def test_failed_copy_is_truthful_cleans_up_and_restores_selection(browser,legacy_throws):
    page=plain_page(browser)
    page.locator('#editor').fill('Keep this selected text')
    page.evaluate('''throws => {
      document.execCommand=()=>{if(throws)throw Error('Denied');return false};
      const editor=document.getElementById('editor');editor.focus();editor.setSelectionRange(5,9);
      editor.addEventListener('keydown',async event=>{if(event.key==='F2'){
        event.preventDefault();window.copied=await RadimoClipboard.copy('SHOULD_FAIL');}});
    }''',legacy_throws)
    page.locator('#editor').press('F2')
    page.wait_for_function('window.copied === false')
    assert page.locator('textarea').count()==1
    assert page.evaluate('document.activeElement.id')=='editor'
    assert page.evaluate('[editor.selectionStart,editor.selectionEnd]')==[5,9]


def test_failure_retry_copies_without_another_assignment(browser):
    page=plain_page(browser)
    page.add_script_tag(path=str(ROOT/'static/js/live_history.js'))
    page.evaluate('''async () => {
      window.originalCopy=document.execCommand.bind(document);document.execCommand=()=>false;
      await LiveHistory.showAssignment({person:'Synthetic (RETRY_TEST)',context:'CT'});
    }''')
    assert page.locator('#liveCopyStatus').get_attribute('class').endswith('is-error')
    page.evaluate('document.execCommand=window.originalCopy')
    page.locator('[data-copy-abbreviation="RETRY_TEST"]').click()
    page.wait_for_function("document.getElementById('liveCopyStatus').classList.contains('is-ok')")
    assert paste(page)=='RETRY_TEST'
    assert page.evaluate("JSON.parse(localStorage.getItem('radimo.live.history')).length")==1


@pytest.mark.parametrize('path,button,abbreviation',[
    ('/?modality=ct','#skill-btn-notfall','LIVE_MODALITY_TEST'),
    ('/by-skill?skill=notfall','#mod-btn-ct','LIVE_SKILL_TEST'),
])
def test_actual_live_assignment_and_history_copy_on_plain_http(browser,path,button,abbreviation):
    from app import app
    client=app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in']=True
    response=client.get(path)
    assert response.status_code==200
    html=response.get_data(as_text=True)
    page=browser.new_page()
    requests=[]
    def serve(route):
        target=urlparse(route.request.url).path
        if target.startswith('/static/'):
            file=ROOT/target.lstrip('/')
            route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        elif target.startswith('/api/'):
            requests.append(target)
            route.fulfill(content_type='application/json',body=json.dumps({'selected_person':f'Synthetic ({abbreviation})'}))
        else:
            route.fulfill(content_type='text/html',body=html)
    page.route('http://radimo-copy.test/**',serve)
    page.goto('http://radimo-copy.test'+path)
    assert page.evaluate('window.isSecureContext') is False
    assert page.evaluate('typeof navigator.clipboard')=='undefined'
    page.locator(button).click()
    page.wait_for_function("document.getElementById('liveCopyStatus')?.classList.contains('is-ok')")
    assert page.locator('.live-result__person').inner_text()==f'Synthetic ({abbreviation})'
    page.evaluate("() => {const input=document.createElement('input');input.id='paste';document.body.appendChild(input);}")
    assert paste(page)==abbreviation
    # Replace the clipboard with other text, then re-copy history without a new API request.
    page.locator('#paste').fill('OTHER_CLIPBOARD_TEXT')
    page.locator('#paste').press('Control+A');page.locator('#paste').press('Control+C')
    before=len(requests)
    page.locator('[data-history-copy="0"]').click()
    page.wait_for_function("document.querySelector('[data-history-copy=\"0\"]').classList.contains('is-copied')")
    assert paste(page)==abbreviation
    assert len(requests)==before
