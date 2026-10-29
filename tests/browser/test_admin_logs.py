"""Exercise log viewer races, filters, copying and keyboard tab navigation."""
from pathlib import Path

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def log_page():
    from flask import Flask
    from unittest.mock import patch
    import routes

    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.secret_key = 'test'
    app.register_blueprint(routes.routes)
    with patch('routes.has_admin_access', return_value=True):
        html = app.test_client().get('/admin/logs').get_data(as_text=True)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.route('http://radimo.test/**', lambda route: route.fulfill(content_type='text/html', body=''))
        page.goto('http://radimo.test/')
        page.set_content(html)
        page.add_style_tag(path=str(ROOT / 'static/styles.css'))
        page.evaluate('''() => {
            document.getElementById('admin-logs-config').textContent = JSON.stringify([
                {key: 'selection', exists: true, path: 'selection.log', label: 'RadIMO'},
                {key: 'import', exists: true, path: 'import.log', label: 'Import'}]);
            document.getElementById('preview-source').innerHTML =
                '<option value="selection">RadIMO</option><option value="import">Import</option>';
            window.pending = [];
            window.fetch = () => new Promise(resolve => window.pending.push(resolve));
            window.deliver = (index, text) => window.pending[index]({ok: true,
                json: async () => ({success: true, exists: true, text, modified: '12:00'})});
            Object.defineProperty(navigator, 'clipboard', {value: {
                writeText: async text => { window.copiedText = text; }
            }, configurable: true});
        }''')
        page.add_script_tag(path=str(ROOT / 'static/js/admin_logs.js'))
        yield page
        browser.close()


def test_old_response_cannot_overwrite_current_source_even_after_switching_back(log_page):
    page = log_page
    page.locator('#tab-technical').click()
    page.locator('#preview-source').select_option('import')
    page.locator('#preview-source').select_option('selection')
    page.evaluate("deliver(2, '[INFO] newest response')")
    page.wait_for_function("document.querySelector('#log-preview').textContent.includes('newest')")
    page.evaluate("deliver(0, '[ERROR] stale selection'); deliver(1, '[ERROR] stale import')")
    page.wait_for_function("document.querySelector('#refresh-preview').disabled === false")
    assert 'newest response' in page.locator('#log-preview').inner_text()
    assert 'stale' not in page.locator('#log-preview').inner_text()
    page.locator('#tab-downloads').click()
    page.keyboard.press('ArrowLeft')
    assert page.locator('#panel-technical').is_visible()


def test_copy_obeys_filter_and_is_disabled_without_matches(log_page):
    page = log_page
    page.locator('#tab-technical').click()
    page.evaluate("deliver(0, '[INFO] info\\n[ERROR] error')")
    page.wait_for_function("document.querySelector('#refresh-preview').disabled === false")
    page.locator('[data-level="error"]').click()
    page.locator('#copy-preview').click()
    assert page.evaluate('window.copiedText') == '[ERROR] error\n'
    page.locator('#preview-source').select_option('import')
    page.evaluate("deliver(1, '[INFO] no errors')")
    page.wait_for_function("document.querySelector('#refresh-preview').disabled === false")
    assert page.locator('#copy-preview').is_disabled()
