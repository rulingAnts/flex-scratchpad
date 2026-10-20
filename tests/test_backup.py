"""The notebook backup (Seth, 2026-10-17): to a cloud sync folder, or to S3-compatible storage
through rclone, as a mirror that keeps every replaced or removed file in a dated version; the
keys only ever in the secret store and rclone's environment."""
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from flex_scratchpad.api import Api
from flex_scratchpad.backup import Backup, BackupError, cloud_folders, suggested_folder
from flex_scratchpad.config import AppConfig
from flex_scratchpad.secrets_store import FileStore, MemoryStore


def make(tmp_path):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    api._secrets = MemoryStore()
    api._backup_obj = None
    b = api._backup
    b.lock_dir = tmp_path / "local"
    return api, b


def note_files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_a_folder_backup_mirrors_and_keeps_what_it_replaces_or_removes(tmp_path):
    api, b = make(tmp_path)
    dest = tmp_path / "OneDrive" / "FLEx Scratchpad backup" / "nb"
    n = api.create_note("Notes", "", "Aspect", "first")
    st = api.backup_save({"kind": "folder", "folder": str(dest)})
    assert st["ready"] and st["secrets"] == {"access_key_id": False, "secret_access_key": False, "crypt_password": False}
    assert api.backup_test()["ok"]
    r = api.backup_now()
    assert r["ok"], r
    assert note_files(api._nb.root) == note_files(dest / "current")
    assert b.needed() is False             # on close: nothing changed since, nothing to do
    # change one note, delete another: both old copies are kept in a dated version
    time.sleep(1.1)
    api.save_note(n["id"], {"body": "second"})
    other = api.create_note("Notes", "", "Gone soon", "x")
    assert b.needed() is True
    api.backup_now()
    api.delete_note(other["id"])
    time.sleep(1.1)
    r = api.backup_now()
    assert r["ok"]
    assert note_files(api._nb.root) == note_files(dest / "current")
    versions = api.backup_versions()
    assert len(versions) >= 2
    kept = b"".join(v for f in versions for v in note_files(dest / "versions" / f).values())
    assert b"first" in kept
    # how much it all takes, and pruning: by name, and by age (the current copy is never touched)
    u = b.usage()
    assert u["current"]["files"] == len(note_files(api._nb.root)) and len(u["versions"]) == len(versions)
    assert u["total"] == u["current"]["bytes"] + sum(v["bytes"] for v in u["versions"])
    old = dest / "versions" / "2020-01-01_000000"
    old.mkdir()
    (old / "x.md").write_text("old")
    api.backup_save({"keepDays": 30})
    time.sleep(1.1)
    api.save_note(n["id"], {"body": "third"})
    r = api.backup_now()
    assert r["ok"] and "older than 30 days removed" in r["message"] and not old.exists()
    gone = b.prune(names=[versions[-1]])
    assert gone["versions"] == [versions[-1]] and gone["bytes"] > 0 and not (dest / "versions" / versions[-1]).exists()
    assert (dest / "current").is_dir()
    # restore: into a new folder, never over the notebook
    out = b.restore(tmp_path / "restored")
    assert note_files(out) == note_files(api._nb.root)
    with pytest.raises(BackupError):
        b.restore(out)                       # not empty


def test_the_backup_folder_may_not_be_inside_the_notebook_or_hold_it(tmp_path):
    api, b = make(tmp_path)
    with pytest.raises(BackupError):
        api.backup_save({"kind": "folder", "folder": str(tmp_path / "nb" / "backup")})
    with pytest.raises(BackupError):
        api.backup_save({"kind": "folder", "folder": str(tmp_path)})


