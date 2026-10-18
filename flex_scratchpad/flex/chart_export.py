"""Exports of a text chart (Seth, 2026-10-18): FieldWorks' own discourse-chart XML shape, and a
JSON with every GUID.

THE XML follows what FieldWorks writes from Texts & Words › Text Chart › Export (the "Discourse
XML" template; `Src/LexText/Discourse/DiscourseExporter.cs`, read 2026-10-18), so its own
stylesheets (`Discourse2Word.xsl`, `Discourse2XLingPaper.xsl`) can take it:

    <document>
      <chart>
        <row type="title1"><cell cols="1"><main/></cell><cell cols="2"><main><lit lang="en">Prenuclear</lit></main></cell>…</row>
        <row type="title2"> … the column names … </row>
        <row type="normal" id="1a" endSent="true">
          <cell cols="1"><main><rownum lang="en">1a</rownum></main></cell>
          <cell cols="1"><main><word lang="kal">Kabir</word></main><glosses><gloss lang="en">dog</gloss></glosses></cell>
          <cell cols="1"><main><clauseMkr target="2a" lang="en">2a</clauseMkr></main></cell>
          <cell cols="1"><main><moveMkr lang="en">Preposed</moveMkr></main></cell>
          <cell cols="1"><main><lit lang="en">[</lit><listRef lang="en">Top</listRef><lit lang="en">]</lit></main></cell>
          <cell cols="1"><main><note lang="en">…</note></main></cell>
        </row>
      </chart>
      <languages><language lang="kal" font="Charis SIL" vernacular="true"/><language lang="en" font=""/></languages>
    </document>

FLEx never imports this file (it has no importer), so nothing here can touch a project. What
we ADD, and FLEx's stylesheets ignore: `guid` on `<chart>`, `<row>`, `<cell>` (the cell part's)
and `<word>` (the wordform's), `text` on `<chart>`, `col` (the template column's GUID) on a
cell, `endPara` on a row — so a future importer (flexicon's, we hope: plans/flexicon-requests.md)
can put a chart back exactly. The JSON is the chart dict of flex/model.py as is, plus the app's
version: everything the page knows.
"""
from __future__ import annotations

import json
from xml.sax.saxutils import escape, quoteattr

from . import model


def _attrs(d: dict) -> str:
    return "".join(f" {k}={quoteattr(str(v))}" for k, v in d.items() if v not in (None, "", False))


def _el(tag: str, attrs: dict | None = None, text: str | None = None, inner: str = "") -> str:
    a = _attrs(attrs or {})
    if text is None and not inner:
        return f"<{tag}{a}/>"
    return f"<{tag}{a}>{escape(text) if text is not None else ''}{inner}</{tag}>"


def _header_rows(cols: list[dict]) -> list[list[tuple[str, int]]]:
    depth = max([len(c.get("path") or []) for c in cols], default=0)
    rows: list[list[tuple[str, int]]] = []
    for d in range(depth):
        row: list[tuple[str, int]] = []
        for c in cols:
            path = c.get("path") or []
            name = path[d] if d < len(path) else ""
            key = "/".join(path[: d + 1])
            if row and name and row[-1][0] == key:
                row[-1] = (key, row[-1][1] + 1, row[-1][2])
            else:
                row.append((key, 1, name))
        rows.append([(name, span) for key, span, name in row])
    rows.append([(c.get("name", ""), 1) for c in cols])
    return rows


def _layout(row: dict, cols: list[dict]) -> list[tuple[dict, int, list[dict]]]:
    by_col: dict[int, list[dict]] = {}
    for c in row.get("cells") or []:
        by_col.setdefault(int(c.get("colN") or 0), []).append(c)
    out: list[tuple[dict, int, list[dict]]] = []
    i = 0
    while i < len(cols):
        col = cols[i]
        parts = by_col.get(int(col["n"]), [])
        span = 1
        # FLEx merges a cell with its ONE neighbour, when that is empty (chart.js layoutRow)
        if any(p.get("mergeAfter") for p in parts) and i + 1 < len(cols) and not by_col.get(int(cols[i + 1]["n"])):
            span += 1
        if any(p.get("mergeBefore") for p in parts) and out and not out[-1][2]:
            out.pop()
            span += 1
        out.append((col, span, parts))
        i += span
    return out


