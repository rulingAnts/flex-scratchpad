"""A minimal .docx writer with no dependencies, for exporting a note.

Input is the export document model the page builds (see ui/js/export.js):

    doc = {title, blocks: [block, ...]}
    block = {type: 'h', level, runs} | {type: 'p', runs} | {type: 'quote', runs} | {type: 'code', text}
          | {type: 'list', items: [{runs, ordered, level, task, checked}]}
          | {type: 'table', rows: [[cell, ...]], aligns, header: True, style: {...}}   cell = {runs, blocks?}
          | {type: 'interlinear', title, label, segments: [{n, lines: [{name, cells: [runs]}], free, lit, notes}], ws}
          | {type: 'entry', headword, pos, senses: [{number, pos, gloss, definition, examples: [{text, translation}]}]}
          | {type: 'image', png: <base64>, alt} | {type: 'hr'}
    run   = {text, b, i, u, s, hl (colour or True), color, code, font, rtl}

Interlinear examples become borderless tables (one row per line, one column per word), which
is how FLEx's own Word export lays them out and what keeps the glosses under their words.
"""
from __future__ import annotations

import re
import base64
import io
import zipfile
from xml.sax.saxutils import escape

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' \
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'

HL_NAMES = {"#fff2a8": "yellow", "#ffd6a5": "lightGray", "#caffbf": "green", "#9bf6ff": "cyan",
            "#bdb2ff": "magenta", "#ffadad": "red", "#fdffb6": "yellow"}


def _hex(c: str | None) -> str:
    c = (c or "").strip()
    if c.startswith("#") and len(c) in (4, 7):
        if len(c) == 4:
            c = "#" + "".join(ch * 2 for ch in c[1:])
        return c[1:].upper()
    names = {"red": "C0392B", "green": "1F7A4D", "blue": "1F4F8F", "yellow": "FFF2A8"}
    return names.get(c.lower(), "")


PAGE_W, PAGE_H, MARGIN = 11906, 16838, 1134           # A4 in twentieths of a point
TEXT_W_PORTRAIT = PAGE_W - 2 * MARGIN                 # 9638
TEXT_W_LANDSCAPE = PAGE_H - 2 * MARGIN                # 14570
SECT_PORTRAIT = f'<w:sectPr><w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/><w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
SECT_LANDSCAPE = f'<w:sectPr><w:pgSz w:w="{PAGE_H}" w:h="{PAGE_W}" w:orient="landscape"/><w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'


def _text_len(runs) -> int:
    """The longest line of a cell's runs, in characters (a rough width)."""
    text = "".join(str(r.get("text") or "") for r in (runs or []))
    return max((len(x) for x in text.split("\n")), default=0)


