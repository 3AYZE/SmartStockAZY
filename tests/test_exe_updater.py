"""Deterministic EXE updater tests; no network, GitHub token, or user data."""
import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import exe_updater as app


def release(tag="v0.6.3", body=b"MZ" + b"\x00" * 400):
    return {
        "tag": tag, "asset_id": 17, "asset_size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "token": None, "release_url": "https://github.com/3AYZE/SmartStockAZY/releases/tag/" + tag,
    }


class FakeResponse(io.BytesIO):
    def __init__(self, content, content_type="application/octet-stream"):
        super().__init__(content)
        self.headers = {"Content-Type": content_type}


class ExecutableUpdaterTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "appdata"
        self.data.mkdir()
        patcher = patch.object(app, "user_data_dir", return_value=self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_release_version_is_monotonic(self):
        self.assertTrue(app.is_newer({"tag": "v0.6.2"}, release("v0.6.3")))
        self.assertFalse(app.is_newer({"tag": "v0.6.3"}, release("v0.6.3")))
        self.assertFalse(app.is_newer({"tag": "v0.6.4"}, release("v0.6.3")))
        self.assertTrue(app.is_newer({}, release("v0.6.3")))

    def test_release_metadata_must_contain_sha256(self):
        payload = {
            "tag_name": "v0.6.3", "draft": False, "prerelease": False,
            "assets": [{"name": "SmartStockAZY.exe", "id": 17,
                        "size": 400, "digest": "sha256:" + "a" * 64}],
        }
        with patch.object(app, "_read_limited", return_value=json.dumps(payload).encode()):
            result = app.newest_release()
        self.assertEqual(result["sha256"], "a" * 64)
        self.assertEqual(result["asset_id"], 17)
        payload["assets"][0]["digest"] = None
        with patch.object(app, "_read_limited", return_value=json.dumps(payload).encode()):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                app.newest_release()

    def test_private_repo_prompts_for_cli_not_embedded_token(self):
        error = urllib.error.HTTPError("https://api.github.com/fake", 404,
                                      "Private", {}, None)
        with patch.object(app, "_read_limited", side_effect=error), \
             patch.object(app, "_private_token",
                          side_effect=RuntimeError("gh auth login")):
            with self.assertRaisesRegex(RuntimeError, "gh auth login"):
                app.newest_release()

    def test_untrusted_download_urls_rejected(self):
        for target in ("http://api.github.com/repos", "https://evil.example/a",
                       "file:///fake"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                app._open(target)

    def test_executable_download_verified(self):
        data = b"MZ" + os.urandom(800)
        info = release(body=data)
        with patch.object(app, "_open", return_value=FakeResponse(data)):
            path = app.fetch_exe(info, self.root)
        self.assertEqual(path.read_bytes(), data)

    def test_corrupted_executable_download_removed(self):
        wanted = release(body=b"MZ1234")
        with patch.object(app, "_open", return_value=FakeResponse(b"MZoops")):
            with self.assertRaisesRegex(ValueError, "SHA-256|Incomplete"):
                app.fetch_exe(wanted, self.root)
        self.assertFalse((self.root / "SmartStockAZY.exe").exists())

    def test_frozen_build_info_detects_tag(self):
        (self.root / "build_info.json").write_text('{"tag":"v0.6.7"}', encoding="utf8")
        self.assertEqual(app.installed_build(self.root)["tag"], "v0.6.7")

    def test_executable_update_replaces_only_exe_and_backs_up(self):
        directory = self.root / "program"
        directory.mkdir()
        target = directory / "SmartStockAZY.exe"
        old = b"MZ" + b"old-version"
        new = b"MZ" + b"new-version"
        target.write_bytes(old)
        staging_dir = self.root / "stage"
        staging_dir.mkdir()
        staged = staging_dir / "SmartStockAZY.exe"
        staged.write_bytes(new)
        db = directory / "stonk.db"
        db.write_bytes(b"test user database not a real sqlite file")
        with patch.object(app.update_support, "_wait_for_pid") as wait, \
             patch.object(app, "_spawn") as spawn, \
             patch.object(app, "wait_for_startup") as startup:
            app.apply_executable_update(target, staged,
                                        hashlib.sha256(new).hexdigest(), 123,
                                        "v0.6.8")
        wait.assert_called_once_with(123)
        spawn.assert_called_once_with(target.resolve(), ["--no-browser"])
        startup.assert_called_once_with(spawn.return_value, "v0.6.8")
        self.assertEqual(target.read_bytes(), new)
        self.assertEqual(db.read_bytes(), b"test user database not a real sqlite file")
        backups = list((self.data / "backups").glob("SmartStockAZY-*.exe"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertTrue(app.last_result()["ok"])

    def test_failed_restart_restores_previous_executable(self):
        directory = self.root / "program"
        directory.mkdir()
        target = directory / "SmartStockAZY.exe"
        old = b"MZOLD"
        new = b"MZNEW"
        target.write_bytes(old)
        stage_dir = self.root / "stage"
        stage_dir.mkdir()
        staged = stage_dir / "SmartStockAZY.exe"
        staged.write_bytes(new)
        calls = []

        def spawn(exe, argv=None):
            calls.append((exe, argv))
            if len(calls) == 1:
                raise OSError("simulated launch failure")

        with patch.object(app.update_support, "_wait_for_pid"), \
             patch.object(app, "_spawn", side_effect=spawn):
            with self.assertRaisesRegex(OSError, "simulated launch failure"):
                app.apply_executable_update(target, staged,
                                            hashlib.sha256(new).hexdigest(), 11,
                                            "v0.6.9")
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(len(calls), 2)
        self.assertFalse(app.last_result()["ok"])

    def test_manager_does_not_auto_install(self):
        (self.root / "build_info.json").write_text('{"tag":"v0.6.3"}')
        manager = app.ExeUpdateManager(self.root)
        self.assertEqual(manager.status()["installed_version"], "v0.6.3")
        self.assertEqual(manager.status()["status"], "idle")
        with self.assertRaisesRegex(ValueError, "No newer"):
            manager.download()

    def test_public_release_download_uses_tagged_binary_url(self):
        data = b"MZ" + b"sample"
        with patch.object(app, "_open", return_value=FakeResponse(data)) as download:
            app.fetch_exe(release(body=data), self.root)
        download.assert_called_once_with(
            "https://github.com/3AYZE/SmartStockAZY/releases/download/v0.6.3/SmartStockAZY.exe",
            None, "application/octet-stream")

    def test_version_comparison_crosses_minor_and_major_releases(self):
        self.assertTrue(app.is_newer({"tag": "v0.6.99"}, release("v0.7.0")))
        self.assertTrue(app.is_newer({"tag": "v0.99.99"}, release("v1.0.0")))
        self.assertFalse(app.is_newer({"tag": "v1.0.0"}, release("v0.9.99")))
        self.assertFalse(app.is_newer({"tag": "v0.6.3"}, release("v0.6.4-beta")))

    def test_redirect_strips_credentials_and_rejects_insecure_hosts(self):
        import urllib.request
        from email.message import Message
        req = urllib.request.Request(
            app.REPO_API + "/releases/assets/17", headers={"Authorization": "Bearer example"})
        handler = app._redirect_handler()
        target = "https://release-assets.githubusercontent.com/file"
        redirected = handler.redirect_request(req, None, 302, "Found", Message(), target)
        self.assertFalse(redirected.has_header("Authorization"))
        self.assertEqual(redirected.full_url, target)
        with self.assertRaisesRegex(ValueError, "untrusted"):
            handler.redirect_request(req, None, 302, "Found", Message(),
                                     "http://github.com/unsafe")

    def test_spawn_resets_pyinstaller_environment(self):
        with patch.object(app.subprocess, "Popen") as popen:
            app._spawn(self.root / "SmartStockAZY.exe", ["--no-browser"])
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_startup_requires_expected_release_and_process_identity(self):
        from unittest.mock import Mock
        process = Mock(pid=123)
        process.poll.return_value = None
        payload = {"ok": True, "version": "v0.6.8", "mode": "windows-exe",
                   "pid": 456, "parent_pid": 123}
        with patch.object(app.urllib.request, "urlopen",
                          return_value=FakeResponse(json.dumps(payload).encode())):
            app.wait_for_startup(process, "v0.6.8", timeout=1)
        payload["parent_pid"] = 789
        with patch.object(app.urllib.request, "urlopen",
                          return_value=FakeResponse(json.dumps(payload).encode())), \
             patch.object(app.time, "sleep"), \
             patch.object(app.time, "monotonic", side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(TimeoutError, "startup verification"):
                app.wait_for_startup(process, "v0.6.8", timeout=1)

    def test_failed_health_check_rolls_back(self):
        directory = self.root / "program"
        directory.mkdir()
        target = directory / "SmartStockAZY.exe"
        target.write_bytes(b"MZOLD")
        stage_dir = self.root / "stage"
        stage_dir.mkdir()
        staged = stage_dir / "SmartStockAZY.exe"
        staged.write_bytes(b"MZNEW")
        with patch.object(app.update_support, "_wait_for_pid"), \
             patch.object(app, "_spawn") as spawn, \
             patch.object(app, "wait_for_startup", side_effect=TimeoutError("startup verification")), \
             patch.object(app, "stop_launched_process") as stop:
            with self.assertRaisesRegex(TimeoutError, "startup verification"):
                app.apply_executable_update(target, staged,
                    hashlib.sha256(b"MZNEW").hexdigest(), 123, "v0.6.8")
        stop.assert_called_once_with(spawn.return_value)
        self.assertEqual(target.read_bytes(), b"MZOLD")
        self.assertEqual(spawn.call_count, 2)
        self.assertFalse(app.last_result()["ok"])

    def test_frozen_database_migration_keeps_original(self):
        import importlib.machinery
        import importlib.util

        source = Path(__file__).resolve().parents[1] / "StonkResearch.pyw"
        loader = importlib.machinery.SourceFileLoader("stock_frozen_migration_test", str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        exe_dir = self.root / "legacy"
        exe_dir.mkdir()
        old_db = exe_dir / "stonk.db"
        with contextlib.closing(sqlite3.connect(old_db)) as con:
            con.execute("CREATE TABLE positions_test(ticker TEXT)")
            con.execute("INSERT INTO positions_test VALUES('NVDA')")
            con.commit()
        destination = self.data / "stonk.db"
        with patch.object(module, "IS_FROZEN", True), \
             patch.object(module, "DB_PATH", destination), \
             patch.object(module.sys, "executable", str(exe_dir / "SmartStockAZY.exe")):
            module.migrate_portable_database()
        with contextlib.closing(sqlite3.connect(old_db)) as con:
            self.assertEqual(con.execute("SELECT ticker FROM positions_test").fetchone()[0], "NVDA")
        with contextlib.closing(sqlite3.connect(destination)) as con:
            self.assertEqual(con.execute("SELECT ticker FROM positions_test").fetchone()[0], "NVDA")
