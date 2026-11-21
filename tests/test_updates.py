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


if __name__ == "__main__":
    unittest.main()