def grid_widths(rows: list[list[dict]], text_w: int, fixed: dict | None = None, min_w: int = 500, char_w: int = 105) -> list[int]:
    """Column widths (twips) from the longest text in each column, scaled to fit the text width.
    Word reads them from <w:tblGrid>; LibreOffice needs them to lay a table out at all."""
    ncols = max((len(r) for r in rows), default=0)
    want = [min_w] * ncols
    for r in rows:
        for ci, c in enumerate(r):
            if c.get("covered") or ci >= ncols:
                continue
            n = _text_len(c.get("runs"))
            for b in c.get("blocks") or []:
                if b.get("type") == "wordgrid":       # the grid's own widths (130 twips a character + 200), in this column's units
                    n = max(n, int(sum(min(40, max((_text_len(ln) for ln in w), default=1)) * 130 + 200 for w in b.get("words") or []) / char_w) + 2)
                elif b.get("type") == "p":
                    n = max(n, _text_len(b.get("runs")))
                else:
                    n = max(n, 24)
            span = max(1, int(c.get("colspan") or 1))
            if span == 1:
                want[ci] = max(want[ci], min(n, 40) * char_w + 220)
    for ci, w in (fixed or {}).items():
        if 0 <= ci < ncols:
            want[ci] = w
    total = sum(want)
    if total > text_w and total:
        scale = text_w / total
        want = [max(min_w // 2, int(w * scale)) for w in want]
    return want


# ----------------------------------------------------------------------------- LingTeX-Word
# Examples are drawn the way LingTeX-Word draws them (rulingAnts/LingTeX-Tools, LingTeX-Word/src,
# read 2026-10-18; Seth: "all of our IGTs should be rendered using LingTeX Word styling wherever
# they're expanded"): ONE borderless table per line of text styled "LingTeX Interlinear", one row
# per tier whose first cell's paragraph style names the tier ("LingTeX Vernacular", "LingTeX
# Morphemes", "LingTeX Gloss", "LingTeX Word Gloss", "LingTeX Category"), the free translation a
# "LingTeX Free" paragraph AFTER the table in single quotes, grammatical glosses lowercased with a
# full-size first letter under the "LingTeX Gram Gloss" character style (small capitals — Word
# draws only lowercase letters small), the example number in a FIRST column as Word's own list
# numbering ("LingTeX Example Number", "(%1)"; a second cell "a.", "b." when one example is
# several lines), wrap lines as further row groups of the same table. A document that already has
# the add-in re-wraps these tables; one that does not shows them as they are.
LT_TABLE = "LingTeX Interlinear"
LT_ROLES = {"txt": "Vernacular", "morph": "Morphemes", "cf": "Morphemes", "mgls": "Gloss", "gls": "Word Gloss", "pos": "Category", "tag": "Category"}
LT_SMALLCAPS = {"Gloss", "Word Gloss", "Category"}
LT_NUMBER_HANG = 720            # 36 pt: the number column (LingTeX DEF_NUMBER_HANG)
LT_SUB_W = 360                  # the "a." cell
LT_GAP = 120                    # 6 pt between columns (DEF_GAP)
LT_LINE_GAP = 120               # 6 pt between wrap lines (DEF_LINE_GAP)
LT_FREE_ABOVE = 120             # 6 pt between the table and the translation (DEF_FREE_ABOVE)
LT_BASE_COLORS = {"00379C", "2A6E2A", "4A4F57", "68717D", "7A3E9D", "A8B0BA"}   # the app's own line colours, not the user's
MORPH_DIVS = "-=~<>"


def lt_style_id(name: str) -> str:
    return "".join(ch for ch in name if ch.isalnum())


def is_gram_gloss(seg: str) -> bool:
    """LingTeX-Word's structural test (modFlexParse.IsGramGloss): all capitals, or digit-initial;
    a lone capital, or one with a period, is not a gloss."""
    t = seg.strip()
    if not t:
        return False
    if len(t) == 2 and t[1] == "." and (t[0].isupper() or t[0] in "Ŋŋ"):
        return False
    core = t
    while core and not core[0].isalnum():
        core = core[1:]
    while core and not core[-1].isalnum():
        core = core[:-1]
    if not core:
        return False
    if len(core) == 1 and "A" <= core <= "Z":
        return False
    if core[0].isdigit():
        return all(ch.isalnum() or ch == "_" for ch in core[1:])
    return all(("A" <= ch <= "Z") or ch.isdigit() for ch in core)


def split_gloss_segments(text: str) -> list[str]:
    """modFlexParse.SplitGlossSegments: the morpheme boundaries, '.', ':' and ';' as segments of
    their own, so the pieces reassemble unchanged."""
    out: list[str] = []
    cur = ""
    for ch in text:
        if ch in MORPH_DIVS or ch in ".:;":
            if cur:
                out.append(cur)
                cur = ""
            out.append(ch)
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def small_caps_form(part: str) -> str:
    """Lowercased, the first LETTER a capital (LingTeX's default, Seth's preference: Erg, 3Sg)."""
    s = part.lower()
    for i, ch in enumerate(s):
        if ch.lower() != ch.upper():
            return s[:i] + ch.upper() + s[i + 1:]
    return s


def gram_gloss_runs(runs: list[dict]) -> list[dict]:
    """A meta-language tier's runs with every grammatical segment as its own run under the Gram
    Gloss character style, in its small-caps form; everything else untouched."""
    out: list[dict] = []
    for r in runs:
        text = str(r.get("text") or "")
        if not text:
            continue
        for seg in split_gloss_segments(text):
            x = {k: v for k, v in r.items() if k != "text"}
            if is_gram_gloss(seg):
                x["text"] = small_caps_form(seg)
                x["rStyle"] = lt_style_id("LingTeX Gram Gloss")
            else:
                x["text"] = seg
            out.append(x)
    return out


def lt_clean(r: dict) -> dict:
    """A run as LingTeX draws it: the styles say the look, so the app's own line colours and sizes
    go; what the USER set (a highlight, bold, underline, a colour of their own) stays."""
    x = {k: v for k, v in r.items() if k not in ("size",)}
    if _hex(x.get("color")) in LT_BASE_COLORS:
        x.pop("color", None)
    return x


LT_STYLES_XML = (
    # the tier paragraph styles: based on Normal, size inherited, tight and left-aligned
    "".join(f'<w:style w:type="paragraph" w:styleId="{lt_style_id("LingTeX " + role)}"><w:name w:val="LingTeX {role}"/><w:basedOn w:val="Normal"/>'
            + (f'<w:next w:val="Normal"/>' if role == "Free" else "")
            + f'<w:pPr><w:spacing w:before="0" w:after="{60 if role == "Free" else 0}" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/><w:widowControl w:val="0"/>'
            + ('<w:keepNext/>' if role != "Free" else "") + '</w:pPr>'
            + '<w:rPr>' + ('<w:rFonts w:ascii="Charis SIL" w:hAnsi="Charis SIL" w:cs="Charis SIL"/><w:i/><w:iCs/>' if role in ("Vernacular", "Morphemes") else "")
            + ('<w:noProof/>' if role != "Free" else "") + '</w:rPr></w:style>'
            for role in ("Vernacular", "Morphemes", "Gloss", "Word Gloss", "Category", "Free"))
    # the grammatical-gloss character style: small capitals
    + f'<w:style w:type="character" w:styleId="{lt_style_id("LingTeX Gram Gloss")}"><w:name w:val="LingTeX Gram Gloss"/><w:rPr><w:smallCaps/></w:rPr></w:style>'
    # the number-cell paragraph style, linked to the example-number list
    + f'<w:style w:type="paragraph" w:styleId="{lt_style_id("LingTeX Example")}"><w:name w:val="LingTeX Example"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
      '<w:pPr><w:keepNext/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/><w:widowControl w:val="0"/></w:pPr></w:style>'
    + f'<w:style w:type="numbering" w:styleId="{lt_style_id("LingTeX Example Number")}"><w:name w:val="LingTeX Example Number"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>'
    # the table style: the tag, and borderless with no cell padding
    + f'<w:style w:type="table" w:styleId="{lt_style_id(LT_TABLE)}"><w:name w:val="{LT_TABLE}"/><w:tblPr><w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
      '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
)

LT_NUMBERING_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/><w:styleLink w:val="{lt_style_id("LingTeX Example Number")}"/>'
                    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="(%1)"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr><w:rPr><w:i w:val="0"/><w:smallCaps w:val="0"/></w:rPr></w:lvl>'
                    '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr><w:rPr><w:i w:val="0"/><w:smallCaps w:val="0"/></w:rPr></w:lvl>'
                    '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')


class Docx:
    def __init__(self):
        self.body: list[str] = []
        self.media: list[tuple[str, bytes]] = []   # (name, png bytes)
        self.rels: list[str] = []
        self.in_cell = False                       # a sub-document for a table cell: no section breaks
        self.landscape = False                     # the current section's orientation

    # -- runs ---------------------------------------------------------------------

    def run(self, r: dict) -> str:
        text = str(r.get("text", ""))
        if text == "":
            return ""
        props = []
        if r.get("rStyle"):
            props.append(f'<w:rStyle w:val="{escape(str(r["rStyle"]))}"/>')
        if r.get("font"):
            f = escape(str(r["font"]))
            props.append(f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>')
        if r.get("b"):
            props.append("<w:b/><w:bCs/>")
        if r.get("i"):
            props.append("<w:i/><w:iCs/>")
        if r.get("u"):
            props.append('<w:u w:val="single"/>')
        if r.get("s"):
            props.append("<w:strike/>")
        if r.get("code"):
            props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>')
        if r.get("color"):
            h = _hex(r["color"])
            if h:
                props.append(f'<w:color w:val="{h}"/>')
        if r.get("hl"):
            c = r["hl"] if isinstance(r["hl"], str) else "#fff2a8"
            name = HL_NAMES.get(c.lower())
            if name:
                props.append(f'<w:highlight w:val="{name}"/>')
            else:
                h = _hex(c) or "FFF2A8"
                props.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{h}"/>')
        if r.get("size"):
            props.append(f'<w:sz w:val="{int(r["size"]) * 2}"/>')
        if r.get("rtl"):
            props.append("<w:rtl/>")
        if r.get("href") and not r.get("color"):
            props.append('<w:color w:val="1F4F8F"/><w:u w:val="single"/>')
        rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
        parts = text.split("\n")
        out = []
        for i, part in enumerate(parts):
            if i:
                out.append(f"<w:r>{rpr}<w:br/></w:r>")
            if part:
                out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
        xml = "".join(out)
        if r.get("href"):
            # a link (an attached file's file:/// URL): an external relationship of the document
            rid = f"rIdLink{len(self.rels) + 1}"
            self.rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                             f'Target="{escape(str(r["href"]), {chr(34): "&quot;"})}" TargetMode="External"/>')
            xml = f'<w:hyperlink r:id="{rid}" w:history="1">{xml}</w:hyperlink>'
        return xml

    def runs(self, runs: list[dict] | None) -> str:
        return "".join(self.run(r) for r in (runs or []))

    def para(self, runs, style: str = "", extra: str = "", rtl: bool = False) -> str:
        ppr = ""
        bits = []
        if style:
            bits.append(f'<w:pStyle w:val="{style}"/>')
        if rtl:
            bits.append("<w:bidi/>")
        if extra:
            bits.append(extra)
        if bits:
            ppr = f"<w:pPr>{''.join(bits)}</w:pPr>"
        return f"<w:p>{ppr}{self.runs(runs) if isinstance(runs, list) else runs}</w:p>"

    # -- blocks -------------------------------------------------------------------

    def add(self, block: dict) -> None:
        t = block.get("type")
        if self.landscape and t != "chart":
            self.body.append(f"<w:p><w:pPr>{SECT_LANDSCAPE}</w:pPr></w:p>")
            self.landscape = False
        if t == "h":
            self.body.append(self.para(block.get("runs"), f"Heading{min(6, max(1, int(block.get('level', 1))))}"))
        elif t == "p":
            self.body.append(self.para(block.get("runs"), rtl=bool(block.get("rtl"))))
        elif t == "quote":
            self.body.append(self.para(block.get("runs"), "Quote"))
        elif t == "code":
            for line in str(block.get("text", "")).split("\n"):
                self.body.append(self.para([{"text": line, "code": True}], "Code"))
        elif t == "list":
            for it in block.get("items", []):
                mark = ("☑ " if it.get("checked") else "☐ ") if it.get("task") else (f"{it.get('n', 1)}. " if it.get("ordered") else "• ")
                ind = f'<w:ind w:left="{360 + 360 * int(it.get("level", 0))}" w:hanging="360"/>'
                self.body.append(self.para([{"text": mark}] + list(it.get("runs", [])), extra=ind))
        elif t == "hr":
            self.body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="BBBBBB"/></w:pBdr></w:pPr></w:p>')
        elif t == "table":
            xml = self.table(block)
            if block.get("indent"):
                xml = self._indent(xml, 360 * int(block["indent"]))
            self.body.append(xml)
            self.body.append("<w:p/>")
        elif t == "chart":
            # a chart gets a LANDSCAPE section of its own: the paragraph before it closes the
            # portrait section, the paragraph after it closes the landscape one
            wide = not self.in_cell
            if wide and not self.landscape:
                self.body.append(f"<w:p><w:pPr>{SECT_PORTRAIT}</w:pPr></w:p>")
                self.landscape = True
            parts = self.chart(block)
            if block.get("exNum"):
                parts.insert(0, self.para([{"text": str(block["exNum"]), "color": "#68717d"}]))
            if block.get("indent"):
                parts = [self._indent(x, 360 * int(block["indent"])) for x in parts]
            self.body.extend(parts)
            self.body.append("<w:p/>")
        elif t == "interlinear":
            self.body.extend(self.interlinear(block))      # LingTeX shape: number column, indent inside
        elif t == "entry":
            parts = self.entry(block)
            if block.get("exNum"):      # (1), (2)… on its own line above the entry
                parts.insert(0, self.para([{"text": str(block["exNum"]), "color": "#68717d"}]))
            if block.get("indent"):
                parts = [self._indent(x, 360 * int(block["indent"])) for x in parts]
            self.body.extend(parts)
        elif t == "wordgrid":
            self.body.append(self.wordgrid(block))
        elif t == "image":
            self.body.append(self.image(block))
        elif t == "wordform":
            self.body.append(self.para([{"text": block.get("form", ""), "b": True, "font": block.get("font")}, {"text": "  " + "; ".join(block.get("glosses", []))}]))

    @staticmethod
    def _indent(xml: str, twips: int) -> str:
        """Step a paragraph or table in by `twips` (added to any indent it already has)."""
        if xml.startswith("<w:tbl>"):
            return xml.replace("<w:tblPr>", f'<w:tblPr><w:tblInd w:w="{twips}" w:type="dxa"/>', 1)
        if not xml.startswith("<w:p>"):
            return xml
        m = re.search(r'<w:ind w:left="(\d+)"', xml)
        if m:
            return xml[:m.start(1)] + str(int(m.group(1)) + twips) + xml[m.end(1):]
        ind = f'<w:ind w:left="{twips}"/>'
        if xml.startswith("<w:p><w:pPr>"):
            return xml.replace("<w:pPr>", "<w:pPr>" + ind, 1)
        return "<w:p><w:pPr>" + ind + "</w:pPr>" + xml[len("<w:p>"):]

    def cell(self, cell: dict, width: int | None = None, shade: str = "", borders: bool = True, extra: str = "") -> str:
        tcpr = []
        if extra:
            tcpr.append(extra)                    # gridSpan / vMerge for merged cells
        if width:
            tcpr.append(f'<w:tcW w:w="{width}" w:type="dxa"/>')
        if shade:
            tcpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
        if not borders:
            tcpr.append('<w:tcBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/></w:tcBorders>')
        inner = []
        if cell.get("_para"):
            inner.append(cell["_para"])
        if cell.get("blocks"):
            for b in cell["blocks"]:
                sub = Docx()
                sub.media = self.media
                sub.rels = self.rels
                sub.in_cell = True
                sub.add(b)
                inner.extend(sub.body)
        if (cell.get("runs") is not None or not inner) and not cell.get("_para"):
            align = cell.get("align")
            jc = f'<w:jc w:val="{ {"center": "center", "right": "right"}.get(align, "left") }"/>' if align in ("center", "right") else ""
            inner.insert(0, self.para(cell.get("runs") or [], extra=jc))
        if inner[-1].endswith("</w:tbl>"):
            inner.append('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr></w:p>')   # Word requires a paragraph after a nested table
        return f"<w:tc><w:tcPr>{''.join(tcpr)}</w:tcPr>{''.join(inner)}</w:tc>"

    def table(self, block: dict) -> str:
        rows = block.get("rows", [])
        if not rows:
            return ""
        style = block.get("style") or {}
        flags = set(style.get("flags", []))
        light = "borders-light" in flags
        none = "borders-none" in flags
        border = "nil" if none else "single"
        color = "DDDDDD" if light else "999999"
        tblpr = (f'<w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
                 f'<w:top w:val="{border}" w:sz="4" w:color="{color}"/><w:left w:val="{border}" w:sz="4" w:color="{color}"/>'
                 f'<w:bottom w:val="{border}" w:sz="4" w:color="{color}"/><w:right w:val="{border}" w:sz="4" w:color="{color}"/>'
                 f'<w:insideH w:val="{border}" w:sz="4" w:color="{color}"/><w:insideV w:val="{border}" w:sz="4" w:color="{color}"/>'
                 f'</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>')
        cols = style.get("cols", {}) or {}
        rowst = style.get("rows", {}) or {}
        fixed = {}
        for k, col in cols.items():
            w = col.get("width") if isinstance(col, dict) else None
            if isinstance(w, str) and w.endswith("px"):
                try:
                    fixed[int(k) - 1] = int(float(w[:-2]) * 15)
                except ValueError:
                    pass
        span_anchors = {}
        for key, v in (style.get("spans") or {}).items():
            try:
                ar, ac = (int(x) - 1 for x in str(key).split("."))
                span_anchors[(ar, ac)] = int(v.get("cols", 1))
            except (TypeError, ValueError, AttributeError):
                continue
        measured = [[dict(c, colspan=max(int(c.get("colspan") or 1), span_anchors.get((ri, ci), 1))) for ci, c in enumerate(r)] for ri, r in enumerate(rows)]
        widths = grid_widths(measured, (TEXT_W_LANDSCAPE if self.landscape else TEXT_W_PORTRAIT) - (360 * int(block.get("indent") or 0)), fixed, min_w=block.get("minColW", 500))
        grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
        out = [f"<w:tbl>{tblpr}{grid}"]
        spans: dict = {}
        covered: dict = {}
        for key, v in (style.get("spans") or {}).items():
            try:
                ar, ac = (int(x) - 1 for x in str(key).split("."))
                rn, cn = int(v.get("rows", 1)), int(v.get("cols", 1))
            except (TypeError, ValueError, AttributeError):
                continue
            rn = min(rn, len(rows) - ar)
            cn = min(cn, len(rows[0]) - ac) if rows else 1
            if ar < 0 or ac < 0 or rn < 1 or cn < 1 or (rn == 1 and cn == 1):
                continue
            spans[(ar, ac)] = (rn, cn)
            for i in range(ar, ar + rn):
                for j in range(ac, ac + cn):
                    if (i, j) != (ar, ac):
                        covered[(i, j)] = (ar, ac, rn, cn)
        for ri, row in enumerate(rows):
            cells = []
            for ci, c in enumerate(row):
                col = cols.get(str(ci + 1), {}) or {}
                rs = rowst.get(str(ri + 1), {}) or {}
                shade = _hex(c.get("bg")) or _hex(rs.get("bg") or col.get("bg")) or ("F3F4F6" if ri == 0 and block.get("header", True) else ("F7F8FA" if "striped" in flags and ri % 2 == 0 and ri else ""))
                c = dict(c)
                if ri == 0 and block.get("header", True) or rs.get("bold") or col.get("bold"):
                    c["runs"] = [dict(r, b=True) for r in (c.get("runs") or [])]
                if rs.get("italic") or col.get("italic"):
                    c["runs"] = [dict(r, i=True) for r in (c.get("runs") or [])]
                c["align"] = rs.get("align") or col.get("align") or (block.get("aligns") or [None] * 99)[ci] if ci < len(block.get("aligns") or []) else rs.get("align") or col.get("align")
                width = widths[ci] if ci < len(widths) else None
                # merged cells: a horizontal span is one <w:tc> with gridSpan; a vertical one is
                # the anchor marked vMerge="restart" and each covered cell below it a vMerge
                # continuation (Word needs the continuation cells to exist).
                cov = covered.get((ri, ci))
                if cov is not None:
                    ar, ac, rows_n, cols_n = cov
                    if ci != ac:
                        continue                     # inside a horizontal span: no cell at all
                    cells.append(self.cell({"runs": []}, sum(widths[ac:ac + cols_n]) or width, shade, extra=(f'<w:gridSpan w:val="{cols_n}"/>' if cols_n > 1 else "") + "<w:vMerge/>"))
                    continue
                sp = spans.get((ri, ci))
                extra = ""
                if sp:
                    if sp[1] > 1:
                        extra += f'<w:gridSpan w:val="{sp[1]}"/>'
                        width = sum(widths[ci:ci + sp[1]]) or width
                    if sp[0] > 1:
                        extra += '<w:vMerge w:val="restart"/>'
                cells.append(self.cell(c, width, shade, extra=extra))
            out.append(f"<w:tr>{''.join(cells)}</w:tr>")
        out.append("</w:tbl>")
        return "".join(out)

    def chart(self, block: dict) -> list[str]:
        """A text chart (export.js chartBlock): its title line, then ONE Word table — the header
        rows (a group spanning its columns), a row per chart row with the label first, each cell's
        words (their lines separated by line breaks) and markers, the Free column spanning the
        rows of a segment, the notes; a translation row after a segment's rows when the embed
        shows them that way."""
        out = []
        head = [{"text": (block.get("name") or "Chart") + " · ", "b": True}, {"text": block.get("title") or "", "b": True, "color": "#00379c", "font": (block.get("ws") or {}).get("font")}]
        if block.get("label"):
            head.append({"text": "   " + block["label"], "color": "#68717d"})
        out.append(self.para(head))
        rows: list[list[dict]] = []
        spans: dict = {}
        headers = block.get("headers") or []
        ncols = int(block.get("cols") or 0)
        xcols = block.get("xcols") or []          # a chart note's custom columns (export.js chartBlock extras)
        # a custom column sits LEFT or RIGHT of the FLEx columns (its `side`); xcells are by index
        x_left = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") == "left"]
        x_right = [(i, xc) for i, xc in enumerate(xcols) if xc.get("side") != "left"]
        extra = len(x_right) + (1 if block.get("freeCol") else 0) + (1 if block.get("notesCol") else 0)
        width = 1 + len(x_left) + ncols + extra

        def xhead(xc):
            return {"runs": [{"text": xc.get("name") or "", "b": True, "color": "#68717d"}], "align": "center"}

        for hi, hr in enumerate(headers):
            row = [{"runs": [{"text": "#" if hi == 0 else "", "b": True, "color": "#68717d"}]}]
            for _, xc in x_left:
                row.append(xhead(xc) if hi == 0 else {"runs": []})
                if hi == 0 and len(headers) > 1:
                    spans[f"1.{len(row)}"] = {"rows": len(headers), "cols": 1}
            ci = 1 + len(x_left)
            for h in hr:
                row.append({"runs": [{"text": h.get("text") or "", "b": True, "color": "#68717d"}], "align": "center"})
                if int(h.get("span") or 1) > 1:
                    spans[f"{len(rows) + 1}.{ci + 1}"] = {"rows": 1, "cols": int(h["span"])}
                    for _ in range(int(h["span"]) - 1):
                        row.append({"runs": []})
                ci += int(h.get("span") or 1)
            if hi == 0:
                for _, xc in x_right:
                    row.append(xhead(xc))
                    if len(headers) > 1:
                        spans[f"1.{len(row)}"] = {"rows": len(headers), "cols": 1}
                if block.get("freeCol"):
                    row.append({"runs": [{"text": "Free", "b": True, "color": "#68717d"}]})
                    if len(headers) > 1:
                        spans[f"1.{len(row)}"] = {"rows": len(headers), "cols": 1}
                if block.get("notesCol"):
                    row.append({"runs": [{"text": "Notes", "b": True, "color": "#68717d"}]})
                    if len(headers) > 1:
                        spans[f"1.{len(row)}"] = {"rows": len(headers), "cols": 1}
            else:
                for _ in range(extra):
                    row.append({"runs": []})
            if len(headers) > 1 and hi == 0:
                spans["1.1"] = {"rows": len(headers), "cols": 1}
            rows.append(row)
        def xcell_of(xc):
            xr = {"text": xc.get("text") or ""}
            for k in ("b", "i", "u"):
                if xc.get(k):
                    xr[k] = True
            if xc.get("color"):
                xr["color"] = xc["color"]
            xcell = {"runs": [xr]}
            if xc.get("hl"):
                xcell["bg"] = xc["hl"]
            return xcell

        for r in block.get("rows") or []:
            row = [{"runs": [{"text": r.get("label") or "", "b": True, "color": "#68717d"}], "align": "right"}]
            xcells = r.get("xcells") or []
            for i, _ in x_left:
                row.append(xcell_of(xcells[i] if i < len(xcells) else {}))
            for c in r.get("cells") or []:
                def dress(runs):
                    out_runs = []
                    for x in runs:
                        x = dict(x)
                        if c.get("b"):
                            x["b"] = True
                        if c.get("i"):
                            x["i"] = True
                        if c.get("u"):
                            x["u"] = True
                        if c.get("color") and not x.get("color"):
                            x["color"] = c["color"]
                        out_runs.append(x)
                    return out_runs
                # a word's runs come with '\n' runs between its lines: split them into lines
                words = []
                for w in c.get("words") or []:
                    lines: list[list[dict]] = [[]]
                    for x in w:
                        if str(x.get("text")) == "\n":
                            lines.append([])
                        else:
                            lines[-1].append(x)
                    words.append([dress(ln) for ln in lines])
                blocks = []
                if words:
                    blocks.append({"type": "wordgrid", "words": words})
                if c.get("marks"):
                    blocks.append({"type": "p", "runs": dress(c["marks"])})
                cell = {"runs": None, "blocks": blocks} if blocks else {"runs": []}
                if c.get("hl"):
                    cell["bg"] = c["hl"]
                row.append(cell)
                if int(c.get("span") or 1) > 1:
                    spans[f"{len(rows) + 1}.{len(row)}"] = {"rows": 1, "cols": int(c["span"])}
                    for _ in range(int(c["span"]) - 1):
                        row.append({"runs": []})
            for i, _ in x_right:
                row.append(xcell_of(xcells[i] if i < len(xcells) else {}))
            if block.get("freeCol"):
                fr = r.get("free")
                row.append({"runs": [{"text": fr["text"], "i": True}] if fr else []})
                if fr and int(fr.get("span") or 1) > 1:
                    spans[f"{len(rows) + 1}.{len(row)}"] = {"rows": int(fr["span"]), "cols": 1}
            if block.get("notesCol"):
                row.append({"runs": [{"text": r.get("notes") or "", "color": "#68717d"}]})
            rs = r.get("rowStyle") or {}
            if rs:                                   # a marker's "whole row" look, a rule's row case
                def all_runs(cell):
                    for x in cell.get("runs") or []:
                        yield x
                    for b in cell.get("blocks") or []:
                        for x in b.get("runs") or []:
                            yield x
                        for w in b.get("words") or []:
                            for ln in w:
                                for x in ln:
                                    yield x
                for cell in row[1:]:
                    if rs.get("bg") and not cell.get("bg"):
                        cell["bg"] = rs["bg"]
                    for x in all_runs(cell):
                        if rs.get("b"):
                            x["b"] = True
                        if rs.get("i"):
                            x["i"] = True
                        if rs.get("u"):
                            x["u"] = True
                        if rs.get("color") and not x.get("color"):
                            x["color"] = rs["color"]
            rows.append(row)
            if r.get("freeRow") and (r["freeRow"].get("text") or "").strip():
                frow = [{"runs": []}, {"runs": [{"text": r["freeRow"]["text"], "i": True}, {"text": "   " + (r["freeRow"].get("rows") or ""), "color": "#68717d"}]}]
                spans[f"{len(rows) + 1}.2"] = {"rows": 1, "cols": max(1, width - 1)}
                for _ in range(width - 2):
                    frow.append({"runs": []})
                rows.append(frow)
        rowst = {}
        for i, r in enumerate(rows):
            if i < len(headers):
                rowst[str(i + 1)] = {"bg": "#f3f4f6"}
        tbl = {"rows": rows, "header": False, "style": {"spans": spans, "rows": rowst, "flags": ["borders-light"]}, "minColW": 700}
        out.append(self.table(tbl))
        return out

    def wordgrid(self, block: dict) -> str:
        """A chart cell's words side by side, each word's lines under it (`words`: per word a
        list of lines, each a list of runs) — a borderless table, as the example tables are."""
        words = block.get("words") or []
        nlines = max((len(w) for w in words), default=0)
        if not words or not nlines:
            return "<w:p/>"
        widths = [max(300, min(40, max((_text_len(ln) for ln in w), default=1)) * 130 + 200) for w in words]   # 130 twips a character: Charis at 11 pt
        rows = []
        for li in range(nlines):
            cells = [self.cell({"runs": w[li] if li < len(w) else []}, widths[wi], borders=False) for wi, w in enumerate(words)]
            rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
        tblpr = (f'<w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
                 '<w:tblCellMar><w:left w:w="20" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>')
        grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
        return f"<w:tbl>{tblpr}{grid}{''.join(rows)}</w:tbl>"

    def interlinear(self, block: dict) -> list[str]:
        """An example as LingTeX-Word draws it (see the LingTeX section above): per line of text one
        "LingTeX Interlinear" table — a number column when the embed is numbered (`exNum`: Word's
        "(1)" on the first line, "a." / "b." when the example has several lines), one row per
        tier in its tier style, wrap lines as further row groups — then the free translation,
        literal translation and notes as "LingTeX Free" paragraphs, the source (the text and its
        FLEx line) after the translation as a link into FieldWorks."""
        out = []
        numbered = bool(block.get("exNum"))
        indent = 360 * int(block.get("indent") or 0)
        segs = [sg for sg in block.get("segments", []) if sg.get("lines") or sg.get("free") or sg.get("lit") or sg.get("notes")]
        several = numbered and len(segs) > 1
        num_w = LT_NUMBER_HANG if numbered else 0
        sub_w = LT_SUB_W if several else 0
        text_w = (TEXT_W_LANDSCAPE if self.landscape else TEXT_W_PORTRAIT) - indent - num_w - sub_w
        font = (block.get("ws") or {}).get("font") or ""
        for si, seg in enumerate(segs):
            lines = [ln for ln in seg.get("lines", []) if ln.get("name") in LT_ROLES]
            ncols = max((len(ln.get("cells", [])) for ln in lines), default=0)
            if ncols:
                # the cells as LingTeX writes them: object-language tiers keep their spaces unbreakable;
                # meta-language tiers get their grammatical segments in small capitals
                grid: list[list[list[dict]]] = []
                for ln in lines:
                    role = LT_ROLES[ln["name"]]
                    row_cells = []
                    for ci in range(ncols):
                        runs = [lt_clean(dict(x)) for x in (ln["cells"][ci] if ci < len(ln["cells"]) else [])]
                        if role in LT_SMALLCAPS:
                            runs = gram_gloss_runs(runs)
                        elif role in ("Vernacular", "Morphemes"):
                            for x in runs:
                                x["text"] = str(x.get("text") or "").replace(" ", "\u00a0")
                                if font and not x.get("font"):
                                    x["font"] = font
                        row_cells.append(runs)
                    grid.append(row_cells)
                # column widths from the longest cell of each column, plus the gap; wrap lines when
                # the columns run past the text width (a column is never split)
                widths = [max(300, min(40, max((_text_len(grid[t][ci]) for t in range(len(lines))), default=1)) * 130 + LT_GAP) for ci in range(ncols)]
                wrap_lines: list[list[int]] = [[]]
                used = 0
                for ci, w in enumerate(widths):
                    if wrap_lines[-1] and used + w > text_w:
                        wrap_lines.append([])
                        used = 0
                    wrap_lines[-1].append(ci)
                    used += w
                rows = []
                for g, cols_in_line in enumerate(wrap_lines):
                    for t, ln in enumerate(lines):
                        role = LT_ROLES[ln["name"]]
                        style = lt_style_id("LingTeX " + role)
                        last_tier = t == len(lines) - 1
                        gap_after = LT_LINE_GAP if (last_tier and g < len(wrap_lines) - 1) else 0
                        ppr_extra = f'<w:spacing w:before="0" w:after="{gap_after}"/>'
                        cells = []
                        if numbered:
                            # the number cell: Word's own "(1)" on the very first row of the example, empty elsewhere
                            if si == 0 and g == 0 and t == 0:
                                cells.append(self.cell({"runs": None, "blocks": None, "_para": self.para([], lt_style_id("LingTeX Example"), extra=ppr_extra)}, num_w, borders=False))
                            else:
                                cells.append(self.cell({"runs": None, "_para": self.para([], style, extra=ppr_extra)}, num_w, borders=False))
                        if several:
                            if g == 0 and t == 0:
                                cells.append(self.cell({"runs": None, "_para": self.para([], lt_style_id("LingTeX Example"), extra='<w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr>' + ppr_extra)}, sub_w, borders=False))
                            else:
                                cells.append(self.cell({"runs": None, "_para": self.para([], style, extra=ppr_extra)}, sub_w, borders=False))
                        for ci in cols_in_line:
                            cells.append(self.cell({"runs": None, "_para": self.para(grid[t][ci], style, extra=ppr_extra)}, widths[ci], borders=False))
                        rows.append(f"<w:tr><w:trPr><w:cantSplit/></w:trPr>{''.join(cells)}</w:tr>")
                line_w = [num_w + sub_w + sum(widths[ci] for ci in line) for line in wrap_lines]
                grid_w = [num_w] * bool(numbered) + [sub_w] * bool(several) + [widths[ci] for ci in wrap_lines[0]]
                tblpr = (f'<w:tblPr><w:tblStyle w:val="{lt_style_id(LT_TABLE)}"/><w:tblW w:w="{max(line_w)}" w:type="dxa"/>'
                         + (f'<w:tblInd w:w="{indent}" w:type="dxa"/>' if indent else "")
                         + '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
                         '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>')
                tblgrid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid_w) + "</w:tblGrid>"
                out.append(f"<w:tbl>{tblpr}{tblgrid}{''.join(rows)}</w:tbl>")
            # the translation(s) under the table, in single quotes, indented past the number; the
            # source reference after the free translation, linked to FLEx
            free_style = lt_style_id("LingTeX Free")
            left = indent + num_w + sub_w
            ind = f'<w:ind w:left="{left}"/>' if left else ""
            source = [{"text": "  "}, {"text": ((block.get("title") or "") + " " + str(seg.get("label") or seg.get("n") or "")).strip(), "color": "#68717d", "size": 9}]
            if block.get("url"):
                source[1]["href"] = block["url"]
            wrote_free = False
            for key in ("free", "lit"):
                v = seg.get(key)
                if not v:
                    continue
                runs = [{"text": "\u2018"}] + [lt_clean(dict(x)) for x in (v if isinstance(v, list) else [{"text": str(v)}])] + [{"text": "\u2019"}]
                if key == "lit":
                    runs = [{"text": "Lit. ", "color": "#68717d", "size": 9}] + runs
                if not wrote_free:
                    runs += source
                out.append(self.para(runs, free_style, extra=ind + (f'<w:spacing w:before="{LT_FREE_ABOVE}"/>' if not wrote_free and ncols else "")))
                wrote_free = True
            for v in seg.get("notes") or []:
                out.append(self.para([{"text": "Note  ", "color": "#a8b0ba", "size": 8}] + [dict(lt_clean(dict(x)), i=True) for x in (v if isinstance(v, list) else [{"text": str(v)}])], free_style, extra=ind))
            if not wrote_free:
                out.append(self.para(source[1:], free_style, extra=ind + (f'<w:spacing w:before="{LT_FREE_ABOVE}"/>' if ncols else "")))
        if block.get("label"):
            out.append(self.para([{"text": block["label"], "color": "#68717d", "size": 9}], extra=f'<w:ind w:left="{indent + num_w + sub_w}"/>' if (indent + num_w + sub_w) else ""))
        out.append("<w:p/>")
        return out

    def entry(self, block: dict) -> list[str]:
        head = [{"text": block.get("headword", ""), "b": True, "color": "#00379c", "size": 13, "font": block.get("font")}]
        for k in ("citationForm", "lexemeForm"):
            if block.get(k):
                head.append({"text": "  " + block[k], "color": "#68717d", "font": block.get("font")})
        if block.get("morphType"):
            head.append({"text": "  " + block["morphType"], "i": True, "color": "#a8b0ba"})
        elif block.get("pos") and not block.get("senses"):
            head.append({"text": "  " + block["pos"], "i": True, "color": "#7a3e9d"})
        out = [self.para(head)]
        if block.get("note"):
            out.append(self.para([{"text": block["note"], "i": True, "color": "#68717d"}], extra='<w:ind w:left="360"/>'))
        for s in block.get("senses", []):
            indent = 360 + 360 * int(s.get("level", 0) or 0)
            runs = [{"text": f"{s.get('number', '')}  " if s.get("number") else "", "color": "#68717d"}]
            if s.get("pos"):
                runs.append({"text": s["pos"] + " ", "i": True, "color": "#7a3e9d"})
            runs.append({"text": s.get("gloss", ""), "b": True, "color": "#2a6e2a"})
            if s.get("definition") and s.get("definition") != s.get("gloss"):
                runs.append({"text": (" — " if s.get("gloss") else "") + s["definition"]})
            out.append(self.para(runs, extra=f'<w:ind w:left="{indent}"/>'))
            if s.get("domains"):
                out.append(self.para([{"text": "; ".join(s["domains"]), "color": "#68717d", "size": 9}], extra=f'<w:ind w:left="{indent + 360}"/>'))
            for ex in s.get("examples", []):
                out.append(self.para([{"text": ex.get("text", ""), "color": "#00379c", "font": block.get("font")}, {"text": ("  ‘" + ex["translation"] + "’") if ex.get("translation") else ""}], extra=f'<w:ind w:left="{indent + 360}"/>'))
            if s.get("note"):
                out.append(self.para([{"text": s["note"], "i": True, "color": "#68717d"}], extra=f'<w:ind w:left="{indent + 360}"/>'))
        return out

    def image(self, block: dict) -> str:
        data = block.get("png") or ""
        if "," in data:
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data)
        except Exception:  # noqa: BLE001
            return ""
        idx = len(self.media) + 1
        name = f"image{idx}.png"
        self.media.append((name, raw))
        rid = f"rIdImg{idx}"
        self.rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>')
        w = int(block.get("width") or 600)
        h = int(block.get("height") or 300)
        cx, cy = int(min(w, 620) * 9525), int(h * min(w, 620) / max(1, w) * 9525)
        return (f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                f'<wp:docPr id="{idx}" name="{name}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{idx}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')

    # -- package ---------------------------------------------------------------------

    def build(self, title: str = "") -> bytes:
        document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}><w:body>'
                    + "".join(self.body)
                    + (SECT_LANDSCAPE if self.landscape else SECT_PORTRAIT)
                    + '</w:body></w:document>')
        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                  '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Charis SIL" w:eastAsia="Calibri"/><w:sz w:val="22"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
                  '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="200" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="140" w:after="60"/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading5"><w:name w:val="heading 5"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="4"/></w:pPr><w:rPr><w:b/><w:color w:val="595959"/><w:sz w:val="22"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading6"><w:name w:val="heading 6"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="5"/></w:pPr><w:rPr><w:b/><w:i/><w:color w:val="595959"/><w:sz w:val="22"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="567"/></w:pPr><w:rPr><w:i/><w:color w:val="555555"/></w:rPr></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr></w:style>'
                  + LT_STYLES_XML
                  + '</w:styles>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
                + "".join(self.rels) + '</Relationships>')
        content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                         '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
                         '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                         '</Types>')
        root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                     '</Relationships>')
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f'<dc:title>{escape(title or "")}</dc:title><dc:creator>FLEx Scratchpad</dc:creator></cp:coreProperties>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", root_rels)
            z.writestr("word/document.xml", document)
            z.writestr("word/styles.xml", styles)
            z.writestr("word/numbering.xml", LT_NUMBERING_XML)
            z.writestr("word/_rels/document.xml.rels", rels)
            z.writestr("docProps/core.xml", core)
            for name, raw in self.media:
                z.writestr("word/media/" + name, raw)
        return buf.getvalue()


def build_docx(doc: dict) -> bytes:
    d = Docx()
    for b in doc.get("blocks", []):
        d.add(b)
    return d.build(doc.get("title", ""))
