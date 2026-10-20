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
    {"type": "table", "rows": [[{"runs": [{"text": "h1"}]}, {"runs": [{"text": "h2"}]}, {"runs": [{"text": "h3"}]}],
                               [{"runs": [{"text": "wide"}]}, {"runs": [], "covered": True}, {"runs": [{"text": "r1"}]}],
                               [{"runs": [{"text": "tall"}]}, {"runs": [{"text": "x"}]}, {"runs": [{"text": "y"}]}],
                               [{"runs": [], "covered": True}, {"runs": [{"text": "z"}]}, {"runs": [{"text": "w"}]}]],
     "aligns": [None, None, None], "style": {"flags": [], "cols": {}, "rows": {}, "spans": {"2.1": {"rows": 1, "cols": 2}, "3.1": {"rows": 2, "cols": 1}}}},
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
    for needle in ("Heading", "bold", "kabir", "Kabir", "nuwa-mo", "The dog slept.", "a domestic dog", ">\u2611 <", ">one<", ">1. <", ">two<"):
        assert needle in xml, needle
    assert xml.count("<w:tbl>") == 3                     # the note tables and the interlinear grid
    assert '<w:gridSpan w:val="2"/>' in xml and '<w:vMerge w:val="restart"/>' in xml and "<w:vMerge/>" in xml
    tbl2 = xml.split("<w:tbl>")[2]
    assert tbl2.count("<w:tc>") == 3 + 2 + 3 + 3      # merged-right row has two cells; the vMerge continuation cell exists
    assert '<w:highlight w:val="lightGray"/>' in xml and '<w:color w:val="C0392B"/>' in xml
    assert '<w:u w:val="single"/>' in xml and '<w:rFonts w:ascii="Charis SIL"' in xml
    assert '<w:tcW w:w="1800"' in xml                    # 120px column → twentieths of a point
    assert "r:embed=\"rIdImg1\"" in xml
    ET.fromstring(z.read("word/_rels/document.xml.rels"))


def test_docx_numbered_indented_examples():
    """`ex` / `indent=N` on an embed: (n) above the example, the whole example stepped in."""
    doc = {"title": "Ex", "blocks": [
        dict(DOC["blocks"][5], exNum="(1)", indent=2),                       # the interlinear
        dict(DOC["blocks"][6], exNum="(2)", indent=1),                       # the entry
    ]}
    xml = zipfile.ZipFile(__import__("io").BytesIO(build_docx(doc))).read("word/document.xml").decode("utf-8")
    ET.fromstring(xml)
    # the example's number is Word's own, in a first cell styled LingTeX Example (LingTeX-Word's shape)
    assert xml.index('<w:pStyle w:val="LingTeXExample"/>') < xml.index(">Kabir<") and xml.index(">(2)<") < xml.index(">kabir<")
    assert '<w:tblInd w:w="720" w:type="dxa"/>' in xml                       # the interlinear table, 2 levels in
    assert '<w:ind w:left="1440"/>' in xml                                   # its Free line: the indent + the number column (36 pt)
    assert '<w:ind w:left="360"/>' in xml and '<w:ind w:left="720"/>' in xml  # entry head / sense (level 0) + 1


