"""The FLEx layer without FieldWorks: model + links, the .flextext fallback, the demo backend,
the snapshot cache, audio clips, and the service's live-then-cached behaviour."""
import wave
from pathlib import Path

import pytest

from conftest import FIXTURES
from flex_scratchpad.flex import FlexService, model
from flex_scratchpad.flex.audio import cut_clip
from flex_scratchpad.flex.cache import SnapshotCache
from flex_scratchpad.flex.demo import DemoBackend, T_STORY, T_ARAB, E, write_demo_wav
from flex_scratchpad.flex.flextext import FlextextBackend, FlextextFile
from flex_scratchpad.flex.lcm import FlexError, _friendly
from flex_scratchpad.notebook import Notebook


def test_goto_url_and_parse():
    url = model.goto_url("My Project", "entry", "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001")
    assert url == "silfw://localhost/link?app=flex&server=&database=My%20Project&tool=lexiconEdit&guid=6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001"
    assert model.goto_url("p", "text", "x").endswith("tool=interlinearEdit&guid=x")
    info = model.parse_silfw("silfw://localhost/link?app=flex&server=&database=Kalu&tool=interlinearEdit&guid=9B1C2D3E-4F50-4A6B-8C7D-0E1F2A3B0001&tag=")
    assert info == {"database": "Kalu", "tool": "interlinearEdit", "guid": "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001", "tag": ""}
    # the form FLEx itself puts on the clipboard: the query percent-encoded as a whole
    enc = model.parse_silfw("silfw://localhost/link?database%3dfau-iya-flex%26tool%3dinterlinearEdit%26guid%3d59be473f-e42a-4fb6-9b57-a866a66ae7dc%26tag%3d")
    assert enc == {"database": "fau-iya-flex", "tool": "interlinearEdit", "guid": "59be473f-e42a-4fb6-9b57-a866a66ae7dc", "tag": ""}
    assert model.parse_silfw("https://example.org") is None
    assert model.parse_silfw("silfw://localhost/link?app=flex&guid=nope") is None


def test_tokenize_and_baseline():
    toks = model.tokenize("“Ɲamú!” ka-sila lo.")
    assert [t["txt"] for t in toks] == ["“", "Ɲamú", "!”", "ka-sila", "lo", "."]
    assert [t["punct"] for t in toks] == [True, False, True, False, False, True]
    assert model.baseline_from_words(toks) == "“Ɲamú!” ka-sila lo."


def test_flextext_parse(tmp_path):
    f = FlextextFile(FIXTURES / "sample.flextext")
    assert f.vern_lang == "kal" and f.anal_lang == "en"
    assert len(f.texts) == 1
    t = f.texts[0]
    assert t["title"] == "Kabir pemu" and t["abbrev"] == "KP" and t["segmentCount"] == 3
    assert t["ws"]["vern"]["font"] == "Charis SIL"
    s1 = t["segments"][0]
    assert s1["n"] == 1 and s1["para"] == 1 and s1["baseline"] == "Kabir ka-nuwa-mo lo."
    # FLEx's own numbering: paragraph.segment, as the Gloss / Print views show it
    assert [(s["n"], s["label"]) for s in t["segments"]] == [(1, "1.1"), (2, "1.2"), (3, "2.1")]
    assert s1["free"] == "The dog slept." and s1["notes"] == ["First sentence."]
    assert s1["begin"] == 0 and s1["end"] == 1200 and s1["media"] == "cccccccc-0000-4000-8000-000000000001"
    w = s1["words"][1]
    assert w["txt"] == "ka-nuwa-mo" and w["gls"] == "slept" and w["pos"] == "v"
    assert [m["form"] for m in w["morphs"]] == ["ka-", "nuwa", "-mo"]
    assert [m["gls"] for m in w["morphs"]] == ["3SG-", "sleep", "-PST"]      # glosses wear the break characters
    assert s1["words"][3]["punct"] is True
    s2 = t["segments"][1]
    assert s2["lit"] == "Child DECL." and s2["para"] == 1
    s3 = t["segments"][2]
    assert s3["para"] == 2 and s3["free"] == "Free translation before the words."
    assert s3["baseline"] == "pemu lo"            # reconstructed: no txt item, morphemes-only word
    assert t["media"][0]["found"] is False and t["media"][0]["uri"].endswith("sample.wav")


def test_flextext_media_resolution_by_basename(tmp_path):
    media = tmp_path / "audio" / "deep"
    media.mkdir(parents=True)
    write_demo_wav(media / "sample.wav", seconds=0.2)
    f = FlextextFile(FIXTURES / "sample.flextext", media_folders=[str(tmp_path / "audio")])
    m = f.texts[0]["media"][0]
    assert m["found"] and m["path"].endswith("sample.wav") and m["fileUrl"].startswith("file://")


