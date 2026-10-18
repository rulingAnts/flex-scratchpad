"""Text charts (Seth, 2026-10-18): FieldWorks constituent charts read into plain dicts, sliced by
rows with GUID anchors, snapshotted, searchable."""
import json
from pathlib import Path

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex import model
from flex_scratchpad.flex.demo import CHART, T_STORY, DemoBackend
from flex_scratchpad.notebook import parse_query


def _api(tmp_path):
    return Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)


def test_the_demo_chart_has_every_kind_of_cell_flex_makes():
    c = DemoBackend().get_chart(CHART)
    assert c["kind"] == "chart" and c["text"] == T_STORY and c["rowCount"] == 7
    assert [r["label"] for r in c["rows"]] == ["1a", "1b", "2a", "2b", "2c", "3a", "3b"]
    cols = c["template"]["columns"]
    assert [x["name"] for x in cols] == ["Outer", "Inner", "Subject", "Verb", "Object", "Inner", "Outer"]
    assert cols[1]["path"] == ["Prenuclear"] and cols[5]["path"] == ["Postnuclear"]     # same name, different group
    kinds = {cell["kind"] for r in c["rows"] for cell in r["cells"]}
    assert kinds == {"words", "moved", "clause", "tag"}
    r1b = c["rows"][1]
    assert r1b["endSent"] and r1b["endPara"]
    moved = [x for x in r1b["cells"] if x["kind"] == "moved"][0]
    assert moved["preposed"] and moved["targetRow"] == "1b" and moved["targetColN"] == 1
    clause = [x for r in c["rows"] for x in r["cells"] if x["kind"] == "clause"][0]
    assert clause["labels"] == ["2a"] and c["rows"][2]["clause"] == "speech"
    # a word group is PART of a segment: words by analysis index, punctuation left out
    v = [x for x in c["rows"][0]["cells"] if x["colN"] == 4][0]
    assert [w["txt"] for w in v["words"]] == ["ka-nuwa-mo", "lo"] and v["from"] == {"seg": 1, "w": 1} and v["to"] == {"seg": 1, "w": 2}
    assert [s["n"] for s in c["segments"]] == [1, 2, 3, 4, 5, 6] and c["segments"][0]["free"] == "The dog slept."
    assert c["index"][0] == {"n": 1, "label": "1a", "guid": c["rows"][0]["guid"]}


def test_rows_are_sliced_by_number_and_anchored_by_guid(tmp_path):
    api = _api(tmp_path)
    part = api.flex_get("chart", CHART, 2, 4)
    assert [r["label"] for r in part["rows"]] == ["1b", "2a", "2b"] and part["range"] == [2, 4]
    assert part["anchors"] == [model.anchor_of(part["rows"][0]["guid"]), model.anchor_of(part["rows"][-1]["guid"])]
    assert len(part["template"]["columns"]) == 7 and len(part["segments"]) == 6     # headers and translations for any slice
    # the anchors win over the numbers (a row inserted above moves the numbers, not the rows)
    moved = api.flex_get("chart", CHART, 1, 3, at=part["anchors"])
    assert [r["label"] for r in moved["rows"]] == ["1b", "2a", "2b"] and moved["rangeMoved"]
    whole = api.flex_get("chart", CHART)
    assert whole["rowCount"] == 7 and len(whole["rows"]) == 7


def test_a_chart_is_snapshotted_and_listed_without_flex(tmp_path):
    api = _api(tmp_path)
    api.flex_get("chart", CHART, 1, 2)
    snap = next((tmp_path / "nb" / ".scratchpad").rglob("chart-*.json"))
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["rowCount"] == 7 and len(data["rows"]) == 7           # the WHOLE chart is kept
    assert api.flex_charts()[0]["name"] == "Story chart" and api.flex_charts(T_STORY)[0]["rows"] == 7
    assert api.flex_charts("00000000-0000-4000-8000-000000000000") == []
    assert [m["name"] for m in api.flex_chart_markers()] == ["Topic", "Focus", "New", "Given"]
    api._flex.close()
    api._flex.backend = None
    off = api.flex_get("chart", CHART, 3, 3)
    assert off["cached"] and [r["label"] for r in off["rows"]] == ["2a"]
    assert api.flex_charts()[0]["cached"] and api.flex_chart_markers()[1]["abbr"] == "Foc"


