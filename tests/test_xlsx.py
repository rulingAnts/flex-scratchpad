"""The Excel export (xlsx_writer.py): a valid workbook, with the note's content laid out as the
page model says — read back with openpyxl when it is installed (dev only)."""
import zipfile
import xml.etree.ElementTree as ET

import pytest

from flex_scratchpad.xlsx_writer import build_xlsx, col_letter

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _doc():
    seg = lambda n, label, words, free: {"n": n, "label": label, "free": [{"text": free}], "begin": n * 1000, "end": n * 1000 + 900, "lines": [  # noqa: E731
        {"name": "txt", "cells": [[{"text": w[0], "color": "#00379c"}] for w in words]}, {"name": "gls", "cells": [[{"text": w[1], "color": "#2a6e2a"}] for w in words]}]}
    W = lambda txt, gls: [{"text": txt, "color": "#00379c"}, {"text": "\n"}, {"text": gls, "color": "#2a6e2a"}]  # noqa: E731
    cell = lambda col, words, **kw: dict({"span": 1, "col": col, "segs": [1], "words": words, "marks": [], "plain": {"txt": " ".join(w[0]["text"] for w in words), "gls": " ".join(w[2]["text"] for w in words), "marks": [], "moved": [], "clauses": []}, "hl": "", "b": False, "i": False, "u": False, "color": ""}, **kw)  # noqa: E731
    chart = {"type": "chart", "guid": "c1", "text": "t1", "name": "Story chart", "title": "The dog", "cols": 3, "freeCol": False, "notesCol": True,
             "headers": [[{"text": "Nucleus", "span": 2}, {"text": "Post", "span": 1}], [{"text": "Subject", "span": 1}, {"text": "Verb", "span": 1}, {"text": "Inner", "span": 1}]],
             "columns": [{"n": 1, "name": "Subject", "path": "Nucleus/Subject"}, {"n": 2, "name": "Verb", "path": "Nucleus/Verb"}, {"n": 3, "name": "Inner", "path": "Post/Inner"}],
             "xcols": [{"name": "Status", "kind": "list"}, {"name": "Role", "kind": "rule"}],
             "segments": [{"n": 1, "label": "1.1", "free": "The dog slept."}],
             "rows": [
                 {"n": 1, "label": "1a", "clause": "normal", "endSent": True, "endPara": False, "segs": [1], "notesText": "a note", "notes": "a note",
                  "cells": [cell(1, [W("Kabir", "dog")]), cell(2, [W("ka-nuwa-mo", "slept"), W("lo", "DECL")], span=2, marks=[{"text": " new ", "hl": "#ffd6a5", "b": True}])],
                  "xcells": [{"text": "given", "hl": "", "color": "", "b": False, "i": False, "u": False}, {"text": "N", "hl": "#fde68a", "color": "", "b": True, "i": False, "u": False}],
                  "rowStyle": {"bg": "#fef3c7"}, "free": None, "freeRow": {"text": "‘The dog slept.’", "rows": "1a"}},
             ]}
    for c in chart["rows"][0]["cells"]:
        if c["span"] == 2:
            c["plain"]["marks"] = ["New"]
    return {"title": "My note / test", "where": "Notes › Grammar", "project": "Kalu Demo", "date": "2026-10-18", "blocks": [
        {"type": "h", "level": 1, "runs": [{"text": "Heading"}]},
        {"type": "p", "runs": [{"text": "Plain and "}, {"text": "bold", "b": True}]},
        {"type": "list", "items": [{"runs": [{"text": "one"}], "ordered": False, "level": 0}, {"runs": [{"text": "two"}], "ordered": True, "n": 2, "level": 1, "task": True, "checked": True}]},
        {"type": "table", "header": True, "rows": [[{"runs": [{"text": "Form"}]}, {"runs": [{"text": "Gloss"}]}], [{"runs": [{"text": "kabir"}], "colspan": 2}, {"runs": [], "covered": True}]], "style": {}},
        {"type": "interlinear", "guid": "t1", "text": "t1", "title": "The dog", "exNum": "(1)", "ws": {"font": "Charis SIL"},
         "segments": [seg(1, "1.1", [("Kabir", "dog"), ("ka-nuwa-mo", "slept")], "The dog slept."), seg(2, "1.2", [("Haŋa", "yesterday")], "Yesterday.")]},
        chart,
        {"type": "entry", "headword": "kabir", "pos": "n", "senses": [{"number": "1", "gloss": "dog", "definition": "a domestic dog", "examples": [{"text": "kabir lo", "translation": "the dog"}]}]},
    ]}


