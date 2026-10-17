"""Backing the notebook up (Seth, 2026-10-17), to one of two kinds of place:

  * a CLOUD SYNC FOLDER — OneDrive, Google Drive, Dropbox, iCloud Drive, Box: an ordinary folder
    that the provider's own program uploads ("a simple file browse operation that makes an
    educated guess at the correct folders": `cloud_folders()` finds them);
  * S3-COMPATIBLE STORAGE through rclone (Amazon S3, Cloudflare R2, Backblaze B2, Wasabi, MinIO,
    DigitalOcean Spaces, any other), with the access keys in the Windows Credential Manager.

Either way a backup is a MIRROR that keeps old versions: `<dest>/current/` is the notebook as it
is now, and whatever a backup changes or removes there is first moved to
`<dest>/versions/<YYYY-MM-DD_HHMMSS>/`, so an earlier state can always be got back. Optionally the
files are encrypted before they leave the computer (rclone's `crypt`; its password is a secret too).
Backups run on demand and when the app closes (skipped when nothing changed).

rclone gets its whole configuration through environment variables (RCLONE_CONFIG_<REMOTE>_…) and
an EMPTY config file of our own, so no secret is ever on a command line or in an rclone.conf, and
a user's own rclone.conf is never read. Without encryption a folder backup needs no rclone at all
(`_mirror_folder`, plain Python); rclone is bundled with the Windows build (`<app>/rclone/`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

REMOTE, CRYPT = "fsbackup", "fsbackupc"
SECRETS = ("access_key_id", "secret_access_key", "crypt_password")
SECRET_PREFIX = "backup/"

# (id, label, rclone provider, endpoint example, region example)
PROVIDERS = [
    ("aws", "Amazon S3", "AWS", "", "us-east-1"),
    ("r2", "Cloudflare R2", "Cloudflare", "https://<account id>.r2.cloudflarestorage.com", "auto"),
    ("b2", "Backblaze B2", "Other", "https://s3.<region>.backblazeb2.com", "<region>"),
    ("wasabi", "Wasabi", "Wasabi", "https://s3.<region>.wasabisys.com", "<region>"),
    ("do", "DigitalOcean Spaces", "DigitalOcean", "https://<region>.digitaloceanspaces.com", ""),
    ("minio", "MinIO", "Minio", "https://minio.example.org", ""),
    ("other", "Other S3-compatible", "Other", "https://…", ""),
]
DEFAULTS = {"kind": "", "folder": "", "provider": "aws", "endpoint": "", "region": "", "bucket": "",
            "prefix": "", "encrypt": False, "onClose": True, "rclone": "", "keepDays": 0, "last": None}
SKIP = re.compile(r"(\.tmp|\.part|~)$|(^|/)(\.~lock\.|~\$)", re.I)


def bundled_rclone() -> Path | None:
    """The rclone shipped with the Windows build, beside the program: `<app>/rclone/rclone.exe`."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve().parent / "rclone" / ("rclone.exe" if sys.platform == "win32" else "rclone")
    return exe if exe.is_file() else None


def find_rclone(configured: str = "") -> str | None:
    b = bundled_rclone()
    for cand in ([configured] if configured else []) + [str(b) if b else "", shutil.which("rclone") or ""]:
        if cand and Path(cand).is_file():
            return cand
    return None


# -- cloud sync folders: the educated guess ------------------------------------------------

