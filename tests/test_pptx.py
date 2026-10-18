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