def discourse_xml(chart: dict, rows: tuple | list | None = None, app: str = "") -> str:
    """The chart (or rows a..b of it, 1-based inclusive) in FieldWorks' discourse-chart XML."""
    vern = (chart.get("ws") or {}).get("vern") or {}
    anal = (chart.get("ws") or {}).get("anal") or {}
    vt, at = vern.get("tag") or "", anal.get("tag") or ""
    cols = (chart.get("template") or {}).get("columns") or []
    all_rows = chart.get("rows") or []
    if rows:
        a, b = int(rows[0] or 1), int(rows[1] or rows[0] or 1)
        all_rows = [r for r in all_rows if a <= int(r.get("n") or 0) <= b]
    by_group = {c["guid"]: (r, c) for r in chart.get("rows") or [] for c in r.get("cells") or [] if c.get("kind") == "words"}
    by_row_guid = {r["guid"]: r for r in chart.get("rows") or []}
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<document>"]
    out.append("<chart" + _attrs({"guid": chart.get("guid"), "text": chart.get("text"), "name": chart.get("name"), "title": chart.get("title"),
                                 "template": (chart.get("template") or {}).get("name"), "generator": app}) + ">")
    for hi, hr in enumerate(_header_rows(cols), 1):
        cells = ["<cell cols=\"1\"><main/></cell>"]
        for name, span in hr:
            cells.append(f'<cell cols="{span}"><main>' + (_el("lit", {"lang": at}, name) if name else "") + "</main></cell>")
        out.append(f'<row type="title{hi}">' + "".join(cells) + "</row>")
    for r in all_rows:
        ra = {"type": r.get("clause") or "normal", "id": r.get("label"), "guid": r.get("guid")}
        if r.get("endPara"):
            ra["endPara"] = "true"
        if r.get("endSent"):
            ra["endSent"] = "true"
        cells = ['<cell cols="1"><main>' + _el("rownum", {"lang": at}, r.get("label", "")) + "</main></cell>"]
        for col, span, parts in _layout(r, cols):
            main: list[str] = []
            glosses: list[str] = []
            guids = [p.get("guid", "") for p in parts]
            for p in parts:
                k = p.get("kind")
                if k == "words":
                    moved = any(c.get("kind") == "moved" and c.get("target") == p.get("guid") for rr in chart.get("rows") or [] for c in rr.get("cells") or [])
                    for w in p.get("words") or []:
                        if w.get("punct"):
                            main.append(_el("lit", {"lang": vt}, w.get("txt", "")))
                            continue
                        wa = {"lang": vt}
                        if moved:
                            wa["moved"] = "true"
                        if w.get("guid"):
                            wa["guid"] = w["guid"]
                        main.append(_el("word", wa, w.get("txt", "")))
                        glosses.append(_el("gloss", {"lang": at}, w.get("gls", "")))
                elif k == "moved":
                    t = by_group.get(p.get("target", ""))
                    main.append(_el("moveMkr", {"lang": at, "target": t[1].get("guid") if t else p.get("target")}, "Preposed" if p.get("preposed") else "Postposed"))
                elif k == "clause":
                    labels = p.get("labels") or [by_row_guid[g]["label"] for g in p.get("rows") or [] if g in by_row_guid]
                    main.append(_el("lit", {"lang": at, "noSpaceAfter": "true"}, "["))
                    for i, lab in enumerate(labels[:1] + labels[-1:] if len(labels) > 1 else labels):
                        if i:
                            main.append(_el("lit", {"lang": at}, "-"))
                        main.append(_el("clauseMkr", {"target": lab, "lang": at}, lab))
                    main.append(_el("lit", {"lang": at, "noSpaceBefore": "true"}, "]"))
                elif k == "tag":
                    tag = p.get("tag") or {}
                    main.append(_el("lit", {"lang": at, "noSpaceAfter": "true"}, "["))
                    main.append(_el("listRef", {"lang": at, "guid": tag.get("guid")}, tag.get("abbr") or tag.get("name") or ""))
                    main.append(_el("lit", {"lang": at, "noSpaceBefore": "true"}, "]"))
            ca = {"cols": str(span), "col": col.get("guid"), "guid": " ".join(g for g in guids if g)}
            cells.append("<cell" + _attrs(ca) + "><main>" + "".join(main) + "</main>" + (f"<glosses>{''.join(glosses)}</glosses>" if glosses else "") + "</cell>")
        if (r.get("notes") or "").strip():
            cells.append('<cell cols="1"><main>' + _el("note", {"lang": at}, r["notes"]) + "</main></cell>")
        out.append("<row" + _attrs(ra) + ">" + "".join(cells) + "</row>")
    out.append("</chart>")
    langs = []
    if vt:
        la = {"lang": vt, "font": vern.get("font", ""), "vernacular": "true"}
        if vern.get("rtl"):
            la["RightToLeft"] = "true"
        langs.append(_el("language", la))
    if at:
        la = {"lang": at, "font": anal.get("font", "")}
        if anal.get("rtl"):
            la["RightToLeft"] = "true"
        langs.append(_el("language", la))
    out.append("<languages>" + "".join(langs) + "</languages>")
    out.append("</document>")
    return "\n".join(out) + "\n"


def chart_json(chart: dict, rows: tuple | list | None = None, app: str = "") -> str:
    """The chart as this app holds it (flex/model.py), every GUID included; `rows` keeps a..b."""
    out = dict(chart)
    out.pop("cached", None)
    out.pop("liveError", None)
    if rows:
        out = model.slice_chart(out, int(rows[0] or 1), int(rows[1] or rows[0] or 1))
    out["generator"] = app
    out["format"] = "flex-scratchpad-chart/1"
    return json.dumps(out, ensure_ascii=False, indent=1) + "\n"
