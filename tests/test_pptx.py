"""The PowerPoint export (pptx_writer.py): a valid package whose slides hold the deck's content."""
import io
import zipfile
import xml.etree.ElementTree as ET

from flex_scratchpad.pptx_writer import build_pptx

from test_xlsx import _doc


def _deck():
    doc = _doc()
    blocks = doc["blocks"]
    return {"title": doc["title"], "where": doc["where"], "project": doc["project"], "date": doc["date"], "slides": [
        {"kind": "title", "title": doc["title"], "subtitle": "Notes › Grammar · FLEx project Kalu Demo · 2026-10-18"},
        {"kind": "text", "title": "Heading", "blocks": [blocks[1], blocks[2]]},
        {"kind": "object", "title": "Heading", "blocks": [blocks[3]]},
        {"kind": "object", "title": "Heading", "lead": {"type": "p", "runs": [{"text": "An example:"}]}, "blocks": [blocks[4]]},
        {"kind": "object", "title": "Heading", "blocks": [blocks[5]]},
        {"kind": "object", "title": "", "blocks": [blocks[6]]},
        {"kind": "object", "title": "Pic", "blocks": [{"type": "image", "png": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "width": 1, "height": 1}]},
    ]}


def test_package_parts_relationships_and_content():
    data = build_pptx(_deck())
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    names = set(z.namelist())
    for part in ("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "ppt/slideMasters/slideMaster1.xml",
                 "ppt/slideLayouts/slideLayout1.xml", "ppt/theme/theme1.xml", "ppt/slides/slide1.xml", "ppt/slides/slide7.xml", "ppt/slides/_rels/slide7.xml.rels", "ppt/media/image1.png"):
        assert part in names, part
    for n in sorted(x for x in names if x.endswith(".xml") or x.endswith(".rels")):
        ET.fromstring(z.read(n))                                          # every part well-formed
    pres = z.read("ppt/presentation.xml").decode("utf-8")
    assert pres.count("<p:sldId ") == 7 and 'cx="12192000"' in pres
    rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8")
    assert rels.count('relationships/slide"') == 7 and "slideMaster1.xml" in rels and "theme1.xml" in rels
    s1 = z.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "My note / test" in s1 and 'val="1F4F8F"' in s1                 # the title slide, on its blue
    s2 = z.read("ppt/slides/slide2.xml").decode("utf-8")
    assert ">Heading<" in s2 and "Plain and " in s2 and 'b="1"' in s2 and "<a:buChar" in s2 and "☑" in s2       # the bullet, the ticked task
    s3 = z.read("ppt/slides/slide3.xml").decode("utf-8")
    assert "<a:tbl>" in s3 and ">Form<" in s3 and 'gridSpan="2"' in s3 and 'hMerge="1"' in s3
    s4 = z.read("ppt/slides/slide4.xml").decode("utf-8")
    assert "An example:" in s4 and "ka-nuwa-mo" in s4 and 'typeface="Charis SIL"' in s4 and "The dog slept." in s4 and "<a:tbl>" in s4
    s5 = z.read("ppt/slides/slide5.xml").decode("utf-8")
    assert ">Nucleus<" in s5 and ">Status<" in s5 and ">given<" in s5 and 'val="FEF3C7"' in s5 and 'val="FDE68A"' in s5 and "The dog slept." in s5 and 'rowSpan="2"' in s5
    assert "Kabir" in s5 and ">ka-nuwa-mo<" in s5 and "<a:t>  </a:t>" in s5 and ">lo<" in s5   # a cell's words on one line, two spaces apart
    s6 = z.read("ppt/slides/slide6.xml").decode("utf-8")
    assert ">kabir<" in s6 and "a domestic dog" in s6
    s7 = z.read("ppt/slides/_rels/slide7.xml.rels").decode("utf-8")
    assert "../media/image1.png" in s7 and "<p:pic>" in z.read("ppt/slides/slide7.xml").decode("utf-8")
    # every cell of every table row is written (PowerPoint refuses ragged rows)
    for n in ("ppt/slides/slide3.xml", "ppt/slides/slide4.xml", "ppt/slides/slide5.xml"):
        root = ET.fromstring(z.read(n))
        A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        for tbl in root.iter(A + "tbl"):
            ncols = len(list(tbl.find(A + "tblGrid")))
            for tr in tbl.iter(A + "tr"):
                assert len(list(tr.findall(A + "tc"))) == ncols, n


