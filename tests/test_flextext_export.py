"""A note's examples as a .flextext (Seth, 2026-10-16), and the flexscratchpad:// link plumbing."""
import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from flex_scratchpad import links
from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex.demo import T_ARAB, T_STORY
from flex_scratchpad.flex.flextext import FlextextBackend
from flex_scratchpad.flex.model import morph_type_of, strip_markers


def make(tmp_path):
    return Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)


ITEMS = [{"kind": "text", "guid": T_STORY, "seg": [1, 2], "at": None, "label": "SVC a"},
         {"kind": "entry", "guid": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001"},
         {"kind": "text", "guid": T_STORY, "seg": [4, 4], "at": None, "label": ""}]


def test_export_is_one_flex_text_with_a_paragraph_per_example(tmp_path):
    api = make(tmp_path)
    n = api.create_note(None, "", "SVCs", "Collected serial verbs.\n\n{{flex:text %s seg=1-2 \"SVC a\"}}\n\n{{flex:text %s seg=4}}" % (T_STORY, T_STORY), "examples")
    out = tmp_path / "svcs.flextext"
    r = api.export_note_flextext(n["id"], ITEMS, {"title": "SVCs", "includeLink": True, "includeMarkdown": True}, str(out))
    assert r["path"] == str(out) and r["examples"] == 2 and r["skipped"] == 1 and r["texts"] == [{"ws": "kal", "examples": 2}]
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    texts = root.findall("interlinear-text")
    assert len(texts) == 1 and texts[0].get("guid") != T_STORY
    it = texts[0]
    assert [i.text for i in it.findall("item") if i.get("type") == "title"] == ["SVCs"]
    assert any(i.get("type") == "source" and "flexscratchpad://note/" + n["id"] in i.text for i in it.findall("item"))
    assert any(i.get("type") == "comment" and "Collected serial verbs." in i.text for i in it.findall("item"))
    paras = it.findall("paragraphs/paragraph")
    assert len(paras) == 2                                                        # one per example
    phrases = [ph for p in paras for ph in p.findall("phrases/phrase")]
    assert len(phrases) == 3
    assert [ph.find("item[@type='segnum']").text for ph in phrases] == ["1.1", "1.2", "2.1"]
    demo_guids = {f"9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b1{i:03d}" for i in range(1, 7)}
    assert not (demo_guids & {ph.get("guid") for ph in phrases})                    # new phrase GUIDs, never the originals
    # every writing system rides: the first segment's free translation in en AND id, the first word's gloss too
    ph1 = phrases[0]
    frees = {i.get("lang"): i.text for i in ph1.findall("item[@type='gls']")}
    assert frees == {"en": "The dog slept.", "id": "Anjing itu tidur."}
    w1 = ph1.find("words/word")
    assert {i.get("lang"): i.text for i in w1.findall("item[@type='gls']")} == {"en": "dog", "id": "anjing"}
    assert w1.find("item[@type='txt']").get("lang") == "kal" and w1.find("item[@type='txt']").text == "Kabir"
    # morphemes: break characters on the forms, bare glosses, FLEx morph types
    w2 = ph1.findall("words/word")[1]
    morphs = w2.findall("morphemes/morph")
    assert [m.get("type") for m in morphs] == ["prefix", "stem", "suffix"]
    assert [m.find("item[@type='txt']").text for m in morphs] == ["ka-", "nuwa", "-mo"]
    assert [m.find("item[@type='gls']").text for m in morphs] == ["3SG", "sleep", "PST"]
    # punctuation, the original note, and the Source note with title, FLEx number, GUIDs and the link
    assert ph1.findall("words/word")[-1].find("item[@type='punct']").text == "."
    notes = [i.text for i in ph1.findall("item[@type='note']")]
    assert "Segment one has a note." in notes
    src = [x for x in notes if x.startswith("Source:")][0]
    assert "The dog and the river 1.1" in src and "segment 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b1001" in src and "text " + T_STORY in src and "label: SVC a" in src and "note: flexscratchpad://note/" + n["id"] in src
    # timed segments carry their offsets and a media-files block
    assert ph1.get("begin-time-offset") == "0" and ph1.get("end-time-offset") == "1500" and ph1.get("media-file")
    assert it.find("media-files/media").get("guid") == ph1.get("media-file")
    # languages: the vernacular flagged, fonts carried, the second analysis language listed
    langs = {lg.get("lang"): lg for lg in it.findall("languages/language")}
    assert langs["kal"].get("vernacular") == "true" and langs["kal"].get("font") == "Charis SIL"
    assert "en" in langs and "id" in langs and langs["en"].get("vernacular") is None


def test_export_round_trips_through_our_own_flextext_reader(tmp_path):
    api = make(tmp_path)
    n = api.create_note(None, "", "Round trip", "x", "examples")
    out = tmp_path / "rt.flextext"
    api.export_note_flextext(n["id"], ITEMS, {"sourceNotes": False, "includeLink": False}, str(out))
    be = FlextextBackend([str(out)])
    texts = be.list_texts()
    assert len(texts) == 1 and texts[0]["title"] == "Round trip"
    t = be.get_text(texts[0]["guid"], 1, None)
    orig = api.flex_get("text", T_STORY, 1, 2)["segments"] + api.flex_get("text", T_STORY, 4, 4)["segments"]
    assert [s["baseline"] for s in t["segments"]] == [s["baseline"] for s in orig]
    assert [s["label"] for s in t["segments"]] == ["1.1", "1.2", "2.1"]
    for a, b in zip(t["segments"], orig):
        assert [w["txt"] for w in a["words"]] == [w["txt"] for w in b["words"]]
        assert [[m["form"] for m in w["morphs"]] for w in a["words"]] == [[m["form"] for m in w["morphs"]] for w in b["words"]]
        assert [[m["gls"] for m in w["morphs"]] for w in a["words"]] == [[m["gls"] for m in w["morphs"]] for w in b["words"]]   # markers back on the glosses
        assert a["free"] == b["free"]


def test_mixed_baselines_become_separate_texts_and_only_ws_filters(tmp_path):
    api = make(tmp_path)
    n = api.create_note(None, "", "Mixed", "x", "examples")
    items = [{"kind": "text", "guid": T_STORY, "seg": [1, 1]}, {"kind": "text", "guid": T_ARAB, "seg": None, "at": None}, {"kind": "text", "guid": T_STORY, "seg": [2, 2]}]
    assert api.flextext_preview(items) == {"texts": [{"ws": "kal", "examples": 2}, {"ws": "kal-Arab", "examples": 1}], "skipped": 0}
    out = tmp_path / "mixed.flextext"
    r = api.export_note_flextext(n["id"], items, {"title": "Mixed"}, str(out))
    assert r["texts"] == [{"ws": "kal", "examples": 2}, {"ws": "kal-Arab", "examples": 1}]
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    titles = [t.find("item[@type='title']").text for t in root.findall("interlinear-text")]
    assert titles == ["Mixed (kal)", "Mixed (kal-Arab)"]
    arab = root.findall("interlinear-text")[1]
    assert len(arab.findall("paragraphs/paragraph/phrases/phrase")) == 2                 # the whole text when the embed has no range
    assert arab.find("languages/language[@lang='kal-Arab']").get("RightToLeft") == "true"
    r2 = api.export_note_flextext(n["id"], items, {"title": "Mixed", "onlyWs": "kal-Arab"}, str(tmp_path / "one.flextext"))
    assert r2["texts"] == [{"ws": "kal-Arab", "examples": 1}]
    assert len(ET.fromstring((tmp_path / "one.flextext").read_text(encoding="utf-8")).findall("interlinear-text")) == 1


def test_markers_and_morph_types():
    assert strip_markers("-PST", "-mo") == "PST" and strip_markers("3SG-", "ka-") == "3SG" and strip_markers("sleep", "nuwa") == "sleep"
    assert strip_markers("=lo", "=lo") == "lo"
    assert [morph_type_of(f) for f in ("ka-", "nuwa", "-mo", "=de", "de=", "<in>")] == ["prefix", "stem", "suffix", "enclitic", "proclitic", "infix"]


def test_note_links_parse_hand_over_and_lock(tmp_path):
    assert links.parse_note_url("flexscratchpad://note/abc123") == "abc123"
    assert links.parse_note_url("FLEXSCRATCHPAD://note/abc123/?x=1#f") == "abc123"
    assert links.parse_note_url("https://example.org/note/abc") is None and links.parse_note_url("flexscratchpad://tab/x") is None
    assert links.note_url("abc") == "flexscratchpad://note/abc"
    assert links.launch_command().endswith('"%1"') and ("-m flex_scratchpad" in links.launch_command() or ".exe" in links.launch_command())
    req = tmp_path / "open-request.txt"
    links.hand_over("flexscratchpad://note/one", req)
    links.hand_over("", req)
    assert links.take_requests(req) == ["flexscratchpad://note/one", ""] and links.take_requests(req) == []
    got, done = [], threading.Event()
    t = links.watch_requests(lambda u: (got.append(u), done.set()), interval=0.05, path=req)
    links.hand_over("flexscratchpad://note/two", req)
    assert done.wait(3) and got == ["flexscratchpad://note/two"]
    t.stop.set()
    a = links.InstanceLock(tmp_path / "instance.lock")
    b = links.InstanceLock(tmp_path / "instance.lock")
    assert a.acquire() and not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


def test_ordinary_renders_carry_no_alternatives(tmp_path):
    api = make(tmp_path)
    seg = api.flex_get("text", T_STORY, 1, 1)["segments"][0]
    assert "freeAlts" not in seg and "txtAlts" not in seg["words"][0]
    json.dumps(api.flex_get("text", T_STORY, 1, 1))


def test_word_guids_are_kept_unless_asked_not_to():
    from flex_scratchpad.flex.flextext_writer import build_flextext
    from flex_scratchpad.flex import model
    t = model.empty_text("11111111-2222-4333-8444-555555555555", "T", model.make_ws("kal", "Kalu", "", False), model.make_ws("en", "English", "", False))
    w = model.make_word("kabir", gls="dog", pos="n", morphs=[model.make_morph("kabir", "dog", "n")], guid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    t["segments"] = [model.make_segment("99999999-8888-4777-8666-555555555555", 1, 1, "kabir", [w], free="dog", k=1)]
    t["segmentCount"] = 1
    model.fill_alts(t)
    kept = ET.fromstring(build_flextext([{"text": t}], {"title": "x"}))
    assert kept.find(".//word").get("guid") == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert kept.find(".//phrase").get("guid") != "99999999-8888-4777-8666-555555555555"
    dropped = ET.fromstring(build_flextext([{"text": t}], {"title": "x", "wordGuids": False}))
    assert dropped.find(".//word").get("guid") is None


def test_audio_is_bundled_into_one_recording_with_rewritten_offsets(tmp_path):
    import wave
    api = make(tmp_path)
    n = api.create_note(None, "", "Audio", "x", "examples")
    out = tmp_path / "audio.flextext"
    r = api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [1, 2]}, {"kind": "text", "guid": T_STORY, "seg": [4, 4]}], {"title": "Audio", "audio": "bundle"}, str(out))
    wav = tmp_path / "audio.wav"
    assert r["audio"] == str(wav) and r["audioMatched"] == 3 and r["audioMissing"] == 0 and wav.exists()
    with wave.open(str(wav)) as w:
        length_ms = w.getnframes() * 1000 / w.getframerate()
    # segments 1 (0–1500), 2 (1500–3200), 4 (4600–6000) → 1500 + 1700 + 1400 ms of audio + two 600 ms gaps
    assert abs(length_ms - (1500 + 1700 + 1400 + 2 * 600)) < 30, length_ms
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    phrases = root.findall(".//phrase")
    spans = [(int(p.get("begin-time-offset")), int(p.get("end-time-offset"))) for p in phrases]
    assert spans[0][0] == 0 and abs(spans[0][1] - 1500) < 20
    assert abs(spans[1][0] - (1500 + 600)) < 20 and abs(spans[1][1] - (1500 + 600 + 1700)) < 20
    assert abs(spans[2][0] - (1500 + 600 + 1700 + 600)) < 20
    media = root.findall(".//media-files/media")
    assert len(media) == 1 and media[0].get("location") == str(wav.resolve()) and all(p.get("media-file") == media[0].get("guid") for p in phrases)
    # 'original' keeps the source offsets and file; 'none' drops the timing
    api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [2, 2]}], {"title": "Orig", "audio": "original"}, str(tmp_path / "orig.flextext"))
    ph = ET.parse(tmp_path / "orig.flextext").getroot().find(".//phrase")
    assert ph.get("begin-time-offset") == "1500" and ph.get("end-time-offset") == "3200"
    assert ET.parse(tmp_path / "orig.flextext").getroot().find(".//media-files/media").get("location").endswith("kalu-story.wav")
    api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [2, 2]}], {"title": "None", "audio": "none"}, str(tmp_path / "none.flextext"))
    ph = ET.parse(tmp_path / "none.flextext").getroot().find(".//phrase")
    assert ph.get("begin-time-offset") is None and ET.parse(tmp_path / "none.flextext").getroot().find(".//media-files") is None


