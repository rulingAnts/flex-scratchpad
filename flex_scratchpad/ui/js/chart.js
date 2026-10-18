/* chart.js — FieldWorks TEXT CHARTS (constituent charts) drawn in a note (Seth, 2026-10-18:
 * "a Text Chart, part of a text chart (including the headers), a range of rows from a text chart").
 *
 * The object comes from Api.flex_get('chart', guid, rowFrom, rowTo, …, at) — see flex/model.py
 * for its shape: template columns (with their group paths), rows (label, clause type, sentence /
 * paragraph ends, notes, cells), the text's segments the rows touch (for the free translations).
 * Drawn as ONE table: the header rows built from the columns' paths (a group spans its columns;
 * ALWAYS included on a range of rows — Seth: "the column headings should be included"), FLEx's
 * row label in front, one cell per visible column — a word group's words with the lines chosen
 * (`lines=`, Words + Word gloss by default), a moved-text marker as ‹‹ / ›› pointing at its
 * word group, a clause marker as [2a], a chart tag as a chip — merged cells spanning as FLEx
 * merges them, the free translations spliced in as the user chooses (`free=`: a Free column
 * spanning the rows of one segment, a translation row after the last chart row of a segment
 * naming the rows it covers, a tip under the chart for the clicked cell, or hidden), the row
 * notes in a last column. Styles: `hl= b= u= i= s= color=` with chart targets (a row, a
 * column, a cell, a word; flexref.resolveChartStyles) from the popover a click on a word, a
 * cell, a row label or a column header opens.
 *
 * FS.chart.renderChart(obj, spec, opts) is called by interlinear.render (which fetches, shows
 * "Loading…", handles errors and ↻ for every kind); the pure helpers (headerRows, layoutRow,
 * freeRuns, visibleColumns) are node-tested in tests/js/chart.test.js. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const el = FS.el;
  const R = FS.flexref;
  const LINE_NAMES = { txt: 'Words', gls: 'Word gloss', morph: 'Morphemes', mgls: 'Morph gloss', pos: 'Category', cf: 'Lex. entries' };
  const FREE_NAMES = { row: 'a row after each segment’s rows', col: 'a Free column', tip: 'a tip for the clicked cell', off: 'hidden' };
  const HL_COLORS = ['', '#ffd6a5', '#caffbf', '#9bf6ff', '#bdb2ff', '#ffadad', '#fdffb6'];
  const TXT_COLORS = ['#c0392b', '#1f7a4d', '#1f4f8f', '#7a3e9d', '#b45309'];
  const PALETTE = ['#ffd6a5', '#caffbf', '#9bf6ff', '#bdb2ff', '#ffadad', '#fdffb6', '#a0c4ff', '#ffc6ff', '#b9fbc0', '#f1c0e8'];

  /* ------------------------------------------------------------------ pure helpers */
  /* The columns an embed shows: all, or those `cols=` names — a column's name, Group/Name, its
   * abbreviation, a group (all of its columns), its GUID, or c3 / c3-c5 by position. */
  function visibleColumns(spec, chart) {
    const cols = (chart.template && chart.template.columns) || [];
    const sel = spec.extra && spec.extra.cols;
    if (!sel) return cols;
    const want = new Set();
    for (const item of String(sel).split(',')) {
      const s = item.trim();
      if (!s) continue;
      const m = /^c(\d+)(?:-c?(\d+))?$/i.exec(s);
      if (m) { for (let n = +m[1]; n <= (+m[2] || +m[1]); n++) want.add(n); continue; }
      const key = s.replace(/_/g, ' ').toLowerCase();
      for (const c of cols) {
        const path = (c.path || []).concat([c.name]).join('/').toLowerCase();
        if (c.guid === key || c.name.toLowerCase() === key || (c.abbr || '').toLowerCase() === key || path === key || path.endsWith('/' + key) || (c.path || []).some((p) => p.toLowerCase() === key)) want.add(c.n);
      }
    }
    const out = cols.filter((c) => want.has(c.n));
    return out.length ? out : cols;
  }
  /* Header rows from the columns' paths: one row per depth, a group spanning its consecutive
   * columns, then the columns themselves. [{text, span, key?, col?}] per row. */
  function headerRows(cols) {
    const depth = Math.max(0, ...cols.map((c) => (c.path || []).length));
    const rows = [];
    for (let d = 0; d < depth; d++) {
      const row = [];
      for (const c of cols) {
        const name = (c.path || [])[d] || '';
        const key = (c.path || []).slice(0, d + 1).join('/');
        const last = row[row.length - 1];
        if (last && name && last.key === key) last.span++;
        else row.push({ text: name, span: 1, key });
      }
      rows.push(row);
    }
    rows.push(cols.map((c) => ({ text: c.name, abbr: c.abbr, span: 1, col: c })));
    return rows;
  }
  /* One row's cells laid over the visible columns: [{col, span, parts}] — a cell that merges
   * after takes the empty columns to its right, one that merges before the empty ones to its
   * left (what FLEx's MergesAfter / MergesBefore mean). */
  function layoutRow(row, cols) {
    const byCol = new Map();
    for (const c of row.cells || []) { if (!byCol.has(c.colN)) byCol.set(c.colN, []); byCol.get(c.colN).push(c); }
    const out = [];
    let i = 0;
    while (i < cols.length) {
      const col = cols[i];
      const parts = byCol.get(col.n) || [];
      let span = 1;
      // FLEx merges a cell with its ONE neighbour (MergesAfter / MergesBefore), when that is empty
      if (parts.some((p) => p.mergeAfter) && i + 1 < cols.length && !(byCol.get(cols[i + 1].n) || []).length) span++;
      if (parts.some((p) => p.mergeBefore) && out.length && !out[out.length - 1].parts.length) { out.pop(); span++; }
      out.push({ col, span, parts });
      i += span;
    }
    return out;
  }
  /* The text segments a row's word groups come from, ascending. */
  function rowSegs(row) {
    const s = new Set();
    for (const c of row.cells || []) if (c.kind === 'words' && c.seg) for (let n = c.seg; n <= (c.segTo || c.seg); n++) s.add(n);
    return [...s].sort((a, b) => a - b);
  }
  /* Where the free translations go: a segment's translation is shown ONCE, after the LAST row
   * that holds any of its words (Seth's Siakai chart, 2026-10-18: row 1 holds the end of 1.1 and
   * the start of 2.1, rows 2a–2b the rest of 2.1 — grouping rows by their segment set printed
   * 2.1 twice). Runs never overlap (a Free column spans each run's rows): a run ends at a row
   * where some segment ends and starts after the previous run; rows left over at the end join
   * the last run. [{from, to, segs}] by row index. */
  function freeRuns(rows) {
    const lastRow = new Map();
    rows.forEach((r, i) => { for (const n of rowSegs(r)) lastRow.set(n, i); });
    const endsAt = new Map();
    for (const [n, i] of lastRow) { if (!endsAt.has(i)) endsAt.set(i, []); endsAt.get(i).push(n); }
    const runs = [];
    let from = 0;
    rows.forEach((r, i) => {
      if (!endsAt.has(i)) return;
      runs.push({ from, to: i, segs: endsAt.get(i).sort((a, b) => a - b) });
      from = i + 1;
    });
    if (runs.length && from < rows.length) runs[runs.length - 1].to = rows.length - 1;
    return runs;
  }
  /* Where a timed line STARTS in the chart (Seth, 2026-10-18: "play controls on the first row
   * that starts an interlinear line"): row index → the timed segments whose first words are in
   * that row, in the chart's order. */
  function lineStarts(rows, segments) {
    const timed = new Map((segments || []).filter((s) => s.begin != null && s.end != null).map((s) => [s.n, s]));
    const out = new Map();
    const seen = new Set();
    rows.forEach((r, i) => {
      for (const n of rowSegs(r)) {
        if (seen.has(n)) continue;
        seen.add(n);
        if (!timed.has(n)) continue;
        if (!out.has(i)) out.set(i, []);
        out.get(i).push(timed.get(n));
      }
    });
    return out;
  }
  const segsByN = (chart) => new Map((chart.segments || []).map((s) => [s.n, s]));
  /* ‘The dog slept.’ (1.1) · ‘Yesterday…’ (1.2) — the free translations of some segments. */
  function freeText(chart, segs, withLabels) {
    const by = segsByN(chart);
    const parts = segs.map((n) => by.get(n)).filter(Boolean).filter((s) => (s.free || '').trim());
    return parts.map((s) => '‘' + s.free.trim() + '’' + (withLabels && parts.length > 1 ? ' (' + (s.label || s.n) + ')' : ''));
  }
  const rowsLabel = (rows, a, b) => (a === b ? rows[a].label : rows[a].label + '–' + rows[b].label);
  function markerLook(chart, tag, spec) {
    if (FS.tagstyles && FS.tagstyles.resolve) {
      try { return FS.tagstyles.resolve(Object.assign({}, tag, { marker: true }), spec || null, Object.assign({}, FS.tagstyles.context(), { text: chart.text || '' })); } catch (e) { /* the palette below */ }
    }
    if (tag && tag.back) return { bg: tag.back, fg: tag.fore || (FS.readableTextColor ? FS.readableTextColor(tag.back) : '#111') };
    const i = Math.max(0, (chart.markers || []).findIndex((m) => m.guid === (tag && tag.guid)));
    return { bg: PALETTE[i % PALETTE.length], fg: '#1a1d21' };
  }

  /* ------------------------------------------------------------------ styled text */
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const rgba = (hex, a) => { const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ''); return m ? 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')' : hex; };
  function styledHtml(text, styles) {
    if (!styles || !styles.length) return esc(text);
    let cls = '', st = '';
    for (const s of styles) {
      if (s.style === 'hl') { cls += ' st-hl'; if (s.color) st += 'background:' + s.color + ';'; }
      else if (s.style === 'color') { if (s.color) st += 'color:' + s.color + ';'; }
      else cls += ' st-' + s.style;
    }
    return '<span class="' + cls.trim() + '"' + (st ? ' style="' + st + '"' : '') + '>' + esc(text) + '</span>';
  }
  const wsAttrs = (ws) => { const a = {}; if (ws && ws.tag) a.lang = ws.tag; if (ws && ws.rtl) a.dir = 'rtl'; if (ws && ws.font) a.style = { fontFamily: '"' + ws.font.replace(/"/g, '') + '", var(--font-vern)' }; return a; };
  const lineText = (w, line) => line === 'txt' ? (w.txt || '') : line === 'gls' ? (w.gls || '') : line === 'pos' ? (w.pos || '') : line === 'morph' ? (w.morphs || []).map((m) => m.form || '').join(' ') : line === 'mgls' ? (w.morphs || []).map((m) => m.gls || '').join(' ') : line === 'cf' ? (w.morphs || []).map((m) => m.cf || '').join(' ') : '';

  /* ------------------------------------------------------------------ the table */
  function renderChart(obj, spec, opts) {
    opts = opts || {};
    const cols = visibleColumns(spec, obj);
    const lines = R.chartLines(spec);
    const free = R.freeMode(spec);
    const headers = !(spec.extra && spec.extra.headers === 'off');
    const notesOn = !(spec.extra && spec.extra.notes === 'off') && (obj.rows || []).some((r) => (r.notes || '').trim());
    const index = R.resolveChartStyles(spec, obj);
    const vern = (obj.ws && obj.ws.vern) || {}, anal = (obj.ws && obj.ws.anal) || {};
    const rows = obj.rows || [];
    const showTextTags = !!(spec.lines && spec.lines.includes('tag')) && (obj.tags || []).length > 0;   // the text's markup tags inside the cells (Seth, 2026-10-18)
    const box = el('div', { class: 'flex-obj chart-obj' + (obj.cached ? ' cached' : ''), dataset: { chart: obj.guid } });
    const range = obj.range || [rows[0] && rows[0].n, rows.length && rows[rows.length - 1].n];
    const rangeText = rows.length ? (range[0] === range[1] ? 'row ' + rows[0].label : 'rows ' + rows[0].label + '–' + rows[rows.length - 1].label) + ' of ' + (obj.rowCount || rows.length) : 'no rows';
    const change = () => opts.onSpecChange && opts.onSpecChange(spec);

    const head = el('div', { class: 'flex-head' + (opts.inCell ? ' compact' : '') },
      opts.editable && !opts.overlay && !opts.context && !opts.collection ? el('span', { class: 'drag-handle', draggable: 'true', title: 'Drag to move this object (Ctrl: copy)' }, '⠿') : null,
      el('span', { class: 'ttl' }, (obj.name || 'Chart') + ' · '),
      el('span', Object.assign({ class: 'ttl vern' }, wsAttrs(vern)), obj.title || '(untitled text)'),
      el('span', { class: 'badge', 'data-test': 'chart-range' }, rangeText),
      obj.cached ? el('span', { class: 'badge warn', title: obj.liveError || 'Shown from the notebook cache' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')) : null,
      obj.anchorsLost ? el('span', { class: 'badge warn', title: 'Some of these rows are no longer in the chart as they were' }, 'rows changed in FLEx') : null,
      spec.label ? el('span', { class: 'badge' }, spec.label) : null,
      el('span', { class: 'spacer' }));
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
    const markersHere = FS.tagstyles && FS.tagstyles.markersIn ? FS.tagstyles.markersIn(obj) : [];
    if (opts.editable && markersHere.length) head.appendChild(el('button', { class: 'lnk tag-btn', 'data-test': 'marker-btn', title: 'Chart markers in this chart: show, hide, style (a marker can style its whole row)', onclick: (e) => FS.tagstyles.examplePopover(e.currentTarget, spec, obj, Object.assign({}, opts, { markers: true })) }, '⚑ ' + markersHere.length));
    if (opts.editable && !opts.overlay) head.appendChild(el('button', { class: 'lnk', 'data-test': 'collapse-obj', title: 'Collapse to a chip', onclick: () => FS.interlinear.setCollapsed(spec, opts, true) }, '⤡'));
    if (opts.editable && opts.inCell && opts.editCell && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Edit the cell’s text', onclick: () => opts.editCell() }, '✎'));
    if (opts.editable && !opts.overlay && opts.duplicate) head.appendChild(el('button', { class: 'lnk', title: 'Duplicate this object', onclick: () => opts.duplicate() }, '⧉'));
    if (opts.editable && !opts.overlay && opts.remove) head.appendChild(el('button', { class: 'lnk danger', title: 'Remove this object…', onclick: async (e) => { if (await FS.confirmAt(e.currentTarget, 'Remove this chart from the note? (Undo brings it back.)', 'Remove')) { FS.interlinear.closeOverlay(); opts.remove(); } } }, '🗑'));
    if (!opts.context && spec.seg) head.appendChild(el('button', { class: 'lnk', title: 'See the whole chart', onclick: () => wholeChart(spec, obj) }, '⊡ Whole chart'));
    if (!opts.inCell) head.appendChild(el('button', { class: 'lnk', title: 'Copy as a tab-separated grid (headers, rows, notes)', onclick: () => { FS.copyText(chartTsv(spec, obj)); FS.toast('Copied as TSV'); } }, '⎘ TSV'));
    if (obj.url) head.appendChild(el('a', { href: obj.url, title: 'Open the text in FieldWorks (its Text Chart tab)', onclick: (e) => { e.preventDefault(); FS.interlinear.openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    if (opts.editable) head.appendChild(el('button', { class: 'lnk', 'data-test': 'chart-menu', title: 'Options', onclick: (e) => chartMenu(e.currentTarget, spec, opts, obj) }, '⋯'));
    box.appendChild(head);

    if (opts.onObject) { try { opts.onObject(obj); } catch (e) { /* the owner's problem */ } }
    const xcols = opts.extraCols || [];               // a chart note's custom columns (chartnote.js)
    // audio: ▶ on the first row of each timed line, ▶ all in the corner; the clip machinery is
    // the examples' (interlinear.playRange keyed on the TEXT's guid), the lit cells carry data-segs
    const starts = lineStarts(rows, obj.segments);
    const timedAll = (obj.segments || []).filter((s) => s.begin != null && s.end != null);
    const mediaByGuid = new Map((obj.media || []).map((m) => [m.guid, m]));
    const textObj = Object.assign({}, obj, { guid: obj.text || obj.guid, title: obj.title });
    const play = (segs, btn) => FS.interlinear.playRange && FS.interlinear.playRange(box, textObj, segs, mediaByGuid, opts, btn);
    const playBtn = (segs, title, cls) => el('button', { class: 'seg-play ' + (cls || ''), 'data-test': cls || 'chart-play', title, onclick: (e) => { e.stopPropagation(); play(segs, e.currentTarget); } }, '▶');
    const table = el('table', { class: 'tchart' + (vern.rtl ? ' rtl' : '') });
    const extraCols = (free === 'col' ? 1 : 0) + (notesOn ? 1 : 0) + xcols.length;
    if (headers) {
      const thead = el('thead');
      const hrows = headerRows(cols);
      hrows.forEach((hr, hi) => {
        const tr = el('tr', { class: hi === hrows.length - 1 ? 'th-cols' : 'th-groups' });
        if (hi === 0) tr.appendChild(el('th', { class: 'th-lab', rowspan: hrows.length }, timedAll.length && starts.size ? playBtn(timedAll, 'Play the lines of these rows', 'chart-play-all') : null, '#'));
        for (const h of hr) {
          const th = el('th', { colspan: h.span > 1 ? h.span : null, class: h.col ? 'th-col' : 'th-group', title: h.col ? ((h.col.path || []).concat([h.col.name]).join(' › ') + (h.col.abbr && h.col.abbr !== h.col.name ? ' (' + h.col.abbr + ')' : '')) : h.text, dataset: h.col ? { col: h.col.n } : null }, h.text);
          if (h.col && opts.editable) th.addEventListener('click', (e) => stylePopover(e.currentTarget, spec, { col: h.col.n }, opts, 'column ' + h.col.name));
          tr.appendChild(th);
        }
        if (hi === 0) {
          for (const xc of xcols) tr.appendChild(el('th', { class: 'th-x th-x-' + xc.kind, rowspan: hrows.length, dataset: { x: xc.key } }, xc.head ? xc.head() : xc.name));
          if (free === 'col') tr.appendChild(el('th', { class: 'th-free', rowspan: hrows.length }, 'Free'));
          if (notesOn) tr.appendChild(el('th', { class: 'th-notes', rowspan: hrows.length }, 'Notes'));
        }
        thead.appendChild(tr);
      });
      table.appendChild(thead);
    }
    const tbody = el('tbody');
    const runs = freeRuns(rows);
    const runStart = new Map(runs.map((r) => [r.from, r]));
    const runEnd = new Map(runs.map((r) => [r.to, r]));
    const wordGroups = new Map();
    for (const r of rows) for (const c of r.cells || []) if (c.kind === 'words') wordGroups.set(c.guid, { row: r, cell: c });
    const movedTargets = new Set();
    for (const r of rows) for (const c of r.cells || []) if (c.kind === 'moved' && c.target) movedTargets.add(c.target);

    rows.forEach((row, ri) => {
      const tr = el('tr', { class: 'crow cl-' + (row.clause || 'normal') + (row.endSent ? ' end-sent' : '') + (row.endPara ? ' end-para' : '') + (row.depStart ? ' dep-start' : '') + (row.depEnd ? ' dep-end' : ''), dataset: { row: row.n, label: row.label } });
      if (opts.rowDecor) { const d = opts.rowDecor(row) || {}; if (d.style) Object.assign(tr.style, d.style); for (const c of d.classes || []) tr.classList.add(c); }
      // a chart marker whose rule says "whole row" (Seth, 2026-10-18) colours the row it is in
      for (const c of row.cells || []) {
        if (c.kind !== 'tag' || !c.tag) continue;
        const look = markerLook(obj, c.tag, spec);
        if (look.hide || !look.row) continue;
        tr.classList.add('marker-row');
        tr.dataset.markerRow = c.tag.name;
        if (look.bg) tr.style.background = rgba(look.bg, 0.45);
        if (look.b) tr.style.fontWeight = '700';
        if (look.i) tr.style.fontStyle = 'italic';
        if (look.u) tr.style.textDecoration = 'underline';
        if (look.c) tr.style.color = look.c;
      }
      const lab = el('th', { class: 'rlab', title: 'Row ' + row.label + (row.clause && row.clause !== 'normal' ? ' — ' + row.clause + ' clause' : '') + (row.endSent ? '; ends the sentence' : '') + (row.endPara ? '; ends the paragraph' : '') + (opts.editable ? '. Click to style the row.' : '') },
        (starts.get(ri) || []).map((sg) => playBtn([sg], 'Play line ' + (sg.label || sg.n) + ' (' + FS.fmtTime(sg.begin) + '–' + FS.fmtTime(sg.end) + ')', 'chart-play')), row.label);
      if (opts.editable) lab.addEventListener('click', (e) => stylePopover(e.currentTarget, spec, { row: row.n }, opts, 'row ' + row.label));
      tr.appendChild(lab);
      for (const slot of layoutRow(row, cols)) {
        const cellStyles = R.chartStylesFor(index, row.n, slot.col.n, 0, '');
        const segsHere = [...new Set(slot.parts.filter((p) => p.kind === 'words' && p.seg).flatMap((p) => { const a = []; for (let n = p.seg; n <= (p.segTo || p.seg); n++) a.push(n); return a; }))];
        const td = el('td', { class: 'ccell' + (slot.parts.length ? '' : ' empty'), colspan: slot.span > 1 ? slot.span : null, dataset: { row: row.n, col: slot.col.n, segs: segsHere.length ? segsHere.join(' ') : null } });
        applyCellStyles(td, cellStyles);
        for (const part of slot.parts) td.appendChild(renderPart(part, row, slot.col, obj, spec, opts, { lines, index, vern, anal, wordGroups, movedTargets, tbody, showTextTags }));
        if (opts.editable) td.addEventListener('click', (e) => { if (e.target.closest('.cw, .cclause, .ctag, .cmoved, button, a')) return; stylePopover(td, spec, { row: row.n, col: slot.col.n }, opts, 'row ' + row.label + ', ' + slot.col.name); });
        if (free === 'tip') td.addEventListener('click', (e) => { if (e.target.closest('button, a')) return; showTip(box, obj, rowSegs(row), row); });
        tr.appendChild(td);
      }
      for (const xc of xcols) tr.appendChild(el('td', { class: 'xcell xcell-' + xc.kind, dataset: { x: xc.key, row: row.n } }, xc.cell(row, obj)));
      if (free === 'col' && runStart.has(ri)) {
        const run = runStart.get(ri);
        const t = freeText(obj, run.segs, true);
        tr.appendChild(el('td', { class: 'cfree', rowspan: run.to > run.from ? run.to - run.from + 1 : null, lang: anal.tag || null, title: 'Free translation of ' + (run.segs.length ? 'segment' + (run.segs.length > 1 ? 's ' : ' ') + run.segs.map((n) => (segsByN(obj).get(n) || { label: n }).label).join(', ') : 'this row') }, t.join(' ')));
      }
      if (notesOn) tr.appendChild(el('td', { class: 'cnotes', lang: anal.tag || null }, row.notes || ''));
      tbody.appendChild(tr);
      if (free === 'row' && runEnd.has(ri)) {
        const run = runEnd.get(ri);
        const t = freeText(obj, run.segs, true);
        if (t.length) tbody.appendChild(el('tr', { class: 'cfree-row' }, el('th', { class: 'rlab' }), el('td', { colspan: cols.length + extraCols, lang: anal.tag || null }, el('span', { class: 'cfree-text' }, t.join(' ')), el('span', { class: 'cfree-rows', title: 'The chart rows this translation covers' }, rowsLabel(rows, run.from, run.to)))));
      }
    });
    if (!rows.length) tbody.appendChild(el('tr', {}, el('td', { colspan: cols.length + 1 + extraCols, class: 'seg-empty' }, 'No rows in this range.')));
    table.appendChild(tbody);
    box.appendChild(el('div', { class: 'chart-scroll' }, table));
    if (free === 'tip') box.appendChild(el('div', { class: 'chart-tip muted small', 'data-test': 'chart-tip' }, 'Click a cell to see its free translation here.'));
    if (opts.context) box.classList.add('context');
    return box;
  }

  function applyCellStyles(td, styles) {
    for (const s of styles) {
      if (s.style === 'hl') { td.classList.add('st-hl'); if (s.color) td.style.background = s.color; }
      else if (s.style === 'color' && s.color) td.style.color = s.color;
      else if (s.style === 'b') td.style.fontWeight = '700';
      else if (s.style === 'i') td.style.fontStyle = 'italic';
      else if (s.style === 'u') td.style.textDecoration = 'underline';
      else if (s.style === 's') td.style.textDecoration = 'line-through';
    }
  }

  /* One cell part. */
  function renderPart(part, row, col, obj, spec, opts, ctx) {
    if (part.kind === 'words') {
      const wrap = el('div', { class: 'cwords' + (ctx.movedTargets.has(part.guid) ? ' moved-src' : '') + (part.lost ? ' lost' : ''), dataset: { group: part.guid, seg: part.seg } });
      if (part.lost) { wrap.appendChild(el('span', { class: 'muted small' }, '⚠ words no longer in the text')); return wrap; }
      let wi = 0;
      for (const w of part.words || []) {
        if (w.punct) { wrap.appendChild(el('span', Object.assign({ class: 'cw punct' }, wsAttrs(ctx.vern)), el('span', { class: 'il-txt' }, w.txt || ''))); continue; }
        wi++;
        const n = wi;
        const cw = el('span', { class: 'cw', dataset: { w: n, ai: w.ai != null ? w.ai : '' }, title: opts.editable ? 'Click to style this word' : null });
        for (const line of ctx.lines) {
          const t = lineText(w, line);
          if (!t && line !== 'txt') { cw.appendChild(el('span', { class: 'il-line il-empty il-' + line, html: '&nbsp;' })); continue; }
          const st = R.chartStylesFor(ctx.index, row.n, col.n, n, line).filter((s) => !(s.style === 'hl' && line !== 'txt' && ctx.index.has(row.n + '|' + col.n + '|' + n + '|') === false && false));
          const attrs = { class: 'il-line il-' + line, html: styledHtml(t, st) };
          if (line === 'txt' || line === 'morph' || line === 'cf') Object.assign(attrs, wsAttrs(ctx.vern)); else if (ctx.anal.tag) attrs.lang = ctx.anal.tag;
          cw.appendChild(el('span', attrs));
        }
        if (opts.editable) cw.addEventListener('click', (e) => { e.stopPropagation(); stylePopover(cw, spec, { row: row.n, col: col.n, word: n, line: 'txt' }, opts, '“' + (w.txt || '') + '” in row ' + row.label + ', ' + col.name, w); });
        wrap.appendChild(cw);
      }
      if (ctx.showTextTags) {
        // the text's markup tags on these words: a chip per tag, in the look its scopes give it
        const a = part.from ? part.from.w : 0, z = part.to ? part.to.w : Infinity, s = part.seg;
        const chips = [];
        for (const t of obj.tags || []) {
          if (!t.from || !t.to || s < t.from.seg || s > t.to.seg) continue;
          const ta = s === t.from.seg ? t.from.w : 0, tz = s === t.to.seg ? t.to.w : Infinity;
          if (tz < a || ta > z) continue;
          const look = FS.tagstyles ? FS.tagstyles.resolve(t.tag, null, Object.assign({}, FS.tagstyles.context(), { text: obj.text || '' })) : { bg: '#ffd6a5', fg: '#1a1d21' };
          if (look.hide) continue;
          chips.push(el('span', { class: 'ctexttag', style: { background: look.bg, color: look.fg }, title: t.tag.name + ' (FLEx text markup tag' + (look.styleVia ? '; styled by ' + look.styleVia.label : '') + ')', dataset: { tag: t.tag.name } }, t.tag.abbr || t.tag.name));
        }
        if (chips.length) wrap.appendChild(el('span', { class: 'ctagrow' }, chips));
      }
      return wrap;
    }
    if (part.kind === 'moved') {
      const tgt = ctx.wordGroups.get(part.target);
      const words = tgt ? (tgt.cell.words || []).filter((w) => !w.punct).map((w) => w.txt).join(' ') : '';
      const m = el('span', { class: 'cmoved' + (part.preposed ? ' pre' : ' post'), title: (part.preposed ? 'Preposed' : 'Postposed') + ' text' + (words ? ': “' + words + '”' : '') + (tgt ? ' — charted in ' + (tgt.cell.colN && colName(obj, tgt.cell.colN)) + (tgt.row !== row ? ' of row ' + tgt.row.label : '') : ''), dataset: { target: part.target } }, part.preposed ? '‹‹' : '››');
      m.addEventListener('mouseenter', () => { const g = ctx.tbody.querySelector('.cwords[data-group="' + part.target + '"]'); if (g) g.classList.add('flash'); });
      m.addEventListener('mouseleave', () => { ctx.tbody.querySelectorAll('.cwords.flash').forEach((g) => g.classList.remove('flash')); });
      return m;
    }
    if (part.kind === 'clause') {
      const labels = part.labels && part.labels.length ? part.labels : (part.rows || []).map((g) => g.slice(0, 4));
      const text = labels.length > 1 ? labels[0] + '–' + labels[labels.length - 1] : (labels[0] || '?');
      const c = el('span', { class: 'cclause', title: 'Dependent clause' + (labels.length > 1 ? 's ' : ' ') + labels.join(', ') + ' (click to show)', dataset: { rows: (part.rows || []).join(' ') } }, '[' + text + ']');
      c.addEventListener('click', (e) => { e.stopPropagation(); for (const lab of labels) { const tr = ctx.tbody.querySelector('.crow[data-label="' + CSS.escape(lab) + '"]'); if (tr) { tr.classList.add('flash'); tr.scrollIntoView({ block: 'nearest' }); setTimeout(() => tr.classList.remove('flash'), 1600); } } });
      return c;
    }
    if (part.kind === 'tag') {
      const t = part.tag;
      if (!t) return el('span', { class: 'ctag missing', title: 'A chart marker whose list item is missing' }, '?');
      const look = markerLook(obj, t, spec);
      if (look.hide) return el('span', { class: 'ctag hidden', dataset: { marker: t.name }, title: t.name + ' (hidden by ' + (look.hideVia ? look.hideVia.label : 'a rule') + ')' });
      const st = { background: look.bg, color: look.fg };
      if (look.b) st.fontWeight = '800';
      if (look.i) st.fontStyle = 'italic';
      if (look.u) st.textDecoration = 'underline';
      return el('span', { class: 'ctag', style: st, title: t.name + ((t.path || []).length ? ' — ' + t.path.join(' › ') : '') + ' (chart marker' + (look.styleVia ? '; styled by ' + look.styleVia.label : '') + ')', dataset: { marker: t.name } }, t.abbr || t.name);
    }
    return el('span', { class: 'muted small', title: part.error || '' }, '(' + (part.className || part.kind) + ')');
  }
  const colName = (obj, n) => { const c = ((obj.template && obj.template.columns) || []).find((x) => x.n === n); return c ? (c.path || []).concat([c.name]).join(' › ') : 'column ' + n; };

  function showTip(box, obj, segs, row) {
    const tip = box.querySelector('.chart-tip');
    if (!tip) return;
    const t = freeText(obj, segs, true);
    tip.textContent = '';
    tip.classList.remove('muted');
    tip.appendChild(el('b', {}, row.label + ' '));
    tip.appendChild(document.createTextNode(t.length ? t.join(' ') : '(no free translation)'));
  }

  function wholeChart(spec, obj) {
    const m = FS.modal({ title: (obj.name || 'Chart') + ' — ' + (obj.title || ''), class: 'context' });
    const host = el('div', { class: 'chart-context' });
    m.body.appendChild(host);
    const s = Object.assign({}, spec, { seg: null, at: null });
    FS.interlinear.render(host, s, { editable: false, context: true });
  }

  /* ------------------------------------------------------------------ styles popover */
  function stylePopover(anchor, spec, target, opts, desc, word) {
    FS.popover(anchor, (pop, close) => {
      const state = { scope: target.word != null ? 'word' : target.row != null && target.col != null ? 'cell' : target.row != null ? 'row' : 'col', line: target.line || 'txt' };
      const tgt = () => {
        if (state.scope === 'word') return { row: target.row, col: target.col, word: target.word, line: state.line };
        if (state.scope === 'cell') return { row: target.row, col: target.col, line: '' };
        if (state.scope === 'row') return { row: target.row, line: '' };
        return { col: target.col, line: '' };
      };
      const apply = (style, color) => { R.toggleStyle(spec, tgt(), style, color || ''); opts.onSpecChange && opts.onSpecChange(spec); refresh(); };
      const has = (style, color) => R.hasStyle(spec, tgt(), style, color == null ? undefined : color);
      const rows = el('div');
      function refresh() {
        rows.innerHTML = '';
        rows.appendChild(el('div', { class: 'row' }, el('b', {}, desc)));
        const scopes = [['word', 'this word'], ['cell', 'the cell'], ['row', 'the row'], ['col', 'the column']].filter(([s]) => (s === 'word' ? target.word != null : s === 'cell' ? target.row != null && target.col != null : s === 'row' ? target.row != null : target.col != null));
        if (scopes.length > 1) {
          const sr = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Style'));
          for (const [s, lab] of scopes) sr.appendChild(el('button', { class: 'tog' + (state.scope === s ? ' on' : ''), onclick: () => { state.scope = s; refresh(); } }, lab));
          rows.appendChild(sr);
        }
        if (state.scope === 'word') {
          const sel = el('select', { onchange: (e) => { state.line = e.target.value; refresh(); } });
          for (const l of R.chartLines(spec)) sel.appendChild(el('option', { value: l, selected: l === state.line }, LINE_NAMES[l] || l));
          rows.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Line'), sel));
        }
        const hlRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Highlight'));
        for (const c of HL_COLORS) hlRow.appendChild(el('button', { class: 'sw' + (has('hl', c) ? ' on' : ''), style: { background: c || 'var(--hl)' }, title: c || 'default', onclick: () => apply('hl', c) }));
        rows.appendChild(hlRow);
        const tRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Text'));
        for (const [st, label] of [['b', 'Bold'], ['u', 'Underline'], ['i', 'Italic'], ['s', 'Strike']]) tRow.appendChild(el('button', { class: 'tog' + (has(st, '') ? ' on' : ''), onclick: () => apply(st, '') }, label));
        rows.appendChild(tRow);
        const cRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Colour'));
        for (const c of TXT_COLORS) cRow.appendChild(el('button', { class: 'sw' + (has('color', c) ? ' on' : ''), style: { background: c }, onclick: () => apply('color', c) }));
        rows.appendChild(cRow);
        rows.appendChild(el('hr'));
        rows.appendChild(el('div', { class: 'row' },
          el('button', { class: 'tog', onclick: () => { R.clearStyles(spec, tgt()); opts.onSpecChange && opts.onSpecChange(spec); refresh(); } }, 'Clear this'),
          el('button', { class: 'tog', onclick: () => { R.clearStyles(spec, null); opts.onSpecChange && opts.onSpecChange(spec); close(); } }, 'Clear all styles')));
      }
      refresh();
      pop.appendChild(rows);
    });
  }

  /* ------------------------------------------------------------------ the ⋯ menu */
  function chartMenu(anchor, spec, opts, obj) {
    FS.popover(anchor, (pop, close) => {
      const change = () => opts.onSpecChange && opts.onSpecChange(spec);
      const x = spec.extra = spec.extra || {};
      const label = el('input', { type: 'text', value: spec.label || '', placeholder: 'e.g. the tail of the story', style: { width: '200px' } });
      label.addEventListener('change', () => { spec.label = label.value.trim(); change(); });
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Label'), label));
      pop.appendChild(el('hr'));
      // rows
      const rows = obj.index || [];
      if (rows.length) {
        const cur = spec.seg || obj.range || [1, obj.rowCount || 1];
        const a = el('input', { type: 'text', value: (rows.find((r) => r.n === cur[0]) || {}).label || cur[0], style: { width: '56px' }, title: 'First row (its FLEx label, e.g. 2a, or its number)' });
        const b = el('input', { type: 'text', value: (rows.find((r) => r.n === cur[1]) || {}).label || cur[1], style: { width: '56px' }, title: 'Last row' });
        const num = (v, fb) => { const s = String(v).trim().toLowerCase(); const r = rows.find((e) => String(e.label).toLowerCase() === s) || rows.find((e) => String(e.n) === s); return r ? r.n : fb; };
        const set = () => { const p = num(a.value, cur[0]), q = num(b.value, cur[1]); spec.seg = [Math.min(p, q), Math.max(p, q)]; const at = (n) => { const e = rows.find((i) => i.n === n); return e ? e.guid.replace(/-/g, '').slice(-12) : ''; }; spec.at = at(spec.seg[0]) ? [at(spec.seg[0]), at(spec.seg[1]) || at(spec.seg[0])] : null; change(); };
        a.addEventListener('change', set); b.addEventListener('change', set);
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Rows'), a, el('span', { class: 'muted' }, '–'), b, el('button', { class: 'btn small', title: 'Every row of the chart', onclick: () => { spec.seg = null; spec.at = null; change(); close(); } }, 'All')));
      }
      // lines
      const lr = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Lines'));
      const cur = R.chartLines(spec);
      const tagOn = !!(spec.lines && spec.lines.includes('tag'));
      const setLines = (on) => { spec.lines = (on.length ? on : ['txt']).concat(tagOn ? ['tag'] : []); };
      for (const l of R.CHART_LINES) lr.appendChild(el('button', { class: 'tog' + (cur.includes(l) ? ' on' : ''), onclick: () => { setLines(cur.includes(l) ? cur.filter((k) => k !== l) : R.CHART_LINES.filter((k) => cur.includes(k) || k === l)); change(); close(); } }, LINE_NAMES[l]));
      if ((obj.tags || []).length) lr.appendChild(el('button', { class: 'tog' + (tagOn ? ' on' : ''), 'data-test': 'chart-texttags', title: 'The text’s FLEx markup tags on the words of each cell', onclick: () => { spec.lines = cur.concat(tagOn ? [] : ['tag']); change(); close(); } }, 'FLEx tags'));
      pop.appendChild(lr);
      // free translations
      const fsel = el('select', { onchange: (e) => { if (e.target.value === 'row') delete x.free; else x.free = e.target.value; change(); close(); } });
      for (const m of R.FREE_MODES) fsel.appendChild(el('option', { value: m, selected: R.freeMode(spec) === m }, FREE_NAMES[m]));
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Free translations'), fsel));
      const hcb = el('input', { type: 'checkbox', checked: x.headers !== 'off' });
      hcb.addEventListener('change', () => { if (hcb.checked) delete x.headers; else x.headers = 'off'; change(); });
      const ncb = el('input', { type: 'checkbox', checked: x.notes !== 'off' });
      ncb.addEventListener('change', () => { if (ncb.checked) delete x.notes; else x.notes = 'off'; change(); });
      pop.appendChild(el('div', { class: 'row' }, el('label', {}, hcb, ' Column headings'), el('label', {}, ncb, ' Row notes')));
      // columns
      const cols = (obj.template && obj.template.columns) || [];
      if (cols.length) {
        const shown = new Set(visibleColumns(spec, obj).map((c) => c.n));
        const box = el('div', { class: 'chart-cols' });
        const write = () => { const on = cols.filter((c) => shown.has(c.n)); if (on.length === cols.length || !on.length) delete x.cols; else x.cols = on.map((c) => 'c' + c.n).join(','); change(); };
        let lastGroup = null;
        for (const c of cols) {
          const g = (c.path || []).join(' › ');
          if (g !== lastGroup) {
            lastGroup = g;
            const gcb = el('input', { type: 'checkbox', checked: cols.filter((k) => (k.path || []).join(' › ') === g).every((k) => shown.has(k.n)) });
            gcb.addEventListener('change', () => { for (const k of cols) if ((k.path || []).join(' › ') === g) { if (gcb.checked) shown.add(k.n); else shown.delete(k.n); } write(); close(); });
            box.appendChild(el('label', { class: 'chart-col-group' }, gcb, ' ', g || 'Columns'));
          }
          const cb = el('input', { type: 'checkbox', checked: shown.has(c.n) });
          cb.addEventListener('change', () => { if (cb.checked) shown.add(c.n); else shown.delete(c.n); write(); });
          box.appendChild(el('label', { class: 'chart-col' }, cb, ' ', c.name, c.abbr && c.abbr !== c.name ? el('span', { class: 'muted small' }, ' ' + c.abbr) : null));
        }
        pop.appendChild(el('div', { class: 'row', style: { alignItems: 'flex-start' } }, el('span', { class: 'lbl' }, 'Columns'), box));
      }
      pop.appendChild(el('hr'));
      if (opts.layout) {
        const cb = el('input', { type: 'checkbox', checked: !!x.ex });
        cb.addEventListener('change', () => { if (cb.checked) x.ex = true; else delete x.ex; change(); });
        pop.appendChild(el('label', { class: 'row', style: { gap: '8px' } }, cb, 'Number as example (1), (2)…'));
      }
      if (obj.url) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(obj.url); FS.toast('FLEx link copied'); close(); } }, 'Copy FLEx link'));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'chart-pivot', title: 'Counts of rows by marker (and clause type) and by column', onclick: () => { close(); pivotDialog(obj, spec); } }, 'Pivot: markers \u00d7 columns\u2026'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(chartTsv(spec, obj)); FS.toast('Copied as TSV'); close(); } }, 'Copy as TSV'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(R.serialize(spec)); FS.toast('Embed code copied'); close(); } }, 'Copy embed code'));
      if (FS.api && FS.api.export_chart) {
        pop.appendChild(el('button', { class: 'menu-item', title: 'The shape FieldWorks itself exports (Texts & Words › Discourse Chart › Export), with GUIDs added', onclick: async () => { close(); try { const p = await FS.api.export_chart(obj.guid, 'xml', spec.seg || null); if (p) FS.toast('Saved ' + p); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Export as FLEx chart XML…'));
        pop.appendChild(el('button', { class: 'menu-item', title: 'Every row, cell and word with its GUID', onclick: async () => { close(); try { const p = await FS.api.export_chart(obj.guid, 'json', spec.seg || null); if (p) FS.toast('Saved ' + p); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Export as JSON…'));
      }
      if (FS.newChartNote && !opts.collection) pop.appendChild(el('button', { class: 'menu-item', title: 'A note that is this chart, with its own columns (choice lists, notes, rules) and these styles', onclick: () => { close(); FS.newChartNote(obj.guid, R.serialize(spec)); } }, 'Open as a chart note\u2026'));
      if (opts.editSource) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); opts.editSource(); } }, 'Edit source'));
      if (opts.duplicate || opts.remove) pop.appendChild(el('hr'));
      if (opts.duplicate) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); opts.duplicate(); } }, 'Duplicate this object'));
      if (opts.remove) pop.appendChild(el('button', { class: 'menu-item danger', onclick: async () => { close(); if (await FS.confirmAt(anchor, 'Remove this chart from the note? (Undo brings it back.)', 'Remove')) { FS.interlinear.closeOverlay(); opts.remove(); } } }, 'Remove this object…'));
    });
  }

  /* ------------------------------------------------------------------ plain text */
  /* The chart as a tab-separated grid: the header rows, then per row its label, one cell per
   * visible column (words space-separated; markers as ‹‹1b, [2a], ⟨Top⟩), the free translation
   * and the notes. What "Copy as TSV" and the readable copy in the file (flexcopy.js) use. */
  function chartGrid(spec, obj) {
    const cols = visibleColumns(spec, obj);
    const lines = R.chartLines(spec);
    const free = R.freeMode(spec);
    const notesOn = !(spec.extra && spec.extra.notes === 'off') && (obj.rows || []).some((r) => (r.notes || '').trim());
    const out = [];
    if (!(spec.extra && spec.extra.headers === 'off')) {
      headerRows(cols).forEach((hr, hi) => {
        const cells = [''];
        for (const h of hr) { cells.push(h.text); for (let i = 1; i < h.span; i++) cells.push(''); }
        if (free !== 'off') cells.push(hi === 0 ? 'Free' : '');
        if (notesOn) cells.push(hi === 0 ? 'Notes' : '');
        out.push(cells);
      });
    }
    const wg = new Map();
    for (const r of obj.rows || []) for (const c of r.cells || []) if (c.kind === 'words') wg.set(c.guid, { row: r, cell: c });
    const partText = (p) => {
      if (p.kind === 'words') return (p.words || []).map((w) => w.punct ? (w.txt || '') : lines.map((l) => lineText(w, l)).filter(Boolean).join('/')).join(' ');
      if (p.kind === 'moved') { const t = wg.get(p.target); return (p.preposed ? '‹‹' : '››') + (t ? t.row.label : ''); }
      if (p.kind === 'clause') return '[' + ((p.labels || []).length > 1 ? p.labels[0] + '–' + p.labels[p.labels.length - 1] : (p.labels || ['?'])[0]) + ']';
      if (p.kind === 'tag') return '⟨' + ((p.tag && (p.tag.abbr || p.tag.name)) || '?') + '⟩';
      return '';
    };
    const runs = freeRuns(obj.rows || []);
    (obj.rows || []).forEach((row, ri) => {
      const cells = [row.label];
      for (const slot of layoutRow(row, cols)) { cells.push(slot.parts.map(partText).filter(Boolean).join(' ')); for (let i = 1; i < slot.span; i++) cells.push(''); }
      if (free !== 'off') { const run = runs.find((r) => r.from === ri); cells.push(run ? freeText(obj, run.segs, true).join(' ') : ''); }
      if (notesOn) cells.push(row.notes || '');
      out.push(cells);
    });
    return out;
  }
  const chartTsv = (spec, obj) => chartGrid(spec, obj).map((r) => r.map((c) => String(c == null ? '' : c).replace(/[\t\r\n]+/g, ' ')).join('\t')).join('\n') + '\n';

  /* ------------------------------------------------------------------ the pivot
   * Rows: every chart marker (and the clause types, moved text, clause references); columns: the
   * visible template columns; a cell counts the rows that carry the marker AND have words in the
   * column; the last column counts the rows with the marker at all (Seth, 2026-10-18: "compile"). */
  function pivot(obj, spec) {
    const cols = visibleColumns(spec, obj);
    const rows = obj.rows || [];
    const keys = new Map();     // key → {label, rows: Set(row n)}
    const addKey = (k, label, n) => { if (!keys.has(k)) keys.set(k, { label, rows: new Set() }); keys.get(k).rows.add(n); };
    for (const r of rows) {
      for (const c of r.cells || []) {
        if (c.kind === 'tag' && c.tag) addKey('m:' + c.tag.name, '\u2690 ' + c.tag.name, r.n);
        else if (c.kind === 'moved') addKey('moved:' + (c.preposed ? 'preposed' : 'postposed'), 'moved text, ' + (c.preposed ? 'preposed' : 'postposed'), r.n);
        else if (c.kind === 'clause') addKey('clauseref', 'clause marker', r.n);
      }
      if (r.clause && r.clause !== 'normal') addKey('clause:' + r.clause, r.clause + ' clause', r.n);
    }
    const hasWords = (r, colN) => (r.cells || []).some((c) => c.kind === 'words' && c.colN === colN && (c.words || []).some((w) => !w.punct));
    const out = { columns: cols.map((c) => (c.path || []).concat([c.name]).join(' \u203a ')), lines: [], totals: cols.map((c) => rows.filter((r) => hasWords(r, c.n)).length), rowCount: rows.length };
    for (const [k, v] of keys) out.lines.push({ key: k, label: v.label, counts: cols.map((c) => rows.filter((r) => v.rows.has(r.n) && hasWords(r, c.n)).length), total: v.rows.size });
    return out;
  }
  function pivotDialog(obj, spec) {
    const p = pivot(obj, spec);
    const m = FS.modal({ title: 'Pivot \u2014 ' + (obj.name || 'Chart') + ' \u00b7 ' + (obj.title || '') });
    if (!p.lines.length) { m.body.appendChild(el('p', { class: 'muted' }, 'No markers, clause types or moved text in these rows to count.')); return; }
    const tbl = el('table', { class: 'pivot-table' });
    tbl.appendChild(el('tr', {}, el('th', {}), ...p.columns.map((c) => el('th', {}, c)), el('th', {}, 'rows')));
    for (const l of p.lines) tbl.appendChild(el('tr', {}, el('th', {}, l.label), ...l.counts.map((n) => el('td', { class: n ? 'n' : 'n zero' }, n ? String(n) : '\u00b7')), el('td', { class: 'n total' }, String(l.total))));
    tbl.appendChild(el('tr', { class: 'totals' }, el('th', {}, 'rows with words'), ...p.totals.map((n) => el('td', { class: 'n' }, String(n))), el('td', { class: 'n total' }, String(p.rowCount))));
    const tsv = [['', ...p.columns, 'rows'].join('\t')].concat(p.lines.map((l) => [l.label, ...l.counts, l.total].join('\t'))).concat([['rows with words', ...p.totals, p.rowCount].join('\t')]).join('\n') + '\n';
    m.body.append(el('p', { class: 'muted small' }, 'Each cell counts the rows of this chart (the range shown) that carry the marker and have words in the column; the last column counts the rows with the marker.'), tbl,
      el('div', { class: 'btn-row' }, el('button', { class: 'btn', 'data-test': 'pivot-copy', onclick: () => { FS.copyText(tsv); FS.toast('Copied as TSV'); } }, 'Copy as TSV'), el('button', { class: 'btn primary', onclick: () => m.close() }, 'Done')));
  }

  FS.chart = { renderChart, visibleColumns, headerRows, layoutRow, rowSegs, freeRuns, lineStarts, freeText, chartGrid, chartTsv, markerLook, pivot, pivotDialog, LINE_NAMES, FREE_NAMES };
})();
