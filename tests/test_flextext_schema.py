"""Every .flextext the app writes is checked twice (Seth, 2026-10-16: "You are checking the official
flextext documentation … and XSD, right?"):

1. against FieldWorks' own schema, tests/fixtures/FlexInterlinear.xsd — a verbatim copy of
   https://github.com/sillsdev/FieldWorks/blob/master/DistFiles/Language%20Explorer/Export%20Templates/Interlinear/FlexInterlinear.xsd
   (LGPL, SIL International). One allowance: FLEx's OWN exporter (InterlinearExporter.cs) writes
   `RightToLeft="true"` on <language>, which the schema does not list; we write it as FLEx does
   and drop it before validating.
2. against what FLEx's importer (BIRDInterlinearImporter.cs) actually assumes, which is more than
   the schema says — `flex.flextext_check.import_problems`. Seth's export was schema-valid and
   still failed the import on one <word/> without items.
"""
from pathlib import Path

import pytest

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex.demo import T_ARAB, T_STORY
from flex_scratchpad.flex.flextext_check import import_problems

etree = pytest.importorskip("lxml.etree")
XSD = Path(__file__).parent / "fixtures" / "FlexInterlinear.xsd"


def schema_errors(xml: str) -> list[str]:
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    doc = etree.fromstring(xml.encode("utf-8"))
    for lg in doc.iter("language"):
        lg.attrib.pop("RightToLeft", None)            # FLEx's own exporter writes it; its XSD lags
    if schema.validate(doc):
        return []
    return [f"line {e.line}: {e.message}" for e in schema.error_log]


def both(xml: str) -> list[str]:
    return schema_errors(xml) + import_problems(xml)


EXPORTS = {
    "plain": ([{"kind": "text", "guid": T_STORY, "seg": [1, 2], "label": "a"}, {"kind": "text", "guid": T_STORY, "seg": [4, 4]}],
              {"title": "Plain", "includeLink": True, "includeMarkdown": True}),
    "mixed baselines (RTL)": ([{"kind": "text", "guid": T_STORY, "seg": [1, 1]}, {"kind": "text", "guid": T_ARAB, "seg": None}],
                              {"title": "Mixed / RTL"}),
    "clips": ([{"kind": "text", "guid": T_STORY, "seg": [1, 3]}], {"title": "Clips", "audio": "clips"}),
    "bundle": ([{"kind": "text", "guid": T_STORY, "seg": [1, 2]}, {"kind": "text", "guid": T_STORY, "seg": [4, 4]}], {"title": "Bundle", "audio": "bundle"}),
    "original audio": ([{"kind": "text", "guid": T_STORY, "seg": [2, 2]}], {"title": "Orig", "audio": "original"}),
    "no audio, no guids, no source notes": ([{"kind": "text", "guid": T_STORY, "seg": None}],
                                           {"title": "Bare", "audio": "none", "wordGuids": False, "sourceNotes": False}),
}


@pytest.mark.parametrize("name", list(EXPORTS))
def test_every_export_is_schema_valid_and_importable(tmp_path, name):
    items, opts = EXPORTS[name]
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "C", "Some text.\n\n> a note", "examples")
    items = [dict(it, note="An example's own note.") if k == 0 else it for k, it in enumerate(items)]
    out = tmp_path / "x.flextext"
    api.export_note_flextext(n["id"], items, opts, str(out))
    xml = out.read_text(encoding="utf-8")
    assert both(xml) == []


def test_our_sample_fixture_is_schema_valid():
    xml = (Path(__file__).parent / "fixtures" / "sample.flextext").read_text(encoding="utf-8")
    assert schema_errors(xml) == []


SETH_SHAPE = """<?xml version="1.0" encoding="utf-8"?>
<document version="2"><interlinear-text guid="24e45d2d-4dd6-4e8e-b15d-d403189cf509">
<item type="title" lang="en">7 Shared Subject</item>
<paragraphs><paragraph guid="b73c5eea-21c5-4e34-b2dc-f95051f929a3"><phrases>
<phrase guid="45f3eeaf-31c3-4533-881c-86bc9ce7cc31"><item type="segnum" lang="en">3.1</item><words>
<word guid="7e23c17f-3188-474f-96f8-cfad79ff1412"><item type="txt" lang="fau">bodi</item>%s</word>
<word />
</words><item type="gls" lang="en">went and met him</item></phrase>
</phrases></paragraph></paragraphs>
<languages><language lang="fau" vernacular="true"/><language lang="en"/></languages>
</interlinear-text></document>"""


def test_the_checker_catches_what_the_schema_lets_through():
    """The shape of Seth's export (2026-10-16): valid by the XSD, fatal to FLEx's import."""
    xml = SETH_SHAPE % ""
    assert schema_errors(xml) == []
    assert import_problems(xml) == ["text 1, phrase 3.1, word 2: no txt or punct item"]
    bad_morphs = SETH_SHAPE % '<morphemes><morph type="stem"><item type="gls" lang="en">meet</item></morph></morphemes>'
    assert "text 1, phrase 3.1, word 1, morph 1: no txt item" in import_problems(bad_morphs)
    empty = SETH_SHAPE.replace("<word />", "") % "<morphemes></morphemes>"
    assert import_problems(empty) == ["text 1, phrase 3.1, word 1: an empty <morphemes>"]
    timed = SETH_SHAPE.replace('<phrase guid', '<phrase media-file="0b0b0b0b-0000-4000-8000-000000000000" begin-time-offset="0" end-time-offset="10" guid').replace("<word />", "") % ""
    assert import_problems(timed) == ["text 1, phrase 3.1: media-file 0b0b0b0b-0000-4000-8000-000000000000 is not in the text's <media-files>"]
    assert import_problems(SETH_SHAPE.replace("<word />", "") % "") == []


def test_an_export_the_importer_would_fail_on_is_refused(tmp_path, monkeypatch):
    from flex_scratchpad.flex import flextext_writer
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "C", "x", "examples")
    monkeypatch.setattr(flextext_writer, "build_flextext", lambda *a, **k: SETH_SHAPE % "")
    with pytest.raises(ValueError, match="would not import into FLEx.*word 2: no txt or punct item"):
        api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [1, 1]}], {"title": "x", "audio": "none"}, str(tmp_path / "bad.flextext"))
    assert not (tmp_path / "bad.flextext").exists()