def test_flextext_backend_pages_and_resolves():
    be = FlextextBackend(str(FIXTURES / "sample.flextext"))
    assert be.status()["texts"] == 1 and be.list_texts()[0]["segmentCount"] == 3
    page = be.get_text("11111111-2222-4333-8444-555555555555", 2, 3)
    assert [s["n"] for s in page["segments"]] == [2, 3] and page["range"] == [2, 3] and page["segmentCount"] == 3
    assert be.resolve_guid("BBBBBBBB-0000-4000-8000-000000000002") == {"kind": "text", "guid": "11111111-2222-4333-8444-555555555555", "title": "Kabir pemu", "seg": 2}
    assert be.search_entries("x") == []
    with pytest.raises(KeyError):
        be.get_entry("11111111-2222-4333-8444-555555555555")


def test_demo_backend(tmp_path):
    be = DemoBackend(media_dir=tmp_path)
    assert (tmp_path / "AudioVisual" / "kalu-story.wav").exists()
    assert be.get_text(T_STORY)["media"][0]["found"]
    assert be.get_text(T_ARAB)["ws"]["vern"]["rtl"] is True
    hits = be.search_entries("ka")
    assert [h["headword"] for h in hits] == ["kabir", "ka-"]
    e = be.get_entry(E["kabir"])
    assert len(e["senses"]) == 3 and e["senses"][0]["examples"][0]["translation"] == "the dog is sleeping"
    assert [(s["number"], s["level"], s["parent"]) for s in e["senses"]] == [("1", 0, ""), ("2", 0, ""), ("2.1", 1, "2")]
    assert e["senses"][0]["note"] == "Also used of puppies." and e["senses"][0]["domains"] == ["1.6.1.1.2 Carnivore"]
    senses = {s["guid"] for en in [be.get_entry(g) for g in E.values()] for s in en["senses"]}
    assert len(senses) == sum(len(be.get_entry(g)["senses"]) for g in E.values())   # sense guids are unique
    assert be.resolve_guid(e["senses"][1]["guid"])["sense"] == "2"
    assert be.get_text(T_STORY, 1, None, max_segments=2)["range"] == [1, 2]


def test_cache_merges_text_pages(tmp_path):
    c = SnapshotCache(tmp_path)
    be = DemoBackend()
    c.merge_text("P", T_STORY, be.get_text(T_STORY, 1, 2))
    c.merge_text("P", T_STORY, be.get_text(T_STORY, 5, 6))
    snap = c.get("P", "text", T_STORY)
    assert [s["n"] for s in snap["segments"]] == [1, 2, 5, 6] and snap["cached"] is True and snap["cachedAt"]
    assert c.find("text", T_STORY)["title"] == "The dog and the river"
    assert c.get("P", "entry", "nope") is None


def test_cut_wav_clip(tmp_path):
    src = write_demo_wav(tmp_path / "a.wav", seconds=2.0, rate=8000)
    dst = tmp_path / "clip.wav"
    # the stdlib cutter: an exact WAV slice
    assert cut_clip(src, dst, 500, 1250, ffmpeg=None) == dst or cut_clip(src, dst, 500, 1250) is not None
    from flex_scratchpad.flex import audio as _audio
    out = _audio.cut_wav(src, dst, 500, 1250)
    with wave.open(str(out)) as w:
        assert w.getnframes() == 6000 and w.getframerate() == 8000
    assert cut_clip(src, tmp_path / "x.wav", 900, 900) is None
    # with ffmpeg on the machine, cut_clip prefers a FLAC slice of the right length
    import shutil, subprocess, json
    exe = shutil.which("ffmpeg")
    if exe:
        out = cut_clip(src, tmp_path / "clip2.wav", 500, 1250, ffmpeg=exe)
        assert out and out.suffix == ".flac"
        probe = shutil.which("ffprobe")
        if probe:
            d = float(subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(out)], capture_output=True, text=True).stdout and json.loads(subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(out)], capture_output=True, text=True).stdout)["format"]["duration"])
            assert 0.7 <= d <= 0.8, d


def test_service_live_then_cached(tmp_path):
    nb = Notebook(tmp_path)
    svc = FlexService(nb)
    svc.configure(source="demo", project="Kalu Demo")
    st = svc.open()
    assert st["open"] and st["backend"] == "demo"
    live = svc.get_object("text", T_STORY, 1, 2)
    assert live["cached"] is False and len(live["segments"]) == 2
    entry = svc.get_object("sense", E["kabir"])
    assert entry["kind"] == "entry" and entry["cached"] is False
    # searchable text for the index comes from the snapshots
    body = "x {{flex:text %s seg=1-2}} y [k](flex:entry/%s)" % (T_STORY, E["kabir"])
    txt = svc.searchable_text_for_body(body)
    assert "Kabir" in txt and "slept" in txt and "domestic dog" in txt
    # link resolution
    r = svc.resolve_link("silfw://localhost/link?app=flex&server=&database=Kalu%20Demo&tool=lexiconEdit&guid=" + E["tiket"] + "&tag=")
    assert r["kind"] == "entry" and r["title"] == "tiket" and r["database"] == "Kalu Demo"
    assert svc.resolve_link("not a link") is None
    # find by text
    assert svc.find_in_text(T_STORY, "kabir") == [1, 4, 6]
    assert svc.find_in_text(T_STORY, "the child saw") == [2]
    # audio clip is cut into the cache
    clip = svc.ensure_clip(T_STORY, None, 1500, 3200)
    assert clip["found"] and Path(clip["clipPath"]).exists() and clip["needsCapture"] is False
    # close the source: snapshots keep the note readable
    svc.close()
    cached = svc.get_object("text", T_STORY, 2, 2)
    assert cached["cached"] is True and [s["n"] for s in cached["segments"]] == [2] and cached["liveError"]
    assert svc.get_object("entry", E["kabir"])["cached"] is True
    with pytest.raises(FlexError):
        svc.get_object("entry", E["pemu"])          # never fetched, never cached