def test_an_empty_deck_still_opens():
    data = build_pptx({"title": "Empty", "slides": []})
    z = zipfile.ZipFile(io.BytesIO(data))
    assert "ppt/slides/slide1.xml" in z.namelist() and "Empty" in z.read("ppt/slides/slide1.xml").decode("utf-8")


def test_recordings_play_beside_their_examples_and_themes_recolour_the_deck():
    """Seth, 2026-10-20: "embedded audio as playable media in the slides next to the examples", the
    blocks the user put on one slide stacked on a MIXED slide, and "more styling options than just
    white background". An example whose block carries `audio.src` gets the recording (from the
    media resolver: Api.export_note_pptx reads it in Python) as a p:pic with an audioFile link and a
    p14:media embed to one media part, a ▶ picture, and the timing node PowerPoint plays it from;
    the same recording twice is one part; a recording that cannot be had leaves no player."""
    doc = _doc()
    ex = next(b for b in doc["blocks"] if b.get("type") == "interlinear")
    ex = dict(ex, audio={"src": "fs-clip:00112233445566aa"})
    gone = dict(ex, audio={"src": "fs-clip:ffffffffffffffff"})
    deck = {"title": "Talk", "theme": {"bg": "#1e2227", "fg": "#e8eaed", "accent": "#3b6fb6", "vern": "#8ab4ff", "font": "Charis SIL"}, "slides": [
        {"kind": "title", "title": "Talk", "subtitle": "s"},
        {"kind": "object", "title": "One", "blocks": [ex]},
        {"kind": "mixed", "title": "Two", "blocks": [{"type": "p", "runs": [{"text": "Look at this:"}]}, ex, {"type": "p", "runs": [{"text": "and this"}]}, gone]},
    ]}
    asked = []

    def media(src):
        asked.append(src)
        return (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav", ".wav") if src.endswith("aa") else None
    z = zipfile.ZipFile(io.BytesIO(build_pptx(deck, media)))
    assert z.testzip() is None
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            ET.fromstring(z.read(n))
    assert sorted(n for n in z.namelist() if n.startswith("ppt/media/")) == ["ppt/media/audio-play.png", "ppt/media/media1.wav"]
    assert 'Extension="wav" ContentType="audio/wav"' in z.read("[Content_Types].xml").decode()
    s2, s3 = z.read("ppt/slides/slide2.xml").decode(), z.read("ppt/slides/slide3.xml").decode()
    for s in (s2, s3):
        assert s.count("<a:audioFile ") == 1 and s.count("<p:audio>") == 1 and "ppaction://media" in s and "p14:media" in s
    r3 = z.read("ppt/slides/_rels/slide3.xml.rels").decode()
    assert "relationships/audio" in r3 and "2007/relationships/media" in r3 and "../media/media1.wav" in r3
    assert "Look at this:" in s3 and "and this" in s3 and s3.count('name="Example"') == 2 * s2.count('name="Example"') > 0      # both examples on the mixed slide
    # the theme: the slide's background, the example's colours, the font
    assert '<p:bg><p:bgPr><a:solidFill><a:srgbClr val="1E2227"/>' in s2 and "8AB4FF" in s2 and "00379C" not in s2
    assert 'typeface="Charis SIL"' in z.read("ppt/theme/theme1.xml").decode()
    # the default theme writes what it always did
    plain = zipfile.ZipFile(io.BytesIO(build_pptx({"title": "T", "slides": [{"kind": "object", "title": "One", "blocks": [ex]}]})))
    p1 = plain.read("ppt/slides/slide1.xml").decode()
    assert "00379C" in p1 and "<p:bg>" not in p1 and "<a:audioFile" not in p1       # no resolver: no player