def test_default_audio_is_one_mono_wav_clip_per_line(tmp_path):
    """Seth, 2026-10-16: flextext attaches clips to individual lines; small 16-bit mono WAVs
    that go into the project's Linked Files."""
    import wave
    api = make(tmp_path)
    n = api.create_note(None, "", "Clips", "x", "examples")
    out = tmp_path / "clips.flextext"
    r = api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [1, 2]}, {"kind": "text", "guid": T_STORY, "seg": [4, 4]}], {"title": "Clips"}, str(out))
    folder = tmp_path / "clips-audio"
    assert r["audio"] == str(folder) and r["audioMatched"] == 3 and r["audioMissing"] == 0
    names = sorted(p.name for p in folder.glob("*.wav"))
    assert names == ["Clips-1.1.wav", "Clips-1.2.wav", "Clips-2.1.wav"]
    lengths = []
    for name in names:
        with wave.open(str(folder / name)) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2
            lengths.append(w.getnframes() * 1000 / w.getframerate())
    assert [round(x) for x in lengths] == [1500, 1700, 1400]
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    phrases = root.findall(".//phrase")
    media = {m.get("guid"): m.get("location") for m in root.findall(".//media-files/media")}
    assert len(media) == 3
    for ph, name, length in zip(phrases, names, lengths):
        assert ph.get("begin-time-offset") == "0" and abs(int(ph.get("end-time-offset")) - length) < 2
        assert media[ph.get("media-file")] == str((folder / name).resolve())
    # a folder inside a LinkedFiles tree → locations relative to it, as FLEx stores them
    lf = tmp_path / "Proj" / "LinkedFiles" / "AudioVisual"
    r2 = api.export_note_flextext(n["id"], [{"kind": "text", "guid": T_STORY, "seg": [1, 1]}], {"title": "Clips", "audioFolder": str(lf)}, str(tmp_path / "lf.flextext"))
    assert r2["audioMatched"] == 1 and (lf / "Clips-1.1.wav").exists()
    loc = ET.parse(tmp_path / "lf.flextext").getroot().find(".//media-files/media").get("location")
    assert loc == "AudioVisual/Clips-1.1.wav"