def test_cloud_sync_folders_are_guessed_from_each_programs_own_settings(tmp_path):
    home = tmp_path / "home"
    for d in ("OneDrive - Payap University", "Dropbox (Old)", "My Drive", "iCloudDrive"):
        (home / d).mkdir(parents=True)
    od = tmp_path / "od-personal"
    od.mkdir()
    appdata = tmp_path / "appdata"
    (appdata / "Dropbox").mkdir(parents=True)
    dbx = tmp_path / "Dropbox (Team)"
    dbx.mkdir()
    (appdata / "Dropbox" / "info.json").write_text(json.dumps({"business": {"path": str(dbx)}}), encoding="utf-8")
    gdrive = tmp_path / "G"
    (gdrive / "My Drive").mkdir(parents=True)
    found = cloud_folders(home=home, env={"OneDriveConsumer": str(od), "APPDATA": str(appdata)}, drives=[str(gdrive)])
    labels = [(f["service"], f["label"]) for f in found]
    assert labels[0] == ("onedrive", "OneDrive")
    assert ("onedrive", "OneDrive (Payap University)") in labels
    assert ("dropbox", "Dropbox (business)") in labels
    assert any(s == "gdrive" for s, _ in labels) and ("icloud", "iCloud Drive") in labels
    assert len({f["path"] for f in found}) == len(found)
    assert suggested_folder(str(od), tmp_path / "My notes").endswith(os.path.join("FLEx Scratchpad backup", "My notes"))


FAKE_RCLONE = r'''#!{python}
import json, os, sys
log = os.environ.get("FAKE_RCLONE_LOG")
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "env": {{k: v for k, v in os.environ.items() if k.startswith("RCLONE_")}}, "stdin": sys.stdin.read() if sys.argv[1:2] == ["obscure"] else ""}}) + "\n")
if sys.argv[1:2] == ["obscure"]:
    print("OBSCURED")
elif sys.argv[1:2] == ["lsjson"] and "--dirs-only" in sys.argv:
    print(json.dumps([{{"Path": "2026-10-17_101500", "IsDir": True}}, {{"Path": "2026-10-16_090000", "IsDir": True}}, {{"Path": "junk", "IsDir": True}}]))
elif sys.argv[1:2] == ["lsjson"]:
    print(json.dumps([{{"Path": "2026-10-17_101500/a.md", "Size": 10}}, {{"Path": "2026-10-17_101500/b/c.md", "Size": 5}}, {{"Path": "2026-10-16_090000/a.md", "Size": 7}}]))
elif sys.argv[1:2] == ["size"]:
    print(json.dumps({{"count": 4, "bytes": 1234}}))
elif sys.argv[1:2] == ["purge"]:
    pass
elif os.environ.get("FAKE_RCLONE_FAIL"):
    print("2026/10/17 ERROR : SignatureDoesNotMatch: the request signature", file=sys.stderr); sys.exit(1)
elif "--use-json-log" in sys.argv:
    for b, t in ((0, 0), (400, 0), (1000, 2)):
        print(json.dumps({{"level": "info", "msg": "stats", "stats": {{"bytes": b * 3, "totalBytes": 3000, "transfers": t, "totalTransfers": 3, "checks": 0, "totalChecks": 0, "eta": 7 if t < 2 else 0}}}}))
    print(json.dumps({{"level": "info", "msg": "stats", "stats": {{"bytes": 3000, "totalBytes": 3000, "transfers": 3, "totalTransfers": 3, "eta": 0}}}}))
else:
    print("Transferred:   3 / 3, 100%")
'''


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in rclone is a script with a #! line")
def test_s3_through_rclone_keeps_the_keys_off_the_command_line_and_out_of_any_file(tmp_path, monkeypatch):
    api, b = make(tmp_path)
    fake = tmp_path / "rclone"
    fake.write_text(FAKE_RCLONE.format(python=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "rclone.log"
    monkeypatch.setenv("FAKE_RCLONE_LOG", str(log))
    monkeypatch.setenv("RCLONE_CONFIG_EVIL_TYPE", "local")          # a user's own rclone setup is not inherited
    st = api.backup_save({"kind": "s3", "provider": "r2", "endpoint": "https://acct.r2.cloudflarestorage.com", "region": "auto",
                          "bucket": "/field-notes/", "prefix": "seth", "rclone": str(fake), "encrypt": True},
                         {"access_key_id": "AKIA-ID-123", "secret_access_key": "SECRET-456", "crypt_password": "horse battery"})
    assert st["ready"] and all(st["secrets"].values())
    assert "SECRET-456" not in json.dumps(st)                    # secrets never come back to the page
    assert "SECRET-456" not in (tmp_path / "config.json").read_text(encoding="utf-8")
    assert api.backup_test()["ok"]
    seen = []
    b.report = seen.append
    r = api.backup_now()
    assert r["ok"], r
    assert "3 files (2.9 KB) copied to field-notes/seth" in r["message"], r["message"]
    copying = [x for x in seen if x["phase"] == "copying"]
    assert copying and copying[-1]["percent"] == 100.0 and any(x["eta"] == 7 for x in copying), copying
    assert [x["phase"] for x in seen][0] == "scanning" and seen[-1]["phase"] == "done"
    calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    sync = next(c for c in calls if c["argv"][0] == "sync")
    obscure = next(c for c in calls if c["argv"][0] == "obscure")
    assert obscure["argv"][:2] == ["obscure", "-"] and obscure["stdin"] == "horse battery"
    for c in calls:
        assert not any(s in " ".join(c["argv"]) for s in ("AKIA-ID-123", "SECRET-456", "horse battery"))
        assert "RCLONE_CONFIG_EVIL_TYPE" not in c["env"]
        assert Path(c["env"]["RCLONE_CONFIG"]).read_text() == ""          # an empty config of our own
    env = sync["env"]
    assert env["RCLONE_CONFIG_FSBACKUP_TYPE"] == "s3" and env["RCLONE_CONFIG_FSBACKUP_PROVIDER"] == "Cloudflare"
    assert env["RCLONE_CONFIG_FSBACKUP_ACCESS_KEY_ID"] == "AKIA-ID-123" and env["RCLONE_CONFIG_FSBACKUP_SECRET_ACCESS_KEY"] == "SECRET-456"
    assert env["RCLONE_CONFIG_FSBACKUPC_REMOTE"] == "fsbackup:field-notes/seth" and env["RCLONE_CONFIG_FSBACKUPC_PASSWORD"] == "OBSCURED"
    assert sync["argv"][1] == str(api._nb.root) and sync["argv"][2] == "fsbackupc:current"
    i = sync["argv"].index("--backup-dir")
    assert sync["argv"][i + 1].startswith("fsbackupc:versions/20")
    assert api.backup_versions() == ["2026-10-17_101500", "2026-10-16_090000"]
    u = b.usage()
    assert u["current"] == {"files": 4, "bytes": 1234}
    assert u["versions"] == [{"name": "2026-10-17_101500", "files": 2, "bytes": 15}, {"name": "2026-10-16_090000", "files": 1, "bytes": 7}]
    assert u["total"] == 1234 + 22
    assert b.prune(names=["2026-10-16_090000", "not-a-version"])["versions"] == ["2026-10-16_090000"]
    purge = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if '"purge"' in x][-1]
    assert purge["argv"][1] == "fsbackupc:versions/2026-10-16_090000"
    # a refusal reads as one
    monkeypatch.setenv("FAKE_RCLONE_FAIL", "1")
    r = api.backup_now()
    assert not r["ok"] and "refused the keys" in r["message"]
    assert api.backup_status()["last"]["ok"] is False
    # forgetting a key makes the backup not ready again
    st = api.backup_save({}, None, ["secret_access_key"])
    assert not st["ready"] and "the secret access key" in st["missing"]


def test_the_off_windows_secret_file_is_readable_by_the_user_only(tmp_path):
    s = FileStore(tmp_path / "secrets.json")
    s.set("backup/x", "v")
    assert s.get("backup/x") == "v" and s.has("backup/x")
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "secrets.json").stat().st_mode) == 0o600
    s.delete("backup/x")
    assert s.get("backup/x") is None