def test_media_browse_mapping_persists(tmp_path):
    nb = Notebook(tmp_path)
    svc = FlexService(nb)
    svc.configure(source="demo")
    svc.open()
    wav = write_demo_wav(tmp_path / "elsewhere" / "real.wav", seconds=0.3)
    svc.set_media_path("c0ffee00-0000-4000-8000-00000000a001", str(wav))
    nb2 = Notebook(tmp_path)
    assert nb2.config["media"]["byGuid"]["c0ffee00-0000-4000-8000-00000000a001"] == str(wav)
    assert str(wav.parent) in nb2.config["media"]["folders"]
    assert svc.get_object("text", T_STORY, 1, 1)["media"][0]["path"] == str(wav)


def test_friendly_errors():
    class FP_FileLockedError(Exception):
        pass
    e = _friendly(FP_FileLockedError("locked"), "Proj")
    assert e.code == "locked" and "Sharing" in e.message
    assert _friendly(ImportError("no module named clr")).code == "no-flexicon"


def test_lcm_module_imports_without_flexicon():
    """The LCM backend must be importable (and fail politely) on machines without FieldWorks."""
    from flex_scratchpad.flex.lcm import FlexiconBackend
    be = FlexiconBackend()
    try:
        with pytest.raises(FlexError) as ei:
            be.list_projects()
        assert ei.value.code in ("no-flexicon", "lcm")
    finally:
        be.close()


def test_locate_pasted_interlinear_lines(tmp_path):
    nb = Notebook(tmp_path)
    svc = FlexService(nb)
    svc.configure(source="demo")
    svc.open()
    # FLEx-style rows with labels and tabs: only the Word / Free rows are used for matching
    pasted = "Word\tHaŋa\ttiket\tka-sila-mo\tpemu\nMorphemes\thaŋa\ttiket\tka- sila -mo\tpemu\nLex. Gloss\tyesterday\tchild\t3SG see PST\triver\nFree\tYesterday the child saw the river."
    hits = svc.locate(pasted)
    assert hits and hits[0]["guid"] == T_STORY and hits[0]["seg"] == 2 and hits[0]["segTo"] == 2 and hits[0]["score"] >= 3
    # two bare baseline lines → consecutive segments; diacritics-insensitive, case-insensitive
    hits = svc.locate("HAŊA tiket ka-sila-mo pemu.\n\u201cɲamu!\u201d ka-sila lo.")   # case, marks and punctuation ignored (ŋ/ɲ are letters)
    assert hits[0]["seg"] == 2 and hits[0]["segTo"] == 3 and hits[0]["matched"] == 2
    # a fragment inside a baseline, and the Arabic-script text
    assert svc.locate("tiket ka-sila")[0]["seg"] == 2
    assert svc.locate("\u0631\u0623\u0649 \u0627\u0644\u0648\u0644\u062f")[0]["guid"] == T_ARAB
    # prose that is nowhere in the project
    assert svc.locate("completely unrelated sentence here") == []
    assert svc.locate("") == []


def test_flex_numbering_is_paragraph_dot_segment(tmp_path):
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    t = api.flex_get("text", "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001")
    labels = [(s["n"], s["para"], s["label"]) for s in t["segments"]]
    assert labels[0] == (1, 1, "1.1") and all(lab == f"{p}.{k}" for (_, p, lab), k in zip(labels, [1, 2, 1, 2, 1, 2]))
    page = api.flex_get("text", "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001", 3, 4)
    assert [s["label"] for s in page["segments"]] == ["2.1", "2.2"]      # a range keeps FLEx's numbers


def test_morph_break_characters_follow_the_form():
    assert model.morph_markers("-mo") == ("-", "") and model.morph_markers("ka-") == ("", "-")
    assert model.morph_markers("=lo") == ("=", "") and model.morph_markers("<in>") == ("<", ">") and model.morph_markers("nuwa") == ("", "")
    assert model.morph_markers("-") == ("-", "")                      # a bare hyphen is not a postfix too
    m = model.make_morph("-mo", "PST", "suffix", "-mo")
    assert (m["form"], m["gls"], m["cf"]) == ("-mo", "-PST", "-mo")
    m = model.make_morph("mo", "PST", "suffix", "-mo")                 # markers only on the headword → still applied
    assert (m["form"], m["gls"]) == ("-mo", "-PST")
    m = model.make_morph("a", "lnk", "", "", prefix="-", postfix="")   # markers from the morph type
    assert (m["form"], m["gls"]) == ("-a", "-lnk")
    m = model.make_morph("ka-", "3SG-", "", "ka-")                     # never doubled
    assert m["gls"] == "3SG-"


