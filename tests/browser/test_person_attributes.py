"""Browser regression checks; requires Playwright and its Chromium browser."""
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
MALICIOUS = 'Name " onmouseover="window.injected = true" data-extra=" & <img src=x onerror="window.injected = true"> (ID)'


@pytest.fixture
def page():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.route("http://radimo.test/**", lambda route: route.fulfill(
            content_type="text/html", body='<html><head></head><body></body></html>'
        ))
        page.goto("http://radimo.test/")
        yield page
        browser.close()


@pytest.mark.parametrize("expanded", [False, True])
def test_worker_identifier_stays_a_single_attribute(page, expanded):
    page.set_content('<script id="page-config" type="application/json">{}</script><table><tbody id="tbody-global"></tbody></table>')
    page.add_script_tag(path=str(ROOT / "static/js/worker_load_monitor.js"))
    page.evaluate("""({name, expanded}) => {
        workersData = [{ canonical_id: name, name, hours_worked_now: 0, global_weight: 1 }];
        expandedWorkerId = expanded ? name : null;
        renderGlobalTable();
    }""", {"name": MALICIOUS, "expanded": expanded})
    row = page.locator("tr.worker-row")
    assert row.get_attribute("data-worker-id") == MALICIOUS
    assert row.locator(".worker-col").inner_text() == MALICIOUS
    assert page.locator("[onmouseover], [onerror], [data-extra], img").count() == 0
    row.hover()
    assert page.evaluate("window.injected === true") is False
    if expanded:
        assert page.locator("tr.detail-row").get_attribute("data-worker-id") == MALICIOUS
        assert page.locator("form.correction-form").count() == 1


def test_live_history_name_stays_text_and_title(page):
    page.set_content('<div id="liveHistory"></div>')
    page.evaluate("entry => localStorage.setItem('radimo.live.history', JSON.stringify([entry]))", {
        "person": MALICIOUS, "time": "12:00", "context": "A · CT", "abbreviation": "ID",
    })
    page.add_script_tag(path=str(ROOT / "static/js/live_history.js"))
    page.evaluate("LiveHistory.render()")
    person = page.locator(".live-history__person")
    assert person.get_attribute("title") == MALICIOUS
    assert person.inner_text() == MALICIOUS
    assert page.locator("[onmouseover], [onerror], [data-extra], img").count() == 0
    person.hover()
    assert page.evaluate("window.injected === true") is False
