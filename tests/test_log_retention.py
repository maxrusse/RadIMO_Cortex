from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging

import pytest

from lib.log_retention import RetentionFileHandler, maintain_logs


NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def test_default_hundred_days(tmp_path):
    path = tmp_path / 'changes.jsonl'
    entries = [
        {'date': '2026-07-22', 'id': 'expired'},
        {'date': '2026-07-23', 'id': 'boundary'},
        {'date': '2026-10-30', 'id': 'today'},
    ]
    path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries) + 'broken\n')
    maintain_logs(tmp_path, now=NOW)
    retained = [json.loads(line) for line in path.read_text().splitlines()]
    assert [entry['id'] for entry in retained] == ['boundary', 'today']


def test_technical_multiline_records_and_usage_csv(tmp_path):
    path = tmp_path / 'selection.log'
    path.write_text('2026-10-28 12:00:00 old\nold traceback\n2026-10-30 12:00:00 new\nnew traceback\n')
    rotated = tmp_path / 'selection.log.1'
    rotated.write_text('2026-10-28 12:00:00 old\n')
    usage = tmp_path / 'usage_stats' / 'usage_stats.csv'
    usage.parent.mkdir()
    usage.write_text('date,count\n2026-10-28,1\n2026-10-30,2\n')
    unknown = tmp_path / 'unrelated.txt'
    unknown.write_text('do not touch')
    inode = path.stat().st_ino
    maintain_logs(tmp_path, 1, now=NOW)
    assert path.read_text() == '2026-10-30 12:00:00 new\nnew traceback\n'
    assert path.stat().st_ino == inode
    assert not rotated.exists()
    assert usage.read_text().splitlines() == ['date,count', '2026-10-30,2']
    assert unknown.read_text() == 'do not touch'


def test_periodic_maintenance_settings_changes_and_force(tmp_path):
    assert maintain_logs(tmp_path, now=NOW)
    assert not maintain_logs(tmp_path, now=NOW)
    assert maintain_logs(tmp_path, 2, now=NOW)
    assert maintain_logs(tmp_path, 2, now=NOW, force=True)


@pytest.mark.parametrize('days', [0, -1, True, '100', 1.5])
def test_invalid_retention_rejected(tmp_path, days):
    with pytest.raises(ValueError):
        maintain_logs(tmp_path, days, now=NOW)


def test_concurrent_audit_appends_and_maintenance_preserve_records(tmp_path):
    from lib.change_audit import append_entry
    path = tmp_path / 'changes.jsonl'
    def append(index):
        append_entry(path, {'date': '2026-10-30', 'id': index})
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(append, index) for index in range(60)]
        futures += [pool.submit(maintain_logs, tmp_path, 100, now=NOW, force=True)]
        for future in futures:
            future.result()
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert {entry['id'] for entry in entries} == set(range(60))


def test_handler_preserves_live_descriptor_after_cleanup(tmp_path):
    path = tmp_path / 'selection.log'
    path.write_text('2026-10-28 12:00:00 old\n')
    handler = RetentionFileHandler(path)
    handler.setFormatter(logging.Formatter('2026-10-30 12:00:00 %(message)s'))
    try:
        maintain_logs(tmp_path, 1, now=NOW)
        handler.emit(logging.makeLogRecord({'msg': 'new'}))
    finally:
        handler.close()
    assert path.read_text() == '2026-10-30 12:00:00 new\n'


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / 'outside'
    outside.write_text('2026-01-01 old\n')
    (tmp_path / 'selection.log').symlink_to(outside)
    maintain_logs(tmp_path, 1, now=NOW)
    assert outside.read_text() == '2026-01-01 old\n'
