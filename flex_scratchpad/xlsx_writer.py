"""A minimal .xlsx writer with no dependencies, for exporting a note to Excel (Seth, 2026-10-18:
"pretty exports … HTML, DOCX, Excel, and PDF").

Input is the SAME export document model the page builds for Word (ui/js/export.js, see
docx_writer.py for the block shapes). What comes out:

  * sheet "Note"   — the whole note in reading order: headings, paragraphs and lists as rows,
                     a Markdown table as a bordered grid, an interlinear example as one row per
                     line (the words across the columns, the glosses under their words — the
                     layout FLEx's own exports use), a text chart as its table (the header rows
                     merged over their groups, a cell's words stacked `word⏎gloss` in two colours,
                     the markers, the Free column or translation rows, the notes, a chart note's
                     custom columns, the rows' own colours);
  * sheet "Examples" — one row per interlinear LINE across the note (example, text, FLEx number,
                     baseline, morphemes, glosses, parts of speech, free / literal translation,
                     notes): the shape to filter, sort and count in Excel;
  * one sheet per chart, "Chart N rows" — one row per chart row: the label, clause type and
                     flags, each template column's words and (after them) their glosses, the
                     markers, moved text and clause references, the custom columns, the free
                     translation, the notes.

Rich text (two colours in one cell) is written as inline strings with runs; styles are built up
as they are needed (fonts, fills, borders, alignments → cellXfs). Everything is UTF-8 and
Unicode-safe; vernacular text keeps the writing system's font name when the page passed one.
Checked by tests/test_xlsx.py with openpyxl when it is installed (dev only).
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

VERN = "#00379c"
GLOSS = "#2a6e2a"
MUTED = "#68717d"
POS = "#7a3e9d"
MORPH = "#4a4f57"
HEAD_FILL = "#f3f4f6"
FREE_FILL = "#f3f9f3"
XCOL_FILL = "#eef2fb"


def _hex(c) -> str:
    """'#rrggbb' / '#rgb' / a few names → 'RRGGBB' ('' when unknown)."""
    c = str(c or "").strip()
    if c.startswith("#") and len(c) in (4, 7):
        if len(c) == 4:
            c = "#" + "".join(ch * 2 for ch in c[1:])
        return c[1:].upper()
    return {"red": "C0392B", "green": "1F7A4D", "blue": "1F4F8F", "yellow": "FFF2A8"}.get(c.lower(), "")


def col_letter(n: int) -> str:
    """1 → A, 27 → AA."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _t(text) -> str:
    return escape(_BAD_XML.sub("", str(text if text is not None else "")))


