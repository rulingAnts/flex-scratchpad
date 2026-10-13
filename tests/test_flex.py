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
