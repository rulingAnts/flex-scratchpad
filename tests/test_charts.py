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


def test_a_chart_note_is_a_kind_of_note_with_its_chart_in_the_front_matter(tmp_path):
    api = _api(tmp_path)
    n = api.create_chart_note(None, "", "", CHART)
    assert n["kind"] == "chart" and n["chart"] == CHART and n["title"] == "Story chart — The dog and the river"
    assert n["body"] == "{{flex:chart " + CHART + "}}\n"
    text = Path(n["path"]).read_text(encoding="utf-8")
    assert "kind: chart" in text and "chart: " + CHART in text
    # the view carried over from an embed keeps its settings; a wrong GUID is refused
    v = api.create_chart_note(None, "", "Mine", CHART, "{{flex:chart " + CHART + " rows=1-2 free=col}}")
    assert v["body"].startswith("{{flex:chart " + CHART + " rows=1-2 free=col}}")
    import pytest
    with pytest.raises(RuntimeError):
        api.create_chart_note(None, "", "", "00000000-0000-4000-8000-000000000000")
    with pytest.raises(ValueError):
        api.create_note(None, "", "x", "", "chart", chart="nope")
    # the kind survives a rescan, a duplicate keeps the chart, an ordinary note has no chart key
    api.rescan()
    again = api.get_note(n["id"])
    assert again["kind"] == "chart" and again["chart"] == CHART
    d = api.duplicate_note(n["id"])
    assert d["kind"] == "chart" and d["chart"] == CHART
    plain = api.create_note(None, "", "Plain", "hello")
    assert "chart:" not in Path(plain["path"]).read_text(encoding="utf-8")
    # the project-wide choice lists
    assert api.chart_lists() == {}
    lists = api.set_chart_list("Information status", ["new", "given", "", "given"], True)
    assert lists == {"Information status": {"options": ["new", "given"], "open": True}}
    api.set_chart_list("Information status", None, False)
    assert api.chart_lists()["Information status"]["open"] is False
    api.set_chart_list("Information status", rename="Info")
    assert list(api.chart_lists()) == ["Info"]
    api.set_chart_list("Info")
    assert api.chart_lists() == {}
    assert json.loads((tmp_path / "nb" / "notebook.json").read_text(encoding="utf-8")).get("chartLists") == {}


def test_chart_search_by_words_columns_markers_and_more(tmp_path):
    api = _api(tmp_path)
    labels = lambda rows: [r["label"] for r in rows]  # noqa: E731
    assert labels(api.chart_search("kabir")) == ["1a", "2c", "3b"]
    assert labels(api.chart_search("col:Subject lex:kabir")) == ["1a", "2c", "3b"]
    assert labels(api.chart_search("col:Verb kabir")) == []
    hit = api.chart_search("col:Verb -mo")[0]
    assert hit["label"] == "1a" and hit["hits"] == [4]
    assert labels(api.chart_search("marker:new")) == ["1a"] and labels(api.chart_search("marker:Reference")) == ["1a", "2c"]
    assert labels(api.chart_search("marker:*")) == ["1a", "2c"] and labels(api.chart_search("-marker:*")) == ["1b", "2a", "2b", "3a", "3b"]
    assert labels(api.chart_search("clause:speech")) == ["2a"] and labels(api.chart_search("moved")) == ["1b"] and labels(api.chart_search("moved:postposed")) == []
    assert labels(api.chart_search("clauseref")) == ["2b"] and labels(api.chart_search("endpara")) == ["1b", "2c", "3b"]
    assert labels(api.chart_search("gloss:river")) == ["1b", "2c"] and labels(api.chart_search("col:Postnuclear/Inner gloss:river")) == ["2c"]
    assert labels(api.chart_search("col:c1")) == ["1b"] and labels(api.chart_search("col:Pre-O")) == ["1b"]
    assert labels(api.chart_search("pos:adv")) == ["1b"] and labels(api.chart_search("lex:sila")) == ["1b", "2b"]
    assert labels(api.chart_search("note:locative")) == ["2c"] and labels(api.chart_search("locative")) == ["2c"]
    assert labels(api.chart_search('"ka-sila"')) == ["1b", "2b"] and labels(api.chart_search("row:2b")) == ["2b"]
    assert labels(api.chart_search("chart:story text:dog template:default")) and labels(api.chart_search("chart:nothing")) == []
    assert [r["label"] for r in api.chart_search("")] == ["1a", "1b", "2a", "2b", "2c", "3a", "3b"]   # everything
    # the profile: where kabir sits
    p = api.chart_profile("kabir")
    assert p["total"] == 3 and p["templates"][0]["name"] == "Default"
    cols = {c["name"]: c["count"] for c in p["templates"][0]["columns"]}
    assert cols == {"Subject": 3}
    assert [r["label"] for r in p["templates"][0]["columns"][0]["rows"]] == ["1a", "2c", "3b"]
    p2 = api.chart_profile("sleep")        # a gloss: ka-nuwa-mo, ka-nuwa, ka-nuwa-mo
    assert p2["total"] == 3 and p2["templates"][0]["columns"][0]["name"] == "Verb"
    assert api.chart_profile("")["total"] == 0


