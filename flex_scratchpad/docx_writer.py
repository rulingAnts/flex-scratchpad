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


class Docx:
    def __init__(self):
        self.body: list[str] = []
        self.media: list[tuple[str, bytes]] = []   # (name, png bytes)
        self.rels: list[str] = []

    # -- runs ---------------------------------------------------------------------

    def run(self, r: dict) -> str:
        text = str(r.get("text", ""))
        if text == "":
            return ""
        props = []
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
        elif t in ("interlinear", "entry"):
            parts = self.interlinear(block) if t == "interlinear" else self.entry(block)
            if block.get("exNum"):      # (1), (2)… on its own line above the example
                parts.insert(0, self.para([{"text": str(block["exNum"]), "color": "#68717d"}]))
            if block.get("indent"):
                parts = [self._indent(x, 360 * int(block["indent"])) for x in parts]
            self.body.extend(parts)
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
        if cell.get("blocks"):
            for b in cell["blocks"]:
                sub = Docx()
                sub.media = self.media
                sub.rels = self.rels
                sub.add(b)
                inner.extend(sub.body)
        if cell.get("runs") is not None or not inner:
            align = cell.get("align")
            jc = f'<w:jc w:val="{ {"center": "center", "right": "right"}.get(align, "left") }"/>' if align in ("center", "right") else ""
            inner.insert(0, self.para(cell.get("runs") or [], extra=jc))
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
        out = [f"<w:tbl>{tblpr}"]
        cols = style.get("cols", {}) or {}
        rowst = style.get("rows", {}) or {}
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
                shade = _hex(rs.get("bg") or col.get("bg")) or ("F3F4F6" if ri == 0 and block.get("header", True) else ("F7F8FA" if "striped" in flags and ri % 2 == 0 and ri else ""))
                c = dict(c)
                if ri == 0 and block.get("header", True) or rs.get("bold") or col.get("bold"):
                    c["runs"] = [dict(r, b=True) for r in (c.get("runs") or [])]
                if rs.get("italic") or col.get("italic"):
                    c["runs"] = [dict(r, i=True) for r in (c.get("runs") or [])]
                c["align"] = rs.get("align") or col.get("align") or (block.get("aligns") or [None] * 99)[ci] if ci < len(block.get("aligns") or []) else rs.get("align") or col.get("align")
                width = None
                w = col.get("width")
                if isinstance(w, str) and w.endswith("px"):
                    try:
                        width = int(float(w[:-2]) * 15)   # px → twentieths of a point (~96 dpi)
                    except ValueError:
                        width = None
                # merged cells: a horizontal span is one <w:tc> with gridSpan; a vertical one is
                # the anchor marked vMerge="restart" and each covered cell below it a vMerge
                # continuation (Word needs the continuation cells to exist).
                cov = covered.get((ri, ci))
                if cov is not None:
                    ar, ac, rows_n, cols_n = cov
                    if ci != ac:
                        continue                     # inside a horizontal span: no cell at all
                    cells.append(self.cell({"runs": []}, width, shade, extra=(f'<w:gridSpan w:val="{cols_n}"/>' if cols_n > 1 else "") + "<w:vMerge/>"))
                    continue
                sp = spans.get((ri, ci))
                extra = ""
                if sp:
                    if sp[1] > 1:
                        extra += f'<w:gridSpan w:val="{sp[1]}"/>'
                    if sp[0] > 1:
                        extra += '<w:vMerge w:val="restart"/>'
                cells.append(self.cell(c, width, shade, extra=extra))
            out.append(f"<w:tr>{''.join(cells)}</w:tr>")
        out.append("</w:tbl>")
        return "".join(out)

    def interlinear(self, block: dict) -> list[str]:
        out = []
        head = []
        if block.get("title"):
            head.append({"text": block["title"], "b": True, "color": "#00379c", "font": (block.get("ws") or {}).get("font")})
        if block.get("label"):
            head.append({"text": "   " + block["label"], "color": "#68717d"})
        if head:
            out.append(self.para(head))
        for seg in block.get("segments", []):
            lines = seg.get("lines", [])
            ncols = max((len(l.get("cells", [])) for l in lines), default=0)
            if ncols:
                rows = []
                for li, line in enumerate(lines):
                    cells = []
                    num = {"runs": [{"text": str(seg.get("label") or seg.get("n", "")) if li == 0 else "", "color": "#a8b0ba", "size": 9}]}
                    cells.append(self.cell(num, 500, borders=False))
                    for ci in range(ncols):
                        runs = line["cells"][ci] if ci < len(line["cells"]) else []
                        cells.append(self.cell({"runs": runs}, None, borders=False))
                    rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
                tblpr = ('<w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="autofit"/>'
                         '<w:tblCellMar><w:left w:w="60" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar></w:tblPr>')
                out.append(f"<w:tbl>{tblpr}{''.join(rows)}</w:tbl>")
            for key, lab in (("free", "Free"), ("lit", "Lit."), ("notes", "Note")):
                vals = seg.get(key)
                if not vals:
                    continue
                for v in (vals if isinstance(vals, list) else [vals]):
                    runs = v if isinstance(v, list) else [{"text": str(v)}]
                    out.append(self.para([{"text": lab + "  ", "color": "#a8b0ba", "size": 8}] + runs, extra='<w:ind w:left="360"/>'))
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
                    + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
                    '</w:body></w:document>')
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
                  '</w:styles>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                + "".join(self.rels) + '</Relationships>')
        content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
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
