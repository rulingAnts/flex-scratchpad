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
    const st = { flags: new Set(), cols: {}, rows: {} };
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
        if (fm) st.flags.add('borders-' + fm[1].toLowerCase());
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
    if (col.width) css.width = col.width;
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
    const widget = { t, container, focus: null, insertText: null, refresh: () => render(container, serialize(t), opts) };
    const table = el('table', { class: 'md-table ' + [...t.style.flags].join(' ') });
    const thead = el('thead'), tbody = el('tbody');
    const commit = () => opts.onChange && opts.onChange(serialize(t));
    t.rows.forEach((row, r) => {
      const tr = el('tr');
      row.forEach((cell, c) => {
        const { css, cls } = cellStyle(t, r, c);
        const td = el(r === 0 ? 'th' : 'td', { class: cls.join(' '), style: css, dataset: { r, c } });
        mountCell(td, t, r, c, widget, commit, opts);
        tr.appendChild(td);
      });
      (r === 0 ? thead : tbody).appendChild(tr);
    });
    table.append(thead, tbody);
    container.appendChild(el('div', { class: 'tbl-wrap' }, table));
    // tools
    const tools = el('div', { class: 'tbl-tools' });
    const cur = () => widget.focus || { r: t.rows.length - 1, c: 0 };
    tools.append(
      el('button', { title: 'Add a row below the current one', onclick: () => { const { r } = cur(); t.rows.splice(r + 1, 0, t.rows[0].map(() => '')); shiftRowStyles(t, r + 2, 1); commit(); widget.refresh(); } }, '+ Row'),
      el('button', { title: 'Add a column after the current one', onclick: () => { const { c } = cur(); t.rows.forEach((row) => row.splice(c + 1, 0, '')); t.aligns.splice(c + 1, 0, null); shiftColStyles(t, c + 2, 1); commit(); widget.refresh(); } }, '+ Column'),
      el('button', { title: 'Delete the current row', onclick: () => { const { r } = cur(); if (t.rows.length <= 1 || r === 0) return; t.rows.splice(r, 1); delete t.style.rows[r + 1]; shiftRowStyles(t, r + 2, -1); commit(); widget.refresh(); } }, '− Row'),
      el('button', { title: 'Delete the current column', onclick: () => { const { c } = cur(); if (t.rows[0].length <= 1) return; t.rows.forEach((row) => row.splice(c, 1)); t.aligns.splice(c, 1); delete t.style.cols[c + 1]; shiftColStyles(t, c + 2, -1); commit(); widget.refresh(); } }, '− Column'),
      el('button', { onclick: (e) => colPopover(e.currentTarget, t, cur().c, commit, widget) }, 'Column ▾'),
      el('button', { onclick: (e) => rowPopover(e.currentTarget, t, cur().r, commit, widget) }, 'Row ▾'),
      el('button', { onclick: (e) => tablePopover(e.currentTarget, t, commit, widget) }, 'Table ▾'),
    );
    container.appendChild(tools);
    return widget;
  }

  function shiftRowStyles(t, from, by) { const o = {}; for (const [k, v] of Object.entries(t.style.rows)) o[+k >= from ? +k + by : +k] = v; t.style.rows = o; }
  function shiftColStyles(t, from, by) { const o = {}; for (const [k, v] of Object.entries(t.style.cols)) o[+k >= from ? +k + by : +k] = v; t.style.cols = o; }

  /* A cell shows rendered markdown (embeds hydrated); clicking it edits the source in place. */
  function mountCell(td, t, r, c, widget, commit, opts) {
    const src = () => t.rows[r][c];
    const view = el('div', { class: 'cell-view', html: FS.markdown.renderInline(src()) || '<span class="muted">&nbsp;</span>' });
    hydrate(view, t, r, c, commit, opts);
    td.appendChild(view);
    const startEdit = (offset) => {
      if (td.querySelector('.cell-edit')) return;
      view.remove();
      const ed = el('div', { class: 'cell-edit', contenteditable: 'true', spellcheck: 'true', dir: 'auto' });
      ed.textContent = src();
      ed.innerHTML = FS.markdown.decorate(ed.textContent, 'p') || '';
      td.appendChild(ed);
      widget.focus = { r, c };
      widget.insertText = (text) => { insertAtCaret(ed, text); refresh(); };
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
      ed.addEventListener('input', () => { if (!composing) refresh(); });
      ed.addEventListener('beforeinput', (e) => {
        const it = e.inputType;
        if (it === 'insertParagraph') { e.preventDefault(); finish(); moveTo(r + 1, c, true); return; }
        if (it === 'insertLineBreak') { e.preventDefault(); insertAtCaret(ed, '\n'); refresh(); return; }
        if (it === 'insertFromPaste' || it === 'insertFromDrop') {
          e.preventDefault();
          const text = (e.dataTransfer && e.dataTransfer.getData('text/plain')) || '';
          if (opts.onPasteLink && /silfw:|^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(text.trim())) { opts.onPasteLink(text.trim(), (embed) => { insertAtCaret(ed, embed); refresh(); }); return; }
          insertAtCaret(ed, text.replace(/\r\n?/g, '\n')); refresh(); return;
        }
        if (it === 'formatBold') { e.preventDefault(); wrapSel(ed, '**'); refresh(); return; }
        if (it === 'formatItalic') { e.preventDefault(); wrapSel(ed, '*'); refresh(); return; }
        if (/^(insertText|insertCompositionText|insertReplacementText|deleteContent|deleteWord|deleteByCut|deleteSoftLineBackward|deleteHardLineBackward)/.test(it)) return;
        e.preventDefault();
      });
      ed.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') { e.preventDefault(); finish(); if (e.shiftKey) moveTo(c > 0 ? r : r - 1, c > 0 ? c - 1 : t.rows[0].length - 1); else { if (r === t.rows.length - 1 && c === t.rows[0].length - 1) { t.rows.push(t.rows[0].map(() => '')); commit(); widget.refresh(); setTimeout(() => moveTo(r + 1, 0), 0); return; } moveTo(c < t.rows[0].length - 1 ? r : r + 1, c < t.rows[0].length - 1 ? c + 1 : 0); } }
        else if (e.key === 'Escape') { e.preventDefault(); finish(); td.focus && td.focus(); }
        else if (e.key === 'ArrowUp' && e.altKey) { e.preventDefault(); finish(); moveTo(r - 1, c); }
        else if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); finish(); moveTo(r + 1, c); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); wrapSel(ed, '**'); refresh(); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'i') { e.preventDefault(); wrapSel(ed, '*'); refresh(); }
        e.stopPropagation();
      });
      ed.addEventListener('blur', () => setTimeout(() => { if (ed.isConnected) finish(); }, 0));
      const finish = () => {
        if (!ed.isConnected) return;
        const val = ed.textContent.replace(/\n+$/, '');
        ed.remove();
        if (widget.insertText) widget.insertText = null;
        if (val !== t.rows[r][c]) { t.rows[r][c] = val; commit(); }
        view.innerHTML = FS.markdown.renderInline(t.rows[r][c]) || '<span class="muted">&nbsp;</span>';
        hydrate(view, t, r, c, commit, opts);
        td.appendChild(view);
      };
      const moveTo = (rr, cc, create) => {
        if (rr < 0 || cc < 0) return;
        if (rr >= t.rows.length) { if (!create) return; t.rows.push(t.rows[0].map(() => '')); commit(); widget.refresh(); setTimeout(() => { const cell = widget.container.querySelector('[data-r="' + rr + '"][data-c="' + cc + '"] .cell-view'); if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); }, 0); return; }
        const cell = widget.container.querySelector('[data-r="' + rr + '"][data-c="' + cc + '"] .cell-view');
        if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      };
    };
    view.addEventListener('mousedown', (e) => {
      if (e.target.closest('a, button, .flex-obj, .seg-play')) return;
      if (e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      startEdit();
    });
    td.addEventListener('focusin', () => { widget.focus = { r, c }; });
  }

  /* Hydrate `{{flex …}}` placeholders inside a rendered cell. */
  function hydrate(view, t, r, c, commit, opts) {
    view.querySelectorAll('.flex-inline[data-src]').forEach((ph) => {
      const mount = (spec) => FS.interlinear.render(ph, spec, {
        editable: true, compact: true,
        onSpecChange: (s) => {
          const ns = FS.flexref.serialize(s);
          t.rows[r][c] = t.rows[r][c].replace(ph.dataset.src, ns);
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
    const s = ed.textContent;
    const sel = s.slice(a, b);
    if (sel.startsWith(m) && sel.endsWith(m) && sel.length >= m.length * 2) { ed.textContent = s.slice(0, a) + sel.slice(m.length, -m.length) + s.slice(b); FS.editor.setCaret(ed, a, b - 2 * m.length); }
    else { ed.textContent = s.slice(0, a) + m + sel + m + s.slice(b); FS.editor.setCaret(ed, a + m.length, b + m.length); }
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
  function tablePopover(anchor, t, commit, widget) {
    FS.popover(anchor, (pop, close) => {
      const render = () => {
        pop.innerHTML = '';
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Table')));
        const flag = (f, label) => el('button', { class: 'tog' + (t.style.flags.has(f) ? ' on' : ''), onclick: () => { t.style.flags.has(f) ? t.style.flags.delete(f) : t.style.flags.add(f); commit(); widget.refresh(); render(); } }, label);
        pop.appendChild(el('div', { class: 'row' }, flag('striped', 'Striped'), flag('header-col', 'Header column'), flag('compact', 'Compact'), flag('full', 'Full width')));
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

  function fromHtml(html) {
    if (!html || !/<table[\s>]/i.test(html)) return null;
    let doc;
    try { doc = new DOMParser().parseFromString(html, 'text/html'); } catch (e) { return null; }
    const table = doc.querySelector('table');
    if (!table) return null;
    const rows = [];
    for (const tr of table.querySelectorAll('tr')) {
      if (tr.closest('table') !== table) continue;          // nested tables: keep only the outer grid
      const cells = [];
      for (const td of tr.children) {
        if (!/^(td|th)$/i.test(td.tagName)) continue;
        let text = cellMarkdown(td).replace(/\u00a0/g, ' ').split('\n').map((l) => l.trim()).join('\n').replace(/\n{2,}/g, '\n').trim();
        // Excel/Word style the CELL (font-weight on the td) rather than wrapping the text
        const fw = (td.style && td.style.fontWeight) || '';
        if (text && !text.includes('\n') && !/^\*\*/.test(text) && /^(bold|[6-9]00)$/.test(fw)) text = '**' + text + '**';
        if (text && !text.includes('\n') && td.style && td.style.fontStyle === 'italic' && !/^\*/.test(text)) text = '*' + text + '*';
        cells.push(text);
        const span = parseInt(td.getAttribute('colspan') || '1', 10);
        for (let i = 1; i < span; i++) cells.push('');
      }
      if (cells.some((c) => c !== '')) rows.push(cells);
    }
    if (rows.length < 1) return null;
    const w = Math.max(...rows.map((r) => r.length));
    rows.forEach((r) => { while (r.length < w) r.push(''); });
    if (rows.length === 1) rows.push(rows[0].map(() => ''));
    return serialize({ rows, aligns: [], style: parseStyle('') });
  }

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

  FS.tables = { parse, serialize, splitRow, parseStyle, serializeStyle, render, template, fromHtml, fromTsv, fromClipboard, cellMarkdown };
})();
