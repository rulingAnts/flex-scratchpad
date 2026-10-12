"""The notebook on disk: front matter, tabs/folders as directories, tags, search, trash."""
import json
from pathlib import Path

import pytest

from flex_scratchpad import notebook as nbmod
from flex_scratchpad.notebook import Notebook, dump_front_matter, parse_note_file, parse_query, slugify, make_snippet


def test_front_matter_round_trip():
    meta = {"id": "n_0123456789", "title": "A: title #1 [x]", "tags": ["todo", "gram-mar"], "created": "2026-10-12T09:30:00", "pinned": True}
    text = dump_front_matter(meta) + "body\n\n**bold**"
    got, body = parse_note_file(text)
    assert got == meta
    assert body == "body\n\n**bold**"


def test_plain_file_without_header_is_all_body():
    meta, body = parse_note_file("just text\n")
    assert meta == {} and body == "just text\n"


def test_slugify_keeps_unicode_letters():
    assert slugify("வணக்கம் / test: two?") == "வணக்கம் - test- two"
    assert slugify("   ") == "note"
    assert slugify("a" * 100).startswith("a" * 60) and len(slugify("a" * 100)) == 60


def test_notebook_lifecycle(tmp_path):
    nb = Notebook(tmp_path)
    assert (tmp_path / "notebook.json").exists()
    assert nb.tab_dirs() == ["Notes"]
    n = nb.create_note(title="Aspect marking", body="Hello **world** #phonology")
    path = Path(n.path)
    assert path.name == f"Aspect marking--{n.id}.md" and path.parent.name == "Notes"
    # rename moves the file; id is stable
    nb.save_note(n.id, title="Aspect marking (verbs)")
    n2 = nb.get_note(n.id)
    assert n2.path.name.startswith("Aspect marking (verbs)--") and not path.exists()
    # tabs and folders are directories
    t = nb.add_tab("Grammar / Verbs")
    assert (tmp_path / t["dir"]).is_dir() and t["dir"] == "Grammar - Verbs"
    f = nb.create_folder(t["dir"], "Aspect")
    nb.move_note(n.id, t["dir"], f)
    assert nb.get_note(n.id).path.parent == tmp_path / t["dir"] / "Aspect"
    assert nb.folders()[t["dir"]] == ["Aspect"]
    # rescanning from disk finds the same note
    nb2 = Notebook(tmp_path)
    got = nb2.get_note(n.id)
    assert got.title == "Aspect marking (verbs)" and got.tab == t["dir"] and got.folder == "Aspect"
    assert "phonology" in [x["name"] for x in nb2.all_tags()]
    # trash, never delete
    nb2.delete_note(n.id)
    with pytest.raises(KeyError):
        nb2.get_note(n.id)
    assert list((tmp_path / ".scratchpad" / "trash").iterdir())


def test_unknown_directory_becomes_a_tab(tmp_path):
    (tmp_path / "Fieldwork 2026").mkdir(parents=True)
    (tmp_path / "Fieldwork 2026" / "loose.md").write_text("A loose note\nwith no header", encoding="utf-8")
    nb = Notebook(tmp_path)
    assert "Fieldwork 2026" in nb.tab_dirs()
    notes = nb.list_notes()
    assert len(notes) == 1 and notes[0]["title"] == "loose" and notes[0]["tab"] == "Fieldwork 2026"


def test_tag_rename_touches_headers_and_inline_tags(tmp_path):
    nb = Notebook(tmp_path)
    a = nb.create_note(title="a", body="see #todo and #todo-later")
    nb.save_note(a.id, tags=["todo"])
    changed = nb.rename_tag("todo", "done")
    assert changed == 1
    n = nb.get_note(a.id)
    assert n.tags == ["done"] and n.body == "see #done and #todo-later"


def test_search_ranking_filters_and_diacritics(tmp_path):
    nb = Notebook(tmp_path)
    nb.create_note(title="Vowel harmony", body="Notes on harmony in the verb.")
    hit = nb.create_note(title="Verbs", body="The suffix -mo marks past tense. See ɲamú for the vocative.")
    nb.save_note(hit.id, tags=["grammar"])
    t = nb.add_tab("Lexicon")
    nb.create_note(tab=t["dir"], title="lexeme", body="harmony harmony harmony harmony")
    r = nb.search("harmony")
    assert [x["title"] for x in r][:1] == ["Vowel harmony"]           # a title match outranks body repeats
    assert [x["title"] for x in nb.search("harmony tab:Lexicon")] == ["lexeme"]
    assert [x["title"] for x in nb.search("tag:grammar")] == ["Verbs"]
    assert [x["title"] for x in nb.search("#grammar")] == ["Verbs"]
    assert [x["title"] for x in nb.search('"past tense"')] == ["Verbs"]
    assert nb.search('"tense past"') == []
    assert [x["title"] for x in nb.search("ɲamu")] == ["Verbs"]        # diacritics-insensitive by default (ɲ is its own letter)
    nb.config["settings"]["diacriticsInsensitive"] = False
    assert nb.search("ɲamu") == []
    assert [x["title"] for x in nb.search("ɲamú")] == ["Verbs"]


def test_snippet_marks_point_at_original_text():
    body = "Intro line. The suffix -mo marks past tense, and -mo again."
    snippet, marks = make_snippet(body, ["-mo"], True, width=20)
    for a, b in marks:
        assert snippet[a:b].lower() == "-mo"
    assert len(marks) == 2


def test_parse_query():
    q = parse_query('aspect "free translation" tag:todo tab:Grammar #x')
    assert q["terms"] == ["aspect", "free translation"]
    assert q["filters"] == {"tag": ["todo", "x"], "tab": ["Grammar"], "folder": []}


def test_extra_text_reaches_the_index(tmp_path):
    seen = {}
    nb = Notebook(tmp_path, extra_text=lambda body: "kabir dog" if "{{flex" in body else "")
    nb.create_note(title="embed", body="{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}")
    assert [x["title"] for x in nb.search("kabir")] == ["embed"]


def test_config_merge_keeps_unknown_keys(tmp_path):
    nb = Notebook(tmp_path)
    cfg = json.loads((tmp_path / "notebook.json").read_text(encoding="utf-8"))
    cfg["future"] = {"x": 1}
    (tmp_path / "notebook.json").write_text(json.dumps(cfg), encoding="utf-8")
    nb2 = Notebook(tmp_path)
    assert nb2.config["future"] == {"x": 1} and nb2.config["flex"]["source"] == "lcm"
