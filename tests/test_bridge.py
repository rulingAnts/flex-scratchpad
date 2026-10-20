"""The page gets the Api the way pywebview hands it over, and never the demo in its place.

pywebview exposes `window.pywebview.api` by walking the Api's public attributes (`webview/util.py`
inject_pywebview); one attribute that raises, or one method whose signature cannot be read, leaves
the page WITHOUT an api, and until 2026-10-19 the page then quietly fell back to its in-browser
demo notebook — Seth's newest wheel started on "Kalu Demo" over his own notebook ("My data's
gone"). `bridge_check.exposed` repeats pywebview's walk so this fails before a user sees it, the
window logs the walk's outcome after load, and the page waits visibly instead of pretending."""
import logging
import re
from pathlib import Path

from flex_scratchpad import app, log as L
from flex_scratchpad.api import Api
from flex_scratchpad.bridge_check import exposed, report
from flex_scratchpad.config import AppConfig

UI = Path(app.__file__).parent / "ui"


def test_pywebviews_walk_of_the_api_meets_no_problem(tmp_path):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    names, problems = exposed(api)
    assert problems == []
    assert "init" in names and "list_notes" in names and "flex_projects" in names
    assert all("." not in n for n in names), [n for n in names if "." in n]   # nothing public is walked into
    assert report(api).startswith(f"{len(names)} functions") and "MISSING" not in report(api)


def test_the_walk_names_what_breaks():
    class Broken:
        def init(self):
            return {}

        @property
        def boom(self):
            raise RuntimeError("not now")

    names, problems = exposed(Broken())
    assert names == ["init"]
    assert problems == ["boom: reading it raised RuntimeError: not now"]


def test_the_window_checks_the_bridge_after_load_and_logs_it(tmp_path):
    class Win:
        def __init__(self, answer):
            self.answer = answer

        def evaluate_js(self, js):
            assert "pywebview.api.init" in js
            return self.answer

    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    lines = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(record.levelname + " " + record.getMessage())

    h = H(logging.DEBUG)
    L.LOG.addHandler(h)
    level = L.LOG.level
    L.LOG.setLevel(logging.DEBUG)
    try:
        assert app.check_bridge(Win("function"), api) is True
        assert app.check_bridge(Win("undefined"), api) is False
    finally:
        L.LOG.removeHandler(h)
        L.LOG.setLevel(level)
    assert any(l.startswith("INFO bridge: the page has the Api") for l in lines)
    bad = [l for l in lines if l.startswith("ERROR bridge: the page did NOT get the Api")]
    assert bad and "init is undefined" in bad[0] and "functions" in bad[0]
    src = Path(app.__file__).read_text(encoding="utf-8")
    assert re.search(r"def on_loaded\(\):\n\s+check_bridge\(window, api\)", src)


def test_pywebviews_own_log_lines_reach_our_handlers():
    lines = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    h = H(logging.DEBUG)
    L.LOG.addHandler(h)
    try:
        L.adopt_logger("pywebview")
        logging.getLogger("pywebview").error("Error occurred in script")
    finally:
        L.LOG.removeHandler(h)
        logging.getLogger("pywebview").removeHandler(h)
    assert "pywebview: Error occurred in script" in lines
    src = Path(L.__file__).read_text(encoding="utf-8")
    assert 'adopt_logger("pywebview")' in src.split("def setup(")[1].split("\nclass ")[0]   # setup() does it


def test_the_page_never_falls_back_to_the_demo_inside_the_app():
    """api.js: the mock is for a plain browser only. Inside a WebView2 / WebKit window (known from
    the host object before pywebview injects anything) the page waits and says so."""
    js = (UI / "js" / "api.js").read_text(encoding="utf-8")
    poll = js.split("const poll = () => {")[1].split("poll();")[0]
    assert "window.chrome.webview" in js and "window.webkit.messageHandlers" in js
    assert "if (!hosted() && document.readyState === 'complete' && waited > 600) return finish(FS.mockApi());" in poll
    assert "showWait(waited)" in poll and "waited > 15000" not in poll
    assert "bridge-wait" in js and "flex-scratchpad -v" in js
    assert "location.reload()" in js and "reloads < 2" in js          # the retry, bounded
