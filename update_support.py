"""Opt-in GitHub source updater for the local SmartStockAZY desktop application.

Checks only the owner's main branch, validates every managed Git blob against
the GitHub commit tree, stages files, and installs only after explicit approval.
Never touches the user's portfolio database during application-file replacement.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

OWNER = "3AYZE"
REPO = "SmartStockAZY"
BRANCH = "main"
API = "https://api.github.com/repos/" + OWNER + "/" + REPO
CORE_FILES = ("StonkResearch.pyw", "app.js", "app.css", "index.html", "update_support.py")
MANAGED_FILES = CORE_FILES + ("README.md",)
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_EXTRACTED = 6 * 1024 * 1024
CHECK_INTERVAL = 6 * 3600
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_HOSTS = {"api.github.com", "codeload.github.com", "github.com"}


def git_blob(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def state_folder() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "SmartStockAZY" if base else Path(tempfile.gettempdir()) / "SmartStockAZY"


def _cli_token() -> str | None:
    """Reuse existing GitHub CLI authentication; do not store or display tokens."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True,
            timeout=5, creationflags=flags, check=False
        )
        token = result.stdout.strip()
        return token if result.returncode == 0 and token else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class _TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).hostname not in ALLOWED_HOSTS:
            raise ValueError("Unexpected update download destination")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, token: str | None, max_bytes: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Untrusted update URL")
    headers = {
        "User-Agent": "SmartStockAZY-Desktop-Updater",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(_TrustedRedirect())
    with opener.open(urllib.request.Request(url, headers=headers), timeout=18) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("GitHub update exceeds maximum download size")
    return data


def _api_json(url: str, token: str | None) -> dict:
    value = json.loads(_get(url, token, 2 * 1024 * 1024).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid GitHub API response")
    return value


def get_github_snapshot() -> dict:
    """Try public GitHub; for private repositories use a signed-in GitHub CLI."""
    token = None
    commit_url = API + "/commits/" + BRANCH
    try:
        info = _api_json(commit_url, None)
    except urllib.error.HTTPError as exc:
        if exc.code not in (401, 403, 404):
            raise
        token = _cli_token()
        if not token:
            raise RuntimeError(
                "This repository is private or unavailable. For private updates, "
                "install the free GitHub CLI and run 'gh auth login' once. "
                "No access token is stored in SmartStockAZY."
            ) from None
        info = _api_json(commit_url, token)
    commit_sha = info.get("sha", "")
    tree_sha = (info.get("commit") or {}).get("tree", {}).get("sha", "")
    if not SHA40.fullmatch(commit_sha) or not SHA40.fullmatch(tree_sha):
        raise ValueError("GitHub returned an invalid commit/tree SHA")
    tree = _api_json(API + "/git/trees/" + tree_sha + "?recursive=1", token)
    if tree.get("truncated"):
        raise ValueError("GitHub returned an incomplete source tree")
    blobs = {
        item.get("path"): item.get("sha")
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
    }
    for filename in MANAGED_FILES:
        if not SHA40.fullmatch(blobs.get(filename, "")):
            raise ValueError("Expected application file missing from GitHub: " + filename)
    return {
        "sha": commit_sha,
        "blobs": {name: blobs[name] for name in MANAGED_FILES},
        "token": token,
        "updated_at": (info.get("commit") or {}).get("committer", {}).get("date"),
    }


def local_changes(root: Path, remote_blobs: dict) -> list[str]:
    changed = []
    for name in CORE_FILES:
        try:
            digest = git_blob((root / name).read_bytes())
        except OSError:
            digest = None
        if digest != remote_blobs.get(name):
            changed.append(name)
    return changed


def extract_verified(archive: bytes, snapshot: dict, stage: Path) -> None:
    """Read only allowlisted root-level files. Never extract paths from ZIP entries."""
    if len(archive) > MAX_ARCHIVE:
        raise ValueError("Update ZIP is too large")
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        if len(zf.infolist()) > 400:
            raise ValueError("Update ZIP has too many entries")
        entries = {}
        seen_size = 0
        for item in zf.infolist():
            seen_size += item.file_size
            if seen_size > MAX_EXTRACTED:
                raise ValueError("Update ZIP has too much expanded data")
            if item.is_dir():
                continue
            parts = item.filename.split("/")
            if len(parts) == 2 and parts[1] in MANAGED_FILES:
                # POSIX symlink file-type bits, if present.
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("ZIP contains a link in a managed file")
                if parts[1] in entries:
                    raise ValueError("Duplicate file in update ZIP")
                entries[parts[1]] = item
        if set(entries) != set(MANAGED_FILES):
            raise ValueError("Incomplete GitHub source archive")
        for name in MANAGED_FILES:
            raw = zf.read(entries[name])
            if git_blob(raw) != snapshot["blobs"][name]:
                raise ValueError("Downloaded source failed GitHub blob verification: " + name)
            (stage / name).write_bytes(raw)


def stage_download(snapshot: dict, root: Path, progress=None) -> Path:
    sha = snapshot["sha"]
    if not SHA40.fullmatch(sha):
        raise ValueError("Refusing update with invalid commit")
    folder = Path(tempfile.mkdtemp(prefix="SmartStockAZY-update-"))
    try:
        if progress:
            progress(25, "Downloading selected GitHub commit")
        archive_url = API + "/zipball/" + sha
        archive = _get(archive_url, snapshot["token"], MAX_ARCHIVE)
        if progress:
            progress(70, "Verifying downloaded files")
        extract_verified(archive, snapshot, folder)
        local = {}
        for name in MANAGED_FILES:
            path = root / name
            local[name] = git_blob(path.read_bytes()) if path.exists() else None
        manifest = {
            "sha": sha,
            "blobs": snapshot["blobs"],
            "local": local,
            "files": list(MANAGED_FILES),
        }
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _load_manifest(stage: Path, root: Path) -> dict:
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("files") != list(MANAGED_FILES) or not SHA40.fullmatch(manifest.get("sha", "")):
        raise ValueError("Invalid staged update manifest")
    for name in MANAGED_FILES:
        data = (stage / name).read_bytes()
        if git_blob(data) != manifest["blobs"][name]:
            raise ValueError("Staged update changed after download")
        local = root / name
        current = git_blob(local.read_bytes()) if local.exists() else None
        if current != manifest["local"][name]:
            raise ValueError("Local program files changed after staging; check again")
    return manifest


def _wait_for_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x00100000, 0, pid)
        if handle:
            result = kernel.WaitForSingleObject(ctypes.c_void_p(handle), 60000)
            kernel.CloseHandle(ctypes.c_void_p(handle))
            if result != 0:
                raise TimeoutError("Old application did not shut down")
    else:
        for _ in range(300):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.2)
        raise TimeoutError("Old application did not shut down")