def test_only_an_example_collection_exports_and_collections_round_trip(tmp_path):
    """Seth, 2026-10-16: a special note type that is JUST the examples, and only it exports."""
    api = make(tmp_path)
    plain = api.create_note(None, "", "Plain", "{{flex:text %s seg=1}}" % T_STORY)
    with pytest.raises(Exception) as e:
        api.export_note_flextext(plain["id"], ITEMS, {"title": "x"}, str(tmp_path / "x.flextext"))
    assert "example collection" in str(e.value)
    assert "kind:" not in Path(plain["path"]).read_text(encoding="utf-8")        # ordinary files are unchanged
    col = api.create_note(None, "", "SVCs", "", "examples")
    assert col["kind"] == "examples" and "kind: examples" in Path(col["path"]).read_text(encoding="utf-8")
    # examples are appended at the end, one paragraph each
    api.add_to_collection(col["id"], ["{{flex:text %s seg=1}}" % T_STORY])
    s = api.add_to_collection(col["id"], ["{{flex:text %s seg=4}}" % T_STORY, "  "])
    assert api.get_note(col["id"])["body"] == "{{flex:text %s seg=1}}\n\n{{flex:text %s seg=4}}\n" % (T_STORY, T_STORY)
    assert s["kind"] == "examples"
    with pytest.raises(Exception):
        api.add_to_collection(plain["id"], ["{{flex:text %s seg=1}}" % T_STORY])
    cols = api.list_collections()
    assert [c["id"] for c in cols] == [col["id"]] and cols[0]["count"] == 2
    # the kind survives a rescan from disk and a duplicate
    api2 = make(tmp_path)
    assert api2.get_note(col["id"])["kind"] == "examples" and api2.get_note(plain["id"])["kind"] == ""
    dup = api2.duplicate_note(col["id"])
    assert dup["kind"] == "examples"
    r = api2.export_note_flextext(col["id"], [{"kind": "text", "guid": T_STORY, "seg": [1, 1]}, {"kind": "text", "guid": T_STORY, "seg": [4, 4]}], {"title": "SVCs"}, str(tmp_path / "c.flextext"))
    assert r["examples"] == 2
    with pytest.raises(Exception):
        api2.create_note(None, "", "Odd", "", "nonsense")
