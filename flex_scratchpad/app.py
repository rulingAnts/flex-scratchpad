"""The native window: pywebview showing ui/index.html from the package's own files.

No HTTP server anywhere (Seth, 2026-10-12 — a loopback server trips anti-malware software):
the page is a `file://` document and talks to Python only through the exposed `js_api`.
"""
from __future__ import annotations

from pathlib import Path

from . import APP_NAME
from .api import Api
from .config import AppConfig, local_data_dir

UI_DIR = Path(__file__).parent / "ui"


def run(notebook_dir: str | None = None, demo: bool = False, debug: bool = False, open_url: str | None = None) -> int:
    import json
    import webview  # imported here so the package stays importable without pywebview (tests, Linux)
    from . import links

    # One window per user: a second start (a flexscratchpad:// link clicked in FLEx or a
    # browser) hands its URL to the running instance through a file and exits.
    lock = links.InstanceLock()
    if not lock.acquire():
        links.hand_over(open_url or "")
        return 0

    config = AppConfig()
    api = Api(config, notebook_dir=notebook_dir, demo=demo)
    size = config.data.get("window", {})
    window = webview.create_window(
        APP_NAME,
        url=str(UI_DIR / "index.html"),     # url=, never html= — a file document keeps its base URL
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
            from . import __version__
            if config.data.get("linksRegistered") != __version__ and links.register_scheme():
                config.data["linksRegistered"] = __version__
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
        webview.start(debug=debug, private_mode=False, storage_path=str(storage))
    finally:
        lock.release()
    return 0
