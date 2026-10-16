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
    starts = re.findall(r"webview\.start\((.*?)\)\s*$", SRC, re.M | re.S)   # the call may span lines
    assert starts and all("http_server=False" in s for s in starts), starts
    assert "http_server=True" not in SRC


def test_the_app_icon_is_packaged_and_used():
    """Seth, 2026-10-16: "a cooler app icon … (not just an F on a rounded blue square)"."""
    assert app.ICON.exists() and app.ICON.name == "flex-scratchpad.ico"
    data = app.ICON.read_bytes()                                    # ICONDIR, then 16-byte entries
    assert data[:4] == b"\x00\x00\x01\x00"
    count = int.from_bytes(data[4:6], "little")
    sizes = {data[6 + 16 * k] or 256 for k in range(count)}         # width 0 means 256
    assert {16, 24, 32, 48, 256} <= sizes, sizes
    assert "icon=str(ICON)" in SRC                                  # the window and taskbar
    ui = Path(app.UI_DIR)
    html = (ui / "index.html").read_text(encoding="utf-8")
    assert 'src="img/icon-small.svg"' in html and (ui / "img" / "icon-small.svg").exists() and (ui / "img" / "icon.svg").exists()
    spec = (Path(app.__file__).resolve().parent.parent / "build" / "flex-scratchpad.spec").read_text(encoding="utf-8")
    assert "flex-scratchpad.ico" in spec                            # the built exe


def test_the_window_starts_maximized():
    """Seth, 2026-10-16: the default window started hanging off the edge of his screen."""
    calls = re.findall(r"create_window\((.*?)\n    \)", SRC, re.S)
    assert "maximized=True" in calls[0]


def test_the_restore_size_fits_the_screen(monkeypatch):
    import sys
    import types
    fake = types.SimpleNamespace(screens=[types.SimpleNamespace(width=1366, height=768)])
    monkeypatch.setitem(sys.modules, "webview", fake)
    assert app._fit_to_screen(1920, 1200) == (1229, 691)
    assert app._fit_to_screen(1000, 600) == (1000, 600)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(screens=[]))
    assert app._fit_to_screen(1280, 820) == (1280, 820)          # no screen information