def test_one_backup_at_a_time(tmp_path):
    api, b = make(tmp_path)
    api.backup_save({"kind": "folder", "folder": str(tmp_path / "dest")})
    b.lock_dir.mkdir(parents=True, exist_ok=True)
    (b.lock_dir / "backup.lock").write_text("1")
    assert api.backup_now()["busy"]


def test_storage_by_kind_and_the_cleanup_options(tmp_path):
    api, b = make(tmp_path)
    import base64
    used = api.attach_data("used.pdf", base64.b64encode(b"u" * 100).decode())
    api.attach_data("orphan.wav", base64.b64encode(b"o" * 1000).decode())
    api.create_note("Notes", "", "Uses one", "See {{file attachments/used.pdf}}.")
    gone = api.create_note("Notes", "", "Trashed", "{{file attachments/kept%20by%20trash.txt}} x")
    api.attach_data("kept by trash.txt", base64.b64encode(b"k").decode())
    api.delete_note(gone["id"])
    clips = api._nb.cache_dir / "Kalu Demo" / "audio"
    clips.mkdir(parents=True, exist_ok=True)
    (clips / "a_0-100.wav").write_bytes(b"c" * 50)
    u = api.storage_usage()
    parts = {x["id"]: x for x in u["notebook"]["parts"]}
    assert parts["attachments"]["bytes"] == 1101 and parts["clips"]["bytes"] == 50 and parts["trash"]["files"] == 1
    assert u["notebook"]["total"] == sum(x["bytes"] for x in parts.values())
    # a file only a trashed note uses still counts as used: the note may come back
    assert [f["name"] for f in u["unused"]["list"]] == ["orphan.wav"] and u["unused"]["bytes"] == 1000
    r = api.storage_trash_unused()
    assert r == {"files": 1, "bytes": 1000}
    assert not (api._nb.root / "attachments" / "orphan.wav").exists()
    assert any(p.name.endswith("--orphan.wav") for p in (api._nb.trash_dir / "attachments").iterdir())
    assert api.storage_clear_clips() == {"files": 1, "bytes": 50} and not clips.exists()
    r = api.storage_empty_trash()
    assert r["files"] == 2 and not api._nb.trash_dir.exists()
    assert (api._nb.root / used["ref"]).exists()