def test_anchored_ranges_follow_renumbered_segments(tmp_path):
    """An embed's seg= is a running count; its at= anchors are segment GUIDs. When a segment
    is inserted above, the range moves with the anchors and the text says so."""
    from flex_scratchpad.flex import FlexService
    from flex_scratchpad.flex.demo import DemoBackend
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    g = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001"
    page = api.flex_get("text", g, 3, 4)
    assert [s["label"] for s in page["segments"]] == ["2.1", "2.2"] and page["rangeMoved"] is False
    anchors = page["anchors"]
    assert len(anchors) == 2 and all(len(a) == 12 for a in anchors)
    assert [e["n"] for e in page["index"]][:3] == [1, 2, 3] and page["index"][2]["label"] == "2.1"
    # FLEx inserts a new segment at the top of the text: everything is renumbered
    t = api._flex._live().texts[g]
    new = dict(t["segments"][0]); new["guid"] = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3bffff"; new["baseline"] = "Inserted."
    t["segments"].insert(0, new)
    for i, s in enumerate(t["segments"], 1):
        s["n"] = i
    page2 = api.flex_get("text", g, 3, 4, False, None, anchors)
    assert page2["rangeMoved"] is True and page2["range"] == [4, 5]
    assert [s["baseline"] for s in page2["segments"]] == [s["baseline"] for s in page["segments"]]
    # a lost anchor keeps the numbers and says so
    page3 = api.flex_get("text", g, 3, 4, False, None, ["00000000", "00000000"])
    assert page3["anchorsLost"] is True and page3["range"] == [3, 4]
    # the snapshot resolves anchors offline too
    api._flex.close()
    cached = api._flex.get_object("text", g, 3, 4, prefer_cache=True, at=anchors)
    assert cached["cached"] is True and cached["range"] == [4, 5]


def test_locate_numbered_blocks_from_flex_print_view(tmp_path):
    """Copied from FLEx's Gloss / Print view: each segment leads with its number, rows are
    labelled, the Word row ends with §. A range must match as a range."""
    from flex_scratchpad.api import Api
    from flex_scratchpad.config import AppConfig
    api = Api(AppConfig(tmp_path / "cfg.json"), notebook_dir=tmp_path / "nb", demo=True)
    svc = api._flex
    pasted = ("1.1\tWord\tKabir\tka-nuwa-mo\tlo\t§\n"
              "\tLex. Gloss\tdog\t3SG- sleep -PST\tDECL\n"
              "Free\tThe dog slept.\n"
              "1.2\tWord\tHaŋa\ttiket\tka-sila-mo\tpemu\t§\n"
              "\tLex. Gloss\tyesterday\tchild\t3SG- see -PST\triver\n"
              "Free\tYesterday the child saw the river.\n"
              "2.1 Word\tƝamú\tka-sila\tlo\n"
              "Free\t“Mother!” he sees.\n")
    hits = svc.locate(pasted)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 3 and hits[0]["matched"] == 3 and hits[0]["of"] == 3, hits


