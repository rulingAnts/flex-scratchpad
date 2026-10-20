"""Doubled morph bundles (Seth, 2026-10-19: "budu budu" with "*** ***" under it): FieldWorks'
interlinear importer gives a glossed word with no <morphemes> one bundle holding the word's form
per GLOSS LANGUAGE, on the same analysis. `model.doubled_bundles` recognises the shape and
`--doubled-morphs` lists every such analysis with its uses (read-only)."""
from flex_scratchpad.__main__ import print_doubled
from flex_scratchpad.flex.model import doubled_bundles


def b(form, **kw):
    return {"guid": kw.get("guid", form), "forms": {"fau": form}, "sense": kw.get("sense", ""), "msa": kw.get("msa", ""), "morph": kw.get("morph", "")}


def test_identical_unlinked_bundles_are_found_and_linked_ones_are_not():
    assert doubled_bundles([b("budu", guid="a"), b("budu", guid="b")]) == [[0, 1]]
    assert doubled_bundles([b("budu"), b("budu"), b("budu")]) == [[0, 1, 2]]
    assert doubled_bundles([b("ka-"), b("nuwa"), b("-mo")]) == []                 # a real analysis
    assert doubled_bundles([b("budu", sense="s1"), b("budu", sense="s1")]) == []  # linked: not the importer's shape
    assert doubled_bundles([b("budu"), b("budu", sense="s1")]) == []
    assert doubled_bundles([b("budu")]) == []
    assert doubled_bundles([{"guid": "x", "forms": {}}, {"guid": "y", "forms": {}}]) == []   # empty forms are not "the same form"
    # two languages' forms must both agree
    assert doubled_bundles([{"guid": "x", "forms": {"fau": "budu", "fau-fonipa": "bu"}}, {"guid": "y", "forms": {"fau": "budu"}}]) == []


def test_the_terminal_listing(capsys):
    print_doubled({"texts": ["Tosokai"], "wordformsChecked": 0, "analysesChecked": 3, "textsHit": {"Tosokai": 2},
                   "analyses": [{"wordform": "budu", "bundles": ["budu", "budu"], "extra": 1, "looksLikeBaseline": True,
                                 "uses": [{"text": "Tosokai", "line": "11.1"}, {"text": "Tosokai", "line": "12.1"}]},
                                {"wordform": "fa", "bundles": ["fa", "fa"], "extra": 1, "looksLikeBaseline": True, "uses": []},
                                {"wordform": "hodidi", "bundles": ["=ho", "=di", "=di"], "extra": 1, "looksLikeBaseline": False, "uses": []}]})
    out = capsys.readouterr().out
    assert "1 text(s) checked (3 analyses); 3 analyses repeat an unlinked morph bundle, used in 1 text(s)" in out
    assert "- budu: [budu | budu]  1 extra  — Tosokai 11.1, Tosokai 12.1" in out
    assert "- fa: [fa | fa]  1 extra  — not used in any text\n" in out
    assert "- hodidi: [=ho | =di | =di]  1 extra  — not used in any text  ⚠ not the import's shape" in out
