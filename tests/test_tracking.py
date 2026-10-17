"""An example stays on ITS lines while the text changes in FLEx (Seth, 2026-10-17: "lines deleted,
merged, or split in baseline … We'd really like our flex objects to be more reliable, stable, and
intelligent"). The demo text is edited here the way FieldWorks edits segments
(liblcm AnalysisAdjuster): an untouched segment keeps its GUID, a split keeps it on the FIRST
piece, a merge keeps the FIRST segment, a rebuilt paragraph gets new GUIDs."""
import copy

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.flex import tracking
from flex_scratchpad.flex.demo import T_STORY


def make(tmp_path):
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    return api, api._flex.backend.texts[T_STORY]


def renumber(text):
    para, k, prev = 0, 0, None
    for n, s in enumerate(text["segments"], 1):
        if s["para"] != prev:
            para, k, prev = para + 1, 0, s["para"]
        k += 1
        s["n"], s["k"], s["label"] = n, k, f"{para}.{k}"
    text["segmentCount"] = len(text["segments"])


def new_seg(like, tail, baseline):
    s = copy.deepcopy(like)
    s["guid"] = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b" + tail
    s["baseline"] = baseline
    s["words"] = [{"txt": w, "gls": ""} for w in baseline.rstrip(".").split()]
    return s


def show(api, a, b, at):
    o = api.flex_get("text", T_STORY, a, b, False, None, at)
    return o, [s["baseline"] for s in o["segments"]]


def test_renumbered_split_merged_deleted_and_rebuilt_lines(tmp_path):
    api, text = make(tmp_path)
    segs = text["segments"]
    # the example: lines 2.1–2.2 (running numbers 3–4)
    o, lines = show(api, 3, 4, None)
    assert lines == ["“Ɲamú!” ka-sila lo.", "Kabir pemu ka-nuwa lo."]
    at = o["anchors"]

    # 1. a line added at the top: the same lines, renumbered
    segs.insert(0, new_seg(segs[0], "9001", "Ere ka-sila."))
    renumber(text)
    o, lines = show(api, 3, 4, at)
    assert lines == ["“Ɲamú!” ka-sila lo.", "Kabir pemu ka-nuwa lo."]
    assert o["range"] == [4, 5] and o["rangeMoved"] and o["track"]["change"] == "moved"
    assert o["track"]["map"] == [4, 5]

    # 2. the example's last line split in two: FLEx keeps the first piece; both pieces stay in it
    last = next(s for s in segs if s["baseline"] == "Kabir pemu ka-nuwa lo.")
    i = segs.index(last)
    last["baseline"] = "Kabir pemu."
    last["words"] = [{"txt": "Kabir"}, {"txt": "pemu"}]
    segs.insert(i + 1, new_seg(last, "9002", "Ka-nuwa lo."))
    renumber(text)
    o, lines = show(api, 4, 5, o["anchors"])
    assert lines == ["“Ɲamú!” ka-sila lo.", "Kabir pemu.", "Ka-nuwa lo."], lines
    assert o["track"]["change"] == "reshaped" and "split" in o["track"]["how"]
    assert o["track"]["map"] == [4, 5]

    # 3. the example's first line merged into the line before it (FLEx keeps the earlier one)
    at, a, b = o["anchors"], o["range"][0], o["range"][1]
    first = next(s for s in segs if s["baseline"].startswith("“Ɲamú!”"))
    j = segs.index(first)
    segs[j - 1]["baseline"] = segs[j - 1]["baseline"].rstrip(".") + " “Ɲamú!” ka-sila lo."
    del segs[j]
    renumber(text)
    o, lines = show(api, a, b, at)
    assert lines[0].endswith("“Ɲamú!” ka-sila lo.") and lines[1:] == ["Kabir pemu.", "Ka-nuwa lo."], lines
    assert "merged" in o["track"]["how"] and o["track"]["map"][0] is None

    # 4. a line inside the example deleted: the rest stays, the map says which went
    at, a, b = o["anchors"], o["range"][0], o["range"][1]
    mid = next(s for s in segs if s["baseline"] == "Kabir pemu.")
    segs.remove(mid)
    renumber(text)
    o, lines = show(api, a, b, at)
    assert lines[1:] == ["Ka-nuwa lo."] and o["track"]["map"][1] is None

    # 5. the paragraph rebuilt (every segment new): the lines are found again by their text
    at, a, b = o["anchors"], o["range"][0], o["range"][1]
    for k, s in enumerate(segs):
        s["guid"] = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b8%03d" % k
    segs.insert(0, new_seg(segs[0], "7777", "Una pemu."))
    renumber(text)
    o, lines = show(api, a, b, at)
    assert o["track"]["change"] == "found" and lines[-1] == "Ka-nuwa lo.", (o["track"], lines)

    # 6. and when the lines are simply gone: the saved copy, marked lost — never other lines
    at, a, b = o["anchors"], o["range"][0], o["range"][1]
    saved = lines
    for k, s in enumerate(segs):
        s["guid"] = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b6%03d" % k
        s["baseline"] = "Zzz qqq %d." % k
    renumber(text)
    o, lines = show(api, a, b, at)
    assert o.get("lost") and o["track"]["change"] == "lost" and lines == saved


def test_the_snapshot_never_keeps_an_old_line_under_a_new_number(tmp_path):
    api, text = make(tmp_path)
    segs = text["segments"]
    show(api, 1, 6, None)
    segs.insert(0, new_seg(segs[0], "9003", "Ere ka-sila."))
    renumber(text)
    o, _ = show(api, 1, 1, None)
    snap = api._flex.cache.get(api._flex.project_name, "text", T_STORY)
    by_n = {s["n"]: s["guid"] for s in snap["segments"]}
    idx = {e["n"]: e["guid"] for e in o["index"]}
    assert all(idx[n] == g for n, g in by_n.items())


def test_norm_ignores_punctuation_and_case_but_not_letters():
    assert tracking.norm("“Ɲamú!” Ka-sila lo.") == tracking.norm("ɲamú kasila LO")
    assert tracking.norm("pemu") != tracking.norm("pému")


def test_a_plain_redraw_never_reads_the_whole_text(tmp_path):
    api, text = make(tmp_path)
    be = api._flex.backend
    calls = []
    real = be.text_baselines
    be.text_baselines = lambda g: calls.append(g) or real(g)
    o, _ = show(api, 3, 4, None)
    for _ in range(3):
        o, _ = show(api, 3, 4, o["anchors"])
    segs = text["segments"]
    segs.insert(0, new_seg(segs[0], "9004", "Ere ka-sila."))
    renumber(text)
    o, _ = show(api, 3, 4, o["anchors"])           # renumbered: still no reading of the whole text
    assert o["range"] == [4, 5] and calls == []
