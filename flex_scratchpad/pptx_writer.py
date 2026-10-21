"""A minimal .pptx writer with no dependencies (Seth, 2026-10-18: "Slideshow HTML export (and
PowerPoint?)").

Input is the DECK model the page builds from its export document (ui/js/export.js `slidesOf`):

    deck  = {title, where, project, date, slides: [slide, ...]}
    slide = {kind: 'title', title, subtitle}
          | {kind: 'text', title, blocks: [h / p / quote / list / code / hr blocks]}
          | {kind: 'object', title, lead?, blocks: [one interlinear / chart / table / entry / image block]}

(the block shapes are the export document's, see docx_writer.py). One 16:9 slide per entry: a
title bar, then text as paragraphs, an interlinear example as a borderless table per line (the
words across, their glosses under them), a text chart as a table (its header rows merged over
their groups, a cell's words on one line and their glosses on the next, the markers, the free
translations, a chart note's custom columns, the rows' colours), a Markdown table as a bordered
table, a picture as itself. Examples and charts are MEASURED (see "measuring"):
wrapped, shrunk to 12 pt, and continued on "(cont.)" slides rather than squeezed or drawn over each other.
A slide may also be {kind: 'mixed', title, blocks: [any of them]} — the blocks the user put on one
slide in the export dialog (export.js slidesOf with a plan), stacked top to bottom with the room
shared out by what each needs. An example or chart whose block carries `audio: {src}` gets its
recording as PLAYABLE MEDIA beside it (Seth, 2026-10-20) — `media(src)` (Api.export_note_pptx)
returns its bytes, mime and extension (.m4a / .mp3 / .wav: what PowerPoint plays) — a round ▶ that
plays it on a click in the slide show, with PowerPoint's own player bar. `deck.theme` recolours the
deck (background, text, accent, the example colours, the font; export.js SLIDE_THEMES).

The package is the smallest PowerPoint accepts: a presentation, one slide master with one blank
layout, a theme, the slides. Checked by tests/test_pptx.py (well-formed parts, the relationships,
the content) and opened with LibreOffice during development.
"""
from __future__ import annotations

import base64
import io
import re
import threading
import unicodedata
import zipfile
import zlib
from xml.sax.saxutils import escape

SLIDE_W, SLIDE_H = 12192000, 6858000          # 16:9, EMU
MARGIN = 457200                               # ½ inch
CONTENT_W = SLIDE_W - 2 * MARGIN
TITLE_H = 760000
BODY_Y = MARGIN + TITLE_H + 120000
BODY_H = SLIDE_H - BODY_Y - MARGIN
EMU_PER_PT = 12700
AUDIO_SIZE = 457200                           # the ▶ of a recording, ½ inch
TEXT_TYPES = ("h", "p", "quote", "list", "code", "hr")

VERN, GLOSS, MUTED, POS, MORPH = "00379C", "2A6E2A", "68717D", "7A3E9D", "4A4F57"

_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _t(s) -> str:
    return escape(_BAD.sub("", str(s if s is not None else "")))


def _hex(c) -> str:
    c = str(c or "").strip()
    if c.startswith("#") and len(c) in (4, 7):
        if len(c) == 4:
            c = "#" + "".join(ch * 2 for ch in c[1:])
        return c[1:].upper()
    return {"red": "C0392B", "green": "1F7A4D", "blue": "1F4F8F", "yellow": "FFF2A8"}.get(c.lower(), "")


def _plain(runs) -> str:
    return "".join(str(r.get("text") or "") for r in (runs or []))


# ----------------------------------------------------------------------------- the theme
DEFAULT_THEME = {"bg": "FFFFFF", "fg": "1A1D21", "accent": "1F4F8F", "titleFg": "FFFFFF", "sub": "CFE0FF", "rule": "E8EBEF",
                 "panel": "F3F4F6", "vern": VERN, "gloss": GLOSS, "pos": POS, "morph": MORPH, "muted": MUTED, "font": "Segoe UI"}
_TH: dict = dict(DEFAULT_THEME)
_CMAP: dict = {}          # the default palette's colours → the theme's (run colours, fills, borders)


def _set_theme(theme: dict | None) -> None:
    global _TH, _CMAP
    th = dict(DEFAULT_THEME)
    for k, v in (theme or {}).items():
        if k == "font":
            if v:
                th[k] = str(v)[:60]
        elif _hex(v):
            th[k] = _hex(v)
    _TH = th
    pairs = {VERN: "vern", GLOSS: "gloss", POS: "pos", MORPH: "morph", MUTED: "muted", "1A1D21": "fg", "E8EBEF": "rule", "D9DDE3": "rule", "F3F4F6": "panel",
             "A8B0BA": "muted", "4A4F57": "morph", "1F4F8F": "accent", "C9CED6": "rule"}
    # only what the theme changes: the default theme writes exactly what it always did
    _CMAP = {k: th[v] for k, v in pairs.items() if th[v] != DEFAULT_THEME[v] and th[v] != k}


def _remap(c: str) -> str:
    return _CMAP.get(c, c) if c else c


# ----------------------------------------------------------------------------- DrawingML text
def run_xml(r: dict, size: int, base: dict | None = None) -> str:
    """One <a:r> (or <a:br/> for a bare newline). `size` in hundredths of a point."""
    base = base or {}
    text = str(r.get("text") or "")
    if text == "\n":
        return "<a:br/>"
    if not text:
        return ""
    attrs = f' lang="en-US" sz="{int(r.get("size") * 100) if r.get("size") else size}" dirty="0"'
    if r.get("b") or base.get("b"):
        attrs += ' b="1"'
    if r.get("i") or base.get("i"):
        attrs += ' i="1"'
    if r.get("u") or base.get("u"):
        attrs += ' u="sng"'
    if r.get("s"):
        attrs += ' strike="sngStrike"'
    inner = ""
    color = _remap(_hex(r.get("color") or base.get("color"))) or (_TH["fg"] if _TH["fg"] != DEFAULT_THEME["fg"] else "")   # table cells do not inherit the theme's text colour everywhere
    if color:
        inner += f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
    hl = r.get("hl")
    if hl:
        inner += f'<a:highlight><a:srgbClr val="{_hex(hl) if _hex(hl) else "FFF2A8"}"/></a:highlight>'
    font = r.get("font") or base.get("font") or ("Consolas" if r.get("code") else "")
    if font:
        inner += f'<a:latin typeface="{_t(font)}"/><a:cs typeface="{_t(font)}"/>'
    parts = text.split("\n")
    out = []
    for i, part in enumerate(parts):
        if i:
            out.append("<a:br/>")
        if part:
            out.append(f"<a:r><a:rPr{attrs}>{inner}</a:rPr><a:t>{_t(part)}</a:t></a:r>")
    return "".join(out)


