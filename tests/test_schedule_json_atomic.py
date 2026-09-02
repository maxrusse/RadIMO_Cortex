import json
import threading
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from data_manager import file_ops


class TestScheduleJsonAtomicWrites(unittest.TestCase):
    def test_atomic_write_keeps_previous_json_readable_until_replacement(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "Cortex_ALL_scheduled.json"
            previous = {"version": "previous"}
            replacement = {"version": "replacement", "working_hours": [1, 2, 3]}
            target.write_text(json.dumps(previous), encoding="utf-8")

            dump_started = threading.Event()
            allow_dump = threading.Event()
            thread_errors = []
            original_dump = file_ops.json.dump

            def delayed_dump(*args, **kwargs):
                dump_started.set()
                if not allow_dump.wait(timeout=2):
                    raise RuntimeError("test writer timeout")
                return original_dump(*args, **kwargs)

            def write_replacement() -> None:
                try:
                    file_ops._write_payload_to_path(replacement, str(target), "scheduled")
                except Exception as exc:  # pragma: no cover - failure is asserted below
                    thread_errors.append(exc)

            with patch.object(file_ops.json, "dump", side_effect=delayed_dump):
                writer = threading.Thread(target=write_replacement)
                writer.start()
                self.assertTrue(dump_started.wait(timeout=2))

                # A reader must still see the complete old document while the
                # replacement is being serialized to its private temp file.
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), previous)

                allow_dump.set()
                writer.join(timeout=2)

            self.assertFalse(writer.is_alive())
            self.assertEqual(thread_errors, [])
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), replacement)

    def test_malformed_schedule_is_logged_as_import_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "Cortex_ALL_scheduled.json"
            target.write_text("", encoding="utf-8")

            with self.assertLogs("radimo.import", level="ERROR") as captured:
                result = file_ops.load_unified_scheduled_into_staged(str(target))

        self.assertFalse(result)
        self.assertTrue(any("line 1 column 1" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