class _Styles:
    """Fonts, fills, borders and alignments as they are asked for; `xf()` gives the cellXfs index
    of a combination."""

    def __init__(self):
        self.fonts: list[str] = ['<font><sz val="11"/><name val="Calibri"/></font>']
        self.fills: list[str] = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        self.borders: list[str] = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        self.xfs: list[str] = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
        self._font_ix: dict[str, int] = {self.fonts[0]: 0}
        self._fill_ix: dict[str, int] = {self.fills[0]: 0, self.fills[1]: 1}
        self._border_ix: dict[str, int] = {self.borders[0]: 0}
        self._xf_ix: dict[str, int] = {self.xfs[0]: 0}

    def font(self, b=False, i=False, u=False, s=False, color="", size=None, name="") -> int:
        xml = "<font>" + ("<b/>" if b else "") + ("<i/>" if i else "") + ("<strike/>" if s else "") + ("<u/>" if u else "")
        xml += f'<sz val="{size or 11}"/>'
        if _hex(color):
            xml += f'<color rgb="FF{_hex(color)}"/>'
        xml += f'<name val="{_t(name or "Calibri")}"/></font>'
        if xml not in self._font_ix:
            self._font_ix[xml] = len(self.fonts)
            self.fonts.append(xml)
        return self._font_ix[xml]

    def fill(self, color="") -> int:
        h = _hex(color)
        if not h:
            return 0
        xml = f'<fill><patternFill patternType="solid"><fgColor rgb="FF{h}"/><bgColor indexed="64"/></patternFill></fill>'
        if xml not in self._fill_ix:
            self._fill_ix[xml] = len(self.fills)
            self.fills.append(xml)
        return self._fill_ix[xml]

    def border(self, kind="") -> int:
        if not kind:
            return 0
        color = "DDDDDD" if kind == "light" else "999999"
        side = f'<{{s}} style="thin"><color rgb="FF{color}"/></{{s}}>'
        xml = "<border>" + "".join(side.format(s=s) for s in ("left", "right", "top", "bottom")) + "<diagonal/></border>"
        if xml not in self._border_ix:
            self._border_ix[xml] = len(self.borders)
            self.borders.append(xml)
        return self._border_ix[xml]

    def xf(self, font=0, fill=0, border=0, wrap=False, halign="", valign="top", indent=0) -> int:
        al = f'<alignment vertical="{valign}"' + (f' horizontal="{halign}"' if halign else "") + (' wrapText="1"' if wrap else "") + (f' indent="{indent}"' if indent else "") + "/>"
        xml = (f'<xf numFmtId="0" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
               + (' applyFont="1"' if font else "") + (' applyFill="1"' if fill else "") + (' applyBorder="1"' if border else "") + ' applyAlignment="1">' + al + "</xf>")
        if xml not in self._xf_ix:
            self._xf_ix[xml] = len(self.xfs)
            self.xfs.append(xml)
        return self._xf_ix[xml]

    def xml(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                f'<borders count="{len(self.borders)}">{"".join(self.borders)}</borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(self.xfs)}">{"".join(self.xfs)}</cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                "</styleSheet>")


def _run_xml(r: dict, base: dict | None = None) -> str:
    """One run of an inline rich string: <r><rPr>…</rPr><t>…</t></r>."""
    base = base or {}
    text = str(r.get("text") or "")
    if not text:
        return ""
    pr = ""
    font = r.get("font") or base.get("font")
    if font:
        pr += f'<rFont val="{_t(font)}"/>'
    if r.get("b") or base.get("b"):
        pr += "<b/>"
    if r.get("i") or base.get("i"):
        pr += "<i/>"
    if r.get("s"):
        pr += "<strike/>"
    color = _hex(r.get("color") or base.get("color"))
    if color:
        pr += f'<color rgb="FF{color}"/>'
    size = r.get("size") or base.get("size")
    if size:
        pr += f'<sz val="{size}"/>'
    if r.get("u") or base.get("u"):
        pr += "<u/>"
    return "<r>" + (f"<rPr>{pr}</rPr>" if pr else "") + f'<t xml:space="preserve">{_t(text)}</t></r>'


class Sheet:
    def __init__(self, name: str, styles: _Styles):
        self.name = name
        self.st = styles
        self.cells: dict[tuple[int, int], str] = {}          # (row, col) 1-based → <c> xml
        self.widths: dict[int, float] = {}                   # col → max text width seen
        self.merges: list[str] = []
        self.freeze_rows = 0
        self.landscape = False
        self.row = 1                                         # the next free row

    # -- writing cells ----------------------------------------------------------------------
    def _note_width(self, col: int, text: str):
        longest = max((len(line) for line in str(text).split("\n")), default=0)
        self.widths[col] = max(self.widths.get(col, 0), min(60, longest))

    def text(self, r: int, c: int, value, xf: int = 0):
        value = "" if value is None else str(value)
        self._note_width(c, value)
        ref = f"{col_letter(c)}{r}"
        if value == "":
            self.cells[(r, c)] = f'<c r="{ref}" s="{xf}"/>'
        else:
            self.cells[(r, c)] = f'<c r="{ref}" s="{xf}" t="inlineStr"><is><t xml:space="preserve">{_t(value)}</t></is></c>'

    def number(self, r: int, c: int, value, xf: int = 0):
        self.cells[(r, c)] = f'<c r="{col_letter(c)}{r}" s="{xf}"><v>{value}</v></c>'
        self._note_width(c, str(value))

    def rich(self, r: int, c: int, runs: list[dict], xf: int = 0, base: dict | None = None):
        """A cell of runs; a run of just '\\n' breaks the line (wrap the cell)."""
        runs = [x for x in (runs or []) if str(x.get("text") or "")]
        if not runs:
            self.text(r, c, "", xf)
            return
        plain = "".join(str(x.get("text") or "") for x in runs)
        self._note_width(c, plain)
        xml = "".join(_run_xml(x, base) for x in runs)
        self.cells[(r, c)] = f'<c r="{col_letter(c)}{r}" s="{xf}" t="inlineStr"><is>{xml}</is></c>'

    def merge(self, r1: int, c1: int, r2: int, c2: int):
        if r2 > r1 or c2 > c1:
            self.merges.append(f"{col_letter(c1)}{r1}:{col_letter(c2)}{r2}")

    # -- the XML ------------------------------------------------------------------------------
    def xml(self) -> str:
        rows: dict[int, list[tuple[int, str]]] = {}
        for (r, c), x in self.cells.items():
            rows.setdefault(r, []).append((c, x))
        last_row = max(rows) if rows else 1
        last_col = max((c for (_, c) in self.cells), default=1)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
               f'<dimension ref="A1:{col_letter(last_col)}{last_row}"/>']
        out.append('<sheetViews><sheetView workbookViewId="0"' + (' tabSelected="1"' if self.name == "Note" else "") + ">")
        if self.freeze_rows:
            out.append(f'<pane ySplit="{self.freeze_rows}" topLeftCell="A{self.freeze_rows + 1}" activePane="bottomLeft" state="frozen"/>')
        out.append("</sheetView></sheetViews>")
        out.append('<sheetFormatPr defaultRowHeight="15"/>')
        if self.widths:
            out.append("<cols>")
            for c in sorted(self.widths):
                w = max(6, min(70, self.widths[c] * 1.1 + 2))
                out.append(f'<col min="{c}" max="{c}" width="{w:.2f}" customWidth="1"/>')
            out.append("</cols>")
        out.append("<sheetData>")
        for r in sorted(rows):
            out.append(f'<row r="{r}">' + "".join(x for _, x in sorted(rows[r])) + "</row>")
        out.append("</sheetData>")
        if self.merges:
            out.append(f'<mergeCells count="{len(self.merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in self.merges) + "</mergeCells>")
        out.append('<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>')
        if self.landscape:
            out.append('<pageSetup orientation="landscape"/>')
        out.append("</worksheet>")
        return "".join(out)


_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


class Workbook:
    def __init__(self):
        self.styles = _Styles()
        self.sheets: list[Sheet] = []

    def sheet(self, name: str) -> Sheet:
        base = _SHEET_BAD.sub("-", name).strip() or "Sheet"
        base = base[:31]
        taken = {s.name.casefold() for s in self.sheets}
        name = base
        n = 2
        while name.casefold() in taken:
            suffix = f" ({n})"
            name = base[: 31 - len(suffix)] + suffix
            n += 1
        s = Sheet(name, self.styles)
        self.sheets.append(s)
        return s

    def build(self) -> bytes:
        if not self.sheets:
            self.sheet("Note")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       '<Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                       '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                       + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(self.sheets)))
                       + '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                       '</Types>')
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                       "</Relationships>")
            z.writestr("docProps/app.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>FLEx Scratchpad</Application></Properties>')
            z.writestr("xl/workbook.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       "<sheets>" + "".join(f'<sheet name="{_t(s.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(self.sheets)) + "</sheets></workbook>")
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(self.sheets)))
                       + f'<Relationship Id="rId{len(self.sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                       "</Relationships>")
            for i, s in enumerate(self.sheets):
                z.writestr(f"xl/worksheets/sheet{i + 1}.xml", s.xml())
            z.writestr("xl/styles.xml", self.styles.xml())
        return buf.getvalue()


