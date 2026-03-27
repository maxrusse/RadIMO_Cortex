import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import routes
from routes import routes as routes_blueprint


class TestLogDownloads(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__, template_folder="../templates")
        app.secret_key = "test-secret"
        app.register_blueprint(routes_blueprint)
        self.client = app.test_client()

    def _write_log(self, base_dir: Path, relative_path: str, content: str) -> None:
        full_path = base_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def test_admin_logs_page_redirects_without_access(self) -> None:
        with patch("routes.has_admin_access", return_value=False):
            response = self.client.get("/admin/logs")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_tail_download_returns_zip_with_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_root = Path(tmp_dir)
            self._write_log(log_root, "gunicorn.log", "g1\nline2\nline3\n")
            self._write_log(log_root, "selection.log", "s1\ns2\ns3\n")
            self._write_log(log_root, "flow_balance.log", "f1\nf2\n")

            with patch("routes.has_admin_access", return_value=True), patch.object(routes, "LOG_ROOT", log_root):
                response = self.client.get("/admin/logs/download?sources=gunicorn,selection&scope=tail&lines=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")

        archive = zipfile.ZipFile(io.BytesIO(response.data))
        self.assertEqual(
            sorted(archive.namelist()),
            [
                "gunicorn/gunicorn.log.tail.log",
                "selection/selection.log.tail.log",
            ],
        )
        self.assertEqual(archive.read("gunicorn/gunicorn.log.tail.log").decode("utf-8"), "line2\nline3\n")
        self.assertEqual(archive.read("selection/selection.log.tail.log").decode("utf-8"), "s2\ns3\n")

    def test_full_download_includes_rotated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_root = Path(tmp_dir)
            self._write_log(log_root, "gunicorn.log", "current-g\n")
            self._write_log(log_root, "gunicorn.log.1", "rotated-g-1\n")
            self._write_log(log_root, "selection.log", "current-s\n")
            self._write_log(log_root, "selection.log.1", "rotated-s-1\n")

            with patch("routes.has_admin_access", return_value=True), patch.object(routes, "LOG_ROOT", log_root):
                response = self.client.get("/admin/logs/download?sources=gunicorn,selection&scope=full")

        self.assertEqual(response.status_code, 200)

        archive = zipfile.ZipFile(io.BytesIO(response.data))
        self.assertIn("gunicorn/gunicorn.log", archive.namelist())
        self.assertIn("gunicorn/gunicorn.log.1", archive.namelist())
        self.assertIn("selection/selection.log", archive.namelist())
        self.assertIn("selection/selection.log.1", archive.namelist())
        self.assertEqual(archive.read("gunicorn/gunicorn.log.1").decode("utf-8"), "rotated-g-1\n")

    def test_unknown_log_source_returns_400(self) -> None:
        with patch("routes.has_admin_access", return_value=True):
            response = self.client.get("/admin/logs/download?sources=bogus&scope=tail")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("Unknown log source", payload["error"])


if __name__ == "__main__":
    unittest.main()
