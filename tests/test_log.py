"""The troubleshooting log (Seth, 2026-10-18: verbose on a terminal from a pip install, so a
transcript can be copied and sent): every Api call is logged, secrets never are, and the level
follows the flags."""
import logging

import pytest

from flex_scratchpad import log as L
from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def grab():
    h = _Grab()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    L.LOG.addHandler(h)
    L.LOG.setLevel(logging.DEBUG)
    yield h
    L.LOG.removeHandler(h)


def test_every_api_call_is_logged_with_its_arguments_and_time(tmp_path, grab):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "Logged", "hello")
    api.get_note(n["id"])
    lines = "\n".join(grab.lines)
    assert "api.create_note(" in lines and "'Logged'" in lines and "ms)" in lines
    assert "api.get_note(" in lines and n["id"] in lines
    assert "wrote " in lines                      # the notebook says what it wrote


def test_secrets_never_reach_the_log(tmp_path, grab):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    api._secrets = {}
    try:
        api.backup_save({"kind": "folder", "dest": str(tmp_path / "bk")}, {"secretKey": "HUNTER2-VALUE", "password": "PW-VALUE"})
    except Exception:  # noqa: BLE001 — the save may refuse the settings; only the log matters here
        pass
    api.attach_data("x.txt", "QkFTRTY0LVBBWUxPQUQ=")
    lines = "\n".join(grab.lines)
    assert "HUNTER2-VALUE" not in lines and "PW-VALUE" not in lines
    assert "QkFTRTY0" not in lines
    assert "<redacted>" in lines


def test_an_expected_error_is_a_warning_and_an_unexpected_one_has_a_traceback(tmp_path, grab):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    with pytest.raises(KeyError):
        api.get_note("no-such-note")
    assert any(ln.startswith("WARNING api.get_note(") for ln in grab.lines)
    def boom(self):
        return 1 / 0                                 # a bug, not a user error
    Api.boom = L.logged(boom)
    try:
        with pytest.raises(ZeroDivisionError):
            api.boom()
    finally:
        del Api.boom
    assert any(ln.startswith("ERROR api.boom(") and "Traceback" in ln for ln in grab.lines)


def test_redaction_and_shortening():
    assert L.redact({"a": 1, "secrets": {"k": "v"}, "data_base64": "zzz", "nested": {"password": "p", "ok": 2}}) == \
        {"a": 1, "secrets": "<redacted>", "data_base64": "<redacted>", "nested": {"password": "<redacted>", "ok": 2}}
    assert L.short("x" * 200).endswith("…(+40)'")
    assert L.short(list(range(20))).startswith("<list 20:")
    assert L.call_line("api.f", ("a", "KEY"), {"password": "p"}, ["name", "api_key"]) == "api.f(name='a', api_key=<redacted>, password=<redacted>)"


def test_the_level_follows_the_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "_setup_done", False)
    monkeypatch.setenv("FLEX_SCRATCHPAD_LOGFILE", str(tmp_path / "x.log"))
    for h in list(L.LOG.handlers):
        L.LOG.removeHandler(h)
    L.setup(verbose=True)
    console = [h for h in L.LOG.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    files = [h for h in L.LOG.handlers if isinstance(h, logging.FileHandler)]
    assert console and console[0].level == logging.DEBUG
    assert files and files[0].baseFilename == str(tmp_path / "x.log")
    L.LOG.info("hello file")
    files[0].flush()
    assert "hello file" in (tmp_path / "x.log").read_text(encoding="utf-8")
    for h in list(L.LOG.handlers):
        L.LOG.removeHandler(h)
    monkeypatch.setattr(L, "_setup_done", False)
    monkeypatch.setenv("FLEX_SCRATCHPAD_LOGFILE", "")
    L.setup(quiet=True)
    console = [h for h in L.LOG.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    assert console[0].level == logging.WARNING and not [h for h in L.LOG.handlers if isinstance(h, logging.FileHandler)]
    for h in list(L.LOG.handlers):
        L.LOG.removeHandler(h)
    monkeypatch.setattr(L, "_setup_done", False)
