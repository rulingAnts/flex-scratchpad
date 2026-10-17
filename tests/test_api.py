"""The js_api surface, driven exactly as the page drives it (plain JSON in and out)."""
import json

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex.demo import E, T_STORY


def make(tmp_path):
    cfg = AppConfig(tmp_path / "config.json")
    return Api(cfg, notebook_dir=tmp_path / "nb", demo=True)


def test_init_is_json(tmp_path):
    api = make(tmp_path)
    init = api.init()
    json.dumps(init)
    assert init["flex"]["open"] and init["flex"]["backend"] == "demo"
    assert init["config"]["tabs"][0]["dir"] == "Notes" and init["notes"] == []


def test_note_round_trip_and_search(tmp_path):
    api = make(tmp_path)
    n = api.create_note(None, "", "Aspect", "Hello **world** #grammar\n\n{{flex:text %s seg=1-2}}" % T_STORY)
    api.save_note(n["id"], {"tags": ["todo"], "pinned": True})
    got = api.get_note(n["id"])
    assert got["tags"] == ["todo"] and got["pinned"] and got["inlineTags"] == ["grammar"]
    # the embed's snapshot text becomes searchable once the object has been rendered once
    api.flex_get("text", T_STORY, 1, 2)
    api.rescan()
    assert [h["title"] for h in api.search("kabir", {})] == ["Aspect"]
    assert [h["title"] for h in api.search("", {"tags": ["grammar"]})] == ["Aspect"]
    hit = api.search("world", {})[0]
    assert hit["snippet"] and hit["snippetMarks"]
    json.dumps(api.list_notes()); json.dumps(api.tags()); json.dumps(api.folders())


def test_flex_methods(tmp_path):
    api = make(tmp_path)
    assert [h["headword"] for h in api.flex_search_entries("tik")] == ["tiket"]
    assert api.flex_texts("dog")[0]["guid"] == T_STORY
    assert api.flex_find_in_text(T_STORY, "pemu") == [2, 4]
    r = api.flex_resolve_link(E["ka"])
    assert r["kind"] == "entry" and r["title"] == "ka-"
    clip = api.audio_clip(T_STORY, None, 0, 1500)
    assert clip["clipUrl"].startswith("file://")
    stored = api.audio_store_clip(T_STORY, 7000, 8000, "data:audio/webm;base64,AAAA", "audio/webm")
    assert stored["clipPath"].endswith("_7000-8000.webm")


def test_errors_are_plain_runtime_errors(tmp_path):
    api = make(tmp_path)
    try:
        api.flex_get("entry", "00000000-0000-4000-8000-000000000000")
    except RuntimeError as e:
        assert "not cached" in str(e) or "No entry" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_tabs_folders_settings(tmp_path):
    api = make(tmp_path)
    t = api.add_tab("Grammar", "#123456")
    api.update_tab(t["dir"], {"name": "Grammar!"})
    f = api.create_folder(t["dir"], "Verbs")
    n = api.create_note(t["dir"], f, "x", "")
    assert api.folders()[t["dir"]] == ["Verbs"]
    assert api.rename_folder(t["dir"], f, "Verbs 2") == "Verbs 2"
    assert api.get_note(n["id"])["folder"] == "Verbs 2"
    assert api.reorder_tabs([t["dir"], "Notes"])[0]["dir"] == t["dir"]
    s = api.set_setting("diacriticsInsensitive", False)
    assert s["diacriticsInsensitive"] is False
    api.set_tags([{"name": "#todo", "color": "#000"}, {"name": "todo"}])
    assert [x["name"] for x in api._nb.config["tags"]] == ["todo"]