def test_a_chart_collection_from_a_rule_takes_in_new_rows(tmp_path):
    from flex_scratchpad.notebook import example_keys, match_embed, match_keys, clean_rule
    api = _api(tmp_path)
    assert clean_rule({"charts": " col:Subject "}) == {"charts": "col:Subject"}
    assert clean_rule({"charts": ""}) is None
    n = api.create_rule_collection(None, "", "Subjects", {"charts": "col:Subject"})
    assert n["kind"] == "examples" and n["rule"] == {"charts": "col:Subject"} and n["matched"] == 5
    body = n["body"]
    assert body.count("{{flex:chart " + CHART + " rows=") == 5 and " rows=1 at=" in body
    assert [x for x in api.list_notes() if x["id"] == n["id"]][0]["exampleCount"] == 5
    assert "rule-charts: col:Subject" in Path(n["path"]).read_text(encoding="utf-8")
    api.rescan()
    assert api.get_note(n["id"])["rule"] == {"charts": "col:Subject"}
    # the same keys from the file and from a match; nothing new the second time
    row = api.chart_search("col:Subject")[0]
    assert match_embed(row).startswith("{{flex:chart " + CHART + " rows=1 at=") and set(match_keys(row)) <= example_keys(body)
    r = api.update_rule_collection(n["id"])
    assert r["added"] == [] and r["matched"] == 5
    # a wider rule finds the rest
    api.set_note_rule(n["id"], {"charts": ""})
    assert api.get_note(n["id"])["rule"] is None
    api.set_note_rule(n["id"], {"charts": "-marker:nothing"})
    r = api.update_rule_collection(n["id"])
    assert len(r["added"]) == 2 and r["total"] == 7


def test_a_text_knows_its_chart_spans_and_a_chart_its_text_tags(tmp_path):
    api = _api(tmp_path)
    t = api.flex_get("text", T_STORY, 1, 2)
    spans = t["chartSpans"]
    assert spans and spans[0]["chart"] == CHART and spans[0]["chartName"] == "Story chart"
    first = [s for s in spans if s["row"] == "1a"]
    assert [s["column"]["name"] for s in first] == ["Subject", "Verb"] and first[1]["from"] == {"seg": 1, "w": 1} and first[1]["to"] == {"seg": 1, "w": 2}
    assert first[0]["column"]["path"] == ["Nucleus"]
    # offline: from the snapshots
    api._flex.close()
    api._flex.backend = None
    off = api.flex_get("text", T_STORY, 1, 2)
    assert off["cached"] and len(off["chartSpans"]) == len(spans)
    c = api.flex_get("chart", CHART)
    assert [tg["tag"]["name"] for tg in c["tags"]][:3] == ["Subject", "Verb", "Focus"]


def test_dump_charts_picks_a_chart_with_rows_that_matches_every_word():
    from flex_scratchpad.flex.lcm import pick_chart
    # Seth's project (2026-10-18): five nameless charts on "Siakai", the first two empty
    charts = [
        {"guid": "28d8", "name": "", "title": "Siakai", "rows": 0, "template": "Grammatical Relation Tracking"},
        {"guid": "4c24", "name": "", "title": "Siakai", "rows": 0, "template": "Clause-Chain Analysis"},
        {"guid": "7db4", "name": "", "title": "Siakai", "rows": 72, "template": "Default"},
        {"guid": "97e1", "name": "", "title": "Siakai", "rows": 58, "template": "SVC Analysis"},
        {"guid": "00d4", "name": "", "title": "Advice for a Fayu Husband", "rows": 9, "template": "Default"},
    ]
    assert pick_chart(charts, "Siakai") == 2            # the chart with most rows, never an empty one
    assert pick_chart(charts, "siakai svc") == 3        # every word: the title and the template
    assert pick_chart(charts, "97e1") == 3              # a GUID (prefix) works too
    assert pick_chart(charts, "") == 2                  # no filter: the fullest chart
    assert pick_chart(charts, "Clause-Chain") == 1      # an empty chart when only empty ones match
    assert pick_chart(charts, "nothing like it") is None
    assert pick_chart([], "") is None
