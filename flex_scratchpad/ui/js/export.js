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

  async function flexBlock(spec, extras) {
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
    if (kind === 'chart') return chartBlock(obj, spec, extras);
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
      const out = { n: seg.n, label: seg.label || String(seg.n), lines: lineModels, begin: seg.begin, end: seg.end, media: seg.media || null };
      if (lines.includes('ft') && seg.free) out.free = styledRuns(seg.free, R.stylesFor(index, seg.n, 'ft', 0), {});
      if (lines.includes('lit') && seg.lit) out.lit = styledRuns(seg.lit, R.stylesFor(index, seg.n, 'lit', 0), { color: '#68717d' });
      if (lines.includes('note') && (seg.notes || []).length) out.notes = seg.notes.map((n) => styledRuns(n, R.stylesFor(index, seg.n, 'note', 0), { i: true, color: '#68717d' }));
      return out;
    });
    return { type: 'interlinear', guid: obj.guid, text: obj.guid, title: obj.title, abbrev: obj.abbrev || '', url: obj.url || '', label: spec.label, segments: segs, media: obj.media || [], ws: vern, segmentCount: obj.segmentCount, range: obj.range };
  }

  /* A text chart (Seth, 2026-10-18) for the exports: {type: 'chart', title, name, label, headers:
   * [[{text, span}]], rows: [{label, clause, endSent, endPara, cells: [{span, runs}], free, notes}],
   * ws} — the same layout the page draws (chart.js helpers), each cell's content as runs. */
  /* A colour at `a` opacity over white, as a hex colour: what a tinted row looks like on paper. */
  function tint(hex, a) {
    const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return hex || '';
    const ch = (h) => Math.round(parseInt(h, 16) * a + 255 * (1 - a)).toString(16).padStart(2, '0');
    return '#' + ch(m[1]) + ch(m[2]) + ch(m[3]);
  }
  /* `extras` (a chart note's export, chartnote.js exportExtras): {cols: [{name, kind}], cell(i, row,
   * chart) → {text, hl?, b?, i?, u?, c?}, rowStyle(row, chart) → {hl?, b?, i?, u?, c?}}. */
  function chartBlock(obj, spec, extras) {
    const C = FS.chart;
    extras = extras || null;
    obj = C.flatten ? C.flatten(obj, spec) : obj;    // the one-column view exports as one column
    let cols = C.visibleColumns(spec, obj);
    // a column's own look (its `column:` rules): a hidden column is left out, a tinted / bold one tinted / bold
    const colLooks = new Map();
    if (!obj.flat && C.columnLook) { for (const c of cols) { const lk = C.columnLook(c, obj, spec); if (lk && lk.styled) colLooks.set(c.n, lk); else if (lk && lk.hide) colLooks.set(c.n, lk); } const shown = cols.filter((c) => !(colLooks.get(c.n) || {}).hide); if (shown.length) cols = shown; }
    const lines = R.chartLines(spec);
    const free = R.freeMode(spec);
    const headers = !(spec.extra && spec.extra.headers === 'off');
    const notesOn = !(spec.extra && spec.extra.notes === 'off') && (obj.rows || []).some((r) => (r.notes || '').trim());
    const index = R.resolveChartStyles(spec, obj);
    const vern = obj.ws && obj.ws.vern || {}, anal = obj.ws && obj.ws.anal || {};
    const wg = new Map();
    for (const r of obj.rows || []) for (const c of r.cells || []) if (c.kind === 'words') wg.set(c.guid, { row: r, cell: c });
    const runsOfStyles = (text, st, base) => styledRuns(text, st.map((s) => ({ style: s.style, color: s.color, chars: null })), base);
    const lineText = (w, line) => line === 'txt' ? (w.txt || '') : line === 'gls' ? (w.gls || '') : line === 'pos' ? (w.pos || '') : line === 'morph' ? (w.morphs || []).map((m) => m.form || '').join(' ') : line === 'mgls' ? (w.morphs || []).map((m) => m.gls || '').join(' ') : line === 'cf' ? (w.morphs || []).map((m) => m.cf || '').join(' ') : '';
    const LB = { txt: { color: '#00379c', font: vern.font || undefined }, morph: { color: '#4a4f57', font: vern.font || undefined }, cf: { color: '#68717d' }, gls: { color: '#2a6e2a', size: 9 }, mgls: { color: '#2a6e2a', size: 9 }, pos: { color: '#7a3e9d', size: 8 } };
    const partWords = (p, row, col) => {
      // one run group per word: its lines joined by a line break
      const words = [];
      let wi = 0;
      for (const w of p.words || []) {
        if (w.punct) { words.push([{ text: w.txt || '', color: '#00379c', font: vern.font || undefined }]); continue; }
        wi++;
        const runs = [];
        lines.forEach((line, li) => { const t = lineText(w, line); if (!t && line !== 'txt') return; if (li) runs.push({ text: '\n' }); runs.push(...runsOfStyles(t, R.chartStylesFor(index, row.n, col.n, wi, line), LB[line] || {})); });
        words.push(runs);
      }
      return words;
    };
    const runs = freeRunsOf(obj.rows || []);
    const rows = (obj.rows || []).map((row, ri) => {
      const cells = C.layoutRow(row, cols, obj.flat ? null : ((obj.template && obj.template.columns) || [])).map((slot) => {
        const cellSt = R.chartStylesFor(index, row.n, slot.col.n, 0, '');
        const words = [];
        const marks = [];
        for (const p of slot.parts) {
          if (p.kind === 'words') words.push(...partWords(p, row, slot.col));
          else if (p.kind === 'moved') { const t = wg.get(p.target); marks.push({ text: (p.preposed ? '\u2039\u2039' : '\u203a\u203a') + (t ? t.row.label : ''), color: '#7a3e9d', b: true }); }
          else if (p.kind === 'clause') marks.push({ text: '[' + ((p.labels || []).length > 1 ? p.labels[0] + '\u2013' + p.labels[p.labels.length - 1] : (p.labels || ['?'])[0]) + ']', color: '#1f4f8f', b: true });
          else if (p.kind === 'tag') { const look = C.markerLook(obj, p.tag || {}, spec); if (look.hide || (C.markerShown && !C.markerShown(look, spec, slot.parts.some((q) => q.kind === 'words' && (q.srcCol || slot.col).n === (p.srcCol || slot.col).n)))) continue; marks.push({ text: ' ' + ((p.tag && (p.tag.abbr || p.tag.name)) || '?') + ' ', hl: look.bg, color: look.fg, size: 8, b: true }); }
        }
        const hl = cellSt.find((s) => s.style === 'hl');
        // the plain content too (the Excel export's data sheet, searches over the file)
        const plainWords = slot.parts.filter((p) => p.kind === 'words').flatMap((p) => p.words || []);
        const plain = { txt: plainWords.map((w) => w.txt || '').join(' '), gls: plainWords.filter((w) => !w.punct).map((w) => w.gls || '').join(' '),
          marks: slot.parts.filter((p) => p.kind === 'tag' && p.tag).map((p) => p.tag.name), moved: slot.parts.filter((p) => p.kind === 'moved').map((p) => (p.preposed ? 'preposed ' : 'postposed ') + ((wg.get(p.target) || { row: {} }).row.label || '')), clauses: slot.parts.filter((p) => p.kind === 'clause').flatMap((p) => p.labels || []) };
        const cellSegs = [...new Set(slot.parts.filter((p) => p.kind === 'words' && p.seg).flatMap((p) => { const a = []; for (let n = p.seg; n <= (p.segTo || p.seg); n++) a.push(n); return a; }))];
        const cl = colLooks.get(slot.col.n) || {};
        const clBg = cl.styled ? (cl.tile ? (cl.tc || cl.bg) : cl.hl ? cl.bg : '') : '';
        return { span: slot.span, col: slot.col.n, segs: cellSegs, words, marks, plain, hl: hl ? (hl.color || '#fff2a8') : (clBg ? tint(clBg, cl.tile ? 0.35 : 0.5) : ''), b: cellSt.some((s) => s.style === 'b') || !!(cl.styled && cl.b), i: cellSt.some((s) => s.style === 'i') || !!(cl.styled && cl.i), u: cellSt.some((s) => s.style === 'u') || !!(cl.styled && cl.u), color: (cellSt.find((s) => s.style === 'color') || {}).color || (cl.styled && cl.c) || '' };
      });
      // the row's own look: a chart marker whose rule says "whole row", a rule column's row case
      const rowStyle = {};
      for (const c of row.cells || []) {
        if (c.kind !== 'tag' || !c.tag) continue;
        const look = C.markerLook(obj, c.tag, spec);
        if (look.hide || !look.row) continue;
        if (look.bg) rowStyle.bg = tint(look.bg, 0.45);
        if (look.c) rowStyle.color = look.c;
        if (look.b) rowStyle.b = true;
        if (look.i) rowStyle.i = true;
        if (look.u) rowStyle.u = true;
      }
      // a clause type's look (dependent / speech / song rows; Seth, 2026-10-20): the tint, the words' colour, B I U
      if (row.clause && row.clause !== 'normal' && C.pseudoLook) {
        const lk = C.pseudoLook('clause:' + row.clause, obj, spec);
        if (lk && lk.styled && !lk.hide) {
          const bgc = lk.tile ? (lk.tc || lk.bg) : lk.bg;
          if (bgc) rowStyle.bg = tint(bgc, lk.tile ? 0.35 : 0.45);
          if (lk.c) rowStyle.color = lk.c;
          if (lk.b) rowStyle.b = true;
          if (lk.i) rowStyle.i = true;
          if (lk.u) rowStyle.u = true;
        }
      }
      if (extras && extras.rowStyle) { const st = extras.rowStyle(row, obj) || {}; if (st.hl) rowStyle.bg = st.hl; if (st.c) rowStyle.color = st.c; if (st.b) rowStyle.b = true; if (st.i) rowStyle.i = true; if (st.u) rowStyle.u = true; }
      const xcells = extras ? extras.cols.map((_, i) => { const v = extras.cell(i, row, obj) || {}; return { text: v.text || '', hl: v.hl || '', color: v.c || '', b: !!v.b, i: !!v.i, u: !!v.u }; }) : [];
      const run = runs.find((x) => x.from === ri);
      const runEnd = runs.find((x) => x.to === ri);
      return { n: row.n, label: row.label, clause: row.clause, endSent: !!row.endSent, endPara: !!row.endPara, notesText: row.notes || '', cells, xcells, rowStyle: Object.keys(rowStyle).length ? rowStyle : null,
        segs: C.rowSegs(row),
        free: free === 'col' && run ? { text: C.freeText(obj, run.segs, true).join(' '), span: run.to - run.from + 1 } : null,
        freeRow: free === 'row' && runEnd ? { text: C.freeText(obj, runEnd.segs, true).join(' '), rows: runEnd.from === runEnd.to ? obj.rows[runEnd.from].label : obj.rows[runEnd.from].label + '\u2013' + obj.rows[runEnd.to].label } : null,
        notes: notesOn ? (row.notes || '') : null };
    });
    const segments = (obj.segments || []).map((sg) => ({ n: sg.n, label: sg.label || String(sg.n), free: sg.free || '', begin: sg.begin, end: sg.end, media: sg.media || null }));
    return { type: 'chart', guid: obj.guid, text: obj.text, title: obj.title, name: obj.name, template: (obj.template || {}).name || '', label: spec.label, headers: headers ? C.headerRows(cols).map((hr) => hr.map((h) => ({ text: h.text, span: h.span }))) : [],
      columns: cols.map((c) => ({ n: c.n, name: c.name, path: (c.path || []).concat([c.name]).join('/'), width: C.colWidths ? (C.colWidths(spec).get(String(c.n)) || 0) : 0 })), xcols: extras ? extras.cols.map((c, i) => ({ name: c.name, kind: c.kind, side: c.side === 'left' ? 'left' : 'right', width: C.colWidths ? (C.colWidths(spec).get('x' + i) || 0) : 0 })) : [],
      widths: C.colWidths ? Object.fromEntries(C.colWidths(spec)) : {},
      freeCol: free === 'col', notesCol: notesOn, cols: cols.length, rows, segments, media: obj.media || [], ws: vern, anal, rowCount: obj.rowCount, range: obj.range };
  }
  const freeRunsOf = (rows) => FS.chart.freeRuns(rows);

  /* ------------------------------------------------------------------ the recordings in a page
   * (Seth, 2026-10-18: "audio players and base64 embedded audio where audio files and
   * segmentation data are available and match"). Every interlinear example and chart whose
   * lines are timed gets ONE clip — its first timed line's begin to its last one's end, cut and
   * compressed by Python (Api.export_clips) — carried in the page as a data: URL, and a ▶ per
   * line that seeks inside it; the page's own script (PLAYER_JS) lights the playing line. */
  function timedBlocks(doc) {
    const out = [];
    const walk = (blocks) => {
      for (const b of blocks || []) {
        if ((b.type === 'interlinear' || b.type === 'chart') && (b.segments || []).some((sg) => sg.begin != null && sg.end != null && sg.end > sg.begin)) out.push(b);
        if (b.type === 'table') for (const row of b.rows || []) for (const c of row) if (c.blocks) walk(c.blocks);
      }
    };
    walk(doc.blocks);
    return out;
  }
  async function embedAudio(doc, job) {
    const blocks = timedBlocks(doc);
    if (!blocks.length) return { count: 0, bytes: 0, missing: 0 };
    const items = blocks.map((b, i) => {
      const timed = b.segments.filter((sg) => sg.begin != null && sg.end != null && sg.end > sg.begin);
      return { id: 'a' + (i + 1), text: b.text || b.guid, label: (b.title || '') + (b.label ? ' ' + b.label : ''), media: timed[0].media || (b.media && b.media[0] && b.media[0].guid) || null, begin: Math.min(...timed.map((sg) => sg.begin)), end: Math.max(...timed.map((sg) => sg.end)) };
    });
    if (job) job.step('Preparing the recordings…', 0, items.length);
    // the recordings stay in Python (Seth, 2026-10-20: "audio stays in python is a good idea"): each clip
    // comes back as a TOKEN, written into the page as `fs-clip:<token>`, and Api.export_note_html puts the
    // recording itself into the file — megabytes of base64 through the bridge froze the window
    const got = await FS.api.export_clips(items, job ? job.id : null);
    let bytes = 0, count = 0, missing = 0;
    blocks.forEach((b, i) => {
      const r = (got || []).find((x) => x.id === items[i].id);
      if (!r || r.error) { missing++; b.audioMissing = (r && r.error) || 'no recording'; return; }
      const segs = {};
      for (const sg of b.segments) if (sg.begin != null && sg.end != null && sg.end > sg.begin) segs[sg.n] = [sg.begin, sg.end];
      if (!r || (!r.token && !r.base64)) { missing++; b.audioMissing = 'no recording'; return; }
      b.audio = { id: items[i].id, src: r.token ? 'fs-clip:' + r.token : 'data:' + r.mime + ';base64,' + r.base64, begin: items[i].begin, end: items[i].end, segs, bytes: r.bytes };
      bytes += r.bytes; count++;
    });
    return { count, bytes, missing };
  }
  const audioTag = (b) => (b.audio ? '<audio data-a="' + esc(b.audio.id) + '" data-begin="' + b.audio.begin + '" data-segs=\'' + JSON.stringify(b.audio.segs).replace(/'/g, '&#39;') + '\' preload="none" src="' + b.audio.src + '"></audio>' : '');
  const playButton = (b, segs, title) => (b.audio && segs.some((n) => b.audio.segs[n]) ? '<button class="play" data-a="' + esc(b.audio.id) + '" data-segs="' + segs.filter((n) => b.audio.segs[n]).join(' ') + '" title="' + esc(title) + '">\u25b6</button>' : '');

  /* ------------------------------------------------------------------ slides
   * (Seth, 2026-10-18: "Slideshow HTML export (and PowerPoint?)"). The note is cut into slides:
   * a title slide; every heading starts a slide named by it; every example, chart, table and
   * picture gets a slide of its own (titled by the section it is in); running text fills slides
   * in order and spills onto a continuation slide when it grows long. The same deck model feeds
   * the HTML slideshow (toSlides) and the PowerPoint writer (Python, pptx_writer.py). */
  const OWN_SLIDE = new Set(['interlinear', 'chart', 'table', 'image', 'imageref', 'entry', 'wordform']);
  function slidesOf(doc) {
    const slides = [{ kind: 'title', title: doc.title || 'Untitled', subtitle: [doc.where, doc.project ? 'FLEx project ' + doc.project : '', doc.date].filter(Boolean).join(' · '), blocks: [] }];
    let section = '';
    let cur = null;
    const weight = (b) => (b.type === 'list' ? b.items.length * 1.2 : b.type === 'code' ? String(b.text || '').split('\n').length : Math.max(1, Math.ceil(plainOf(b.runs).length / 90)));
    const fresh = (title, kind) => { cur = { kind: kind || 'text', title, blocks: [], lines: 0 }; slides.push(cur); return cur; };
    for (const b of doc.blocks || []) {
      if (b.type === 'h') { section = plainOf(b.runs); fresh(section); continue; }
      if (OWN_SLIDE.has(b.type)) {
        const s = fresh(section, 'object');
        // a short lead-in line just before it ("A chart of the same text:") rides along
        const prev = slides[slides.length - 2];
        if (prev && prev.kind === 'text' && prev.blocks.length && prev.blocks[prev.blocks.length - 1].type === 'p' && plainOf(prev.blocks[prev.blocks.length - 1].runs).length < 120 && /[:：]\s*$/.test(plainOf(prev.blocks[prev.blocks.length - 1].runs))) {
          s.lead = prev.blocks.pop();
          if (!prev.blocks.length) slides.splice(slides.length - 2, 1);
        }
        s.blocks.push(b);
        continue;
      }
      if (b.type === 'hr') { cur = null; continue; }
      if (!cur || cur.kind !== 'text' || cur.lines + weight(b) > 14) fresh(section + (cur && cur.kind === 'text' && cur.title === section && section ? ' (cont.)' : ''));
      cur.blocks.push(b);
      cur.lines += weight(b);
    }
    return { title: doc.title || 'Untitled', where: doc.where || '', project: doc.project || '', date: doc.date || '', slides: slides.filter((s) => s.kind === 'title' || s.blocks.length) };
  }
  const plainOf = (runs) => (runs || []).map((r) => r.text || '').join('');

  const SLIDES_CSS = `
  html, body { height: 100%; }
  body { margin: 0; max-width: none; padding: 0; background: #1a1d21; overflow: hidden; }
  body.wide { margin: 0; }
  .deck { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; }
  .slide { width: 1280px; height: 720px; background: #fff; border-radius: 6px; box-shadow: 0 20px 60px rgba(0,0,0,0.5); display: none; flex-direction: column; padding: 40px 56px; box-sizing: border-box; transform-origin: center center; position: absolute; }
  .slide.on { display: flex; }
  .slide .stitle { font-size: 30px; font-weight: 700; color: #1a1d21; margin: 0 0 14px; flex: none; border-bottom: 2px solid #e8ebef; padding-bottom: 8px; }
  .slide .stitle small { color: #68717d; font-weight: 400; font-size: 18px; margin-left: 12px; }
  .slide .lead { color: #4a4f57; font-size: 20px; margin: 0 0 12px; flex: none; }
  .slide .sbody { flex: 1 1 auto; min-height: 0; overflow: hidden; position: relative; }
  .slide .sbody > .fit { transform-origin: top left; }
  .slide.title { justify-content: center; align-items: center; text-align: center; background: linear-gradient(135deg, #0b2a6f, #1f4f8f 60%, #2f6fb6); color: #fff; }
  .slide.title h1 { font-size: 48px; margin: 0 0 16px; color: #fff; } .slide.title .sub { font-size: 20px; color: #cfe0ff; }
  .slide.title .hint { position: absolute; bottom: 28px; left: 0; right: 0; font-size: 13px; color: #9fb8e6; }
  .slide .obj { border: 0; box-shadow: none; padding: 0; margin: 0; } .slide .seg { padding: 8px 4px; } .slide .txt { font-size: 24px; } .slide .gls, .slide .mgls { font-size: 17px; } .slide .morph { font-size: 18px; } .slide .pos { font-size: 14px; } .slide .ft { font-size: 19px; margin-top: 8px; } .slide .n { font-size: 14px; min-width: 30px; }
  .slide p, .slide li { font-size: 22px; line-height: 1.45; } .slide h4, .slide h5, .slide h6 { font-size: 22px; } .slide blockquote { font-size: 21px; } .slide pre { font-size: 15px; }
  .slide table.tchart { font-size: 15px; } .slide table.note { font-size: 19px; }
  .slide .obj .head .ttl { font-size: 18px; }
  .nav { position: fixed; left: 0; right: 0; bottom: 0; display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; color: #a8b0ba; font: 13px -apple-system, "Segoe UI", Roboto, sans-serif; z-index: 8; pointer-events: none; }
  .nav b { color: #fff; font-weight: 500; } .nav .keys { opacity: 0.7; }
  .nav button { pointer-events: auto; border: 1px solid #4a4f57; background: transparent; color: #c9ced6; border-radius: 6px; padding: 3px 9px; cursor: pointer; margin-left: 6px; }
  .nav button:hover { border-color: #fff; color: #fff; }
  .toc { position: fixed; top: 0; right: 0; bottom: 0; width: 320px; background: #fff; box-shadow: -8px 0 30px rgba(0,0,0,0.35); overflow: auto; padding: 16px; display: none; z-index: 10; font-size: 14px; }
  .toc.open { display: block; } .toc h3 { margin: 0 0 10px; font-size: 14px; color: #68717d; } .toc a { display: block; padding: 5px 6px; color: #1a1d21; text-decoration: none; border-radius: 6px; } .toc a:hover, .toc a.on { background: #eaf1ff; } .toc a i { color: #a8b0ba; font-style: normal; width: 28px; display: inline-block; }
  @media print {
    body { background: #fff; overflow: visible; } .deck { position: static; display: block; } .nav, .toc { display: none !important; }
    .slide { display: flex !important; position: relative; transform: none !important; box-shadow: none; border-radius: 0; break-after: page; margin: 0 auto; }
    .slide .sbody > .fit { transform: none !important; }
  }`;
  const SLIDES_JS = `
  (function () {
    var slides = [].slice.call(document.querySelectorAll('.slide')), i = 0, deck = document.querySelector('.deck'), counter = document.getElementById('ctr'), toc = document.getElementById('toc');
    function fit() {
      var s = slides[i]; if (!s) return;
      var k = Math.min(window.innerWidth / 1300, (window.innerHeight - 36) / 740, 1.6);
      slides.forEach(function (x) { x.style.transform = 'scale(' + k + ')'; });
      var body = s.querySelector('.sbody'), inner = body && body.firstElementChild;
      if (inner) { inner.style.transform = ''; var kk = Math.min(1, body.clientHeight / Math.max(1, inner.scrollHeight), body.clientWidth / Math.max(1, inner.scrollWidth)); if (kk < 1) inner.style.transform = 'scale(' + kk + ')'; }
    }
    function show(n, push) {
      n = Math.max(0, Math.min(slides.length - 1, n));
      if (slides[i]) slides[i].classList.remove('on');
      i = n; slides[i].classList.add('on');
      counter.textContent = (i + 1) + ' / ' + slides.length;
      [].forEach.call(toc.querySelectorAll('a'), function (a, j) { a.classList.toggle('on', j === i); });
      if (push !== false) { try { history.replaceState(null, '', '#' + (i + 1)); } catch (e) { /* file:// */ } }
      requestAnimationFrame(fit);
    }
    document.addEventListener('keydown', function (e) {
      if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown' || e.key === 'j' || e.key === 'n') { e.preventDefault(); show(i + 1); }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp' || e.key === 'k' || e.key === 'p' || e.key === 'Backspace') { e.preventDefault(); show(i - 1); }
      else if (e.key === 'Home') show(0); else if (e.key === 'End') show(slides.length - 1);
      else if (e.key === 'f' || e.key === 'F') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); }
      else if (e.key === 't' || e.key === 'T' || e.key === 'm') toc.classList.toggle('open');
      else if (e.key === 'Escape' && toc.classList.contains('open')) toc.classList.remove('open');
    });
    deck.addEventListener('click', function (e) {
      if (e.target.closest('button, a, audio, .toc, .nav')) return;
      var r = deck.getBoundingClientRect();
      show(i + ((e.clientX - r.left) / r.width < 0.3 ? -1 : 1));
    });
    toc.addEventListener('click', function (e) { var a = e.target.closest('a[data-n]'); if (!a) return; e.preventDefault(); show(+a.getAttribute('data-n')); toc.classList.remove('open'); });
    document.getElementById('btn-toc').addEventListener('click', function () { toc.classList.toggle('open'); });
    document.getElementById('btn-full').addEventListener('click', function () { document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); });
    document.getElementById('btn-print').addEventListener('click', function () { window.print(); });
    window.addEventListener('resize', fit);
    var start = parseInt((location.hash || '').replace('#', ''), 10);
    show(isNaN(start) ? 0 : start - 1, false);
  })();`;
  function toSlides(doc) {
    const deck = slidesOf(doc);
    const hasAudio = timedBlocks(doc).some((b) => b.audio);
    const slideHtml = (s, n) => {
      if (s.kind === 'title') return '<section class="slide title" data-n="' + n + '"><h1>' + esc(s.title) + '</h1><div class="sub">' + esc(s.subtitle || '') + '</div><div class="hint">→ next · ← back · T contents · F full screen · P print' + (hasAudio ? ' · ▶ plays a line' : '') + '</div></section>';
      const obj = s.kind === 'object' ? s.blocks[0] : null;
      const sub = obj ? (obj.type === 'interlinear' ? obj.title : obj.type === 'chart' ? (obj.name || 'Chart') + ' · ' + (obj.title || '') : obj.type === 'entry' ? obj.headword : '') : '';
      return '<section class="slide' + (obj && obj.type === 'chart' ? ' wide' : '') + '" data-n="' + n + '">'
        + (s.title || sub ? '<h2 class="stitle">' + esc(s.title || sub) + (s.title && sub && sub !== s.title ? '<small>' + esc(sub) + '</small>' : '') + '</h2>' : '')
        + (s.lead ? '<p class="lead">' + runsHtml(s.lead.runs) + '</p>' : '')
        + '<div class="sbody"><div class="fit">' + s.blocks.map(blockHtml).join('\n') + '</div></div></section>';
    };
    const tocHtml = deck.slides.map((s, n) => '<a href="#' + (n + 1) + '" data-n="' + n + '"><i>' + (n + 1) + '</i>' + esc(s.kind === 'title' ? s.title : (s.title || (s.blocks[0] && (s.blocks[0].title || s.blocks[0].headword)) || 'Slide ' + (n + 1))) + '</a>').join('');
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(deck.title) + ' — slides</title><style>' + CSS + SLIDES_CSS + '\n  @page { size: landscape; margin: 0; }</style></head><body class="wide">'
      + '<div class="deck">' + deck.slides.map(slideHtml).join('\n') + '</div>'
      + '<div class="nav"><span><b>' + esc(deck.title) + '</b></span><span><span class="keys" id="ctr"></span><button id="btn-toc" title="Contents (T)">☰</button><button id="btn-full" title="Full screen (F)">⛶</button><button id="btn-print" title="Print / save as PDF (P)">⎙</button></span></div>'
      + '<div class="toc" id="toc"><h3>Slides</h3>' + tocHtml + '</div>'
      + (hasAudio ? '<div id="np" hidden><button class="pp" title="Pause / play">❚❚</button><button class="st" title="Stop">■</button><span class="w"></span><div class="bar"><i></i></div><span class="t"></span></div><script>' + PLAYER_JS + '</script>' : '')
      + '<script>' + SLIDES_JS + '</script></body></html>';
  }

  /* ------------------------------------------------------------------ note → model */
  /* Give the window a moment: a long export never holds the page for more than a frame or two (Seth,
   * 2026-10-20: "the UI just hangs while it works and I'm not entirely sure it isn't frozen"). */
  let lastYield = 0;
  const breathe = async (force) => { const t = performance.now(); if (!force && t - lastYield < 25) return; await new Promise((r) => setTimeout(r, 0)); lastYield = performance.now(); };
  async function buildDoc(note, editor, job) {
    const blocks = [];
    const numCtx = { counters: [] };                        // outline numbering carried across blocks
    let exNum = 0;                                          // (1), (2)… for embeds flagged `ex`
    const all = editor.blocks || [];
    const objects = all.filter((b) => b.type === 'flex' || b.type === 'table' || ((b.type === 'p' || b.type === 'quote') && /\{\{\s*flex:/.test(b.src || ''))).length;
    let seen = 0;
    for (const b of all) {
      await breathe();
      if (job) { if (job.cancelled) throw new Error('cancelled'); if (b.type === 'flex' || b.type === 'table' || /\{\{\s*flex:/.test(b.src || '')) { seen++; job.step('Reading the examples from FLEx… ' + seen + ' of ' + objects, seen - 1, objects); } }
      if (b.type !== 'list' && b.type !== 'p') numCtx.counters = [];
      if (b.type === 'p' || b.type === 'quote') {
        // a quote's lines carry their `> ` in the note; the exports draw the block as a quotation
        const parts = await textWithEmbeds(b.type === 'quote' ? b.src.replace(/^>[ \t]?/gm, '') : b.src);
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
          else if (x.collapsed) blk = { type: 'p', runs: [await linkRun(spec)] };        // a chip in the note: a FLEx link in the export
          else try { blk = await flexBlock(spec, b.extras); } catch (e) { blk = { type: 'p', runs: [{ text: '[FLEx object unavailable: ' + (e.message || e) + ']', color: '#c0392b' }] }; }
          blocks.push(Object.assign(blk, layout));
        }
      } else if (b.type === 'table') {
        const t = FS.tables.parse(b.src);
        const rows = [];
        const spans = FS.tables.spanMap(t);
        for (const [ri, row] of t.rows.entries()) {
          const cells = [];
          for (const [ci, cell] of row.entries()) {
            const parts = await textWithEmbeds(cell, true);
            const out = (parts.length === 1 && !parts[0].type) ? { runs: parts[0].runs } : { runs: null, blocks: parts.map((p) => (p.type ? p : { type: 'p', runs: p.runs })) };
            const sp = spans.anchors[ri + '.' + ci];
            if (sp) { out.rowspan = sp.rows; out.colspan = sp.cols; }
            if (spans.covered.has(ri + '.' + ci)) out.covered = true;
            cells.push(out);
          }
          rows.push(cells);
        }
        blocks.push({ type: 'table', rows, aligns: t.aligns, header: true, style: { flags: [...t.style.flags], cols: t.style.cols, rows: t.style.rows, spans: t.style.spans }, indent: t.style.indent || 0 });
      } else if (b.type === 'image') {
        const m = /^!\[([^\]]*)\]\(([^)\s]+)/.exec(b.src.trim());
        if (m) blocks.push({ type: 'imageref', src: m[2], alt: m[1] });
      }
    }
    const where = [note.tab, note.folder].filter(Boolean).join(' \u203a ');
    const project = (FS.tagstyles && FS.tagstyles.context && FS.tagstyles.context().project) || '';
    return { title: note.title || 'Untitled', blocks, where, project, date: new Date().toISOString().slice(0, 10) };
  }

  /* A COLLAPSED example, chart or entry, and every inline chip (Seth, 2026-10-18: "When not
   * expanded, then just a text abbreviation or title and line range that is a hyperlink to that
   * text in FLEx"): one run, the text's abbreviation (its title when it has none) and the FLEx
   * line numbers — a chart's name and rows, an entry's headword — linked to the object in FLEx. */
  async function linkRun(spec) {
    let obj = null;
    try { obj = await FS.interlinear.flexGet(spec.kind === 'sense' ? 'entry' : spec.kind, spec.guid, spec.seg ? spec.seg[0] : null, spec.seg ? spec.seg[1] : null, false, spec.kind === 'text' ? spec.ws : null, spec.at || null); } catch (err) { obj = null; }
    const I = FS.interlinear;
    let text;
    if (spec.label) text = spec.label;
    else if (!obj) text = spec.kind + ' ' + spec.guid.slice(0, 8) + '…';
    else if (spec.kind === 'text') text = ((obj.abbrev || obj.title || 'text') + ' ' + I.chipRange(spec, obj)).trim();
    else if (spec.kind === 'chart') text = I.chipTitle(spec, obj) + ' ' + I.chipRange(spec, obj);
    else text = I.chipTitle(spec, obj);
    const r = { text, color: '#1f4f8f', u: false, title: obj && obj.title || '' };
    if (obj && obj.url) r.href = obj.url;
    return r;
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
  async function textWithEmbeds(text, inCell) {
    const parts = [];
    let pos = 0, runs = [];
    const flush = () => { if (runs.length) parts.push({ runs }); runs = []; };
    for (const e of R.findEmbeds(text)) {
      if (e.start > pos) runs.push(...runsOf(text.slice(pos, e.start)));
      pos = e.end;
      if (e.spec.kind === 'file') { runs.push(await fileRun(e.spec)); continue; }
      // an object in a line of text is a chip, and in a cell a chip unless `expanded`: the
      // export shows what the page shows — a FLEx link, or the object in full
      const expanded = inCell && e.spec.extra && e.spec.extra.expanded;
      if (!expanded) { runs.push(await linkRun(e.spec)); continue; }
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
  :root { color-scheme: light; }
  body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; color: #1a1d21; max-width: 900px; margin: 32px auto 80px; padding: 0 24px; background: #fff; }
  body.wide { max-width: none; margin-left: 32px; margin-right: 32px; }
  header.doc { border-bottom: 1px solid #e8ebef; margin-bottom: 20px; padding-bottom: 10px; }
  header.doc h1 { margin: 0 0 4px; font-size: 26px; } header.doc .meta { color: #68717d; font-size: 13px; } header.doc .meta span + span::before { content: " \\00b7 "; color: #c9ced6; }
  h1 { font-size: 26px; } h2 { font-size: 20px; margin-top: 28px; } h3 { font-size: 17px; margin-top: 22px; } h4, h5, h6 { font-size: 15px; margin-top: 18px; }
  blockquote { border-left: 3px solid #d9dde3; margin: 8px 0; padding-left: 12px; color: #68717d; font-style: italic; }
  pre { background: #f3f4f6; padding: 10px 12px; border-radius: 8px; font: 13px/1.5 Consolas, Menlo, monospace; overflow: auto; }
  code { background: #e9ebef; border-radius: 3px; padding: 0 3px; font-family: Consolas, Menlo, monospace; font-size: 0.92em; }
  mark { background: #fff2a8; } a { color: #1f4f8f; }
  table.note { border-collapse: collapse; margin: 8px 0 14px; } table.note th, table.note td { border: 1px solid #d9dde3; padding: 6px 10px; vertical-align: top; } table.note th { background: #f3f4f6; text-align: left; }
  table.note.striped tbody tr:nth-child(even) td { background: #f7f8fa; } table.note.borders-light th, table.note.borders-light td { border-color: #e8ebef; } table.note.borders-none th, table.note.borders-none td { border-color: transparent; }
  .obj { border: 1px solid #e8ebef; border-radius: 10px; padding: 10px 12px; margin: 8px 0 14px; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
  .obj .head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; } .obj .tscroll { overflow-x: auto; max-width: 100%; }
  .obj .ttl { font-weight: 700; color: #00379c; font-family: "Charis SIL", "Doulos SIL", serif; font-size: 15px; } .obj .lbl { color: #68717d; font-size: 13px; margin-left: 10px; }
  .exrow { display: flex; gap: 10px; align-items: flex-start; } .exrow .exn { flex: none; min-width: 30px; padding-top: 14px; color: #68717d; } .exrow .exbody { flex: 1 1 auto; min-width: 0; }
  .seg { display: flex; gap: 10px; padding: 5px 4px; border-top: 1px dotted #e8ebef; border-radius: 6px; } .seg:first-of-type { border-top: 0; } .n { color: #a8b0ba; font-size: 12px; min-width: 26px; text-align: right; flex: none; display: flex; align-items: center; justify-content: flex-end; gap: 4px; padding-top: 2px; }
  .il { display: flex; flex-wrap: wrap; gap: 0 14px; } .w { display: flex; flex-direction: column; } .l { white-space: nowrap; line-height: 1.35; }
  .txt { color: #00379c; font-family: "Charis SIL", "Doulos SIL", serif; font-size: 17px; } .morph { color: #4a4f57; font-family: "Charis SIL", serif; font-size: 14px; } .mgls, .gls { color: #2a6e2a; font-size: 13.5px; } .cf { color: #68717d; font-size: 12.5px; } .pos { color: #7a3e9d; font-size: 12px; }
  .ft { margin-top: 6px; } .ft b, .lit b, .note b { font-size: 11px; color: #a8b0ba; text-transform: uppercase; margin-right: 8px; font-weight: 400; } .lit { color: #68717d; font-size: 13.5px; } .note { color: #68717d; font-style: italic; font-size: 13px; }
  .hw { font-size: 20px; font-weight: 700; color: #00379c; font-family: "Charis SIL", serif; } .sense { display: flex; gap: 8px; padding: 3px 0; } .sense .sn { color: #a8b0ba; min-width: 20px; text-align: right; } .sense .pos { font-style: italic; } .sense .gl { color: #2a6e2a; font-weight: 600; } .ex { color: #68717d; margin-left: 6px; border-left: 2px solid #e8ebef; padding-left: 8px; font-size: 13.5px; } .ex .v { color: #00379c; font-family: "Charis SIL", serif; font-size: 14.5px; }
  ul.task { list-style: none; padding-left: 8px; } hr { border: 0; border-top: 1px solid #d9dde3; margin: 16px 0; } img { max-width: 100%; }
  [dir=rtl] .il { flex-direction: row-reverse; justify-content: flex-end; }
  table.tchart { border-collapse: collapse; font-size: 13px; margin-top: 6px; } table.tchart th, table.tchart td { border: 1px solid #e8ebef; padding: 3px 7px; vertical-align: top; text-align: left; }
  table.tchart thead th { background: #f3f4f6; color: #68717d; font-size: 11px; text-align: center; } table.tchart thead th.xh { background: #eef2fb; color: #1f4f8f; }
  table.tchart tbody th { color: #68717d; text-align: right; background: #f7f8fa; font-variant-numeric: tabular-nums; white-space: nowrap; }
  table.tchart tr.end-sent > th, table.tchart tr.end-sent > td { border-bottom: 2px solid #c9ced6; } table.tchart tr.end-para > th, table.tchart tr.end-para > td { border-bottom: 3px double #1a1d21; }
  table.tchart tr.dependent th { font-style: italic; } table.tchart .cw { display: inline-block; vertical-align: top; margin-right: 8px; line-height: 1.3; } table.tchart td.free, table.tchart tr.free-row td { font-style: italic; background: #f3f9f3; }
  table.tchart tr.free-row .rows { float: right; font-style: normal; font-size: 11px; color: #68717d; } table.tchart td.notes { color: #68717d; font-size: 12px; } table.tchart td.xcell { background: #fbfcff; }
  button.play { border: 1px solid #c9ced6; background: #fff; color: #1f4f8f; border-radius: 999px; width: 20px; height: 20px; font-size: 8px; line-height: 1; padding: 0; cursor: pointer; vertical-align: middle; margin-right: 4px; flex: none; }
  button.play:hover { border-color: #1f4f8f; } button.play.on { background: #1f4f8f; color: #fff; border-color: #1f4f8f; }
  .seg.playing { background: #eaf1ff; box-shadow: inset 3px 0 0 #1f4f8f; } table.tchart td.playing { background: #eaf1ff !important; box-shadow: inset 0 0 0 2px #1f4f8f; }
  #np { position: fixed; left: 50%; bottom: 14px; transform: translateX(-50%); display: flex; align-items: center; gap: 10px; background: #1a1d21; color: #fff; border-radius: 999px; padding: 8px 14px; font-size: 13px; box-shadow: 0 6px 20px rgba(0,0,0,0.25); z-index: 9; max-width: 90vw; }
  #np[hidden] { display: none; } #np button { border: 0; background: #fff; color: #1a1d21; border-radius: 999px; width: 26px; height: 26px; cursor: pointer; font-size: 11px; } #np .bar { width: 180px; height: 6px; background: #4a4f57; border-radius: 3px; position: relative; cursor: pointer; } #np .bar i { position: absolute; left: 0; top: 0; bottom: 0; width: 0; background: #8ab4ff; border-radius: 3px; } #np .t { font-variant-numeric: tabular-nums; color: #c9ced6; } #np .w { color: #fff; max-width: 40vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  footer.doc { color: #a8b0ba; font-size: 11px; margin-top: 40px; }
  @media print {
    body { margin: 0; max-width: none; font-size: 12.5px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .obj { break-inside: avoid; box-shadow: none; } .seg, table.tchart tr, table.note tr { break-inside: avoid; } thead { display: table-header-group; } h1, h2, h3 { break-after: avoid; }
    button.play, #np, audio { display: none !important; } a { color: inherit; text-decoration: none; }
    table.tchart { font-size: 10.5px; } table.tchart th, table.tchart td { padding: 2px 4px; }
  }`;
  /* the page's own player: ▶ plays a line (or the whole example / chart) from the clip, lights the
   * playing line (.seg, or every chart cell holding its words), a bar at the bottom pauses, stops
   * and seeks; a second click on the same ▶ stops; Esc stops. Plain script, no dependencies. */
  const PLAYER_JS = `
  (function () {
    var cur = null, np = document.getElementById('np'), bar = np.querySelector('.bar'), fill = bar.firstElementChild, tEl = np.querySelector('.t'), wEl = np.querySelector('.w'), pp = np.querySelector('.pp');
    function fmt(ms) { ms = Math.max(0, ms); var s = Math.floor(ms / 1000); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2) + '.' + Math.floor((ms % 1000) / 100); }
    function unlight(obj) { obj.querySelectorAll('.playing').forEach(function (x) { x.classList.remove('playing'); }); obj.removeAttribute('data-lit'); }
    function light(obj, n) { if (obj.getAttribute('data-lit') === String(n)) return; unlight(obj); if (n == null) return; obj.setAttribute('data-lit', n); obj.querySelectorAll('.seg[data-n="' + n + '"], td[data-segs~="' + n + '"]').forEach(function (x) { x.classList.add('playing'); }); var first = obj.querySelector('.playing'); if (first) { var r = first.getBoundingClientRect(); if (r.top < 0 || r.bottom > window.innerHeight) first.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } }
    function stop() { if (!cur) return; cur.a.pause(); cancelAnimationFrame(cur.raf); unlight(cur.obj); cur.btn.classList.remove('on'); cur = null; np.hidden = true; }
    function tick() { if (!cur) return; var c = cur, t = c.a.currentTime * 1000 + c.clip0, n = null; for (var k in c.segs) if (t >= c.segs[k][0] - 5 && t < c.segs[k][1]) n = k; light(c.obj, n); fill.style.width = (Math.min(1, Math.max(0, (t - c.t0) / (c.t1 - c.t0))) * 100) + '%'; tEl.textContent = fmt(t - c.t0) + ' / ' + fmt(c.t1 - c.t0); if (t >= c.t1 - 15 || c.a.ended) { stop(); return; } c.raf = requestAnimationFrame(tick); }
    document.addEventListener('click', function (e) {
      var b = e.target.closest('button.play'); if (!b) return;
      e.preventDefault();
      if (cur && cur.btn === b) { stop(); return; }
      stop();
      var obj = b.closest('.obj'), a = obj && obj.querySelector('audio[data-a="' + b.getAttribute('data-a') + '"]'); if (!a) return;
      var segs = JSON.parse(a.getAttribute('data-segs')), ns = b.getAttribute('data-segs').split(' ').filter(function (x) { return segs[x]; }); if (!ns.length) return;
      var t0 = Math.min.apply(null, ns.map(function (n) { return segs[n][0]; })), t1 = Math.max.apply(null, ns.map(function (n) { return segs[n][1]; })), clip0 = +a.getAttribute('data-begin') || 0;
      cur = { a: a, btn: b, obj: obj, segs: segs, t0: t0, t1: t1, clip0: clip0, raf: 0 };
      var ttl = obj.querySelector('.ttl'); wEl.textContent = (ttl ? ttl.textContent : '') + (ns.length === 1 ? ' \\u00b7 ' + (b.getAttribute('title') || '').replace(/^Play /, '') : '');
      a.currentTime = Math.max(0, (t0 - clip0) / 1000);
      var p = a.play();
      b.classList.add('on'); np.hidden = false; pp.textContent = '\\u275a\\u275a';
      (p && p.then ? p : Promise.resolve()).then(function () { cur && (cur.raf = requestAnimationFrame(tick)); }).catch(function (err) { stop(); alert('This browser could not play the recording: ' + (err && err.message || err)); });
    });
    pp.addEventListener('click', function () { if (!cur) return; if (cur.a.paused) { cur.a.play(); pp.textContent = '\\u275a\\u275a'; cur.raf = requestAnimationFrame(tick); } else { cur.a.pause(); cancelAnimationFrame(cur.raf); pp.textContent = '\\u25b6'; } });
    np.querySelector('.st').addEventListener('click', stop);
    bar.addEventListener('click', function (e) { if (!cur) return; var r = bar.getBoundingClientRect(); var f = (e.clientX - r.left) / r.width; cur.a.currentTime = (cur.t0 + f * (cur.t1 - cur.t0) - cur.clip0) / 1000; });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') stop(); });
  })();`;

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
    if (r.href) s = '<a href="' + esc(r.href) + '"' + (r.title ? ' title="' + esc(r.title) + '"' : '') + '>' + s + '</a>';
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
        return '<div class="obj"' + (rtl ? ' dir="rtl"' : '') + '><div class="head">' + playButton(b, b.segments.map((sg) => sg.n), 'Play the example') + '<span class="ttl">' + esc(b.title || '') + '</span>' + (b.label ? '<span class="lbl">' + esc(b.label) + '</span>' : '') + '</div>' + audioTag(b)
          + b.segments.map((seg) => {
            const ncols = Math.max(0, ...seg.lines.map((l) => l.cells.length));
            const words = [];
            for (let i = 0; i < ncols; i++) words.push('<div class="w">' + seg.lines.map((l) => '<div class="l ' + l.name + '">' + runsHtml(l.cells[i] || []) + '</div>').join('') + '</div>');
            return '<div class="seg" data-n="' + seg.n + '"><span class="n">' + playButton(b, [seg.n], 'Play line ' + (seg.label || seg.n)) + esc(seg.label || seg.n) + '</span><div><div class="il">' + words.join('') + '</div>'
              + (seg.free ? '<div class="ft"><b>Free</b>' + runsHtml(seg.free) + '</div>' : '') + (seg.lit ? '<div class="lit"><b>Lit</b>' + runsHtml(seg.lit) + '</div>' : '')
              + (seg.notes || []).map((n) => '<div class="note"><b>Note</b>' + runsHtml(n) + '</div>').join('') + '</div></div>';
          }).join('') + '</div>';
      }
      case 'chart': {
        const rtl = b.ws && b.ws.rtl;
        const xcols = b.xcols || [];
        const xL = xcols.map((x, i) => Object.assign({ i }, x)).filter((x) => x.side === 'left'), xR = xcols.map((x, i) => Object.assign({ i }, x)).filter((x) => x.side !== 'left');
        const extra = (b.freeCol ? 1 : 0) + (b.notesCol ? 1 : 0) + xcols.length;
        const st = (c) => (c.hl || c.b || c.i || c.u || c.color ? ' style="' + (c.hl ? 'background:' + c.hl + ';' : '') + (c.b ? 'font-weight:700;' : '') + (c.i ? 'font-style:italic;' : '') + (c.u ? 'text-decoration:underline;' : '') + (c.color ? 'color:' + c.color + ';' : '') + '"' : '');
        const rowSt = (r) => (r.rowStyle ? ' style="' + (r.rowStyle.bg ? 'background:' + r.rowStyle.bg + ';' : '') + (r.rowStyle.color ? 'color:' + r.rowStyle.color + ';' : '') + (r.rowStyle.b ? 'font-weight:700;' : '') + (r.rowStyle.i ? 'font-style:italic;' : '') + (r.rowStyle.u ? 'text-decoration:underline;' : '') + '"' : '');
        const audio = b.audio;          // {src, begin, segs: {n: [begin, end]}} when the export embeds the recording (embedAudio)
        const playBtn = (segs, title) => playButton(b, segs, title);
        const W = b.widths || {};
        const colTags = ['lab'].concat(xL.map((x) => 'x' + x.i), (b.columns || []).map((c) => String(c.n)), xR.map((x) => 'x' + x.i), b.freeCol ? ['free'] : [], b.notesCol ? ['notes'] : []).map((k) => '<col' + (W[k] ? ' style="width:' + W[k] + 'px"' : '') + '>').join('');
        let h = '<div class="obj chart" data-chart="' + esc(b.guid || '') + '"><div class="head"><span class="ttl">' + esc(b.name || 'Chart') + ' \u00b7 ' + esc(b.title || '') + '</span>' + (b.label ? '<span class="lbl">' + esc(b.label) + '</span>' : '') + '</div>' + audioTag(b) + '<div class="tscroll"><table class="tchart"' + (rtl ? ' dir="rtl"' : '') + (Object.keys(W).length ? ' style="width:max-content;min-width:100%"' : '') + '><colgroup>' + colTags + '</colgroup>';
        if (b.headers.length) {
          const xh = (x) => '<th class="xh" rowspan="' + b.headers.length + '">' + esc(x.name) + '</th>';
          h += '<thead>' + b.headers.map((hr, i) => '<tr>' + (i === 0 ? '<th rowspan="' + b.headers.length + '">' + playBtn(b.segments.map((sg) => sg.n), 'Play these rows') + '#</th>' + xL.map(xh).join('') : '') + hr.map((x) => '<th' + (x.span > 1 ? ' colspan="' + x.span + '"' : '') + '>' + esc(x.text) + '</th>').join('') + (i === 0 ? xR.map(xh).join('') : '') + (i === 0 && b.freeCol ? '<th rowspan="' + b.headers.length + '">Free</th>' : '') + (i === 0 && b.notesCol ? '<th rowspan="' + b.headers.length + '">Notes</th>' : '') + '</tr>').join('') + '</thead>';
        }
        const starts = FS.chart.lineStarts(b.rows.map((r) => ({ cells: (r.segs || []).map((n) => ({ kind: 'words', seg: n, segTo: n })) })), b.segments);
        h += '<tbody>' + b.rows.map((r, ri) => {
          const sgs = starts.get(ri) || [];
          const xtd = (x) => { const c = r.xcells[x.i] || { text: '' }; return '<td class="xcell"' + st(c) + '>' + esc(c.text).replace(/\n/g, '<br>') + '</td>'; };
          let tr = '<tr class="' + esc(r.clause || 'normal') + (r.endSent ? ' end-sent' : '') + (r.endPara ? ' end-para' : '') + '"' + rowSt(r) + '><th>' + sgs.map((sg) => playBtn([sg.n], 'Play line ' + sg.label)).join('') + esc(r.label) + '</th>' + xL.map(xtd).join('');
          tr += r.cells.map((c) => '<td' + (c.span > 1 ? ' colspan="' + c.span + '"' : '') + st(c) + (audio && (c.segs || []).length ? ' data-segs="' + c.segs.join(' ') + '"' : '') + '>'
            + c.words.map((w) => '<span class="cw">' + runsHtml(w).replace(/\n/g, '<br>') + '</span>').join(' ') + (c.marks.length ? ' ' + runsHtml(c.marks) : '') + '</td>').join('');
          tr += xR.map(xtd).join('');
          if (r.free) tr += '<td class="free"' + (r.free.span > 1 ? ' rowspan="' + r.free.span + '"' : '') + '>' + esc(r.free.text) + '</td>';
          if (r.notes != null) tr += '<td class="notes">' + esc(r.notes) + '</td>';
          tr += '</tr>';
          if (r.freeRow && r.freeRow.text) tr += '<tr class="free-row"><th></th><td colspan="' + (b.cols + extra) + '"><i>' + esc(r.freeRow.text) + '</i> <span class="rows">' + esc(r.freeRow.rows) + '</span></td></tr>';
          return tr;
        }).join('') + '</tbody></table></div></div>';
        return h;
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

  /* The page: a header (title, where the note lives, the date, the FLEx project), the blocks, the
   * player bar when a recording is embedded, a footer. A note with a chart is laid out wide and
   * printed landscape. */
  function toHtml(doc) {
    const hasChart = JSON.stringify(doc.blocks).includes('"type":"chart"');
    const hasAudio = timedBlocks(doc).some((b) => b.audio);
    const meta = [];
    if (doc.where) meta.push(esc(doc.where));
    if (doc.project) meta.push('FLEx project ' + esc(doc.project));
    meta.push(esc(doc.date || new Date().toISOString().slice(0, 10)));
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(doc.title) + '</title><style>' + CSS + (hasChart ? '\n  @page { size: landscape; margin: 12mm; }' : '\n  @page { margin: 18mm; }') + '</style></head><body' + (hasChart ? ' class="wide"' : '') + '>'
      + '<header class="doc"><h1>' + esc(doc.title) + '</h1><div class="meta">' + meta.map((m) => '<span>' + m + '</span>').join('') + '</div></header>\n'
      + doc.blocks.map(blockHtml).join('\n')
      + (hasAudio ? '\n<div id="np" hidden><button class="pp" title="Pause / play">\u275a\u275a</button><button class="st" title="Stop">\u25a0</button><span class="w"></span><div class="bar"><i></i></div><span class="t"></span></div><script>' + PLAYER_JS + '</script>' : '')
      + '\n<footer class="doc">Exported from FLEx Scratchpad' + (hasAudio ? ' \u2014 the recordings are embedded in this file' : '') + '</footer></body></html>';
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
      const folder = el('input', { type: 'text', placeholder: 'next to the .flextext — or a folder of your recordings, such as a lameta session', style: { flex: '1 1 auto', minWidth: '0' } });
      const browse = el('button', { class: 'btn', onclick: async () => { try { const f = await FS.api.pick_folder(); if (f) folder.value = f; } catch (e) { FS.toast(e.message, 'error'); } } }, 'Browse…');
      const folderRow = el('div', { class: 'form-row' }, el('label', {}, 'Audio into'), el('div', { style: { display: 'flex', gap: '6px', flex: '1 1 auto', minWidth: '0' } }, folder, browse));
      const folderNote = el('p', { class: 'small muted' }, 'One audio file is named like its .flextext (the Audio Segmenter pairs them by name); clips per line go into a <name>-audio folder; the .flextext points at them by full path. Keep large recordings out of the FLEx project\u2019s own LinkedFiles folder: FieldWorks\u2019 Send/Receive fails on files of more than a few megabytes there. 16-bit mono WAV.');
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
        // the work is a queued job with the sidebar's progress pill (the audio bundle can take a while)
        m.close();
        resolve(FS.jobs.run('Export \u201c' + (note.title || 'collection') + '\u201d to a FLEx text', async (job) => {
          job.step('Writing the FLEx text' + (opts.audio && opts.audio !== 'none' ? ' and its audio' : '') + '…');
          const r = await FS.api.export_note_flextext(note.id, items, opts);
          if (r) FS.toast('Saved ' + (r.paths || [r.path]).join('; ') + ' — ' + r.examples + ' example' + (r.examples === 1 ? '' : 's') + (r.texts.length > 1 ? ' in ' + r.texts.length + ' texts' : '') + (r.skipped ? ', ' + r.skipped + ' skipped' : '') + (r.audio ? '; audio: ' + r.audioMatched + ' line' + (r.audioMatched === 1 ? '' : 's') + (opts.audio === 'bundle' ? ' in ' : ' clipped in ') + r.audio + (r.audioMissing ? ' (' + r.audioMissing + ' segment' + (r.audioMissing === 1 ? '' : 's') + ' without a playable clip)' : '') : ''), 'ok');
          return job.done(r && (r.paths ? r.paths.join('; ') : r.path));
        }));
      } }, 'Export…'));
      m.body.appendChild(row);
      title.focus();
    });
  }

  /* ------------------------------------------------------------------ actions
   * AN EXPORT IS A QUEUED JOB (Seth, 2026-10-20: "queue that and have progress bars … similar to the FLEx
   * project connection and backup status"; "the UI shouldn't just do nothing … it should register a
   * click"): the questions come first while the user is there (the recordings? where to save?), then the
   * note as it is NOW is copied and the work runs in FS.jobs with a progress bar in the sidebar, the
   * window free to use; several exports wait their turn. */
  const KIND = { html: 'a web page', docx: 'Word', xlsx: 'Excel', pptx: 'PowerPoint', slides: 'a slideshow', pdf: 'PDF', md: 'Markdown' };
  const EXT = { html: '.html', docx: '.docx', xlsx: '.xlsx', pptx: '.pptx', slides: '.html', pdf: '.pdf', md: '.md' };
  // the note's blocks as they are at the click: an edit made while the export runs does not reach it
  const snapshot = (editor) => Object.assign({}, editor, { blocks: (editor.blocks || []).map((b) => Object.assign({}, b)) });
  // the objects that may carry recordings, without fetching them (the question is asked before the work)
  const mayHaveAudio = (editor) => (editor.blocks || []).filter((b) => b.type === 'flex' && /\{\{\s*flex:(text|chart)\b/.test(b.src || '') && !/\bcollapsed\b/.test(b.src || '')).length;
  async function chooseTarget(note, format) {
    try { return await FS.api.export_target(note.id, EXT[format], format === 'slides' ? ' slides' : ''); } catch (e) { return undefined; }   // no such method (an old mock): the writer asks
  }
  async function exportNote(note, editor, format) {
    if (format === 'flextext') return exportFlextext(note, editor);
    if (format === 'md') { const p = await FS.api.export_note_markdown(note.id); if (p) FS.toast('Saved ' + p, 'ok'); return p; }
    const snap = snapshot(editor);
    let embed = false;
    if ((format === 'html' || format === 'slides') && !(FS.isMock && FS.isMock())) {
      const n = mayHaveAudio(snap);
      if (n) { embed = await askEmbedAudio(n, format === 'slides' ? 'Slideshow export' : null); if (embed === null) return null; }
    }
    let direct = format !== 'pdf';
    if (format === 'pdf') { try { direct = !!(await FS.api.export_pdf_direct()); } catch (e) { direct = false; } }
    let target = null;
    if (direct && !(FS.isMock && FS.isMock())) { target = await chooseTarget(note, format); if (target === null) return null; if (target === undefined) target = null; }
    const title = note.title || 'note';
    return FS.jobs.run('Export \u201c' + title + '\u201d to ' + KIND[format], (job) => runExport(job, note, snap, format, embed, target));
  }
  async function runExport(job, note, editor, format, embed, target) {
    const stop = () => { if (job.cancelled) throw new Error('cancelled'); };   // Stop in the jobs list: between steps
    const doc = await buildDoc(note, editor, job);
    stop();
    job.step('Laying out the ' + (format === 'xlsx' ? 'workbook' : format === 'pptx' || format === 'slides' ? 'slides' : 'document') + '…');
    await breathe(true);
    if (format === 'html' || format === 'slides') {
      let stats = null;
      if (embed) { try { stats = await embedAudio(doc, job); } catch (e) { FS.toast('The recordings could not be embedded: ' + e.message, 'warn'); } }
      stop();
      job.step('Writing the page…');
      await breathe(true);
      const p = await FS.api.export_note_html(note.id, format === 'slides' ? toSlides(doc) : toHtml(doc), target, format === 'slides' ? ' slides' : '', job.id);
      if (p) FS.toast('Saved ' + p + (stats && stats.count ? ' \u2014 ' + stats.count + ' recording' + (stats.count > 1 ? 's' : '') + ' embedded (' + (FS.files ? FS.files.fmtSize(stats.bytes) : stats.bytes + ' B') + ')' + (stats.missing ? ', ' + stats.missing + ' not available' : '') : ''), 'ok');
      return job.done(p);
    }
    stop();
    if (format === 'docx') { const p = await FS.api.export_note_docx(note.id, doc, target, job.id); if (p) FS.toast('Saved ' + p, 'ok'); return job.done(p); }
    if (format === 'xlsx') { const p = await FS.api.export_note_xlsx(note.id, doc, target, job.id); if (p) FS.toast('Saved ' + p, 'ok'); return job.done(p); }
    if (format === 'pptx') { const p = await FS.api.export_note_pptx(note.id, slidesOf(doc), target, job.id); if (p) FS.toast('Saved ' + p, 'ok'); return job.done(p); }
    if (format === 'pdf') {
      const html = toHtml(doc);
      // Windows: WebView2 writes the PDF itself (Api.export_note_pdf → pdf_print.py), landscape
      // when the note holds a chart; anywhere else, or when that fails, the browser's print
      // dialog offers "Save as PDF" on the same page
      let r = { fallback: true };
      if (target) { try { r = (await FS.api.export_note_pdf(note.id, html, target, html.includes('@page { size: landscape'), job.id)) || r; } catch (e) { r = { fallback: true, failed: true, error: e.message }; } }
      if (r.cancelled) return job.done(null);
      if (r.path && !r.fallback) { FS.toast('Saved ' + r.path, 'ok'); return job.done(r.path); }
      job.step('Opening the print dialog…');
      if (r.failed) FS.toast('The PDF could not be written directly' + (r.error ? ' (' + r.error + ')' : '') + ' — choose “Save as PDF” in the print dialog.', 'warn');
      // the HTML rendering in a hidden frame, printed: the print dialog offers "Save as PDF"
      const frame = document.createElement('iframe');
      frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
      document.body.appendChild(frame);
      frame.srcdoc = html;
      await new Promise((res) => { frame.onload = res; setTimeout(res, 1500); });
      try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (e) { FS.toast('Print failed: ' + e.message, 'error'); }
      setTimeout(() => frame.remove(), 60000);
      return job.done(true);
    }
    return job.done(null);
  }

  /* "Embed the recordings?" — a page with N players is bigger (about 300 KB a minute compressed,
   * much more without ffmpeg); the user decides. Resolves true / false, null when closed. */
  function askEmbedAudio(n, title) {
    return new Promise((resolve) => {
      let answered = false;
      const m = FS.modal({ title: title || 'Web page export', class: 'narrow', onClose: () => { if (!answered) resolve(null); } });
      const cb = el('input', { type: 'checkbox', checked: true, 'data-test': 'embed-audio' });
      m.body.appendChild(el('label', { class: 'row', style: { gap: '8px' } }, cb, el('span', {}, 'Embed the recordings as players (' + n + ' example' + (n > 1 ? 's' : '') + ' that may have audio)')));
      m.body.appendChild(el('p', { class: 'small muted' }, 'Each example gets one clip, compressed with ffmpeg when it is available (about 300 KB a minute), written INTO the page as base64 so the file plays anywhere on its own. A ▶ per line plays that line and lights it while it plays.'));
      m.body.appendChild(el('div', { class: 'btn-row' },
        el('button', { class: 'btn', onclick: () => { answered = true; m.close(); resolve(null); } }, 'Cancel'),
        el('button', { class: 'btn primary', 'data-test': 'export-html-go', onclick: () => { answered = true; const v = cb.checked; m.close(); resolve(v); } }, 'Export')));
    });
  }

  FS.exporter = { buildDoc, toHtml, toSlides, slidesOf, exportNote, runsOf, flextextItems, exportFlextext, embedAudio, timedBlocks, askEmbedAudio, linkRun };
})();
