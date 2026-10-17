"""The native window: pywebview showing ui/index.html from the package's own files.

No HTTP server anywhere (Seth, 2026-10-12 — a loopback server trips anti-malware software):
the page is a `file://` document and talks to Python only through the exposed `js_api`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import APP_NAME
from .api import Api
from .config import AppConfig, local_data_dir

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

    config = AppConfig()
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

    state = {"maximized": True}

    def on_maximized():
        state["maximized"] = True

    def on_restored():
        state["maximized"] = False

    def on_closing():
        try:
            if not state["maximized"]:      # a maximized window's size is the screen's, not a size to restore to
                config.data["window"] = {"width": window.width, "height": window.height}
                config.save()
        except Exception:  # noqa: BLE001
            pass
        api._flex.close()
        # the backup on close (Seth, 2026-10-17): a separate quiet process, so the window closes
        # at once and the upload carries on; skipped when nothing changed since the last one
        try:
            if api._backup.needed():
                _start_backup_process(str(api._nb.root))
        except Exception:  # noqa: BLE001 — a backup problem must never stop the app closing
            pass

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
        links.watch_requests(open_link)
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
        lock.release()
    return 0


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
