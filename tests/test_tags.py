"""FLEx text markup tags (Seth, 2026-10-17): read with a text, listed for the picker and the
style editors, found by tag across the project, searchable in notes; and the scoped tag styles the
notebook keeps (an example's own live in its embed)."""
import json
from pathlib import Path

import pytest

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex import model
from flex_scratchpad.flex.demo import T_STORY, TAG_LIST
from flex_scratchpad.notebook import parse_query


def make(tmp_path):
    return Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)


def test_a_text_carries_its_tags_and_a_tag_keeps_its_place_in_a_page(tmp_path):
    api = make(tmp_path)
    t = api.flex_get("text", T_STORY, 1, 2)
    tags = t["tags"]
    assert len(tags) == 8                                   # all of the text's tags, whatever the page
    first = tags[0]
    assert first["tag"]["name"] == "Subject" and first["tag"]["abbr"] == "S"
    assert first["tag"]["path"] == ["Syntax", "Arguments"] and first["tag"]["group"] == "Arguments"   # FLEx's list nests: the whole path, top first
    assert first["from"] == {"seg": 1, "w": 0} and first["to"] == {"seg": 1, "w": 0}
    assert first["tag"]["back"] == "#dbeafe"                # FLEx's own colour, when the list item has one
    spanning = [x for x in tags if x["from"]["seg"] != x["to"]["seg"]]
    assert spanning and spanning[0]["tag"]["name"] == "Topic" and (spanning[0]["from"]["seg"], spanning[0]["to"]["seg"]) == (5, 6)
    # the snapshot keeps them, so a note shows its tags without FLEx
    snap = api._flex.cache.get(api._flex.project_name, "text", T_STORY)
    assert len(snap["tags"]) == 8


def test_the_tag_list_and_where_each_tag_is_used(tmp_path):
    api = make(tmp_path)
    lst = api.flex_text_tags()
    assert [t["name"] for t in lst] == ["Subject", "Object", "Verb", "Topic", "Focus"]
    assert {t["name"]: t["count"] for t in lst}["Topic"] == 2
    rows = api.flex_tag_occurrences(next(t["guid"] for t in lst if t["name"] == "Topic"))
    assert [(r["seg"], r["segTo"], r["label"], r["labelTo"]) for r in rows] == [(4, 4, "2.2", "2.2"), (5, 6, "3.1", "3.2")]
    assert rows[0]["words"] == "Kabir pemu" and rows[1]["words"] == "Tiket ka-nuwa-mo…"
    assert rows[0]["at"] == [model.anchor_of("9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b1004"), model.anchor_of("9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b1004")]
    assert [r["seg"] for r in api.flex_tag_occurrences(lst[0]["guid"], "tiket")] == [2]     # filtered by the words
    # the list is kept in the snapshot folder for a session without FLEx
    api._flex.close()
    assert [t["name"] for t in api.flex_text_tags()] == [t["name"] for t in lst]


def test_fw_colours_and_searchable_text():
    assert model.fw_color(0x00FF80) == "#80ff00"            # BGR → #rrggbb
    assert model.fw_color(-1073741824) == "" and model.fw_color(-1) == "" and model.fw_color("x") == ""
    # an item nobody coloured reads 0/0 (black on black): no colour, so the palette takes over
    # (Seth's project, 2026-10-18: every tag a black bar)
    black = model.tag_item("g", "Subject", "S", "", model.fw_color(0), model.fw_color(0))
    assert (black["fore"], black["back"]) == ("", "")
    kept = model.tag_item("g", "Subject", "S", "", "#ffffff", "#000000")
    assert (kept["fore"], kept["back"]) == ("#ffffff", "#000000")


def test_lcm_never_reads_a_name_through_flexicon_s_beststr():
    """Seth's project, 2026-10-18: every tag was "?" — flexicon's BestStr validates with
    isinstance() against the multistring interfaces, which pythonnet's runtime-typed objects do
    not satisfy. Names, abbreviations and notes go through our own _best()."""
    src = Path("flex_scratchpad/flex/lcm.py").read_text(encoding="utf-8")
    uses = [l for l in src.splitlines() if "BestStr(" in l and "explain_tags" not in l and "flexiconBestStr" not in l and not l.strip().startswith(("#", "*", '"""'))]
    assert uses == [], uses
    assert "def _best(self, multi)" in src
    text = {"kind": "text", "title": "T", "segments": [], "tags": [{"tag": {"name": "Topic shift", "abbr": "Top"}}]}
    st = model.searchable_text(text)
    assert "Topic shift" in st and "⚑Topic_shift" in st and "⚑Top" in st
    assert parse_query("tagged:Topic_shift kabir")["terms"] == ["⚑Topic_shift", "kabir"]