def test_locate_rows_without_a_word_row(tmp_path):
    """Seth, 2026-10-13: Morphemes + Lex. Gloss + Free copied from FLEx pasted as plain TSV.
    The Lex. Gloss row leads with an EMPTY cell, the Free line is "Free" + space with bidi
    marks (U+200E) instead of a tab, and there is no Word row — the joined morphemes have to
    stand in for the baseline."""
    nb = Notebook(tmp_path)
    svc = FlexService(nb)
    svc.configure(source="demo")
    svc.open()
    pasted = ("1.1\tMorphemes\tKabir\tka-\tnuwa\t-mo\tlo\t\t\n"
              "\tLex. Gloss\tdog\t3SG-\tsleep\t-PST\tDECL\n"
              "\u200eFree \u200e\u200eThe dog slept.\n")
    hits = svc.locate(pasted)
    assert hits and hits[0]["guid"] == T_STORY and hits[0]["seg"] == 1 and hits[0]["segTo"] == 1 and hits[0]["score"] >= 4, hits
    # two such blocks in a row locate as a range; the free line alone never starts a new block
    two = pasted + "1.2\tMorphemes\tHaŋa\ttiket\tka-\tsila\t-mo\tpemu\n\tLex. Gloss\tyesterday\tchild\t3SG-\tsee\t-PST\triver\nFree Yesterday the child saw the river.\n"
    hits = svc.locate(two)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 2 and hits[0]["matched"] == 2 and hits[0]["of"] == 2, hits
    # the Print tab's shape (Seth's exact paste, 2026-10-13): Word row, empty Word Gloss row,
    # "Free Eng …" with bidi marks, and a bare "Ind" line for the second analysis language
    print_tab = ("1.1\tWord\tKabir\tka-nuwa-mo\tlo\t\t\n"
                 "\tLex. Gloss\tdog\t3SG-\tsleep\t-PST\tDECL\n"
                 "\tWord Gloss\t\t\t\t\t\n"
                 "\u200eFree \u200eEng\u200e \u200e\u200eThe dog slept.\n"
                 "\u200e \u200eInd\u200e \u200e\u200e\n")
    hits = svc.locate(print_tab)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 1 and hits[0]["of"] == 1, hits
    hits = svc.locate(print_tab + print_tab.replace("1.1", "1.2").replace("Kabir\tka-nuwa-mo\tlo", "Haŋa\ttiket\tka-sila-mo\tpemu").replace("The dog slept.", "Yesterday the child saw the river."))
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 2 and hits[0]["matched"] == 2 and hits[0]["of"] == 2, hits
    # the Gloss tab with several analysis / vernacular writing systems showing: labels carry
    # the writing system ("Word base" / "Word fau-ose"), the second Word row is the SAME
    # segment in another spelling, and Lex. Entries / Lex. Gram. Info. / Word Gloss rows ride along
    gloss_tab = ("1.1\tWord base\tKabir\tka-nuwa-mo\tlo\t\t\n"
                 "\tWord fau-ose\tQabir\tqa-nuwa-mo\tlo\t\t\n"
                 "\tMorphemes base\tKabir\tka-\tnuwa\t-mo\tlo\n"
                 "\tMorphemes fau-ose\tQabir\tqa-\tnuwa\t-mo\tlo\n"
                 "\tLex. Entries base\tkabir\tka-\tnuwa\t-mo\tlo\n"
                 "\tLex. Entries fau-ose\tqabir\tqa-\tnuwa\t-mo\tlo\n"
                 "\tLex. Gloss\tdog\t3SG-\tsleep\t-PST\tDECL\n"
                 "\tLex. Gram. Info.\tn\tv\tv\t\t\n"
                 "\tWord Gloss Eng\tdog\tsleeps\t\t\n"
                 "\tWord Gloss Ind\t\t\t\t\t\n"
                 "\u200eFree \u200e\u200eThe dog slept.\n")
    hits = svc.locate(gloss_tab)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 1 and hits[0]["of"] == 1 and hits[0]["score"] >= 4, hits
    # the Analyze tab: Word, Morphemes, Lex. Gloss, Word Gloss per language, Word Cat., Free per language
    analyze = ("1.1\tWord\tKabir\tka-nuwa-mo\tlo\t\t\n"
               "\tMorphemes\tKabir\tka-\tnuwa\t-mo\tlo\n"
               "\tLex. Gloss\tdog\t3SG-\tsleep\t-PST\tDECL\n"
               "\tWord Gloss Eng\tdog\tsleeps\t\t\n"
               "\tWord Gloss Ind\t\t\t\t\t\n"
               "\tWord Cat.\tn\tv\t\t\t\n"
               "\u200eFree \u200eEng\u200e \u200e\u200eThe dog slept.\n"
               "\u200e \u200eInd\u200e \u200e\u200e\n")
    assert svc.locate(analyze)[0]["seg"] == 1 and svc.locate(analyze)[0]["of"] == 1
    # the writing-system alternate under the SAME number, in a two-segment range
    two = gloss_tab + gloss_tab.replace("1.1", "1.2").replace("Kabir\tka-nuwa-mo\tlo", "Haŋa\ttiket\tka-sila-mo\tpemu").replace("The dog slept.", "Yesterday the child saw the river.")
    hits = svc.locate(two)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 2 and hits[0]["matched"] == 2 and hits[0]["of"] == 2, hits
    # the Print tab with limited lines (Seth, 2026-10-13): no Word row, a clitic "=mo" in the
    # morphemes, an EMPTY "Free Eng" line and the translation on the "Ind" line under it
    limited = ("1.1\tMorphemes\tKabir\tka-\tnuwa\t=mo\tlo\t\t\n"
               "\tLex. Gloss\t***\t3SG-\tsleep\t-PST\tDECL\n"
               "\tWord Gloss\tanjing\ttidur\t\t\t\n"
               "\u200eFree \u200eEng\u200e \u200e\u200e\n"
               "\u200e \u200eInd\u200e \u200e\u200eAnjing itu tidur.\n")
    hits = svc.locate(limited)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 1 and hits[0]["of"] == 1, hits
    two = limited + limited.replace("1.1", "1.2").replace("Kabir\tka-\tnuwa\t=mo\tlo", "Haŋa\ttiket\tka-\tsila\t=mo\tpemu")
    hits = svc.locate(two)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 2 and hits[0]["matched"] == 2 and hits[0]["of"] == 2, hits
    # a Morphemes row under a Word row changes nothing
    assert svc.locate("Word\tKabir\tka-nuwa-mo\tlo\nMorphemes\tKabir\tka-\tnuwa\t-mo\tlo\nFree\tThe dog slept.")[0]["seg"] == 1


