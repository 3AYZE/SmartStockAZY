"""Secure, opt-in update manager for the frozen Windows SmartStockAZY executable.

For frozen builds only: checks GitHub Releases, verifies SHA-256 for the exact
release asset, and stages a verified executable. A temporary copy of the *old*
EXE waits for process exit and replaces the installed EXE with rollback.
Never downloads a .pyw and never overwrites the user's SQLite database.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import update_support

REPO_API = "https://api.github.com/repos/3AYZE/SmartStockAZY"
MAX_EXE_SIZE = 160 * 1024 * 1024
MAX_RELEASE_METADATA = 1024 * 1024
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
TAG = re.compile(r"^v0\.6\.(\d+)$")
TRUSTED_HOSTS = {
    "api.github.com", "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
CHECK_INTERVAL = 6 * 60 * 60


def user_data_dir() -> Path:
    return update_support.state_folder()


def installed_build(resource_root: Path) -> dict:
    path = Path(resource_root) / "build_info.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _redirect_handler():
    class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urllib.parse.urlparse(newurl)
            previous = urllib.parse.urlparse(req.full_url)
            if target.scheme != "https" or target.hostname not in TRUSTED_HOSTS:
                raise ValueError("GitHub redirected an update to an untrusted host")
            safe = dict(headers)
            # Never send GitHub credentials to redirect CDN hosts.
            if target.hostname != previous.hostname:
                safe.pop("Authorization", None)
                safe.pop("authorization", None)
            return super().redirect_request(req, fp, code, msg, safe, newurl)
    return RestrictedRedirect()


def _open(url: str, token: str | None = None,
          accept: str = "application/vnd.github+json"):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS:
        raise ValueError("Untrusted update source")
    headers = {
        "User-Agent": "SmartStockAZY-EXE-Updater",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(_redirect_handler())
    return opener.open(urllib.request.Request(url, headers=headers), timeout=30)


def _read_limited(url, token, limit=MAX_RELEASE_METADATA, accept="application/vnd.github+json"):
    with _open(url, token, accept) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError("GitHub metadata exceeds the size limit")
    return result


def _private_token():
    token = update_support._cli_token()
    if not token:
        raise RuntimeError(
            "GitHub repository access is private or restricted. "
            "Install the free GitHub CLI, run 'gh auth login' once, then retry. "
            "SmartStockAZY does not store your GitHub token."
        )
    return token


def newest_release() -> dict:
    """Returns only the verified repository's latest published EXE release metadata."""
    url = REPO_API + "/releases/latest"
    token = None
    try:
        raw = _read_limited(url, None)
    except urllib.error.HTTPError as exc:
        if exc.code not in (401, 403, 404):
            raise
        token = _private_token()
        raw = _read_limited(url, token)
    data = json.loads(raw.decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        raise RuntimeError("GitHub latest release is not a stable release")
    tag = str(data.get("tag_name") or "")
    if not TAG.fullmatch(tag):
        raise ValueError("Unexpected GitHub release tag")
    asset = next((a for a in data.get("assets", [])
                  if a.get("name") == "SmartStockAZY.exe"), None)
    if not asset:
        raise ValueError("Latest GitHub release has no SmartStockAZY.exe asset")
    if not isinstance(asset.get("id"), int) or not 0 < asset.get("size", 0) <= MAX_EXE_SIZE:
        raise ValueError("Invalid release executable asset")
    digest = str(asset.get("digest") or "")
    checksum_asset = next((a for a in data.get("assets", [])
                           if a.get("name") == "SmartStockAZY.exe.sha256"), None)
    if digest.startswith("sha256:") and SHA256.fullmatch(digest[7:]):
        expected_hash = digest[7:].lower()
    elif checksum_asset and isinstance(checksum_asset.get("id"), int):
        raw_checksum = _read_limited(
            REPO_API + "/releases/assets/" + str(checksum_asset["id"]),
            token, 4096, "application/octet-stream"
        )
        value = raw_checksum.decode("utf-8-sig").strip().split()[0]
        if not SHA256.fullmatch(value):
            raise ValueError("Invalid published SHA-256 checksum")
        expected_hash = value.lower()
    else:
        raise ValueError("Release missing trusted SHA-256 information")
    return {
        "tag": tag,
        "release_url": "https://github.com/3AYZE/SmartStockAZY/releases/tag/" + tag,
        "updated_at": data.get("published_at"),
        "asset_id": asset["id"],
        "asset_size": asset["size"],
        "sha256": expected_hash,
        "token": token,
    }


def is_newer(installed: dict, release: dict) -> bool:
    older = TAG.fullmatch(str(installed.get("tag", "")))
    newer = TAG.fullmatch(release["tag"])
    if not newer:
        return False
    if older:
        return int(newer.group(1)) > int(older.group(1))
    return release["tag"] != installed.get("tag")


def fetch_exe(release: dict, stage: Path, progress=None) -> Path:
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    destination = stage / "SmartStockAZY.exe"
    expected = release["sha256"]
    asset_url = REPO_API + "/releases/assets/" + str(release["asset_id"])
    digest = hashlib.sha256()
    total = 0
    try:
        with _open(asset_url, release["token"], "application/octet-stream") as response, \
                destination.open("wb") as target:
            content_type = response.headers.get("Content-Type", "").lower()
            if "json" in content_type:
                raise ValueError("GitHub returned metadata instead of the EXE asset")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_EXE_SIZE:
                    raise ValueError("Executable exceeds the maximum update size")
                target.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(min(98, max(3, int(total / release["asset_size"] * 100))),
                             "Downloading verified GitHub EXE")
        if total != release["asset_size"]:
            raise ValueError("Incomplete EXE download")
        if digest.hexdigest() != expected:
            raise ValueError("EXE update failed SHA-256 verification")
        with destination.open("rb") as source:
            if source.read(2) != b"MZ":
                raise ValueError("Downloaded asset is not a Windows executable")
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def result_path() -> Path:
    return user_data_dir() / "exe-update-result.json"


def write_result(ok: bool, message: str, tag=None):
    try:
        directory = user_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "ok": ok, "message": message, "tag": tag,
            "time": datetime.now(timezone.utc).isoformat(),
        }
        tmp = directory / "exe-update-result.tmp"
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, result_path())
    except OSError:
        pass