# ----------------------------------------------------------------------------- the note → sheets
def _plain(runs) -> str:
    return "".join(str(r.get("text") or "") for r in (runs or []))


class _NoteWriter:
    """Writes the document model onto the workbook."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.wb = Workbook()
        self.st = self.wb.styles
        self.note = self.wb.sheet("Note")
        self.examples: list[list] = []                  # rows of the Examples sheet
        self.charts: list[dict] = []
        self.ex_n = 0
        # the styles used again and again
        self.x_plain = self.st.xf(wrap=True)
        self.x_h = {lvl: self.st.xf(font=self.st.font(b=True, size={1: 16, 2: 14, 3: 12}.get(lvl, 11)), wrap=True) for lvl in range(1, 7)}
        self.x_quote = self.st.xf(font=self.st.font(i=True, color=MUTED), wrap=True, indent=1)
        self.x_code = self.st.xf(font=self.st.font(name="Consolas"), wrap=True)
        self.x_muted = self.st.xf(font=self.st.font(color=MUTED, size=9), wrap=True)
        self.x_head = self.st.xf(font=self.st.font(b=True, color=MUTED, size=10), fill=self.st.fill(HEAD_FILL), border=self.st.border("light"), wrap=True, halign="center", valign="center")
        self.x_cell = self.st.xf(border=self.st.border("light"), wrap=True)
        self.x_label = self.st.xf(font=self.st.font(b=True, color=MUTED, size=10), fill=self.st.fill("#f7f8fa"), border=self.st.border("light"), halign="right")
        self.x_free = self.st.xf(font=self.st.font(i=True), fill=self.st.fill(FREE_FILL), border=self.st.border("light"), wrap=True)
        self.x_free_rows = self.st.xf(font=self.st.font(color=MUTED, size=9), fill=self.st.fill(FREE_FILL), border=self.st.border("light"), halign="right")

    # -- helpers ------------------------------------------------------------------------------
    def _cell_xf(self, bg="", b=False, i=False, u=False, color="", border="light", halign="", wrap=True, size=None, font=""):
        f = self.st.font(b=b, i=i, u=u, color=color, size=size, name=font) if (b or i or u or color or size or font) else 0
        return self.st.xf(font=f, fill=self.st.fill(bg), border=self.st.border(border), wrap=wrap, halign=halign)

    def blank(self, n=1):
        self.note.row += n

    # -- blocks -------------------------------------------------------------------------------
    def write(self) -> bytes:
        self.note.text(1, 1, self.doc.get("title") or "Untitled", self.st.xf(font=self.st.font(b=True, size=18)))
        meta = " · ".join(x for x in (self.doc.get("where"), ("FLEx project " + self.doc["project"]) if self.doc.get("project") else "", self.doc.get("date")) if x)
        if meta:
            self.note.text(2, 1, meta, self.x_muted)
        self.note.row = 4
        for b in self.doc.get("blocks") or []:
            self.block(b)
        self.note.widths[1] = max(self.note.widths.get(1, 0), 10)
        if self.examples:
            self.examples_sheet()
        return self.wb.build()

    def block(self, b: dict, indent: int = 0):
        t = b.get("type")
        s = self.note
        if t == "h":
            s.rich(s.row, 1, b.get("runs"), self.x_h.get(int(b.get("level") or 1), self.x_h[6]))
            s.row += 1
        elif t in ("p", "quote"):
            runs = b.get("runs") or []
            if b.get("exNum"):
                runs = [{"text": b["exNum"] + "  ", "color": MUTED}] + list(runs)
            s.rich(s.row, 1, runs, self.x_quote if t == "quote" else self.st.xf(wrap=True, indent=indent + int(b.get("indent") or 0)))
            s.row += 1
        elif t == "code":
            for line in str(b.get("text") or "").split("\n"):
                s.text(s.row, 1, line, self.x_code)
                s.row += 1
        elif t == "list":
            for it in b.get("items") or []:
                mark = ("☑ " if it.get("checked") else "☐ ") if it.get("task") else (f"{it.get('n') or 1}. " if it.get("ordered") else "• ")
                s.rich(s.row, 1, [{"text": mark, "color": MUTED}] + list(it.get("runs") or []), self.st.xf(wrap=True, indent=int(it.get("level") or 0) + 1))
                s.row += 1
        elif t == "hr":
            s.text(s.row, 1, "—" * 20, self.x_muted)
            s.row += 1
        elif t == "table":
            self.table(b)
        elif t == "interlinear":
            self.interlinear(b)
        elif t == "chart":
            self.chart(b)
        elif t == "entry":
            self.entry(b)
        elif t == "wordform":
            s.rich(s.row, 1, [{"text": b.get("form") or "", "b": True, "color": VERN}, {"text": "  " + "; ".join(b.get("glosses") or []), "color": GLOSS}], self.x_plain)
            s.row += 1
        elif t in ("image", "imageref"):
            s.text(s.row, 1, "[picture" + (": " + b["alt"] if b.get("alt") else "") + "]", self.x_muted)
            s.row += 1
        else:
            return
        s.row += 1                                      # a blank row between blocks

    def table(self, b: dict):
        s = self.note
        rows = b.get("rows") or []
        style = b.get("style") or {}
        cols, rst = style.get("cols") or {}, style.get("rows") or {}
        for ri, row in enumerate(rows):
            for ci, c in enumerate(row):
                if c.get("covered"):
                    continue
                col = cols.get(str(ci + 1), {}) or {}
                rs = rst.get(str(ri + 1), {}) or {}
                header = ri == 0 and b.get("header", True)
                xf = self.x_head if header else self._cell_xf(bg=rs.get("bg") or col.get("bg"), b=bool(rs.get("bold") or col.get("bold")), i=bool(rs.get("italic") or col.get("italic")),
                                                              color=rs.get("color") or col.get("color"), halign=rs.get("align") or col.get("align") or "")
                if c.get("blocks"):
                    # a cell holding objects: their plain text, one per line
                    parts = []
                    for blk in c["blocks"]:
                        if blk.get("type") == "interlinear":
                            parts.append("; ".join(" ".join(_plain(w) for w in (seg["lines"][0]["cells"] if seg.get("lines") else [])) for seg in blk.get("segments") or []))
                        elif blk.get("type") == "chart":
                            parts.append((blk.get("name") or "Chart") + " · " + (blk.get("title") or ""))
                        elif blk.get("type") == "entry":
                            parts.append(blk.get("headword") or "")
                        else:
                            parts.append(_plain(blk.get("runs")))
                    s.text(s.row, ci + 1, "\n".join(p for p in parts if p), xf)
                else:
                    s.rich(s.row, ci + 1, c.get("runs"), xf)
                if int(c.get("rowspan") or 1) > 1 or int(c.get("colspan") or 1) > 1:
                    s.merge(s.row, ci + 1, s.row + int(c.get("rowspan") or 1) - 1, ci + int(c.get("colspan") or 1))
            s.row += 1

    def interlinear(self, b: dict):
        """One block of rows: the title, then per segment a row per line with the words across
        the columns (from column 2; column 1 holds the FLEx number on the first line), the free
        translation merged under them. The Examples sheet gets a flat row per segment."""
        s = self.note
        self.ex_n += 1
        s.rich(s.row, 1, [{"text": (b.get("exNum") + "  ") if b.get("exNum") else "", "color": MUTED}, {"text": b.get("title") or "", "b": True, "color": VERN}, {"text": ("   " + b["label"]) if b.get("label") else "", "color": MUTED}], self.x_plain)
        s.row += 1
        font = (b.get("ws") or {}).get("font") or ""
        look = {"txt": {"color": VERN, "font": font, "size": 12}, "morph": {"color": MORPH, "font": font}, "mgls": {"color": GLOSS}, "gls": {"color": GLOSS}, "pos": {"color": POS, "size": 9}, "cf": {"color": MUTED, "size": 9}, "tag": {"size": 8, "b": True}}
        for seg in b.get("segments") or []:
            first = True
            width = 1
            for line in seg.get("lines") or []:
                if first:
                    s.text(s.row, 1, seg.get("label") or str(seg.get("n") or ""), self.x_muted)
                    first = False
                for wi, cell in enumerate(line.get("cells") or []):
                    s.rich(s.row, wi + 2, cell, self.st.xf(font=self.st.font(**{k: v for k, v in look.get(line["name"], {}).items() if k != "font"}, name=look.get(line["name"], {}).get("font", "")), wrap=False), base=look.get(line["name"]))
                    width = max(width, wi + 2)
                s.row += 1
            for key, label in (("free", "Free"), ("lit", "Lit."), ("notes", None)):
                vals = seg.get(key)
                if not vals:
                    continue
                for v in (vals if key == "notes" else [vals]):
                    s.rich(s.row, 2, [{"text": (label or "Note") + "  ", "color": "#a8b0ba", "size": 8}] + list(v), self.st.xf(font=self.st.font(i=key != "free", color=MUTED if key != "free" else ""), wrap=True))
                    s.merge(s.row, 2, s.row, max(width, 6))
                    s.row += 1
            # the Examples sheet
            def line_text(name):
                for ln in seg.get("lines") or []:
                    if ln["name"] == name:
                        return " ".join(_plain(c) for c in ln["cells"])
                return ""
            self.examples.append([self.ex_n, b.get("title") or "", seg.get("label") or str(seg.get("n") or ""), line_text("txt"), line_text("morph"), line_text("mgls") or line_text("gls"), line_text("gls"), line_text("pos"), _plain(seg.get("free")), _plain(seg.get("lit")), " | ".join(_plain(n) for n in (seg.get("notes") or []))])
            s.row += 1

    def entry(self, b: dict):
        s = self.note
        s.rich(s.row, 1, [{"text": b.get("headword") or "", "b": True, "color": VERN, "size": 13}, {"text": ("  " + b["pos"]) if b.get("pos") else "", "i": True, "color": MUTED}, {"text": ("   " + b["label"]) if b.get("label") else "", "color": MUTED}], self.x_plain)
        s.row += 1
        for sense in b.get("senses") or []:
            s.text(s.row, 1, sense.get("number") or "", self.x_muted)
            s.rich(s.row, 2, [{"text": (sense["pos"] + " ") if sense.get("pos") else "", "i": True, "color": MUTED}, {"text": sense.get("gloss") or "", "b": True, "color": GLOSS}, {"text": (" — " + sense["definition"]) if sense.get("definition") and sense.get("definition") != sense.get("gloss") else ""}], self.x_plain)
            s.row += 1
            for ex in sense.get("examples") or []:
                s.rich(s.row, 2, [{"text": ex.get("text") or "", "color": VERN}, {"text": ("  ‘" + ex["translation"] + "’") if ex.get("translation") else "", "color": MUTED}], self.st.xf(wrap=True, indent=1))
                s.row += 1

    # -- charts -----------------------------------------------------------------------------
    def chart(self, b: dict):
        """The chart as a table on a sheet of its own ("Chart", "Chart 2"…: its columns would
        otherwise set the widths of the whole Note sheet); the Note sheet names it."""
        self.charts.append(b)
        n = len(self.charts)
        name = "Chart" if n == 1 else f"Chart {n}"
        self.note.rich(self.note.row, 1, [{"text": b.get("name") or "Chart", "b": True}, {"text": " · "}, {"text": b.get("title") or "", "b": True, "color": VERN}, {"text": ("   " + b["label"]) if b.get("label") else "", "color": MUTED}, {"text": "   → sheet “" + name + "”", "color": MUTED}], self.x_plain)
        self.note.row += 1
        s = self.wb.sheet(name)
        s.landscape = True
        s.rich(1, 1, [{"text": b.get("name") or "Chart", "b": True, "size": 13}, {"text": " · ", "size": 13}, {"text": b.get("title") or "", "b": True, "color": VERN, "size": 13}, {"text": ("   " + b["label"]) if b.get("label") else "", "color": MUTED}], self.x_plain)
        s.row = 3
        headers = b.get("headers") or []
        ncols = int(b.get("cols") or 0)
        xcols = b.get("xcols") or []
        x_left = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") == "left"]     # custom columns left of the chart
        x_right = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") != "left"]
        free_col = bool(b.get("freeCol"))
        notes_col = bool(b.get("notesCol"))
        total = 1 + ncols + len(xcols) + (1 if free_col else 0) + (1 if notes_col else 0)
        x_xhead = self.st.xf(font=self.st.font(b=True, color="#1f4f8f", size=10), fill=self.st.fill(XCOL_FILL), border=self.st.border("light"), wrap=True, halign="center", valign="center")
        top = s.row
        for hi, hr in enumerate(headers):
            c = 2
            if hi == 0:
                s.text(s.row, 1, "#", self.x_head)
                if len(headers) > 1:
                    s.merge(top, 1, top + len(headers) - 1, 1)
                for _, xc in x_left:
                    s.text(s.row, c, xc.get("name") or "", x_xhead)
                    if len(headers) > 1:
                        s.merge(top, c, top + len(headers) - 1, c)
                    c += 1
            else:
                c += len(x_left)
            for h in hr:
                span = int(h.get("span") or 1)
                s.text(s.row, c, h.get("text") or "", self.x_head)
                for k in range(1, span):
                    s.text(s.row, c + k, "", self.x_head)
                if span > 1:
                    s.merge(s.row, c, s.row, c + span - 1)
                c += span
            if hi == 0:
                for _, xc in x_right:
                    s.text(s.row, c, xc.get("name") or "", x_xhead)
                    if len(headers) > 1:
                        s.merge(top, c, top + len(headers) - 1, c)
                    c += 1
                for label, on in (("Free", free_col), ("Notes", notes_col)):
                    if on:
                        s.text(s.row, c, label, self.x_head)
                        if len(headers) > 1:
                            s.merge(top, c, top + len(headers) - 1, c)
                        c += 1
            s.row += 1
        font = (b.get("ws") or {}).get("font") or ""
        for r in b.get("rows") or []:
            rs = r.get("rowStyle") or {}
            label_xf = self.x_label if not rs else self._cell_xf(bg=rs.get("bg"), b=True, color=MUTED, halign="right", size=10)
            s.text(s.row, 1, r.get("label") or "", label_xf)
            c = 2
            xcells = r.get("xcells") or []

            def xcell(xc, col):
                s.text(s.row, col, xc.get("text") or "", self._cell_xf(bg=xc.get("hl") or rs.get("bg") or "#fbfcff", b=bool(xc.get("b")), i=bool(xc.get("i")), u=bool(xc.get("u")), color=xc.get("color")))

            for i, _ in x_left:
                xcell(xcells[i] if i < len(xcells) else {}, c)
                c += 1
            for cell in r.get("cells") or []:
                runs: list[dict] = []
                for wi, w in enumerate(cell.get("words") or []):
                    if wi:
                        runs.append({"text": "\n"})
                    runs.extend(dict(x) for x in w)
                if cell.get("marks"):
                    if runs:
                        runs.append({"text": "\n"})
                    runs.extend(dict(x, text=str(x.get("text") or "").strip()) for x in cell["marks"])
                runs = [x for x in runs if str(x.get("text") or "")]
                # a word's lines come as runs split by '\n'; the first run of a word is its baseline
                xf = self._cell_xf(bg=cell.get("hl") or rs.get("bg"), b=bool(cell.get("b") or rs.get("b")), i=bool(cell.get("i") or rs.get("i")), u=bool(cell.get("u") or rs.get("u")), color=cell.get("color") or rs.get("color"))
                s.rich(s.row, c, runs, xf, base={"font": font} if font else None)
                span = int(cell.get("span") or 1)
                for k in range(1, span):
                    s.text(s.row, c + k, "", xf)
                if span > 1:
                    s.merge(s.row, c, s.row, c + span - 1)
                c += span
            for i, _ in x_right:
                xcell(xcells[i] if i < len(xcells) else {}, c)
                c += 1
            if free_col:
                fr = r.get("free")
                s.text(s.row, c, fr["text"] if fr else "", self.x_free)
                if fr and int(fr.get("span") or 1) > 1:
                    s.merge(s.row, c, s.row + int(fr["span"]) - 1, c)
                c += 1
            if notes_col:
                s.text(s.row, c, r.get("notes") or "", self._cell_xf(color=MUTED, size=9))
                c += 1
            s.row += 1
            if r.get("freeRow") and (r["freeRow"].get("text") or "").strip():
                s.text(s.row, 1, "", self.x_free)
                s.text(s.row, 2, r["freeRow"]["text"], self.x_free)
                if total > 3:
                    s.merge(s.row, 2, s.row, total - 1)
                    s.text(s.row, total, r["freeRow"].get("rows") or "", self.x_free_rows)
                s.row += 1
        if headers:
            s.freeze_rows = top + len(headers) - 1
        self.chart_rows_sheet(b, n)

    def chart_rows_sheet(self, b: dict, i: int):
        """One flat row per chart row — the shape Excel filters and pivots."""
        sh = self.wb.sheet("Chart rows" if i == 1 else f"Chart {i} rows")
        sh.landscape = True
        cols = b.get("columns") or [{"n": k + 1, "name": f"c{k + 1}", "path": f"c{k + 1}"} for k in range(int(b.get("cols") or 0))]
        xcols = b.get("xcols") or []
        head = ["Row", "Clause", "Ends sentence", "Ends paragraph"] + [c.get("path") or c.get("name") for c in cols] + [(c.get("path") or c.get("name")) + " (gloss)" for c in cols] + ["Markers", "Moved text", "Clause refs"] + [x.get("name") for x in xcols] + ["Free translation", "Notes"]
        for ci, h in enumerate(head, 1):
            sh.text(1, ci, h, self.x_head)
        sh.freeze_rows = 1
        r = 2
        for row in b.get("rows") or []:
            by_col: dict[int, dict] = {}
            for cell in row.get("cells") or []:
                by_col[int(cell.get("col") or 0)] = cell
            txts, glss, marks, moved, clauses = [], [], [], [], []
            for c in cols:
                cell = by_col.get(int(c.get("n") or 0)) or {}
                pl = cell.get("plain") or {}
                txts.append(pl.get("txt") or "")
                glss.append(pl.get("gls") or "")
                marks += pl.get("marks") or []
                moved += pl.get("moved") or []
                clauses += pl.get("clauses") or []
            vals = [row.get("label") or "", row.get("clause") or "normal", "yes" if row.get("endSent") else "", "yes" if row.get("endPara") else ""] + txts + glss + ["; ".join(marks), "; ".join(moved), "; ".join(clauses)] + [x.get("text") or "" for x in (row.get("xcells") or [])] + [(row.get("free") or {}).get("text") or (row.get("freeRow") or {}).get("text") or "", row.get("notesText") if row.get("notesText") is not None else (row.get("notes") or "")]
            rs = row.get("rowStyle") or {}
            xf = self._cell_xf(bg=rs.get("bg"), color=rs.get("color"), b=bool(rs.get("b")), i=bool(rs.get("i")))
            for ci, v in enumerate(vals, 1):
                sh.text(r, ci, v, xf)
            r += 1

    def examples_sheet(self):
        sh = self.wb.sheet("Examples")
        head = ["Example", "Text", "Line", "Baseline", "Morphemes", "Morph glosses", "Word glosses", "POS", "Free translation", "Literal", "Notes"]
        for ci, h in enumerate(head, 1):
            sh.text(1, ci, h, self.x_head)
        sh.freeze_rows = 1
        for r, vals in enumerate(self.examples, 2):
            for ci, v in enumerate(vals, 1):
                if ci == 1:
                    sh.number(r, ci, v, self.x_cell)
                else:
                    sh.text(r, ci, v, self.x_cell)


def build_xlsx(doc: dict) -> bytes:
    """The note (export.js document model) as an .xlsx file."""
    return _NoteWriter(doc or {}).write()
