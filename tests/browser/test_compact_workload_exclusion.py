"""Verify compact-only exclusion, unchanged percentage bars and absolute delta."""
from pathlib import Path
import pytest
playwright=pytest.importorskip('playwright.sync_api')
ROOT=Path(__file__).resolve().parents[2]


def test_compact_exclusion_and_both_deviation_units():
    with playwright.sync_playwright() as driver:
        browser=driver.chromium.launch();page=browser.new_page()
        page.set_content('<script id="page-config" type="application/json">{"skills":["cvt"],"modalities":["ct"]}</script>'
                         '<table id="table-global"><tbody id="tbody-global"></tbody></table>'
                         '<table id="table-advanced-count"><thead id="thead-advanced-count"></thead><tbody id="tbody-advanced-count"></tbody></table>')
        for file in ('worker_name_utils.js','worker_load_monitor.js'):
            page.add_script_tag(path=str(ROOT/'static/js'/file))
        page.evaluate('''() => {
            const worker=(name,ratio,excluded=false)=>({canonical_id:name,name,weight_per_hour:ratio,
                hours_worked_now:2,global_weight:ratio*2,balance_weight:ratio*2,
                exclude_from_compact_stats:excluded,
                modalities:{ct:{skill_counts:{cvt:1},assignment_total:1}},skills:{cvt:1}});
            workersData=[worker('Low',1),worker('High',3),worker('Offset',100,true)];
            expandedWorkerId='Offset'; // a refresh must not reinsert an excluded detail row
            renderGlobalTable();
        }''')
        assert page.locator('#tbody-global tr.worker-row').count()==2
        assert 'Offset' not in page.locator('#tbody-global').inner_text()
        assert page.locator('#tbody-global tr.totals-row td').nth(4).inner_text()=='8.00'
        labels=page.locator('.dev-label').all_inner_texts()
        assert any('+50 %' in s and '+1.00 /h' in s for s in labels)
        assert any('-50 %' in s and '-1.00 /h' in s for s in labels)
        assert page.locator('.dev-bar__fill').first.evaluate('(e)=>e.style.width')=='25%'
        # Visual filters select rows but do not change the compact median.
        page.evaluate("workersData[0].skills.cvt=0;filters.skill='cvt';renderGlobalTable()")
        assert '+50 %' in page.locator('.dev-label').inner_text()
        page.evaluate("filters.skill='';renderAdvancedTable('count')")
        assert 'Offset' in page.locator('#table-advanced-count tbody').inner_text()
        assert page.evaluate('formatAbsoluteDeviation({hours_worked_now:0,weight_per_hour:3},2)')=='–'
        browser.close()
