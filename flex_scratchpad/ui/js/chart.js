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
  function selectedColumns(spec, chart) {
    const cols = (chart.template && chart.template.columns) || [];
    if (chart.flat) return cols;
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
  /* The columns an embed shows (`cols=`), less the EMPTY ones when `empty=off` says so (Seth,
   * 2026-10-18: "option to hide empty columns on all chart objects") — a column with no cell part
   * in the rows shown; never all of them. */
  function visibleColumns(spec, chart) {
    const cols = selectedColumns(spec, chart);
    if (!(spec.extra && spec.extra.empty === 'off')) return cols;
    const used = new Set();
    const all = (chart.template && chart.template.columns) || [];
    for (const r of chart.rows || []) for (const c of r.cells || []) { used.add(c.colN); const nb = mergeMode(spec) === 'owner' ? null : mergedNeighbour(c, all); if (nb) used.add(nb.n); }
    const out = cols.filter((c) => used.has(c.n));
    return out.length ? out : cols;
  }
  /* ONE COLUMN (Seth, 2026-10-18: "collapse the text chart data into a single display column that
   * just displays the row all in one cell with visual filters … the option to switch back and
   * forth"): `view=flat` — every part of a row in one cell, in the columns' order, each word group
   * labelled with its column (so column visual filters and markers do the work the columns did).
   * `flatten` gives the chart that shape: one template column, every cell part on it, its own
   * column kept as `srcCol` for the styles and the labels; the renderer, the grid / TSV copy and
   * the exports all take it. */
  const FLAT_COL = { n: 0, name: 'Text', abbr: 'Text', path: [], guid: 'flat' };
  /* MERGED CELLS (Seth, 2026-10-19: "I merge columns when I'm unsure which column it is because it
   * could be either"): a part merged with its empty neighbour (FLEx's MergesAfter / MergesBefore)
   * belongs to BOTH columns by default — for the DATA (a search, a rule's col:, hidden empty columns,
   * the line-up all match either column) and for the LOOK (the owner's look round the contents, the
   * neighbour's round that when it has a rule of its own, so the drawing says "either"). The user's
   * choice, `merge=`: `both` (default), `owner` (owner column only, data and look), `lookowner`
   * (both for data, the owner's look only). The Python search always counts both. */
  const mergeMode = (spec) => { const v = spec && spec.extra && spec.extra.merge; return v === 'owner' || v === 'lookowner' ? v : 'both'; };
  const mergesAfter = (p) => !!(p && (p.srcMergeAfter != null ? p.srcMergeAfter : p.mergeAfter));
  const mergesBefore = (p) => !!(p && (p.srcMergeBefore != null ? p.srcMergeBefore : p.mergeBefore));
  /* The template column a merged part extends into, or null. */
  function mergedNeighbour(part, allCols) {
    if (!part || !(mergesAfter(part) || mergesBefore(part))) return null;
    const n = part.srcCol ? part.srcCol.n : part.colN;
    const i = (allCols || []).findIndex((c) => c.n === n);
    if (i < 0) return null;
    return mergesAfter(part) ? allCols[i + 1] || null : allCols[i - 1] || null;
  }
  /* The columns a part counts for: the owner, and the merged neighbour unless `merge=` says not. */
  function partColumns(part, allCols, spec, forLook) {
    const owner = part.srcCol || (allCols || []).find((c) => c.n === part.colN) || null;
    const mode = mergeMode(spec);
    if (!owner) return [];
    if (mode === 'owner' || (forLook && mode === 'lookowner')) return [owner];
    const nb = mergedNeighbour(part, allCols);
    return nb ? [owner, nb] : [owner];
  }
  const viewOf = (spec) => { const v = spec.extra && spec.extra.view; return v === 'flat' || v === 'groups' ? v : 'cols'; };
  const isFlat = (spec) => viewOf(spec) !== 'cols';
  const isGroups = (spec) => viewOf(spec) === 'groups';
  /* The header GROUP a column belongs to: its first path element, else the column itself. */
  const groupNameOf = (c) => ((c.path || [])[0] || c.name || '');
  /* `view=flat`: ONE column; `view=groups` (Seth, 2026-10-19: "a major-column view … just the 3
   * parent columns (and then style text from sub columns within each cell per visual filter
   * rules)"): one column PER HEADER GROUP, its sub-columns' parts in order inside each cell, each
   * labelled and styled by its own column's rules — the same flat machinery with several cells. */
  function flatten(obj, spec) {
    if (!isFlat(spec) || obj.flat) return obj;
    const cols = visibleColumns(spec, obj);
    const grouped = isGroups(spec);
    const order = new Map(cols.map((c, i) => [c.n, i]));
    const byN = new Map(cols.map((c) => [c.n, c]));
    const groups = [];                       // the groups view's columns, in the chart's order
    const groupN = new Map();
    if (grouped) for (const c of cols) { const g = groupNameOf(c); if (!groupN.has(g)) { groupN.set(g, 1000 + groups.length); groups.push({ n: 1000 + groups.length, name: g, abbr: g, path: [], guid: 'group:' + g, group: true }); } }
    const rows = (obj.rows || []).map((r) => {
      const parts = (r.cells || []).filter((c) => order.has(c.colN)).map((c, i) => Object.assign({}, c, { srcCol: byN.get(c.colN), colN: grouped ? groupN.get(groupNameOf(byN.get(c.colN))) : 0, srcMergeAfter: !!c.mergeAfter, srcMergeBefore: !!c.mergeBefore, mergeAfter: false, mergeBefore: false, _i: i }));
      parts.sort((a, b) => (order.get(a.srcCol.n) - order.get(b.srcCol.n)) || (a._i - b._i));
      return Object.assign({}, r, { cells: parts });
    });
    return Object.assign({}, obj, { flat: true, grouped, template: Object.assign({}, obj.template || {}, { columns: grouped ? groups : [FLAT_COL], srcColumns: (obj.template && obj.template.columns) || [] }), rows });
  }
  /* LINE UP ON A COLUMN (Seth, 2026-10-19: in the one-column view "align elements from one or more
   * specific columns so that they do line up … center arrange/align … other elements just adjacent
   * to the left or right and wrapped as needed"): `align=` names columns like `cols=` does; in each
   * cell the parts before the first aligned run go LEFT (ending at a shared axis), the run of
   * aligned parts sits CENTRED on the axis, the rest flows RIGHT — a 3-track grid whose left and
   * anchor tracks are as wide as the widest row needs (`alignFlat` measures after drawing). */
  function alignedColumns(spec, full) {
    const sel = spec.extra && spec.extra.align;
    if (!sel || !isFlat(spec)) return new Set();
    return new Set(selectedColumns({ extra: { cols: sel } }, full).map((c) => c.n));
  }
  /* Which edge of the lined-up column meets the axis (Seth, 2026-10-19: "line up the left edge,
   * right edge, or center of that column"): `alignat=left|center|right`, centre when unset. */
  /* Where a cell's MARKER CHIPS go (Seth, 2026-10-19: "display marker chips on a separate line (to
   * make column widths smaller) … wrap at word width"): `chips=inline` (beside the words, the
   * default), `chips=line` (a line of their own under the words), `chips=wrap` (that line no wider
   * than the words, so the chips wrap and the column stays as narrow as its words). */
  const chipsMode = (spec) => { const v = spec && spec.extra && spec.extra.chips; return v === 'line' || v === 'wrap' ? v : 'inline'; };
  /* Appends a part's node to a container, keeping the marker chips on a `.chips-line` at the end
   * when the mode says so; `.chips-line.wrap` gets its width from the words after the draw. */
  function addPart(container, node, mode) {
    if (mode === 'inline' || !(node.classList && node.classList.contains('ctag'))) {
      const line = container.querySelector(':scope > .chips-line');
      if (line) container.insertBefore(node, line); else container.appendChild(node);
      return;
    }
    let line = container.querySelector(':scope > .chips-line');
    if (!line) { line = el('span', { class: 'chips-line' + (mode === 'wrap' ? ' wrap' : '') }); container.appendChild(line); }
    line.appendChild(node);
    if (![...line.children].some((c) => !c.classList.contains('hidden'))) line.classList.add('void'); else line.classList.remove('void');
  }
  /* `chips=wrap`: each chip line no wider than the words it belongs with (measured, since a table
   * column is as wide as its widest cell and the chips must not be what makes it wide). */
  function placeChipLines(table) {
    const lines = [...table.querySelectorAll('.chips-line.wrap')];
    if (!lines.length) return;
    const place = () => {
      if (!table.isConnected) return;
      for (const line of lines) {
        const host = line.parentElement;
        let w = 0;
        for (const n of host.children) if (n !== line && !n.classList.contains('chips-line')) w = Math.max(w, n.getBoundingClientRect().width);
        const v = Math.max(48, Math.ceil(w)) + 'px';
        if (line.style.maxWidth !== v) line.style.maxWidth = v;
      }
    };
    place();
    if (typeof ResizeObserver !== 'undefined') {
      let queued = false;
      const ro = new ResizeObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; if (!table.isConnected) { ro.disconnect(); return; } place(); }); });
      ro.observe(table);
    }
  }
  const alignEdge = (spec) => { const v = spec && spec.extra && spec.extra.alignat; return v === 'left' || v === 'right' ? v : 'center'; };
  function alignFlat(table) {
    const cells = [...table.querySelectorAll('.al-grid')];
    if (!cells.length) return;
    const place = () => {
      if (!table.isConnected) return;
      table.style.setProperty('--al-l', 'max-content');
      table.style.setProperty('--al-a', 'max-content');
      let l = 0, a = 0, w = 0;
      for (const g of cells) {
        const L = g.querySelector('.al-l'), A = g.querySelector('.al-a');
        if (L) l = Math.max(l, L.getBoundingClientRect().width);
        if (A) a = Math.max(a, A.getBoundingClientRect().width);
        w = Math.max(w, g.getBoundingClientRect().width);
      }
      const left = Math.min(Math.ceil(l), Math.max(60, Math.floor(w * 0.45)));
      const vl = left + 'px', va = Math.ceil(a) + 'px';
      if (table.style.getPropertyValue('--al-l') !== vl) table.style.setProperty('--al-l', vl);
      if (table.style.getPropertyValue('--al-a') !== va) table.style.setProperty('--al-a', va);
    };
    place();
    if (typeof ResizeObserver !== 'undefined') {
      let queued = false;
      const ro = new ResizeObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; if (!table.isConnected) { ro.disconnect(); return; } place(); }); });
      ro.observe(table);
    }
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
  function layoutRow(row, cols, allCols) {
    const byCol = new Map();
    for (const c of row.cells || []) { if (!byCol.has(c.colN)) byCol.set(c.colN, []); byCol.get(c.colN).push(c); }
    // with hidden columns a merge may only span into the TEMPLATE neighbour (Seth, 2026-10-19), never whatever shows next
    const adjacent = (a, b) => { if (!allCols || !allCols.length) return true; const i = allCols.findIndex((c) => c.n === a.n); return i >= 0 && !!allCols[i + 1] && allCols[i + 1].n === b.n; };
    const out = [];
    let i = 0;
    while (i < cols.length) {
      const col = cols[i];
      const parts = byCol.get(col.n) || [];
      let span = 1;
      // FLEx merges a cell with its ONE neighbour (MergesAfter / MergesBefore), when that is empty
      if (parts.some((p) => p.mergeAfter) && i + 1 < cols.length && !(byCol.get(cols[i + 1].n) || []).length && adjacent(col, cols[i + 1])) span++;
      if (parts.some((p) => p.mergeBefore) && out.length && !out[out.length - 1].parts.length && out[out.length - 1].span === 1 && adjacent(out[out.length - 1].col, col)) { out.pop(); span++; }
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
  /* COLUMN WIDTHS (Seth, 2026-10-18: "adjust column sizes (including off the right side,
   * requiring rightward scroll)"): `cw=4:300,free:160,x0:120` in the embed — a template column by
   * its number, `free` / `notes`, a custom column by `x<i>` — pixels. Parsed here, written by the
   * header resizers; a table wider than its pane scrolls in `.chart-scroll`. */
  function colWidths(spec) {
    const out = new Map();
    for (const part of String((spec.extra && spec.extra.cw) || '').split(',')) {
      const m = /^([a-z0-9]+):(\d+)$/i.exec(part.trim());
      if (m && +m[2] >= 24) out.set(m[1], +m[2]);
    }
    return out;
  }
  function setColWidths(spec, widths) {
    spec.extra = spec.extra || {};
    const s = [...widths].filter(([, w]) => w > 0).map(([k, w]) => k + ':' + Math.round(w)).join(',');
    if (s) spec.extra.cw = s; else delete spec.extra.cw;
  }
  /* FROZEN COLUMNS: the row labels, and a chart note's custom columns that ask for it, stay put
   * while the table scrolls sideways — `position: sticky` inside .chart-scroll, with each frozen
   * column's offset the widths of the frozen columns before it (left) or after it (right), read
   * from the <col>s and kept up to date by a ResizeObserver. */
  function placeFrozen(table, colKeys, colEls, frozen) {
    const put = (cell, prop, v) => { if (cell.style[prop] !== v) cell.style[prop] = v; };   // no write when nothing changed
    const place = () => {
      if (!table.isConnected) { ro.disconnect(); return; }
      const w = (k) => { const c = colEls.get(k); return c ? c.getBoundingClientRect().width : 0; };
      let left = 0;
      for (const k of colKeys) {
        if (frozen.get(k) !== 'l') continue;
        for (const cell of table.querySelectorAll('[data-ck="' + k + '"]')) put(cell, 'left', left + 'px');
        left += w(k);
      }
      let right = 0;
      for (const k of colKeys.slice().reverse()) {
        if (frozen.get(k) !== 'r') continue;
        for (const cell of table.querySelectorAll('[data-ck="' + k + '"]')) put(cell, 'right', right + 'px');
        right += w(k);
      }
    };
    // the observer's work waits for the next frame: writing styles inside the callback is what
    // Chromium reports as "ResizeObserver loop completed with undelivered notifications"
    let queued = false;
    const ro = new ResizeObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; place(); }); });
    ro.observe(table);
    place();
  }

  /* STICKY HEADER ROWS (Seth, 2026-10-18: "we want the chart header rows to be sticky"). CSS
   * `position: sticky` cannot do it: the table sits in `.chart-scroll` (its sideways scroller),
   * and a sticky cell sticks to THAT box, which never scrolls up. So while the table's header has
   * passed the top of the pane and its rows are still in view, a copy of the header (the same
   * colgroup, the same cell widths) is laid over the top of the pane, fixed, clipped to the
   * chart's width and shifted with its sideways scroll. Below the note's sticky headings strip and
   * a collection's / chart note's header. Removed with the chart. */
  function wireStickyHead(box, table) {
    let scroller = box.parentElement;
    while (scroller && !/(auto|scroll)/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement;
    if (!scroller || !table.tHead) return;
    const scroll = box.querySelector('.chart-scroll');
    let ghost = null, inner = null;
    const offset = () => {
      const sr = scroller.getBoundingClientRect();
      let off = 0;
      const sh = document.getElementById('sticky-heads');
      if (scroller.id === 'editor' && sh && sh.offsetParent && !sh.hidden) off = Math.max(off, sh.getBoundingClientRect().bottom - sr.top);
      const ch = scroller.querySelector(':scope > .coll-head');
      if (ch) off = Math.max(off, ch.getBoundingClientRect().bottom - sr.top);
      return sr.top + off;
    };
    const build = () => {
      ghost = el('div', { class: 'tchart-sticky', 'data-test': 'chart-sticky-head' });
      inner = el('table', { class: table.className + ' ghost' });
      const cg = table.querySelector('colgroup');
      if (cg) inner.appendChild(cg.cloneNode(true));
      inner.appendChild(table.tHead.cloneNode(true));
      ghost.appendChild(inner);
      document.body.appendChild(ghost);
    };
    const sync = () => {
      // the live table's column widths (a single-column header cell per column: the label and
      // the extras span every header row, the template columns sit in the last row), put on
      // the copy's <col>s so its fixed layout matches the table under it
      const live = table.tHead.rows, n = live.length;
      const widths = [];
      let pos = 0;
      for (const cell of live[0].cells) { if (cell.rowSpan >= n) widths[pos] = cell.getBoundingClientRect().width; pos += cell.colSpan; }
      if (n > 1) { let q = 1; for (const cell of live[n - 1].cells) { widths[q] = cell.getBoundingClientRect().width; q += cell.colSpan; } }
      let cg = inner.querySelector('colgroup');
      if (!cg) { cg = el('colgroup'); inner.insertBefore(cg, inner.firstChild); }
      while (cg.children.length < widths.length) cg.appendChild(el('col'));
      widths.forEach((w, i) => { if (w) cg.children[i].style.width = w + 'px'; });
      inner.style.width = table.getBoundingClientRect().width + 'px';
      // the frozen header cells keep their offsets in the copy; the copy scrolls like the table
      // (scrollLeft, not a transform: a transform would carry the sticky cells along)
      const mine = inner.tHead.rows;
      for (let r = 0; r < n && r < mine.length; r++) for (let c = 0; c < live[r].cells.length && c < mine[r].cells.length; c++) { const lc = live[r].cells[c]; if (lc.dataset.frz) { mine[r].cells[c].style.left = lc.style.left; mine[r].cells[c].style.right = lc.style.right; } }
      ghost.scrollLeft = scroll ? scroll.scrollLeft : 0;
    };
    const update = () => {
      if (!table.isConnected) { stop(); return; }
      const top = offset();
      const tr = table.getBoundingClientRect(), hh = table.tHead.getBoundingClientRect().height;
      const sr = (scroll || table).getBoundingClientRect();
      const show = tr.top < top && tr.bottom - hh > top && sr.width > 0 && box.offsetParent;
      if (!show) { if (ghost) ghost.style.display = 'none'; return; }
      if (!ghost) build();
      ghost.style.display = '';
      const g = ghost.style, want = { top: top + 'px', left: sr.left + 'px', width: sr.width + 'px' };
      for (const k of Object.keys(want)) if (g[k] !== want[k]) g[k] = want[k];
      sync();
    };
    let ro = null, sweep = 0;
    const stop = () => { if (ghost) ghost.remove(); ghost = null; scroller.removeEventListener('scroll', update); window.removeEventListener('resize', update); if (scroll) scroll.removeEventListener('scroll', update); if (ro) ro.disconnect(); ro = null; if (sweep) clearInterval(sweep); sweep = 0; };
    scroller.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    if (scroll) scroll.addEventListener('scroll', update, { passive: true });
    // the header moves when the pane's sticky strip grows or the table re-lays out: a cheap
    // re-check, on the next frame (styles written inside the callback make Chromium report a loop)
    let queued = false;
    ro = new ResizeObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; if (table.isConnected) update(); else stop(); }); });
    ro.observe(table);
    // a chart that leaves the page without a scroll (another note opened, a redraw) must take
    // its copy along (Seth, 2026-10-19: a header "left behind that never goes away")
    sweep = setInterval(() => { if (!table.isConnected || !box.isConnected) stop(); }, 500);
    box._stickyStop = stop;
    requestAnimationFrame(update);
  }
  const segsByN = (chart) => new Map((chart.segments || []).map((s) => [s.n, s]));
  /* ‘The dog slept.’ (1.1) · ‘Yesterday…’ (1.2) — the free translations of some segments. */
  function freeText(chart, segs, withLabels) {
    const by = segsByN(chart);
    const parts = segs.map((n) => by.get(n)).filter(Boolean).filter((s) => (s.free || '').trim());
    return parts.map((s) => '‘' + s.free.trim() + '’' + (withLabels && parts.length > 1 ? ' (' + (s.label || s.n) + ')' : ''));
  }
  const rowsLabel = (rows, a, b) => (a === b ? rows[a].label : rows[a].label + '–' + rows[b].label);
  /* Whether a marker chip is drawn: its rule may hide it; in a cell with NO WORDS it follows
   * `emptymarkers=off` (the ⋯ menu's switch) unless its own rule says `empty` / `noempty`
   * (Seth, 2026-10-19: "show or hide markers associated with empty cells"). A view setting only:
   * a chart note's rule columns and the search read the chart itself, hidden or not. */
  function markerShown(look, spec, cellHasWords) {
    if (look.hide) return false;
    if (cellHasWords) return true;
    if (look.onEmpty != null) return look.onEmpty;
    return !(spec && spec.extra && spec.extra.emptymarkers === 'off');
  }
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
    const full = obj;                       // the chart as fetched (the menu's column list, the pivot)
    obj = flatten(obj, spec);
    const flat = !!obj.flat;
    // a column's own look (Seth, 2026-10-18: "apply specific styles to specific columns … and
    // configure them myself"): the `column:<Group/Name>` rules, from the chart's ⚑ popover or any
    // scope dialog — its cells tinted / bordered / coloured, a hidden column left out
    const colLooks = new Map();
    const alignSet = alignedColumns(spec, full);
    const chipMode = chipsMode(spec);
    let cols = visibleColumns(spec, obj);
    if (!flat) {
      for (const c of cols) { const lk = columnLook(c, obj, spec); if (lk) colLooks.set(c.n, lk); }
      const shown = cols.filter((c) => !(colLooks.get(c.n) || {}).hide);
      if (shown.length) cols = shown;
    }
    // a look that comes from a HEADER GROUP's rule (`column:group:<name>`) styles the group's
    // columns AS ONE UNIT (Seth, 2026-10-19: "not 3 minor columns styled the same"): the group's
    // heading wears it, and in each row the run of its cells is one box (`unitOf` → first / mid / last)
    const groupLooks = new Map();            // norm(group name) → the GROUP's own look (one colour for the whole unit)
    for (const c of cols) { const lk = colLooks.get(c.n), g = lk && groupOfLook(lk); if (g && !groupLooks.has(g)) groupLooks.set(g, groupLook(g, c, obj, spec) || lk); }
    const unitOf = (i, span) => {
      const lk = colLooks.get(cols[i].n), g = lk && groupOfLook(lk);
      if (!g) return null;
      const same = (j) => j >= 0 && j < cols.length && groupOfLook(colLooks.get(cols[j].n) || {}) === g;
      return { group: g, first: !same(i - 1), last: !same(i + (span || 1)) };
    };
    const allCols = (full.template && full.template.columns) || [];
    const lines = R.chartLines(spec);
    const free = R.freeMode(spec);
    const headers = !(spec.extra && spec.extra.headers === 'off');
    const notesOn = !(spec.extra && spec.extra.notes === 'off') && (obj.rows || []).some((r) => (r.notes || '').trim());
    const index = R.resolveChartStyles(spec, obj);
    const vern = (obj.ws && obj.ws.vern) || {}, anal = (obj.ws && obj.ws.anal) || {};
    const rows = obj.rows || [];
    const showTextTags = !!(spec.lines && spec.lines.includes('tag')) && (obj.tags || []).length > 0;   // the text's markup tags inside the cells (Seth, 2026-10-18)
    const box = el('div', { class: 'flex-obj chart-obj' + (obj.cached ? ' cached' : '') + (flat ? ' flat' : ''), dataset: { chart: obj.guid } });
    // ZOOM (Seth, 2026-10-18: "zoom in and out option for our chart notes (and chart examples)"):
    // `zoom=NN` percent in the embed; the table's font sizes are all multiples of --cz
    const zoom = zoomOf(spec);
    if (zoom !== 100) box.style.setProperty('--cz', String(zoom / 100));
    const range = obj.range || [rows[0] && rows[0].n, rows.length && rows[rows.length - 1].n];
    const rangeText = rows.length ? (range[0] === range[1] ? 'row ' + rows[0].label : 'rows ' + rows[0].label + '–' + rows[rows.length - 1].label) + ' of ' + (obj.rowCount || rows.length) : 'no rows';
    const change = () => opts.onSpecChange && opts.onSpecChange(spec);

    const head = el('div', { class: 'flex-head' + (opts.inCell ? ' compact' : '') },
      opts.editable && !opts.overlay && !opts.context && !opts.collection ? el('span', { class: 'drag-handle', draggable: 'true', title: 'Drag to move this object (Ctrl: copy)' }, '⠿') : null,
      el('span', { class: 'ttl' }, (obj.name || 'Chart') + ' · '),
      el('span', Object.assign({ class: 'ttl vern', title: obj.title || '' }, wsAttrs(vern)), obj.title || '(untitled text)'),
      el('span', { class: 'badge', 'data-test': 'chart-range' }, rangeText),
      obj.cached ? el('span', { class: 'badge warn', title: obj.liveError || 'Shown from the notebook cache' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')) : null,
      obj.anchorsLost ? el('span', { class: 'badge warn', title: 'Some of these rows are no longer in the chart as they were' }, 'rows changed in FLEx') : null,
      spec.label ? el('span', { class: 'badge' }, spec.label) : null,
      el('span', { class: 'spacer' }));
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
    // ⚑ on EVERY chart (Seth, 2026-10-18: the Great Flood chart, which has no markers, had no way to
    // its visual filters): the chart markers, the text's tags, the filter switches, the scopes
    const markersHere = FS.tagstyles && FS.tagstyles.markersIn ? FS.tagstyles.markersIn(obj) : [];
    const tagsHere = FS.tagstyles && FS.tagstyles.tagsIn && (obj.tags || []).length ? FS.tagstyles.tagsIn(obj) : [];
    if (opts.editable && FS.tagstyles) head.appendChild(el('button', { class: 'lnk tag-btn', 'data-test': 'marker-btn', title: 'Chart markers, text markup tags and columns in this chart: show, hide, style (a marker can style its whole row, a column its cells); visual filters', onclick: (e) => FS.tagstyles.examplePopover(e.currentTarget, spec, obj, Object.assign({}, opts, { markers: true, fullChart: full })) }, '⚑' + (markersHere.length + tagsHere.length ? ' ' + (markersHere.length + tagsHere.length) : '')));
    if (opts.editable && !opts.overlay) head.appendChild(el('button', { class: 'lnk', 'data-test': 'collapse-obj', title: 'Collapse to a chip', onclick: () => FS.interlinear.setCollapsed(spec, opts, true) }, '⤡'));
    if (opts.editable && opts.inCell && opts.editCell && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Edit the cell’s text', onclick: () => opts.editCell() }, '✎'));
    if (opts.editable && !opts.overlay && opts.duplicate) head.appendChild(el('button', { class: 'lnk', title: 'Duplicate this object', onclick: () => opts.duplicate() }, '⧉'));
    if (opts.editable && !opts.overlay && opts.remove) head.appendChild(el('button', { class: 'lnk danger', title: 'Remove this object…', onclick: async (e) => { if (await FS.confirmAt(e.currentTarget, 'Remove this chart from the note? (Undo brings it back.)', 'Remove')) { FS.interlinear.closeOverlay(); opts.remove(); } } }, '🗑'));
    if (!opts.context && spec.seg) head.appendChild(el('button', { class: 'lnk', title: 'See the whole chart', onclick: () => wholeChart(spec, obj) }, '⊡ Whole chart'));
    if (!opts.inCell) head.appendChild(el('button', { class: 'lnk', title: 'Copy as a tab-separated grid (headers, rows, notes)', onclick: () => { FS.copyText(chartTsv(spec, obj)); FS.toast('Copied as TSV'); } }, '⎘ TSV'));
    if (obj.url) head.appendChild(el('a', { href: obj.url, title: 'Open the text in FieldWorks (its Text Chart tab)', onclick: (e) => { e.preventDefault(); FS.interlinear.openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    if (opts.editable && !opts.inCell) head.appendChild(el('button', { class: 'lnk', 'data-test': 'chart-view', title: flat ? 'Show the chart columns' : 'One column: each row in one cell, its words labelled with their columns', onclick: () => { spec.extra = spec.extra || {}; if (flat) delete spec.extra.view; else spec.extra.view = 'flat'; change(); } }, flat ? '▦ Columns' : '▤ One column'));
    if (opts.editable && !opts.inCell && !isGroups(spec) && ((full.template && full.template.columns) || []).some((c) => (c.path || []).length)) head.appendChild(el('button', { class: 'lnk', 'data-test': 'chart-view-groups', title: 'The header groups only: one cell per group, its columns’ words inside, labelled and styled by their own columns', onclick: () => { spec.extra = spec.extra || {}; spec.extra.view = 'groups'; change(); } }, '▥ Groups'));
    if (opts.editable) head.appendChild(el('button', { class: 'lnk', 'data-test': 'chart-menu', title: 'Options', onclick: (e) => chartMenu(e.currentTarget, spec, opts, full) }, '⋯'));
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
    const playBtn = (segs, title, cls, mark) => el('button', { class: 'seg-play ' + (cls || ''), 'data-test': cls || 'chart-play', title, onclick: (e) => { e.stopPropagation(); play(segs, e.currentTarget); } }, '▶', mark ? el('small', {}, mark) : null);
    // ▶§ a whole SENTENCE (the rows sharing a number: 4a, 4b, 4c) and ▶¶ a whole PARAGRAPH (up to
    // a row that ends one), on their first row (Seth, 2026-10-18: "play buttons for paragraphs
    // and sentences … a play button for 4, not just for 4a, 4b, 4c")
    const groups = playGroups(rows, obj.segments);
    const table = el('table', { class: 'tchart' + (vern.rtl ? ' rtl' : '') });
    const extraCols = (free === 'col' ? 1 : 0) + (notesOn ? 1 : 0) + xcols.length;
    // one <col> per table column, keyed like `cw=`; a sized column keeps its width, the rest lay
    // out as they please; the table grows past the pane when the widths say so (it scrolls)
    const widths = colWidths(spec);
    // a chart note's custom columns sit LEFT or RIGHT of the FLEx columns (Seth, 2026-10-18: "freeze
    // columns … for custom columns, on either or both sides of the chart"); `xi` is each one's key
    const xL = xcols.map((xc, i) => Object.assign({ xi: i }, xc)).filter((xc) => xc.side === 'left');
    const xR = xcols.map((xc, i) => Object.assign({ xi: i }, xc)).filter((xc) => xc.side !== 'left');
    const colKeys = ['lab'].concat(xL.map((xc) => 'x' + xc.xi), cols.map((c) => String(c.n)), xR.map((xc) => 'x' + xc.xi), free === 'col' ? ['free'] : [], notesOn ? ['notes'] : []);
    // frozen columns (sticky inside .chart-scroll): the row labels always, a custom column when it says so
    const frozen = new Map([['lab', 'l']]);
    for (const xc of xL) if (xc.frozen) frozen.set('x' + xc.xi, 'l');
    for (const xc of xR) if (xc.frozen) frozen.set('x' + xc.xi, 'r');
    const frz = (node, key) => { if (frozen.has(key)) { node.dataset.frz = frozen.get(key); node.dataset.ck = key; } return node; };
    const colEls = new Map();
    const colgroup = el('colgroup');
    for (const k of colKeys) { const c = el('col', { dataset: { key: k } }); if (widths.has(k)) c.style.width = widths.get(k) + 'px'; colEls.set(k, c); colgroup.appendChild(c); }
    table.appendChild(colgroup);
    if (widths.size) table.classList.add('sized');
    const resizer = (th, key) => {
      if (!opts.editable) return;
      const grip = el('span', { class: 'col-rs', title: 'Drag to resize this column; double-click to let it size itself', 'data-test': 'col-rs-' + key });
      grip.addEventListener('click', (e) => e.stopPropagation());
      grip.addEventListener('dblclick', (e) => { e.stopPropagation(); widths.delete(key); setColWidths(spec, widths); change(); });
      grip.addEventListener('mousedown', (e) => {
        e.preventDefault(); e.stopPropagation();
        const col = colEls.get(key);
        const startX = e.clientX, startW = th.getBoundingClientRect().width;
        const scroller = box.querySelector('.chart-scroll');
        let w = startW;
        const move = (ev) => {
          w = Math.max(40, startW + ev.clientX - startX);
          col.style.width = w + 'px';
          table.classList.add('sized');
          if (scroller) { const r = scroller.getBoundingClientRect(); if (ev.clientX > r.right - 24) scroller.scrollLeft += 12; }   // past the right edge: scroll along
        };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); document.body.classList.remove('col-resizing'); widths.set(key, Math.round(w)); setColWidths(spec, widths); change(); };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
        document.body.classList.add('col-resizing');
      });
      th.appendChild(grip);
    };
    if (headers) {
      const thead = el('thead');
      const hrows = headerRows(cols);
      hrows.forEach((hr, hi) => {
        const tr = el('tr', { class: hi === hrows.length - 1 ? 'th-cols' : 'th-groups' });
        if (hi === 0) {
          tr.appendChild(frz(el('th', { class: 'th-lab', rowspan: hrows.length }, timedAll.length && starts.size ? playBtn(timedAll, 'Play the lines of these rows', 'chart-play-all') : null, '#'), 'lab'));
          for (const xc of xL) { const th = frz(el('th', { class: 'th-x th-x-' + xc.kind + ' th-x-left', rowspan: hrows.length, dataset: { x: xc.key } }, xc.head ? xc.head() : xc.name), 'x' + xc.xi); resizer(th, 'x' + xc.xi); tr.appendChild(th); }
        }
        for (const h of hr) {
          const th = el('th', { colspan: h.span > 1 ? h.span : null, class: h.col ? 'th-col' : 'th-group', title: h.col ? ((h.col.path || []).concat([h.col.name]).join(' › ') + (h.col.abbr && h.col.abbr !== h.col.name ? ' (' + h.col.abbr + ')' : '')) : h.text, dataset: h.col ? { col: h.col.n } : null }, h.text);
          if (h.col && opts.editable) th.addEventListener('click', (e) => stylePopover(e.currentTarget, spec, { col: h.col.n }, opts, 'column ' + h.col.name, null, [{ label: 'Hide this column', test: 'hide-col', fn: () => { const on = visibleColumns(spec, obj).filter((c) => c.n !== h.col.n); if (!on.length) return; spec.extra = spec.extra || {}; spec.extra.cols = on.map((c) => 'c' + c.n).join(','); change(); } }, { label: 'Style this column everywhere… (⚑)', test: 'style-col', fn: () => { const b = box.querySelector('[data-test=marker-btn]'); if (b) b.click(); } }]));
          if (h.col && colLooks.has(h.col.n) && !groupOfLook(colLooks.get(h.col.n))) applyColumnLook(th, colLooks.get(h.col.n), true);
          if (!h.col && groupLooks.has(normKey(h.text))) applyColumnLook(th, groupLooks.get(normKey(h.text)), true);
          if (h.col) resizer(th, String(h.col.n));
          tr.appendChild(th);
        }
        if (hi === 0) {
          for (const xc of xR) { const th = frz(el('th', { class: 'th-x th-x-' + xc.kind, rowspan: hrows.length, dataset: { x: xc.key } }, xc.head ? xc.head() : xc.name), 'x' + xc.xi); resizer(th, 'x' + xc.xi); tr.appendChild(th); }
          if (free === 'col') { const th = el('th', { class: 'th-free', rowspan: hrows.length }, 'Free'); resizer(th, 'free'); tr.appendChild(th); }
          if (notesOn) { const th = el('th', { class: 'th-notes', rowspan: hrows.length }, 'Notes'); resizer(th, 'notes'); tr.appendChild(th); }
        }
        thead.appendChild(tr);
      });
      table.appendChild(thead);
    }
    const tbody = el('tbody');
    const runs = freeRuns(rows);
    const runStart = new Map(runs.map((r) => [r.from, r]));
    const runEnd = new Map(runs.map((r) => [r.to, r]));
    const movedParts = [];                   // {part, home}: every moved-text marker, for the word groups it points at
    const wordGroups = new Map();
    for (const r of rows) for (const c of r.cells || []) if (c.kind === 'words') wordGroups.set(c.guid, { row: r, cell: c });
    const movedTargets = new Set();
    for (const r of rows) for (const c of r.cells || []) if (c.kind === 'moved' && c.target) movedTargets.add(c.target);

    let lastCrow = null;                     // the previous row's <tr>, for a `join`
    rows.forEach((row, ri) => {
      // the sentence / paragraph boundary goes UNDER the free translation row when one follows
      // this row (Seth, 2026-10-18), else under the row itself
      const freeAfter = free === 'row' && runEnd.has(ri) ? freeText(obj, runEnd.get(ri).segs, true) : [];
      const bound = (row.endSent ? ' end-sent' : '') + (row.endPara ? ' end-para' : '');
      const tr = el('tr', { class: 'crow cl-' + (row.clause || 'normal') + (freeAfter.length ? '' : bound) + (row.depStart ? ' dep-start' : '') + (row.depEnd ? ' dep-end' : ''), dataset: { row: row.n, label: row.label } });
      if (opts.rowDecor) {
        const d = opts.rowDecor(row) || {};
        if (d.style) Object.assign(tr.style, d.style);
        for (const c of d.classes || []) if (c !== 'join-up' || lastCrow) tr.classList.add(c);   // the first row has nothing above to join
        // a rule's `join` (chartnote.js): no line between this row and the one above, the style on both
        if (d.classes && d.classes.includes('join-up') && lastCrow) { lastCrow.classList.add('join-down'); if (d.joinStyle) Object.assign(lastCrow.style, d.joinStyle); Object.assign(tr.style, d.joinStyle || {}); }
      }
      lastCrow = tr;
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
      // a clause TYPE's look (Seth, 2026-10-19: dependent / speech / song clauses as visual filters): the whole row
      if (row.clause && row.clause !== 'normal') {
        const lk = pseudoLook('clause:' + row.clause, obj, spec);
        if (lk && lk.styled && !lk.hide) {
          tr.classList.add('clause-styled');
          if (lk.bg) tr.style.background = rgba(lk.bg, 0.45);
          if (lk.c) tr.style.color = lk.c;
          if (lk.b) tr.style.fontWeight = '700';
          if (lk.i) tr.style.fontStyle = 'italic';
          if (lk.u) tr.style.textDecoration = 'underline';
        }
      }
      const g = groups.get(ri) || {};
      const lab = el('th', { class: 'rlab', title: 'Row ' + row.label + (row.clause && row.clause !== 'normal' ? ' — ' + row.clause + ' clause' : '') + (row.endSent ? '; ends the sentence' : '') + (row.endPara ? '; ends the paragraph' : '') + (opts.editable ? '. Click to style the row.' : '') },
        g.para ? playBtn(g.para.segs, 'Play the paragraph (rows ' + g.para.label + ')', 'chart-play-para', '¶') : null,
        g.sent ? playBtn(g.sent.segs, 'Play sentence ' + g.sent.name + ' (rows ' + g.sent.label + ')', 'chart-play-sent', '§') : null,
        (starts.get(ri) || []).map((sg) => playBtn([sg], 'Play line ' + (sg.label || sg.n) + ' (' + FS.fmtTime(sg.begin) + '–' + FS.fmtTime(sg.end) + ')', 'chart-play')), row.label);
      if (opts.editable) lab.addEventListener('click', (e) => stylePopover(e.currentTarget, spec, { row: row.n }, opts, 'row ' + row.label));
      tr.appendChild(frz(lab, 'lab'));
      for (const xc of xL) tr.appendChild(frz(el('td', { class: 'xcell xcell-' + xc.kind + ' xcell-left', dataset: { x: xc.key, row: row.n } }, xc.cell(row, obj)), 'x' + xc.xi));
      for (const slot of layoutRow(row, cols, flat ? null : allCols)) {
        const cellStyles = R.chartStylesFor(index, row.n, slot.col.n, 0, '');
        const segsHere = [...new Set(slot.parts.filter((p) => p.kind === 'words' && p.seg).flatMap((p) => { const a = []; for (let n = p.seg; n <= (p.segTo || p.seg); n++) a.push(n); return a; }))];
        const td = el('td', { class: 'ccell' + (slot.parts.length ? '' : ' empty'), colspan: slot.span > 1 ? slot.span : null, dataset: { row: row.n, col: slot.col.n, segs: segsHere.length ? segsHere.join(' ') : null } });
        const unit = colLooks.has(slot.col.n) ? unitOf(cols.indexOf(slot.col), slot.span) : null;
        // a MERGED cell (Seth, 2026-10-19): the neighbour's look round the owner's, when it has a rule of its own
        const mergedPart = slot.span > 1 ? slot.parts.find((p) => mergesAfter(p) || mergesBefore(p)) : null;
        const nbCol = mergedPart ? partColumns(mergedPart, allCols, spec, true)[1] : null;
        const nbLook = nbCol && colLooks.has(nbCol.n) && colLooks.get(nbCol.n).styled && (!unit || groupOfLook(colLooks.get(nbCol.n)) !== unit.group) ? colLooks.get(nbCol.n) : null;
        let content = td;
        if (nbLook) { applyColumnLook(td, nbLook, false, null); td.classList.add('cmerged'); content = el('div', { class: 'cmerge-in' }); td.appendChild(content); if (colLooks.has(slot.col.n)) applyColumnLook(content, unit ? groupLooks.get(unit.group) : colLooks.get(slot.col.n), false, null); }
        else if (colLooks.has(slot.col.n)) applyColumnLook(td, unit ? groupLooks.get(unit.group) : colLooks.get(slot.col.n), false, unit);
        applyCellStyles(td, cellStyles);        // the user's own cell styles win over the column's
        // the one-column view boxes the parts of ONE chart cell together (Seth, 2026-10-18: a
        // marker "should be inside the same border as the cell they apply to"); the cells of a
        // header group styled as a group share ONE box (Seth, 2026-10-19)
        let group = null;
        // lining up on a column (Seth, 2026-10-19): left of the axis, the aligned run, the rest
        const onAligned = (p) => partColumns(p, allCols, spec).some((c) => alignSet.has(c.n));
        const aligning = flat && alignSet.size && slot.parts.some((p) => p.srcCol && onAligned(p));
        let grid = null, zone = 'l', zones = null;
        if (aligning) { zones = { l: el('span', { class: 'al-l' }), a: el('span', { class: 'al-a' }), r: el('span', { class: 'al-r' }) }; grid = el('div', { class: 'al-grid' }, zones.l, zones.a, zones.r); content.appendChild(grid); }
        const into = (p) => { if (!aligning) return content; const on = !!(p.srcCol && onAligned(p)); if (zone === 'l' && on) zone = 'a'; else if (zone === 'a' && !on) zone = 'r'; return zones[zone]; };
        const colsOf = (p) => partColumns(p.srcCol ? p : Object.assign({}, p, { srcCol: slot.col }), allCols, spec).map((c) => c.n);
        for (const part of slot.parts) {
          if (part.kind === 'moved') movedParts.push({ part, home: part.srcCol || slot.col });
          const mine = colsOf(part);
          const cellHasWords = slot.parts.some((q) => q.kind === 'words' && colsOf(q).some((n) => mine.includes(n)));
          const node = renderPart(part, row, part.srcCol || slot.col, obj, spec, opts, { lines, index, vern, anal, wordGroups, movedTargets, tbody, showTextTags, cellHasWords });
          const host = into(part);
          if (!(flat && part.srcCol)) { addPart(host, node, chipMode); continue; }
          const key = flatUnitKey(part.srcCol, obj, spec);
          if (!group || group.key !== key || group.host !== host) { if (group) group.finish(); group = flatWrap(part, obj, spec, key, chipMode); group.host = host; host.appendChild(group.wrap); }
          group.add(node, part);
        }
        if (group) group.finish();
        if (opts.editable) td.addEventListener('click', (e) => { if (e.target.closest('.cw, .cclause, .ctag, .cmoved, button, a')) return; stylePopover(td, spec, { row: row.n, col: slot.col.n }, opts, 'row ' + row.label + ', ' + slot.col.name); });
        if (free === 'tip') td.addEventListener('click', (e) => { if (e.target.closest('button, a')) return; showTip(box, obj, rowSegs(row), row); });
        tr.appendChild(td);
      }
      for (const xc of xR) tr.appendChild(frz(el('td', { class: 'xcell xcell-' + xc.kind, dataset: { x: xc.key, row: row.n } }, xc.cell(row, obj)), 'x' + xc.xi));
      if (free === 'col' && runStart.has(ri)) {
        const run = runStart.get(ri);
        const t = freeText(obj, run.segs, true);
        tr.appendChild(el('td', { class: 'cfree', rowspan: run.to > run.from ? run.to - run.from + 1 : null, lang: anal.tag || null, title: 'Free translation of ' + (run.segs.length ? 'segment' + (run.segs.length > 1 ? 's ' : ' ') + run.segs.map((n) => (segsByN(obj).get(n) || { label: n }).label).join(', ') : 'this row') }, t.join(' ')));
      }
      if (notesOn) tr.appendChild(el('td', { class: 'cnotes', lang: anal.tag || null }, row.notes || ''));
      tbody.appendChild(tr);
      if (freeAfter.length) {
        const run = runEnd.get(ri);
        const t = freeAfter;
        // the custom columns keep a cell of their own in the translation row (a frozen one would
        // otherwise cover the start or the end of the text while the chart is scrolled)
        tbody.appendChild(el('tr', { class: 'cfree-row' + bound }, frz(el('th', { class: 'rlab' }), 'lab'),
          xL.map((xc) => frz(el('td', { class: 'xcell xcell-left xcell-blank' }), 'x' + xc.xi)),
          el('td', { colspan: cols.length + extraCols - xcols.length, lang: anal.tag || null }, el('span', { class: 'cfree-text' }, t.join(' ')), el('span', { class: 'cfree-rows', title: 'The chart rows this translation covers' }, rowsLabel(rows, run.from, run.to))),
          xR.map((xc) => frz(el('td', { class: 'xcell xcell-blank' }), 'x' + xc.xi))));
      }
    });
    if (!rows.length) tbody.appendChild(el('tr', {}, el('td', { colspan: cols.length + 1 + extraCols, class: 'seg-empty' }, 'No rows in this range.')));
    applyMovedLooks(tbody, obj, spec, movedParts, wordGroups);
    table.appendChild(tbody);
    box.appendChild(el('div', { class: 'chart-scroll' }, table));
    requestAnimationFrame(() => { if (box.isConnected) placeFrozen(table, colKeys, colEls, frozen); });
    if (alignSet.size) { table.classList.add('al-' + alignEdge(spec)); requestAnimationFrame(() => { if (box.isConnected) alignFlat(table); }); }
    if (chipMode === 'wrap') requestAnimationFrame(() => { if (box.isConnected) placeChipLines(table); });
    // SENTENCE / PARAGRAPH BOUNDARIES as visual-filter targets (Seth, 2026-10-19: "custom style sentence
    // boundaries and paragraph boundaries"): the line under an end-sent / end-para row (or the free
    // translation row that carries it) takes the rule's style, thickness and colour, or goes away
    for (const [kind, cls, v] of [['boundary:sentence', 'end-sent', '--bnd-s'], ['boundary:paragraph', 'end-para', '--bnd-p']]) {
      const lk = pseudoLook(kind, obj, spec);
      if (!lk || (!lk.styled && !lk.hide)) continue;
      for (const tr of tbody.querySelectorAll('tr.' + cls)) {
        if (lk.hide) { tr.style.setProperty(v, '1px solid var(--border-soft)'); tr.classList.add('bnd-off'); continue; }
        tr.style.setProperty(v, (lk.bw || (cls === 'end-para' ? 3 : 2)) + 'px ' + (lk.bs || (cls === 'end-para' ? 'double' : 'solid')) + ' ' + (lk.bc || lk.bg || 'currentColor'));
        tr.classList.add('bnd-styled');
      }
    }
    if (headers && !opts.inCell) requestAnimationFrame(() => { if (box.isConnected) wireStickyHead(box, table); });
    if (free === 'tip') box.appendChild(el('div', { class: 'chart-tip muted small', 'data-test': 'chart-tip' }, 'Click a cell to see its free translation here.'));
    if (opts.context) box.classList.add('context');
    return box;
  }

  const ZOOM_MIN = 50, ZOOM_MAX = 200, ZOOM_STEP = 10;
  const zoomOf = (spec) => { const z = parseInt(spec.extra && spec.extra.zoom, 10); return z >= ZOOM_MIN && z <= ZOOM_MAX ? z : 100; };
  function setZoom(spec, z) {
    spec.extra = spec.extra || {};
    z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(z / ZOOM_STEP) * ZOOM_STEP));
    if (z === 100) delete spec.extra.zoom; else spec.extra.zoom = String(z);
    return z;
  }
  /* The sentence and paragraph play groups by row index: a SENTENCE is the rows sharing a label
   * number (4a, 4b, 4c → "4"; FLEx numbers rows by sentence, letters the clauses), a PARAGRAPH runs
   * up to a row that ends one. A group gets a button on its first row when it spans several rows
   * (a one-row sentence IS its line) and holds timed lines. → Map(rowIndex → {sent?, para?}) */
  const sentNo = (r) => (/^\d+/.exec(r.label || '') || [r.label || ''])[0];
  function playGroups(rows, segments) {
    const timed = new Map((segments || []).filter((s) => s.begin != null && s.end != null).map((s) => [s.n, s]));
    const segsOf = (list) => { const seen = new Set(); const out = []; for (const r of list) for (const n of rowSegs(r)) if (!seen.has(n) && timed.has(n)) { seen.add(n); out.push(timed.get(n)); } return out; };
    const out = new Map();
    const put = (i, k, v) => { if (!out.has(i)) out.set(i, {}); out.get(i)[k] = v; };
    const label = (a, b) => (a === b ? rows[a].label : rows[a].label + '\u2013' + rows[b].label);
    let i = 0;
    while (i < rows.length) {
      const name = sentNo(rows[i]);
      let j = i;
      while (j + 1 < rows.length && sentNo(rows[j + 1]) === name) j++;
      if (j > i) { const segs = segsOf(rows.slice(i, j + 1)); if (segs.length) put(i, 'sent', { name, label: label(i, j), segs }); }
      i = j + 1;
    }
    if (rows.some((r) => r.endPara)) {
      let from = 0;
      rows.forEach((r, k) => {
        if (!r.endPara && k < rows.length - 1) return;
        const names = new Set(rows.slice(from, k + 1).map(sentNo));
        if (names.size > 1) { const segs = segsOf(rows.slice(from, k + 1)); if (segs.length) put(from, 'para', { label: label(from, k), segs }); }
        from = k + 1;
      });
    }
    return out;
  }
  /* A word group in the one-column view: wrapped with its column's abbreviation and the look the
   * column's visual-filter rules give it (`column:<Group/Name>` in tagstyles, the same rules that
   * style chart columns drawn on an example). */
  /* The look a column's rules give it (`column:<Group/Name>` in tagstyles, resolved for this
   * chart's text and the current note / tab / folder / project), or null when there is no rule
   * machinery. */
  function columnLook(col, obj, spec) {
    if (!(FS.tagstyles && FS.tagstyles.resolve)) return null;
    const path = (col.path || []).concat([col.name]);
    if (FS.tagstyles.noteColumn) FS.tagstyles.noteColumn(col);
    try {
      const look = FS.tagstyles.resolve({ guid: 'column:' + (col.guid || col.name), name: path.join('/'), abbr: col.abbr || col.name, group: (col.path || [])[(col.path || []).length - 1] || '', path: col.path || [], column: true, fore: '', back: '' }, spec || null, Object.assign({}, FS.tagstyles.context(), { text: obj.text || '' }));
      // only a look somebody asked for counts (the palette's default colour is not a style)
      look.styled = !!(look.styleVia && look.styleVia.kind !== 'default');
      return look;
    } catch (e) { return null; }
  }
  const normKey = (s) => String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
  /* The header group a look comes from, when its rule is `column:group:<name>` (else ''). */
  const groupOfLook = (look) => { const k = look && look.styledBy || ''; return k.startsWith('column:group:') ? k.slice(13) : ''; };
  /* A header GROUP's own look (`column:group:<name>` rules), resolved for the group itself so every
   * cell of the unit, in either layout, wears the same colour; `col` is any column under it. */
  function groupLook(gNorm, col, obj, spec) {
    if (!(FS.tagstyles && FS.tagstyles.resolve)) return null;
    const path = col.path || [];
    const i = path.findIndex((p) => normKey(p) === gNorm);
    if (i < 0) return null;
    try {
      const look = FS.tagstyles.resolve({ guid: 'column:group:' + path[i], name: 'group:' + path[i], abbr: '', group: path[i], path: path.slice(0, i + 1), column: true, isGroup: true, fore: '', back: '' }, spec || null, Object.assign({}, FS.tagstyles.context(), { text: obj.text || '' }));
      look.styled = !!(look.styleVia && look.styleVia.kind !== 'default');
      return look;
    } catch (e) { return null; }
  }
  /* The look of a chart-structure item (a clause type, the [2a] markers, moved text), or null. */
  function pseudoLook(key, obj, spec) {
    if (!(FS.tagstyles && FS.tagstyles.structureItem)) return null;
    const item = FS.tagstyles.structureItem(key);
    if (!item) return null;
    try {
      const look = FS.tagstyles.resolve(item, spec || null, Object.assign({}, FS.tagstyles.context(), { text: obj.text || '' }));
      look.styled = !!(look.styleVia && look.styleVia.kind !== 'default');
      return look;
    } catch (e) { return null; }
  }
  /* A column's look on one of its cells (or its heading): tile / marker → a tint, box → a border,
   * colour, bold / italic / underline. Brackets are drawn in the one-column view and on examples.
   * `unit` ({group, first, last}) = the cell is part of a header group's run: the box is drawn
   * round the RUN (top and bottom on every cell, the sides on its ends) and the inner cell
   * borders go, so the group reads as one. */
  function applyColumnLook(node, look, heading, unit) {
    if (!look || !look.styled) return;
    node.classList.add('col-styled');
    const bg = look.tile ? (look.tc || look.bg) : look.hl ? look.bg : '';
    if (bg) node.style.background = rgba(bg, heading ? 0.6 : look.tile ? 0.35 : 0.5);
    if (unit) { node.classList.add('cgrp'); if (unit.first) node.classList.add('cgrp-first'); if (unit.last) node.classList.add('cgrp-last'); }
    if (look.box) {
      const w = (look.bw || 2) + 'px', col = look.bc || look.bg || 'currentColor';
      if (unit) {
        const parts = ['inset 0 ' + w + ' 0 0 ' + col, 'inset 0 -' + w + ' 0 0 ' + col];
        if (unit.first) parts.push('inset ' + w + ' 0 0 0 ' + col);
        if (unit.last) parts.push('inset -' + w + ' 0 0 0 ' + col);
        node.style.boxShadow = parts.join(', ');
      } else {
        node.style.boxShadow = 'inset 0 0 0 ' + w + ' ' + col;
        if (look.bs && look.bs !== 'solid') node.style.outline = w + ' ' + look.bs + ' ' + col;
      }
    }
    if (look.c && !heading) node.style.color = look.c;
    if (look.b) node.style.fontWeight = '700';
    if (look.i) node.style.fontStyle = 'italic';
    if (look.u) node.style.textDecoration = 'underline';
  }
  /* A look on a word group (a `.cwords`): tint, border, brackets, colour, B I U. */
  function applyGroupLook(g, look) {
    const bg = look.tile ? (look.tc || look.bg) : look.hl ? look.bg : '';
    if (bg) g.style.background = rgba(bg, look.tile ? 0.45 : 0.6);
    if (look.box) { g.style.outline = (look.bw || 2) + 'px ' + (look.bs || 'solid') + ' ' + (look.bc || look.bg || 'currentColor'); g.style.outlineOffset = '1px'; }
    if (look.c) g.style.color = look.c;
    if (look.b) g.style.fontWeight = '700';
    if (look.i) g.style.fontStyle = 'italic';
    if (look.u) g.style.textDecoration = 'underline';
    const B = FS.tagstyles && FS.tagstyles.BRACKETS, br = look.br && B && B[look.br];
    if (br) { g.insertBefore(el('span', { class: 'cw-br' }, br[0]), g.firstChild); g.appendChild(el('span', { class: 'cw-br' }, br[1])); }
  }
  /* MOVED TEXT (Seth, 2026-10-19: "detect clauses marked as pre-posed from or postposed from and
   * highlight those cells … same as the column they're preposed from (so like 'Preposed Subj') or
   * same as the column they're preposed to (with some kind of preposed marker plus label)"): every
   * moved-text marker names the word group that was moved and sits in the column it CAME FROM;
   * the word group (wherever it is charted, in either layout) gets the rule's look — its own, the
   * home column's (`ms=from`) or the column it sits in (`ms=to`) — and a label: ‹‹ / ›› plus the
   * home column's abbreviation (default), the current column's (`ml=to`), or none (`ml=off`). */
  function applyMovedLooks(tbody, obj, spec, moved, wordGroups) {
    if (!moved.length) return;
    const colsByN = new Map((((obj.template || {}).columns) || []).map((c) => [c.n, c]));
    for (const m of moved) {
      const look = pseudoLook(m.part.preposed ? 'moved:preposed' : 'moved:postposed', obj, spec);
      if (!look || !look.styled || look.hide) continue;
      const g = tbody.querySelector('.cwords[data-group="' + m.part.target + '"]');
      if (!g || g.classList.contains('moved-styled')) continue;
      g.classList.add('moved-styled');
      const tgt = wordGroups.get(m.part.target);
      const cur = tgt ? (tgt.cell.srcCol || colsByN.get(tgt.cell.colN)) : null, home = m.home;   // srcCol: the one-column view's cells sit on the "Text" column
      let src = look;
      if (look.ms === 'from' && home) { const cl = columnLook(home, obj, spec); if (cl && cl.styled) src = cl; }
      else if (look.ms === 'to' && cur) { const cl = columnLook(cur, obj, spec); if (cl && cl.styled) src = cl; }
      applyGroupLook(g, src);
      if (look.ml !== 'off') {
        const col = look.ml === 'to' ? cur : home;
        g.appendChild(el('sub', { class: 'moved-lab', title: (m.part.preposed ? 'Preposed from ' : 'Postposed from ') + (home ? (home.path || []).concat([home.name]).join(' › ') : '?') }, (m.part.preposed ? '‹‹ ' : '›› ') + (col ? (col.abbr || col.name) : '')));
      }
    }
  }
  /* What a part shares a box with in the one-column view: its column, or — when the column's look
   * comes from a header group's rule — that group (Seth, 2026-10-19: the group's columns as one). */
  function flatUnitKey(col, obj, spec) {
    if (obj.grouped) return 'c:' + col.n;    // the groups view: the cell already is the group
    const lk = columnLook(col, obj, spec);
    const g = lk && lk.styled ? groupOfLook(lk) : '';
    return g ? 'g:' + g : 'c:' + col.n;
  }
  function flatWrap(part, obj, spec, key, chipMode) {
    const col = part.srcCol;
    const asGroup = !!(key && key.startsWith('g:'));
    const bothCols = partColumns(part, (obj.template && obj.template.srcColumns) || [], spec, true);
    const nb = bothCols[1] || null;
    const look = asGroup ? (groupLook(key.slice(2), col, obj, spec) || columnLook(col, obj, spec)) : columnLook(col, obj, spec);
    const groupName = asGroup ? ((col.path || []).find((p) => normKey(p) === key.slice(2)) || key.slice(2)) : '';
    const path = asGroup ? (col.path || []).slice(0, (col.path || []).findIndex((p) => normKey(p) === key.slice(2)) + 1) : (col.path || []).concat([col.name]);
    const wrap = el('span', { class: 'cflat-g' + (asGroup ? ' cflat-group' : ''), dataset: { col: asGroup ? null : col.n, group: asGroup ? groupName : null }, title: path.join(' \u203a ') });
    if (look && look.hide) wrap.classList.add('hidden');
    const B = FS.tagstyles && FS.tagstyles.BRACKETS;
    const br = look && look.br && B && B[look.br];
    if (br) wrap.appendChild(el('span', { class: 'cflat-br' }, br[0]));
    const body = el('span', { class: 'cflat-body' });
    wrap.appendChild(body);
    if (br) wrap.appendChild(el('span', { class: 'cflat-br' }, br[1]));
    const labelsOn = !(spec.extra && spec.extra.collab === 'off') && !(look && look.label === false);
    const label = labelsOn ? el('sub', { class: 'cflat-lab' }, asGroup ? groupName : (col.abbr || col.name) + (nb ? '+' + (nb.abbr || nb.name) : '')) : null;
    if (label) wrap.appendChild(label);
    // inside a group's box each column's parts are followed by that column's own small label
    let lastCol = null;
    const colLabel = () => { if (asGroup && labelsOn && lastCol) body.appendChild(el('sub', { class: 'cflat-lab cflat-sublab' }, lastCol.abbr || lastCol.name)); };
    // a box whose every chip is hidden draws nothing at all — no tile, border or label (Seth,
    // 2026-10-19: "if whatever chips were in that cell are invisible, then the cell border, tile
    // or whatever shouldn't draw")
    let shown = false;
    const add = (node, p) => { if (asGroup && lastCol && p.srcCol && p.srcCol.n !== lastCol.n) colLabel(); lastCol = p.srcCol || lastCol; addPart(body, node, chipMode || 'inline'); if (p.kind === 'words') wrap.classList.add('cflat-words'); if (!node.classList.contains('hidden')) shown = true; };
    const finish = () => { colLabel(); lastCol = null; if (!shown) wrap.classList.add('cflat-void'); };
    if (look) {
      const bg = look.tile ? (look.tc || look.bg) : look.hl ? look.bg : '';
      if (bg) wrap.style.background = rgba(bg, look.tile ? 0.45 : 0.6);
      if (look.box) { wrap.style.border = (look.bw || 2) + 'px ' + (look.bs || 'solid') + ' ' + (look.bc || look.bg || 'currentColor'); wrap.style.borderRadius = '4px'; }
      if (look.c) wrap.style.color = look.c;
      if (look.b) wrap.style.fontWeight = '700';
      if (look.i) wrap.style.fontStyle = 'italic';
      if (look.u) wrap.style.textDecoration = 'underline';
    }
    // a merged part: the neighbour column's look round the owner's (Seth, 2026-10-19: "it could be either")
    const nbLook = nb && !asGroup ? columnLook(nb, obj, spec) : null;
    let outer = null;
    if (nbLook && nbLook.styled) {
      outer = el('span', { class: 'cflat-g cflat-outer', dataset: { col: nb.n }, title: (nb.path || []).concat([nb.name]).join(' \u203a ') + ' (merged)' }, wrap);
      const bg = nbLook.tile ? (nbLook.tc || nbLook.bg) : nbLook.hl ? nbLook.bg : '';
      if (bg) outer.style.background = rgba(bg, nbLook.tile ? 0.3 : 0.45);
      if (nbLook.box) { outer.style.border = (nbLook.bw || 2) + 'px ' + (nbLook.bs || 'solid') + ' ' + (nbLook.bc || nbLook.bg || 'currentColor'); outer.style.borderRadius = '5px'; }
      if (nbLook.c) outer.style.color = nbLook.c;
      const B2 = FS.tagstyles && FS.tagstyles.BRACKETS;
      const br2 = nbLook.br && B2 && B2[nbLook.br];
      if (br2) { outer.insertBefore(el('span', { class: 'cflat-br' }, br2[0]), wrap); outer.appendChild(el('span', { class: 'cflat-br' }, br2[1])); }
    }
    const finish2 = () => { finish(); if (outer && wrap.classList.contains('cflat-void')) outer.classList.add('cflat-void'); };
    return { wrap: outer || wrap, add, finish: finish2, key };
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
      const mlk = pseudoLook(part.preposed ? 'moved:preposed' : 'moved:postposed', obj, spec);
      if (mlk && mlk.hide) return el('span', { class: 'cmoved hidden', dataset: { target: part.target } });
      const m = el('span', { class: 'cmoved' + (part.preposed ? ' pre' : ' post'), title: (part.preposed ? 'Preposed' : 'Postposed') + ' text' + (words ? ': “' + words + '”' : '') + (tgt ? ' — charted in ' + (tgt.cell.colN && colName(obj, tgt.cell.colN)) + (tgt.row !== row ? ' of row ' + tgt.row.label : '') : ''), dataset: { target: part.target } }, part.preposed ? '‹‹' : '››');
      if (mlk && mlk.styled && !mlk.ms) { if (mlk.bg) { m.style.background = mlk.bg; m.style.color = mlk.fg || (FS.readableTextColor ? FS.readableTextColor(mlk.bg) : ''); m.style.borderRadius = '4px'; m.style.padding = '0 3px'; } if (mlk.b) m.style.fontWeight = '700'; }
      m.addEventListener('mouseenter', () => { const g = ctx.tbody.querySelector('.cwords[data-group="' + part.target + '"]'); if (g) g.classList.add('flash'); });
      m.addEventListener('mouseleave', () => { ctx.tbody.querySelectorAll('.cwords.flash').forEach((g) => g.classList.remove('flash')); });
      return m;
    }
    if (part.kind === 'clause') {
      const labels = part.labels && part.labels.length ? part.labels : (part.rows || []).map((g) => g.slice(0, 4));
      const text = labels.length > 1 ? labels[0] + '–' + labels[labels.length - 1] : (labels[0] || '?');
      const clk = pseudoLook('clauseref', obj, spec);
      if (clk && clk.hide) return el('span', { class: 'cclause hidden', dataset: { rows: (part.rows || []).join(' ') } });
      const c = el('span', { class: 'cclause', title: 'Dependent clause' + (labels.length > 1 ? 's ' : ' ') + labels.join(', ') + ' (click to show)', dataset: { rows: (part.rows || []).join(' ') } }, '[' + text + ']');
      if (clk && clk.styled) { if (clk.bg) { c.style.background = clk.bg; c.style.color = clk.fg || (FS.readableTextColor ? FS.readableTextColor(clk.bg) : ''); c.style.borderRadius = '4px'; c.style.padding = '0 4px'; } if (clk.b) c.style.fontWeight = '700'; if (clk.i) c.style.fontStyle = 'italic'; if (clk.u) c.style.textDecoration = 'underline'; }
      c.addEventListener('click', (e) => { e.stopPropagation(); for (const lab of labels) { const tr = ctx.tbody.querySelector('.crow[data-label="' + CSS.escape(lab) + '"]'); if (tr) { tr.classList.add('flash'); tr.scrollIntoView({ block: 'nearest' }); setTimeout(() => tr.classList.remove('flash'), 1600); } } });
      return c;
    }
    if (part.kind === 'tag') {
      const t = part.tag;
      if (!t) return el('span', { class: 'ctag missing', title: 'A chart marker whose list item is missing' }, '?');
      const look = markerLook(obj, t, spec);
      if (look.hide) return el('span', { class: 'ctag hidden', dataset: { marker: t.name }, title: t.name + ' (hidden by ' + (look.hideVia ? look.hideVia.label : 'a rule') + ')' });
      if (!markerShown(look, spec, ctx.cellHasWords !== false)) return el('span', { class: 'ctag hidden', dataset: { marker: t.name, empty: '' }, title: t.name + ' (in a cell with no words; hidden by ' + (look.emptyVia ? look.emptyVia.label : 'this chart’s settings') + ')' });
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
  function stylePopover(anchor, spec, target, opts, desc, word, actions) {
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
        for (const a of actions || []) rows.appendChild(el('button', { class: 'menu-item', 'data-test': a.test || null, onclick: () => { close(); a.fn(); } }, a.label));
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
      // layout: the chart's columns, or every row in one cell; empty columns; zoom
      const vsel = el('select', { 'data-test': 'chart-view-select', onchange: (e) => { if (e.target.value === 'flat' || e.target.value === 'groups') x.view = e.target.value; else delete x.view; change(); close(); } },
        el('option', { value: 'cols', selected: viewOf(spec) === 'cols' }, 'The chart’s columns'), el('option', { value: 'groups', selected: isGroups(spec) }, 'The header groups: one cell per group'), el('option', { value: 'flat', selected: viewOf(spec) === 'flat' }, 'One column: each row in one cell'));
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Layout'), vsel));
      // merged cells (Seth, 2026-10-19: "it could be either" column)
      const msel = el('select', { 'data-test': 'chart-merge-select', title: 'A cell merged with its empty neighbour could belong to either column', onchange: (e) => { if (e.target.value === 'both') delete x.merge; else x.merge = e.target.value; change(); } },
        el('option', { value: 'both', selected: mergeMode(spec) === 'both' }, 'both columns: searches, rules and the line-up match either; the neighbour’s look round the owner’s'),
        el('option', { value: 'lookowner', selected: mergeMode(spec) === 'lookowner' }, 'both for searches and rules; drawn with the owner column’s look only'),
        el('option', { value: 'owner', selected: mergeMode(spec) === 'owner' }, 'the owner column only'));
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Merged cells'), msel));
      // marker chips (Seth, 2026-10-19: "on a separate line … wrap at word width")
      const csel = el('select', { 'data-test': 'chart-chips-select', title: 'Where a cell’s chart-marker chips go', onchange: (e) => { if (e.target.value === 'inline') delete x.chips; else x.chips = e.target.value; change(); } },
        el('option', { value: 'inline', selected: chipsMode(spec) === 'inline' }, 'beside the words'), el('option', { value: 'line', selected: chipsMode(spec) === 'line' }, 'on a line of their own under the words'), el('option', { value: 'wrap', selected: chipsMode(spec) === 'wrap' }, 'on their own line, no wider than the words (they wrap)'));
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Marker chips'), csel));
      const ecb = el('input', { type: 'checkbox', checked: x.empty === 'off', 'data-test': 'chart-hide-empty' });
      ecb.addEventListener('change', () => { if (ecb.checked) x.empty = 'off'; else delete x.empty; change(); });
      const mcb = el('input', { type: 'checkbox', checked: x.emptymarkers !== 'off', 'data-test': 'chart-empty-markers' });
      mcb.addEventListener('change', () => { if (mcb.checked) delete x.emptymarkers; else x.emptymarkers = 'off'; change(); });
      const lcb = el('input', { type: 'checkbox', checked: x.collab !== 'off' });
      lcb.addEventListener('change', () => { if (lcb.checked) delete x.collab; else x.collab = 'off'; change(); });
      pop.appendChild(el('div', { class: 'row' }, el('label', { title: 'Leave out the columns with nothing in these rows' }, ecb, ' Hide empty columns'), isFlat(spec) ? el('label', { title: 'The column’s abbreviation under each word group' }, lcb, ' Column labels') : null));
      pop.appendChild(el('div', { class: 'row' }, el('label', { title: 'Chart markers in a cell that holds no words (a marker’s own rule in ⚑ can say otherwise)' }, mcb, ' Markers in cells with no words')));
      const zl = el('span', { class: 'zoom-val', 'data-test': 'chart-zoom' }, zoomOf(spec) + '%');
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Zoom'),
        el('button', { class: 'tog', 'data-test': 'chart-zoom-out', title: 'Smaller', onclick: () => { zl.textContent = setZoom(spec, zoomOf(spec) - ZOOM_STEP) + '%'; change(); } }, '\u2212'),
        zl,
        el('button', { class: 'tog', 'data-test': 'chart-zoom-in', title: 'Larger', onclick: () => { zl.textContent = setZoom(spec, zoomOf(spec) + ZOOM_STEP) + '%'; change(); } }, '+'),
        el('button', { class: 'lnk small', onclick: () => { zl.textContent = setZoom(spec, 100) + '%'; change(); } }, 'reset')));
      // LINE UP ON a column in the one-column / groups views (Seth, 2026-10-19)
      const allCols = (obj.template && obj.template.columns) || [];
      if (isFlat(spec) && allCols.length) {
        const on = alignedColumns(spec, obj);
        const abox = el('div', { class: 'chart-cols' });
        const writeAlign = () => { const sel = allCols.filter((c) => on.has(c.n)); if (sel.length) x.align = sel.map((c) => 'c' + c.n).join(','); else delete x.align; change(); };
        // a header GROUP lines up as one block (Seth, 2026-10-19: "either the parent column header or the daughter")
        let lastG = null;
        for (const c of allCols) {
          const g = (c.path || []).join(' › ');
          if (g && g !== lastG) {
            lastG = g;
            const members = allCols.filter((k) => (k.path || []).join(' › ') === g);
            const gcb = el('input', { type: 'checkbox', checked: members.every((k) => on.has(k.n)), 'data-test': 'chart-align-group', dataset: { group: g } });
            gcb.addEventListener('change', () => { for (const k of members) { if (gcb.checked) on.add(k.n); else on.delete(k.n); } writeAlign(); });
            abox.appendChild(el('label', { class: 'chart-col-group', title: 'Line up the whole group as one block' }, gcb, ' ', g));
          }
          const cb = el('input', { type: 'checkbox', checked: on.has(c.n), 'data-test': 'chart-align-col', dataset: { col: c.n } });
          cb.addEventListener('change', () => { if (cb.checked) on.add(c.n); else on.delete(c.n); writeAlign(); });
          abox.appendChild(el('label', { class: 'chart-col', title: 'Line up this column’s text across the rows: centred on one axis, the rest of the row to its left and right' }, cb, ' ', (c.path || []).concat([c.name]).join(' › ')));
        }
        const esel = el('select', { 'data-test': 'chart-align-edge', title: 'Which edge of the lined-up text meets the shared axis', onchange: (e) => { if (e.target.value === 'center') delete x.alignat; else x.alignat = e.target.value; change(); } },
          el('option', { value: 'center', selected: alignEdge(spec) === 'center' }, 'centred on the axis'), el('option', { value: 'left', selected: alignEdge(spec) === 'left' }, 'left edges on the axis'), el('option', { value: 'right', selected: alignEdge(spec) === 'right' }, 'right edges on the axis'));
        pop.appendChild(el('div', { class: 'row', style: { alignItems: 'flex-start' } }, el('span', { class: 'lbl', title: 'The text of these columns lines up across the rows (a run of neighbouring columns as one block)' }, 'Line up on'), el('div', {}, abox, el('div', { class: 'row' }, esel))));
      }
      // columns
      const cols = allCols;
      if (cols.length) {
        const shown = new Set(selectedColumns(spec, obj).map((c) => c.n));
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
      if (colWidths(spec).size) pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'chart-reset-widths', onclick: () => { delete x.cw; change(); close(); } }, 'Reset column widths'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(chartTsv(spec, obj)); FS.toast('Copied as TSV'); close(); } }, 'Copy as TSV'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(R.serialize(spec)); FS.toast('Embed code copied'); close(); } }, 'Copy embed code'));
      if (FS.api && FS.api.export_chart) {
        pop.appendChild(el('button', { class: 'menu-item', title: 'The shape FieldWorks itself exports (Texts & Words › Discourse Chart › Export), with GUIDs added', onclick: async () => { close(); try { const p = await FS.api.export_chart(obj.guid, 'xml', spec.seg || null); if (p) FS.toast('Saved ' + p); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Export as FLEx chart XML…'));
        pop.appendChild(el('button', { class: 'menu-item', title: 'Every row, cell and word with its GUID', onclick: async () => { close(); try { const p = await FS.api.export_chart(obj.guid, 'json', spec.seg || null); if (p) FS.toast('Saved ' + p); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Export as JSON…'));
      }
      if (FS.newChartNote && !opts.collection) pop.appendChild(el('button', { class: 'menu-item', title: 'A note that is this chart, with its own columns (choice lists, notes, rules) and these styles', onclick: () => { close(); FS.newChartNote(obj.guid, R.serialize(spec)); } }, 'Open as a chart note\u2026'));
      // another chart in this object (Seth, 2026-10-18): the view settings stay, the rows, the
      // column choice, the widths and the styles (which name rows and columns of the old chart) go
      if (FS.pickChart) pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'chart-change', title: 'Show another of the project’s charts here, with these view settings', onclick: () => {
        close();
        const retarget = (guid) => { spec.guid = guid; spec.seg = null; spec.at = null; delete x.cw; delete x.cols; R.clearStyles(spec, null); change(); };
        FS.pickChart({ title: 'Change the chart', current: spec.guid, test: 'pick-chart-change', onPick: async (c) => { try { if (opts.changeChart) await opts.changeChart(c.guid, retarget); else retarget(c.guid); } catch (e) { FS.toast(e.message, 'error'); } } });
      } }, 'Change the chart…'));
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
    obj = flatten(obj, spec);
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
      if (p.kind === 'words') return (p.words || []).map((w) => w.punct ? (w.txt || '') : lines.map((l) => lineText(w, l)).filter(Boolean).join('/')).join(' ') + (p.srcCol && !(spec.extra && spec.extra.collab === 'off') ? ' \u2039' + (p.srcCol.abbr || p.srcCol.name) + '\u203a' : '');
      if (p.kind === 'moved') { const t = wg.get(p.target); return (p.preposed ? '‹‹' : '››') + (t ? t.row.label : ''); }
      if (p.kind === 'clause') return '[' + ((p.labels || []).length > 1 ? p.labels[0] + '–' + p.labels[p.labels.length - 1] : (p.labels || ['?'])[0]) + ']';
      if (p.kind === 'tag') return '⟨' + ((p.tag && (p.tag.abbr || p.tag.name)) || '?') + '⟩';
      return '';
    };
    const runs = freeRuns(obj.rows || []);
    (obj.rows || []).forEach((row, ri) => {
      const cells = [row.label];
      for (const slot of layoutRow(row, cols, obj.flat ? null : ((obj.template && obj.template.columns) || []))) { cells.push(slot.parts.map(partText).filter(Boolean).join(' ')); for (let i = 1; i < slot.span; i++) cells.push(''); }
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
    const allC = (obj.template && obj.template.columns) || [];
    const hasWords = (r, colN) => (r.cells || []).some((c) => c.kind === 'words' && partColumns(c, allC, spec).some((k) => k.n === colN) && (c.words || []).some((w) => !w.punct));
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

  FS.chart = { renderChart, visibleColumns, selectedColumns, flatten, isFlat, isGroups, viewOf, alignedColumns, alignEdge, chipsMode, mergeMode, mergedNeighbour, partColumns, zoomOf, setZoom, playGroups, columnLook, pseudoLook, markerShown, headerRows, layoutRow, rowSegs, freeRuns, lineStarts, colWidths, setColWidths, freeText, chartGrid, chartTsv, markerLook, pivot, pivotDialog, LINE_NAMES, FREE_NAMES };
})();