def _write_result(ok: bool, message: str, sha: str | None = None) -> None:
    try:
        directory = state_folder()
        directory.mkdir(parents=True, exist_ok=True)
        content = {"ok": ok, "message": message, "sha": sha,
                   "time": datetime.now(timezone.utc).isoformat()}
        target = directory / "last-update.json"
        temp = directory / "last-update.tmp"
        temp.write_text(json.dumps(content), encoding="utf-8")
        os.replace(temp, target)
    except OSError:
        pass


def last_result() -> dict | None:
    try:
        value = json.loads((state_folder() / "last-update.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def apply_stage(stage: Path, root: Path, wait_pid=0, restart=False) -> Path:
    """Back up user data, install allowlisted files, and roll back on a failure."""
    stage, root = Path(stage).resolve(), Path(root).resolve()
    _wait_for_pid(wait_pid)
    manifest = _load_manifest(stage, root)
    home = state_folder()
    home.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = home / "backups" / stamp
    backup.mkdir(parents=True)
    original = {}
    replaced = []
    try:
        for name in MANAGED_FILES:
            old = root / name
            original[name] = old.exists()
            if old.exists():
                shutil.copy2(old, backup / name)
        database = root / "stonk.db"
        if database.is_file():
            with contextlib.closing(sqlite3.connect(str(database))) as source:
                with contextlib.closing(sqlite3.connect(str(backup / "stonk.db"))) as target:
                    source.backup(target)
        # Atomic per-file replacement; validated files are never executed before approval.
        for name in MANAGED_FILES:
            temporary = root / ("." + name + ".update-tmp")
            try:
                shutil.copy2(stage / name, temporary)
                os.replace(temporary, root / name)
                replaced.append(name)
            finally:
                temporary.unlink(missing_ok=True)
        _write_result(True, "Application files updated successfully", manifest["sha"])
    except Exception as exc:
        for name in reversed(replaced):
            try:
                if original[name]:
                    restore = root / ("." + name + ".restore-tmp")
                    shutil.copy2(backup / name, restore)
                    os.replace(restore, root / name)
                else:
                    (root / name).unlink(missing_ok=True)
            except OSError:
                pass
        _write_result(False, "Update failed; original files restored where possible: " + str(exc))
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if restart:
        _launch_app(root)
    return backup


def _launch_app(root: Path) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [sys.executable, str(root / "StonkResearch.pyw"), "--no-browser"],
        cwd=str(root), creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class UpdateManager:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.snapshot_data = None
        self.stage = None
        self.last_check = 0.0
        self.data = {
            "status": "idle", "available": False, "percent": 0,
            "message": "Not checked yet", "latest_sha": None,
            "private_auth": "GitHub CLI sign-in is needed if the repository is private.",
        }

    def status(self) -> dict:
        with self.lock:
            result = dict(self.data)
        result["last_result"] = last_result()
        return result

    def _set(self, **fields):
        with self.lock:
            self.data.update(fields)

    def check(self, force=False) -> dict:
        with self.lock:
            if self.data["status"] in ("checking", "downloading", "ready", "installing"):
                return self.status_unlocked()
            if not force and time.time() - self.last_check < CHECK_INTERVAL:
                return self.status_unlocked()
            self.data.update(status="checking", message="Checking GitHub main branch", percent=0)
        threading.Thread(target=self._check_worker, daemon=True).start()
        return self.status()

    def status_unlocked(self):
        return dict(self.data)

    def _check_worker(self):
        try:
            snapshot = get_github_snapshot()
            changed = local_changes(self.root, snapshot["blobs"])
            with self.lock:
                self.snapshot_data = snapshot
                self.last_check = time.time()
                self.data.update(
                    status="available" if changed else "current",
                    available=bool(changed), changed=changed,
                    latest_sha=snapshot["sha"][:12],
                    source_url="https://github.com/" + OWNER + "/" + REPO + "/commits/" + BRANCH,
                    updated_at=snapshot["updated_at"], percent=0,
                    message=("New source update is available" if changed
                             else "You are up to date with GitHub main"),
                )
        except Exception as exc:
            self._set(status="error", available=False, message=str(exc))
            with self.lock:
                self.last_check = time.time()

    def download(self):
        with self.lock:
            if self.data["status"] != "available" or self.snapshot_data is None:
                raise ValueError("Check for an available update before downloading")
            snapshot = dict(self.snapshot_data)
            self.data.update(status="downloading", percent=5,
                             message="Preparing update download")
        threading.Thread(target=self._download_worker, args=(snapshot,), daemon=True).start()
        return self.status()

    def _download_worker(self, snapshot):
        try:
            stage = stage_download(
                snapshot, self.root,
                lambda percent, msg: self._set(percent=percent, message=msg),
            )
            with self.lock:
                self.stage = stage
                self.data.update(status="ready", percent=100,
                                 message="Verified update ready. Restart to install.",
                                 available=True)
        except Exception as exc:
            self._set(status="error", percent=0, message="Update download failed: " + str(exc))

    def install(self):
        with self.lock:
            if self.data["status"] != "ready" or not self.stage:
                raise ValueError("No verified update is ready to install")
            stage = self.stage
            self.data.update(status="installing", message="Restarting to install update")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                [sys.executable, str(self.root / "update_support.py"), "--apply",
                 str(stage), str(self.root), str(os.getpid()), "restart"],
                cwd=str(self.root), creationflags=flags,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._set(status="ready", message="Could not launch the updater process")
            raise
        return {"ok": True, "message": "The application will restart to install the update"}


def _main():
    if len(sys.argv) != 6 or sys.argv[1] != "--apply":
        raise SystemExit("This file is part of SmartStockAZY; launch StonkResearch.pyw.")
    stage = Path(sys.argv[2])
    root = Path(sys.argv[3])
    pid = int(sys.argv[4])
    restart = sys.argv[5] == "restart"
    try:
        apply_stage(stage, root, wait_pid=pid, restart=restart)
    except Exception as exc:
        _write_result(False, "Update failed: " + str(exc))
        # Start the restored build so the application remains usable.
        _launch_app(root)


if __name__ == "__main__":
    _main()