def test_a_note_quoting_a_chart_is_found_by_its_words_and_markers(tmp_path):
    api = _api(tmp_path)
    n = api.create_note(None, "", "Charted", "{{flex:chart " + CHART + " rows=1-2}}\n")
    api.flex_get("chart", CHART, 1, 2)          # the snapshot exists now; the note is re-indexed
    hits = api.search("Haŋa")
    assert [h["id"] for h in hits] == [n["id"]]
    assert any(h["id"] == n["id"] for h in api.search("marker:New"))
    assert parse_query("marker:Given_now")["terms"] == ["⚐Given_now"]
    st = model.searchable_text(api.flex_get("chart", CHART))
    assert "Story chart" in st and "Subject" in st and "⚐New" in st and "Locative" in st


def test_the_cli_dump_writes_the_demo_chart(tmp_path):
    from flex_scratchpad.__main__ import main
    out = tmp_path / "charts.json"
    assert main(["--demo", "--dump-charts", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["charts"][0]["rows"] == 7 and rep["chart"]["rows"][3]["cells"][0]["kind"] == "clause"


def test_lcm_reads_charts_behind_the_guard_and_never_writes():
    src = Path("flex_scratchpad/flex/lcm.py").read_text(encoding="utf-8")
    for attr in ("BeginAnalysisIndex", "EndAnalysisIndex", "ClauseType", "EndParagraph", "EndSentence", "MergesAfter", "DependentClausesRS", "WordGroupRA", "Preposed", "TagRA", "ChartMarkersOA"):
        assert attr in src, attr
    for line in src.splitlines():
        if "RowsOS" in line or "CellsOS" in line:
            assert "_t(" in line or line.strip().startswith("#"), line      # every chart access is guarded


def test_a_chart_exports_as_flex_discourse_xml_and_as_json(tmp_path):
    import xml.etree.ElementTree as ET
    api = _api(tmp_path)
    out = api.export_chart(CHART, "xml", [1, 4], path=str(tmp_path / "c.xml"))
    doc = ET.parse(out).getroot()
    assert doc.tag == "document" and doc.find("chart").get("guid") == CHART and doc.find("chart").get("text") == T_STORY
    rows = doc.findall("chart/row")
    assert [r.get("type") for r in rows] == ["title1", "title2", "normal", "normal", "speech", "normal"]
    assert [r.get("id") for r in rows[2:]] == ["1a", "1b", "2a", "2b"] and rows[3].get("endPara") == "true" and rows[2].get("endSent") == "true"
    # the header rows: a group spans its columns, the column names follow
    assert [c.get("cols") for c in rows[0].findall("cell")] == ["1", "2", "3", "2"]
    assert [c.findtext("main/lit") for c in rows[1].findall("cell")][1:] == ["Outer", "Inner", "Subject", "Verb", "Object", "Inner", "Outer"]
    # 1a: the row number cell, then the columns; words with glosses; the chart tag as a listRef in brackets
    cells = rows[2].findall("cell")
    assert cells[0].findtext("main/rownum") == "1a"
    assert [w.text for w in cells[4].findall("main/word")] == ["ka-nuwa-mo", "lo"] and [g.text for g in cells[4].findall("glosses/gloss")] == ["slept", "DECL"]
    assert cells[6].findtext("main/listRef") == "new" and [x.text for x in cells[6].findall("main/lit")] == ["[", "]"]
    # 1b: a preposed moved-text marker naming its word group; its words are marked moved
    c1b = rows[3].findall("cell")
    assert c1b[7].findtext("main/moveMkr") == "Preposed" and c1b[7].find("main/moveMkr").get("target") == c1b[1].get("guid")
    assert c1b[1].find("main/word").get("moved") == "true"
    # 2b: the clause marker
    assert rows[5].findall("cell")[1].find("main/clauseMkr").get("target") == "2a"
    assert doc.find("languages/language").get("vernacular") == "true" and doc.find("languages/language").get("font") == "Charis SIL"
    js = json.loads((tmp_path / "c.json").read_text(encoding="utf-8")) if api.export_chart(CHART, "json", None, path=str(tmp_path / "c.json")) else None
    assert js["format"] == "flex-scratchpad-chart/1" and js["rowCount"] == 7 and js["rows"][1]["cells"][4]["kind"] == "moved"
