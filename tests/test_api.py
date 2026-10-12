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