def test_clip_prefers_flac_when_ffmpeg_exists(tmp_path, monkeypatch):
    import shutil
    from flex_scratchpad.flex import audio
    src = tmp_path / "a.wav"
    import wave as _w
    with _w.open(str(src), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\x00\x01" * 8000)
    # no ffmpeg → a WAV slice from the stdlib
    monkeypatch.setattr(audio, "find_ffmpeg", lambda configured="": None)
    out = audio.cut_clip(src, tmp_path / "clip.wav", 100, 300)
    assert out and out.suffix == ".wav"
    # ffmpeg available (if this machine has it) → a FLAC slice
    real = shutil.which("ffmpeg")
    if real:
        monkeypatch.setattr(audio, "find_ffmpeg", lambda configured="": real)
        out = audio.cut_clip(src, tmp_path / "clip2.wav", 100, 300)
        assert out and out.suffix == ".flac" and out.stat().st_size > 0


def test_locate_without_a_word_line_uses_the_segment_s_own_morphemes_and_glosses(tmp_path):
    """Seth, 2026-10-14: morpheme forms need NOT spell the baseline word (an underlying form,
    another writing system). Rows without a Word line are matched against the segment's own
    Morphemes and Lex. Gloss lines, which every backend indexes."""
    nb = Notebook(tmp_path)
    svc = FlexService(nb)
    svc.configure(source="demo")
    svc.open()
    # the demo index carries morphemes and glosses per segment
    idx = svc._live().all_baselines()[T_STORY]["segments"]
    assert idx[0][3].startswith("kabir ka-") and "sleep" in idx[0][4], idx[0]
    # a stand-in text whose morpheme line does not spell the baseline (kuɾi vs kudi)
    svc._live().all_baselines = lambda: {"g1": {"title": "fau", "segments": [
        (1, "ia toduo", "he walked", "ia todu -o", "3SG walk -PST"),
        (2, "nawa kudi", "she caught it", "naw -a kuɾi", "hold lnk take.CMP"),
        (3, "boda ohodode", "", "boda ohodo =de", "ball foot ERG")]}}
    morph_only = "11.5\tMorphemes\tnaw\t-a\tkuɾi\t\t\n\tLex. Gloss\thold\tlnk\t\ttake\t.CMP\n\u200eFree \u200e\u200eshe caught it.\n"
    hits = svc.locate(morph_only)
    assert hits and hits[0]["seg"] == 2 and hits[0]["segTo"] == 2 and hits[0]["score"] >= 5, hits   # morphs 3 + gloss 1 + free 1
    # Lex. Gloss alone (no Word, no Morphemes) still finds it
    assert svc.locate("\tLex. Gloss\thold\tlnk\t\ttake\t.CMP\n")[0]["seg"] == 2
    # a range of morpheme-only blocks
    two = morph_only + "11.6\tMorphemes\tboda\tohodo\t=de\n\tLex. Gloss\tball\tfoot\tERG\n"
    hits = svc.locate(two)
    assert hits and hits[0]["seg"] == 2 and hits[0]["segTo"] == 3 and hits[0]["matched"] == 2, hits


def test_locate_a_range_when_flex_left_segments_out_of_the_copy(tmp_path):
    """Seth, 2026-10-16: a paste of 12.1, 12.3, 13, 14, 15 (FLEx's copy had no 12.2) found only its
    first segment, because the pasted segments were matched to consecutive ones. Now a range may
    skip a few of the text's segments between two of its own."""
    L = "‎"
    rows = [  # (label, Word, Morphemes, Lex. Gloss, Free) as copied from FLEx's Print view
        ("12.1", "ə dʉɥa ka ɸu dʒɥa", "ə dʉɥa ka= ɸu =dʒɥ -a", "eh go.around .CMP put .NFIN canoe stand lnk", "On they went putting (fish) in the canoe."),
        ("12.3", "ɸakau dʒuɭi ataha kuɾiɛtɛ ka ɸu dʒɥa", "ɸakau dʒuɭi ataha kuɾi -ɛ =tɛ ka= ɸu =dʒɥ -a", "type.of.fish thing all take .CMP lnk SEQ put", "fakau fish, all things they caught and put in the boat."),
        ("13", "bɛɾia ɸu dʒʉɥatɛ natɛɾiɛtɛ ɸu ɸia natɛɾi", "bɛɾɛ ɸu =dʒʉ -ɥa =tɛ natɛɾi -ɛ =tɛ ɸu ɸia natɛɾi", "um canoe stand CMP SEQ leave.behind", "Um... put them in the boat and then left the boat tied up."),
        ("14", "ti ka ɸu dʒʉa natɛɾi", "ti ka= ɸu =dʒʉ -a natɛɾi", "fish put .NFIN canoe stand lnk leave.behind .CMP", "(They) left the fish in the canoe."),
    ]

    def paste(labels):
        out = []
        for lab, w, m, g, f in (r for r in rows if r[0] in labels):
            out += [f"{lab}\tWord\t" + "\t".join(w.split()) + "\t", "\tMorphemes\t" + "\t".join(m.split()),
                    "\tLex. Gloss Eng\t" + "\t".join(g.split()), "\tLex. Gloss Ind\t\t\t.NFIN\tperahu\t",
                    "\tWord Gloss Ind\t\t\t", "\tWord Cat. Eng\tn\tv\t",
                    f"{L}Free {L}Eng{L} {L}{L}{f}", f"{L} {L}Ind{L} {L}{L}"]
        return "\n".join(out) + "\n"

    def seg(n, r):
        return (n, r[1], r[4], r[2], r[3])
    gap = ("", "ɛ ɛ", "ɛ ɛ", "eh eh", "A segment the copy left out.")
    segs = [(1, "a b c", "Before.", "a b c", "x y z"), seg(2, rows[0]), seg(3, gap), seg(4, rows[1]),
            seg(5, gap), seg(6, rows[2]), seg(7, rows[3])]

    class Fake:
        kind = "fake"

        def all_baselines(self):
            return {"g1": {"title": "Fish story", "segments": segs}}

    fs = FlexService(Notebook(tmp_path / "nb"))
    fs.backend = Fake()
    for labels, want in ((["12.1", "12.3"], (2, 4)), (["12.3", "13", "14"], (4, 7)), (["12.1", "12.3", "13", "14"], (2, 7))):
        hits = fs.locate(paste(labels))
        assert hits and (hits[0]["seg"], hits[0]["segTo"]) == want and hits[0]["matched"] == hits[0]["of"] == len(labels), (labels, hits[:1])


def test_locate_follows_flexs_own_segment_numbers(tmp_path):
    """Seth, 2026-10-16: the paste "pretty consistently [grabbed] the wrong line (like two lines
    above the one I selected)". A refrain repeated in a story matches by content in several
    places; the number FLEx puts on the pasted rows says which one was copied."""
    refrain = ("ka ɸu dʒɥa", "ka= ɸu =dʒɥ -a", "put canoe stand lnk", "They put it in the canoe.")
    other = ("ti natɛɾi", "ti natɛɾi", "fish leave.behind", "They left the fish.")
    segs = [  # (n, baseline, free, morphs, glosses, FLEx number)
        (1, refrain[0], refrain[3], refrain[1], refrain[2], "10.1"),
        (2, other[0], other[3], other[1], other[2], "10.2"),
        (3, refrain[0], refrain[3], refrain[1], refrain[2], "10.3"),
        (4, other[0], other[3], other[1], other[2], "11"),
        (5, "bɛɾia ɸu", "Um, the canoe.", "bɛɾɛ ɸu", "um canoe", "12.1"),
    ]

    class Fake:
        kind = "fake"

        def all_baselines(self):
            return {"g1": {"title": "Story", "segments": [s[:5] + ((s[5],) if len(s) > 5 else ()) for s in segs]}}

    fs = FlexService(Notebook(tmp_path / "nb"))
    fs.backend = Fake()

    def rows(label, r):
        return f"{label}\tWord\t" + "\t".join(r[0].split()) + f"\n\tMorphemes\t" + "\t".join(r[1].split()) + f"\n‎Free ‎Eng‎ {r[3]}\n"
    # the second copy of the refrain, by its number (content alone found the first, two lines up)
    h = fs.locate(rows("10.3", refrain))
    assert (h[0]["seg"], h[0]["segTo"], h[0].get("byLabel")) == (3, 3, True), h[:2]
    # a range across a segment the copy left out follows the numbers too ("11" is "11.1")
    h = fs.locate(rows("10.3", refrain) + rows("11", other))
    assert (h[0]["seg"], h[0]["segTo"], h[0]["matched"]) == (3, 4, 2), h[:2]
    # a number whose content disagrees (another text numbered alike) is not trusted
    h = fs.locate(rows("12.1", refrain))
    assert not h[0].get("byLabel") and h[0]["seg"] in (1, 3), h[:2]
    # no numbers on the rows: content matching as before
    h = fs.locate("Word\t" + "\t".join(other[0].split()) + "\n")
    assert h[0]["seg"] in (2, 4) and not h[0].get("byLabel")


def test_locate_returns_flex_numbers_and_guid_anchors(tmp_path):
    """The dialog shows FLEx's numbers; the embed gets the segments' GUID anchors (at=)."""
    fs = FlexService(Notebook(tmp_path / "nb"))
    fs.backend = DemoBackend()
    segs = {s["n"]: s for s in fs.backend.texts[T_STORY]["segments"]}
    h = fs.locate("2.2\tWord\tKabir\tpemu\tka-nuwa\tlo\n\tWord\tTiket\tka-nuwa-mo\nFree\tThe child slept.")
    top = h[0]
    assert (top["seg"], top["segTo"], top["label"], top["labelTo"]) == (4, 5, "2.2", "3.1"), top
    assert top["at"] == [model.anchor_of(segs[4]["guid"]), model.anchor_of(segs[5]["guid"])]
    h = fs.locate("Word\tKabir\tlo\nFree\tThe dog.")                 # unnumbered: content, still anchored
    assert h[0]["seg"] == 6 and h[0]["at"] == [model.anchor_of(segs[6]["guid"])] * 2 and h[0]["label"] == "3.2"


def test_locate_report_explains_a_paste(tmp_path):
    """`flex-scratchpad --locate FILE` writes what the locator saw: for diagnosing a paste that
    does not land, against the real project (here the demo)."""
    import json
    from flex_scratchpad.__main__ import main
    paste = tmp_path / "paste.txt"
    paste.write_text("2.2\tWord\tKabir\tpemu\tka-nuwa\tlo\n‎Free ‎Eng‎ The dog sleeps by the river.\n", encoding="utf-8")
    out = tmp_path / "report.json"
    assert main(["--demo", "--locate", str(paste), "--out", str(out)]) == 0
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["queries"][0]["label"] == "2.2" and r["hits"][0]["label"] == "2.2" and r["hits"][0]["seg"] == 4
    assert r["bestPerSegment"][0]["candidates"][0]["label"] == "2.2"
    seg = r["textsWithThoseNumbers"][0]["segments"][0]
    assert seg["label"] == "2.2" and seg["baselineNorm"] == "kabir pemu kanuwa lo"


def test_free_row_drops_its_writing_system_code(tmp_path):
    """Seth's Print-view copy, 2026-10-16: "Free Eng So concerning…" kept "eng" in the query,
    while a translation that only starts with a short word keeps it."""
    fs = FlexService(Notebook(tmp_path / "nb"))
    pasted = ("51.1\tWord\tbɛtɛ\tnae\r\n\tWord Gloss Eng\tand.then\tdog\r\n"
              "‎Free ‎Eng‎ ‎‎So concerning the dogs, \r\n‎ ‎Ind‎ ‎‎\r\n")
    q, _ = fs._paste_queries(pasted)
    assert q[0]["free"] == "so concerning the dogs" and q[0]["label"] == "51.1"
    q, _ = fs._paste_queries("Word\tshe caught it\nFree She caught it.")
    assert q[0]["free"] == "she caught it"
    q, _ = fs._paste_queries("Word\tfoo bar\nFree\tEng\tThe dog ran.\nInd")
    assert q[0]["free"] == "the dog ran"


def test_unreadable_punctuation_comes_from_the_baseline_or_is_dropped():
    """Seth's screen, 2026-10-16: a punctuation token whose text read empty showed as
    "A PunctuationForm" (its ShortName); before that it was an empty <word/> in an export."""
    w = [model.make_word("dʒuɾi"), model.make_word("", punct=True), model.make_word("kuɾiətɛ"), model.make_word("", punct=True)]
    assert [x["txt"] for x in model.fill_punctuation(w, "dʒuɾi, kuɾiətɛ.")] == ["dʒuɾi", ",", "kuɾiətɛ", "."]
    w = [model.make_word("ka"), model.make_word("", punct=True)]
    assert [x["txt"] for x in model.fill_punctuation(w, "ka")] == ["ka"]                 # nothing to take: dropped
    assert model.fill_punctuation([model.make_word("", punct=True)], "") == []
    src = (Path(__file__).resolve().parent.parent / "flex_scratchpad" / "flex" / "lcm.py").read_text(encoding="utf-8")
    assert "tok.ShortName" not in src.replace("never tok.ShortName", "")


def test_export_clips_gives_one_compressed_clip_per_example(tmp_path, monkeypatch):
    """Seth, 2026-10-18: the HTML export embeds the audio as base64 — one clip per example, cut
    like the playback clip and compressed through ffmpeg when there is one, the WAV slice itself
    otherwise; an example without a recording gets an error instead of a player."""
    import base64
    from flex_scratchpad.flex import audio
    nb = Notebook(tmp_path / "nb")
    svc = FlexService(nb)
    svc.configure(source="demo")
    svc.open()
    items = [{"id": "a", "text": T_STORY, "begin": 1500, "end": 3200}, {"id": "b", "text": T_STORY, "begin": 0, "end": 0}, {"id": "c", "text": T_ARAB, "begin": 0, "end": 1000}]
    # no ffmpeg → the WAV slice itself
    monkeypatch.setattr(audio, "find_ffmpeg", lambda configured="": None)
    out = svc.export_clips(items)
    assert [o["id"] for o in out] == ["a", "b", "c"]
    assert out[0]["mime"] == "audio/wav" and out[0]["bytes"] > 1000 and base64.b64decode(out[0]["base64"])[:4] == b"RIFF"
    assert out[1]["error"] == "no timing" and "error" in out[2]
    # ffmpeg (when this machine has one) → Opus in Ogg, kept beside the clip for the next export
    import shutil
    real = shutil.which("ffmpeg")
    if real:
        monkeypatch.setattr(audio, "find_ffmpeg", lambda configured="": real)
        out = svc.export_clips(items[:1])
        assert out[0]["mime"] in ("audio/ogg", "audio/mpeg") and out[0]["bytes"] > 100, out[0]
        kept = list(svc.cache.audio_dir(svc.project_name).glob("*_1500-3200.export.*"))
        assert kept and svc.cache.find_audio_clip(svc.project_name, T_STORY, 1500, 3200).suffix in (".wav", ".flac"), kept   # the copy is never mistaken for the clip
