"""The page is loaded as a file:// URL, never through an HTTP server (Seth: "NO HTTP SERVER. EVER.").

pywebview starts its built-in server for any url that is not http(s):// or file:// — a plain
path included — so the window must be given a file:// URL and start() must say http_server=False.
This is checked on the source as well, because pywebview is not installed where the tests run."""
import re
from pathlib import Path

from flex_scratchpad import app

SRC = Path(app.__file__).read_text(encoding="utf-8")


def test_the_page_is_a_file_url():
    u = app.ui_url()
    assert u.startswith("file:///") and u.endswith("/ui/index.html")
    assert Path(app.UI_DIR / "index.html").exists()


def test_the_window_gets_that_url_and_no_server_is_started():
    calls = re.findall(r"create_window\((.*?)\n    \)", SRC, re.S)
    assert len(calls) == 1 and "url=ui_url()" in calls[0], calls
    starts = re.findall(r"webview\.start\((.*)\)\s*$", SRC, re.M)
    assert starts and all("http_server=False" in s for s in starts), starts
    assert "http_server=True" not in SRC
