"""Bounded log retention and removal of obsolete address metadata.

Maintenance preserves open file descriptors by compacting in place. Technical
log handlers and CSV writers must use ``log_write_lock`` while writing.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import csv
import fcntl
import io
import json
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re


_ADDRESS_KEYS = frozenset({'client_ip', 'peer_ip'})
_DATE_PREFIX = re.compile(rb'^\[?(\d{4}-\d{2}-\d{2})[T ]')


def strip_address_metadata(value):
    """Remove obsolete metadata without interpreting arbitrary user text."""
    if isinstance(value, dict):
        return {key: strip_address_metadata(item) for key, item in value.items()
                if key not in _ADDRESS_KEYS}
    if isinstance(value, list):
        return [strip_address_metadata(item) for item in value]
    return value


@contextmanager
def log_write_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.retention.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class RetentionFileHandler(RotatingFileHandler):
    """Coordinate rotation and emission with retention across worker processes."""
    def emit(self, record):
        with log_write_lock(Path(self.baseFilename).parent):
            super().emit(record)


def _rewrite(path, transform):
    """Use the same inode and advisory lock as change_audit.append_entry."""
    if path.is_symlink():
        return
    try:
        with path.open('r+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            original = stream.read()
            revised = transform(original)
            if revised != original:
                stream.seek(0)
                stream.write(revised)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
    except FileNotFoundError:
        pass


def _jsonl_content(raw, cutoff):
    output = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                continue
            entry_date = date.fromisoformat(str(entry.get('date', entry.get('timestamp', '')))[:10])
        except (ValueError, TypeError):
            continue
        if entry_date >= cutoff:
            output.append(json.dumps(strip_address_metadata(entry), ensure_ascii=False).encode() + b'\n')
    return b''.join(output)


def _technical_content(raw, cutoff, fresh):
    keep = fresh
    output = []
    for line in raw.splitlines(keepends=True):
        match = _DATE_PREFIX.match(line)
        if match:
            try:
                keep = date.fromisoformat(match[1].decode()) >= cutoff
            except ValueError:
                keep = fresh
        if keep:
            output.append(line)
    return b''.join(output)


def _csv_content(raw, cutoff):
    text = io.StringIO(raw.decode('utf-8'))
    reader = csv.DictReader(text)
    if not reader.fieldnames or 'date' not in reader.fieldnames:
        return raw
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
    writer.writeheader()
    for row in reader:
        try:
            keep = date.fromisoformat(row['date']) >= cutoff
        except (ValueError, TypeError):
            keep = False
        if keep:
            writer.writerow(row)
    return output.getvalue().encode('utf-8')


def maintain_logs(root, days=100, *, now=None, force=False):
    """Apply retention at first use, on settings change, and at most hourly.

    ``days`` includes today, so 1 retains today's records. Undated technical
    records use the file modification date. Unknown files are never touched.
    Returns whether maintenance ran. Exceptions propagate for caller reporting.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError('Log retention days must be a positive integer')
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=days - 1)
    with log_write_lock(root):
        marker = root / '.retention-status.json'
        try:
            status = json.loads(marker.read_text())
            elapsed = now.timestamp() - float(status['timestamp'])
            if not force and status['days'] == days and 0 <= elapsed < 3600:
                return False
        except (FileNotFoundError, ValueError, TypeError, KeyError):
            pass
        for path in root.glob('changes.jsonl*'):
            if path.is_file() and not path.is_symlink():
                _rewrite(path, lambda raw: _jsonl_content(raw, cutoff))
        for pattern in ('gunicorn.log*', 'selection.log*', 'flow_balance.log*', 'import.log*'):
            for path in root.glob(pattern):
                if not path.is_file() or path.is_symlink():
                    continue
                fresh = datetime.fromtimestamp(path.stat().st_mtime, now.tzinfo).date() >= cutoff
                _rewrite(path, lambda raw, fresh=fresh: _technical_content(raw, cutoff, fresh))
                if path.name != pattern[:-1] and path.stat().st_size == 0:
                    path.unlink()
        _rewrite(root / 'usage_stats' / 'usage_stats.csv', lambda raw: _csv_content(raw, cutoff))
        marker.write_text(json.dumps({'days': days, 'timestamp': now.timestamp()}))
    return True
