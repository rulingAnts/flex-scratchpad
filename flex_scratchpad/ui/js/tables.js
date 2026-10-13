/* tables.js — the table block: GFM pipe tables, edited in place.
 *
 *   | Form | Gloss | Example |
 *   |:-----|:-----:|--------:|
 *   | kabir | dog | {{flex:text <guid> seg=1}} |
 *   | a<br>b | … | … |
 *   {table: striped; header-col; borders light; col 2: bold, center, width 30%; row 2: bg #fff2a8}
 *
 * `<br>` is a line break inside a cell, `\|` a literal pipe; `{{flex …}}` embeds may sit inside
 * cells (the cell splitter never splits inside {{ }} or backticks). The optional {table: …}
 * line after the table carries styling, edited through popovers rather than typed. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el, esc } = FS;

  /* ------------------------------------------------------------------ parsing */
  function splitRow(line) {
    let s = line.trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
    const cells = [];
    let cur = '', depth = 0, tick = false;
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (c === '\\' && s[i + 1] === '|') { cur += '|'; i++; continue; }
      if (c === '`') tick = !tick;
      if (!tick) {
        if (c === '{' && s[i + 1] === '{') { depth++; cur += '{{'; i++; continue; }
        if (c === '}' && s[i + 1] === '}' && depth) { depth--; cur += '}}'; i++; continue; }
        if (c === '|' && !depth) { cells.push(cur.trim()); cur = ''; continue; }
      }
      cur += c;
    }
    cells.push(cur.trim());
    return cells;
  }

  function parseStyle(line) {
    const st = { flags: new Set(), cols: {}, rows: {}, spans: {} };
    const m = /^\s*\{table\s*:?\s*([^}]*)\}\s*$/.exec(line || '');
    if (!m) return st;
    for (const part of m[1].split(';')) {
      const p = part.trim();
      if (!p) continue;
      const cm = /^(col|column|row)\s*(\d+)\s*:\s*(.*)$/i.exec(p);
      if (cm) {
        const target = cm[1].toLowerCase().startsWith('col') ? st.cols : st.rows;
        target[+cm[2]] = Object.assign(target[+cm[2]] || {}, parseProps(cm[3]));
      } else {
        const fm = /^borders?\s+(\w+)$/i.exec(p);
        const fr = /^freeze\s+(rows?|cols?|columns?)\s+(\d+)$/i.exec(p);
        const mh = /^(?:max-?height|height)\s+(\S+)$/i.exec(p);
        const sp = /^span\s+(\d+)\.(\d+)\s*:\s*(\d+)\s*[x×]\s*(\d+)$/i.exec(p);
        if (fm) st.flags.add('borders-' + fm[1].toLowerCase());
        else if (sp) { if (+sp[3] > 1 || +sp[4] > 1) st.spans[sp[1] + '.' + sp[2]] = { rows: Math.max(1, +sp[3]), cols: Math.max(1, +sp[4]) }; }
        else if (fr) st[fr[1].toLowerCase().startsWith('r') ? 'freezeRows' : 'freezeCols'] = +fr[2];
        else if (mh) st.maxHeight = mh[1];
        else st.flags.add(p.toLowerCase().replace(/\s+/g, '-'));
      }
    }
    return st;
  }

  function parseProps(s) {
    const o = {};
    for (const raw of s.split(',')) {
      const p = raw.trim();
      if (!p) continue;
      const wm = /^(width|bg|background|color|colour|font-size|size)\s+(.+)$/i.exec(p);
      if (wm) { const k = wm[1].toLowerCase(); o[k === 'background' ? 'bg' : k === 'colour' ? 'color' : k === 'font-size' ? 'size' : k] = wm[2].trim(); continue; }
      if (['left', 'center', 'centre', 'right'].includes(p.toLowerCase())) { o.align = p.toLowerCase() === 'centre' ? 'center' : p.toLowerCase(); continue; }
      o[p.toLowerCase()] = true;
    }
    return o;
  }

  function serializeProps(o) {
    const out = [];
    for (const [k, v] of Object.entries(o)) {
      if (v === true) out.push(k);
      else if (k === 'align') out.push(v);
      else if (v) out.push(k + ' ' + v);
    }
    return out.join(', ');
  }

  function serializeStyle(st) {
    const parts = [...st.flags].map((f) => f.startsWith('borders-') ? 'borders ' + f.slice(8) : f);
    if (st.freezeRows) parts.push('freeze rows ' + st.freezeRows);
    if (st.freezeCols) parts.push('freeze cols ' + st.freezeCols);
    if (st.maxHeight) parts.push('max-height ' + st.maxHeight);
    for (const [k, v] of Object.entries(st.spans || {})) parts.push('span ' + k + ': ' + v.rows + 'x' + v.cols);
    for (const [i, o] of Object.entries(st.cols)) { const s = serializeProps(o); if (s) parts.push('col ' + i + ': ' + s); }
    for (const [i, o] of Object.entries(st.rows)) { const s = serializeProps(o); if (s) parts.push('row ' + i + ': ' + s); }
    return parts.length ? '{table: ' + parts.join('; ') + '}' : '';
  }

  function parse(src) {
    const lines = String(src || '').split('\n').filter((l) => l.trim() !== '');
    const t = { rows: [], aligns: [], style: parseStyle('') };
    if (!lines.length) return t;
    let styleLine = '';
    if (/^\s*\{table\b/.test(lines[lines.length - 1])) styleLine = lines.pop();
    t.style = parseStyle(styleLine);
    const header = splitRow(lines[0]);
    const sep = lines.length > 1 && FS.markdown.RE.tableSep.test(lines[1]) ? splitRow(lines[1]) : null;
    t.aligns = header.map((_, i) => {
      const s = sep && sep[i] ? sep[i] : '';
      return s.startsWith(':') && s.endsWith(':') ? 'center' : s.endsWith(':') ? 'right' : s.startsWith(':') ? 'left' : null;
    });
    t.rows.push(header);
    for (let i = sep ? 2 : 1; i < lines.length; i++) t.rows.push(splitRow(lines[i]));
    const w = Math.max(...t.rows.map((r) => r.length));
    for (const r of t.rows) while (r.length < w) r.push('');
    while (t.aligns.length < w) t.aligns.push(null);
    return t;
  }

  /* Merged cells (Seth, 2026-10-12: "Merging cells would also be great, but I realize that's
   * not allowed in Markdown"). They are not: the grid stays a plain pipe table — every cell is
   * still there, a covered cell is simply empty — and the style line carries
   * `span R.C: RxC` (1-based anchor, rows × cols). Rendered as rowspan/colspan; a markdown
   * export keeps the table readable and only loses the merge. */
  function spanMap(t) {
    const covered = new Map();                 // "r.c" (0-based) → anchor key
    const anchors = {};
    const nr = t.rows.length, nc = t.rows[0] ? t.rows[0].length : 0;
    for (const [k, v] of Object.entries(t.style.spans || {})) {
      const [r, c] = k.split('.').map((x) => +x - 1);
      if (r < 0 || c < 0 || r >= nr || c >= nc) continue;
      let rows = Math.min(v.rows, nr - r), cols = Math.min(v.cols, nc - c);
      if (r === 0 && rows > 1) rows = 1;       // the header row cannot reach into the body
      if (rows < 2 && cols < 2) continue;
      anchors[r + '.' + c] = { rows, cols };
      for (let i = r; i < r + rows; i++) for (let j = c; j < c + cols; j++) if (i !== r || j !== c) covered.set(i + '.' + j, r + '.' + c);
    }
    return { anchors, covered };
  }
  function remapSpans(t, fn) {
    const o = {};
    for (const [k, v] of Object.entries(t.style.spans || {})) {
      const [r, c] = k.split('.').map(Number);
      const n = fn(r, c, v.rows, v.cols);
      if (n && n.rows >= 1 && n.cols >= 1 && (n.rows > 1 || n.cols > 1)) o[n.r + '.' + n.c] = { rows: n.rows, cols: n.cols };
    }
    t.style.spans = o;
  }
  /* Merge the current cell with its neighbour to the right or below: the anchor's span grows
   * and the newly covered cells' text moves into it. Fails quietly across the header edge or
   * into another merged cell. */
  function mergeCell(t, r, c, dir) {
    const { anchors, covered } = spanMap(t);
    if (covered.has(r + '.' + c)) return false;
    const sp = anchors[r + '.' + c] || { rows: 1, cols: 1 };
    const nr = t.rows.length, nc = t.rows[0].length;
    const next = dir === 'right' ? { rows: sp.rows, cols: sp.cols + 1 } : { rows: sp.rows + 1, cols: sp.cols };
    if (r + next.rows > nr || c + next.cols > nc) return false;
    if (dir === 'down' && r === 0) return false;
    const taken = [];
    for (let i = r; i < r + next.rows; i++) for (let j = c; j < c + next.cols; j++) {
      if (i === r && j === c) continue;
      const k = i + '.' + j;
      const inOld = i < r + sp.rows && j < c + sp.cols;
      if (!inOld && (anchors[k] || (covered.has(k) && covered.get(k) !== r + '.' + c))) return false;
      if (!inOld) taken.push([i, j]);
    }
    const extra = taken.map(([i, j]) => t.rows[i][j]).filter((x) => x && x.trim());
    if (extra.length) t.rows[r][c] = [t.rows[r][c], ...extra].filter((x) => x && x.trim()).join('<br>');   // cells keep <br> as their line break
    for (const [i, j] of taken) t.rows[i][j] = '';
    t.style.spans[(r + 1) + '.' + (c + 1)] = next;
    return true;
  }
  /* Merge a rectangle of cells (0-based, inclusive) into one. The rectangle is first grown to
   * include any merged cell it touches, so a span is never cut in half; the header row only
   * merges sideways. Non-empty texts are joined row by row with <br>. */
  function growToSpans(t, sel) {
    const { anchors } = spanMap(t);
    let { r1, c1, r2, c2 } = sel;
    let changed = true;
    while (changed) {
      changed = false;
      for (const [k, v] of Object.entries(anchors)) {
        const [ar, ac] = k.split('.').map(Number);
        const br = ar + v.rows - 1, bc = ac + v.cols - 1;
        if (br < r1 || ar > r2 || bc < c1 || ac > c2) continue;
        const n = { r1: Math.min(r1, ar), c1: Math.min(c1, ac), r2: Math.max(r2, br), c2: Math.max(c2, bc) };
        if (n.r1 !== r1 || n.c1 !== c1 || n.r2 !== r2 || n.c2 !== c2) { ({ r1, c1, r2, c2 } = n); changed = true; }
      }
    }
    return { r1, c1, r2, c2 };
  }
  function mergeRange(t, sel) {
    const g = growToSpans(t, sel);
    if (g.r1 === 0 && g.r2 > 0) return false;
    if (g.r1 === g.r2 && g.c1 === g.c2) return false;
    const texts = [];
    for (let i = g.r1; i <= g.r2; i++) for (let j = g.c1; j <= g.c2; j++) { const v = t.rows[i][j]; if (v && v.trim()) texts.push(v); if (i !== g.r1 || j !== g.c1) t.rows[i][j] = ''; }
    t.rows[g.r1][g.c1] = texts.join('<br>');
    for (const k of Object.keys(t.style.spans)) { const [ar, ac] = k.split('.').map((x) => +x - 1); if (ar >= g.r1 && ar <= g.r2 && ac >= g.c1 && ac <= g.c2) delete t.style.spans[k]; }
    t.style.spans[(g.r1 + 1) + '.' + (g.c1 + 1)] = { rows: g.r2 - g.r1 + 1, cols: g.c2 - g.c1 + 1 };
    return true;
  }
  function unmergeRange(t, sel) {
    const g = growToSpans(t, sel);
    let n = 0;
    for (const k of Object.keys(t.style.spans)) { const [ar, ac] = k.split('.').map((x) => +x - 1); if (ar >= g.r1 && ar <= g.r2 && ac >= g.c1 && ac <= g.c2) { delete t.style.spans[k]; n++; } }
    return n > 0;
  }
  function unmergeCell(t, r, c) {
    const { covered } = spanMap(t);
    const key = covered.get(r + '.' + c) || (r + '.' + c);
    const [ar, ac] = key.split('.').map(Number);
    if (!t.style.spans[(ar + 1) + '.' + (ac + 1)]) return false;
    delete t.style.spans[(ar + 1) + '.' + (ac + 1)];
    return true;
  }

  /* Split a table above row r (0-based, body rows only): both halves keep the header, the
   * column styles and the flags; row styles and spans follow their rows. Returns [top, bottom]. */
  function splitAt(t, r) {
    if (r <= 0 || r >= t.rows.length) return null;
    const clone = (rows) => ({ rows: rows.map((x) => x.slice()), aligns: t.aligns.slice(), style: { flags: new Set(t.style.flags), cols: JSON.parse(JSON.stringify(t.style.cols)), rows: {}, spans: {}, freezeRows: t.style.freezeRows, freezeCols: t.style.freezeCols, maxHeight: t.style.maxHeight } });
    const top = clone(t.rows.slice(0, r)), bottom = clone([t.rows[0], ...t.rows.slice(r)]);
    for (const [k, v] of Object.entries(t.style.rows)) { const n = +k; if (n <= r) top.style.rows[n] = v; else bottom.style.rows[n - r + 1] = v; }
    for (const [k, v] of Object.entries(t.style.spans || {})) {
      const [ar, ac] = k.split('.').map(Number);
      if (ar <= r) top.style.spans[k] = { rows: Math.min(v.rows, r - ar + 1), cols: v.cols };
      else bottom.style.spans[(ar - r + 1) + '.' + ac] = { rows: v.rows, cols: v.cols };
    }
    return [top, bottom];
  }
  /* Append table b under table a. b's header row is dropped when it repeats a's (a split put
   * it there); otherwise it becomes an ordinary row. Column styles and flags are a's. */
  function mergeTables(a, b) {
    const same = b.rows[0].length === a.rows[0].length && b.rows[0].every((x, i) => (x || '').trim() === (a.rows[0][i] || '').trim());
    const w = Math.max(a.rows[0].length, b.rows[0].length);
    const t = { rows: a.rows.map((x) => x.slice()), aligns: a.aligns.slice(), style: { flags: new Set(a.style.flags), cols: JSON.parse(JSON.stringify(a.style.cols)), rows: JSON.parse(JSON.stringify(a.style.rows)), spans: JSON.parse(JSON.stringify(a.style.spans || {})), freezeRows: a.style.freezeRows, freezeCols: a.style.freezeCols, maxHeight: a.style.maxHeight } };
    const skip = same ? 1 : 0, base = a.rows.length;
    for (const row of b.rows.slice(skip)) t.rows.push(row.slice());
    for (const r of t.rows) while (r.length < w) r.push('');
    while (t.aligns.length < w) t.aligns.push(null);
    for (const [k, v] of Object.entries(b.style.rows)) { const n = +k - skip; if (n >= 1) t.style.rows[n + base] = v; }
    for (const [k, v] of Object.entries(b.style.spans || {})) { const [ar, ac] = k.split('.').map(Number); const n = ar - skip; if (n >= 1) t.style.spans[(n + base) + '.' + ac] = v; }
    return t;
  }

  function cellOut(s) { return String(s || '').replace(/\|/g, '\\|').replace(/\n/g, '<br>'); }

  function serialize(t) {
    const w = Math.max(1, ...t.rows.map((r) => r.length));
    const rows = t.rows.map((r) => { const c = r.slice(); while (c.length < w) c.push(''); return c; });
    const lines = ['| ' + rows[0].map(cellOut).join(' | ') + ' |'];
    lines.push('|' + Array.from({ length: w }, (_, i) => { const a = t.aligns[i]; return a === 'center' ? ':---:' : a === 'right' ? '---:' : a === 'left' ? ':---' : '---'; }).join('|') + '|');
    for (const r of rows.slice(1)) lines.push('| ' + r.map(cellOut).join(' | ') + ' |');
    const st = serializeStyle(t.style);
    if (st) lines.push(st);
    return lines.join('\n');
  }

  const template = (rows, cols) => serialize({ rows: Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => (r === 0 ? 'Column ' + (c + 1) : ''))), aligns: [], style: parseStyle('') });

  /* ------------------------------------------------------------------ rendering */
  function cellStyle(t, r, c) {
    const col = t.style.cols[c + 1] || {}, row = t.style.rows[r + 1] || {};
    const css = {};
    const cls = [];
    const a = row.align || col.align || t.aligns[c];
    if (a) css.textAlign = a;
    if (col.width) { css.width = col.width; css.minWidth = col.width; }
    if (row.bg || col.bg) css.background = row.bg || col.bg;
    if (row.color || col.color) css.color = row.color || col.color;
    if (row.size || col.size) css.fontSize = row.size || col.size;
    if (row.bold || col.bold) css.fontWeight = '700';
    if (row.italic || col.italic) css.fontStyle = 'italic';
    if (row.nowrap || col.nowrap) cls.push('nowrap');
    if (row.vern || col.vern) cls.push('vern-cell');
    return { css, cls };
  }

  /* Render a table block into `container`. opts.onChange(newSrc) is called on every edit;
   * opts.editor lets cells reach the note's shared services (flex rendering, links). */
  function render(container, src, opts) {
    opts = opts || {};
    const t = parse(src);
    container.innerHTML = '';
    // ⚠ Every structural change re-renders the whole table. A cell that is still being edited
    // must be saved FIRST, or whatever was typed in it is lost: its editor is torn down with
    // the old DOM and the blur that would have saved it never fires on a removed element
    // (Seth, 2026-10-12: "Resizing columns … loses data … and since there's no undo, I
    // can't get it back"). finishEdit is set by the open cell editor and cleared by it.
    if (activeWidget && activeWidget.container === container) activeWidget = null;   // a re-render drops the old selection
    // ONE widget object per table, reused by every re-render: the editor (activeTable,
    // wrap._table), paste handlers and dialogs keep references to it across refreshes, and a
    // stale copy would insert into — and commit — the table as it was before the last change
    // (Seth, 2026-10-13: objects "jumping from cells I insert them into to other columns").
    const widget = container._widget = container._widget || {};
    for (const k of Object.keys(widget)) delete widget[k];
    Object.assign(widget, { t, container, focus: null, insertText: null, finishEdit: null, lastCell: null, lastCaret: null, sel: null, gsel: null, anchor: null });
    /* A re-render keeps the user where they were (Seth, 2026-10-13: "not have the table jump
     * back to the first cell whenever an example has been inserted"): the editor pane's scroll
     * position is restored, the focused cell stays the focused cell, and a cell that was being
     * edited — or just received an insert — is reopened with its caret. */
    widget.refresh = (reopen) => {
      const editing = !!widget.finishEdit;
      const focus = widget.focus;
      const caret = editing && widget.lastCaret ? widget.lastCaret() : null;
      if (widget.finishEdit) widget.finishEdit();
      const pane = container.closest('#editor');
      const top = pane ? pane.scrollTop : 0;
      const w2 = render(container, serialize(t), opts);
      if (pane) pane.scrollTop = top;
      const want = reopen || (editing && focus ? { r: focus.r, c: focus.c, caret } : null);
      if (want && w2) {
        const cell = container.querySelector('[data-r="' + want.r + '"][data-c="' + want.c + '"]');
        if (cell && want.rendered) {
          // after an insert: show the rendered cell (the chip), keep it the target of the next
          // insert and of a click on its padding, but do not drop the user into the source
          w2.focus = { r: want.r, c: want.c };
          w2.lastCell = { r: want.r, c: want.c, caret: want.caret };
          w2.insertText = (text) => w2.insertInto(want.r, want.c, text, want.caret);
        } else if (cell) { w2.focus = { r: want.r, c: want.c }; cell.dispatchEvent(new CustomEvent('cell-edit', { detail: { caret: want.caret } })); }
      } else if (focus && w2) w2.focus = focus;
      return w2;
    };
    const table = el('table', { class: 'md-table ' + [...t.style.flags].join(' ') });
    const thead = el('thead'), tbody = el('tbody');
    const commit = () => opts.onChange && opts.onChange(serialize(t));
    /* Put text into a cell that is not being edited (the picker closed the cell editor). */
    widget.insertInto = (r, c, text, caret) => {
      const s = t.rows[r][c] || '';
      const at = caret == null ? s.length : Math.min(caret, s.length);
      const sep = (at > 0 && !/\s$/.test(s.slice(0, at))) ? ' ' : '';
      t.rows[r][c] = s.slice(0, at) + sep + text + s.slice(at);
      commit();
      widget.refresh({ r, c, caret: at + sep.length + text.length, rendered: true });
    };
    const spans = spanMap(t);
    const nRows = t.rows.length, nCols = t.rows[0] ? t.rows[0].length : 0;
    /* Selection handles like a spreadsheet's (Seth, 2026-10-12): a strip above the header
     * selects columns, a strip left of each row selects rows, the corner selects the table;
     * drag or Shift-click across the strips for a range. They carry no data-r/data-c, so the
     * grid code (spans, freeze, resize) never sees them. */
    const gutterSelect = (kind, a, b) => {
      if (widget.finishEdit) widget.finishEdit();
      if (kind === 'col') widget.select({ r: 0, c: Math.min(a, b) }, { r: nRows - 1, c: Math.max(a, b) });
      else if (kind === 'row') widget.select({ r: Math.min(a, b), c: 0 }, { r: Math.max(a, b), c: nCols - 1 });
      else widget.select({ r: 0, c: 0 }, { r: nRows - 1, c: nCols - 1 });
      widget.gsel = { kind, a };
    };
    const gutter = (kind, i, title) => {
      const g = el('th', { class: 'gutter ' + kind, title, dataset: kind === 'col' ? { gc: i } : kind === 'row' ? { gr: i } : {} });
      g.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const a = (e.shiftKey && widget.gsel && widget.gsel.kind === kind) ? widget.gsel.a : i;
        gutterSelect(kind, a, i);
        if (!e.shiftKey) widget.gsel = { kind, a: i };
      });
      g.addEventListener('mouseenter', (e) => { if ((e.buttons & 1) && widget.gsel && widget.gsel.kind === kind && kind !== 'all') gutterSelect(kind, widget.gsel.a, i); });
      return g;
    };
    const gutterRow = el('tr', { class: 'gutter-row' }, gutter('all', 0, 'Select the whole table'));
    for (let c = 0; c < nCols; c++) gutterRow.appendChild(gutter('col', c, 'Select column ' + (c + 1) + ' (drag or Shift-click for several)'));
    thead.appendChild(gutterRow);
    t.rows.forEach((row, r) => {
      const tr = el('tr', {}, gutter('row', r, 'Select row ' + (r + 1) + ' (drag or Shift-click for several)'));
      row.forEach((cell, c) => {
        if (spans.covered.has(r + '.' + c)) return;
        const { css, cls } = cellStyle(t, r, c);
        const td = el(r === 0 ? 'th' : 'td', { class: cls.join(' '), style: css, dataset: { r, c } });
        const sp = spans.anchors[r + '.' + c];
        if (sp) { if (sp.rows > 1) td.rowSpan = sp.rows; if (sp.cols > 1) td.colSpan = sp.cols; td.classList.add('merged'); }
        mountCell(td, t, r, c, widget, commit, opts);
        if (r === 0) td.appendChild(colResizer(td, t, c, widget, commit));
        tr.appendChild(td);
      });
      (r === 0 ? thead : tbody).appendChild(tr);
    });
    table.append(thead, tbody);
    const wrap = el('div', { class: 'tbl-wrap' + ((t.style.freezeRows || t.style.freezeCols) ? ' frozen' : '') }, table);
    if (t.style.freezeRows || t.style.freezeCols) wrap.style.maxHeight = t.style.maxHeight || '60vh';
    container.appendChild(wrap);
    if (t.style.freezeRows || t.style.freezeCols) requestAnimationFrame(() => applyFreeze(table, t));
    // the structural operations, shared by the bar under the table and the right-click menu
    const done = () => { commit(); widget.refresh(); };
    const ops = widget.ops = {
      insertRow: (i) => { i = Math.max(1, Math.min(i, t.rows.length)); t.rows.splice(i, 0, t.rows[0].map(() => '')); shiftRowStyles(t, i + 1, 1); done(); },
      insertCol: (i) => { i = Math.max(0, Math.min(i, t.rows[0].length)); t.rows.forEach((row) => row.splice(i, 0, '')); t.aligns.splice(i, 0, null); shiftColStyles(t, i + 1, 1); done(); },
      deleteRow: (r) => { if (t.rows.length <= 1 || r === 0) return; t.rows.splice(r, 1); delete t.style.rows[r + 1]; shiftRowStyles(t, r + 2, -1); done(); },
      deleteCol: (c) => { if (t.rows[0].length <= 1) return; t.rows.forEach((row) => row.splice(c, 1)); t.aligns.splice(c, 1); delete t.style.cols[c + 1]; shiftColStyles(t, c + 2, -1); done(); },
      mergeRight: (r, c) => { if (mergeCell(t, r, c, 'right')) done(); },
      mergeDown: (r, c) => { if (mergeCell(t, r, c, 'down')) done(); },
      mergeRange: (sel) => { if (mergeRange(t, sel)) done(); },
      unmerge: (sel) => { if (unmergeRange(t, sel)) done(); },
      freezeHere: (r, c) => { t.style.freezeRows = r; t.style.freezeCols = c; done(); },
      freezeTop: () => { t.style.freezeRows = 1; done(); },
      freezeFirst: () => { t.style.freezeCols = 1; done(); },
      unfreeze: () => { t.style.freezeRows = 0; t.style.freezeCols = 0; done(); },
    };
    /* Clipboard and keys for a selection (Seth, 2026-10-12: "paste rows or columns into a
     * table"): with cells selected and no cell open, Ctrl+C / Ctrl+X copy them as TSV + HTML,
     * Delete clears them, and Ctrl+V pastes a grid — over the cells from the top-left corner
     * (growing the table as needed), or, when whole rows / columns are selected, as new rows
     * above / columns to the left of them, like a spreadsheet's Insert Copied Cells. */
    const grow = (nr, nc) => {
      while (t.rows.length < nr) t.rows.push(t.rows[0].map(() => ''));
      if (nc > t.rows[0].length) { t.rows.forEach((row) => { while (row.length < nc) row.push(''); }); while (t.aligns.length < nc) t.aligns.push(null); }
    };
    ops.pasteOver = (r, c, rows) => {
      grow(r + rows.length, c + Math.max(...rows.map((x) => x.length)));
      rows.forEach((row, i) => row.forEach((v, j) => { t.rows[r + i][c + j] = String(v == null ? '' : v); }));
      done();
    };
    ops.pasteRowsAt = (i, rows) => {
      i = Math.max(1, Math.min(i, t.rows.length));
      grow(0, Math.max(...rows.map((x) => x.length)));
      rows.forEach((row, k) => { const nr = t.rows[0].map((_, j) => String(row[j] == null ? '' : row[j])); t.rows.splice(i + k, 0, nr); shiftRowStyles(t, i + k + 1, 1); });
      done();
    };
    ops.pasteColsAt = (i, rows) => {
      i = Math.max(0, Math.min(i, t.rows[0].length));
      const m = Math.max(...rows.map((x) => x.length));
      grow(rows.length, 0);
      for (let j = 0; j < m; j++) { t.rows.forEach((row, r) => row.splice(i + j, 0, String(rows[r] && rows[r][j] != null ? rows[r][j] : ''))); t.aligns.splice(i + j, 0, null); shiftColStyles(t, i + j + 1, 1); }
      done();
    };
    ops.clear = (sel) => { for (let r = sel.r1; r <= sel.r2; r++) for (let c = sel.c1; c <= sel.c2; c++) t.rows[r][c] = ''; done(); };
    widget.selectedRows = () => { const s = widget.sel; if (!s) return []; const out = []; for (let r = s.r1; r <= s.r2; r++) out.push(t.rows[r].slice(s.c1, s.c2 + 1)); return out; };
    widget.wholeRows = () => widget.sel && widget.sel.c1 === 0 && widget.sel.c2 === t.rows[0].length - 1 && !(widget.sel.r1 === 0 && widget.sel.r2 === t.rows.length - 1 && widget.gsel && widget.gsel.kind === 'col');
    widget.wholeCols = () => widget.sel && widget.sel.r1 === 0 && widget.sel.r2 === t.rows.length - 1 && !widget.wholeRows();
    widget.pasteGrid = (rows, how) => {
      const s = widget.sel || { r1: (widget.focus || { r: 1 }).r, c1: (widget.focus || { c: 0 }).c, r2: 0, c2: 0 };
      how = how || (widget.wholeRows() ? 'rows-above' : widget.wholeCols() ? 'cols-left' : 'over');
      if (how === 'rows-above') ops.pasteRowsAt(s.r1, rows);
      else if (how === 'rows-below') ops.pasteRowsAt(s.r2 + 1, rows);
      else if (how === 'cols-left') ops.pasteColsAt(s.c1, rows);
      else if (how === 'cols-right') ops.pasteColsAt(s.c2 + 1, rows);
      else ops.pasteOver(s.r1, s.c1, rows);
    };
    // a selected range of cells (Shift+click or drag across cells): {r1,c1,r2,c2}, 0-based
    widget.sel = null;
    widget.select = (a, b) => {
      const raw = { r1: Math.min(a.r, b.r), c1: Math.min(a.c, b.c), r2: Math.max(a.r, b.r), c2: Math.max(a.c, b.c) };
      widget.sel = growToSpans(t, raw);
      activeWidget = widget;
      // the selection takes the keyboard: a text block or input that still had focus would
      // otherwise swallow Ctrl+C / Ctrl+V / Delete
      const act = document.activeElement;
      if (act && act !== document.body && act.blur && !(act.closest && act.closest('.popover, .modal'))) act.blur();
      table.querySelectorAll('.sel').forEach((x) => x.classList.remove('sel'));
      table.querySelectorAll('td, th').forEach((cell) => { const r = +cell.dataset.r, c = +cell.dataset.c; if (r >= widget.sel.r1 && r <= widget.sel.r2 && c >= widget.sel.c1 && c <= widget.sel.c2) cell.classList.add('sel'); });
      table.querySelectorAll('.gutter.row').forEach((g) => g.classList.toggle('on', +g.dataset.gr >= widget.sel.r1 && +g.dataset.gr <= widget.sel.r2));
      table.querySelectorAll('.gutter.col').forEach((g) => g.classList.toggle('on', +g.dataset.gc >= widget.sel.c1 && +g.dataset.gc <= widget.sel.c2));
    };
    widget.clearSelection = () => { widget.sel = null; widget.gsel = null; if (activeWidget === widget) activeWidget = null; table.querySelectorAll('.sel, .gutter.on').forEach((x) => { x.classList.remove('sel'); x.classList.remove('on'); }); };
    table.addEventListener('contextmenu', (e) => {
      const cell = e.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      e.preventDefault();
      if (cell.classList.contains('gutter')) {
        const kind = cell.classList.contains('col') ? 'col' : cell.classList.contains('row') ? 'row' : 'all';
        const i = kind === 'col' ? +cell.dataset.gc : kind === 'row' ? +cell.dataset.gr : 0;
        const inside = widget.sel && (kind === 'col' ? (i >= widget.sel.c1 && i <= widget.sel.c2 && widget.sel.r1 === 0 && widget.sel.r2 === nRows - 1) : kind === 'row' ? (i >= widget.sel.r1 && i <= widget.sel.r2 && widget.sel.c1 === 0 && widget.sel.c2 === nCols - 1) : false);
        if (!inside) gutterSelect(kind, i, i);
        const at = kind === 'col' ? { r: widget.sel.r1, c: i } : kind === 'row' ? { r: i, c: widget.sel.c1 } : { r: 0, c: 0 };
        widget.focus = at;
        contextMenu(e.clientX, e.clientY, t, at, commit, widget, opts);
        return;
      }
      const at = { r: +cell.dataset.r, c: +cell.dataset.c };
      const inSel = widget.sel && at.r >= widget.sel.r1 && at.r <= widget.sel.r2 && at.c >= widget.sel.c1 && at.c <= widget.sel.c2;
      if (!inSel) { widget.clearSelection(); widget.focus = at; }
      contextMenu(e.clientX, e.clientY, t, at, commit, widget, opts);
    });
    // the bar under the table; sticks to the bottom of the pane while the table is partly
    // scrolled past it (Seth, 2026-10-12: "reverse sticky")
    const tools = el('div', { class: 'tbl-tools' });
    const cur = () => widget.focus || { r: t.rows.length - 1, c: 0 };
    tools.append(
      el('button', { title: 'Add a row below the current one', onclick: () => ops.insertRow(cur().r + 1) }, '+ Row'),
      el('button', { title: 'Add a column after the current one', onclick: () => ops.insertCol(cur().c + 1) }, '+ Column'),
      el('button', { title: 'Delete the current row', onclick: () => ops.deleteRow(cur().r) }, '− Row'),
      el('button', { title: 'Delete the current column', onclick: () => ops.deleteCol(cur().c) }, '− Column'),
      el('button', { onclick: (e) => colPopover(e.currentTarget, t, cur().c, commit, widget) }, 'Column ▾'),
      el('button', { onclick: (e) => rowPopover(e.currentTarget, t, cur().r, commit, widget) }, 'Row ▾'),
      el('button', { onclick: (e) => cellPopover(e.currentTarget, t, cur(), commit, widget) }, 'Cells ▾'),
      el('button', { onclick: (e) => tablePopover(e.currentTarget, t, commit, widget, opts) }, 'Table ▾'),
      el('span', { class: 'small muted', style: { marginLeft: '6px' } }, 'right-click a cell for all commands'),
    );
    container.appendChild(tools);
    return widget;
  }

  /* The table with the live cell selection, for the document-level clipboard and key handlers. */
  let activeWidget = null;
  const liveSelection = () => {
    const w = activeWidget;
    if (!w || !w.sel || !w.container.isConnected || w.finishEdit) return null;
    const a = document.activeElement;
    if (a && a.closest && a.closest('[contenteditable="true"], input, textarea, select')) return null;
    return w;
  };
  document.addEventListener('copy', (e) => { const w = liveSelection(); if (!w) return; const rows = w.selectedRows(); e.clipboardData.setData('text/plain', tsvOf(rows)); e.clipboardData.setData('text/html', htmlOf(rows)); e.preventDefault(); });
  document.addEventListener('cut', (e) => { const w = liveSelection(); if (!w) return; const rows = w.selectedRows(); e.clipboardData.setData('text/plain', tsvOf(rows)); e.clipboardData.setData('text/html', htmlOf(rows)); e.preventDefault(); w.ops.clear(w.sel); });
  document.addEventListener('paste', (e) => { const w = liveSelection(); if (!w) return; const rows = clipGrid(e.clipboardData); if (!rows) return; e.preventDefault(); w.pasteGrid(rows); });
  document.addEventListener('keydown', (e) => {
    const w = liveSelection();
    if (!w) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); w.ops.clear(w.sel); }
    else if (e.key === 'Escape') { w.clearSelection(); }
  });
  /* The context menu's Paste… items read the clipboard themselves (Chromium asks once). */
  async function readClipGrid() {
    try {
      if (navigator.clipboard && navigator.clipboard.read) {
        for (const item of await navigator.clipboard.read()) {
          if (item.types.includes('text/html')) { const g = htmlGrid(await (await item.getType('text/html')).text()); if (g) return g.rows; }
          if (item.types.includes('text/plain')) { const text = (await (await item.getType('text/plain')).text()).replace(/\r\n?/g, '\n').replace(/\n+$/, ''); if (text) return text.split('\n').map((l) => l.split('\t')); }
        }
      } else if (navigator.clipboard && navigator.clipboard.readText) {
        const text = (await navigator.clipboard.readText()).replace(/\r\n?/g, '\n').replace(/\n+$/, '');
        if (text) return text.split('\n').map((l) => l.split('\t'));
      }
    } catch (err) { /* no permission: fall through */ }
    return null;
  }

  /* Right-click menu on a cell: everything the bar and the popovers offer, in one place
   * (Seth, 2026-10-12: "all the table commands on a context menu … split, merge, insert,
   * delete (rows, columns, cells), or freeze panes"). Acts on the selected range when the
   * click is inside one, else on the clicked cell. */
  function contextMenu(x, y, t, at, commit, widget, opts) {
    const ops = widget.ops;
    const sel = widget.sel;
    const range = sel || { r1: at.r, c1: at.c, r2: at.r, c2: at.c };
    const multi = sel && (sel.r1 !== sel.r2 || sel.c1 !== sel.c2);
    const { anchors, covered } = spanMap(t);
    const key = at.r + '.' + at.c;
    let mergedInRange = false;
    for (const k of Object.keys(anchors)) { const [ar, ac] = k.split('.').map(Number); if (ar >= range.r1 && ar <= range.r2 && ac >= range.c1 && ac <= range.c2) mergedInRange = true; }
    FS.popoverAt(x, y, (pop, close) => {
      pop.classList.add('menu');
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, multi ? 'Cells ' + (sel.r1 + 1) + ',' + (sel.c1 + 1) + ' – ' + (sel.r2 + 1) + ',' + (sel.c2 + 1) : (at.r === 0 ? 'Header cell ' : 'Cell ') + (at.r + 1) + ',' + (at.c + 1))));
      const item = (label, fn, disabled) => pop.appendChild(el('button', { class: 'menu-item', disabled: !!disabled, onclick: () => { close(); fn(); } }, label));
      const sep = () => pop.appendChild(el('hr'));
      item('Insert row above', () => ops.insertRow(range.r1), range.r1 === 0);
      item('Insert row below', () => ops.insertRow(range.r2 + 1));
      item('Insert column to the left', () => ops.insertCol(range.c1));
      item('Insert column to the right', () => ops.insertCol(range.c2 + 1));
      item(multi && range.r1 !== range.r2 ? 'Delete rows' : 'Delete row', () => { for (let r = range.r2; r >= range.r1; r--) ops.deleteRow(r); }, range.r1 === 0 && range.r2 === 0);
      item(multi && range.c1 !== range.c2 ? 'Delete columns' : 'Delete column', () => { for (let c = range.c2; c >= range.c1; c--) ops.deleteCol(c); }, t.rows[0].length <= range.c2 - range.c1 + 1);
      sep();
      if (multi) item('Merge cells', () => ops.mergeRange(range), range.r1 === 0 && range.r2 > 0);
      else {
        item('Merge with the cell to the right', () => ops.mergeRight(at.r, at.c), covered.has(key));
        item('Merge with the cell below', () => ops.mergeDown(at.r, at.c), covered.has(key) || at.r === 0);
      }
      item('Unmerge', () => ops.unmerge(range), !(mergedInRange || covered.has(key)));
      sep();
      const copySel = () => { if (!widget.sel) widget.select(at, at); FS.copyText(tsvOf(widget.selectedRows())); };
      item(multi ? 'Copy cells' : 'Copy cell', copySel);
      item(multi ? 'Cut cells' : 'Cut cell', () => { copySel(); ops.clear(widget.sel); });
      item(multi ? 'Clear cells' : 'Clear cell', () => ops.clear(range));
      const pasteAs = (how, label) => item(label, async () => { const rows = await readClipGrid(); if (!rows) { FS.toast('Nothing tabular on the clipboard — or no permission to read it: select the cells and press Ctrl+V instead', 'error'); return; } if (!widget.sel) widget.select(at, at); widget.pasteGrid(rows, how); });
      pasteAs('over', 'Paste over these cells');
      pasteAs('rows-above', 'Paste rows above');
      pasteAs('rows-below', 'Paste rows below');
      pasteAs('cols-left', 'Paste columns to the left');
      pasteAs('cols-right', 'Paste columns to the right');
      sep();
      const frozen = (t.style.freezeRows || 0) + (t.style.freezeCols || 0) > 0;
      item('Freeze panes here (rows above, columns to the left)', () => ops.freezeHere(at.r, at.c), at.r === 0 && at.c === 0);
      item('Freeze top row', () => ops.freezeTop());
      item('Freeze first column', () => ops.freezeFirst());
      item('Unfreeze panes', () => ops.unfreeze(), !frozen);
      if (opts && (opts.onSplit || opts.onMerge)) {
        sep();
        if (opts.onSplit) item('Split table above this row', () => opts.onSplit(at.r), at.r === 0);
        if (opts.onMerge && opts.canMerge) {
          item('Merge with table above', () => opts.onMerge(-1), !opts.canMerge(-1));
          item('Merge with table below', () => opts.onMerge(1), !opts.canMerge(1));
        }
      }
      sep();
      const anchorCell = () => widget.container.querySelector('[data-r="' + at.r + '"][data-c="' + at.c + '"]') || widget.container;
      item('Column style…', () => colPopover(anchorCell(), t, at.c, commit, widget));
      item('Row style…', () => rowPopover(anchorCell(), t, at.r, commit, widget));
      item('Table style…', () => tablePopover(anchorCell(), t, commit, widget, opts));
    });
  }

  /* Drag the right edge of a header cell to set that column's width (saved as `col N: width
   * NNNpx` in the style line). A table dragged wider than the pane turns `wide` on, so the
   * cells keep their widths and the table scrolls sideways inside the note instead of being
   * squeezed (Seth, 2026-10-12: "the table can be wider than the document content pane, if the
   * user wants"). */
  function colResizer(th, t, c, widget, commit) {
    const h = el('div', { class: 'col-resizer', title: 'Drag to resize this column' });
    h.addEventListener('mousedown', (e) => {
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, startW = th.getBoundingClientRect().width;
      const table = th.closest('table');
      const wrap = widget.container.querySelector('.tbl-wrap');
      h.classList.add('dragging'); document.body.classList.add('resizing');
      const cells = [...table.querySelectorAll('[data-c="' + c + '"]')].filter((x) => (x.colSpan || 1) === 1);
      let w = startW;
      const move = (ev) => { w = Math.max(40, Math.round(startW + ev.clientX - startX)); for (const cell of cells) { cell.style.width = w + 'px'; cell.style.minWidth = w + 'px'; } };
      const up = () => {
        document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
        h.classList.remove('dragging'); document.body.classList.remove('resizing');
        t.style.cols[c + 1] = Object.assign(t.style.cols[c + 1] || {}, { width: w + 'px' });
        const total = [...table.querySelectorAll('thead th')].reduce((a, x) => a + x.getBoundingClientRect().width, 0);
        if (wrap && total > wrap.clientWidth + 2) t.style.flags.add('wide');
        commit(); widget.refresh();
      };
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    });
    h.addEventListener('dblclick', (e) => { e.stopPropagation(); if (t.style.cols[c + 1]) { delete t.style.cols[c + 1].width; commit(); widget.refresh(); } });
    return h;
  }

  /* Excel-style frozen panes: the first N rows stick to the top and the first M columns to
   * the left while the table scrolls inside its box (`freeze rows 1; freeze cols 1` in the
   * style line). Offsets are measured, so resized columns and tall header rows still work. */
  function applyFreeze(table, t) {
    const rows = [...table.querySelectorAll('tr')];
    const nr = t.style.freezeRows || 0, nc = t.style.freezeCols || 0;
    let top = 0;
    rows.forEach((tr) => {
      const h = tr.getBoundingClientRect().height;
      const ri = tr.classList.contains('gutter-row') ? -1 : +(tr.querySelector('[data-r]') || { dataset: { r: 0 } }).dataset.r;
      const stickyRow = nr > 0 && ri < nr;          // the column strip rides with frozen rows
      let left = 0;
      [...tr.children].forEach((cell) => {
        const w = cell.getBoundingClientRect().width;
        const ci = cell.classList.contains('gutter') ? -1 : +cell.dataset.c;
        const stickyCol = nc > 0 && ci < nc;        // the row strip rides with frozen columns
        if (stickyRow || stickyCol) {
          cell.classList.add('frozen');
          cell.style.position = 'sticky';
          if (stickyRow) cell.style.top = top + 'px';
          if (stickyCol) cell.style.left = left + 'px';
          cell.style.zIndex = (stickyRow && stickyCol) ? 4 : (stickyRow ? 3 : 2);
        }
        left += w;
      });
      if (stickyRow) top += h;
    });
  }

  function shiftRowStyles(t, from, by) {
    const o = {}; for (const [k, v] of Object.entries(t.style.rows)) o[+k >= from ? +k + by : +k] = v; t.style.rows = o;
    // by = +1: a row was inserted at 1-based `from`; by = -1: the row at `from - 1` was deleted
    remapSpans(t, (r, c, rows, cols) => {
      if (by > 0) return r >= from ? { r: r + 1, c, rows, cols } : (from > r && from < r + rows ? { r, c, rows: rows + 1, cols } : { r, c, rows, cols });
      const d = from - 1;
      if (r === d) return null;
      if (r > d) return { r: r - 1, c, rows, cols };
      return d < r + rows ? { r, c, rows: rows - 1, cols } : { r, c, rows, cols };
    });
  }
  function shiftColStyles(t, from, by) {
    const o = {}; for (const [k, v] of Object.entries(t.style.cols)) o[+k >= from ? +k + by : +k] = v; t.style.cols = o;
    remapSpans(t, (r, c, rows, cols) => {
      if (by > 0) return c >= from ? { r, c: c + 1, rows, cols } : (from > c && from < c + cols ? { r, c, rows, cols: cols + 1 } : { r, c, rows, cols });
      const d = from - 1;
      if (c === d) return null;
      if (c > d) return { r, c: c - 1, rows, cols };
      return d < c + cols ? { r, c, rows, cols: cols - 1 } : { r, c, rows, cols };
    });
  }

  /* A cell shows rendered markdown (embeds hydrated); clicking it edits the source in place. */
  function mountCell(td, t, r, c, widget, commit, opts) {
    const src = () => t.rows[r][c];
    const view = el('div', { class: 'cell-view', html: FS.markdown.renderInline(src()) || '<span class="muted">&nbsp;</span>' });
    hydrate(view, t, r, c, commit, opts, widget);
    td.appendChild(view);
    const startEdit = (offset) => {
      if (td.querySelector('.cell-edit')) return;
      view.remove();
      const ed = el('div', { class: 'cell-edit', contenteditable: 'true', spellcheck: 'true', dir: 'auto' });
      ed.textContent = src();
      ed.innerHTML = FS.markdown.decorate(ed.textContent, 'p') || '';
      td.appendChild(ed);
      widget.focus = { r, c };
      widget.insertText = (text) => { if (ed.isConnected) { insertAtCaret(ed, text); refresh(); } else widget.insertInto(r, c, text); };
      widget.lastCaret = () => (ed.isConnected ? FS.editor.getCaret(ed) : null);
      ed.focus();
      FS.editor && FS.editor.setCaret(ed, offset == null ? ed.textContent.length : offset);
      const refresh = () => {
        const caret = FS.editor.getCaret(ed);
        const html = FS.markdown.decorate(ed.textContent, 'p');
        if (html !== ed.innerHTML) { ed.innerHTML = html; FS.editor.setCaret(ed, caret); }
      };
      let composing = false;
      ed.addEventListener('compositionstart', () => { composing = true; });
      ed.addEventListener('compositionend', () => { composing = false; refresh(); });
      ed.addEventListener('input', () => { if (!composing) refresh(); });   // also after a native undo/redo
      ed.addEventListener('beforeinput', (e) => {
        const it = e.inputType;
        if (it === 'insertParagraph') { e.preventDefault(); finish(); moveTo(r + 1, c, true); return; }
        if (it === 'insertLineBreak') { e.preventDefault(); insertAtCaret(ed, '\n'); refresh(); return; }
        if (it === 'insertFromPaste' || it === 'insertFromDrop') {
          e.preventDefault();
          const text = (e.dataTransfer && e.dataTransfer.getData('text/plain')) || '';
          // A dialog may open before the insert happens; by then this cell editor has been
          // closed by the focus change. So insert through the cell's coordinates + the caret
          // captured now, whether the editor is still live or not.
          const caretNow = FS.editor.getCaret(ed);
          const put = (t) => {
            if (!ed.isConnected) { widget.insertInto(r, c, t, caretNow); return; }
            const before = ed.textContent.slice(0, FS.editor.getCaret(ed));
            insertAtCaret(ed, (before && !/\s$/.test(before) && !/^\s/.test(t) ? ' ' : '') + t); refresh();   // a chooser result is a token: keep it off the preceding word
          };
          if (opts.onPasteLink && /silfw:|^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(text.trim())) { opts.onPasteLink(text.trim(), (embed) => put(String(embed).replace(/\n/g, ' '))); return; }
          if (opts.onPasteLocate && /\t/.test(text)) { const plain = () => put(text.replace(/\r\n?/g, '\n').replace(/\n/g, ' ')); opts.onPasteLocate(text, (embed) => put(String(embed).replace(/\n/g, ' ')), plain); return; }
          insertAtCaret(ed, text.replace(/\r\n?/g, '\n')); refresh(); return;
        }
        if (it === 'formatBold') { e.preventDefault(); wrapSel(ed, '**'); refresh(); return; }
        if (it === 'formatItalic') { e.preventDefault(); wrapSel(ed, '*'); refresh(); return; }
        if (/^(insertText|insertCompositionText|insertReplacementText|deleteContent|deleteWord|deleteByCut|deleteSoftLineBackward|deleteHardLineBackward|historyUndo|historyRedo)/.test(it)) return;
        e.preventDefault();
      });
      ed.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') { e.preventDefault(); finish(); if (e.shiftKey) moveTo(c > 0 ? r : r - 1, c > 0 ? c - 1 : t.rows[0].length - 1); else { if (r === t.rows.length - 1 && c === t.rows[0].length - 1) { t.rows.push(t.rows[0].map(() => '')); commit(); widget.refresh(); setTimeout(() => moveTo(r + 1, 0), 0); return; } moveTo(c < t.rows[0].length - 1 ? r : r + 1, c < t.rows[0].length - 1 ? c + 1 : 0); } }
        else if (e.key === 'Escape') { e.preventDefault(); finish(); td.focus && td.focus(); }
        else if (e.key === 'ArrowUp' && e.altKey) { e.preventDefault(); finish(); moveTo(r - 1, c); }
        else if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); finish(); moveTo(r + 1, c); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); wrapSel(ed, '**'); refresh(); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'i') { e.preventDefault(); wrapSel(ed, '*'); refresh(); }
        else if (!(e.ctrlKey || e.metaKey)) e.stopPropagation();   // plain keys are the cell's; app shortcuts pass through
      });
      ed.addEventListener('blur', () => setTimeout(() => { if (ed.isConnected) finish(); }, 0));
      const finish = () => {
        if (!ed.isConnected) return;
        // only unhook OURSELVES: another cell may have opened (and registered its own
        // finish) between our blur and this deferred call
        if (widget.finishEdit === finish) widget.finishEdit = null;
        const val = ed.textContent.replace(/\n+$/, '');
        ed.remove();
        const caret = FS.editor.getCaret(ed);
        widget.lastCell = { r, c, caret };
        widget.insertText = (text) => widget.insertInto(r, c, text, caret);
        if (val !== t.rows[r][c]) { t.rows[r][c] = val; commit(); }
        view.innerHTML = FS.markdown.renderInline(t.rows[r][c]) || '<span class="muted">&nbsp;</span>';
        hydrate(view, t, r, c, commit, opts, widget);
        td.appendChild(view);
      };
      if (widget.finishEdit && widget.finishEdit !== finish) widget.finishEdit();   // one open cell at a time
      widget.finishEdit = finish;
      const moveTo = (rr, cc, create) => {
        if (rr < 0 || cc < 0) return;
        if (rr >= t.rows.length) { if (!create) return; t.rows.push(t.rows[0].map(() => '')); commit(); widget.refresh(); setTimeout(() => { const cell = widget.container.querySelector('[data-r="' + rr + '"][data-c="' + cc + '"] .cell-view'); if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); }, 0); return; }
        const cell = widget.container.querySelector('[data-r="' + rr + '"][data-c="' + cc + '"] .cell-view');
        if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      };
    };
    view.addEventListener('mousedown', (e) => {
      if (e.target.closest('a, button, .flex-obj, .seg-play, .flex-collapsed, .flex-inline')) return;   // chips/objects handle their own clicks
      if (e.ctrlKey || e.metaKey) return;
      if (e.button === 2) { widget.anchor = widget.anchor || { r, c }; return; }      // right-click: the menu decides
      e.preventDefault();
      if (e.shiftKey && widget.anchor) { if (widget.finishEdit) widget.finishEdit(); widget.select(widget.anchor, { r, c }); return; }
      widget.clearSelection();
      widget.anchor = { r, c };
      startEdit();
    });
    // dragging from one cell into another selects the rectangle between them (like a spreadsheet)
    td.addEventListener('mouseenter', (e) => {
      if (!(e.buttons & 1) || !widget.anchor || (widget.anchor.r === r && widget.anchor.c === c)) return;
      if (widget.finishEdit) widget.finishEdit();
      widget.select(widget.anchor, { r, c });
    });
    /* Typing before / after a FLEx object, or adding a second one (Seth, 2026-10-13: "we
     * can't … without using keyboard shortcuts"): a click on the cell's own padding, a
     * double-click on the chip / example, the ✎ button, or the overlay's "Edit cell" open the
     * cell's source with the caret after the object. */
    td.addEventListener('mousedown', (e) => { if (e.target === td && e.button === 0) { e.preventDefault(); widget.clearSelection(); widget.anchor = { r, c }; startEdit(); } });
    view.addEventListener('dblclick', (e) => {
      const obj = e.target.closest('.flex-collapsed, .flex-inline, .flex-obj');
      if (!obj) return;
      e.preventDefault(); e.stopPropagation();
      FS.interlinear.closeOverlay();
      const srcTxt = obj.closest('.flex-inline') ? obj.closest('.flex-inline').dataset.src : '';
      const at = srcTxt ? t.rows[r][c].indexOf(srcTxt) : -1;
      startEdit(at >= 0 ? at + srcTxt.length : undefined);
    });
    td.addEventListener('cell-edit', (e) => {
      const ph = e.detail && e.detail.after;
      if (!ph && e.detail && e.detail.caret != null) { startEdit(e.detail.caret); return; }
      const srcTxt = ph && ph.dataset ? ph.dataset.src : '';
      const at = srcTxt ? t.rows[r][c].indexOf(srcTxt) : -1;
      startEdit(at >= 0 ? at + srcTxt.length : undefined);
    });
    td.addEventListener('focusin', () => { widget.focus = { r, c }; });
  }

  /* Hydrate `{{flex …}}` placeholders inside a rendered cell. */
  function hydrate(view, t, r, c, commit, opts, widget) {
    view.querySelectorAll('.flex-inline[data-src]').forEach((ph) => {
      const mount = (spec) => FS.interlinear.render(ph, spec, {
        editable: true, compact: true, inCell: true,
        editCell: () => { const cell = ph.closest('td, th'); if (cell) cell.dispatchEvent(new CustomEvent('cell-edit', { detail: { after: ph } })); },
        duplicate: () => { const src = ph.dataset.src; const i = t.rows[r][c].indexOf(src); t.rows[r][c] = i >= 0 ? t.rows[r][c].slice(0, i + src.length) + ' ' + src + t.rows[r][c].slice(i + src.length) : t.rows[r][c] + ' ' + src; commit(); widget.refresh(); },
        remove: () => { const src = ph.dataset.src; t.rows[r][c] = t.rows[r][c].replace(src, '').replace(/\s{2,}/g, ' ').trim(); commit(); widget.refresh(); },
        onSpecChange: (s) => {
          const ns = FS.flexref.serialize(s);
          const cur = t.rows[r][c];
          if (cur.includes(ph.dataset.src)) t.rows[r][c] = cur.replace(ph.dataset.src, ns);
          else {
            // the placeholder's copy and the cell's source drifted (another edit in between):
            // replace the embed for this GUID, so the change is never silently dropped
            const re = new RegExp('\\{\\{flex:' + s.kind + '\\s+' + s.guid + '[^}]*\\}\\}', 'i');
            t.rows[r][c] = re.test(cur) ? cur.replace(re, ns) : cur + ' ' + ns;
          }
          ph.dataset.src = ns;
          commit();
          mount(s);
        },
      });
      const spec = FS.flexref.parse(ph.dataset.src);
      if (spec) mount(spec);
    });
    view.querySelectorAll('a[data-href]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); opts.openLink && opts.openLink(a.dataset.href); }));
  }

  /* ------------------------------------------------------------------ caret helpers (cells) */
  function insertAtCaret(ed, text) {
    const caret = FS.editor.getCaret(ed), end = FS.editor.getCaretEnd(ed);
    const s = ed.textContent;
    ed.textContent = s.slice(0, caret) + text + s.slice(end);
    ed.innerHTML = FS.markdown.decorate(ed.textContent, 'p');
    FS.editor.setCaret(ed, caret + text.length);
  }
  function wrapSel(ed, m) {
    const a = FS.editor.getCaret(ed), b = FS.editor.getCaretEnd(ed);
    const r = FS.editor.wrapLines(ed.textContent, a, b, m);
    ed.textContent = r.text;
    ed.innerHTML = FS.markdown.decorate(ed.textContent, 'p');
    FS.editor.setCaret(ed, r.a, r.z);
  }

  /* ------------------------------------------------------------------ style popovers */
  const BGS = ['', '#fff2a8', '#ffd6a5', '#caffbf', '#9bf6ff', '#bdb2ff', '#ffadad', '#e9ebef'];
  const FGS = ['', '#c0392b', '#1f7a4d', '#1f4f8f', '#7a3e9d', '#b45309', '#00379c', '#2a6e2a'];

  function propsPopover(anchor, title, props, onChange, extra) {
    FS.popover(anchor, (pop, close) => {
      const render = () => {
        pop.innerHTML = '';
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, title)));
        const tog = (k, label) => el('button', { class: 'tog' + (props[k] ? ' on' : ''), onclick: () => { if (props[k]) delete props[k]; else props[k] = true; onChange(); render(); } }, label);
        pop.appendChild(el('div', { class: 'row' }, tog('bold', 'Bold'), tog('italic', 'Italic'), tog('nowrap', 'No wrap'), tog('vern', 'Vernacular font')));
        const al = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Align'));
        for (const [v, l] of [['left', '←'], ['center', '↔'], ['right', '→']]) al.appendChild(el('button', { class: 'tog' + (props.align === v ? ' on' : ''), onclick: () => { props.align = props.align === v ? undefined : v; if (!props.align) delete props.align; onChange(); render(); } }, l));
        pop.appendChild(al);
        const bg = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Background'));
        for (const c of BGS) bg.appendChild(el('button', { class: 'sw' + ((props.bg || '') === c ? ' on' : ''), style: { background: c || 'var(--bg)' }, title: c || 'none', onclick: () => { if (c) props.bg = c; else delete props.bg; onChange(); render(); } }));
        pop.appendChild(bg);
        const fg = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Text'));
        for (const c of FGS) fg.appendChild(el('button', { class: 'sw' + ((props.color || '') === c ? ' on' : ''), style: { background: c || 'var(--bg)' }, title: c || 'default', onclick: () => { if (c) props.color = c; else delete props.color; onChange(); render(); } }));
        pop.appendChild(fg);
        if (extra) extra(pop, props, onChange, render, close);
      };
      render();
    });
  }

  function colPopover(anchor, t, c, commit, widget) {
    const props = t.style.cols[c + 1] = t.style.cols[c + 1] || {};
    propsPopover(anchor, 'Column ' + (c + 1), props, () => { commit(); widget.refresh(); }, (pop, p, onChange) => {
      const w = el('input', { type: 'text', value: p.width || '', placeholder: 'e.g. 30% or 200px', style: { width: '130px' } });
      w.addEventListener('change', () => { if (w.value.trim()) p.width = w.value.trim(); else delete p.width; onChange(); });
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Width'), w));
    });
  }
  function rowPopover(anchor, t, r, commit, widget) {
    const props = t.style.rows[r + 1] = t.style.rows[r + 1] || {};
    propsPopover(anchor, r === 0 ? 'Header row' : 'Row ' + (r + 1), props, () => { commit(); widget.refresh(); });
  }
  function cellPopover(anchor, t, at, commit, widget) {
    FS.popover(anchor, (pop, close) => {
      const { anchors, covered } = spanMap(t);
      const key = at.r + '.' + at.c;
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Cell ' + (at.r + 1) + ',' + (at.c + 1))));
      const item = (label, fn, disabled) => pop.appendChild(el('button', { class: 'menu-item', disabled: !!disabled, onclick: () => { close(); if (fn()) { commit(); widget.refresh(); } } }, label));
      if (widget.sel && (widget.sel.r1 !== widget.sel.r2 || widget.sel.c1 !== widget.sel.c2)) item('Merge the selected cells', () => mergeRange(t, widget.sel), widget.sel.r1 === 0 && widget.sel.r2 > 0);
      item('Merge with the cell to the right', () => mergeCell(t, at.r, at.c, 'right'), covered.has(key));
      item('Merge with the cell below', () => mergeCell(t, at.r, at.c, 'down'), covered.has(key) || at.r === 0);
      item('Unmerge', () => (widget.sel ? unmergeRange(t, widget.sel) : unmergeCell(t, at.r, at.c)), !(anchors[key] || covered.has(key) || widget.sel));
      pop.appendChild(el('hr'));
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Freeze panes')));
      const frozen = (t.style.freezeRows || 0) + (t.style.freezeCols || 0) > 0;
      item('Freeze panes here (rows above, columns to the left)', () => { t.style.freezeRows = at.r; t.style.freezeCols = at.c; return true; }, at.r === 0 && at.c === 0);
      item('Freeze top row', () => { t.style.freezeRows = 1; return true; });
      item('Freeze first column', () => { t.style.freezeCols = 1; return true; });
      item('Unfreeze panes', () => { t.style.freezeRows = 0; t.style.freezeCols = 0; return true; }, !frozen);
      pop.appendChild(el('div', { class: 'hint' }, 'Merged cells are kept as `span row.col: rows×cols` in the style line; a plain Markdown reader sees the grid with the covered cells empty.'));
    });
  }
  function tablePopover(anchor, t, commit, widget, opts) {
    opts = opts || {};
    FS.popover(anchor, (pop, close) => {
      const render = () => {
        pop.innerHTML = '';
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Table')));
        if (opts.onSplit || opts.onMerge) {
          const row = el('div', { class: 'row' });
          const r = widget.focus ? widget.focus.r : 0;
          if (opts.onSplit) row.appendChild(el('button', { class: 'tog', disabled: r <= 0, title: 'Split the table above the current row, with an empty line between the halves', onclick: () => { close(); opts.onSplit(r); } }, 'Split above row ' + (r + 1)));
          if (opts.onMerge && opts.canMerge) {
            if (opts.canMerge(-1)) row.appendChild(el('button', { class: 'tog', onclick: () => { close(); opts.onMerge(-1); } }, 'Merge with table above'));
            if (opts.canMerge(1)) row.appendChild(el('button', { class: 'tog', onclick: () => { close(); opts.onMerge(1); } }, 'Merge with table below'));
          }
          pop.appendChild(row);
        }
        const flag = (f, label) => el('button', { class: 'tog' + (t.style.flags.has(f) ? ' on' : ''), onclick: () => { t.style.flags.has(f) ? t.style.flags.delete(f) : t.style.flags.add(f); commit(); widget.refresh(); render(); } }, label);
        pop.appendChild(el('div', { class: 'row' }, flag('striped', 'Striped'), flag('header-col', 'Header column'), flag('compact', 'Compact'), flag('full', 'Full width'), flag('wide', 'Wide (scroll sideways)')));
        const at = widget.focus || { r: 0, c: 0 };
        const fz = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Freeze'));
        const fzb = (label, fn, dis, title) => fz.appendChild(el('button', { class: 'tog', disabled: !!dis, title: title || '', onclick: () => { fn(); commit(); widget.refresh(); render(); } }, label));
        fzb('Here', () => { t.style.freezeRows = at.r; t.style.freezeCols = at.c; }, at.r === 0 && at.c === 0, 'Freeze the rows above and the columns to the left of the current cell (like Excel)');
        fzb('Top row', () => { t.style.freezeRows = 1; });
        fzb('First column', () => { t.style.freezeCols = 1; });
        fzb('Unfreeze', () => { t.style.freezeRows = 0; t.style.freezeCols = 0; }, !(t.style.freezeRows || t.style.freezeCols));
        pop.appendChild(fz);
        const fr = el('input', { type: 'number', min: 0, max: 10, value: t.style.freezeRows || 0, style: { width: '56px' } });
        const fc = el('input', { type: 'number', min: 0, max: 10, value: t.style.freezeCols || 0, style: { width: '56px' } });
        const mh = el('input', { type: 'text', value: t.style.maxHeight || '', placeholder: '60vh', style: { width: '70px' } });
        const setFreeze = () => { t.style.freezeRows = +fr.value || 0; t.style.freezeCols = +fc.value || 0; t.style.maxHeight = mh.value.trim(); commit(); widget.refresh(); };
        fr.addEventListener('change', setFreeze); fc.addEventListener('change', setFreeze); mh.addEventListener('change', setFreeze);
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, ''), el('span', { class: 'small muted' }, 'rows'), fr, el('span', { class: 'small muted' }, 'cols'), fc, el('span', { class: 'small muted' }, 'height'), mh));
        pop.appendChild(el('div', { class: 'hint' }, 'Frozen rows and columns stay put while the table scrolls inside its box (set height to e.g. 300px or 60vh).'));
        const b = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Borders'));
        for (const [v, l] of [['', 'Normal'], ['borders-light', 'Light'], ['borders-none', 'None']]) b.appendChild(el('button', { class: 'tog' + ((v ? t.style.flags.has(v) : !t.style.flags.has('borders-light') && !t.style.flags.has('borders-none')) ? ' on' : ''), onclick: () => { t.style.flags.delete('borders-light'); t.style.flags.delete('borders-none'); if (v) t.style.flags.add(v); commit(); widget.refresh(); render(); } }, l));
        pop.appendChild(b);
      };
      render();
    });
  }

  /* ------------------------------------------------------------------ clipboard import
   * Excel, Word and browsers put an HTML <table> on the clipboard next to tab-separated text.
   * Either becomes a table block; inline bold/italic and line breaks inside cells survive. */
  function cellMarkdown(node) {
    let out = '';
    for (const c of node.childNodes) {
      if (c.nodeType === 3) { out += c.nodeValue.replace(/\s+/g, ' '); continue; }
      if (c.nodeType !== 1) continue;
      const tag = c.tagName.toLowerCase();
      if (tag === 'br') { out += '\n'; continue; }
      if (tag === 'script' || tag === 'style') continue;
      const inner = cellMarkdown(c);
      if (!inner.trim()) { out += inner; continue; }
      const fw = (c.style && c.style.fontWeight) || '';
      if (tag === 'b' || tag === 'strong' || /^(bold|[6-9]00)$/.test(fw)) out += '**' + inner.trim() + '**';
      else if (tag === 'i' || tag === 'em' || (c.style && c.style.fontStyle === 'italic')) out += '*' + inner.trim() + '*';
      else if (tag === 'a' && c.getAttribute('href')) out += '[' + inner.trim() + '](' + c.getAttribute('href') + ')';
      else if (tag === 'p' || tag === 'div' || tag === 'li') out += (out && !out.endsWith('\n') ? '\n' : '') + inner;
      else out += inner;
    }
    return out;
  }

  /* The grid of an HTML table: {rows, spans} with merged cells laid out, or null. */
  function htmlGrid(html) {
    if (!html || !/<table[\s>]/i.test(html)) return null;
    let doc;
    try { doc = new DOMParser().parseFromString(html, 'text/html'); } catch (e) { return null; }
    const table = doc.querySelector('table');
    if (!table) return null;
    // Lay the cells out on a grid honouring rowspan / colspan (Excel, Word and browsers all
    // put them on the clipboard as attributes), so merged cells arrive as `span` entries.
    const grid = [];                       // grid[r][c] = text | '' ; taken[r][c] = true when covered
    const taken = [];
    const spans = {};
    const at = (r, c) => (taken[r] && taken[r][c]);
    let r = 0;
    for (const tr of table.querySelectorAll('tr')) {
      if (tr.closest('table') !== table) continue;          // nested tables: keep only the outer grid
      grid[r] = grid[r] || [];
      let c = 0;
      for (const td of tr.children) {
        if (!/^(td|th)$/i.test(td.tagName)) continue;
        while (at(r, c)) c++;
        let text = cellMarkdown(td).replace(/\u00a0/g, ' ').split('\n').map((l) => l.trim()).join('\n').replace(/\n{2,}/g, '\n').trim();
        // Excel/Word style the CELL (font-weight on the td) rather than wrapping the text
        const fw = (td.style && td.style.fontWeight) || '';
        if (text && !text.includes('\n') && !/^\*\*/.test(text) && /^(bold|[6-9]00)$/.test(fw)) text = '**' + text + '**';
        if (text && !text.includes('\n') && td.style && td.style.fontStyle === 'italic' && !/^\*/.test(text)) text = '*' + text + '*';
        const cs = Math.max(1, parseInt(td.getAttribute('colspan') || '1', 10) || 1);
        const rs = Math.max(1, parseInt(td.getAttribute('rowspan') || '1', 10) || 1);
        grid[r][c] = text;
        for (let i = r; i < r + rs; i++) {
          taken[i] = taken[i] || []; grid[i] = grid[i] || [];
          for (let j = c; j < c + cs; j++) { taken[i][j] = true; if (i !== r || j !== c) grid[i][j] = ''; }
        }
        if (cs > 1 || rs > 1) spans[(r + 1) + '.' + (c + 1)] = { rows: rs, cols: cs };
        c += cs;
      }
      r++;
    }
    const rows = grid.map((row) => Array.from(row, (x) => x == null ? '' : x));
    // drop empty rows at the end only (an empty row inside a span keeps its place)
    while (rows.length && rows[rows.length - 1].every((x) => x === '') && !Object.keys(spans).some((k) => { const [ar] = k.split('.').map(Number); const v = spans[k]; return ar + v.rows - 1 >= rows.length; })) rows.pop();
    if (rows.length < 1) return null;
    const w = Math.max(...rows.map((x) => x.length));
    rows.forEach((x) => { while (x.length < w) x.push(''); });
    return { rows, spans };
  }
  function fromHtml(html) {
    const g = htmlGrid(html);
    if (!g) return null;
    const rows = g.rows;
    if (rows.length === 1) rows.push(rows[0].map(() => ''));
    const style = parseStyle('');
    for (const [k, v] of Object.entries(g.spans)) { const [ar] = k.split('.').map(Number); if (ar === 1 && v.rows > 1) { v.rows = 1; if (v.cols < 2) continue; } style.spans[k] = v; }
    return serialize({ rows, aligns: [], style });
  }
  /* Rows of cells out of a clipboard: an HTML table, tab-separated lines, or one value. */
  function clipGrid(dt) {
    if (!dt) return null;
    const g = htmlGrid(dt.getData && dt.getData('text/html'));
    if (g) return g.rows;
    const text = String((dt.getData && dt.getData('text/plain')) || '').replace(/\r\n?/g, '\n').replace(/\n+$/, '');
    if (!text) return null;
    return text.split('\n').map((l) => l.split('\t'));
  }
  const tsvOf = (rows) => rows.map((r) => r.map((x) => String(x == null ? '' : x).replace(/\t/g, ' ')).join('\t')).join('\n');
  const htmlOf = (rows) => '<table>' + rows.map((r) => '<tr>' + r.map((x) => '<td>' + FS.markdown.renderInline(x) + '</td>').join('') + '</tr>').join('') + '</table>';

  function fromTsv(text) {
    const lines = String(text || '').replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n');
    if (lines.length < 2 || !lines.every((l) => l.includes('\t'))) return null;
    const rows = lines.map((l) => l.split('\t').map((c) => c.trim()));
    const w = Math.max(...rows.map((r) => r.length));
    rows.forEach((r) => { while (r.length < w) r.push(''); });
    return serialize({ rows, aligns: [], style: parseStyle('') });
  }

  /* Markdown for a pasted table, or null when the clipboard holds no table. */
  function fromClipboard(dt) {
    if (!dt) return null;
    const html = dt.getData && dt.getData('text/html');
    return fromHtml(html) || fromTsv(dt.getData && dt.getData('text/plain'));
  }

  FS.tables = { spanMap, mergeCell, unmergeCell, mergeRange, unmergeRange, growToSpans, splitAt, mergeTables, htmlGrid, clipGrid, tsvOf, parse, serialize, splitRow, parseStyle, serializeStyle, render, template, fromHtml, fromTsv, fromClipboard, cellMarkdown };
})();