def test_col_letters():
    assert [col_letter(n) for n in (1, 26, 27, 52, 703)] == ["A", "Z", "AA", "AZ", "AAA"]


def test_workbook_is_a_valid_package_with_the_note_the_examples_and_the_chart_rows(tmp_path):
    data = build_xlsx(_doc())
    z = zipfile.ZipFile(__import__("io").BytesIO(data))
    assert z.testzip() is None
    names = set(z.namelist())
    assert {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml", "xl/worksheets/sheet4.xml"} <= names
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    assert [s.get("name") for s in wb.iter("{%s}sheet" % NS["m"])] == ["Note", "Chart", "Chart rows", "Examples"]
    for n in sorted(x for x in names if x.endswith(".xml")):
        ET.fromstring(z.read(n))                                             # well-formed, all of it
    note = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "My note / test" in note and "Notes › Grammar" in note and "Heading" in note and "<b/>" in note
    assert "ka-nuwa-mo" in note and "Story chart" in note and "sheet “Chart”" in note
    chart = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
    assert "Nucleus" in chart and "Status" in chart and ">given<" in chart and "<mergeCells" in chart and 'state="frozen"' in chart
    styles = z.read("xl/styles.xml").decode("utf-8")
    assert 'rgb="FFFEF3C7"' in styles and 'rgb="FFFDE68A"' in styles         # the row's and the rule cell's colours
    rows = z.read("xl/worksheets/sheet3.xml").decode("utf-8")
    assert "Nucleus/Subject" in rows and "Nucleus/Verb (gloss)" in rows and ">New<" in rows and ">given<" in rows and "The dog slept." in rows and "a note" in rows
    ex = z.read("xl/worksheets/sheet4.xml").decode("utf-8")
    assert "Baseline" in ex and "Kabir ka-nuwa-mo" in ex and "dog slept" in ex and "Yesterday." in ex
    # a sheet name that Excel refuses is made safe and never repeated
    from flex_scratchpad.xlsx_writer import Workbook
    w = Workbook()
    assert [w.sheet(n).name for n in ("a/b:c", "a-b-c", "x" * 40, "x" * 40)] == ["a-b-c", "a-b-c (2)", "x" * 31, "x" * 27 + " (2)"]


def test_openpyxl_reads_it_back(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "n.xlsx"
    p.write_bytes(build_xlsx(_doc()))
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Note", "Chart", "Chart rows", "Examples"]
    ws = wb["Chart rows"]
    head = [c.value for c in ws[1]]
    assert head[:4] == ["Row", "Clause", "Ends sentence", "Ends paragraph"] and "Markers" in head and "Status" in head
    row = {h: v for h, v in zip(head, [c.value for c in ws[2]])}
    assert row["Row"] == "1a" and row["Nucleus/Subject"] == "Kabir" and row["Nucleus/Verb"] == "ka-nuwa-mo lo" and row["Markers"] == "New" and row["Role"] == "N"
    ex = wb["Examples"]
    assert ex["A2"].value == 1 and ex["D2"].value == "Kabir ka-nuwa-mo" and ex.freeze_panes == "A2"
    note = wb["Note"]
    assert note["A1"].value == "My note / test" and any(isinstance(c.value, str) and "Story chart" in c.value for r in note.iter_rows() for c in r)
    assert wb["Chart"].merged_cells.ranges and wb["Chart"].freeze_panes == "A5"   # header groups merged, the headers frozen
