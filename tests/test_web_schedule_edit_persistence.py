import copy
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from flask import Flask

import data_manager.file_ops as file_ops
import data_manager.schedule_crud as schedule_crud
from config import SKILL_COLUMNS, allowed_modalities
from routes import routes
from state_manager import StateManager


class TestWebScheduleEditPersistence(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__, template_folder="../templates")
        app.secret_key = "test-secret"
        app.register_blueprint(routes)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True

        self.state = StateManager.get_instance()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name)
        self.live_path = self.upload_dir / "backups" / "Cortex_ALL_live.json"
        self.target_date = date(2026, 6, 9)

        self.original_live = {
            modality: copy.deepcopy(self.state.modality_data[modality])
            for modality in allowed_modalities
        }
        self.original_staged = {
            modality: copy.deepcopy(self.state.staged_modality_data[modality])
            for modality in allowed_modalities
        }
        self.original_global = copy.deepcopy(self.state.global_worker_data)
        self.original_paths = dict(self.state.unified_schedule_paths)
        self.original_upload_folder = file_ops.UPLOAD_FOLDER

        self.state.unified_schedule_paths["live"] = str(self.live_path)
        file_ops.UPLOAD_FOLDER = str(self.upload_dir)
        for modality in allowed_modalities:
            self.state.modality_data[modality].update({
                "working_hours_df": self._initial_df(modality),
                "worker_modifiers": {},
                "total_work_hours": {},
            })
            self.state.staged_modality_data[modality].update({
                "working_hours_df": self._initial_df(modality),
                "worker_modifiers": {},
                "total_work_hours": {},
                "target_date": self.target_date,
            })

    def tearDown(self) -> None:
        file_ops.UPLOAD_FOLDER = self.original_upload_folder
        self.state.unified_schedule_paths.clear()
        self.state.unified_schedule_paths.update(self.original_paths)
        for modality in allowed_modalities:
            self.state.modality_data[modality].clear()
            self.state.modality_data[modality].update(self.original_live[modality])
            self.state.staged_modality_data[modality].clear()
            self.state.staged_modality_data[modality].update(self.original_staged[modality])
        self.state.global_worker_data.clear()
        self.state.global_worker_data.update(self.original_global)
        self.temp_dir.cleanup()

    def _initial_df(self, modality: str) -> pd.DataFrame:
        row = {
            "PPL": "Alice (A1)",
            "start_time": datetime.strptime("08:00", "%H:%M").time(),
            "end_time": datetime.strptime("16:00", "%H:%M").time(),
            "Modifier": 1.0,
            "tasks": f"Old {modality}",
            "row_type": "shift_segment",
            "training": True,
            "counts_for_hours": True,
            "shift_duration": 8.0,
        }
        row.update({skill: (-1 if skill == SKILL_COLUMNS[0] else 0) for skill in SKILL_COLUMNS})
        return pd.DataFrame([row])

    def _worker_plan(self, *, value=1, start="09:00", end="15:00") -> dict:
        modalities = {}
        for modality in allowed_modalities:
            skills = {skill: 0 for skill in SKILL_COLUMNS}
            skills[SKILL_COLUMNS[0]] = value
            modalities[modality] = {
                "row_index": 0,
                "materialize": True,
                "skills": skills,
            }
        return {
            "worker": "Alice (A1)",
            "shifts": [{
                "start_time": start,
                "end_time": end,
                "modifier": 1.25,
                "counts_for_hours": True,
                "training": True,
                "task": "Manual web edit",
                "row_type": "shift",
                "modalities": modalities,
            }],
        }

    def test_today_edit_replaces_worker_and_survives_live_snapshot_reload(self) -> None:
        response = self.client.post(
            "/api/live-schedule/apply-worker-plan",
            json=self._worker_plan(value=1),
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(self.live_path.exists())
        for modality in allowed_modalities:
            worker_rows = self.state.modality_data[modality]["working_hours_df"]
            worker_rows = worker_rows[worker_rows["PPL"] == "Alice (A1)"]
            self.assertEqual(len(worker_rows), 1)
            self.assertEqual(worker_rows.iloc[0]["start_time"].strftime("%H:%M"), "09:00")
            self.assertEqual(str(worker_rows.iloc[0][SKILL_COLUMNS[0]]), "1")

        for modality in allowed_modalities:
            self.state.modality_data[modality]["working_hours_df"] = pd.DataFrame()
        self.assertTrue(file_ops._load_unified_backup(str(self.live_path), use_staged=False))
        for modality in allowed_modalities:
            reloaded = self.state.modality_data[modality]["working_hours_df"]
            self.assertEqual(str(reloaded.iloc[0][SKILL_COLUMNS[0]]), "1")
            self.assertEqual(reloaded.iloc[0]["tasks"], "Manual web edit")

    def test_tomorrow_edit_writes_and_reloads_selected_dated_snapshot(self) -> None:
        payload = self._worker_plan(value="w", start="10:00", end="14:00")
        payload["target_date"] = self.target_date.isoformat()

        response = self.client.post(
            "/api/prep-next-day/apply-worker-plan",
            json=payload,
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        staged_path = (
            self.upload_dir
            / "backups"
            / "staged_days"
            / f"Cortex_ALL_staged_{self.target_date.isoformat()}.json"
        )
        self.assertTrue(staged_path.exists())
        for modality in allowed_modalities:
            self.assertIsNotNone(self.state.staged_modality_data[modality]["last_modified"])
            self.assertTrue(self.state.staged_modality_data[modality]["last_prepped_at"])

        for modality in allowed_modalities:
            self.state.staged_modality_data[modality]["working_hours_df"] = None
            self.state.staged_modality_data[modality]["target_date"] = None
        self.assertTrue(file_ops.reload_staged_data_from_disk(target_date=self.target_date))
        for modality in allowed_modalities:
            reloaded = self.state.staged_modality_data[modality]["working_hours_df"]
            self.assertEqual(str(reloaded.iloc[0][SKILL_COLUMNS[0]]), "w")
            self.assertEqual(reloaded.iloc[0]["start_time"].strftime("%H:%M"), "10:00")

    def test_persistence_failure_rolls_back_every_live_modality(self) -> None:
        before = {
            modality: self.state.modality_data[modality]["working_hours_df"].copy(deep=True)
            for modality in allowed_modalities
        }

        with patch.object(
            schedule_crud,
            "persist_schedule_snapshot",
            side_effect=OSError("disk full"),
        ):
            response = self.client.post(
                "/api/live-schedule/apply-worker-plan",
                json=self._worker_plan(),
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["code"], "persistence_failed")
        for modality in allowed_modalities:
            pd.testing.assert_frame_equal(
                self.state.modality_data[modality]["working_hours_df"],
                before[modality],
            )

    def test_create_existing_worker_returns_conflict_without_overwrite(self) -> None:
        before = {
            modality: self.state.modality_data[modality]["working_hours_df"].copy(deep=True)
            for modality in allowed_modalities
        }

        response = self.client.post(
            "/api/live-schedule/create-worker-plan",
            json=self._worker_plan(start="11:00", end="12:00"),
        )

        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["code"], "worker_exists")
        self.assertEqual(payload["worker"], "Alice (A1)")
        for modality in allowed_modalities:
            pd.testing.assert_frame_equal(
                self.state.modality_data[modality]["working_hours_df"],
                before[modality],
            )

    def test_create_new_worker_persists_without_replacing_existing_workers(self) -> None:
        payload = self._worker_plan()
        payload["worker"] = "Bob (B1)"

        response = self.client.post(
            "/api/live-schedule/create-worker-plan",
            json=payload,
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["created"])
        for modality in allowed_modalities:
            workers = set(self.state.modality_data[modality]["working_hours_df"]["PPL"])
            self.assertEqual(workers, {"Alice (A1)", "Bob (B1)"})

    def test_create_new_worker_for_tomorrow_writes_selected_snapshot(self) -> None:
        payload = self._worker_plan()
        payload["worker"] = "Bob (B1)"
        payload["target_date"] = self.target_date.isoformat()

        response = self.client.post(
            "/api/prep-next-day/create-worker-plan",
            json=payload,
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        staged_path = (
            self.upload_dir
            / "backups"
            / "staged_days"
            / f"Cortex_ALL_staged_{self.target_date.isoformat()}.json"
        )
        self.assertTrue(staged_path.exists())
        for modality in allowed_modalities:
            workers = set(self.state.staged_modality_data[modality]["working_hours_df"]["PPL"])
            self.assertEqual(workers, {"Alice (A1)", "Bob (B1)"})

    def test_quick_edit_write_failure_rolls_back_updated_row(self) -> None:
        before = self.state.modality_data[allowed_modalities[0]]["working_hours_df"].copy(deep=True)

        with patch.object(
            schedule_crud,
            "persist_schedule_snapshot",
            side_effect=OSError("disk full"),
        ):
            response = self.client.post(
                "/api/live-schedule/update-row",
                json={
                    "modality": allowed_modalities[0],
                    "row_index": 0,
                    "updates": {"Modifier": 2.5},
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be persisted", response.get_json()["error"])
        pd.testing.assert_frame_equal(
            self.state.modality_data[allowed_modalities[0]]["working_hours_df"],
            before,
        )

    def test_build_failure_does_not_change_any_modality(self) -> None:
        before = {
            modality: self.state.modality_data[modality]["working_hours_df"].copy(deep=True)
            for modality in allowed_modalities
        }
        original_builder = schedule_crud._build_replaced_worker_schedule_df
        calls = 0

        def fail_on_second_modality(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("invalid second modality")
            return original_builder(*args, **kwargs)

        with patch.object(
            schedule_crud,
            "_build_replaced_worker_schedule_df",
            side_effect=fail_on_second_modality,
        ):
            response = self.client.post(
                "/api/live-schedule/apply-worker-plan",
                json=self._worker_plan(),
            )

        self.assertEqual(response.status_code, 400)
        for modality in allowed_modalities:
            pd.testing.assert_frame_equal(
                self.state.modality_data[modality]["working_hours_df"],
                before[modality],
            )

    def test_stale_worker_revision_prevents_edit(self) -> None:
        payload = self._worker_plan()
        payload["worker_revision"] = "stale"

        response = self.client.post(
            "/api/live-schedule/apply-worker-plan",
            json=payload,
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("updated in another session", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
