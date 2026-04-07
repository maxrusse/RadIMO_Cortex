import unittest

from scripts.generate_worker_team_plot import (
    Worker,
    build_imbalance_test_cases,
    build_imbalance_test_workers,
    build_realistic_day_cases,
    build_realistic_workers,
    build_origin_sequence,
    get_balancer_settings,
    simulate_distribution,
    simulate_realistic_day,
)


class TestWorkerTeamPlot(unittest.TestCase):
    def setUp(self) -> None:
        self.workers_by_team = {
            "A": [Worker("A1", "A"), Worker("A2", "A")],
            "B": [Worker("B1", "B"), Worker("B2", "B")],
        }
        self.settings = {
            "min_assignments_per_skill": 3,
            "imbalance_threshold_pct": 20,
            "warm_start_release_mode": "either",
        }

    def test_origin_sequence_respects_totals_and_first_run(self) -> None:
        sequence = build_origin_sequence(60, {"A": 40, "B": 20}, first_team="A", first_run=6)
        self.assertEqual(len(sequence), 60)
        self.assertEqual(sequence.count("A"), 40)
        self.assertEqual(sequence.count("B"), 20)
        self.assertEqual(sequence[:6], ["A"] * 6)

    def test_simulation_produces_expected_summary(self) -> None:
        sequence = build_origin_sequence(60, {"A": 40, "B": 20}, first_team="A", first_run=6)
        simulation = simulate_distribution(
            sequence,
            self.workers_by_team,
            self.settings,
            total_day_minutes=540,
            start_buffer_minutes=15,
            end_buffer_minutes=20,
        )

        self.assertEqual(sum(simulation["loads"].values()), 60)
        self.assertEqual(simulation["origin_summary"]["A"]["origin_total"], 40)
        self.assertEqual(simulation["origin_summary"]["B"]["origin_total"], 20)
        self.assertEqual(simulation["origin_summary"]["A"]["handled_by_own_team"], 33)
        self.assertEqual(simulation["origin_summary"]["A"]["handled_by_other_team"], 7)
        self.assertEqual(simulation["origin_summary"]["B"]["handled_by_own_team"], 20)
        self.assertEqual(simulation["origin_summary"]["B"]["handled_by_other_team"], 0)
        self.assertEqual(simulation["team_totals"]["A"], 33)
        self.assertEqual(simulation["team_totals"]["B"], 27)

    def test_get_balancer_settings_accepts_mapping(self) -> None:
        config = {"balancer": {"min_assignments_per_skill": 7}}
        self.assertEqual(get_balancer_settings(config)["min_assignments_per_skill"], 7)

    def test_realistic_day_case_builder_has_expected_totals(self) -> None:
        cases = build_realistic_day_cases(seed=12345)
        self.assertEqual(len(cases), 120)
        self.assertEqual(sum(1 for case in cases if case.modality == "CT"), 60)
        self.assertEqual(sum(1 for case in cases if case.modality == "MR"), 60)
        self.assertEqual(sum(1 for case in cases if case.phase == "late"), 30)
        self.assertFalse(
            any(case.minute >= 495 and case.origin_group in {"GYN", "NOTFALL"} for case in cases)
        )

    def test_realistic_day_late_workers_are_generic_names(self) -> None:
        workers = build_realistic_workers()
        late_workers = [worker.name for worker in workers if worker.shift_end_minute > 495]
        self.assertEqual(late_workers, ["Late1", "Late2", "Late3"])

    def test_imbalance_test_worker_roster_has_two_early_workers_per_target_group(self) -> None:
        workers = build_imbalance_test_workers()
        early_counts = {}
        for worker in workers:
            if worker.shift_end_minute <= 495 and worker.group in {"AOU", "CVT", "MDH"}:
                early_counts[worker.group] = early_counts.get(worker.group, 0) + 1

        self.assertEqual(len(workers), 11)
        self.assertEqual(early_counts, {"AOU": 2, "CVT": 2, "MDH": 2})

    def test_imbalance_test_case_builder_has_fifteen_cases_and_target_groups(self) -> None:
        cases = build_imbalance_test_cases(seed=12345)
        self.assertEqual(len(cases), 15)
        self.assertEqual({case.phase for case in cases}, {"imbalance"})
        self.assertEqual({case.origin_group for case in cases}, {"AOU", "CVT", "MDH"})

    def test_imbalance_test_simulation_balances_two_workers_per_group(self) -> None:
        cases = build_imbalance_test_cases(seed=12345)
        workers = build_imbalance_test_workers()
        simulation = simulate_realistic_day(
            cases,
            workers,
            self.settings,
            total_day_minutes=750,
            start_buffer_minutes=15,
            end_buffer_minutes=20,
        )

        self.assertEqual(len(simulation["rows"]), 15)
        self.assertEqual(simulation["origin_summary"]["AOU"]["origin_total"], 6)
        self.assertEqual(simulation["origin_summary"]["CVT"]["origin_total"], 5)
        self.assertEqual(simulation["origin_summary"]["MDH"]["origin_total"], 4)
        self.assertEqual(simulation["origin_summary"]["GYN"]["origin_total"], 0)
        self.assertEqual(simulation["origin_summary"]["NOTFALL"]["origin_total"], 0)
        self.assertEqual(set(simulation["team_totals"].keys()), {"AOU", "CVT", "MDH", "GYN", "NOTFALL"})
        self.assertEqual(sum(simulation["team_totals"].values()), 15)

    def test_realistic_day_simulation_balances_groups_and_loads(self) -> None:
        cases = build_realistic_day_cases(seed=12345)
        workers = build_realistic_workers()
        simulation = simulate_realistic_day(
            cases,
            workers,
            self.settings,
            total_day_minutes=750,
            start_buffer_minutes=15,
            end_buffer_minutes=20,
        )

        self.assertEqual(len(simulation["rows"]), 120)
        self.assertEqual(simulation["origin_summary"]["AOU"]["origin_total"], 33)
        self.assertEqual(simulation["origin_summary"]["CVT"]["origin_total"], 33)
        self.assertEqual(simulation["origin_summary"]["MDH"]["origin_total"], 33)
        self.assertEqual(simulation["origin_summary"]["GYN"]["origin_total"], 13)
        self.assertEqual(simulation["origin_summary"]["NOTFALL"]["origin_total"], 8)
        self.assertEqual(set(simulation["team_totals"].keys()), {"AOU", "CVT", "MDH", "GYN", "NOTFALL"})
        self.assertEqual(sum(simulation["team_totals"].values()), 120)


if __name__ == "__main__":
    unittest.main()
