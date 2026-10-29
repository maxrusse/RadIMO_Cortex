from pathlib import Path
import sys
import os
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def isolate_change_history(tmp_path, monkeypatch):
    """Tests must never append synthetic events to the application's real history."""
    from lib import change_audit

    original_append = change_audit.append_entry

    def append_test_entry(path, entry):
        if Path(path).resolve() == REPO_ROOT / 'logs' / 'changes.jsonl':
            path = tmp_path / 'audit' / 'changes.jsonl'
        return original_append(path, entry)

    monkeypatch.setattr(change_audit, 'append_entry', append_test_entry)