def para_xml(runs, size: int, align: str = "", bullet: str = "", level: int = 0, space_after: int = 600, base: dict | None = None) -> str:
    ppr = f'<a:pPr lvl="{level}"' + (f' algn="{align}"' if align else "") + (f' marL="{342900 * (level + 1)}" indent="-342900"' if bullet else "") + ">"
    ppr += f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
    ppr += (f'<a:buFont typeface="Arial"/><a:buChar char="{_t(bullet)}"/>' if bullet and bullet != "#" else '<a:buAutoNum type="arabicPeriod"/>' if bullet == "#" else "<a:buNone/>")
    ppr += "</a:pPr>"
    body = "".join(run_xml(r, size, base) for r in (runs or []))
    return f"<a:p>{ppr}{body}<a:endParaRPr lang=\"en-US\" sz=\"{size}\"/></a:p>"


def text_box(sid: int, name: str, x: int, y: int, w: int, h: int, paras: list[str], anchor: str = "t", autofit: bool = True) -> str:
    body = (f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}">'
            + ("<a:normAutofit/>" if autofit else "") + "</a:bodyPr><a:lstStyle/>" + "".join(paras) + "</p:txBody>")
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_t(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>{body}</p:sp>')


def _line(tag: str, color: str, w: int = 6350) -> str:
    color = _remap(color)
    if not color:
        return f"<a:{tag}><a:noFill/></a:{tag}>"
    return f'<a:{tag} w="{w}" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:prstDash val="solid"/></a:{tag}>'


def table_xml(sid: int, name: str, x: int, y: int, w: int, widths: list[int], rows: list[list[dict | None]], row_h, border: str = "E8EBEF", size: int = 1200) -> str:
    """rows: per row a list of cells; a cell is {paras: [xml], fill, span, rowspan, anchor} or
    {merged: 'h'|'v'} for a covered position (PowerPoint needs every cell written). `row_h`: one
    height for every row, or a list of them."""
    hs = list(row_h) if isinstance(row_h, (list, tuple)) else [row_h] * len(rows)
    hs = (hs + [hs[-1] if hs else 300000] * len(rows))[:len(rows)]
    total = sum(widths) or w
    if total > w:                                    # never wider than the slide; narrower is fine
        widths = [int(c * w / total) for c in widths]
    out = [f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{sid}" name="{_t(name)}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
           f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{sum(widths)}" cy="{sum(hs)}"/></p:xfrm>'
           '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/>'
           "<a:tblGrid>" + "".join(f'<a:gridCol w="{cw}"/>' for cw in widths) + "</a:tblGrid>"]
    for ri, row in enumerate(rows):
        out.append(f'<a:tr h="{hs[ri]}">')
        for ci in range(len(widths)):
            c = row[ci] if ci < len(row) else None
            c = c or {}
            attrs = ""
            if c.get("merged") == "h":
                attrs += ' hMerge="1"'
            if c.get("merged") == "v":
                attrs += ' vMerge="1"'
            if c.get("merged") == "hv":
                attrs += ' hMerge="1" vMerge="1"'
            if int(c.get("span") or 1) > 1:
                attrs += f' gridSpan="{int(c["span"])}"'
            if int(c.get("rowspan") or 1) > 1:
                attrs += f' rowSpan="{int(c["rowspan"])}"'
            paras = c.get("paras") or [f'<a:p><a:endParaRPr lang="en-US" sz="{size}"/></a:p>']
            tcpr = f'<a:tcPr marL="45720" marR="45720" marT="27432" marB="27432" anchor="{c.get("anchor") or "t"}">'
            tcpr += _line("lnL", border) + _line("lnR", border) + _line("lnT", border) + _line("lnB", border)
            fill = _remap(_hex(c.get("fill")))
            tcpr += f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
            tcpr += "</a:tcPr>"
            out.append(f'<a:tc{attrs}><a:txBody><a:bodyPr/><a:lstStyle/>{"".join(paras)}</a:txBody>{tcpr}</a:tc>')
        out.append("</a:tr>")
    out.append("</a:tbl></a:graphicData></a:graphic></p:graphicFrame>")
    return "".join(out)


def _text_len(runs) -> int:
    text = _plain(runs)
    return max((len(x) for x in text.split("\n")), default=0)


def fit_widths(longest: list[int], total: int, min_w: int = 500000, per_char: int = 95000) -> list[int]:
    want = [max(min_w, n * per_char + 120000) for n in longest]
    s = sum(want) or 1
    if s > total:
        want = [int(x * total / s) for x in want]
    return want


# ----------------------------------------------------------------------------- measuring
# PowerPoint draws a table exactly as it is written: it never shrinks one to its slide (Seth, 2026-10-20:
# "In HTML slideshow … it auto-resizes the example to fit. I don't know if we can get our PowerPoint export to
# do the same"; a long example came out with words broken inside their cells — "cano / e", "15. / 1" — and its
# free translation drawn over the next rows). So the writer measures: a character is ~0.58 em (combining marks
# take no room), a cell adds its margins, a line of text is 1.32 × its size; a word column is never narrower
# than its words; a line too long for the slide wraps into further row groups; the font steps down to MIN_SIZE
# until the example fits, and what still does not fit continues on "(cont.)" slides — at PAGE_SIZE then, since
# a slide that continues anyway can be read from the back of the room.
CHAR_EM = 0.52
CELL_PAD = 91440 + 60000                      # the cell's own margins, and some air
MAX_SIZE, MIN_SIZE, PAGE_SIZE = 1800, 1200, 1600   # an example's baseline: 18 pt, never under 12 pt; 16 pt once it is paged
GROUP_GAP = 70000


def _glen(text) -> int:
    return sum(1 for ch in str(text or "") if not unicodedata.combining(ch) and unicodedata.category(ch) not in ("Mn", "Me", "Cf"))


def text_w(text, size: int) -> int:
    """About how wide `text` is at `size` (hundredths of a point), in EMU."""
    return int(max((_glen(x) for x in str(text or "").split("\n")), default=0) * size * 127 * CHAR_EM)


def cell_line_h(size: int) -> int:
    return int(size * 127 * 1.32) + 54864     # + the cell's top and bottom margins


def text_line_h(size: int) -> int:
    return int(size * 127 * 1.3)


def il_units(b: dict, size: int, width: int) -> list[dict]:
    """An interlinear example measured at `size` in `width`: per line of text its row groups (as many
    words as fit across, a column per word) and then its translations and notes — each a unit with its
    height, in order, `seg` saying which line it belongs to."""
    sub, lab = max(900, size - 300), max(900, size - 600)
    segs = b.get("segments") or []
    num_w = max([text_w(sg.get("label") or str(sg.get("n") or ""), lab) + CELL_PAD for sg in segs] + [300000])
    out: list[dict] = []
    for si, sg in enumerate(segs):
        lines = sg.get("lines") or []
        ncols = max((len(ln.get("cells") or []) for ln in lines), default=0)
        col_w = [max([text_w(_plain((ln.get("cells") or [])[ci] if ci < len(ln.get("cells") or []) else []), size if ln.get("name") == "txt" else sub) for ln in lines] + [0]) + CELL_PAD for ci in range(ncols)]
        room = max(400000, width - num_w)
        col_w = [min(w, room) for w in col_w]            # one word wider than the slide: it wraps, nothing else can
        groups: list[list[int]] = []
        cur: list[int] = []
        used = 0
        for ci, w in enumerate(col_w):
            if cur and used + w > room:
                groups.append(cur)
                cur, used = [], 0
            cur.append(ci)
            used += w
        if cur:
            groups.append(cur)
        row_hs = [cell_line_h(size if ln.get("name") == "txt" else sub) for ln in lines]
        label = sg.get("label") or str(sg.get("n") or "")
        for gi, g in enumerate(groups):
            out.append({"kind": "grp", "seg": si, "cols": g, "lines": lines, "col_w": col_w, "num_w": num_w, "width": width, "row_hs": row_hs,
                        "label": label if gi == 0 else "", "size": size, "sub": sub, "lab": lab, "h": sum(row_hs) + GROUP_GAP})
        for key, lab_text in (("free", "Free"), ("lit", "Lit."), ("notes", "Note")):
            vals = sg.get(key)
            if not vals:
                continue
            for v in (vals if key == "notes" else [vals]):
                runs = v if isinstance(v, list) else [{"text": str(v)}]
                n = max(1, -(-text_w(lab_text + "  " + _plain(runs), sub) // max(1, width - num_w)))
                out.append({"kind": "tr", "seg": si, "key": key, "lab_text": lab_text, "runs": runs, "num_w": num_w, "width": width, "sub": sub,
                            "h": n * text_line_h(sub) + 50000})
        if out:
            out[-1]["h"] += cell_line_h(sub) // 2          # room between two lines of text
    return out


def il_fit(b: dict, width: int, room: int) -> tuple[int, list[dict]]:
    """The largest size (18 pt down to 12 pt) at which the example fits `room`; else PAGE_SIZE, and the
    caller pages its units."""
    for size in range(MAX_SIZE, MIN_SIZE - 1, -100):
        units = il_units(b, size, width)
        if sum(u["h"] for u in units) <= room:
            return size, units
    return PAGE_SIZE, il_units(b, PAGE_SIZE, width)


def chart_widths(b: dict, width: int, size: int) -> list[int]:
    """A chart's column widths, the same on every page: from its headings and its cells' words."""
    headers = b.get("headers") or []
    ncols = int(b.get("cols") or 0)
    xcols = b.get("xcols") or []
    x_left = [x for x in xcols if x.get("side") == "left"]
    x_right = [x for x in xcols if x.get("side") != "left"]
    nl = len(x_left)
    longest = [3] + [max(4, len(x.get("name") or "")) for x in x_left] + [4] * ncols + [max(4, len(x.get("name") or "")) for x in x_right] + ([12] if b.get("freeCol") else []) + ([10] if b.get("notesCol") else [])
    if headers:                                         # a column at least as wide as its heading
        c = 1 + nl
        for h in headers[-1]:
            if int(h.get("span") or 1) == 1 and c <= ncols + nl:
                longest[c] = max(longest[c], len(h.get("text") or ""))
            c += int(h.get("span") or 1)
    for r in b.get("rows") or []:
        for c in r.get("cells") or []:
            pl = c.get("plain") or {}
            n = max(len(pl.get("txt") or ""), len(pl.get("gls") or ""))
            col = int(c.get("col") or 0)
            if 1 <= col <= ncols and int(c.get("span") or 1) == 1:
                longest[col + nl] = max(longest[col + nl], min(28, n))
    widths = fit_widths(longest, width, min_w=380000, per_char=int(size * 0.6 * 127))
    if sum(widths) < width:                             # a chart fills the slide's width
        widths = [int(w * width / sum(widths)) for w in widths]
    return widths


def _chart_cell_lines(cell: dict, w: int, size: int) -> int:
    """How many lines a chart cell takes in a column `w` wide: its words' lines, wrapped, and its markers."""
    tiers: list[str] = []
    for word in cell.get("words") or []:
        parts = _plain(word).split("\n")
        for li, part in enumerate(parts):
            while len(tiers) <= li:
                tiers.append("")
            tiers[li] += ("  " if tiers[li] else "") + part
    room = max(1, w - CELL_PAD)
    n = sum(max(1, -(-text_w(t, size if li == 0 else max(800, size - 200)) // room)) for li, t in enumerate(tiers))
    if cell.get("marks"):
        n += 1
    return max(1, n)


def chart_row_heights(b: dict, body: list, size: int, widths: list[int]) -> list[int]:
    """The height of every table row of a page of the chart: the header rows, then each row (and its
    translation row) as tall as its tallest cell."""
    ncols = int(b.get("cols") or 0)
    nl = len([x for x in b.get("xcols") or [] if x.get("side") == "left"])
    out = []
    for hr in b.get("headers") or []:
        n = 1
        c = 1 + nl
        for h in hr:
            span = int(h.get("span") or 1)
            w = sum(widths[c:c + span]) if c < len(widths) else widths[-1]
            n = max(n, -(-text_w(h.get("text") or "", size) // max(1, w - CELL_PAD)))
            c += span
        out.append(n * cell_line_h(size) - 30000)
    for r in body:
        n = 1
        c = 1 + nl
        for cell in r.get("cells") or []:
            span = int(cell.get("span") or 1)
            if c < len(widths):
                n = max(n, _chart_cell_lines(cell, sum(widths[c:c + span]), size))
            c += span
        for xc in r.get("xcells") or []:
            n = max(n, len(str(xc.get("text") or "").split("\n")))
        out.append(n * text_line_h(size) + 54864 + 20000)
        fr = r.get("freeRow")
        if fr and (fr.get("text") or "").strip():
            out.append(max(1, -(-text_w(fr["text"], size) // max(1, sum(widths[1:]) - CELL_PAD))) * text_line_h(size) + 54864)
    del ncols
    return out


def chart_chunks(b: dict, width: int, room_first: int, room_next: int) -> list[tuple[list, int]]:
    """The chart's rows as pages: [(rows, size)] — the whole chart on one slide at the largest size from
    12 pt down to 9 pt that fits, else pages of rows at 10 pt, the header rows on each."""
    rows = b.get("rows") or []
    for size in range(1200, 899, -100):
        if sum(chart_row_heights(b, rows, size, chart_widths(b, width, size))) <= room_first:
            return [(rows, size)]
    size = 1000
    widths = chart_widths(b, width, size)
    head = sum(chart_row_heights(b, [], size, widths))
    pages: list[tuple[list, int]] = []
    cur: list = []
    used, room = head, room_first
    for r in rows:
        h = sum(chart_row_heights(b, [r], size, widths)) - head
        if cur and used + h > room:
            pages.append((cur, size))
            cur, used, room = [], head, room_next
        cur.append(r)
        used += h
    if cur:
        pages.append((cur, size))
    return pages


# ----------------------------------------------------------------------------- a slide's content
class _SlideBuilder:
    def __init__(self, deck: "Pptx", n: int):
        self.deck = deck
        self.n = n
        self.shapes: list[str] = []
        self.rels: list[tuple[str, str, str]] = []           # (id, type, target)
        self.next_id = 2
        self.bg = "" if _TH["bg"] == "FFFFFF" else _TH["bg"]
        self.w = CONTENT_W                                   # the width an object may take (less beside its ▶)
        self.audio_ids: list[int] = []

    def sid(self) -> int:
        self.next_id += 1
        return self.next_id

    # -- slide kinds ---------------------------------------------------------------------------
    def title_slide(self, s: dict):
        self.bg = _TH["accent"]
        self.shapes.append(text_box(self.sid(), "Title", MARGIN, SLIDE_H // 2 - 1100000, CONTENT_W, 1400000,
                                    [para_xml([{"text": s.get("title") or "", "b": True, "color": "#" + _TH["titleFg"]}], 4400, align="ctr")], anchor="b"))
        if s.get("subtitle"):
            self.shapes.append(text_box(self.sid(), "Subtitle", MARGIN, SLIDE_H // 2 + 400000, CONTENT_W, 800000,
                                        [para_xml([{"text": s["subtitle"], "color": "#" + _TH["sub"]}], 2000, align="ctr")]))
        self.shapes.append(text_box(self.sid(), "Credit", MARGIN, SLIDE_H - MARGIN - 300000, CONTENT_W, 300000,
                                    [para_xml([{"text": "FLEx Scratchpad", "color": "#" + _TH["sub"]}], 1100, align="ctr")]))

    def heading(self, title: str, sub: str = ""):
        runs = [{"text": title or "", "b": True}]
        if sub and sub != title:
            runs.append({"text": "   " + sub, "color": MUTED, "size": 16})
        if not title and sub:
            runs = [{"text": sub, "b": True, "color": VERN}]
        self.shapes.append(text_box(self.sid(), "Heading", MARGIN, MARGIN, CONTENT_W, TITLE_H, [para_xml(runs, 2800)], anchor="b"))
        # the rule under it
        self.shapes.append(f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{self.sid()}" name="Rule"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm><a:off x="{MARGIN}" y="{MARGIN + TITLE_H + 40000}"/><a:ext cx="{CONTENT_W}" cy="0"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="19050"><a:solidFill><a:srgbClr val="{_remap("E8EBEF")}"/></a:solidFill></a:ln></p:spPr></p:cxnSp>')

    def text_slide(self, s: dict):
        self.heading(s.get("title") or "")
        self.shapes.append(text_box(self.sid(), "Body", MARGIN, BODY_Y, CONTENT_W, BODY_H, self.text_paras(s.get("blocks") or [])))

    @staticmethod
    def text_paras(blocks: list[dict]) -> list[str]:
        paras: list[str] = []
        for b in blocks:
            t = b.get("type")
            if t == "h":
                paras.append(para_xml(b.get("runs"), 2200, base={"b": True}))
            elif t == "p":
                runs = list(b.get("runs") or [])
                if b.get("exNum"):
                    runs.insert(0, {"text": b["exNum"] + "  ", "color": MUTED})
                paras.append(para_xml(runs, 2000))
            elif t == "quote":
                paras.append(para_xml(b.get("runs"), 1900, level=1, base={"i": True, "color": MUTED}))
            elif t == "code":
                for line in str(b.get("text") or "").split("\n"):
                    paras.append(para_xml([{"text": line, "code": True}], 1400, space_after=0))
            elif t == "list":
                for it in b.get("items") or []:
                    mark = ("☑" if it.get("checked") else "☐") if it.get("task") else ("#" if it.get("ordered") else "•")
                    paras.append(para_xml(it.get("runs"), 1900, bullet=mark, level=min(4, int(it.get("level") or 0)), space_after=300))
            elif t == "hr":
                paras.append(para_xml([{"text": "— — —", "color": "C9CED6"}], 1400, align="ctr"))
        return paras

    # -- a recording beside its object ----------------------------------------------------------
    def audio(self, b: dict, y: int) -> bool:
        src = (b.get("audio") or {}).get("src")
        got = self.deck.media_of(src) if src else None
        if not got:
            return False
        data, mime, ext = got
        name = self.deck.media_names.get(src)                # the same recording twice is one part
        if not name:
            name = f"media{len(self.deck.media_names) + 1}{ext if ext in ('.m4a', '.mp3', '.wav') else '.wav'}"
            self.deck.media_names[src] = name
            self.deck.media.append((name, data))
        icon = self.deck.icon()
        base = len(self.rels) + 2
        r_link, r_media, r_img = f"rId{base}", f"rId{base + 1}", f"rId{base + 2}"
        self.rels.append((r_link, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio", f"../media/{name}"))
        self.rels.append((r_media, "http://schemas.microsoft.com/office/2007/relationships/media", f"../media/{name}"))
        self.rels.append((r_img, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", f"../media/{icon}"))
        sid = self.sid()
        self.audio_ids.append(sid)
        label = "Recording" + (" — " + str(b.get("title")) if b.get("title") else "")
        x = MARGIN + CONTENT_W - AUDIO_SIZE
        self.shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{_t(label)}" descr="{_t(label)}"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr>'
            '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
            f'<p:nvPr><a:audioFile r:link="{r_link}"/><p:extLst><p:ext uri="{{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}}">'
            f'<p14:media xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" r:embed="{r_media}"/></p:ext></p:extLst></p:nvPr></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{r_img}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{AUDIO_SIZE}" cy="{AUDIO_SIZE}"/></a:xfrm><a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
        return True

    # -- objects ------------------------------------------------------------------------------
    def il_unit(self, b: dict, u: dict, y: int):
        """One measured piece of an interlinear example (il_units): a row group of a line's words, or
        one of its translations / notes."""
        if u["kind"] == "grp":
            font = (b.get("ws") or {}).get("font") or ""
            look = {"txt": {"color": VERN, "font": font}, "morph": {"color": MORPH, "font": font}, "mgls": {"color": GLOSS}, "gls": {"color": GLOSS}, "pos": {"color": POS}, "cf": {"color": MUTED}, "tag": {"b": True}}
            size, sub, lab = u["size"], u["sub"], u["lab"]
            rows = []
            for li, ln in enumerate(u["lines"]):
                base = look.get(ln.get("name"), {})
                cells = [{"paras": [para_xml([{"text": u["label"] if li == 0 else "", "color": "A8B0BA"}], lab, space_after=0)]}]
                for ci in u["cols"]:
                    runs = ln["cells"][ci] if ci < len(ln.get("cells") or []) else []
                    cells.append({"paras": [para_xml(runs, size if ln.get("name") == "txt" else sub, space_after=0, base=base)]})
                rows.append(cells)
            self.shapes.append(table_xml(self.sid(), "Example", MARGIN, y, u["width"], [u["num_w"]] + [u["col_w"][ci] for ci in u["cols"]], rows, u["row_hs"], border="", size=size))
        else:
            runs = [{"text": u["lab_text"] + "  ", "color": "A8B0BA", "size": 9}] + [dict(x) for x in u["runs"]]
            self.shapes.append(text_box(self.sid(), u["lab_text"], MARGIN + u["num_w"], y, u["width"] - u["num_w"], u["h"], [para_xml(runs, u["sub"], space_after=0, base={"i": u["key"] != "free"})], autofit=False))

    def chart(self, b: dict, y: int, avail_h: int, body: list | None = None, size: int | None = None):
        """The chart, or the page of its rows `body` at `size` (chart_chunks): the header rows always."""
        headers = b.get("headers") or []
        ncols = int(b.get("cols") or 0)
        xcols = b.get("xcols") or []
        x_left = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") == "left"]     # custom columns left of the chart
        x_right = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") != "left"]
        nl = len(x_left)
        free_col, notes_col = bool(b.get("freeCol")), bool(b.get("notesCol"))
        total_cols = 1 + ncols + len(xcols) + (1 if free_col else 0) + (1 if notes_col else 0)
        all_rows = b.get("rows") or []
        body_rows = all_rows if body is None else body
        n_free_rows = sum(1 for r in body_rows if r.get("freeRow") and (r["freeRow"].get("text") or "").strip())
        nrows = len(headers) + len(body_rows) + n_free_rows
        row_h = 420000
        scale = min(1.0, avail_h / max(1, int((len(headers) * 300000 + len(body_rows) * row_h + n_free_rows * 260000) * 1.3)))   # rows come out taller than the sum of their lines
        size = size or max(800, int(1200 * scale))
        font = (b.get("ws") or {}).get("font") or ""
        widths = chart_widths(b, self.w, size)
        rows: list[list[dict | None]] = []
        head_fill = "F3F4F6"
        for hi, hr in enumerate(headers):
            row: list[dict | None] = [None] * total_cols
            if hi == 0:
                row[0] = {"paras": [para_xml([{"text": "#", "b": True, "color": MUTED}], size, align="ctr", space_after=0)], "fill": head_fill, "rowspan": len(headers) if len(headers) > 1 else 1}
            else:
                row[0] = {"merged": "v", "fill": head_fill}
            c = 1
            for _, x in x_left:
                if hi == 0:
                    row[c] = {"paras": [para_xml([{"text": x.get("name") or "", "b": True, "color": "1F4F8F"}], size, align="ctr", space_after=0)], "fill": "EEF2FB", "rowspan": len(headers) if len(headers) > 1 else 1}
                else:
                    row[c] = {"merged": "v", "fill": "EEF2FB"}
                c += 1
            for h in hr:
                span = int(h.get("span") or 1)
                row[c] = {"paras": [para_xml([{"text": h.get("text") or "", "b": True, "color": MUTED}], size, align="ctr", space_after=0)], "fill": head_fill, "span": span if span > 1 else 1}
                for k in range(1, span):
                    row[c + k] = {"merged": "h", "fill": head_fill}
                c += span
            extras = [(x.get("name") or "", "EEF2FB") for _, x in x_right] + ([("Free", head_fill)] if free_col else []) + ([("Notes", head_fill)] if notes_col else [])
            for label, fill in extras:
                if hi == 0:
                    row[c] = {"paras": [para_xml([{"text": label, "b": True, "color": "1F4F8F" if fill != head_fill else MUTED}], size, align="ctr", space_after=0)], "fill": fill, "rowspan": len(headers) if len(headers) > 1 else 1}
                else:
                    row[c] = {"merged": "v", "fill": fill}
                c += 1
            rows.append(row)
        for r in body_rows:
            rs = r.get("rowStyle") or {}
            row = [None] * total_cols
            row[0] = {"paras": [para_xml([{"text": r.get("label") or "", "b": True, "color": MUTED}], size, align="r", space_after=0)], "fill": rs.get("bg") or "F7F8FA"}
            c = 1
            xcells = r.get("xcells") or []

            def xcell(xc):
                return {"paras": [para_xml([{"text": xc.get("text") or "", "b": bool(xc.get("b")), "i": bool(xc.get("i")), "u": bool(xc.get("u")), "color": xc.get("color") or ""}], size, space_after=0)], "fill": xc.get("hl") or rs.get("bg") or "FBFCFF"}

            for i, _ in x_left:
                row[c] = xcell(xcells[i] if i < len(xcells) else {})
                c += 1
            for cell in r.get("cells") or []:
                words = cell.get("words") or []
                # the baseline words on one line, their glosses on the next (no nested tables in a slide)
                lines: list[list[dict]] = []
                for w in words:
                    parts: list[list[dict]] = [[]]
                    for x in w:
                        if str(x.get("text")) == "\n":
                            parts.append([])
                        else:
                            parts[-1].append(dict(x))
                    for li, part in enumerate(parts):
                        while len(lines) <= li:
                            lines.append([])
                        if lines[li]:
                            lines[li].append({"text": "  "})
                        lines[li].extend(part)
                base = {"b": bool(cell.get("b") or rs.get("b")), "i": bool(cell.get("i") or rs.get("i")), "u": bool(cell.get("u") or rs.get("u")), "color": cell.get("color") or rs.get("color") or "", "font": font}
                paras = [para_xml(ln, size if li == 0 else max(800, size - 200), space_after=0, base=dict(base, font=font if li == 0 else "")) for li, ln in enumerate(lines)]
                if cell.get("marks"):
                    paras.append(para_xml([dict(x, text=str(x.get("text") or "").strip() + " ") for x in cell["marks"]], max(800, size - 300), space_after=0))
                span = int(cell.get("span") or 1)
                row[c] = {"paras": paras, "fill": cell.get("hl") or rs.get("bg") or "", "span": span}
                for k in range(1, span):
                    row[c + k] = {"merged": "h"}
                c += span
            for i, _ in x_right:
                row[c] = xcell(xcells[i] if i < len(xcells) else {})
                c += 1
            if free_col:
                fr = r.get("free")
                left = len(body_rows) - body_rows.index(r)          # a run of rows never spans past this page
                row[c] = {"paras": [para_xml([{"text": fr["text"], "i": True}], size, space_after=0)] if fr else None, "fill": "F3F9F3", "rowspan": min(left, int(fr.get("span") or 1)) if fr else 1}
                c += 1
            if notes_col:
                row[c] = {"paras": [para_xml([{"text": r.get("notes") or "", "color": MUTED}], max(800, size - 200), space_after=0)]}
                c += 1
            rows.append(row)
            if r.get("freeRow") and (r["freeRow"].get("text") or "").strip():
                frow: list[dict | None] = [None] * total_cols
                frow[0] = {"fill": "F3F9F3"}
                frow[1] = {"paras": [para_xml([{"text": r["freeRow"]["text"], "i": True}, {"text": "   " + (r["freeRow"].get("rows") or ""), "color": MUTED, "size": 8}], size, space_after=0)], "fill": "F3F9F3", "span": total_cols - 1}
                for k in range(2, total_cols):
                    frow[k] = {"merged": "h", "fill": "F3F9F3"}
                rows.append(frow)
        # the Free column's vertical merges: the cells under a spanning Free cell
        if free_col:
            fc = total_cols - (2 if notes_col else 1)
            skip = 0
            for ri in range(len(headers), len(rows)):
                cell = rows[ri][fc]
                if skip > 0 and (cell is None or not cell.get("paras")):
                    rows[ri][fc] = {"merged": "v", "fill": "F3F9F3"}
                    skip -= 1
                    continue
                skip = max(0, int((cell or {}).get("rowspan") or 1) - 1)
        self.shapes.append(table_xml(self.sid(), "Chart", MARGIN, y, self.w, widths, rows, chart_row_heights(b, body_rows, size, widths) if body is not None else max(230000, int(row_h * max(scale, 0.55))), border="E8EBEF", size=size))
        del nrows

    def table(self, b: dict, y: int, avail_h: int):
        rows_in = b.get("rows") or []
        if not rows_in:
            return
        ncols = max(len(r) for r in rows_in)
        style = b.get("style") or {}
        cols, rst = style.get("cols") or {}, style.get("rows") or {}
        row_h = 400000
        scale = min(1.0, avail_h / max(1, len(rows_in) * row_h))
        size = max(900, int(1600 * scale))
        longest = [max((_text_len(r[ci].get("runs")) if ci < len(r) and not r[ci].get("blocks") else 12 for r in rows_in), default=1) for ci in range(ncols)]
        widths = fit_widths([min(40, n) for n in longest], self.w, min_w=600000, per_char=int(size * 0.6 * 127))
        rows = []
        for ri, r in enumerate(rows_in):
            out: list[dict | None] = []
            for ci in range(ncols):
                c = r[ci] if ci < len(r) else {}
                if c.get("covered"):
                    out.append({"merged": "h" if ci and (r[ci - 1].get("colspan") or r[ci - 1].get("covered")) else "v"})
                    continue
                col, rs = cols.get(str(ci + 1), {}) or {}, rst.get(str(ri + 1), {}) or {}
                header = ri == 0 and b.get("header", True)
                base = {"b": bool(header or rs.get("bold") or col.get("bold")), "i": bool(rs.get("italic") or col.get("italic")), "color": rs.get("color") or col.get("color") or ("" if not header else MUTED)}
                if c.get("blocks"):
                    text = "\n".join(_plain(x.get("runs")) if x.get("runs") else (x.get("title") or x.get("headword") or "") for x in c["blocks"])
                    paras = [para_xml([{"text": text}], size, space_after=0, base=base)]
                else:
                    paras = [para_xml(c.get("runs"), size, align={"center": "ctr", "right": "r"}.get(rs.get("align") or col.get("align") or ((b.get("aligns") or [None] * ncols)[ci] if ci < len(b.get("aligns") or []) else None), ""), space_after=0, base=base)]
                out.append({"paras": paras, "fill": rs.get("bg") or col.get("bg") or ("F3F4F6" if header else ""), "span": int(c.get("colspan") or 1), "rowspan": int(c.get("rowspan") or 1)})
            rows.append(out)
        self.shapes.append(table_xml(self.sid(), "Table", MARGIN, y, self.w, widths, rows, max(260000, int(row_h * max(scale, 0.6))), border="D9DDE3", size=size))

    def entry(self, b: dict, y: int, avail_h: int):
        paras = [para_xml([{"text": b.get("headword") or "", "b": True, "color": VERN, "font": b.get("font") or ""}, {"text": ("  " + b["pos"]) if b.get("pos") else "", "i": True, "color": MUTED}], 2600)]
        for s in b.get("senses") or []:
            paras.append(para_xml([{"text": (s.get("number") or "") + "  ", "color": "A8B0BA"}, {"text": (s["pos"] + " ") if s.get("pos") else "", "i": True, "color": MUTED}, {"text": s.get("gloss") or "", "b": True, "color": GLOSS}, {"text": (" — " + s["definition"]) if s.get("definition") and s.get("definition") != s.get("gloss") else ""}], 1900, level=min(4, int(s.get("level") or 0))))
            for ex in s.get("examples") or []:
                paras.append(para_xml([{"text": ex.get("text") or "", "color": VERN, "font": b.get("font") or ""}, {"text": ("  ‘" + ex["translation"] + "’") if ex.get("translation") else "", "color": MUTED}], 1700, level=min(4, int(s.get("level") or 0) + 1), space_after=300))
        self.shapes.append(text_box(self.sid(), "Entry", MARGIN, y, self.w, avail_h, paras))

    def image(self, b: dict, y: int, avail_h: int):
        png = b.get("png") or ""
        if not png.startswith("data:image/png;base64,"):
            self.shapes.append(text_box(self.sid(), "Picture", MARGIN, y, self.w, 400000, [para_xml([{"text": "[picture: " + (b.get("alt") or b.get("src") or "") + "]", "color": MUTED}], 1400)]))
            return
        data = base64.b64decode(png.split(",", 1)[1])
        name = f"image{len(self.deck.media) + 1}.png"
        self.deck.media.append((name, data))
        rid = f"rId{len(self.rels) + 2}"
        self.rels.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", f"../media/{name}"))
        w, h = int(b.get("width") or 800), int(b.get("height") or 450)
        k = min(self.w / max(1, w * 9525), avail_h / max(1, h * 9525), 1.0)
        cw, ch = int(w * 9525 * k), int(h * 9525 * k)
        self.shapes.append(f'<p:pic><p:nvPicPr><p:cNvPr id="{self.sid()}" name="Picture"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                           f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                           f'<p:spPr><a:xfrm><a:off x="{MARGIN + (self.w - cw) // 2}" y="{y}"/><a:ext cx="{cw}" cy="{ch}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')

    # -- the part -----------------------------------------------------------------------------
    def xml(self) -> str:
        bg = f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{self.bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>' if self.bg else ""
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld>{bg}<p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
                + "".join(self.shapes) + "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>" + self.timing() + "</p:sld>")

    def timing(self) -> str:
        """The media nodes PowerPoint wants for each recording on the slide (what it writes for an
        inserted audio file): the player knows its shape; a click on the ▶ plays it (hlinkClick)."""
        if not self.audio_ids:
            return ""
        nodes, cid = [], 2
        for sid in self.audio_ids:
            nodes.append(f'<p:audio><p:cMediaNode vol="80000"><p:cTn id="{cid}" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
                         f'<p:endCondLst><p:cond evt="onStopAudio" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:endCondLst></p:cTn>'
                         f'<p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl></p:cMediaNode></p:audio>')
            cid += 1
        return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
                + "".join(nodes) + "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>")

    def rels_xml(self) -> str:
        rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>']
        rels += [f'<Relationship Id="{rid}" Type="{typ}" Target="{tgt}"/>' for rid, typ, tgt in self.rels]
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>"


# ----------------------------------------------------------------------------- the package
THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="FLEx Scratchpad"><a:themeElements>'
         '<a:clrScheme name="Scratchpad"><a:dk1><a:srgbClr val="@FG@"/></a:dk1><a:lt1><a:srgbClr val="@BG@"/></a:lt1><a:dk2><a:srgbClr val="@ACCENT@"/></a:dk2><a:lt2><a:srgbClr val="@PANEL@"/></a:lt2>'
         '<a:accent1><a:srgbClr val="1F4F8F"/></a:accent1><a:accent2><a:srgbClr val="2A6E2A"/></a:accent2><a:accent3><a:srgbClr val="7A3E9D"/></a:accent3><a:accent4><a:srgbClr val="C0392B"/></a:accent4><a:accent5><a:srgbClr val="00379C"/></a:accent5><a:accent6><a:srgbClr val="68717D"/></a:accent6>'
         '<a:hlink><a:srgbClr val="1F4F8F"/></a:hlink><a:folHlink><a:srgbClr val="7A3E9D"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="Scratchpad"><a:majorFont><a:latin typeface="@FONT@"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="@FONT@"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="Scratchpad"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
         '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
         '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
         '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>'
         '</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')

_SPTREE = '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree>'
_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          f'<p:sldMaster {_NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>{_SPTREE}</p:cSld>'
          '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
          '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
          '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="2800"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
LAYOUT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          f'<p:sldLayout {_NS} type="blank" preserve="1"><p:cSld name="Blank">{_SPTREE}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


class Pptx:
    def __init__(self, media=None):
        self.slides: list[_SlideBuilder] = []
        self.media: list[tuple[str, bytes]] = []
        self._media_fn = media
        self._media_ok: dict[str, bool] = {}
        self.media_names: dict[str, str] = {}
        self._icon = ""

    def media_of(self, src: str):
        """(bytes, mime, ext) of a recording, or None (no resolver, or it is not there)."""
        if not self._media_fn:
            return None
        try:
            got = self._media_fn(src)
        except Exception:  # noqa: BLE001 — a recording that cannot be read leaves the slide without a player
            return None
        return got if got and got[0] else None

    def icon(self) -> str:
        if not self._icon:
            self._icon = "audio-play.png"
            self.media.append((self._icon, audio_icon_png(bg=tuple(int(_TH["accent"][i:i + 2], 16) for i in (0, 2, 4)))))
        return self._icon

    def add(self, s: dict):
        kind = s.get("kind")
        if kind in ("object", "mixed"):
            self.add_paged(s)
            return
        b = _SlideBuilder(self, len(self.slides) + 1)
        if kind == "title":
            b.title_slide(s)
        else:
            b.text_slide(s)
        self.slides.append(b)

    def has_media(self, b: dict) -> bool:
        src = (b.get("audio") or {}).get("src")
        if not src:
            return False
        if src not in self._media_ok:
            self._media_ok[src] = bool(self.media_of(src))
        return self._media_ok[src]

    def add_paged(self, s: dict):
        """An object slide or a mixed one, MEASURED (see "measuring" above): its blocks become pieces of
        known height — a text group, each row group and translation of an example, a page of a chart's
        rows, a table, an entry, a picture — laid down the slide in order; a piece that does not fit
        starts a "(cont.)" slide. An example's line and a chart's page stay together where they can."""
        blocks = s.get("blocks") or []
        cap = SLIDE_H - MARGIN - BODY_Y
        lead = s.get("lead")
        lead_h = 480000 if lead else 0
        objs = [b for b in blocks if b.get("type") not in TEXT_TYPES]
        single = len(blocks) == 1
        b0 = objs[0] if objs else {}
        t0 = b0.get("type")
        sub = (b0.get("title") if t0 == "interlinear" else ((b0.get("name") or "Chart") + " · " + (b0.get("title") or "")) if t0 == "chart" else (b0.get("headword") or "") if t0 == "entry" else "") if single else ""
        room_first = cap - lead_h

        def piece(h, draw, obj=None, width=CONTENT_W):
            return {"h": int(h), "draw": draw, "obj": obj, "width": width}
        def make_chunks(il_size):
            chunks: list[list[dict]] = []                  # each a run of pieces that should share a slide
            text_run: list[dict] = []

            def flush_text():
                if text_run:
                    bs = list(text_run)
                    chunks.append([piece(min(_need("text", bs), cap), lambda bl, y, h, bs=bs: bl.shapes.append(text_box(bl.sid(), "Text", MARGIN, y, CONTENT_W, h, bl.text_paras(bs))))])
                    text_run.clear()
            for b in blocks:
                t = b.get("type")
                if t in TEXT_TYPES:
                    text_run.append(b)
                    continue
                flush_text()
                width = CONTENT_W - (AUDIO_SIZE + 160000 if t in ("interlinear", "chart") and self.has_media(b) else 0)
                if t == "interlinear":
                    units = il_units(b, il_size, width) if il_size else il_fit(b, width, room_first if single else cap)[1]
                    by_seg: dict[int, list[dict]] = {}
                    for u in units:
                        by_seg.setdefault(u["seg"], []).append(u)
                    for si in sorted(by_seg):
                        chunks.append([piece(u["h"], lambda bl, y, h, b=b, u=u: bl.il_unit(b, u, y), b, width) for u in by_seg[si]])
                elif t == "chart":
                    for rows, size in chart_chunks(b, width, room_first if single else cap, cap):
                        h = sum(chart_row_heights(b, rows, size, chart_widths(b, width, size))) + 40000
                        chunks.append([piece(h, lambda bl, y, h, b=b, rows=rows, size=size: bl.chart(b, y, h, body=rows, size=size), b, width)])
                elif t == "table":
                    chunks.append([piece(min(_need("obj", [b]), cap), lambda bl, y, h, b=b: bl.table(b, y, h))])
                elif t == "entry":
                    chunks.append([piece(min(_need("obj", [b]), cap), lambda bl, y, h, b=b: bl.entry(b, y, h))])
                elif t == "wordform":
                    chunks.append([piece(600000, lambda bl, y, h, b=b: bl.shapes.append(text_box(bl.sid(), "Wordform", MARGIN, y, CONTENT_W, 600000, [para_xml([{"text": b.get("form") or "", "b": True, "color": VERN}, {"text": "  " + "; ".join(b.get("glosses") or []), "color": GLOSS}], 2200)])))])
                elif t in ("image", "imageref"):
                    chunks.append([piece(min(3200000, cap), lambda bl, y, h, b=b: bl.image(b, y, h))])
            flush_text()
            return chunks

        # several blocks on one slide shrink TOGETHER (to 12 pt at most) before anything moves to a "(cont.)"
        # slide, as the web slideshow fits its slide; one object finds its own largest size
        chunks = make_chunks(None)
        if not single and any(b.get("type") == "interlinear" for b in blocks):
            total = lambda cs: sum(sum(p["h"] for p in ch) for ch in cs) + 90000 * sum(1 for a, c in zip(cs, cs[1:]) if c[0]["obj"] is None or c[0]["obj"] is not a[0]["obj"])  # noqa: E731
            if total(chunks) > room_first:
                for size in range(MAX_SIZE, MIN_SIZE - 1, -100):
                    cs = make_chunks(size)
                    if total(cs) <= room_first:
                        chunks = cs
                        break
                else:
                    chunks = make_chunks(PAGE_SIZE)
        # lay the pieces down, slide by slide
        pages: list[list[tuple[dict, int]]] = [[]]
        gap = 90000
        y, bottom = BODY_Y + lead_h, SLIDE_H - MARGIN

        def new_page():
            nonlocal y
            pages.append([])
            y = BODY_Y
        prev_obj = object()
        for ch in chunks:
            obj = ch[0]["obj"]
            if obj is not None and obj is prev_obj:
                y -= gap                                   # the lines of one example follow each other (il_units has their spacing)
            prev_obj = obj
            need = sum(p["h"] for p in ch)
            if pages[-1] and y + need > bottom:
                new_page()
            for p in ch:
                if pages[-1] and y + p["h"] > bottom + 20000:
                    new_page()
                pages[-1].append((p, y))
                y += p["h"]
            y += gap
        for pi, placed in enumerate(pages):
            if not placed and pi:
                continue
            bl = _SlideBuilder(self, len(self.slides) + 1)
            bl.heading((s.get("title") or "") + (" (cont.)" if pi else ""), sub)
            if pi == 0 and lead:
                bl.shapes.append(text_box(bl.sid(), "Lead", MARGIN, BODY_Y, CONTENT_W, 420000, [para_xml(lead.get("runs"), 1800, base={"color": "4A4F57"})]))
            played = set()
            for p, py in placed:
                ob = p["obj"]
                if ob is not None and id(ob) not in played and self.has_media(ob):
                    bl.audio(ob, py)
                    played.add(id(ob))
                bl.w = p["width"]
                p["draw"](bl, py, p["h"])
                bl.w = CONTENT_W
            self.slides.append(bl)

    def build(self, title: str = "") -> bytes:
        if not self.slides:
            self.add({"kind": "title", "title": title or "Untitled"})
        n = len(self.slides)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="m4a" ContentType="audio/mp4"/><Default Extension="mp3" ContentType="audio/mpeg"/><Default Extension="wav" ContentType="audio/wav"/>'
                       '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                       '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
                       '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
                       '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
                       + "".join(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(n))
                       + '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                       '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                       '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>')
            z.writestr("docProps/app.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>FLEx Scratchpad</Application><Slides>' + str(n) + "</Slides></Properties>")
            z.writestr("docProps/core.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>' + _t(title) + "</dc:title><dc:creator>FLEx Scratchpad</dc:creator></cp:coreProperties>")
            z.writestr("ppt/presentation.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<p:presentation {_NS} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                       "<p:sldIdLst>" + "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 3}"/>' for i in range(n)) + "</p:sldIdLst>"
                       f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/><p:notesSz cx="6858000" cy="9144000"/>'
                       '<p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr><a:lvl1pPr marL="0" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1800" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr></p:defaultTextStyle></p:presentation>')
            z.writestr("ppt/_rels/presentation.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
                       + "".join(f'<Relationship Id="rId{i + 3}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i + 1}.xml"/>' for i in range(n))
                       + "</Relationships>")
            z.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>')
            z.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>')
            z.writestr("ppt/theme/theme1.xml", THEME.replace("@FG@", _TH["fg"]).replace("@BG@", _TH["bg"]).replace("@ACCENT@", _TH["accent"]).replace("@PANEL@", _TH["panel"]).replace("@FONT@", _t(_TH["font"])))
            for i, s in enumerate(self.slides):
                z.writestr(f"ppt/slides/slide{i + 1}.xml", s.xml())
                z.writestr(f"ppt/slides/_rels/slide{i + 1}.xml.rels", s.rels_xml())
            for name, data in self.media:
                z.writestr(f"ppt/media/{name}", data)
        return buf.getvalue()


_BUILD_LOCK = threading.Lock()      # the theme is module state for the run helpers: one build at a time


def build_pptx(deck: dict, media=None) -> bytes:
    """The deck (export.js slidesOf) as a .pptx file; `media(src)` → (bytes, mime, ext) of a
    recording an example or chart carries (`audio.src`), or None."""
    with _BUILD_LOCK:
        _set_theme((deck or {}).get("theme"))
        try:
            p = Pptx(media)
            for s in (deck or {}).get("slides") or []:
                p.add(s)
            return p.build((deck or {}).get("title") or "")
        finally:
            _set_theme(None)


def _need(kind: str, blocks: list[dict]) -> int:
    """About how tall a group of a mixed slide wants to be (EMU) before it is shrunk to fit."""
    if kind == "text":
        n = 0.0
        for b in blocks:
            if b.get("type") == "list":
                n += len(b.get("items") or []) * 1.1
            elif b.get("type") == "code":
                n += len(str(b.get("text") or "").split("\n")) * 0.8
            else:
                n += max(1, len(_plain(b.get("runs"))) // 80 + 1)
        return int(n * 400000) + 80000
    b = blocks[0]
    t = b.get("type")
    if t == "interlinear":
        segs = b.get("segments") or []
        return sum(len(sg.get("lines") or []) + (1 if sg.get("free") else 0) + (1 if sg.get("lit") else 0) + len(sg.get("notes") or []) for sg in segs) * 330000 + len(segs) * 160000
    if t == "chart":
        return (len(b.get("headers") or []) + 2 * len(b.get("rows") or [])) * 260000
    if t == "table":
        return len(b.get("rows") or []) * 400000
    if t == "entry":
        return (1 + sum(1 + len(x.get("examples") or []) for x in b.get("senses") or [])) * 420000
    if t in ("image", "imageref"):
        return 3200000
    return 600000


def audio_icon_png(size: int = 96, fg=(255, 255, 255), bg=(31, 79, 143)) -> bytes:
    """A round play button for a recording on a slide (stdlib only: a PNG drawn pixel by pixel)."""
    import math
    import struct
    r = size / 2
    rows = []
    for yy in range(size):
        row = bytearray([0])
        for xx in range(size):
            d = math.hypot(xx + 0.5 - r, yy + 0.5 - r)
            a = max(0.0, min(1.0, r - 1 - d))
            px, py = (xx + 0.5) / size, (yy + 0.5) / size
            inside = 0.38 <= px <= 0.74 and abs(py - 0.5) <= (0.74 - px) * 0.72
            col = fg if inside else bg
            row += bytes([col[0], col[1], col[2], int(255 * a)])
        rows.append(bytes(row))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
