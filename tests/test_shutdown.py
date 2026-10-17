"""Closing the app (Seth, 2026-10-17: "Unhandled Exception: Python.Runtime.InternalPythonnetException:
Failed to create Python type for System.ComponentModel.InvalidAsynchronousStateException" when the
app closes): once the window is gone nothing may call into .NET, and the process ends without
Python's shutdown racing the daemon threads."""
import threading
import time

from flex_scratchpad import app, links
from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig


class Window:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, js):
        self.calls.append(js)


def test_after_the_window_closes_nothing_reaches_it(tmp_path):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    w = Window()
    api._window = w
    api._emit("progress", {"message": "x"})
    assert len(w.calls) == 1
    seen = []
    watcher = links.watch_requests(seen.append, interval=0.05, path=tmp_path / "open-request.txt")
    # an Api call still writing when the window goes: shut_down waits for it
    done = []

    def writer():
        with api._lock:
            time.sleep(0.3)
            done.append(True)
    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.05)
    app.shut_down(api, watcher)
    assert done == [True]
    api._emit("progress", {"message": "late"})
    assert len(w.calls) == 1                      # nothing pushed to a window that is gone
    watcher.join(1)
    assert not watcher.is_alive()                 # the link poller stopped
    assert api._flex.backend is None              # FLEx closed


def test_the_gui_start_ends_through_exit_now(monkeypatch):
    from flex_scratchpad import __main__ as main_mod
    ended = []
    monkeypatch.setattr(app, "run", lambda **kw: 0)
    monkeypatch.setattr(app, "exit_now", lambda code=0: ended.append(code))
    assert main_mod.main([]) == 0 and ended == [0]
