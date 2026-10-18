"""The direct PDF path (pdf_print.py) is Windows + WebView2 only: elsewhere it says so at once
and the page falls back to the print dialog, with no save dialog shown."""
import sys

from flex_scratchpad import pdf_print


def test_not_available_off_windows():
    assert pdf_print.available(object()) is (sys.platform == "win32" and False)
    assert pdf_print.print_to_pdf("<p>x</p>", "/nonexistent/x.pdf", "/tmp") is False or sys.platform == "win32"


def test_api_answers_fallback_without_a_window(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(path=tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "P", "hello")
    assert api.export_note_pdf(n["id"], "<p>hello</p>") == {"fallback": True}