def test_notes_are_found_by_the_tags_on_their_examples(tmp_path):
    api = make(tmp_path)
    tagged = api.create_note(None, "", "Tagged", "{{flex:text %s seg=4}}" % T_STORY)
    api.create_note(None, "", "Plain", "Nothing from FLEx here.")
    api.flex_get("text", T_STORY, 4, 4)                     # drawn once: the snapshot now holds the tags
    api._nb.reindex_all()
    ids = [h["id"] for h in api.search("tagged:Topic")]
    assert ids == [tagged["id"]]
    assert [h["id"] for h in api.search("Topic")] == [tagged["id"]]
    assert api.search("tagged:Nonesuch") == []


def test_scoped_tag_styles_are_kept_in_notebook_json_and_cleaned(tmp_path):
    api = make(tmp_path)
    tab = api.init()["config"]["tabs"][0]["dir"]
    ts = api.set_tag_styles("tab", tab, [{"tag": "Subject", "bg": "#DBEAFE", "b": True, "hide": False, "fg": "nonsense"},
                                        {"tag": "*", "hide": True, "enabled": False}, {"tag": "", "bg": "#000000"}, "junk"])
    assert ts["tab"][tab] == [{"tag": "Subject", "enabled": True, "hide": False, "bg": "#dbeafe", "b": True},
                              {"tag": "*", "enabled": False, "hide": True}]
    cfg = json.loads((tmp_path / "nb" / "notebook.json").read_text(encoding="utf-8"))
    assert cfg["tagStyles"]["tab"][tab][0]["tag"] == "Subject"
    assert api.init()["config"]["tagStyles"]["tab"][tab][1]["enabled"] is False
    api.set_tag_styles("folder", tab + "/Verbs", [{"tag": "Topic", "label": False}])
    assert api.set_tag_styles("folder", tab + "/Verbs", [])["folder"] == {}        # no rules: the key goes
    api.set_tag_styles("note", "n1", [{"tag": "filter:f1", "hide": True}])        # a note's view settings: which filters are on for it
    assert api.init()["config"]["tagStyles"]["note"]["n1"] == [{"tag": "filter:f1", "enabled": True, "hide": True}]
    with pytest.raises(ValueError):
        api.set_tag_styles("page", "x", [])


def test_visual_filters_and_text_styles_are_kept_in_notebook_json(tmp_path):
    api = make(tmp_path)
    tab = api.init()["config"]["tabs"][0]["dir"]
    ts = api.set_tag_styles("tab", tab, [{"tag": "Subject", "br": "sq", "hl": True, "c": "#B45309", "bar": False}, {"tag": "Verb", "br": "nonsense", "box": True, "bar": True},
                                        {"tag": "group:Syntax", "tile": True}, {"tag": "filter:abc", "hide": False}])
    assert ts["tab"][tab] == [{"tag": "Subject", "enabled": True, "c": "#b45309", "hl": True, "br": "sq", "bar": False},
                              {"tag": "Verb", "enabled": True, "box": True, "bar": True},
                              {"tag": "group:Syntax", "enabled": True, "tile": True}, {"tag": "filter:abc", "enabled": True, "hide": False}]
    ts = api.set_tag_filters([{"id": "Disc 1!", "name": " Discourse ", "rules": [{"tag": "group:Discourse", "br": "an"}]}, {"name": "Second", "enabled": False, "rules": "junk"}, "junk", {"id": "disc1", "name": "dup"}])
    assert [f["id"] for f in ts["filters"]] == ["disc1", ts["filters"][1]["id"]] and ts["filters"][1]["id"].startswith("f")
    assert ts["filters"][0] == {"id": "disc1", "name": "Discourse", "enabled": True, "rules": [{"tag": "group:Discourse", "enabled": True, "br": "an"}]}
    assert ts["filters"][1]["enabled"] is False and ts["filters"][1]["rules"] == []
    cfg = json.loads((tmp_path / "nb" / "notebook.json").read_text(encoding="utf-8"))
    assert cfg["tagStyles"]["filters"][0]["name"] == "Discourse"
    assert api.init()["config"]["tagStyles"]["filters"][0]["id"] == "disc1"


def test_the_notes_that_use_each_flex_tag_are_known_as_soon_as_a_text_is_fetched(tmp_path):
    api = make(tmp_path)
    tab = api.init()["config"]["tabs"][0]["dir"]
    tagged = api.create_note(tab, "", "Tagged", "{{flex:text %s seg=4}}" % T_STORY)
    api.create_note(tab, "", "Plain", "Nothing from FLEx here.")
    assert api.flex_tags_used() == {}                       # nothing fetched yet: the index knows no tags
    api.flex_get("text", T_STORY, 4, 4)                     # drawn once: the quoting note is re-indexed with the text's tags
    used = api.flex_tags_used()
    assert used["topic"] == [tagged["id"]] and used["top"] == [tagged["id"]] and used["subject"] == [tagged["id"]]
    assert [h["id"] for h in api.search("tagged:topic")] == [tagged["id"]]
