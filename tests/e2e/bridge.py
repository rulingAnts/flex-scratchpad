"""Playwright harness with NO server: the page is opened as file:// and `window.pywebview.api`
is a Proxy whose calls go through one exposed binding straight into the real Python `Api`
(exactly the contract pywebview provides). Errors reject in pywebview's {message, name} shape."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig

UI = Path(__file__).resolve().parents[2] / "flex_scratchpad" / "ui" / "index.html"

INIT_SCRIPT = """
(() => {
  const call = (method, args) => window.__flexBridge(JSON.stringify({ method, args }))
    .then((r) => { const o = JSON.parse(r); if (o.error) { const e = new Error(o.error.message); e.name = o.error.name; throw e; } return o.result; });
  const api = new Proxy({}, { get: (_, m) => (typeof m === 'string' && m !== 'then') ? (...args) => call(m, args) : undefined });
  window.pywebview = { api };
  document.addEventListener('DOMContentLoaded', () => window.dispatchEvent(new Event('pywebviewready')));
})();
"""


class Harness:
    def __init__(self, demo: bool = True, notebook: str | None = None):
        self.tmp = Path(tempfile.mkdtemp(prefix="fs-e2e-"))
        self.config = AppConfig(self.tmp / "config.json")
        self.api = Api(self.config, notebook_dir=notebook or (self.tmp / "notebook"), demo=demo)
        self.calls: list[tuple[str, list]] = []

    def bridge(self, source, payload: str) -> str:
        req = json.loads(payload)
        method, args = req["method"], req.get("args") or []
        self.calls.append((method, args))
        fn = getattr(self.api, method, None)
        if fn is None or method.startswith("_"):
            return json.dumps({"error": {"name": "ApiError", "message": "No API method " + method}})
        try:
            return json.dumps({"result": fn(*args)}, ensure_ascii=False, default=str)
        except Exception as e:  # noqa: BLE001 — mirrors pywebview's rejected promise
            return json.dumps({"error": {"name": type(e).__name__, "message": str(e)}})

    def open(self, context, query: str = ""):
        context.expose_binding("__flexBridge", self.bridge)
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()
        page.on("pageerror", lambda e: self.calls.append(("pageerror", [str(e)])))
        page.goto(UI.as_uri() + query)
        page.wait_for_selector("#tabs .tab-item")
        return page
