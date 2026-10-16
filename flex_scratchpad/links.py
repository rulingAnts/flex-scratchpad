"""`flexscratchpad://note/<id>` — a link that opens a note in the running app.

No sockets and no server (the house rule): the scheme is registered per user (HKCU on Windows,
no admin), a second instance started with the URL writes it to a request file in the app's
local data folder and exits, and the running instance polls that file. One instance at a time
is kept by a lock file held open for the life of the window.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from . import APP_NAME
from .config import local_data_dir

SCHEME = "flexscratchpad"


def note_url(note_id: str) -> str:
    return f"{SCHEME}://note/{note_id}"


def parse_note_url(url: str) -> str | None:
    """The note id in a flexscratchpad://note/<id> URL (query/fragment ignored), else None."""
    s = (url or "").strip()
    if not s.lower().startswith(SCHEME + "://"):
        return None
    rest = s[len(SCHEME) + 3:].strip("/")
    for sep in ("?", "#"):
        rest = rest.split(sep, 1)[0]
    parts = [p for p in rest.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "note":
        return parts[1]
    return None


def launch_command() -> str:
    """The shell command the registry runs for a link: the frozen exe, or pythonw -m."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            exe = pyw
    return f'"{exe}" -m flex_scratchpad "%1"'


def register_scheme() -> bool:
    """Register the scheme for the current user (Windows only; elsewhere returns False)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        base = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\\Classes\\{SCHEME}")
        winreg.SetValueEx(base, "", 0, winreg.REG_SZ, f"URL:{APP_NAME} link")
        winreg.SetValueEx(base, "URL Protocol", 0, winreg.REG_SZ, "")
        icon = winreg.CreateKey(base, "DefaultIcon")
        ico = Path(__file__).resolve().parent / "ui" / "img" / "flex-scratchpad.ico"
        winreg.SetValueEx(icon, "", 0, winreg.REG_SZ, f'"{ico}",0' if ico.exists() else f'"{sys.executable}",0')
        cmd = winreg.CreateKey(base, r"shell\\open\\command")
        winreg.SetValueEx(cmd, "", 0, winreg.REG_SZ, launch_command())
        return True
    except OSError:
        return False


# -- one running instance, and handing a URL to it -------------------------------------------

def _data_dir() -> Path:
    d = local_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def request_file() -> Path:
    return _data_dir() / "open-request.txt"


class InstanceLock:
    """Held open for the life of the window; a second instance fails to take it."""

    def __init__(self, path: Path | None = None):
        self.path = path or (_data_dir() / "instance.lock")
        self.fh = None

    def acquire(self) -> bool:
        try:
            self.fh = open(self.path, "a+", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fh.seek(0)
            self.fh.truncate()
            self.fh.write(str(os.getpid()))
            self.fh.flush()
            return True
        except OSError:
            if self.fh is not None:
                try:
                    self.fh.close()
                except OSError:
                    pass
                self.fh = None
            return False

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            self.fh.close()
        except OSError:
            pass
        self.fh = None


def hand_over(url: str, path: Path | None = None) -> None:
    """Leave a URL (or an empty line = "come to the front") for the running instance."""
    p = path or request_file()
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write((url or "").strip() + "\n")


BUILD_PREFIX = "#build "


def build_line(build: str) -> str:
    """The hand-over line that tells the running instance which build a second start would run
    (an older instance reads it as a plain "come to the front")."""
    return BUILD_PREFIX + (build or "").strip()


def parse_build_line(line: str) -> str | None:
    return line[len(BUILD_PREFIX):].strip() or None if (line or "").startswith(BUILD_PREFIX) else None


def take_requests(path: Path | None = None) -> list[str]:
    """Read and clear the request file; [] when there is nothing."""
    p = path or request_file()
    try:
        if not p.exists() or p.stat().st_size == 0:
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        p.write_text("", encoding="utf-8")
        return lines
    except OSError:
        return []


def watch_requests(callback, interval: float = 0.7, path: Path | None = None, stop: threading.Event | None = None) -> threading.Thread:
    """A daemon thread calling `callback(url)` for every handed-over line."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            for line in take_requests(path):
                try:
                    callback(line)
                except Exception:  # noqa: BLE001 — the watcher outlives a bad request
                    pass
            time.sleep(interval)

    t = threading.Thread(target=loop, name="flex-scratchpad-links", daemon=True)
    t.stop = stop  # type: ignore[attr-defined]
    t.start()
    return t
