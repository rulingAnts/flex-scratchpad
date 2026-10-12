"""Exports: the zero-dependency docx writer, zip export/import, the sync fingerprint."""
import zipfile
import xml.etree.ElementTree as ET

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.docx_writer import build_docx


DOC = {"title": "Past tense", "blocks": [
    {"type": "h", "level": 2, "runs": [{"text": "Heading"}]},
    {"type": "p", "runs": [{"text": "plain "}, {"text": "bold", "b": True}, {"text": " ", }, {"text": "hl", "hl": "#ffd6a5"}, {"text": " red", "color": "#c0392b"}]},
    {"type": "list", "items": [{"runs": [{"text": "one"}], "task": True, "checked": True}, {"runs": [{"text": "two"}], "ordered": True, "n": 1}]},
    {"type": "table", "rows": [[{"runs": [{"text": "Form"}]}, {"runs": [{"text": "Gloss"}]}], [{"runs": [{"text": "kabir"}]}, {"blocks": [{"type": "p", "runs": [{"text": "dog"}]}]}]],
     "aligns": ["left", None], "style": {"flags": ["striped"], "cols": {"1": {"bold": True, "width": "120px"}}, "rows": {}}},
    {"type": "interlinear", "title": "The dog", "label": "ex. 1", "ws": {"font": "Charis SIL"}, "segments": [
        {"n": 1, "lines": [{"name": "txt", "cells": [[{"text": "Kabir", "font": "Charis SIL", "color": "#00379c"}], [{"text": "ka-", "u": True}, {"text": "nuwa-mo"}]]},
                            {"name": "gls", "cells": [[{"text": "dog"}], [{"text": "slept"}]]}],
         "free": [{"text": "The dog slept.", "hl": True}], "notes": [[{"text": "a note", "i": True}]]}]},
    {"type": "entry", "headword": "kabir", "pos": "n", "senses": [{"number": "1", "pos": "n", "gloss": "dog", "definition": "a domestic dog", "examples": [{"text": "kabir lo", "translation": "the dog"}]}]},
    {"type": "image", "png": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "width": 1, "height": 1},
    {"type": "hr"},
]}


def test_docx_is_a_valid_package_with_the_content(tmp_path):
    raw = build_docx(DOC)
    z = zipfile.ZipFile(tmp_path / "x.docx", "r") if False else zipfile.ZipFile(__import__("io").BytesIO(raw))
    names = set(z.namelist())
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels", "word/media/image1.png"} <= names
    xml = z.read("word/document.xml").decode("utf-8")
    ET.fromstring(xml)                                   # well-formed
    for needle in ("Heading", "bold", "kabir", "Kabir", "nuwa-mo", "The dog slept.", "a domestic dog", "☑ one", "1. two"):
        assert needle in xml, needle
    assert xml.count("<w:tbl>") == 2                     # the note table and the interlinear grid
    assert '<w:highlight w:val="lightGray"/>' in xml and '<w:color w:val="C0392B"/>' in xml
    assert '<w:u w:val="single"/>' in xml and '<w:rFonts w:ascii="Charis SIL"' in xml
    assert '<w:tcW w:w="1800"' in xml                    # 120px column → twentieths of a point
    assert "r:embed=\"rIdImg1\"" in xml
    ET.fromstring(z.read("word/_rels/document.xml.rels"))


def test_zip_export_import_round_trip(tmp_path):
    cfg = AppConfig(tmp_path / "cfg.json")
    api = Api(cfg, notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "Moved", "body {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}")
    api.flex_get("entry", "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001")      # snapshot in the cache
    api.delete_note(api.create_note(None, "", "Trashed", "x")["id"])
    zp = api.export_notebook_zip(str(tmp_path / "out.zip"))
    names = zipfile.ZipFile(zp).namelist()
    assert any(name.startswith("Notes/Moved--") for name in names)
    assert "notebook.json" in names
    assert any(".scratchpad/flex-cache/" in name for name in names)
    assert not any("/trash/" in name for name in names)
    init = api.import_notebook_zip(zp, str(tmp_path / "other"))
    assert [x["title"] for x in init["notes"]] == ["Moved"]
    assert (tmp_path / "other" / ".scratchpad" / "flex-cache").is_dir()
    assert api._nb.root == tmp_path / "other"


def test_fingerprint_and_change_detection(tmp_path):
    cfg = AppConfig(tmp_path / "cfg.json")
    api = Api(cfg, notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "Synced", "v1")
    a = api.notebook_stamp()["stamp"]
    import time
    time.sleep(0.01)
    # another machine edits the file
    path = api._nb.get_note(n["id"]).path
    text = path.read_text(encoding="utf-8").replace("v1", "v2").replace("updated: ", "updated: 2099-01-01T00:00:00\n#")
    path.write_text(text, encoding="utf-8")
    assert api.notebook_stamp()["stamp"] != a
    fresh = api.note_changed_on_disk(n["id"], n["updated"])
    assert fresh and fresh["body"].strip() == "v2"
    assert api.note_changed_on_disk(n["id"], fresh["updated"]) is None
    assert api.export_note_markdown(n["id"], str(tmp_path / "x.md")).endswith("x.md")
    assert api.export_note_html(n["id"], "<p>hi</p>", str(tmp_path / "x.html")) and (tmp_path / "x.html").read_text() == "<p>hi</p>"
    assert api.export_note_docx(n["id"], DOC, str(tmp_path / "x.docx")) and zipfile.is_zipfile(tmp_path / "x.docx")
