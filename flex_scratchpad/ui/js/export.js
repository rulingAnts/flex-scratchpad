/* export.js — one document model of a note, serialised four ways:
 *   Markdown  the note file itself
 *   HTML      self-contained, examples rendered and styled (opens in a browser or Word)
 *   DOCX      the model is handed to Python's docx_writer
 *   PDF       the HTML rendering through the print dialog ("Save as PDF")
 *
 * Model: {title, blocks:[...]} — see flex_scratchpad/docx_writer.py for the block shapes.
 * A run is {text, b, i, u, s, hl, color, code, font, rtl}. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { esc } = FS;
  const MD = FS.markdown;
  const R = FS.flexref;
  const el = FS.el;

  /* ------------------------------------------------------------------ inline → runs */
  function runsOf(text) {
    text = String(text || '');
    const out = { marks: [], embeds: [], links: [], tags: [] };
    for (let i = 0; i < text.length; i++) out.marks.push(new Set());
    MD.markInline(text, out, 0);
    const runs = [];
    let cur = null;
    for (let i = 0; i < text.length; i++) {
      const set = out.marks[i];
      if (set.has('mk')) continue;
      if (set.has('embed')) continue;      // embeds are handled by the caller (cells)
      if (set.has('br')) { push({ text: '\n' }); continue; }
      const r = { text: text[i] };
      if (set.has('b')) r.b = true;
      if (set.has('i')) r.i = true;
      if (set.has('s')) r.s = true;
      if (set.has('mark')) r.hl = true;
      if (set.has('code')) r.code = true;
      if (set.has('link') || set.has('wiki')) r.color = '#1f4f8f';
      if (set.has('tag')) r.color = '#2a6e2a';
      push(r);
    }
    function push(r) {
      const sig = (x) => [x.b, x.i, x.s, x.hl, x.code, x.color].join('|');
      if (cur && sig(cur) === sig(r)) cur.text += r.text; else { cur = Object.assign({}, r); runs.push(cur); }
    }
    return runs;
  }

  /* ------------------------------------------------------------------ FLEx objects → model */
  const STYLE_KEYS = { hl: 'hl', b: 'b', u: 'u', i: 'i', s: 's', color: 'color' };
  function styledRuns(text, styles, base) {
    const gs = FS.graphemes(text || '');
    const runs = [];
    let cur = null;
    gs.forEach((g, i) => {
      const r = Object.assign({ text: g }, base || {});
      for (const st of styles || []) {
        const a = st.chars ? st.chars[0] : 1, b = st.chars ? st.chars[1] : gs.length;
        if (i + 1 < a || i + 1 > b) continue;
        if (st.style === 'hl') r.hl = st.color || true;
        else if (st.style === 'color') r.color = st.color || '#c0392b';
        else r[STYLE_KEYS[st.style]] = true;
      }
      const sig = (x) => [x.b, x.i, x.u, x.s, x.hl, x.color, x.font].join('|');
      if (cur && sig(cur) === sig(r)) cur.text += g; else { cur = r; runs.push(cur); }
    });
    return runs;
  }

  async function flexBlock(spec) {
    const kind = spec.kind === 'sense' ? 'entry' : spec.kind;
    const obj = await FS.interlinear.flexGet(kind, spec.guid, spec.kind === 'text' && spec.seg ? spec.seg[0] : null, spec.kind === 'text' && spec.seg ? spec.seg[1] : null, false, spec.kind === 'text' ? spec.ws : null);
    if (kind === 'entry') {
      const F = new Set(R.entryFields(spec));
      return { type: 'entry', headword: obj.headword || obj.lexemeForm, pos: obj.pos, font: obj.ws && obj.ws.vern && obj.ws.vern.font, label: spec.label,
        citationForm: F.has('cf') && obj.citationForm !== obj.headword ? obj.citationForm : '', lexemeForm: F.has('lf') && obj.lexemeForm !== obj.headword ? obj.lexemeForm : '',
        morphType: F.has('mt') ? obj.morphType : '', note: F.has('note') ? obj.note : '',
        senses: R.visibleSenses(spec, obj.senses).map((s) => ({ number: F.has('sn') ? s.number : '', level: s.level || 0, pos: F.has('spos') ? s.pos : '', gloss: F.has('gl') ? s.gloss : '', definition: F.has('def') ? s.definition : '',
          examples: F.has('ex') ? (s.examples || []).map((ex) => ({ text: ex.text, translation: F.has('tr') ? ex.translation : '' })) : [],
          note: F.has('snote') ? s.note : '', domains: F.has('sem') ? (s.domains || []) : [] })) };
    }
    if (kind === 'wordform') return { type: 'wordform', form: obj.form, glosses: obj.glosses || [], font: obj.ws && obj.ws.vern && obj.ws.vern.font };
    const lines = spec.lines && spec.lines.length ? spec.lines : R.DEFAULT_LINES;
    const index = R.resolveStyles(spec, obj);
    const vern = obj.ws && obj.ws.vern || {};
    const vbase = { color: '#00379c', font: vern.font || undefined, rtl: !!vern.rtl };
    const segs = (obj.segments || []).filter((seg) => !FS.interlinear.blankSeg(seg)).map((seg) => {   // blank lines are left out
      const words = (seg.words || []).filter((w) => !w.punct);
      const lineModels = [];
      const add = (name, cellsFn) => { const cells = words.map((w, i) => cellsFn(w, i + 1)); if (cells.some((c) => c.some((r) => r.text))) lineModels.push({ name, cells }); };
      // FLEx text markup tags styling the TEXT: brackets round the span and a marker behind the words
      const toks = seg.words || [];
      const aiOf = words.map((w) => (w.ai != null ? w.ai : toks.indexOf(w)));
      const tg = lines.includes('tag') && FS.interlinear.segTags ? FS.interlinear.segTags(obj, spec, seg) : [];
      const BR = (FS.tagstyles && FS.tagstyles.BRACKETS) || {};
      const txtRuns = (w, i) => {
        const ai = aiOf[i - 1];
        const runs = styledRuns(w.txt, R.stylesFor(index, seg.n, 'txt', i), vbase);
        const on = tg.filter((o) => ai >= o.a && ai <= o.z);
        for (const o of on) { if (o.res.hl || o.res.tile) for (const r of runs) if (!r.hl) r.hl = (o.res.tile && o.res.tc) || o.res.bg; if (o.res.c) for (const r of runs) r.color = o.res.c; if (o.res.b) for (const r of runs) r.b = true; if (o.res.i) for (const r of runs) r.i = true; }
        const open = on.filter((o) => o.res.br && BR[o.res.br] && o.firstAi === ai && seg.n === o.t.from.seg).sort((x, y) => y.span - x.span).map((o) => BR[o.res.br][0]).join('');
        const close = on.filter((o) => o.res.br && BR[o.res.br] && o.lastAi === ai && seg.n === o.t.to.seg).sort((x, y) => x.span - y.span).map((o) => BR[o.res.br][1] + (o.res.label && !o.res.showBar ? (o.t.tag.abbr || o.t.tag.name) : '')).join('');
        if (open) runs.unshift({ text: open, color: vbase.color });
        if (close) runs.push({ text: close, color: vbase.color });
        return runs;
      };
      for (const line of lines) {
        if (line === 'txt') add('txt', txtRuns);
        else if (line === 'morph') add('morph', (w, i) => styledRuns((w.morphs || []).map((m) => m.form).join(' '), R.stylesFor(index, seg.n, 'morph', i), { font: vern.font || undefined, color: '#4a4f57' }));
        else if (line === 'mgls') add('mgls', (w, i) => styledRuns((w.morphs || []).map((m) => m.gls).join(' '), R.stylesFor(index, seg.n, 'mgls', i), { color: '#2a6e2a' }));
        else if (line === 'cf') add('cf', (w, i) => styledRuns((w.morphs || []).map((m) => m.cf || '').join(' '), R.stylesFor(index, seg.n, 'cf', i), { color: '#68717d' }));
        else if (line === 'gls') add('gls', (w, i) => styledRuns(w.gls || '', R.stylesFor(index, seg.n, 'gls', i), { color: '#2a6e2a' }));
        else if (line === 'pos') add('pos', (w, i) => styledRuns(w.pos || '', R.stylesFor(index, seg.n, 'pos', i), { color: '#7a3e9d', size: 9 }));
      }
      // FLEx text markup tags: a line per lane, the abbreviation on the tag's first word, its colour behind
      if (tg.length) {
        const lanes = tg.reduce((m, o) => Math.max(m, o.lane + 1), 0);
        for (let l = 0; l < lanes; l++) add('tag', (w, i) => { const ai = aiOf[i - 1]; const o = tg.find((x) => x.lane === l && ai >= x.a && ai <= x.z); return o ? [{ text: ai === o.firstAi ? (o.t.tag.abbr || o.t.tag.name) : '\u00a0', hl: o.res.bg, size: 8, b: true }] : [{ text: '' }]; });
      }
      const out = { n: seg.n, label: seg.label || String(seg.n), lines: lineModels };
      if (lines.includes('ft') && seg.free) out.free = styledRuns(seg.free, R.stylesFor(index, seg.n, 'ft', 0), {});
      if (lines.includes('lit') && seg.lit) out.lit = styledRuns(seg.lit, R.stylesFor(index, seg.n, 'lit', 0), { color: '#68717d' });
      if (lines.includes('note') && (seg.notes || []).length) out.notes = seg.notes.map((n) => styledRuns(n, R.stylesFor(index, seg.n, 'note', 0), { i: true, color: '#68717d' }));
      return out;
    });
    return { type: 'interlinear', title: obj.title, label: spec.label, segments: segs, ws: vern, segmentCount: obj.segmentCount, range: obj.range };
  }

  /* ------------------------------------------------------------------ note → model */
  async function buildDoc(note, editor) {
    const blocks = [];
    const numCtx = { counters: [] };                        // outline numbering carried across blocks
    let exNum = 0;                                          // (1), (2)… for embeds flagged `ex`
    for (const b of editor.blocks) {
      if (b.type !== 'list' && b.type !== 'p') numCtx.counters = [];
      if (b.type === 'p' || b.type === 'quote') {
        const parts = await textWithEmbeds(b.src);
        for (const part of parts) blocks.push(part.type ? part : { type: b.type, runs: part.runs });
      } else if (b.type === 'h') {
        const m = /^(#{1,6})\s+(.*)$/.exec(b.src);
        blocks.push({ type: 'h', level: m ? m[1].length : 1, runs: runsOf(m ? m[2] : b.src) });
      } else if (b.type === 'code') {
        blocks.push({ type: 'code', text: b.src.replace(/^\s*```[^\n]*\n?/, '').replace(/\n?\s*```\s*$/, '') });
      } else if (b.type === 'list') {
        const items = [];
        const srcLines = b.src.split('\n');
        const nums = FS.markdown.numberLines(srcLines, 'list', numCtx);      // the outline numbers as shown
        srcLines.forEach((line, li) => {
          const m = /^(\s*)([-*+]|(\d+)[.)])\s+(\[([ xX])\]\s+)?(.*)$/.exec(line);
          if (!m) { if (items.length) items[items.length - 1].runs.push({ text: '\n' + line.trim() }); return; }
          const ordered = !!m[3];
          items.push({ runs: runsOf(m[6]), ordered, n: ordered ? (nums[li] || parseInt(m[3], 10)) : 0, level: FS.markdown.listLevel({ indent: m[1].length }), task: !!m[4], checked: m[5] ? m[5] !== ' ' : false });
        });
        blocks.push({ type: 'list', items });
      } else if (b.type === 'hr') {
        blocks.push({ type: 'hr' });
      } else if (b.type === 'flex') {
        const spec = R.parse(b.src);
        if (spec) {
          const x = spec.extra || {};
          const layout = { exNum: x.ex ? '(' + (++exNum) + ')' : '', indent: Math.max(0, Math.min(4, parseInt(x.indent, 10) || 0)) };
          let blk;
          if (spec.kind === 'file') blk = { type: 'p', runs: [await fileRun(spec)] };
          else try { blk = await flexBlock(spec); } catch (e) { blk = { type: 'p', runs: [{ text: '[FLEx object unavailable: ' + (e.message || e) + ']', color: '#c0392b' }] }; }
          blocks.push(Object.assign(blk, layout));
        }
      } else if (b.type === 'table') {
        const t = FS.tables.parse(b.src);
        const rows = [];
        const spans = FS.tables.spanMap(t);
        for (const [ri, row] of t.rows.entries()) {
          const cells = [];
          for (const [ci, cell] of row.entries()) {
            const parts = await textWithEmbeds(cell);
            const out = (parts.length === 1 && !parts[0].type) ? { runs: parts[0].runs } : { runs: null, blocks: parts.map((p) => (p.type ? p : { type: 'p', runs: p.runs })) };
            const sp = spans.anchors[ri + '.' + ci];
            if (sp) { out.rowspan = sp.rows; out.colspan = sp.cols; }
            if (spans.covered.has(ri + '.' + ci)) out.covered = true;
            cells.push(out);
          }
          rows.push(cells);
        }
        blocks.push({ type: 'table', rows, aligns: t.aligns, header: true, style: { flags: [...t.style.flags], cols: t.style.cols, rows: t.style.rows, spans: t.style.spans }, indent: t.style.indent || 0 });
      } else if (b.type === 'chart') {
        const canvas = b.el && b.el.querySelector('canvas');
        if (canvas) blocks.push({ type: 'image', png: canvas.toDataURL('image/png'), width: canvas.clientWidth, height: canvas.clientHeight, alt: 'chart' });
      } else if (b.type === 'image') {
        const m = /^!\[([^\]]*)\]\(([^)\s]+)/.exec(b.src.trim());
        if (m) blocks.push({ type: 'imageref', src: m[2], alt: m[1] });
      }
    }
    return { title: note.title || 'Untitled', blocks };
  }

  /* An attached file in an export (Seth, 2026-10-17): a Word / HTML / PDF file cannot hold it,
   * so it is 📎 and its label, LINKED to the file (it opens on this computer; elsewhere it is
   * the name). */
  async function fileRun(spec) {
    const ci = FS.files.chipInfo(spec);
    let href = '';
    try { const inf = await FS.files.info(spec.ref); if (inf.exists) href = inf.fileUrl || ''; } catch (e) { /* the name, unlinked */ }
    const r = { text: '📎 ' + ci.title, color: '#1f4f8f' };
    if (href) r.href = href;
    return r;
  }

  /* Text that may contain {{flex …}} embeds: split into runs parts and object blocks. An
   * attached file stays IN its line, as a linked run. */
  async function textWithEmbeds(text) {
    const parts = [];
    let pos = 0, runs = [];
    const flush = () => { if (runs.length) parts.push({ runs }); runs = []; };
    for (const e of R.findEmbeds(text)) {
      if (e.start > pos) runs.push(...runsOf(text.slice(pos, e.start)));
      pos = e.end;
      if (e.spec.kind === 'file') { runs.push(await fileRun(e.spec)); continue; }
      flush();
      try { parts.push(await flexBlock(e.spec)); } catch (err) { parts.push({ runs: [{ text: '[FLEx object unavailable]', color: '#c0392b' }] }); }
    }
    if (pos < text.length) runs.push(...runsOf(text.slice(pos)));
    flush();
    if (!parts.length) parts.push({ runs: [] });
    return parts.filter((p) => p.type || p.runs.some((r) => r.text.trim()) || parts.length === 1);
  }

  /* ------------------------------------------------------------------ model → HTML */
  const CSS = `
  body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; color: #1a1d21; max-width: 860px; margin: 32px auto; padding: 0 24px; }
  h1 { font-size: 26px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
  blockquote { border-left: 3px solid #d9dde3; margin: 8px 0; padding-left: 12px; color: #68717d; font-style: italic; }
  pre { background: #f3f4f6; padding: 10px 12px; border-radius: 8px; font: 13px/1.5 Consolas, Menlo, monospace; }
  code { background: #e9ebef; border-radius: 3px; padding: 0 3px; font-family: Consolas, Menlo, monospace; font-size: 0.92em; }
  mark { background: #fff2a8; }
  table.note { border-collapse: collapse; margin: 8px 0 14px; } table.note th, table.note td { border: 1px solid #d9dde3; padding: 6px 10px; vertical-align: top; } table.note th { background: #f3f4f6; text-align: left; }
  table.note.striped tbody tr:nth-child(even) td { background: #f7f8fa; } table.note.borders-light th, table.note.borders-light td { border-color: #e8ebef; } table.note.borders-none th, table.note.borders-none td { border-color: transparent; }
  .obj { border: 1px solid #e8ebef; border-radius: 10px; padding: 10px 12px; margin: 8px 0 14px; background: #fff; }
  .obj .ttl { font-weight: 700; color: #00379c; font-family: "Charis SIL", "Doulos SIL", serif; font-size: 15px; } .obj .lbl { color: #68717d; font-size: 13px; margin-left: 10px; }
  .exrow { display: flex; gap: 10px; align-items: flex-start; } .exrow .exn { flex: none; min-width: 30px; padding-top: 14px; color: #68717d; } .exrow .exbody { flex: 1 1 auto; min-width: 0; }
  .seg { display: flex; gap: 10px; padding: 5px 0; border-top: 1px dotted #e8ebef; } .seg:first-of-type { border-top: 0; } .n { color: #a8b0ba; font-size: 12px; width: 26px; text-align: right; flex: none; }
  .il { display: flex; flex-wrap: wrap; gap: 0 14px; } .w { display: flex; flex-direction: column; } .l { white-space: nowrap; line-height: 1.35; }
  .txt { color: #00379c; font-family: "Charis SIL", "Doulos SIL", serif; font-size: 17px; } .morph { color: #4a4f57; font-family: "Charis SIL", serif; font-size: 14px; } .mgls, .gls { color: #2a6e2a; font-size: 13.5px; } .cf { color: #68717d; font-size: 12.5px; } .pos { color: #7a3e9d; font-size: 12px; }
  .ft { margin-top: 6px; } .ft b, .lit b, .note b { font-size: 11px; color: #a8b0ba; text-transform: uppercase; margin-right: 8px; font-weight: 400; } .lit { color: #68717d; font-size: 13.5px; } .note { color: #68717d; font-style: italic; font-size: 13px; }
  .hw { font-size: 20px; font-weight: 700; color: #00379c; font-family: "Charis SIL", serif; } .sense { display: flex; gap: 8px; padding: 3px 0; } .sense .sn { color: #a8b0ba; min-width: 20px; text-align: right; } .sense .pos { font-style: italic; } .sense .gl { color: #2a6e2a; font-weight: 600; } .ex { color: #68717d; margin-left: 6px; border-left: 2px solid #e8ebef; padding-left: 8px; font-size: 13.5px; } .ex .v { color: #00379c; font-family: "Charis SIL", serif; font-size: 14.5px; }
  ul.task { list-style: none; padding-left: 8px; } hr { border: 0; border-top: 1px solid #d9dde3; margin: 16px 0; } img { max-width: 100%; }
  [dir=rtl] .il { flex-direction: row-reverse; justify-content: flex-end; }
  @media print { body { margin: 0; max-width: none; } .obj { break-inside: avoid; } }`;

  function runHtml(r) {
    let s = esc(r.text).replace(/\n/g, '<br>');
    const css = [];
    if (r.font) css.push('font-family:"' + esc(r.font) + '",serif');
    if (r.color) css.push('color:' + esc(r.color));
    if (r.hl) css.push('background:' + (typeof r.hl === 'string' ? esc(r.hl) : '#fff2a8'));
    if (r.size) css.push('font-size:' + r.size + 'pt');
    if (r.code) s = '<code>' + s + '</code>';
    if (r.b) s = '<b>' + s + '</b>';
    if (r.i) s = '<i>' + s + '</i>';
    if (r.u) s = '<u>' + s + '</u>';
    if (r.s) s = '<s>' + s + '</s>';
    if (r.href) s = '<a href="' + esc(r.href) + '">' + s + '</a>';
    return css.length ? '<span style="' + css.join(';') + '">' + s + '</span>' : s;
  }
  const runsHtml = (runs) => (runs || []).map(runHtml).join('');

  function blockHtml(b) {
    const inner = blockHtmlInner(b);
    if (!b.exNum && !b.indent) return inner;
    return '<div class="exrow"' + (b.indent ? ' style="margin-left:' + (b.indent * 24) + 'px"' : '') + '>' + (b.exNum ? '<span class="exn">' + esc(b.exNum) + '</span>' : '') + '<div class="exbody">' + inner + '</div></div>';
  }
  function blockHtmlInner(b) {
    switch (b.type) {
      case 'h': return '<h' + b.level + '>' + runsHtml(b.runs) + '</h' + b.level + '>';
      case 'p': return '<p' + (b.rtl ? ' dir="rtl"' : '') + '>' + runsHtml(b.runs) + '</p>';
      case 'quote': return '<blockquote>' + runsHtml(b.runs) + '</blockquote>';
      case 'code': return '<pre>' + esc(b.text) + '</pre>';
      case 'hr': return '<hr>';
      case 'list': {
        const task = b.items.some((i) => i.task);
        const ordered = b.items.length && b.items[0].ordered;
        return '<' + (ordered ? 'ol' : 'ul') + (task ? ' class="task"' : '') + '>' + b.items.map((i) => '<li style="margin-left:' + (i.level * 18) + 'px">' + (i.task ? (i.checked ? '☑ ' : '☐ ') : '') + runsHtml(i.runs) + '</li>').join('') + '</' + (ordered ? 'ol' : 'ul') + '>';
      }
      case 'table': {
        const flags = (b.style && b.style.flags) || [];
        const cols = (b.style && b.style.cols) || {}, rows = (b.style && b.style.rows) || {};
        const cellStyle = (ri, ci) => { const c = cols[ci + 1] || {}, r = rows[ri + 1] || {}; const css = []; const a = r.align || c.align || (b.aligns || [])[ci]; if (a) css.push('text-align:' + a); if (c.width) css.push('width:' + c.width); if (r.bg || c.bg) css.push('background:' + (r.bg || c.bg)); if (r.color || c.color) css.push('color:' + (r.color || c.color)); if (r.bold || c.bold) css.push('font-weight:700'); if (r.italic || c.italic) css.push('font-style:italic'); if (r.nowrap || c.nowrap) css.push('white-space:nowrap'); if (r.vern || c.vern) css.push('font-family:"Charis SIL",serif;color:#00379c'); return css.length ? ' style="' + css.join(';') + '"' : ''; };
        const cellHtml = (c) => c.blocks ? c.blocks.map(blockHtml).join('') : runsHtml(c.runs);
        const spanAttr = (c) => (c.rowspan > 1 ? ' rowspan="' + c.rowspan + '"' : '') + (c.colspan > 1 ? ' colspan="' + c.colspan + '"' : '');
        return '<table class="note ' + flags.join(' ') + '">' + b.rows.map((row, ri) => '<tr>' + row.map((c, ci) => c.covered ? '' : (ri === 0 ? '<th' : '<td') + spanAttr(c) + cellStyle(ri, ci) + '>' + cellHtml(c) + (ri === 0 ? '</th>' : '</td>')).join('') + '</tr>').join('') + '</table>';
      }
      case 'interlinear': {
        const rtl = b.ws && b.ws.rtl;
        return '<div class="obj"' + (rtl ? ' dir="rtl"' : '') + '><div><span class="ttl">' + esc(b.title || '') + '</span>' + (b.label ? '<span class="lbl">' + esc(b.label) + '</span>' : '') + '</div>'
          + b.segments.map((seg) => {
            const ncols = Math.max(0, ...seg.lines.map((l) => l.cells.length));
            const words = [];
            for (let i = 0; i < ncols; i++) words.push('<div class="w">' + seg.lines.map((l) => '<div class="l ' + l.name + '">' + runsHtml(l.cells[i] || []) + '</div>').join('') + '</div>');
            return '<div class="seg"><span class="n">' + esc(seg.label || seg.n) + '</span><div><div class="il">' + words.join('') + '</div>'
              + (seg.free ? '<div class="ft"><b>Free</b>' + runsHtml(seg.free) + '</div>' : '') + (seg.lit ? '<div class="lit"><b>Lit</b>' + runsHtml(seg.lit) + '</div>' : '')
              + (seg.notes || []).map((n) => '<div class="note"><b>Note</b>' + runsHtml(n) + '</div>').join('') + '</div></div>';
          }).join('') + '</div>';
      }
      case 'entry': return '<div class="obj"><div><span class="hw">' + esc(b.headword || '') + '</span>' + (b.citationForm ? ' <span class="pos">' + esc(b.citationForm) + '</span>' : '') + (b.lexemeForm ? ' <span class="pos">' + esc(b.lexemeForm) + '</span>' : '') + (b.morphType ? ' <span class="pos">' + esc(b.morphType) + '</span>' : '') + (b.label ? '<span class="lbl">' + esc(b.label) + '</span>' : '') + '</div>'
        + (b.note ? '<div class="note">' + esc(b.note) + '</div>' : '')
        + (b.senses || []).map((s) => '<div class="sense" style="margin-left:' + ((s.level || 0) * 18) + 'px"><span class="sn">' + esc(s.number || '') + '</span><div>' + (s.pos ? '<span class="pos">' + esc(s.pos) + '</span> ' : '') + '<span class="gl">' + esc(s.gloss || '') + '</span>' + (s.definition && s.definition !== s.gloss ? (s.gloss ? ' — ' : '') + esc(s.definition) : '') + ((s.domains || []).length ? '<div class="note">' + esc(s.domains.join('; ')) + '</div>' : '') + (s.examples || []).map((ex) => '<div class="ex"><span class="v">' + esc(ex.text || '') + '</span>' + (ex.translation ? ' ‘' + esc(ex.translation) + '’' : '') + '</div>').join('') + (s.note ? '<div class="note">' + esc(s.note) + '</div>' : '') + '</div></div>').join('') + '</div>';
      case 'wordform': return '<div class="obj"><span class="hw">' + esc(b.form || '') + '</span> <span class="gls">' + esc((b.glosses || []).join('; ')) + '</span></div>';
      case 'image': return '<p><img src="' + b.png + '" alt="' + esc(b.alt || '') + '"></p>';
      case 'imageref': return '<p><img src="' + esc(b.src) + '" alt="' + esc(b.alt || '') + '"></p>';
      default: return '';
    }
  }

  function toHtml(doc) {
    return '<!doctype html><html><head><meta charset="utf-8"><title>' + esc(doc.title) + '</title><style>' + CSS + '</style></head><body><h1>' + esc(doc.title) + '</h1>'
      + doc.blocks.map(blockHtml).join('\n') + '\n<p style="color:#a8b0ba;font-size:11px;margin-top:40px">Exported from FLEx Scratchpad</p></body></html>';
  }

  /* ------------------------------------------------------------------ examples → .flextext
   * (Seth, 2026-10-16: "collect and concentrate certain grammatical constructions … and then
   * have one flex text where I can analyze those in text chart"). The note's text embeds, in
   * order, wherever they sit (blocks, inline chips, table cells); Python fetches each with
   * every writing system and writes one FLEx text per baseline writing system. */
  function flextextItems(editor) {
    const items = [];
    for (const b of editor.blocks) {
      for (const e of R.findEmbeds(b.src || '')) {
        const sp = e.spec;
        if (!sp || sp.kind === 'file') continue;
        items.push({ kind: sp.kind, guid: sp.guid, seg: sp.seg, at: sp.at, label: sp.label || '' });
      }
    }
    return items;
  }
  async function exportFlextext(note, editor) {
    const items = editor.flextextItems ? editor.flextextItems() : flextextItems(editor);   // a collection brings its notes
    const texts = items.filter((i) => i.kind === 'text');
    if (!texts.length) { FS.toast('This note has no text examples to export.', 'warn'); return null; }
    let preview = { texts: [], skipped: 0 };
    try { preview = await FS.api.flextext_preview(items); } catch (e) { /* the dialog still opens */ }
    return new Promise((resolve) => {
      const m = FS.modal({ title: 'Export examples as a FLEx text (.flextext)', class: 'narrow', onClose: () => resolve(null) });
      const title = el('input', { type: 'text', value: note.title || 'Examples', style: { width: '100%' } });
      const link = el('input', { type: 'checkbox', checked: true });
      const md = el('input', { type: 'checkbox' });
      const src = el('input', { type: 'checkbox', checked: true });
      const wg = el('input', { type: 'checkbox', checked: true });
      const audio = el('select', { style: { width: '100%' } });
      // Seth, 2026-10-17: concatenated (the default) or one clip per line — the user's choice
      audio.appendChild(el('option', { value: 'bundle' }, 'one audio file for the text: each example\u2019s audio in order, a click between examples'));
      audio.appendChild(el('option', { value: 'clips' }, 'one small audio file per line, each line pointing at its own clip'));
      audio.appendChild(el('option', { value: 'original' }, 'point at the original recordings (their offsets, as in FLEx)'));
      audio.appendChild(el('option', { value: 'none' }, 'no audio'));
      audio.value = 'bundle';
      const folder = el('input', { type: 'text', placeholder: 'next to the .flextext — or the project\u2019s LinkedFiles\\AudioVisual', style: { flex: '1 1 auto', minWidth: '0' } });
      const browse = el('button', { class: 'btn', onclick: async () => { try { const f = await FS.api.pick_folder(); if (f) folder.value = f; } catch (e) { FS.toast(e.message, 'error'); } } }, 'Browse…');
      const folderRow = el('div', { class: 'form-row' }, el('label', {}, 'Audio into'), el('div', { style: { display: 'flex', gap: '6px', flex: '1 1 auto', minWidth: '0' } }, folder, browse));
      const folderNote = el('p', { class: 'small muted' }, 'One audio file is named like its .flextext (the Audio Segmenter pairs them by name); clips per line go into a <name>-audio folder. Choose the project\u2019s LinkedFiles\\AudioVisual folder and the audio is written there with locations FLEx resolves on import; anywhere else the file points at it by full path. 16-bit mono WAV.');
      const showFolder = () => { const on = audio.value === 'clips' || audio.value === 'bundle'; folderRow.style.display = on ? '' : 'none'; folderNote.style.display = on ? '' : 'none'; };
      audio.addEventListener('change', showFolder);
      showFolder();
      // Seth, 2026-10-17: one text per baseline writing system, each in its own file by default
      const oneFile = el('input', { type: 'checkbox' });
      const only = el('select', { style: { width: '100%' } });
      only.appendChild(el('option', { value: '' }, preview.texts.length > 1 ? 'all — one FLEx text per baseline writing system' : 'all'));
      for (const t of preview.texts) only.appendChild(el('option', { value: t.ws }, t.ws + ' only (' + t.examples + ' example' + (t.examples === 1 ? '' : 's') + ')'));
      const what = texts.length + ' example' + (texts.length === 1 ? '' : 's')
        + (preview.texts.length > 1 ? ' → ' + preview.texts.length + ' texts: ' + preview.texts.map((t) => t.ws + ' (' + t.examples + ')').join(', ') : preview.texts.length === 1 ? ' → one text, baseline ' + preview.texts[0].ws : '')
        + (items.length > texts.length ? ' · ' + (items.length - texts.length) + ' entry object' + (items.length - texts.length === 1 ? '' : 's') + ' skipped (not interlinear)' : '');
      // Element.append writes a null child as the text "null" (FS.el skips it; append does not)
      m.body.append(...[
        el('p', { class: 'small muted' }, what),
        el('div', { class: 'form-row' }, el('label', {}, 'Text title'), title),
        preview.texts.length > 1 ? el('div', { class: 'form-row' }, el('label', {}, 'Baseline'), only) : null,
        preview.texts.length > 1 ? el('label', { class: 'row', style: { gap: '8px' } }, oneFile, 'Put the texts in one file (else one .flextext per writing system, each with its own audio)') : null,
        el('div', { class: 'form-row' }, el('label', {}, 'Audio'), audio),
        folderRow,
        folderNote,
        el('label', { class: 'row', style: { gap: '8px' } }, src, 'Add a Source note on every line (text title, FLEx number, GUIDs)'),
        el('label', { class: 'row', style: { gap: '8px' } }, link, 'Include a link back to this note (flexscratchpad://note/…)'),
        el('label', { class: 'row', style: { gap: '8px' } }, md, 'Attach this note\u2019s markdown as the text\u2019s comment (Info tab)'),
        el('label', { class: 'row', style: { gap: '8px' } }, wg, 'Keep FLEx\u2019s word analysis GUIDs (the import reuses the same analyses)'),
        el('p', { class: 'small muted' }, 'Each example becomes a paragraph of the new text; its segments keep every writing system. A FLEx text has one baseline writing system, so examples from texts in different vernacular writing systems become separate texts, each in its own file (or together in one, if you tick that). Import with FieldWorks → File → Import → FLExText Interlinear.'),
      ].filter(Boolean));
      const row = el('div', { class: 'btn-row' });
      row.appendChild(el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'));
      row.appendChild(el('button', { class: 'btn primary', onclick: async () => {
        const opts = { title: title.value.trim(), includeLink: link.checked, includeMarkdown: md.checked, sourceNotes: src.checked, wordGuids: wg.checked, onlyWs: only.value || '', audio: audio.value, audioFolder: folder.value.trim(), oneFile: oneFile.checked };
        try {
          const r = await FS.api.export_note_flextext(note.id, items, opts);
          if (r) FS.toast('Saved ' + (r.paths || [r.path]).join('; ') + ' — ' + r.examples + ' example' + (r.examples === 1 ? '' : 's') + (r.texts.length > 1 ? ' in ' + r.texts.length + ' texts' : '') + (r.skipped ? ', ' + r.skipped + ' skipped' : '') + (r.audio ? '; audio: ' + r.audioMatched + ' line' + (r.audioMatched === 1 ? '' : 's') + (opts.audio === 'bundle' ? ' in ' : ' clipped in ') + r.audio + (r.audioMissing ? ' (' + r.audioMissing + ' segment' + (r.audioMissing === 1 ? '' : 's') + ' without a playable clip)' : '') : ''), 'ok');
          m.close(); resolve(r);
        } catch (e) { FS.toast('Export failed: ' + e.message, 'error'); }
      } }, 'Export…'));
      m.body.appendChild(row);
      title.focus();
    });
  }

  /* ------------------------------------------------------------------ actions */
  async function exportNote(note, editor, format) {
    if (format === 'flextext') return exportFlextext(note, editor);
    if (format === 'md') { const p = await FS.api.export_note_markdown(note.id); if (p) FS.toast('Saved ' + p, 'ok'); return p; }
    const doc = await buildDoc(note, editor);
    if (format === 'html') { const p = await FS.api.export_note_html(note.id, toHtml(doc)); if (p) FS.toast('Saved ' + p, 'ok'); return p; }
    if (format === 'docx') { const p = await FS.api.export_note_docx(note.id, doc); if (p) FS.toast('Saved ' + p, 'ok'); return p; }
    if (format === 'pdf') {
      // the HTML rendering in a hidden frame, printed: the print dialog offers "Save as PDF"
      const frame = document.createElement('iframe');
      frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
      document.body.appendChild(frame);
      frame.srcdoc = toHtml(doc);
      await new Promise((res) => { frame.onload = res; setTimeout(res, 1500); });
      try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (e) { FS.toast('Print failed: ' + e.message, 'error'); }
      setTimeout(() => frame.remove(), 60000);
      return true;
    }
    return null;
  }

  FS.exporter = { buildDoc, toHtml, exportNote, runsOf, flextextItems, exportFlextext };
})();
