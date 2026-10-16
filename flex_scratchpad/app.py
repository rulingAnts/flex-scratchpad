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
    window = webview.create_window(
        APP_NAME,
        url=ui_url(),                       # a file:// URL: never a plain path (that starts an HTTP server), never html=
        js_api=api,
        width=int(size.get("width", 1280)),
        height=int(size.get("height", 820)),
        min_size=(760, 480),
        text_select=True,
    )
    api._window = window

    def on_closing():
        try:
            config.data["window"] = {"width": window.width, "height": window.height}
            config.save()
        except Exception:  # noqa: BLE001
            pass
        api._flex.close()

    window.events.closing += on_closing

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
