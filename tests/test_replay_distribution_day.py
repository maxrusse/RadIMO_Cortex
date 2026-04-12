import importlib.util
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path("/home/dpxuser/radimo_dev/scripts/replay_distribution_day.py")
SPEC = importlib.util.spec_from_file_location("replay_distribution_day", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestReplayDistributionDay(unittest.TestCase):
    def test_parse_assignment_events_captures_request_and_selection(self) -> None:
        log_text = """\
2026-04-08 08:11:09,523 [INFO] Assignment request: modality=ct, role=mdh, strict_routing=False, strict_weights=False, time=08:11:09
2026-04-08 08:11:09,535 [INFO] Warm-start overflow gate: mode=either, time_ready=True, min_ready=False, released=True
2026-04-08 08:11:09,537 [INFO] Selected worker: Dorina Korbmacher (KORB) using column mdh (modality ct)
2026-04-08 08:13:16,770 [INFO] Assignment request: modality=ct, role=mdh, strict_routing=False, strict_weights=False, time=08:13:16
2026-04-08 08:13:16,785 [INFO] Warm-start overflow gate: mode=either, time_ready=True, min_ready=False, released=True
2026-04-08 08:13:16,785 [INFO] Specialist overflow triggered: specialist_min=0.6932, generalist_min=0.4621, imbalance=33.3% >= 20%
2026-04-08 08:13:16,788 [INFO] Selected worker: Charlotte Dr Zander (ZANDERCH) using column mdh (modality ct)
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "selection.log"
            log_path.write_text(log_text, encoding="utf-8")

            events = MODULE.parse_assignment_events(log_path, date(2026, 4, 8))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].logged_selected_worker, "Dorina Korbmacher (KORB)")
        self.assertEqual(events[0].selected_skill, "mdh")
        self.assertEqual(events[0].selected_modality, "ct")
        self.assertFalse(events[0].overflow_triggered)
        self.assertEqual(events[1].logged_selected_worker, "Charlotte Dr Zander (ZANDERCH)")
        self.assertTrue(events[1].overflow_triggered)
        self.assertEqual(events[1].overflow_threshold_pct, 20)


if __name__ == "__main__":
    unittest.main()