def test_a_folder_backup_reports_its_progress_and_says_what_it_did(tmp_path):
    api, b = make(tmp_path)
    big = tmp_path / "nb" / "attachments"
    big.mkdir(parents=True)
    (big / "rec1.wav").write_bytes(b"a" * (3 << 20))
    (big / "rec2.wav").write_bytes(b"b" * (2 << 20))
    api.backup_save({"kind": "folder", "folder": str(tmp_path / "OneDrive" / "bk")})
    seen = []
    b.report = seen.append
    r = api.backup_now()
    assert r["ok"] and "copied to" in r["message"] and "MB" in r["message"], r["message"]
    phases = [x["phase"] for x in seen]
    assert phases[0] == "scanning" and phases[-1] == "done" and "finishing" in phases
    pcts = [x["percent"] for x in seen if x["phase"] == "copying" and x["percent"] is not None]
    assert pcts == sorted(pcts) and pcts[-1] == 100.0 and len(pcts) >= 2
    total = next(x["total"] for x in seen if x["phase"] == "copying")
    assert total >= 5 << 20
    # nothing changed: it says so, plainly
    r = api.backup_now()
    assert r["ok"] and r["message"].startswith("nothing had changed"), r["message"]


def test_cancel_stops_between_pieces_and_never_leaves_half_a_file(tmp_path):
    api, b = make(tmp_path)
    big = tmp_path / "nb" / "attachments"
    big.mkdir(parents=True)
    (big / "rec1.wav").write_bytes(b"a" * (4 << 20))
    (big / "rec2.wav").write_bytes(b"b" * (4 << 20))
    dest = tmp_path / "bk"
    api.backup_save({"kind": "folder", "folder": str(dest)})

    def report(st):
        if st["phase"] == "copying":
            api.backup_cancel()
    b.report = report
    r = api.backup_now()
    assert r.get("cancelled") and not r["ok"], r
    # in the middle of a file: the piece being written is dropped, the older copy stays where it was
    from flex_scratchpad.backup import BackupCancelled, _mirror_folder
    stop = {"now": False}

    def tick(phase, done=0, total=0, files=0, files_total=0, name="", force=False, eta=None):
        if done > (1 << 20):
            stop["now"] = True
    with pytest.raises(BackupCancelled):
        _mirror_folder(api._nb.root, tmp_path / "bk-mid", "2026-10-17_000000", tick=tick, cancelled=lambda: stop["now"])
    assert not list((tmp_path / "bk-mid").rglob("*.part"))
    assert not list((tmp_path / "bk-mid" / "current" / "attachments").glob("rec*.wav"))   # whichever came first
    assert not list(dest.rglob("*.part"))
    assert not (b.lock_dir / "backup.lock").exists() and not b.running
    assert api.backup_cancel() is False                # nothing running any more
    b.report = lambda st: None
    r = api.backup_now()                               # and the next one finishes the job
    assert r["ok"] and (dest / "current" / "attachments" / "rec2.wav").stat().st_size == 4 << 20


