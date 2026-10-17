"""Files attached to notes (Seth, 2026-10-17): copied into <notebook>/attachments/ by default,
linked where they are on request; opened in their own program, never started when they are a
program; carried along by a Markdown export; linked from a Word export."""
import base64
import threading
import time
import zipfile

import pytest

from flex_scratchpad.api import Api, file_kind
from flex_scratchpad.config import AppConfig
from flex_scratchpad.docx_writer import build_docx


def make(tmp_path):
    return Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)


def src_file(tmp_path, name, data=b"hello"):
    d = tmp_path / "outside"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def test_copy_keeps_the_name_reuses_the_same_file_and_numbers_a_different_one(tmp_path):
    api = make(tmp_path)
    p = src_file(tmp_path, "Survey ŋa.html", b"<p>a</p>")
    a = api.attach_paths([str(p)])[0]
    assert a["ref"] == "attachments/Survey ŋa.html" and not a["linked"] and a["kind"] == "html"
    assert (tmp_path / "nb" / "attachments" / "Survey ŋa.html").read_bytes() == b"<p>a</p>"
    assert a["fileUrl"].startswith("file://") and a["size"] == 8
    assert api.attach_paths([str(p)])[0]["ref"] == "attachments/Survey ŋa.html"      # same content: reused
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "Survey ŋa.html").write_bytes(b"<p>b</p>")
    assert api.attach_paths([str(other / "Survey ŋa.html")])[0]["ref"] == "attachments/Survey ŋa (2).html"
    assert (tmp_path / "nb" / "attachments" / "Survey ŋa.html").read_bytes() == b"<p>a</p>"   # never overwritten


def test_link_leaves_the_file_where_it_is(tmp_path):
    api = make(tmp_path)
    p = src_file(tmp_path, "rec.wav")
    a = api.attach_paths([str(p)], True)[0]
    assert a["linked"] and a["ref"] == str(p.resolve()) and a["kind"] == "audio"
    assert not (tmp_path / "nb" / "attachments").exists()
    assert api.file_info(a["ref"])["exists"]
    p.unlink()
    assert not api.file_info(a["ref"])["exists"]


def test_the_attachments_folder_is_never_a_tab_and_a_reference_cannot_leave_the_notebook(tmp_path):
    api = make(tmp_path)
    api.attach_data("x.txt", base64.b64encode(b"x").decode())
    (tmp_path / "nb" / "attachments" / "stray.md").write_text("---\nid: n_stray\ntitle: Stray\n---\nbody\n", encoding="utf-8")
    api._nb.scan()
    assert "attachments" not in [t["dir"] for t in api._nb.config["tabs"]]
    assert all(n["id"] != "n_stray" for n in api.list_notes())
    assert api._nb.add_tab("attachments")["dir"] != "attachments"
    with pytest.raises(ValueError):
        api.file_info("../config.json")
    with pytest.raises(ValueError):
        api.file_info("attachments/../../config.json")


def test_open_starts_the_program_windows_associates_but_never_a_program(tmp_path, monkeypatch):
    api = make(tmp_path)
    opened, shown = [], []
    monkeypatch.setattr(Api, "_open_url", staticmethod(lambda u: opened.append(u) or True))
    monkeypatch.setattr(Api, "_reveal", staticmethod(lambda p: shown.append(str(p)) or True))
    doc = api.attach_paths([str(src_file(tmp_path, "notes.pdf"))])[0]
    assert api.open_file(doc["ref"]) == {"opened": True} and opened[-1].endswith("notes.pdf")
    for name in ("setup.exe", "run.bat", "x.ps1", "a.js", "b.lnk", "c.vbs"):
        assert file_kind(src_file(tmp_path, name)) == "program"
        ref = api.attach_paths([str(src_file(tmp_path, name))])[0]["ref"]
        r = api.open_file(ref)
        assert r["opened"] is False and r["reason"] == "program"
    assert len(opened) == 1 and len(shown) == 6
    with pytest.raises(ValueError):
        api.open_file("attachments/nothing-here.pdf")


def test_a_dropped_files_path_comes_from_pywebviews_drop_handler(tmp_path):
    api = make(tmp_path)
    p = src_file(tmp_path, "big recording.wav")
    # the page asks first; pywebview's handler reports the path a moment later on another thread
    t = threading.Timer(0.2, lambda: api._on_drop({"dataTransfer": {"files": [{"name": p.name, "pywebviewFullPath": str(p)}]}}))
    t.start()
    t0 = time.monotonic()
    got = api.attach_dropped([p.name, "not-seen.txt"], True)
    assert time.monotonic() - t0 < 2.5
    assert [f["ref"] for f in got["files"]] == [str(p.resolve())] and got["missing"] == ["not-seen.txt"]
    # claimed once: a second ask does not find it again
    assert api.attach_dropped([p.name], False)["missing"] == [p.name]


def test_markdown_export_brings_the_copied_files_along(tmp_path):
    api = make(tmp_path)
    a = api.attach_paths([str(src_file(tmp_path, "My survey.pdf", b"%PDF-1"))])[0]
    api.attach_paths([str(src_file(tmp_path, "plain.txt", b"t"))])
    linked = api.attach_paths([str(src_file(tmp_path, "elsewhere.wav"))], True)[0]
    body = "See {{file attachments/My%20survey.pdf \"Survey\"}}, {{file attachments/plain.txt}} and {{file " + linked["ref"].replace(" ", "%20") + "}}.\n"
    n = api.create_note("Notes", "", "Field trip", body)
    out = tmp_path / "export"
    out.mkdir()
    target = api.export_note_markdown(n["id"], str(out / "trip.md"))
    assert "{{file attachments/My%20survey.pdf" in (out / "trip.md").read_text(encoding="utf-8")
    assert (out / "attachments" / "My survey.pdf").read_bytes() == b"%PDF-1"
    assert sorted(x.name for x in (out / "attachments").iterdir()) == ["My survey.pdf", "plain.txt"]   # the link is not copied
    assert target == str(out / "trip.md") and a["ref"] == "attachments/My survey.pdf"


def test_word_export_links_an_attachment(tmp_path):
    doc = {"title": "T", "blocks": [{"type": "p", "runs": [{"text": "See "}, {"text": "📎 Survey", "href": "file:///C:/nb/attachments/Survey%20a.pdf"}]}]}
    with zipfile.ZipFile(__import__("io").BytesIO(build_docx(doc))) as z:
        xml = z.read("word/document.xml").decode()
        rels = z.read("word/_rels/document.xml.rels").decode()
    assert '<w:hyperlink r:id="rIdLink' in xml and "📎 Survey" in xml
    assert 'TargetMode="External"' in rels and "file:///C:/nb/attachments/Survey%20a.pdf" in rels


def test_notebook_zip_carries_the_attachments(tmp_path):
    api = make(tmp_path)
    api.attach_data("a.txt", base64.b64encode(b"x").decode())
    z = api._nb.export_zip(tmp_path / "nb.zip")
    with zipfile.ZipFile(z) as zz:
        assert "attachments/a.txt" in zz.namelist()


def test_an_excerpt_reads_an_attachment_as_its_label_or_name():
    from flex_scratchpad.notebook import excerpt
    body = 'Rec is {{file C:/x/Session%203.wav "Session 3"}} and {{file attachments/Eli%20p.html}}. x'
    assert excerpt(body) == "Rec is Session 3 and Eli p.html. x"
