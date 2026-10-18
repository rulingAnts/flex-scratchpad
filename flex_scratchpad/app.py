"""The native window: pywebview showing ui/index.html from the package's own files.

No HTTP server anywhere (Seth, 2026-10-12 — a loopback server trips anti-malware software):
the page is a `file://` document and talks to Python only through the exposed `js_api`.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from . import APP_NAME
from .api import Api
from .config import AppConfig, local_data_dir
from .log import LOG, banner

UI_DIR = Path(__file__).parent / "ui"


ICON = UI_DIR / "img" / "flex-scratchpad.ico"      # rendered from ui/img/icon*.svg by tools/make_icons.py


def _own_taskbar_identity() -> None:
    """On Windows, give the process its own AppUserModelID so the taskbar shows the app's icon
    and groups its window apart from other Python programs."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FLExScratchpad.App")
    except Exception:  # noqa: BLE001 — cosmetic; never a reason not to start
        pass


def _fit_to_screen(width: int, height: int) -> tuple[int, int]:
    """The remembered window size, shrunk to fit the primary screen: the size the window
    restores to when it is un-maximized must never hang off the edge (Seth, 2026-10-16)."""
    try:
        import webview
        scr = webview.screens[0]
        width = min(width, int(scr.width * 0.9))
        height = min(height, int(scr.height * 0.9))
    except Exception:  # noqa: BLE001 — no screen information: keep the remembered size
        pass
    return max(width, 760), max(height, 480)


def ui_url() -> str:
    """The page as a file:// URL. NEVER a plain path: pywebview treats a plain path as a "local
    URL" and starts its built-in HTTP server on 127.0.0.1 to serve it (pywebview 6.2,
    webview/__init__.py start(): `http_server or has_local_urls`). That server is exactly what
    Seth ruled out ("NO HTTP SERVER. EVER." — it triggers anti-malware software), and with a
    persistent WebView2 profile its responses were cached, so a reinstalled app kept showing
    its OLD page (2026-10-16). A file:// URL is loaded directly, with no server and no cache."""
    return (UI_DIR / "index.html").resolve().as_uri()


def run(notebook_dir: str | None = None, demo: bool = False, debug: bool = False, open_url: str | None = None) -> int:
    import json
    import webview  # imported here so the package stays importable without pywebview (tests, Linux)
    from . import links

    # One window per user: a second start (a flexscratchpad:// link clicked in FLEx or a
    # browser) hands its URL to the running instance through a file and exits.
    from . import build_id
    build = build_id()                  # this start's code, read before anything can replace it
    lock = links.InstanceLock()
    if not lock.acquire():
        # Seth, 2026-10-16: after a reinstall the OLD window kept running and a new start only
        # brought it forward, so the update looked missing. Say so here, and tell that window.
        links.hand_over(links.build_line(build))
        links.hand_over(open_url or "")
        print(f"FLEx Scratchpad is already running; brought its window to the front. Close it and "
              f"start again to run the installed build {build}.")
        return 0

    banner()
    config = AppConfig()
    LOG.info("config: %s", config.path)
    api = Api(config, notebook_dir=notebook_dir, demo=demo)
    size = config.data.get("window", {})
    width, height = _fit_to_screen(int(size.get("width", 1280)), int(size.get("height", 820)))
    window = webview.create_window(
        APP_NAME,
        url=ui_url(),                       # a file:// URL: never a plain path (that starts an HTTP server), never html=
        js_api=api,
        width=width,
        height=height,
        min_size=(760, 480),
        maximized=True,                     # Seth, 2026-10-16: the default size hung off his screen
        text_select=True,
    )
    api._window = window
    LOG.info("window created: %s (%dx%d, maximized)%s", ui_url(), width, height, "; developer tools ON (F12 or right-click → Inspect opens them in their own window)" if debug else "")

    state = {"maximized": True}

    def on_maximized():
        state["maximized"] = True

    def on_restored():
        state["maximized"] = False

    def on_closing():
        LOG.info("window closing (backup running: %s)", api._backup.running if getattr(api, '_backup', None) else False)
        # The backup on close (Seth, 2026-10-17: a progress bar "when they exit" too): the window
        # stays open while it runs, the page showing its progress with "Close now, finish in the
        # background" and "Close without backing up"; then it closes itself. Skipped when nothing
        # changed since the last good backup.
        if state.get("closing") and api._backup.running:
            api.backup_close_choice("background")   # ✕ again while it runs: close now, finish quietly
            return False
        if not state.get("closing"):
            try:
                if api._backup.needed() and not api._backup.running:
                    state["closing"] = True
                    threading.Thread(target=lambda: backup_then_close(api, window.destroy), daemon=True).start()
                    return False            # not yet: the page shows the backup
            except Exception:  # noqa: BLE001 — a backup problem must never stop the app closing
                pass
        try:
            if not state["maximized"]:      # a maximized window's size is the screen's, not a size to restore to
                config.data["window"] = {"width": window.width, "height": window.height}
                config.save()
        except Exception:  # noqa: BLE001
            pass
        api._flex.close()

    window.events.closing += on_closing
    for name, fn in (("maximized", on_maximized), ("restored", on_restored)):
        try:
            event = getattr(window.events, name)
            event += fn
        except Exception:  # noqa: BLE001 — an older pywebview without the event
            pass

    def open_link(url: str):
        other = links.parse_build_line(url)
        if other is not None:
            if other != build:          # a different build is installed than this window runs
                try:
                    window.evaluate_js("FS.otherBuild && FS.otherBuild(" + json.dumps(other) + ", " + json.dumps(build) + ")")
                except Exception:  # noqa: BLE001
                    pass
            return
        note_id = links.parse_note_url(url)
        js = "FS.openNoteById(" + json.dumps(note_id) + ")" if note_id else "FS.bringToFront && FS.bringToFront()"
        try:
            window.evaluate_js(js)
            try:
                window.restore()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    def on_loaded():
        # A file dropped from Explorer: only pywebview's own drop handler learns its full path
        # (the page sees a name and bytes), which "link instead of copy" needs (Seth, 2026-10-17).
        try:
            from webview.dom import DOMEventHandler
            window.dom.document.events.drop += DOMEventHandler(api._on_drop, False, False)
        except Exception:  # noqa: BLE001 — an older pywebview: dropped files are copied from their bytes
            pass
        if open_url:
            open_link(open_url)
        state["watcher"] = links.watch_requests(open_link)
        # the per-user scheme registration is cheap and idempotent; once per version is plenty
        try:
            # keyed on the build, not the version (which stays 0.1.0), so a new icon or launch
            # command reaches the registry after an update
            if config.data.get("linksRegistered") != build and links.register_scheme():
                config.data["linksRegistered"] = build
                config.save()
        except Exception:  # noqa: BLE001
            pass

    window.events.loaded += on_loaded
    storage = local_data_dir() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    # private_mode=False + storage_path: a persistent WebView2 profile, so the page's own
    # localStorage (UI preferences only) survives restarts. Everything that matters is on disk
    # through the Api anyway.
    try:
        _own_taskbar_identity()
        webview.start(debug=debug, private_mode=False, storage_path=str(storage), http_server=False,
                      icon=str(ICON) if ICON.exists() else None)
    finally:
        shut_down(api, state.get("watcher"))
        lock.release()
    return 0


