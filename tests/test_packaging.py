"""The Windows packaging, as far as it can be checked off Windows (the Windows runner runs the
built program's --selftest and a real install / upgrade / uninstall: windows-package.yml)."""
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import fetch_ffmpeg  # noqa: E402


def test_ffmpeg_is_the_newest_lgpl_release_branch_else_master():
    names = ["ffmpeg-master-latest-win64-gpl.zip", "ffmpeg-n7.1-latest-win64-lgpl-7.1.zip", "ffmpeg-n8.0-latest-win64-lgpl-8.0.zip",
             "ffmpeg-n8.0-latest-win64-gpl-8.0.zip", "ffmpeg-n8.0-latest-win64-lgpl-shared-8.0.zip", "ffmpeg-n8.0-latest-linux64-lgpl-8.0.tar.xz",
             "ffmpeg-master-latest-win64-lgpl.zip", "checksums.sha256"]
    assert fetch_ffmpeg.pick([{"name": n} for n in names])["name"] == "ffmpeg-n8.0-latest-win64-lgpl-8.0.zip"
    assert fetch_ffmpeg.pick([{"name": n} for n in names if "-n" not in n])["name"] == "ffmpeg-master-latest-win64-lgpl.zip"
    with pytest.raises(SystemExit):
        fetch_ffmpeg.pick([{"name": "ffmpeg-n8.0-latest-win64-gpl-8.0.zip"}])          # never a GPL build


class _Resp:
    def __init__(self, data, status=200, total=None, headers=None):
        self._b = io.BytesIO(data)
        self.status = status
        self.headers = headers or {}
        if total is not None:
            self.headers["Content-Range" if status == 206 else "Content-Length"] = (f"bytes 0-0/{total}" if status == 206 else str(total))

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_dropped_download_resumes_where_it_stopped(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 400
    calls = []

    def urlopen(req, timeout=0):
        rng = req.get_header("Range")
        calls.append(rng)
        if rng is None:
            return _Resp(payload[:30000], 200, total=len(payload))        # the connection drops at 30 kB
        start = int(re.match(r"bytes=(\d+)-", rng).group(1))
        return _Resp(payload[start:], 206, total=len(payload))
    monkeypatch.setattr(fetch_ffmpeg.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fetch_ffmpeg.time, "sleep", lambda s: None)
    out = fetch_ffmpeg.download("https://example.invalid/f.zip", tmp_path / "f.zip")
    assert out.read_bytes() == payload
    assert calls == [None, "bytes=30000-"]
    assert not (tmp_path / "f.zip.part").exists()


def test_a_missing_file_is_not_retried(monkeypatch, tmp_path):
    n = []

    def urlopen(req, timeout=0):
        n.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(fetch_ffmpeg.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        fetch_ffmpeg.download("https://example.invalid/gone.zip", tmp_path / "gone.zip")
    assert len(n) == 1


def test_the_packaged_program_prefers_its_own_ffmpeg(tmp_path, monkeypatch):
    from flex_scratchpad.flex import audio
    app = tmp_path / "FLEx Scratchpad"
    (app / "ffmpeg").mkdir(parents=True)
    exe = app / "ffmpeg" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "FLEx Scratchpad.exe"))
    assert audio.bundled_ffmpeg() == exe.resolve()
    assert audio.find_ffmpeg() == str(exe.resolve())
    assert audio.find_ffmpeg(str(tmp_path / "nowhere.exe")) == str(exe.resolve())    # a stale Settings path falls through
    monkeypatch.setattr(sys, "frozen", False)
    assert audio.bundled_ffmpeg() is None


def test_selftest_writes_its_report(tmp_path):
    from flex_scratchpad.__main__ import main
    out = tmp_path / "st.json"
    main(["--selftest", str(out)])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["checks"]["page"]["ok"] and rep["build"] and "ffmpeg" in rep["checks"]


def test_the_installer_is_per_user_and_removes_only_its_own_files():
    nsi = (ROOT / "build" / "installer.nsi").read_text(encoding="utf-8")
    assert "RequestExecutionLevel user" in nsi and '$LOCALAPPDATA\\Programs\\' in nsi
    # never the install folder wholesale: someone may have pointed it at a folder with other things
    assert not re.search(r'RMDir /r "\$INSTDIR"', nsi)
    assert 'RMDir "$INSTDIR"' in nsi                                     # only when empty
    assert "/SD IDCANCEL" in nsi                                          # a silent run never hangs on a box
    assert 'DeleteRegKey HKCU "Software\\Classes\\flexscratchpad"' in nsi