def test_flex_refresh_all_touches_every_embed(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    api.create_note(None, "", "A", "x {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} y")
    api.create_note(None, "", "B", "| a |\n|---|\n| {{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1-2 at=0e1f2a3b1001-0e1f2a3b1002 hl=1.1}} |\n\n{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=3}}\n\n{{flex:entry 00000000-0000-4000-8000-000000000000}}")
    r = api.flex_refresh_all()
    assert r["objects"] == 4 and r["refreshed"] == 3 and len(r["failed"]) == 1 and r["failed"][0]["guid"] == "00000000-0000-4000-8000-000000000000"
    snap = api._flex.cache.get(api._flex.project_name, "text", "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001")
    assert [s["n"] for s in snap["segments"]] == [1, 2, 3]


def test_flex_status_reports_configuration_and_error_codes(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    st = api.flex_status()
    assert st["open"] and st["configured"] and st["errorCode"] == "" and st.get("shared") is None
    # an unconfigured LCM source: not open, not configured, a clear code
    st = api.flex_configure("lcm", "", "")
    assert not st["open"] and not st["configured"] and st["errorCode"] == "no-project"
    st = api.flex_configure("flextext", "", "")
    assert not st["open"] and st["errorCode"] == "no-file"


def test_file_dialog_filters_are_well_formed(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    seen = {}
    api._dialog = lambda kind, **kw: seen.update(kw) or None
    api._file_dialog(("Audio (*.wav;*.mp3)", "*.wav;*.mp3"), ("All files", "*.*"))
    assert seen["file_types"] == ("Audio (*.wav;*.mp3)", "All files (*.*)")
    assert api.audio_tools()["clipFormat"] in ("flac", "wav")


def test_duplicate_note_in_place_and_to_another_tab(tmp_path):
    api = make(tmp_path)
    n = api.create_note(None, "", "SVCs", "Body with {{flex:text %s seg=1}}" % T_STORY)
    api.save_note(n["id"], {"tags": ["grammar"], "pinned": True})
    c = api.duplicate_note(n["id"])
    assert c["id"] != n["id"] and c["title"] == "SVCs (copy)" and c["body"] == api.get_note(n["id"])["body"]
    assert c["tags"] == ["grammar"] and not c["pinned"] and c["tab"] == n["tab"] and c["folder"] == n["folder"]
    assert len(api.list_notes()) == 2
    api.add_tab("Archive")
    d = api.duplicate_note(n["id"], "Archive", "Old")
    assert d["title"] == "SVCs" and d["tab"] == "Archive" and d["folder"] == "Old" and d["body"] == c["body"]
    assert (tmp_path / "nb" / "Archive" / "Old").is_dir()


def test_build_fingerprint_is_short_hex_and_reported(tmp_path):
    from flex_scratchpad import build_id
    b = build_id()
    assert len(b) == 7 and int(b, 16) >= 0 and build_id() == b
    assert make(tmp_path).init()["build"] == b


def test_texts_used_lists_each_source_text_once(tmp_path):
    """Seth, 2026-10-16: "list which texts are referenced in a [note], a folder, or a selected
    range … not individual items, but texts they come from … a FLEx hyperlink for each"."""
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    from flex_scratchpad.flex.demo import T_ARAB, T_STORY
    api = Api(AppConfig(tmp_path / "c.json"), notebook_dir=tmp_path / "nb", demo=True)
    tab = api.init()["config"]["tabs"][0]["dir"]
    api.create_folder(tab, "Grammar")
    api.create_folder(tab, "Grammar/Verbs")
    a = api.create_note(tab, "Grammar", "A", "{{flex:text %s seg=1}}\n\n{{flex:text %s seg=2}}\n\nInline {{flex:text %s seg=4}} and [see](flex:text/%s)" % (T_STORY, T_STORY, T_STORY, T_ARAB))
    api.create_note(tab, "Grammar/Verbs", "B", "{{flex:text %s seg=1}}\n\n{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}" % T_ARAB)
    api.create_note(tab, "", "Elsewhere", "{{flex:text %s seg=3}}" % T_STORY)
    # a folder takes its subfolders; three examples from one text and one from another: two rows
    r = api.texts_used({"tab": tab, "folder": "Grammar"})
    assert r["notes"] == 2
    rows = {t["title"]: t for t in r["texts"]}
    assert set(rows) == {"The dog and the river", "الكلب والنهر"}
    assert rows["The dog and the river"]["examples"] == 3 and [n["title"] for n in rows["The dog and the river"]["notes"]] == ["A"]
    assert rows["الكلب والنهر"]["examples"] == 1 and rows["الكلب والنهر"]["links"] == 1
    assert {n["title"] for n in rows["الكلب والنهر"]["notes"]} == {"A", "B"}
    for t in r["texts"]:                                         # a FLEx hyperlink for each
        assert t["url"].startswith("silfw://localhost/link?app=flex") and "tool=interlinearEdit" in t["url"] and t["guid"] in t["url"]
    # one note, and the highlighted part of it
    assert [t["title"] for t in api.texts_used({"note": a["id"]})["texts"]] == ["The dog and the river", "الكلب والنهر"]
    part = api.texts_used({"note": a["id"], "markdown": "{{flex:text %s seg=2}}" % T_STORY})["texts"]
    assert len(part) == 1 and part[0]["examples"] == 1
    # the whole tab, and a note with no examples
    assert api.texts_used({"tab": tab, "folder": ""})["notes"] >= 3
    empty = api.create_note(tab, "", "Plain", "No examples here.")
    assert api.texts_used({"note": empty["id"]}) == {"texts": [], "notes": 1}