def last_result():
    try:
        value = json.loads(result_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spawn(executable: Path, args=None):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(executable)] + list(args or []), cwd=str(executable.parent),
        creationflags=flags, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def apply_executable_update(target: Path, staged: Path, sha256: str,
                            pid: int, tag: str):
    """Runs from a temporary COPY of the frozen EXE, not the installed EXE."""
    target = Path(target).resolve()
    staged = Path(staged).resolve()
    if (target.name.lower() != "smartstockazy.exe"
            or staged.name.lower() != "smartstockazy.exe"
            or not TAG.fullmatch(tag) or not SHA256.fullmatch(sha256)):
        raise ValueError("Invalid executable update request")
    if not staged.exists() or sha256_file(staged) != sha256.lower():
        raise ValueError("Staged EXE changed or failed integrity check")
    update_support._wait_for_pid(pid)
    backups = user_data_dir() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / ("SmartStockAZY-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".exe")
    shutil.copy2(target, backup)
    newfile = target.with_name("SmartStockAZY.exe.new")
    replaced = False
    try:
        shutil.copy2(staged, newfile)
        if sha256_file(newfile) != sha256.lower():
            raise ValueError("Install copy failed checksum verification")
        for attempt in range(5):
            try:
                os.replace(newfile, target)
                replaced = True
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(1.5)
        _spawn(target)
        write_result(True, "Installed " + tag + ". Previous EXE backed up.", tag)
    except Exception as exc:
        if replaced:
            restore = target.with_name("SmartStockAZY.exe.restore")
            try:
                shutil.copy2(backup, restore)
                os.replace(restore, target)
            except Exception as restore_error:
                write_result(False, "CRITICAL: executable rollback failed. Restore manually from "
                             + str(backup) + ": " + str(restore_error), tag)
                raise RuntimeError("Executable update and rollback both failed") from exc
        write_result(False, "EXE update failed; original executable retained/restored: " + str(exc), tag)
        # Recovery is permitted only when the original executable is restored.
        _spawn(target)
        raise
    finally:
        newfile.unlink(missing_ok=True)
        shutil.rmtree(staged.parent, ignore_errors=True)


def run_helper_command(argv: list[str]) -> bool:
    """Called BEFORE the normal startup when a PyInstaller EXE runs as a helper."""
    if not argv or argv[0] != "--apply-exe-update":
        return False
    if len(argv) != 6:
        raise ValueError("Invalid EXE updater invocation")
    _, target, stage, digest, pid, tag = argv
    apply_executable_update(Path(target), Path(stage), digest, int(pid), tag)
    return True


class ExeUpdateManager:
    """Same status/check/download/install contract as the portable source updater."""

    def __init__(self, resource_root: Path):
        self.installed = installed_build(resource_root)
        self.lock = threading.Lock()
        self.latest = None
        self.stage = None
        self.checked_at = 0.0
        self.data = {
            "status": "idle",
            "available": False, "percent": 0,
            "message": "Checking GitHub Releases when the application opens",
            "installed_version": self.installed.get("tag", "Unknown EXE build"),
            "latest_sha": None,
        }

    def _set(self, **values):
        with self.lock:
            self.data.update(values)

    def status(self):
        with self.lock:
            current = dict(self.data)
        current["last_result"] = last_result()
        return current

    def check(self, force=False):
        with self.lock:
            if self.data["status"] in ("checking", "downloading", "ready", "installing"):
                return self.data.copy()
            if not force and time.time() - self.checked_at < CHECK_INTERVAL:
                return self.data.copy()
            self.data.update(status="checking", message="Checking official GitHub Releases", percent=0)
        threading.Thread(target=self._check_worker, daemon=True).start()
        return self.status()

    def _check_worker(self):
        try:
            latest = newest_release()
            newer = is_newer(self.installed, latest)
            with self.lock:
                self.latest = latest
                self.checked_at = time.time()
                self.data.update(
                    status="available" if newer else "current", available=newer,
                    latest_sha=latest["tag"], release_url=latest["release_url"],
                    updated_at=latest["updated_at"],
                    changed=["SmartStockAZY.exe"] if newer else [],
                    message="New Windows EXE update available" if newer else "You are using the latest published EXE",
                )
        except Exception as exc:
            with self.lock:
                self.checked_at = time.time()
                self.data.update(status="error", available=False, message=str(exc))

    def download(self):
        with self.lock:
            if self.data["status"] != "available" or not self.latest:
                raise ValueError("No newer published EXE release is available")
            self.data.update(status="downloading", percent=0,
                             message="Downloading verified Windows EXE")
            release = dict(self.latest)
        threading.Thread(target=self._download_worker, args=(release,), daemon=True).start()
        return self.status()

    def _download_worker(self, release):
        folder = Path(tempfile.mkdtemp(prefix="SmartStockAZY-exe-"))
        try:
            exe = fetch_exe(
                release, folder,
                lambda percentage, msg: self._set(percent=percentage, message=msg)
            )
            with self.lock:
                self.stage = exe
                self.data.update(status="ready", percent=100, available=True,
                                 message="Verified Windows executable. Restart to install.")
        except Exception as exc:
            shutil.rmtree(folder, ignore_errors=True)
            self._set(status="error", percent=0, message="EXE download failed: " + str(exc))

    def install(self):
        if os.name != "nt" or not getattr(sys, "frozen", False):
            raise RuntimeError("EXE self-updates require a packaged Windows application")
        with self.lock:
            if self.data["status"] != "ready" or not self.stage or not self.latest:
                raise ValueError("No verified EXE is ready to install")
            target = Path(sys.executable).resolve()
            if target.name.lower() != "smartstockazy.exe":
                raise RuntimeError("Unexpected application executable name")
            stage, release = self.stage, self.latest
        if sha256_file(stage) != release["sha256"]:
            raise RuntimeError("Downloaded EXE changed since verification")
        helper_dir = Path(tempfile.mkdtemp(prefix="SmartStockAZY-helper-"))
        helper_exe = helper_dir / "SmartStockAZY-Updater.exe"
        try:
            shutil.copy2(target, helper_exe)
            _spawn(helper_exe, [
                "--apply-exe-update", str(target), str(stage),
                release["sha256"], str(os.getpid()), release["tag"],
            ])
        except Exception:
            shutil.rmtree(helper_dir, ignore_errors=True)
            raise
        self._set(status="installing", message="Closing application to safely install " + release["tag"])
        return {"ok": True, "message": "The application will restart after its verified EXE update"}
