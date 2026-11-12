"""Check the real Schedule timer against its rendered time axis."""
from datetime import datetime
from pathlib import Path

import pytest

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]


def test_schedule_clock_tracks_time_and_responsive_name_column():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 800})
        page.clock.install(time=datetime(2026, 11, 12, 10, 0, 0))
        page.set_content('<div id="timeline-grid" class="timeline-grid">'
                         '<div id="time-header"></div></div>')
        page.add_style_tag(path=str(ROOT / 'static/styles.css'))
        page.add_style_tag(content='.timeline-grid {--worker-col-width:clamp(250px,20vw,310px)}')
        for name in ('worker_name_utils.js', 'timeline.js', 'timeline_feed.js', 'timetable.js'):
            page.add_script_tag(path=str(ROOT / 'static/js' / name))
        page.evaluate("""() => {
            initTimetableConfig({modalities:{ct:{}},skillColumns:['aou'],
                dataByModality:{ct:[{PPL:'Synthetic',row_index:0,
                    start_time:'08:00',end_time:'16:00',aou:1}]}});
            buildTimeline();
        }""")

        def position():
            return page.evaluate("""() => {
                const axis=document.getElementById('time-header').getBoundingClientRect();
                const line=document.getElementById('current-time-line').getBoundingClientRect();
                return (line.x-axis.x)/axis.width;
            }""")

        assert position() == pytest.approx(4/14, abs=0.00003)
        before = position()
        page.clock.fast_forward(10000)
        assert position() - before == pytest.approx(10/(14*3600), abs=0.00003)
        page.set_viewport_size({"width": 900, "height": 800})
        assert position() == pytest.approx((4+10/3600)/14, abs=0.00003)
        page.clock.fast_forward(60000)
        assert position() == pytest.approx((4+70/3600)/14, abs=0.00003)
        page.clock.fast_forward(11*3600*1000)
        assert page.locator('#current-time-line').count() == 0
        browser.close()