def cloud_folders(home: Path | None = None, env: dict | None = None, drives: list[str] | None = None) -> list[dict]:
    """The sync folders of OneDrive, Google Drive, Dropbox, iCloud Drive and Box on this computer,
    best guess first: [{service, label, path}]. Read from each program's own settings where it
    keeps them (OneDrive's environment variables, Dropbox's info.json), else the usual places."""
    env = os.environ if env is None else env
    home = Path(home or Path.home())
    out: list[dict] = []
    seen: set[str] = set()

    def add(service: str, label: str, path) -> None:
        if not path:
            return
        p = Path(path)
        key = str(p).casefold()
        if key in seen or not p.is_dir():
            return
        seen.add(key)
        out.append({"service": service, "label": label, "path": str(p)})

    # OneDrive (personal and work/school): the variables its client sets
    add("onedrive", "OneDrive", env.get("OneDriveConsumer"))
    add("onedrive", "OneDrive (work or school)", env.get("OneDriveCommercial"))
    add("onedrive", "OneDrive", env.get("OneDrive"))
    for p in sorted(home.glob("OneDrive*")):
        add("onedrive", "OneDrive" + (" (" + p.name.split(" - ", 1)[1] + ")" if " - " in p.name else ""), p)
    # Dropbox: info.json names its folders
    for base in (env.get("APPDATA"), env.get("LOCALAPPDATA")):
        if not base:
            continue
        try:
            info = json.loads((Path(base) / "Dropbox" / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for kind, d in (info or {}).items():
            if isinstance(d, dict):
                add("dropbox", "Dropbox" + (" (" + kind + ")" if kind != "personal" else ""), d.get("path"))
    add("dropbox", "Dropbox", home / "Dropbox")
    # Google Drive for desktop: a drive whose root holds "My Drive" (streaming), or a mirrored folder
    if drives is None:
        drives = [f"{c}:\\" for c in "DEFGHIJKLMNOPQRSTUVWXYZ"] if sys.platform == "win32" else []
    for d in drives:
        add("gdrive", "Google Drive (" + d.rstrip("\\") + ")", Path(d) / "My Drive")
    add("gdrive", "Google Drive", home / "My Drive")
    add("gdrive", "Google Drive", home / "Google Drive" / "My Drive")
    add("gdrive", "Google Drive", home / "Google Drive")
    add("icloud", "iCloud Drive", home / "iCloudDrive")
    add("icloud", "iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs")
    add("box", "Box", home / "Box")
    return out


def suggested_folder(cloud_root: str, notebook: Path) -> str:
    return str(Path(cloud_root) / "FLEx Scratchpad backup" / (Path(notebook).name or "Notebook"))


def tree_stamp(root: Path) -> str:
    """Count, total size and newest change of every file: unchanged stamp = nothing to back up."""
    n = size = newest = 0
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if SKIP.search(fn):
                continue
            try:
                st = os.stat(os.path.join(dirpath, fn))
            except OSError:
                continue
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)
    return f"{n}:{size}:{newest}"


class BackupError(RuntimeError):
    pass


class BackupCancelled(BackupError):
    pass


class Backup:
    """`progress(message)` feeds the status pill; `report(state)` the progress bars (Seth,
    2026-10-17: "a progress bar on the backup … or at the very least some kind of processing
    animation … (or when they exit)"): {phase: scanning|copying|finishing|done, percent (None while
    the size is not known yet), done, total (bytes), files, filesTotal, name}."""

    def __init__(self, config, secrets, notebook_root: Callable[[], Path], lock_dir: Path | None = None,
                 progress: Callable[[str], None] | None = None, report: Callable[[dict], None] | None = None):
        self.config = config
        self.secrets = secrets
        self.notebook_root = notebook_root
        self.progress = progress or (lambda m: None)
        self.report = report or (lambda d: None)
        from .config import local_data_dir
        self.lock_dir = Path(lock_dir or local_data_dir())
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._last_tick = 0.0
        self._last_stats: dict | None = None
        self._copy_t0: tuple | None = None
        self._last_phase = ""
        self.running = False

    def cancel(self) -> bool:
        """Stop a running backup: the file being copied is finished or dropped, never left half."""
        if not self.running:
            return False
        self._cancel.set()
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
        return True

    def _tick(self, phase: str, done: int = 0, total: int = 0, files: int = 0, files_total: int = 0, name: str = "",
              force: bool = False, eta: float | None = None) -> None:
        now = time.monotonic()
        if phase == "copying" and not self._copy_t0:
            self._copy_t0 = (now, done)
        edge = phase != self._last_phase or (total > 0 and done >= total) or (files_total > 0 and files >= files_total)
        if not force and not edge and now - self._last_tick < 0.2:      # a few updates a second is plenty,
            return                                                        # but never drop a new phase or the 100%
        self._last_tick = now
        self._last_phase = phase
        if eta is None and phase == "copying" and total > 0 and self._copy_t0:
            t0, d0 = self._copy_t0
            moved, spent = done - d0, now - t0
            if moved > 0 and spent >= 1.0:                  # a second of copying before guessing
                eta = (total - done) / (moved / spent)
        pct = None
        if total > 0:
            pct = max(0.0, min(100.0, 100.0 * done / total))
        elif files_total > 0:
            pct = max(0.0, min(100.0, 100.0 * files / files_total))
        try:
            self.report({"phase": phase, "percent": None if pct is None else round(pct, 1), "done": done, "total": total,
                         "files": files, "filesTotal": files_total, "name": name,
                         "eta": None if eta is None or eta < 0 else round(eta)})
        except Exception:  # noqa: BLE001 — a closed window must not stop the backup
            pass

    # -- settings -------------------------------------------------------------------

    def settings(self) -> dict:
        s = dict(DEFAULTS)
        s.update(self.config.data.get("backup") or {})
        return s

    def status(self) -> dict:
        self.config.load()                  # the backup on close ran in another process and recorded its result
        s = self.settings()
        rc = find_rclone(s.get("rclone", ""))
        return {"settings": s, "secrets": {k: self._has(k) for k in SECRETS}, "secretsWhere": self.secrets.where,
                "rclone": rc, "providers": [{"id": p[0], "label": p[1], "endpoint": p[3], "region": p[4]} for p in PROVIDERS],
                "clouds": cloud_folders(), "notebook": str(self.notebook_root()), "ready": self._ready(s)[0],
                "missing": self._ready(s)[1], "last": s.get("last")}

    def _has(self, k: str) -> bool:
        try:
            return self.secrets.has(SECRET_PREFIX + k)
        except OSError:
            return False

    def save(self, settings: dict, secrets: dict | None = None, forget: list | None = None) -> dict:
        cur = self.settings()
        for k in ("kind", "folder", "provider", "endpoint", "region", "bucket", "prefix", "rclone"):
            if k in settings:
                cur[k] = str(settings[k] or "").strip()
        for k in ("encrypt", "onClose"):
            if k in settings:
                cur[k] = bool(settings[k])
        if "keepDays" in settings:
            cur["keepDays"] = max(0, int(settings.get("keepDays") or 0))
        cur["bucket"] = cur["bucket"].strip("/")
        cur["prefix"] = cur["prefix"].strip("/\\")
        if cur["kind"] not in ("", "folder", "s3"):
            raise BackupError("Unknown kind of backup.")
        if cur["kind"] == "folder" and cur["folder"]:
            dest = Path(cur["folder"]).resolve()
            nb = Path(self.notebook_root()).resolve()
            if dest == nb or nb in dest.parents:
                raise BackupError("The backup folder cannot be inside the notebook.")
            if dest in nb.parents:
                raise BackupError("The backup folder cannot hold the notebook itself.")
        for k, v in (secrets or {}).items():
            if k in SECRETS and v:
                self.secrets.set(SECRET_PREFIX + k, str(v))
        for k in forget or []:
            if k in SECRETS:
                self.secrets.delete(SECRET_PREFIX + k)
        self.config.data["backup"] = cur
        self.config.save()
        return self.status()

    def _ready(self, s: dict) -> tuple[bool, list[str]]:
        miss = []
        if s["kind"] == "folder":
            if not s["folder"]:
                miss.append("a folder")
        elif s["kind"] == "s3":
            if not s["bucket"]:
                miss.append("a bucket")
            if s["provider"] != "aws" and not s["endpoint"]:
                miss.append("the endpoint")
            for k, label in (("access_key_id", "the access key ID"), ("secret_access_key", "the secret access key")):
                if not self._has(k):
                    miss.append(label)
        else:
            miss.append("a place to back up to")
        if s.get("encrypt") and not self._has("crypt_password"):
            miss.append("the encryption password")
        if (s["kind"] == "s3" or s.get("encrypt")) and not find_rclone(s.get("rclone", "")):
            miss.append("rclone")
        return (not miss, miss)

    # -- rclone ---------------------------------------------------------------------

    def _rclone_base(self, s: dict) -> tuple[str, dict]:
        rc = find_rclone(s.get("rclone", ""))
        if not rc:
            raise BackupError("rclone was not found. It comes with the Windows download; or set its path in Settings.")
        empty = self.lock_dir / "rclone-empty.conf"     # an empty config: nothing read, nothing written with secrets
        empty.parent.mkdir(parents=True, exist_ok=True)
        if not empty.exists():
            empty.write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("RCLONE_")}
        env["RCLONE_CONFIG"] = str(empty)
        return rc, env

    def _env(self, s: dict) -> tuple[str, dict, str]:
        """rclone, its environment, and the root of the backup as an rclone path."""
        rc, env = self._rclone_base(s)
        if s["kind"] == "s3":
            prov = next((p for p in PROVIDERS if p[0] == s["provider"]), PROVIDERS[-1])
            R = "RCLONE_CONFIG_" + REMOTE.upper() + "_"
            env.update({R + "TYPE": "s3", R + "PROVIDER": prov[2], R + "ENV_AUTH": "false", R + "NO_CHECK_BUCKET": "true",
                        R + "ACCESS_KEY_ID": self.secrets.get(SECRET_PREFIX + "access_key_id") or "",
                        R + "SECRET_ACCESS_KEY": self.secrets.get(SECRET_PREFIX + "secret_access_key") or ""})
            if s["endpoint"]:
                env[R + "ENDPOINT"] = s["endpoint"]
            if s["region"]:
                env[R + "REGION"] = s["region"]
            root = f"{REMOTE}:{s['bucket']}" + (f"/{s['prefix']}" if s["prefix"] else "")
        else:
            root = str(Path(s["folder"]))
        if s.get("encrypt"):
            C = "RCLONE_CONFIG_" + CRYPT.upper() + "_"
            env.update({C + "TYPE": "crypt", C + "REMOTE": root, C + "PASSWORD": self._obscure(rc, env, self.secrets.get(SECRET_PREFIX + "crypt_password") or ""),
                        C + "FILENAME_ENCRYPTION": "standard", C + "DIRECTORY_NAME_ENCRYPTION": "true"})
            root = CRYPT + ":"
        return rc, env, root

    @staticmethod
    def _obscure(rc: str, env: dict, password: str) -> str:
        """rclone wants the crypt password in its own obscured form; `rclone obscure -` reads it
        from stdin, so it is never on a command line either."""
        if not password:
            raise BackupError("The encryption password is not set.")
        r = subprocess.run([rc, "obscure", "-"], input=password, capture_output=True, text=True, env=env, timeout=60,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            raise BackupError("rclone could not take the encryption password: " + (r.stderr or "").strip()[-300:])
        return r.stdout.strip()

    def _json(self, rc: str, env: dict, args: list[str], timeout: int = 600):
        """An rclone listing whose stdout is JSON (stderr kept apart)."""
        flags = ["--contimeout", "15s", "--timeout", "60s", "--retries", "2", "--low-level-retries", "3"]
        r = subprocess.run([rc, *args, *flags], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=_NO_WINDOW)
        if r.returncode != 0:
            if re.search(r"directory not found|not found", r.stderr or "", re.I):
                return None
            raise BackupError(_plain_error(r.stderr))
        try:
            return json.loads(r.stdout or "null")
        except ValueError:
            raise BackupError("rclone answered something unexpected: " + (r.stdout or "")[:200])

    def _run(self, rc: str, env: dict, args: list[str], timeout: int = 6 * 3600, stats: bool = False) -> str:
        """rclone, its output read line by line. With `stats` it reports progress every second as
        JSON (`--use-json-log`: the stats ride in a "stats" field), which becomes the bar."""
        flags = ["--contimeout", "15s", "--timeout", "60s", "--retries", "2", "--low-level-retries", "3"]
        if stats:
            flags += ["--use-json-log", "--stats", "1s", "-v"]
        p = subprocess.Popen([rc, *args, *flags], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        self._proc = p
        lines: list[str] = []
        errors: list[str] = []
        t0 = time.monotonic()
        assert p.stdout is not None
        try:
            for line in p.stdout:
                line = line.rstrip()
                if not line:
                    continue
                lines.append(line)
                obj = None
                if line.startswith("{"):
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        obj = None
                if obj is not None:
                    st = obj.get("stats")
                    if isinstance(st, dict):
                        self._last_stats = st
                        self._tick("copying", int(st.get("bytes") or 0), int(st.get("totalBytes") or 0),
                                   int(st.get("transfers") or 0) + int(st.get("checks") or 0),
                                   int(st.get("totalTransfers") or 0) + int(st.get("totalChecks") or 0),
                                   eta=st.get("eta") if isinstance(st.get("eta"), (int, float)) else None)
                    if str(obj.get("level", "")).lower() in ("error", "critical"):
                        errors.append(str(obj.get("msg", "")))
                        self.progress("Backup: " + str(obj.get("msg", ""))[:160])
                elif "ERROR" in line or "Failed" in line:
                    errors.append(line)
                    self.progress("Backup: " + re.sub(r"^.*?(INFO|NOTICE|ERROR)\s*:\s*", "", line)[:160])
                if time.monotonic() - t0 > timeout:
                    p.kill()
                    raise BackupError("The backup took too long and was stopped.")
            code = p.wait()
        finally:
            self._proc = None
        if self._cancel.is_set():
            raise BackupCancelled("The backup was stopped.")
        if code != 0:
            raise BackupError(_plain_error("\n".join((errors or lines)[-4:])))
        return "\n".join(lines)

    # -- operations ---------------------------------------------------------------------

    def test(self) -> dict:
        s = self.settings()
        ok, miss = self._ready(s)
        if not ok:
            return {"ok": False, "message": "Still needed: " + ", ".join(miss) + "."}
        try:
            if s["kind"] == "folder" and not s.get("encrypt"):
                dest = Path(s["folder"])
                dest.mkdir(parents=True, exist_ok=True)
                probe = dest / ".fs-write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return {"ok": True, "message": "The folder can be written to: " + str(dest)}
            rc, env, root = self._env(s)
            self._run(rc, env, ["lsf", root, "--max-depth", "1"], timeout=120)
            return {"ok": True, "message": "Connected: " + (f"{s['bucket']}/{s['prefix']}" if s["kind"] == "s3" else s["folder"])}
        except (BackupError, OSError) as e:
            return {"ok": False, "message": str(e)}

    def _lock(self) -> Path | None:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock = self.lock_dir / "backup.lock"
        try:
            if lock.exists() and time.time() - lock.stat().st_mtime > 6 * 3600:
                lock.unlink()                      # a backup that died long ago
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            return None

    def needed(self) -> bool:
        """For the backup on close: configured, on, and something changed since the last good one."""
        s = self.settings()
        if not s.get("onClose") or not self._ready(s)[0]:
            return False
        last = s.get("last") or {}
        return not (last.get("ok") and last.get("stamp") == tree_stamp(Path(self.notebook_root())))

    def run(self, reason: str = "manual") -> dict:
        s = self.settings()
        ok, miss = self._ready(s)
        if not ok:
            raise BackupError("The backup is not set up yet: still needed " + ", ".join(miss) + ".")
        lock = self._lock()
        if not lock:
            return {"ok": False, "busy": True, "message": "A backup is already running."}
        self._cancel.clear()
        self._last_stats = None
        self._copy_t0 = None
        self.running = True
        self._tick("scanning", force=True)
        nb = Path(self.notebook_root())
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        t0 = time.monotonic()
        result = {"when": datetime.now().replace(microsecond=0).isoformat(), "reason": reason, "ok": False, "message": ""}
        try:
            before = tree_stamp(nb)
            self.progress("Backing up the notebook…")
            if s["kind"] == "folder" and not s.get("encrypt"):
                n = _mirror_folder(nb, Path(s["folder"]), stamp, tick=self._tick, cancelled=self._cancel.is_set)
                result["message"] = _summary(n["copied"], n["bytes"], n["kept"], s["folder"])
            else:
                rc, env, root = self._env(s)
                self._run(rc, env, ["sync", str(nb), root + ("" if root.endswith(":") else "/") + "current",
                                    "--backup-dir", root + ("" if root.endswith(":") else "/") + "versions/" + stamp,
                                    "--exclude", "*.tmp", "--exclude", "*.part", "--exclude", "~$*"], stats=True)
                st = self._last_stats or {}
                result["message"] = _summary(int(st.get("transfers") or 0), int(st.get("bytes") or 0), None,
                                             f"{s['bucket']}/{s['prefix']}" if s["kind"] == "s3" else s["folder"])
            result.update(ok=True, stamp=before, seconds=round(time.monotonic() - t0, 1))
            self._tick("finishing", force=True)
            if int(s.get("keepDays") or 0) > 0:             # "keep old versions for N days"
                gone = self.prune(older_than_days=int(s["keepDays"]), _locked=True)
                if gone["versions"]:
                    result["message"] += f" {len(gone['versions'])} version(s) older than {s['keepDays']} days removed."
        except BackupCancelled:
            result.update(message="Stopped before it finished; the next backup carries on from there.", cancelled=True)
        except (BackupError, OSError) as e:
            result["message"] = str(e)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass
            self.running = False
            self.progress("")
            self._tick("done", force=True)
        self.config.load()                  # another process (the backup on close) may have saved meanwhile
        self.config.data.setdefault("backup", {}).update({"last": result})
        self.config.save()
        return result

    def _dest_join(self, root: str, sub: str) -> str:
        return root + ("" if root.endswith(":") else "/") + sub

    def versions(self) -> list[str]:
        s = self.settings()
        if s["kind"] == "folder" and not s.get("encrypt"):
            v = Path(s["folder"]) / "versions"
            return sorted((p.name for p in v.iterdir() if p.is_dir() and VERSION_RE.match(p.name)), reverse=True) if v.is_dir() else []
        rc, env, root = self._env(s)
        items = self._json(rc, env, ["lsjson", self._dest_join(root, "versions"), "--dirs-only", "--no-mimetype", "--no-modtime"], timeout=300) or []
        return sorted((str(e.get("Path", "")) for e in items if VERSION_RE.match(str(e.get("Path", "")))), reverse=True)

    def usage(self) -> dict:
        """How much the backup takes: the current copy and each dated version (newest first)."""
        s = self.settings()
        out = {"current": {"files": 0, "bytes": 0}, "versions": [], "total": 0}
        if s["kind"] == "folder" and not s.get("encrypt"):
            root = Path(s["folder"])
            out["current"] = _dir_size(root / "current")
            vdir = root / "versions"
            for v in sorted((p for p in vdir.iterdir() if p.is_dir()) if vdir.is_dir() else [], key=lambda p: p.name, reverse=True):
                out["versions"].append(dict(name=v.name, **_dir_size(v)))
        else:
            rc, env, root = self._env(s)
            cur = self._json(rc, env, ["size", self._dest_join(root, "current"), "--json"]) or {}
            out["current"] = {"files": int(cur.get("count") or 0), "bytes": int(cur.get("bytes") or 0)}
            by: dict[str, dict] = {}
            for e in self._json(rc, env, ["lsjson", self._dest_join(root, "versions"), "-R", "--files-only", "--no-mimetype", "--no-modtime"]) or []:
                top = str(e.get("Path", "")).split("/", 1)[0]
                b = by.setdefault(top, {"files": 0, "bytes": 0})
                b["files"] += 1
                b["bytes"] += max(0, int(e.get("Size") or 0))
            out["versions"] = [dict(name=k, **v) for k, v in sorted(by.items(), reverse=True) if VERSION_RE.match(k)]
        out["total"] = out["current"]["bytes"] + sum(v["bytes"] for v in out["versions"])
        return out

    def prune(self, names: list[str] | None = None, older_than_days: int | None = None, _locked: bool = False) -> dict:
        """Remove dated versions: the ones named, or those older than N days. The current copy is
        never touched, so the notebook as it was at the last backup is always there."""
        s = self.settings()
        lock = None if _locked else self._lock()
        if not _locked and not lock:
            raise BackupError("A backup is running; try again when it has finished.")
        try:
            have = self.versions()
            if names is not None:
                todo = [n for n in names if n in have]
            else:
                cutoff = time.time() - (older_than_days or 0) * 86400
                todo = [n for n in have if _version_time(n) < cutoff] if older_than_days else []
            freed = 0
            if s["kind"] == "folder" and not s.get("encrypt"):
                for n in todo:
                    d = Path(s["folder"]) / "versions" / n
                    freed += _dir_size(d)["bytes"]
                    shutil.rmtree(d, ignore_errors=True)
            else:
                rc, env, root = self._env(s)
                for n in todo:
                    self._run(rc, env, ["purge", self._dest_join(root, "versions/" + n)], timeout=3600)
            return {"versions": todo, "bytes": freed}
        finally:
            if lock:
                try:
                    lock.unlink()
                except OSError:
                    pass

    def restore(self, target: Path, version: str = "") -> Path:
        """The backup (or, with `version`, the files that backup set aside) into `target`, which
        must be empty or new. The notebook itself is never touched."""
        s = self.settings()
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise BackupError("Restore into an empty folder.")
        if version and not re.match(r"^\d{4}-\d\d-\d\d_\d{6}$", version):
            raise BackupError("Not a backup version: " + version)
        sub = ("versions/" + version) if version else "current"
        target.mkdir(parents=True, exist_ok=True)
        self.progress("Restoring…")
        try:
            if s["kind"] == "folder" and not s.get("encrypt"):
                src = Path(s["folder"]) / sub
                if not src.is_dir():
                    raise BackupError("There is no backup there yet.")
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                rc, env, root = self._env(s)
                self._run(rc, env, ["copy", self._dest_join(root, sub), str(target)], stats=True)
        finally:
            self.progress("")
        return target


VERSION_RE = re.compile(r"^\d{4}-\d\d-\d\d_\d{6}$")


def _version_time(name: str) -> float:
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H%M%S").timestamp()
    except ValueError:
        return time.time()


def _dir_size(p: Path) -> dict:
    n = size = 0
    for dirpath, _, files in os.walk(p):
        for fn in files:
            try:
                size += os.stat(os.path.join(dirpath, fn)).st_size
                n += 1
            except OSError:
                pass
    return {"files": n, "bytes": size}


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _size(n: int) -> str:
    for unit, k in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= k:
            return f"{n / k:.1f} {unit}"
    return f"{n} B"


def _summary(files: int, size: int, kept: int | None, where: str) -> str:
    """What a finished backup says (Seth, 2026-10-17: it should tell the user it has in fact
    finished, and what it did)."""
    if not files and not kept:
        return f"nothing had changed since the last backup; {where} is up to date."
    out = f"{files} file{'s' if files != 1 else ''} ({_size(size)}) copied to {where}" if files else f"{where} is up to date"
    if kept:
        out += f"; {kept} earlier cop{'ies' if kept != 1 else 'y'} kept in a dated version"
    return out + "."


def _plain_error(text: str) -> str:
    t = text or "rclone failed."
    if re.search(r"InvalidAccessKeyId|SignatureDoesNotMatch|AccessDenied|403", t):
        return "The storage refused the keys (check the access key ID, the secret key and the bucket's permissions). " + t[-300:]
    if re.search(r"NoSuchBucket|404", t):
        return "The bucket was not found (check its name, the region and the endpoint). " + t[-300:]
    if re.search(r"no such host|dial tcp|connection refused|timeout|i/o timeout", t, re.I):
        return "Could not reach the storage (offline, or a wrong endpoint). " + t[-300:]
    return t[-500:]


def _mirror_folder(src: Path, dest: Path, stamp: str, tick=None, cancelled=None) -> dict:
    """A plain folder backup without rclone: `dest/current` becomes a copy of `src`; a file that
    would be replaced or removed there is moved to `dest/versions/<stamp>/` first (nothing lost).
    Unchanged files (same size and modification time) are not copied again. Two passes, so the
    progress (`tick`) knows the total before it starts; `cancelled()` is asked between pieces of a
    file — a file is copied to `.part` and only then put in place, so a stop never leaves half a file."""
    tick = tick or (lambda *a, **k: None)
    cancelled = cancelled or (lambda: False)
    cur, ver = dest / "current", dest / "versions" / stamp
    cur.mkdir(parents=True, exist_ok=True)
    copied = kept = 0

    def set_aside(p: Path) -> None:
        nonlocal kept
        rel = p.relative_to(cur)
        to = ver / rel
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(to))
        kept += 1

    wanted: set[str] = set()
    plan: list[tuple[Path, Path, int]] = []
    for dirpath, dirnames, files in os.walk(src):
        rel_dir = Path(dirpath).relative_to(src)
        for fn in files:
            if SKIP.search(fn):
                continue
            s_file = Path(dirpath) / fn
            rel = rel_dir / fn
            wanted.add(rel.as_posix())
            d_file = cur / rel
            try:
                st = s_file.stat()
            except OSError:
                continue
            if d_file.is_file():
                dt = d_file.stat()
                if dt.st_size == st.st_size and dt.st_mtime_ns == st.st_mtime_ns:   # else copied again: the safe side
                    continue
            plan.append((s_file, d_file, st.st_size))
    total = sum(x[2] for x in plan)
    done = 0
    tick("copying", 0, total, 0, len(plan), force=True)
    for i, (s_file, d_file, size) in enumerate(plan):
        if cancelled():
            raise BackupCancelled("The backup was stopped.")
        if d_file.is_file() or d_file.exists():   # the older copy (or a folder where a file now is) is kept
            set_aside(d_file)
        d_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = d_file.with_name(d_file.name + ".part")
        try:
            with open(s_file, "rb") as fi, open(tmp, "wb") as fo:
                while True:
                    chunk = fi.read(1 << 20)
                    if not chunk:
                        break
                    fo.write(chunk)
                    done += len(chunk)
                    tick("copying", done, total, i, len(plan), s_file.name)
                    if cancelled():
                        raise BackupCancelled("The backup was stopped.")
            shutil.copystat(s_file, tmp)
            os.replace(tmp, d_file)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        copied += 1
        tick("copying", done, total, i + 1, len(plan), s_file.name)
    # what is gone from the notebook is set aside, not deleted
    for dirpath, dirnames, files in os.walk(cur, topdown=False):
        for fn in files:
            p = Path(dirpath) / fn
            if p.relative_to(cur).as_posix() not in wanted:
                set_aside(p)
        if Path(dirpath) != cur:
            try:
                Path(dirpath).rmdir()          # only when empty
            except OSError:
                pass
    tick("copying", total, total, len(plan), len(plan), force=True)
    return {"copied": copied, "kept": kept, "bytes": done}