def test_closing_backs_up_first_and_honours_each_choice(tmp_path):
    import threading
    from flex_scratchpad.app import backup_then_close
    api, b = make(tmp_path)
    events = []
    api._emit = lambda ev, d: events.append((ev, d))
    api.backup_save({"kind": "folder", "folder": str(tmp_path / "bk")})
    closed, started = [], []
    # 1. a backup is due: it runs, then the window closes
    assert b.needed()
    assert backup_then_close(api, lambda: closed.append(1), started.append) == "ok"
    assert closed == [1] and not started and not b.needed()
    assert ("backupClosing", {"state": "running"}) in events
    # 2. "Close now, finish in the background": the run stops, a quiet process takes over
    (tmp_path / "nb" / "attachments").mkdir(exist_ok=True)
    (tmp_path / "nb" / "attachments" / "big.wav").write_bytes(b"x" * (4 << 20))
    b.report = lambda st: st["phase"] == "copying" and st["done"] and api.backup_close_choice("background")
    assert backup_then_close(api, lambda: closed.append(2), started.append) == "background"
    assert started == [str(api._nb.root)] and closed[-1] == 2
    # 3. a failure waits for the answer: "Close anyway"
    b.report = lambda st: None
    api.backup_save({"kind": "folder", "folder": str(tmp_path / "bk2")})
    b.run = lambda reason="manual": {"ok": False, "message": "offline"}
    t = threading.Timer(0.3, lambda: api.backup_close_choice("close"))
    t.start()
    assert backup_then_close(api, lambda: closed.append(3), started.append) == "failed"
    assert ("backupClosing", {"state": "failed", "message": "offline"}) in events and closed[-1] == 3
    # 4. a run that does not answer the cancel (Seth, 2026-10-18: the button "appears to do
    #    nothing"): the choice still closes the window after a short grace, the process started
    import time
    from flex_scratchpad import app as app_mod
    app_mod.CLOSE_GRACE = 0.5
    b.run = lambda reason="manual": (time.sleep(5), {"ok": True})[1]
    threading.Timer(0.3, lambda: api.backup_close_choice("background")).start()
    t0 = time.monotonic()
    assert backup_then_close(api, lambda: closed.append(4), started.append) == "background"
    assert time.monotonic() - t0 < 3 and closed[-1] == 4 and started[-1] == str(api._nb.root)


def test_a_lock_left_by_a_dead_process_does_not_block_the_next_backup(tmp_path):
    """The window closed with "finish in the background" can end before its backup thread let go
    of the lock; the quiet process must not wait six hours for that (Seth, 2026-10-18)."""
    api, b = make(tmp_path)
    api.backup_save({"kind": "folder", "folder": str(tmp_path / "bk")})
    lock = b.lock_dir / "backup.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999999", encoding="utf-8")        # no such process
    assert api.backup_now()["ok"]
    # a lock whose holder is alive (this process) still blocks
    lock.write_text(str(__import__("os").getpid()), encoding="utf-8")
    assert api.backup_now().get("busy")
    lock.unlink()


def test_atomic_writes_ride_out_a_busy_target_and_many_threads(tmp_path, monkeypatch):
    """Windows cannot replace a file another handle has open: `replace_file` retries, and the
    config saves from many threads at once without tripping over each other (Seth, 2026-10-19:
    "Access is denied … config.json.tmp -> config.json" on the backup-before-closing screen)."""
    import os
    import threading
    from flex_scratchpad import fsutil
    from flex_scratchpad.config import AppConfig
    calls = {"n": 0}
    real = os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real(a, b)
    monkeypatch.setattr(fsutil.os, "replace", flaky)
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("x", encoding="utf-8")
    fsutil.replace_file(src, dst)
    assert dst.read_text(encoding="utf-8") == "x" and calls["n"] == 3
    # out of patience: the error comes through and the temp file is gone
    calls["n"] = -100
    src.write_text("y", encoding="utf-8")
    import pytest
    with pytest.raises(PermissionError):
        fsutil.replace_file(src, dst, tries=3)
    assert not src.exists()
    monkeypatch.setattr(fsutil.os, "replace", real)
    cfg = AppConfig(tmp_path / "config.json")
    errors = []

    def one(i):
        try:
            cfg.data["k%d" % i] = i
            cfg.save()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=one, args=(i,)) for i in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors and not list(tmp_path.glob("*.tmp"))
