"""A FieldWorks concordance export (CSV) → example lines (Seth, 2026-10-20)."""
import pytest

from flex_scratchpad.flex import concordance
from flex_scratchpad.flex.demo import DemoBackend

CSV = (
    "Ref,Occurrence\r\n"
    "DOG 1.2,Kabir ka-nuwa-mo lo.§ Haŋa tiket ka-sila-mo pemu.\r\n"          # the abbreviation, FLEx's number
    "The dog and the river 2.1,\"“Ɲamú!” ka-sila lo.§ Kabir pemu ka-nuwa lo.\"\r\n"   # the title
    "The dog 3,Tiket ka-nuwa-mo.\r\n"                                       # eight letters of the title; "3" = 3.1
    "DOG 1.2,Kabir ka-nuwa-mo lo.§ Haŋa tiket ka-sila-mo pemu.\r\n"          # the same line again
    "DOG 9.9,Kabir pemu ka-nuwa lo.\r\n"                                    # no such number: found by its baseline
    "Nowhere 1.1,ba tuhwe de kudia te\r\n"                                  # no such text
    "DOG 8.8,xyz nothing here\r\n"                                          # neither
)


def test_parse_reads_ref_and_occurrence():
    rows = concordance.parse(CSV)
    assert [(r["name"], r["label"]) for r in rows][:3] == [("DOG", "1.2"), ("The dog and the river", "2.1"), ("The dog", "3")]
    assert rows[0]["occurrence"].count(concordance.SEG_SEP) == 1
    assert concordance.parse("﻿Ref,Occurrence\naː boɥo 3.1,ohu bia kakoɾide\n")[0]["name"] == "aː boɥo"
    assert concordance.parse("Ref,Occurrence\nno number here,abc\n") == []
    assert concordance.parse("") == []


def test_match_places_rows_in_the_project():
    be = DemoBackend()
    res = concordance.match(concordance.parse(CSV), be.list_texts(), be.all_baselines())
    assert res["matched"] == 4 and res["unmatched"] == 2
    rows = res["rows"]
    assert [(r["label"], r["how"], r["hits"]) for r in rows] == [("1.2", "number", 2), ("2.1", "number", 1), ("3.1", "number", 1), ("2.2", "text", 1)]
    assert all(r["text"] == be.list_texts()[0]["guid"] for r in rows)
    assert all(len(r["at"]) == 2 and len(r["at"][0]) == 12 for r in rows)
    assert [m["ref"] for m in res["misses"]] == ["Nowhere 1.1", "DOG 8.8"]
    assert "no text named" in res["misses"][0]["why"] and "no line 8.8" in res["misses"][1]["why"]
    assert res["texts"] == ["The dog and the river"]


def test_an_edited_baseline_keeps_flexs_number():
    """The occurrence is the whole paragraph: when 2.1's baseline no longer matches, the other piece
    (2.2's line) must not pull the row onto 2.2 — the number wins, marked as unchecked."""
    be = DemoBackend()
    csv = "Ref,Occurrence\nDOG 2.1,\"Something else now.§ Kabir pemu ka-nuwa lo.\"\n"
    res = concordance.match(concordance.parse(csv), be.list_texts(), be.all_baselines())
    assert [(r["label"], r["how"]) for r in res["rows"]] == [("2.1", "number?")]


def test_norm_ignores_marks_punctuation_and_spacing():
    assert concordance.norm("“Ɲamú!” ka-sila  lo.") == "ɲamu kasila lo"   # break characters go too: ka-sila, ka sila and kasila are one baseline word
    assert concordance.pieces("a b§ c d§ ") == ["a b", "c d"]


def test_api_preview_and_collection(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    pre = api.concordance_preview({"text": CSV})
    assert pre["matched"] == 4 and pre["total"] == 7
    n = api.create_concordance_collection(None, "", "kudia te", {"text": CSV}, {"note": True})
    assert n["kind"] == "examples" and n["matched"] == 4
    body = n["body"]
    assert body.count("{{flex:text ") == 4 and " at=" in body and "seg=2" in body
    assert "> DOG 1.2 (×2)" in body and "Not found in the project: Nowhere 1.1" in body
    with pytest.raises(RuntimeError):
        api.concordance_preview({"text": "nothing"})
    p = tmp_path / "c.csv"
    p.write_bytes(b"\xef\xbb\xbf" + CSV.encode("utf-8"))
    assert api.concordance_preview({"path": str(p)})["matched"] == 4