def shut_down(api, watcher=None, wait: float = 5.0) -> None:
    """After the window is gone, before the process ends (Seth, 2026-10-17: closing the app
    printed "Unhandled Exception: Python.Runtime.InternalPythonnetException: Failed to create
    Python type for System.ComponentModel.InvalidAsynchronousStateException"). A thread still
    calling into .NET then — an event pushed to the page, a page call's answer, the link poller —
    reaches the window's ended UI thread (InvalidAsynchronousStateException) while Python is
    already shutting pythonnet down, and the process dies on it. So: nothing is pushed to the
    page any more, the poller stops, FLEx is closed, an Api call still writing (the last autosave)
    may finish, and `exit_now` ends the process without that shutdown."""
    LOG.info("shutting down")
    api._window = None                  # Api._emit is a no-op from here on
    if watcher is not None and getattr(watcher, "stop", None) is not None:
        watcher.stop.set()
    try:
        api._flex.close()               # idempotent: on_closing usually did it already
    except Exception:  # noqa: BLE001
        pass
    if api._lock.acquire(timeout=wait):
        api._lock.release()


def exit_now(code: int = 0) -> None:
    """End the process now, without Python's interpreter shutdown (see `shut_down`): daemon
    threads must not run into pythonnet's teardown. Everything worth keeping is on disk by now."""
    import os
    import sys
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:  # noqa: BLE001 — a windowed build has no console
            pass
    os._exit(code)


def _start_backup_process(notebook: str) -> None:
    """`<this program> --backup --notebook <dir>`, detached and windowless. It reads the settings
    and the secrets itself: nothing secret is on its command line."""
    import subprocess
    import sys
    args = [sys.executable] + ([] if getattr(sys, "frozen", False) else ["-m", "flex_scratchpad"]) + ["--backup", "--notebook", notebook]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


CLOSE_GRACE = 3.0       # seconds a cancelled backup gets to stop before the window closes anyway


def backup_then_close(api, destroy, start_process=None) -> str:
    """Back up while the window stays open, then close it (what closing the app does when a
    backup is due). The page shows the progress and answers through `Api.backup_close_choice`:
    'background' starts a quiet process to finish and closes, 'skip' closes; after a failure it
    waits for 'retry' or 'close'. Returns how it ended: ok | background | skipped | failed."""
    start_process = start_process or _start_backup_process
    notebook = str(api._nb.root)
    how = "failed"
    try:
        while True:
            api._close_choice = None
            api._close_evt.clear()
            api._emit("backupClosing", {"state": "running"})
            # The backup runs on its own thread so the user's answer is acted on AT ONCE (Seth,
            # 2026-10-18: "Close now, finish in the background" did nothing while the backup was
            # busy in a part of its work that could not be stopped). The choice cancels the run
            # (Api.backup_close_choice); the run gets a moment to stop cleanly — the lock released,
            # no half file left — and the window closes whether or not it has.
            box: dict = {}

            def _run():
                try:
                    box["r"] = api._backup.run("close")
                except Exception as e:  # noqa: BLE001
                    box["r"] = {"ok": False, "message": str(e)}
            t = threading.Thread(target=_run, name="backup-on-close", daemon=True)
            t.start()
            while t.is_alive():
                api._close_evt.wait(0.25)
                if api._close_choice in ("background", "skip"):
                    t.join(CLOSE_GRACE)
                    break
            choice = api._close_choice
            if choice == "background":
                start_process(notebook)
                how = "background"
                break
            if choice == "skip":
                how = "skipped"
                break
            r = box.get("r") or {}
            if r.get("ok") or r.get("busy"):
                how = "ok"
                break
            api._emit("backupClosing", {"state": "failed", "message": r.get("message", "")})
            api._close_evt.wait()
            if api._close_choice != "retry":
                break
    except Exception:  # noqa: BLE001 — whatever happens, the window closes
        pass
    try:
        destroy()
    except Exception:  # noqa: BLE001
        pass
    return how
