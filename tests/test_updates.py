"""Deterministic tests for the opt-in updater. No GitHub/network calls."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import update_support as u


def fake_source(label="new"):
    return {
        name: (label + ":" + name + "\n").encode("utf-8")
        for name in u.MANAGED_FILES
    }


def fake_snapshot(blobs):
    return {
        "sha": "a" * 40,
        "blobs": {name: u.git_blob(raw) for name, raw in blobs.items()},
        "token": None,
        "updated_at": "2026-11-21T00:00:00Z",
    }


def fake_archive(contents, omit=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as zipfile_out:
        for name, raw in contents.items():
            if name != omit:
                zipfile_out.writestr("owner-repo-revision/" + name, raw)
    return data.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "install"
        self.root.mkdir()
        self.stage = self.base / "stage"
        self.stage.mkdir()
        self.home = self.base / "user-state"
        patcher = patch.object(u, "state_folder", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_source(self, values, root=None):
        folder = root or self.root
        for name, raw in values.items():
            (folder / name).write_bytes(raw)

    def prepare_stage(self, new, old=None):
        old = old or fake_source("old")
        self.write_source(old)
        self.write_source(new, self.stage)
        manifest = fake_snapshot(new)
        manifest["local"] = {
            name: u.git_blob(old[name]) for name in u.MANAGED_FILES
        }
        manifest["files"] = list(u.MANAGED_FILES)
        (self.stage / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return old

    def test_git_blob_matches_git_object_formula(self):
        import hashlib
        raw = b"hello\n"
        reference = hashlib.sha1(b"blob 6\0hello\n").hexdigest()
        self.assertEqual(u.git_blob(raw), reference)

    def test_only_application_file_changes_trigger_update(self):
        source = fake_source()
        self.write_source(source)
        snapshot = fake_snapshot(source)
        self.assertEqual(u.local_changes(self.root, snapshot["blobs"]), [])
        (self.root / "README.md").write_text("documentation", encoding="utf-8")
        self.assertEqual(u.local_changes(self.root, snapshot["blobs"]), [])
        (self.root / "app.js").write_text("updated source", encoding="utf-8")
        self.assertEqual(u.local_changes(self.root, snapshot["blobs"]), ["app.js"])

    def test_archive_matches_git_tree(self):
        new = fake_source()
        u.extract_verified(fake_archive(new), fake_snapshot(new), self.stage)
        self.assertEqual((self.stage / "StonkResearch.pyw").read_bytes(), new["StonkResearch.pyw"])

    def test_archive_rejects_missing_managed_file(self):
        new = fake_source()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            u.extract_verified(fake_archive(new, omit="update_support.py"),
                               fake_snapshot(new), self.stage)

    def test_archive_rejects_altered_file(self):
        new = fake_source()
        damaged = dict(new)
        damaged["app.css"] = b"corruption"
        with self.assertRaisesRegex(ValueError, "verification"):
            u.extract_verified(fake_archive(damaged), fake_snapshot(new), self.stage)

    def test_update_urls_must_be_trusted_https_hosts(self):
        for url in ("http://api.github.com/fake",
                    "https://attacker.example/fake",
                    "file:///tmp/foo"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                u._get(url, None, 500)

    def test_private_repo_without_cli_login_explains_blocker(self):
        error = urllib.error.HTTPError("https://api.github.com/fake", 404,
                                      "not found", {}, None)
        with patch.object(u, "_api_json", side_effect=error), \
             patch.object(u, "_cli_token", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "private or unavailable"):
                u.get_github_snapshot()

    def test_stage_download_pins_commit_and_preserves_local_files(self):
        before = fake_source("old")
        new = fake_source("new")
        self.write_source(before)
        snapshot = fake_snapshot(new)
        with patch.object(u, "_get", return_value=fake_archive(new)) as get:
            folder = u.stage_download(snapshot, self.root)
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        self.assertIn(snapshot["sha"], get.call_args.args[0])
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["local"]["app.js"], u.git_blob(before["app.js"]))
        self.assertEqual((self.root / "app.js").read_bytes(), before["app.js"])

    def test_apply_preserves_portfolio_database_and_other_user_files(self):
        new = fake_source("new")
        self.prepare_stage(new)
        db = self.root / "stonk.db"
        with contextlib.closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE holdings(symbol TEXT)")
            con.execute("INSERT INTO holdings VALUES ('AAPL')")
            con.commit()
        (self.root / "custom-settings.txt").write_text("keep", encoding="utf-8")
        backup = u.apply_stage(self.stage, self.root, wait_pid=0, restart=False)
        self.assertEqual((self.root / "app.js").read_bytes(), new["app.js"])
        self.assertEqual((self.root / "custom-settings.txt").read_text(), "keep")
        with contextlib.closing(sqlite3.connect(db)) as con:
            self.assertEqual(con.execute("SELECT symbol FROM holdings").fetchone()[0], "AAPL")
        with contextlib.closing(sqlite3.connect(backup / "stonk.db")) as con:
            self.assertEqual(con.execute("SELECT symbol FROM holdings").fetchone()[0], "AAPL")
        self.assertTrue(u.last_result()["ok"])

    def test_install_blocks_changed_local_file(self):
        new = fake_source("new")
        self.prepare_stage(new)
        (self.root / "app.js").write_text("user edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after staging"):
            u.apply_stage(self.stage, self.root)
        self.assertEqual((self.root / "app.js").read_text(), "user edit")

    def test_failed_replace_restores_original_files(self):
        new = fake_source("new")
        old = self.prepare_stage(new)
        real_replace = os.replace
        fail_once = {"pending": True}

        def fragile_replace(source, dest):
            if Path(dest).name == "app.css" and fail_once["pending"]:
                fail_once["pending"] = False
                raise OSError("simulated locked app.css")
            return real_replace(source, dest)

        with patch.object(u.os, "replace", side_effect=fragile_replace):
            with self.assertRaisesRegex(OSError, "simulated locked"):
                u.apply_stage(self.stage, self.root)
        for name in u.MANAGED_FILES:
            self.assertEqual((self.root / name).read_bytes(), old[name])
        self.assertFalse(u.last_result()["ok"])

    def test_check_is_nonblocking_and_does_not_expose_private_token(self):
        current = fake_source("old")
        latest = fake_source("new")
        self.write_source(current)
        snapshot = fake_snapshot(latest)
        snapshot["token"] = "SECRET_FAKE_TEST_TOKEN"
        manager = u.UpdateManager(self.root)
        with patch.object(u, "get_github_snapshot", return_value=snapshot):
            started = manager.check(force=True)
            self.assertIn(started["status"], ("checking", "available"))
            deadline = time.monotonic() + 3
            while manager.status()["status"] == "checking" and time.monotonic() < deadline:
                time.sleep(.01)
        self.assertEqual(manager.status()["status"], "available")
        self.assertNotIn("SECRET_FAKE", json.dumps(manager.status()))


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        import http.client
        import importlib.machinery
        import importlib.util
        import threading
        from http.server import ThreadingHTTPServer

        source = Path(__file__).resolve().parents[1] / "StonkResearch.pyw"
        loader = importlib.machinery.SourceFileLoader("stock_update_api_test", str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.app = importlib.util.module_from_spec(spec)
        loader.exec_module(self.app)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.old_port = self.app.PORT
        self.app.PORT = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.app.PORT = self.old_port

    def request(self, method, path, payload=None, origin=None):
        import http.client
        port = self.server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"}
        if origin:
            headers["Origin"] = origin
        try:
            conn.request(method, path,
                         body=json.dumps(payload).encode() if payload is not None else None,
                         headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()

    def test_update_check_returns_async_state_without_installing(self):
        with patch.object(self.app.UPDATE_MANAGER, "check",
                          return_value={"status": "checking"}), \
             patch.object(self.app.UPDATE_MANAGER, "status",
                          return_value={"status": "checking", "available": False}):
            code, data = self.request("GET", "/api/updates/check?force=1")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "checking")

    def test_update_download_requires_local_origin(self):
        with patch.object(self.app.UPDATE_MANAGER, "download",
                          return_value={"status": "downloading"}) as download:
            code, data = self.request("POST", "/api/updates/download",
                                      {}, origin="https://evil.example")
        self.assertEqual(code, 403)
        self.assertIn("blocked", data["error"])
        download.assert_not_called()

    def test_update_download_with_same_origin_is_opt_in(self):
        with patch.object(self.app.UPDATE_MANAGER, "download",
                          return_value={"status": "downloading"}) as download:
            port = self.server.server_address[1]
            code, data = self.request("POST", "/api/updates/download",
                                      {}, origin=f"http://127.0.0.1:{port}")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "downloading")
        download.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
