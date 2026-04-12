import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path("/home/dpxuser/radimo_dev/scripts/simulate_distribution_counterfactual.py")
SPEC = importlib.util.spec_from_file_location("simulate_distribution_counterfactual", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestSimulateDistributionCounterfactual(unittest.TestCase):
    def test_write_outputs_creates_expected_files(self) -> None:
        result = {
            "target_date": "2026-04-08",
            "schedule_source": "snapshot",
            "snapshot_path": "/tmp/example.json",
            "transition_count": 1,
            "end_timestamp": "2026-04-08 19:17:28",
            "end_rows": [
                {
                    "canonical_id": "WALD",
                    "name": "Lukas Dr Walder (WALD)",
                    "logged_assignments": 8,
                    "simulated_assignments": 11,
                    "hours": 8.0,
                    "weighted": 11.0,
                    "ratio": 1.375,
                }
            ],
            "transitions": [
                {
                    "timestamp": "2026-04-08 11:08:29",
                    "request_role": "aou",
                    "request_modality": "ct",
                    "logged_worker": "Katerina Samardzhieva (SAM)",
                    "simulated_worker": "Lukas Dr Walder (WALD)",
                    "simulated_skill": "aou",
                    "simulated_modality": "ct",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            outdir = Path(tmpdir)
            MODULE._write_outputs(result, outdir)

            self.assertTrue((outdir / "counterfactual_2026-04-08.json").exists())
            self.assertTrue((outdir / "counterfactual_2026-04-08_endstate.csv").exists())
            self.assertTrue((outdir / "counterfactual_2026-04-08_transitions.csv").exists())


if __name__ == "__main__":
    unittest.main()
