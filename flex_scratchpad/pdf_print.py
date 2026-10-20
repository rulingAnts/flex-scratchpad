"""Save a page as a PDF without a print dialog, through WebView2 (Windows only).

The HTML export is written to a temporary file in the notebook's private folder, opened in a
HIDDEN pywebview window (a `file://` URL, as everything here — never a server), and when it
has loaded, WebView2's own `CoreWebView2.PrintToPdfAsync` writes the PDF: the same rendering
Chromium's "Save as PDF" would give, with the export's print stylesheet (landscape for charts,
the headers repeated, no players). pywebview exposes none of this, so the WebView2 control is
reached through the window's `native` form (`BrowserForm.browser.web_view.CoreWebView2` in
pywebview 5's EdgeChromium backend); every step is guarded and `print_to_pdf` answers False
when any of it is missing, and the page falls back to the browser's print dialog. Not yet run
on a real Windows machine (2026-10-18): the first failure to look at is the log line
"direct PDF: …".
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

from .log import LOG


def available(window) -> bool:
    """Can this window print to PDF directly? Windows, and a WebView2 control we can reach."""
    if sys.platform != "win32" or window is None:
        return False
    try:
        return _core_of(window) is not None
    except Exception:  # noqa: BLE001
        return False


def _core_of(window):
    form = getattr(window, "native", None)
    browser = getattr(form, "browser", None)
    wv = getattr(browser, "web_view", None) or getattr(browser, "webview", None)
    return getattr(wv, "CoreWebView2", None)


def print_to_pdf(html: str, pdf_path: str | Path, tmp_dir: str | Path, landscape: bool = False, timeout: float = 45.0) -> bool:
    """Render `html` and write it to `pdf_path`. True when the file was written."""
    if sys.platform != "win32":
        return False
    try:
        import webview
    except ImportError:
        return False
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_html = tmp_dir / f"print-{uuid.uuid4().hex}.html"
    tmp_html.write_text(html, encoding="utf-8", newline="\n")
    done = threading.Event()
    result = {"ok": False, "error": ""}
    win = None

    def finish(ok: bool, error: str = ""):
        result["ok"] = bool(ok)
        result["error"] = error
        done.set()

    def on_loaded():
        try:
            core = _core_of(win)
            if core is None:
                finish(False, "no CoreWebView2 on the hidden window")
                return

            def start_print():
                try:
                    settings = core.Environment.CreatePrintSettings()
                    try:
                        from Microsoft.Web.WebView2.Core import CoreWebView2PrintOrientation
                        settings.Orientation = CoreWebView2PrintOrientation.Landscape if landscape else CoreWebView2PrintOrientation.Portrait
                    except Exception:  # noqa: BLE001 — an older WebView2 without the enum: portrait
                        pass
                    try:
                        settings.ShouldPrintBackgrounds = True
                        settings.MarginTop = settings.MarginBottom = 0.5
                        settings.MarginLeft = settings.MarginRight = 0.5
                    except Exception:  # noqa: BLE001
                        pass
                    task = core.PrintToPdfAsync(str(pdf_path), settings)
                    from System import Action
                    from System.Threading.Tasks import Task

                    def cont(t):
                        try:
                            if t.IsFaulted:
                                finish(False, str(t.Exception))
                            else:
                                finish(bool(t.Result))
                        except Exception as e:  # noqa: BLE001
                            finish(False, str(e))
                    task.ContinueWith(Action[Task[bool]](cont))
                except Exception as e:  # noqa: BLE001
                    finish(False, f"{type(e).__name__}: {e}")

            form = getattr(win, "native", None)
            invoke = getattr(form, "BeginInvoke", None)
            if invoke is not None:
                from System import Action
                invoke(Action(start_print))       # WebView2 wants its own UI thread
            else:
                start_print()
        except Exception as e:  # noqa: BLE001
            finish(False, f"{type(e).__name__}: {e}")

    try:
        win = webview.create_window("Export to PDF", url=tmp_html.resolve().as_uri(), hidden=True, width=1200, height=900)
        win.events.loaded += on_loaded
        if not done.wait(timeout):
            result["error"] = f"timed out after {timeout:.0f} s"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if win is not None:
                win.destroy()
        except Exception:  # noqa: BLE001
            pass
        try:
            tmp_html.unlink()
        except OSError:
            pass
    if result["ok"]:
        LOG.info("direct PDF written: %s", pdf_path)
    else:
        LOG.warning("direct PDF: %s — the page falls back to the print dialog", result["error"] or "failed")
    return result["ok"]