def test_docx_examples_are_lingtex_word_tables():
    """Seth, 2026-10-18: "all of our IGTs should be rendered using LingTeX Word styling wherever
    they're expanded" — the LingTeX Interlinear table style, a paragraph style per tier, the free
    translation as a LingTeX Free paragraph in single quotes, grammatical glosses in small
    capitals through the LingTeX Gram Gloss character style (lowercased, first letter kept),
    the number by Word's LingTeX Example Number list, a FLEx link after the translation."""
    from flex_scratchpad.docx_writer import is_gram_gloss, split_gloss_segments, small_caps_form, gram_gloss_runs
    assert [is_gram_gloss(x) for x in ("ERG", "3SG", "1pl", "dog", "N.", "P.N.", "A", "PST", "3SG.M", "")] == [True, True, True, False, False, False, False, True, False, False]
    assert split_gloss_segments("3SG-sleep-PST.CMP") == ["3SG", "-", "sleep", "-", "PST", ".", "CMP"]
    assert small_caps_form("ERG") == "Erg" and small_caps_form("3SG") == "3Sg"
    runs = gram_gloss_runs([{"text": "3SG-sleep-PST", "color": "#2a6e2a"}])
    assert [(r["text"], r.get("rStyle")) for r in runs] == [("3Sg", "LingTeXGramGloss"), ("-", None), ("sleep", None), ("-", None), ("Pst", "LingTeXGramGloss")]
    block = {"type": "interlinear", "title": "The dog", "url": "silfw://localhost/link?app=flex&guid=x", "ws": {"font": "Charis SIL"}, "exNum": "(1)", "segments": [
        {"n": 1, "label": "1.1", "lines": [{"name": "txt", "cells": [[{"text": "Kabir lo", "color": "#00379c"}], [{"text": "ka-nuwa-mo", "color": "#00379c"}]]},
                                            {"name": "mgls", "cells": [[{"text": "dog", "color": "#2a6e2a"}], [{"text": "3SG-sleep-PST", "color": "#2a6e2a"}]]},
                                            {"name": "pos", "cells": [[{"text": "n", "color": "#7a3e9d"}], [{"text": "v", "color": "#7a3e9d"}]]}],
         "free": [{"text": "The dog slept.", "hl": "#fff2a8"}]},
        {"n": 2, "label": "1.2", "lines": [{"name": "txt", "cells": [[{"text": "Haŋa"}]]}, {"name": "mgls", "cells": [[{"text": "yesterday"}]]}], "free": [{"text": "Yesterday."}]}]}
    z = zipfile.ZipFile(__import__("io").BytesIO(build_docx({"title": "LT", "blocks": [block]})))
    xml = z.read("word/document.xml").decode("utf-8")
    styles = z.read("word/styles.xml").decode("utf-8")
    numbering = z.read("word/numbering.xml").decode("utf-8")
    for part in (xml, styles, numbering):
        ET.fromstring(part)
    for name in ("LingTeX Interlinear", "LingTeX Vernacular", "LingTeX Morphemes", "LingTeX Gloss", "LingTeX Word Gloss", "LingTeX Category", "LingTeX Free", "LingTeX Gram Gloss", "LingTeX Example", "LingTeX Example Number"):
        assert f'w:val="{name}"' in styles, name
    assert '<w:lvlText w:val="(%1)"/>' in numbering and '<w:lvlText w:val="%2."/>' in numbering
    assert xml.count('<w:tblStyle w:val="LingTeXInterlinear"/>') == 2                   # one table per line of text
    assert '<w:pStyle w:val="LingTeXVernacular"/>' in xml and '<w:pStyle w:val="LingTeXGloss"/>' in xml and '<w:pStyle w:val="LingTeXCategory"/>' in xml
    assert "Kabir\u00a0lo" in xml                                                          # the baseline keeps its space unbreakable
    assert '<w:rStyle w:val="LingTeXGramGloss"/>' in xml and ">3Sg<" in xml and ">Pst<" in xml and ">sleep<" in xml
    assert '<w:color w:val="00379C"/>' not in xml and '<w:color w:val="2A6E2A"/>' not in xml   # the styles carry the look; the app's colours do not travel
    assert '<w:pStyle w:val="LingTeXFree"/>' in xml and "\u2018" in xml and "The dog slept." in xml and '<w:highlight w:val="yellow"/>' in xml   # the user's highlight stays
    assert xml.count('<w:pStyle w:val="LingTeXExample"/>') == 3 and xml.count('<w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr>') == 2   # "(1)" and "a." on line 1, "b." on line 2
    assert 'TargetMode="External"' in z.read("word/_rels/document.xml.rels").decode("utf-8") and ">The dog 1.1<" in xml   # the FLEx link after the translation
    assert '<w:cantSplit/>' in xml and "numbering.xml" in z.read("[Content_Types].xml").decode("utf-8")


def test_docx_indented_table():
    doc = {"title": "T", "blocks": [dict(DOC["blocks"][3], indent=2)]}
    xml = zipfile.ZipFile(__import__("io").BytesIO(build_docx(doc))).read("word/document.xml").decode("utf-8")
    ET.fromstring(xml)
    assert '<w:tblInd w:w="720" w:type="dxa"/>' in xml


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
