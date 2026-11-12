"""Detail cells must show booking totals and distinguish incomplete old history."""
from pathlib import Path

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]


def test_detail_cell_uses_slash_and_actual_strict_total():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.set_content('<script id="page-config" type="application/json">{}</script><table><tbody><tr id="row"></tr></tbody></table>')
        page.add_script_tag(path=str(ROOT / 'static/js/worker_load_monitor.js'))
        page.evaluate('''() => {
            window.draw = details => {
                const worker={modalities:{ct:{skill_counts:{cvt:2},skill_weight_details:{cvt:details}}}};
                document.getElementById('row').innerHTML=assignmentWeightCell(worker,'ct','cvt');
            };
            draw({count:2,weight:3.2,exact:true});
        }''')
        cell = page.locator('#row td')
        assert cell.inner_text() == '2 / 3.20'
        assert cell.get_attribute('title') is None
        page.evaluate('draw({count:2,weight:3.2,exact:false})')
        assert cell.inner_text() == '2 / 3.20'
        assert cell.get_attribute('title') is None
        page.evaluate('draw({count:1,weight:1.6,exact:true})')
        assert cell.inner_text() == '2 / –'
        assert cell.get_attribute('title') is None
        page.evaluate('draw(null)')
        assert cell.inner_text() == '2 / –'
        browser.close()
