import unittest
from unittest.mock import patch

import balancer
from config import SKILL_COLUMNS, allowed_modalities
from data_manager import global_worker_data


class TestShiftModifierPropagation(unittest.TestCase):
    def setUp(self) -> None:
        self.modality = allowed_modalities[0]
        self.skill = SKILL_COLUMNS[0]
        global_worker_data['weighted_counts'] = {}
        global_worker_data['assignments_per_mod'][self.modality] = {}
        balancer.modality_data[self.modality]['worker_modifiers'] = {}

    def test_weighted_assignment_multiplies_all_three_w_sources(self) -> None:
        with (
            patch('balancer.get_roster_modifier_raw', return_value=2.0),
            patch('balancer.get_skill_modality_weight', return_value=1.0),
            patch.dict('balancer.BALANCER_SETTINGS', {'default_w_modifier': 1.25}, clear=False),
        ):
            balancer.update_global_assignment(
                person='GYN1',
                role=self.skill,
                modality=self.modality,
                is_weighted=True,
                shift_modifier_override=0.3,
            )

        # combined = shift(0.3) * roster_w(2.0) * default_w(1.25) = 0.75
        self.assertAlmostEqual(global_worker_data['weighted_counts']['GYN1'], 1.0 / 0.75, places=6)

    def test_uses_pooled_shift_modifier_when_active_row_default(self) -> None:
        balancer.modality_data[self.modality]['worker_modifiers'] = {'GYN1': 1.5}

        with (
            patch('balancer.get_roster_modifier_raw', return_value=2.0),
            patch('balancer.get_skill_modality_weight', return_value=1.0),
            patch.dict('balancer.BALANCER_SETTINGS', {'default_w_modifier': 1.25}, clear=False),
        ):
            balancer.update_global_assignment(
                person='GYN1',
                role=self.skill,
                modality=self.modality,
                is_weighted=True,
                shift_modifier_override=1.0,
            )

        # combined = pooled_shift(1.5) * roster_w(2.0) * default_w(1.25) = 3.75
        self.assertAlmostEqual(global_worker_data['weighted_counts']['GYN1'], 1.0 / 3.75, places=6)

    def test_non_weighted_assignment_uses_shift_modifier_only(self) -> None:
        with (
            patch('balancer.get_roster_modifier_raw', return_value=2.0),
            patch('balancer.get_skill_modality_weight', return_value=1.0),
            patch.dict('balancer.BALANCER_SETTINGS', {'default_w_modifier': 1.25}, clear=False),
        ):
            balancer.update_global_assignment(
                person='GYN1',
                role=self.skill,
                modality=self.modality,
                is_weighted=False,
                shift_modifier_override=0.5,
            )

        # non-weighted ignores W streams -> combined = shift(0.5)
        self.assertAlmostEqual(global_worker_data['weighted_counts']['GYN1'], 1.0 / 0.5, places=6)

    def test_weighted_assignment_uses_shift_and_w_streams(self) -> None:
        with (
            patch('balancer.get_roster_modifier_raw', return_value=2.0),
            patch('balancer.get_skill_modality_weight', return_value=1.0),
            patch.dict('balancer.BALANCER_SETTINGS', {'default_w_modifier': 1.25}, clear=False),
        ):
            balancer.update_global_assignment(
                person='GYN1',
                role=self.skill,
                modality=self.modality,
                is_weighted=True,
                shift_modifier_override=0.3,
            )

        # combined = shift(0.3) * roster_w(2.0) * default_w(1.25)
        self.assertAlmostEqual(global_worker_data['weighted_counts']['GYN1'], 1.0 / (0.3 * 2.0 * 1.25), places=6)


if __name__ == '__main__':
    unittest.main()