def test_flexicon_pythonnet_and_ffmpeg_are_packaged():
    spec = (ROOT / "build" / "flex-scratchpad.spec").read_text(encoding="utf-8")
    for pkg in ("webview", "pythonnet", "clr_loader", "flexicon"):
        assert f'"{pkg}"' in spec
    pkg = (ROOT / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
    assert ".[build,flex]" in pkg and "fetch_ffmpeg.py" in pkg and "--selftest" in pkg
    assert "Uninstall.exe" in pkg                                         # install / upgrade / uninstall tested


def test_workflows_stay_free_and_only_tags_publish():
    """Public repository, standard runners only, no schedule (CLAUDE.md "GitHub Actions")."""
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "schedule:" not in text, wf.name
        for runner in re.findall(r"runs-on:\s*(\S+)", text):
            assert runner in ("ubuntu-latest", "windows-latest", "macos-latest"), (wf.name, runner)
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "tags:" in rel and "--prerelease" in rel and "needs: [version, package]" in rel


def test_the_packaged_entry_point_and_page_are_right(monkeypatch):
    """The first Windows build hung: the spec ran flex_scratchpad/__main__.py as a bare script,
    whose relative imports fail there, and the windowed program showed the error in a message
    box; and collect_data_files left the page out when the package was not installed."""
    import runpy
    spec = (ROOT / "build" / "flex-scratchpad.spec").read_text(encoding="utf-8")
    assert 'os.path.join(here, "launcher.py")' in spec and "collect_data_files(" not in spec
    assert 'os.walk(os.path.join(pkg, "ui"))' in spec and "BUILD_ID" in spec
    monkeypatch.setattr(sys, "argv", ["flex-scratchpad", "--version"])
    with pytest.raises(ImportError):                       # why the launcher exists
        runpy.run_path(str(ROOT / "flex_scratchpad" / "__main__.py"), run_name="__main__")
    wf = (ROOT / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
    assert "WaitForExit(" in wf and "timeout-minutes" in wf and "FS_CONSOLE" in wf


def test_a_stamped_build_id_wins(tmp_path, monkeypatch):
    import flex_scratchpad
    stamp = Path(flex_scratchpad.__file__).resolve().parent / "BUILD_ID"
    assert not stamp.exists()                              # never in the source tree
    monkeypatch.setattr(flex_scratchpad, "_BUILD", None)
    stamp.write_text("abc1234\n", encoding="utf-8")
    try:
        assert flex_scratchpad.build_id() == "abc1234"
    finally:
        stamp.unlink()
        monkeypatch.setattr(flex_scratchpad, "_BUILD", None)


def test_a_dispatched_prerelease_publishes_only_tested_packages():
    import yaml
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    job = ci["jobs"]["prerelease"]
    assert set(job["needs"]) == {"test", "build-windows"} and "prerelease_version != ''" in job["if"]
    assert job["permissions"] == {"contents": "write"}
    run = "\n".join(st.get("run", "") for st in job["steps"])
    assert "--prerelease" in run and "--target" in run


def test_rclone_is_its_own_windows_release_checked_against_its_sums(tmp_path, monkeypatch):
    import fetch_rclone
    names = ["rclone-v1.71.1-linux-amd64.zip", "rclone-v1.71.1-windows-386.zip", "rclone-v1.71.1-windows-amd64.zip",
             "rclone-v1.71.1-windows-arm64.zip", "SHA256SUMS"]
    assert fetch_rclone.pick([{"name": n} for n in names])["name"] == "rclone-v1.71.1-windows-amd64.zip"
    with pytest.raises(SystemExit):
        fetch_rclone.pick([{"name": "rclone-v1.71.1-windows-386.zip"}])
    h = "a" * 64
    signed = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA1\n\n" + "b" * 64 + "  rclone-v1.71.1-windows-386.zip\n"
              + h + "  rclone-v1.71.1-windows-amd64.zip\n-----BEGIN PGP SIGNATURE-----\nxyz\n")
    assert fetch_rclone.expected_sum(signed, "rclone-v1.71.1-windows-amd64.zip") == h
    assert fetch_rclone.expected_sum(signed, "rclone-v9.zip") == ""
    # the packaged program prefers its own rclone, beside the exe
    from flex_scratchpad import backup
    app = tmp_path / "app"
    (app / "rclone").mkdir(parents=True)
    exe = app / "rclone" / ("rclone.exe" if sys.platform == "win32" else "rclone")
    exe.write_text("x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "FLEx Scratchpad.exe"))
    assert backup.bundled_rclone() == exe.resolve() and backup.find_rclone() == str(exe.resolve())
    wf = (ROOT / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
    nsi = (ROOT / "build" / "installer.nsi").read_text(encoding="utf-8")
    assert "fetch_rclone.py" in wf and r'"$dir\rclone\rclone.exe"' in wf
    assert nsi.count('RMDir /r "$INSTDIR\\rclone"') == 2                 # an upgrade and the uninstaller remove it
