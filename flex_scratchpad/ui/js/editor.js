/* editor.js — the block editor.
 *
 * A note is a list of blocks. Text blocks (paragraph, heading, list, quote, code) are
 * contenteditable elements whose textContent IS the markdown; after every input the block is
 * re-decorated (markers faint, bold bold, headings big) and the caret restored by text offset.
 * Chromium's own editing is kept on a short leash through `beforeinput`: plain text in, plain
 * text out, no <div>/<br>/<b> ever injected. Tables, FLEx embeds, charts, images and rules are
 * widgets with their own in-place UI and an "edit source" fallback. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;
  const MD = FS.markdown;

  /* ------------------------------------------------------------------ caret helpers */
  function getCaret(root) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !root.contains(sel.anchorNode)) return root.textContent.length;
    const r = sel.getRangeAt(0).cloneRange();
    r.collapse(true);
    r.setStart(root, 0);
    return r.toString().length;
  }
  function getCaretEnd(root) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !root.contains(sel.focusNode)) return getCaret(root);
    const r = sel.getRangeAt(0).cloneRange();
    r.collapse(false);
    r.setStart(root, 0);
    return r.toString().length;
  }
  function pointAt(root, offset) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n = walker.nextNode(), last = null;
    let acc = 0;
    while (n) {
      const len = n.nodeValue.length;
      if (offset < acc + len || (offset === acc + len && !n.nodeValue.endsWith('\n'))) return { node: n, offset: offset - acc };
      if (offset === acc + len) {
        // right after a line break: put the caret at the START of the next line's span (which
        // may hold only a <br>), never at the tail of the "\n" text node — the "\n" ends the
        // line's own span (markdown.decorate), so the next line is that span's next sibling
        const line = n.parentNode && n.parentNode.closest ? n.parentNode.closest('.md-line') : null;
        const next = line && line.parentNode === root ? line.nextElementSibling : n.nextSibling && n.nextSibling.nodeType === 1 ? n.nextSibling : null;
        if (next) {
          const inner = firstText(next);
          return inner ? { node: inner, offset: 0 } : { node: next, offset: 0 };
        }
        return { node: n, offset: len };
      }
      acc += len;
      last = n;
      n = walker.nextNode();
    }
    if (last) return { node: last, offset: last.nodeValue.length };
    // no text at all: inside the first line span if there is one
    const span = root.firstElementChild;
    return { node: span || root, offset: 0 };
  }
  function firstText(el) {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    return w.nextNode();
  }
  /* Never inside an inline chip (contenteditable=false): the caret goes just before or just
   * after it, which is where typing and Backspace then act as a user expects. */
  function outsideChip(pt) {
    const parent = pt.node.nodeType === 3 ? pt.node.parentNode : pt.node;
    const chip = parent && parent.closest ? parent.closest('.md-embed:not(.reveal-src)') : null;
    if (!chip || !chip.parentNode) return pt;
    const i = [...chip.parentNode.childNodes].indexOf(chip);
    return { node: chip.parentNode, offset: i + (pt.offset > 0 ? 1 : 0) };
  }
  function setCaret(root, start, end) {
    const sel = window.getSelection();
    if (!sel) return;
    const a = outsideChip(pointAt(root, Math.max(0, Math.min(start, root.textContent.length))));
    const b = end == null ? a : outsideChip(pointAt(root, Math.max(0, Math.min(end, root.textContent.length))));
    const r = document.createRange();
    r.setStart(a.node, a.offset);
    r.setEnd(b.node, b.offset);
    sel.removeAllRanges();
    sel.addRange(r);
  }
  function caretRect() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0).cloneRange();
    r.collapse(true);
    let rects = r.getClientRects();
    if (!rects.length) {
      // caret at an empty position: measure a temporary zero-width span
      const span = document.createElement('span');
      span.textContent = '​';
      r.insertNode(span);
      const rr = span.getBoundingClientRect();
      span.remove();
      return rr;
    }
    return rects[0];
  }

  // the kinds "Insert a new block" offers: [kind, label, starting markdown]
  const NEW_BLOCKS = [
    ['p', 'Paragraph', ''], ['h', 'Heading', '## '], ['list', 'Bulleted list', '- '], ['ol', 'Numbered list', '1. '],
    ['task', 'Checklist', '- [ ] '], ['quote', 'Quote', '> '], ['table', 'Table', () => FS.tables.template(3, 3)],
    ['flex', 'FLEx example', ''], ['file', 'Attached file', ''], ['hr', 'Divider', '---'],
  ];
  const TEXT_TYPES = new Set(['p', 'h', 'list', 'quote', 'code']);
  const PLACEHOLDER = 'Write something, or type / for a menu';

  /* ------------------------------------------------------------------ the editor */
  /* With markers hidden, show ONLY the markup that applies at the caret (Seth, 2026-10-18:
   * "whatever character or style markup applies to the current cursor position should be
   * visible, but none of the rest of it … roughly how WhatsApp works"): the markers of every
   * styled run that encloses or touches the caret (nested runs too: at a word that is bold and
   * italic all four show) and the caret line's own heading `###` / quote `>`; a bullet, a
   * number or a checkbox is drawn as its glyph and never as text. Pure DOM: the markers on the
   * caret's line are paired left to right (the same delimiter text; `[`…`](…)`, `[[`…`]]`), and
   * a pair whose span holds the caret reveals; a lone marker (<br>) reveals when touched. */
  function revealMarkers() {
    document.querySelectorAll('.md-marker.reveal').forEach((x) => x.classList.remove('reveal'));
    if (!document.body.classList.contains('md-hide')) return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !sel.anchorNode) return;
    const elOf = (n) => (n.nodeType === 1 ? n : n.parentNode);
    const host = elOf(sel.anchorNode).closest('.blk-body, .cell-edit');
    if (!host) return;
    const line = elOf(sel.anchorNode).closest('.md-line') || host;
    const r = document.createRange();
    r.setStart(line, 0);
    try { r.setEnd(sel.anchorNode, sel.anchorOffset); } catch (e) { return; }
    const caret = r.toString().length;
    const marks = [];
    let pos = 0;
    for (const ch of line.childNodes) {
      const len = ch.textContent.length;
      if (ch.nodeType === 1 && ch.classList.contains('md-marker')) {
        if (pos === 0 && /\bmd-(h\d?|quote-mk)\b/.test(ch.className)) ch.classList.add('reveal');   // the line's own style
        else if (!/\bmd-(bullet|num|task|ind)\b/.test(ch.className)) marks.push({ el: ch, s: pos, e: pos + len, t: ch.textContent });
      }
      pos += len;
    }
    const open = [], pairs = [];
    const take = (t) => { const k = open.map((o) => o.t).lastIndexOf(t); return k >= 0 ? open.splice(k)[0] : null; };
    for (const m of marks) {
      if (m.t === '[' || m.t === '[[') { open.push(m); continue; }
      if (m.t === ']]' || m.t.startsWith('](')) { const o = take(m.t === ']]' ? '[[' : '['); if (o) pairs.push([o, m]); continue; }
      const o = take(m.t);
      if (o) pairs.push([o, m]);
      else if (/^(\*+|_+|~~|==|`+)$/.test(m.t)) open.push(m);
      else pairs.push([m, m]);
    }
    for (const o of open) pairs.push([o, o]);
    for (const [a, z] of pairs) if (caret >= a.s && caret <= z.e) { a.el.classList.add('reveal'); z.el.classList.add('reveal'); }
  }
  document.addEventListener('selectionchange', revealMarkers);

  class Editor {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts || {};
      this.blocks = [];
      this.undo = [];
      this.redo = [];
      this.lastSnap = 0;
      this.composing = false;
      this.findQuery = '';
      this.activeTable = null;      // the table widget whose cell is being edited
      root.classList.add('editor-root');
      // the sticky headings strip lies over the top of the scroller (stickyHeadings below)
      this.sticky = el('div', { id: 'sticky-heads', 'data-test': 'sticky-heads', hidden: true });
      if (root.parentNode) root.parentNode.insertBefore(this.sticky, root);
      this.stickyOn = true;
      root.addEventListener('scroll', () => this.scheduleSticky(), { passive: true });
      // markers hidden: the caret never rests inside a line's hidden prefix (see snapPastPrefix)
      document.addEventListener('selectionchange', () => this.snapPastPrefix());
      if (typeof ResizeObserver === 'function') new ResizeObserver(() => this.scheduleSticky()).observe(root);
      // A click on the page's background (Seth, 2026-10-16: "if I click outside the table, it
      // scrolls to the same position, but deselects the cell/table"): only BELOW the last block
      // does it put the caret at the end of the note; anywhere else it lets go of the cell, the
      // table or the selection and the view stays exactly where it is. The press must start on
      // the background too: a table tool redraws under the pointer, and the release that lands on
      // the background then is not a click there.
      let downOnRoot = false;
      root.addEventListener('mousedown', (e) => { downOnRoot = e.target === root; }, true);
      root.addEventListener('click', (e) => {
        if (e.target !== root || !downOnRoot) return;
        const last = this.blocks[this.blocks.length - 1];
        const r = last && last.el ? last.el.getBoundingClientRect() : null;
        if (!r || e.clientY > r.bottom) { this.focusBlock(this.blocks.length - 1, 'end', true); return; }
        this.keepScroll(() => {
          const ae = document.activeElement;
          if (ae && root.contains(ae) && ae.blur) ae.blur();
          this.clearMsel();
          const sel = window.getSelection();
          if (sel) sel.removeAllRanges();
        });
      });
      root.addEventListener('focusin', (e) => { const w = e.target.closest('.widget'); this.activeTable = w && w._table ? w._table : null; if (w && w._table) this.active = this.blocks.find((b) => b.el === w) || this.active; });
      this.wireDrag(root);
      this.wireMultiSelect(root);
      this.wireInsertMenu(root);
      this.wireGapBar(root);
    }

    /* -- the bar between blocks (Seth, 2026-10-18: "Between blocks an empty line is allowed —
     * in fact, it would be a convenient place for an 'add/remove block' bar similar to the bar
     * at the end of our table") ------------------------------------------------------------
     * One floating strip, `#blk-gap`, shown while the pointer rests in the gap between two
     * blocks (or just above the first / below the last): + Paragraph · + Example · + Table ·
     * + More ▾ insert AT THAT GAP; − Above / − Below remove the neighbouring block (the one it
     * would take is marked while the button is hovered). It lives beside the root (renderAll
     * empties the root) and hides on scroll, during a drag and when the pointer leaves. */
    wireGapBar(root) {
      const pane = root.parentNode;
      if (!pane) return;
      const bar = el('div', { id: 'blk-gap', 'data-test': 'blk-gap', hidden: true });
      pane.appendChild(bar);
      this.gapBar = bar;
      let gap = null, hideT = 0;
      const hide = () => { bar.hidden = true; gap = null; this.root.querySelectorAll('.del-hint').forEach((x) => x.classList.remove('del-hint')); };
      const hideSoon = () => { clearTimeout(hideT); hideT = setTimeout(() => { if (!bar.matches(':hover')) hide(); }, 160); };
      const shown = () => this.blocks.filter((b) => b.el && b.el.isConnected && b.el.offsetParent !== null && !b.hidden);
      // the gap under the pointer: {above, below} blocks (either may be null at the ends)
      const gapAt = (y) => {
        const vis = shown();
        if (!vis.length) return null;
        const pad = 6;
        for (let i = 0; i < vis.length; i++) {
          const r = vis[i].el.getBoundingClientRect();
          const next = vis[i + 1];
          const nr = next ? next.el.getBoundingClientRect() : null;
          if (i === 0 && y < r.top && y > r.top - 14) return { above: null, below: vis[0], y: r.top - 2 };
          if (nr ? (y >= r.bottom - pad && y <= nr.top + pad) : (y >= r.bottom - pad && y <= r.bottom + 18)) return { above: vis[i], below: next || null, y: nr ? (r.bottom + nr.top) / 2 : r.bottom + 2 };
        }
        return null;
      };
      const hint = (b, on) => { if (b && b.el) b.el.classList.toggle('del-hint', !!on); };
      const draw = (g) => {
        gap = g;
        bar.innerHTML = '';
        const ins = (kind) => () => { const g0 = gap; hide(); if (!g0) return; if (g0.above) this.insertNewBlock(g0.above, 'after', kind); else this.insertNewBlock(g0.below, 'before', kind); };
        const rm = (b) => () => { hide(); if (b && this.blocks.includes(b)) this.deleteBlock(b); };
        const btn = (label, title, fn, extra) => el('button', Object.assign({ title, onmousedown: (e) => e.preventDefault(), onclick: fn }, extra || {}), label);
        bar.append(
          btn('+ Paragraph', 'A new paragraph here', ins('p'), { 'data-gap': 'p' }),
          btn('+ Example', 'A FLEx example here (opens the picker)', ins('flex'), { 'data-gap': 'flex' }),
          btn('+ Table', 'A new table here', ins('table'), { 'data-gap': 'table' }),
          btn('+ More \u25BE', 'Any other kind of block here', (e) => {
            const g0 = gap; const anchor = e.currentTarget;
            FS.popover(anchor, (pop, close) => {
              pop.classList.add('menu');
              const b = g0.above || g0.below;
              this.insertSection(pop, close, b);
              pop.querySelectorAll(g0.above ? '[data-ins-where="before"]' : '[data-ins-where="after"]').forEach((x) => x.remove());
              pop.querySelectorAll('.ins-grid .tog').forEach((x) => { x.textContent = 'Insert'; });
            });
          }, { 'data-gap': 'more' }));
        if (g.above || g.below) bar.appendChild(el('span', { class: 'gap-sep' }));
        if (g.above) bar.appendChild(btn('\u2212 Above', 'Remove the block above this line', rm(g.above), { 'data-gap': 'rm-above', onmouseenter: () => hint(g.above, true), onmouseleave: () => hint(g.above, false) }));
        if (g.below) bar.appendChild(btn('\u2212 Below', 'Remove the block below this line', rm(g.below), { 'data-gap': 'rm-below', onmouseenter: () => hint(g.below, true), onmouseleave: () => hint(g.below, false) }));
        const pr = pane.getBoundingClientRect();
        bar.hidden = false;
        bar.style.top = Math.round(g.y - pr.top - bar.offsetHeight / 2) + 'px';
        const rr = root.getBoundingClientRect();
        bar.style.left = Math.round(rr.left - pr.left + rr.width / 2 - bar.offsetWidth / 2) + 'px';
      };
      root.addEventListener('mousemove', (e) => {
        if (FS.drag || e.buttons) { if (!bar.hidden) hide(); return; }
        const g = gapAt(e.clientY);
        if (!g) { if (!bar.hidden) hideSoon(); return; }
        clearTimeout(hideT);
        if (gap && gap.above === g.above && gap.below === g.below && !bar.hidden) return;
        draw(g);
      });
      root.addEventListener('mouseleave', () => hideSoon());
      bar.addEventListener('mouseleave', () => hideSoon());
      bar.addEventListener('mouseenter', () => clearTimeout(hideT));
      root.addEventListener('scroll', () => { if (!bar.hidden) hide(); }, { passive: true });
      root.addEventListener('dragstart', () => hide());
      root.addEventListener('keydown', () => { if (!bar.hidden) hide(); });
    }

    /* -- selecting across blocks (Seth, 2026-10-16) --------------------------------------
     * Chromium keeps a mouse selection inside the editable block it started in, so a selection
     * that spans blocks is ours: {a: {b, off}, z: {b, off}} in document order — partial text at
     * either end, whole blocks (text, tables, examples, lists) between — painted with the CSS
     * highlight API (no DOM change) plus a class on fully covered blocks. Cut / copy / delete /
     * type-over / paste / Enter act on it; Shift+click and Shift+Arrow Up/Down extend it;
     * Ctrl+A with a whole block already selected takes the whole note. */
    /* Right-click on a block that is not running text (an example, a chart, a divider…) or in
     * the space between / after blocks: the "Insert a new block" menu. Text keeps the browser's
     * own menu (spelling, copy, paste); a table's cells have theirs, which ends with the same
     * section. */
    wireInsertMenu(root) {
      root.addEventListener('contextmenu', (e) => {
        if (e.defaultPrevented) return;
        const t = e.target;
        if (t.closest && t.closest('.blk-body, input, textarea, select, a, .popover, .modal, .cell-edit')) return;
        const sel = window.getSelection();
        if (sel && !sel.isCollapsed && root.contains(sel.anchorNode)) return;     // selected text: the browser's Copy
        let b = this.blocks.find((x) => x.el && x.el.contains(t));
        let where = 'after';
        if (!b) {                                          // between blocks: the nearest one above the point
          const above = this.blocks.filter((x) => x.el && x.el.getBoundingClientRect().bottom <= e.clientY + 1);
          b = above.length ? above[above.length - 1] : this.blocks[0];
          where = above.length ? 'after' : 'before';
          if (!b) { e.preventDefault(); this.insertNewBlock(null, 'after', 'p'); return; }
        }
        e.preventDefault();
        FS.popoverAt(e.clientX, e.clientY, (pop, close) => {
          pop.classList.add('menu');
          this.insertSection(pop, close, b);
          if (where === 'before') pop.querySelectorAll('[data-ins-where="after"]').forEach((x) => x.remove());
        });
      });
    }
    wireMultiSelect(root) {
      this.msel = null;
      let drag = null;
      const skip = (t) => t.closest && t.closest('.blk-handle, .widget-bar, .drag-handle, .col-resizer, .row-resizer, .tbl-grip, th.gutter, button, a, input, select, textarea, .popover, .flex-overlay, .modal');
      root.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || skip(e.target)) return;
        const pt = this.pointAtEvent(e);
        if (e.shiftKey && pt) {
          const anchor = this.msel ? this.msel.anchor : this.caretPoint();
          if (anchor && anchor.b !== pt.b) { e.preventDefault(); e.stopPropagation(); this.setMsel(anchor, pt); return; }
        }
        this.clearMsel();
        if (pt) drag = { anchor: pt, started: false };
      }, true);
      document.addEventListener('mousemove', (e) => {
        if (!drag) return;
        if (!(e.buttons & 1)) { drag = null; return; }
        const pt = this.pointAtEvent(e);
        if (!pt) return;
        if (!drag.started && pt.b === drag.anchor.b) return;          // inside the first block: the native selection
        drag.started = true;
        e.preventDefault();
        this.setMsel(drag.anchor, pt);
      });
      document.addEventListener('mouseup', () => { drag = null; });
      root.addEventListener('keydown', (e) => this.onMselKey(e), true);
      root.addEventListener('copy', (e) => { if (!this.msel) return; e.preventDefault(); e.stopPropagation(); e.clipboardData.setData('text/plain', this.selectionMarkdown()); }, true);
      root.addEventListener('cut', (e) => { if (!this.msel) return; e.preventDefault(); e.stopPropagation(); e.clipboardData.setData('text/plain', this.selectionMarkdown()); this.deleteSelection(); }, true);
      root.addEventListener('paste', (e) => {
        if (!this.msel) return;
        e.preventDefault(); e.stopPropagation();
        const dt = e.clipboardData;
        const html = dt && dt.getData('text/html'), text = (dt && dt.getData('text/plain')) || '';
        const at = this.deleteSelection();
        if (!at) return;
        const table = FS.tables.fromHtml(html);
        if (table) this.insertBlockSourceAtCaret(at.body, at.b, table); else if (text) this.pasteText(at.body, at.b, text.replace(/\r\n?/g, '\n'));
      }, true);
      root.addEventListener('beforeinput', (e) => { if (this.msel && /^(insertText|insertCompositionText)$/.test(e.inputType)) { e.preventDefault(); const at = this.deleteSelection(); if (at && e.data) this.insertTextAtCaret(at.body, at.b, e.data); } }, true);
    }
    /* The block and text offset under a mouse event; a widget counts whole (off 0 / Infinity
     * decided by its side in setMsel). Outside every block: the nearest one by height. */
    pointAtEvent(e) {
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      let blkEl = hit && hit.closest ? hit.closest('.blk') : null;
      if (blkEl && !this.root.contains(blkEl)) blkEl = null;
      let b = blkEl && this.blocks.find((x) => x.el === blkEl);
      if (!b) {
        if (!hit || !this.root.contains(hit)) return null;
        let best = null, dist = Infinity;
        for (const x of this.blocks) { if (!x.el) continue; const r = x.el.getBoundingClientRect(); const d = e.clientY < r.top ? r.top - e.clientY : e.clientY > r.bottom ? e.clientY - r.bottom : 0; if (d < dist) { dist = d; best = x; } }
        if (!best) return null;
        const r = best.el.getBoundingClientRect();
        return { b: best, off: e.clientY < r.top + r.height / 2 ? 0 : Infinity };
      }
      if (TEXT_TYPES.has(b.type)) {
        const body = b.el.querySelector('.blk-body');
        const r = document.caretRangeFromPoint ? document.caretRangeFromPoint(e.clientX, e.clientY) : null;
        if (r && body.contains(r.startContainer)) { const rr = r.cloneRange(); rr.setStart(body, 0); return { b, off: rr.toString().length }; }
        const br = body.getBoundingClientRect();
        return { b, off: e.clientY < br.top + br.height / 2 ? 0 : body.textContent.length };
      }
      const r = b.el.getBoundingClientRect();
      return { b, off: e.clientY < r.top + r.height / 2 ? 0 : Infinity };
    }
    caretPoint() {
      const b = this.active;
      if (!b || !this.blocks.includes(b)) return null;
      if (!TEXT_TYPES.has(b.type)) return { b, off: 0 };
      const body = b.el && b.el.querySelector('.blk-body');
      return body ? { b, off: getCaret(body) } : null;
    }
    setMsel(p, q) {
      const ip = this.blocks.indexOf(p.b), iq = this.blocks.indexOf(q.b);
      if (ip < 0 || iq < 0) return;
      if (ip === iq && TEXT_TYPES.has(p.b.type)) {                       // one text block: the native selection does it
        this.clearMsel();
        const body = p.b.el.querySelector('.blk-body');
        body.focus(); setCaret(body, Math.min(p.off, q.off), Math.max(p.off, q.off));
        return;
      }
      let a = p, z = q;
      if (ip > iq || (ip === iq && p.off > q.off)) { a = q; z = p; }
      a = { b: a.b, off: TEXT_TYPES.has(a.b.type) ? Math.max(0, Math.min(a.off, a.b.src.length)) : 0 };
      z = { b: z.b, off: TEXT_TYPES.has(z.b.type) ? Math.max(0, Math.min(z.off, z.b.src.length)) : Infinity };
      this.msel = { anchor: p, a, z };
      const sel = window.getSelection();
      if (sel) sel.removeAllRanges();
      this.paintMsel();
    }
    paintMsel() {
      this.root.querySelectorAll('.msel-block').forEach((x) => x.classList.remove('msel-block'));
      const m = this.msel;
      const canHL = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined';
      if (!m) { if (canHL) CSS.highlights.delete('fs-msel'); return; }
      const ia = this.blocks.indexOf(m.a.b), iz = this.blocks.indexOf(m.z.b);
      const ranges = [];
      for (let i = ia; i <= iz; i++) {
        const b = this.blocks[i];
        if (!b.el) continue;
        const text = TEXT_TYPES.has(b.type);
        const body = text ? b.el.querySelector('.blk-body') : null;
        const from = i === ia && text ? m.a.off : 0;
        const to = i === iz && text ? m.z.off : Infinity;
        if (!text || (from === 0 && to >= b.src.length)) b.el.classList.add('msel-block');
        if (!canHL || !body) continue;
        try {
          const r = document.createRange();
          const s = pointAt(body, Math.min(from, body.textContent.length)), e = pointAt(body, Math.min(to, body.textContent.length));
          r.setStart(s.node, s.offset); r.setEnd(e.node, e.offset);
          ranges.push(r);
        } catch (err) { /* a range that cannot be built is just not painted */ }
      }
      if (canHL) CSS.highlights.set('fs-msel', new Highlight(...ranges));
    }
    clearMsel() {
      if (!this.msel) return;
      this.msel = null;
      this.paintMsel();
    }
    selectAll() {
      if (!this.blocks.length) return;
      const last = this.blocks[this.blocks.length - 1];
      this.setMsel({ b: this.blocks[0], off: 0 }, { b: last, off: TEXT_TYPES.has(last.type) ? last.src.length : Infinity });
    }
    /* The selected markdown: the ends partial (text), everything between whole. */
    selectionMarkdown() {
      const m = this.msel;
      if (!m) return '';
      const ia = this.blocks.indexOf(m.a.b), iz = this.blocks.indexOf(m.z.b);
      const out = [];
      for (let i = ia; i <= iz; i++) {
        const b = this.blocks[i];
        let src = b.src;
        if (TEXT_TYPES.has(b.type)) {
          const from = i === ia ? m.a.off : 0, to = i === iz ? m.z.off : src.length;
          src = src.slice(from, to);
        }
        out.push(src);
      }
      return out.join('\n\n');
    }
    /* Remove the selection; the text before it and after it meet in one block. Returns the
     * caret {body, b, off} there, or null. */
    deleteSelection() {
      const m = this.msel;
      if (!m) return null;
      const ia = this.blocks.indexOf(m.a.b), iz = this.blocks.indexOf(m.z.b);
      const prefix = TEXT_TYPES.has(m.a.b.type) ? m.a.b.src.slice(0, m.a.off) : '';
      const suffix = TEXT_TYPES.has(m.z.b.type) ? m.z.b.src.slice(Math.min(m.z.off, m.z.b.src.length)) : '';
      const joined = prefix + suffix;
      let parts = MD.splitBlocks(joined).map((x) => Object.assign({ id: FS.uid() }, x));
      if (!parts.length) parts = [{ id: FS.uid(), type: 'p', src: '' }];
      if (parts.length === 1 && TEXT_TYPES.has(parts[0].type)) parts[0].src = joined;   // keep the exact text, spaces and all
      this.blocks.splice(ia, iz - ia + 1, ...parts);
      this.msel = null;
      this.renderAll();
      this.paintMsel();
      this.changed({ force: true });
      const b = parts[0];
      const i = this.blocks.indexOf(b);
      if (TEXT_TYPES.has(b.type)) { this.focusBlock(i, prefix.length); return { body: b.el.querySelector('.blk-body'), b, off: prefix.length }; }
      this.focusBlock(i, 0);
      return null;
    }
    onMselKey(e) {
      const mod = e.ctrlKey || e.metaKey;
      if (e.altKey && e.shiftKey && !mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        if (e.target.closest && e.target.closest('.cell-edit, input, textarea, select')) return;
        e.preventDefault(); e.stopPropagation();
        this.moveSelection(e.key === 'ArrowUp' ? -1 : 1);
        return;
      }
      if (mod && e.key.toLowerCase() === 'a' && !e.shiftKey && !e.altKey) {
        // Ctrl+A: the block first (native), the whole note the second time or from a focused
        // widget; never inside a table cell's editor or a form field (theirs)
        if (e.target.closest && e.target.closest('.cell-edit, input, textarea, select')) return;
        const b = this.active;
        const body = b && b.el && b.el.querySelector('.blk-body');
        const whole = body && getCaret(body) === 0 && getCaretEnd(body) === body.textContent.length && body.textContent.length > 0;
        const onWidget = b && b.el && e.target === b.el;
        if (this.msel || whole || onWidget) { e.preventDefault(); e.stopPropagation(); this.selectAll(); }
        return;
      }
      if (!this.msel) return;
      if (e.key === 'Escape') { e.preventDefault(); this.clearMsel(); return; }
      if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); this.deleteSelection(); return; }
      if (mod && e.key.toLowerCase() === 'c' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); FS.copyText(this.selectionMarkdown()); return; }
      if (mod && e.key.toLowerCase() === 'x' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); FS.copyText(this.selectionMarkdown()); this.deleteSelection(); return; }
      if (mod && e.key.toLowerCase() === 'v') return;                          // the paste handler takes it
      if (mod && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) { this.clearMsel(); return; }
      if (e.shiftKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault(); e.stopPropagation();
        const m = this.msel;
        const moving = (m.anchor.b === m.a.b && m.anchor.off === m.a.off) ? 'z' : 'a';
        const cur = m[moving];
        const i = this.blocks.indexOf(cur.b) + (e.key === 'ArrowDown' ? 1 : -1);
        if (i < 0 || i >= this.blocks.length) return;
        const nb = this.blocks[i];
        const pt = { b: nb, off: e.key === 'ArrowDown' ? (TEXT_TYPES.has(nb.type) ? nb.src.length : Infinity) : 0 };
        this.setMsel(m.anchor, pt);
        return;
      }
      if (e.key === 'Enter' && !mod) { e.preventDefault(); e.stopPropagation(); const at = this.deleteSelection(); if (at) this.enter(at.body, at.b); return; }
      if (e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End' || e.key === 'PageUp' || e.key === 'PageDown' || e.key === 'Tab') { this.clearMsel(); return; }
      if (e.key.length === 1 && !mod && !e.altKey) { e.preventDefault(); e.stopPropagation(); const at = this.deleteSelection(); if (at) this.insertTextAtCaret(at.body, at.b, e.key); }
    }

    /* -- dragging FLEx objects around the note (Seth, 2026-10-16) ------------------------
     * Sources: a block object (its ⠿ handle or chip), an inline chip in text, an object in a
     * table cell. Targets: a spot in a line of text (inline), a table cell, or between blocks
     * (a block of its own; dropping on a block's top/bottom half re-orders). A drag MOVES;
     * Ctrl (or Alt) copies. Everything is string surgery on the markdown, then a redraw. */
    wireDrag(root) {
      root.addEventListener('dragstart', (e) => {
        const grip = e.target && e.target.closest ? e.target.closest('.blk-handle button') : null;
        if (grip && root.contains(grip)) {
          const blkEl = grip.closest('.blk');
          const b = this.blocks.find((x) => x.el === blkEl);
          if (!b) return;
          const [a, z] = this.blockRangeFor(b);
          document.querySelectorAll('.popover').forEach((p) => p._close && p._close());
          FS.drag = { type: 'blocks', ids: this.blocks.slice(a, z + 1).map((x) => x.id) };
          e.dataTransfer.effectAllowed = 'copyMove';
          e.dataTransfer.setData('application/x-fs-blocks', String(z - a + 1));
          e.dataTransfer.setData('text/plain', MD.joinBlocks(this.blocks.slice(a, z + 1)));
          try { e.dataTransfer.setDragImage(blkEl, 12, 12); } catch (err) { /* not everywhere */ }
          for (let i = a; i <= z; i++) if (this.blocks[i].el) this.blocks[i].el.classList.add('dragging');
          return;
        }
        const h = e.target && e.target.closest ? e.target.closest('.md-embed, .flex-collapsed, .drag-handle') : null;
        if (!h || !root.contains(h)) return;
        const from = this.dragSourceOf(h);
        if (!from) return;
        FS.drag = from;
        e.dataTransfer.effectAllowed = 'copyMove';
        e.dataTransfer.setData('application/x-flex-embed', from.src);
        e.dataTransfer.setData('text/plain', from.src);
        (h.closest('.flex-obj') || h).classList.add('dragging');
      });
      root.addEventListener('dragend', () => { this.clearDropMarks(); document.querySelectorAll('.dragging').forEach((x) => x.classList.remove('dragging')); FS.drag = null; });
      root.addEventListener('dragover', (e) => {
        if (FS.drag && FS.drag.type === 'blocks') {
          const to = this.blockDropAt(e);
          if (!to) { this.clearDropMarks(); return; }
          e.preventDefault();
          e.dataTransfer.dropEffect = (e.ctrlKey || e.altKey) ? 'copy' : 'move';
          this.markDrop(to);
          return;
        }
        if (FS.files && FS.files.hasFiles(e.dataTransfer) && !FS.drag) {
          // files from Explorer: attached where they land; Alt links instead of copying
          const to = this.dropTargetAt(e);
          if (!to) { this.clearDropMarks(); return; }
          e.preventDefault();
          e.dataTransfer.dropEffect = e.altKey ? 'link' : 'copy';
          this.markDrop(to);
          return;
        }
        if (!this.dragPayload(e)) return;
        const to = this.dropTargetAt(e);
        if (!to) { this.clearDropMarks(); return; }
        e.preventDefault();
        e.dataTransfer.dropEffect = (e.ctrlKey || e.altKey) ? 'copy' : 'move';
        this.markDrop(to);
      });
      root.addEventListener('dragleave', (e) => { if (!e.relatedTarget || !root.contains(e.relatedTarget)) this.clearDropMarks(); });
      root.addEventListener('drop', (e) => {
        if (FS.drag && FS.drag.type === 'blocks') {
          const to = this.blockDropAt(e);
          this.clearDropMarks();
          const ids = FS.drag.ids;
          FS.drag = null;
          if (!to) return;
          e.preventDefault(); e.stopPropagation();
          const idx = ids.map((id) => this.blocks.findIndex((x) => x.id === id)).filter((i) => i >= 0);
          if (idx.length) this.moveBlocksTo(Math.min(...idx), Math.max(...idx), to.index, !!(e.ctrlKey || e.altKey));
          return;
        }
        if (FS.files && !FS.drag && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          const to = this.dropTargetAt(e);
          this.clearDropMarks();
          if (!to) return;
          e.preventDefault();             // no stopPropagation: pywebview's own drop handler must see it (the files' paths)
          this.dropFiles([...e.dataTransfer.files], to, !!e.altKey || e.dataTransfer.dropEffect === 'link');
          return;
        }
        const payload = this.dragPayload(e, true);
        if (!payload) return;
        const to = this.dropTargetAt(e);
        this.clearDropMarks();
        if (!to) return;
        e.preventDefault(); e.stopPropagation();
        const from = FS.drag && FS.drag.src === payload ? FS.drag : null;
        this.moveEmbed(from, to, payload, !!(e.ctrlKey || e.altKey));
        FS.drag = null;
      });
    }
    /* Files dropped on the note (Seth, 2026-10-17): copied into the notebook's attachments/ (or
     * linked, with Alt) and put where they were dropped — in the line, in the table cell, or as
     * blocks of their own between blocks. */
    async dropFiles(files, to, link) {
      const srcs = await FS.files.fromFiles(files, link);
      if (!srcs.length || !this.blocks.includes(to.b || this.blocks[0])) return;
      if (to.type === 'between') {
        const at = Math.max(0, Math.min(to.index, this.blocks.length));
        this.blocks.splice(at, 0, ...srcs.map((src) => ({ id: FS.uid(), type: 'flex', src })));
        this.renderAll();
        this.changed({ force: true });
        return;
      }
      const joined = srcs.join(' ');
      if (to.type === 'cell') {
        const w = to.b.el && to.b.el._table;
        if (w) w.insertInto(to.r, to.c, joined, to.caret);
        this.changed({ force: true });
        return;
      }
      const s = to.b.src;
      const a = Math.max(0, Math.min(to.offset, s.length));
      const padL = a > 0 && !/\s$/.test(s.slice(0, a)) ? ' ' : '';
      const padR = a < s.length && !/^\s/.test(s.slice(a)) ? ' ' : '';
      to.b.src = s.slice(0, a) + padL + joined + padR + s.slice(a);
      this.redrawText(to.b);
      this.changed({ force: true });
      this.resplit(to.b);                          // a file alone on its line becomes a card
    }
    /* Where dragged blocks would land: before or after the block under the pointer (its top or
     * bottom half), never inside what is being dragged; below the last block at the end. */
    blockDropAt(e) {
      const ids = (FS.drag && FS.drag.ids) || [];
      const el0 = e.target && e.target.nodeType === 1 ? e.target : (e.target && e.target.parentNode);
      if (!el0 || !el0.closest) return null;
      const blkEl = el0.closest('.blk');
      const b = blkEl && this.root.contains(blkEl) ? this.blocks.find((x) => x.el === blkEl) : null;
      if (!b) return el0 === this.root ? { type: 'between', index: this.blocks.length, el: this.blocks.length ? this.blocks[this.blocks.length - 1].el : null, after: true } : null;
      if (ids.includes(b.id)) return null;
      const rect = blkEl.getBoundingClientRect();
      const after = e.clientY > rect.top + rect.height / 2;
      let index = this.blocks.indexOf(b) + (after ? 1 : 0);
      // after a closed heading means after its section
      if (after && b.type === 'h' && b.folded) index = MD.sectionEnd(this.blocks, this.blocks.indexOf(b)) + 1;
      return { type: 'between', index, el: blkEl, after };
    }
    dragPayload(e, final) {
      if (FS.drag && FS.drag.src) return FS.drag.src;
      const types = e.dataTransfer ? [...(e.dataTransfer.types || [])] : [];
      if (!types.includes('application/x-flex-embed')) return null;
      return final ? (e.dataTransfer.getData('application/x-flex-embed') || null) : '{{flex:…}}';   // data is unreadable until the drop
    }
    dragSourceOf(h) {
      const blkEl = h.closest('.blk');
      const b = blkEl && this.blocks.find((x) => x.el === blkEl);
      if (!b) return null;
      const inline = h.closest('.md-embed');
      const td = h.closest('td[data-r], th[data-r]');
      if (td && b.type === 'table') {
        const wrap = h.closest('.flex-inline');
        const src = inline ? inline.dataset.src : wrap ? wrap.dataset.src : null;
        return src ? { type: 'cell', b, r: +td.dataset.r, c: +td.dataset.c, src } : null;
      }
      if (inline) return { type: 'inline', b, src: inline.dataset.src };
      if (b.type === 'flex') return { type: 'block', b, src: b.src.trim() };
      return null;
    }
    dropTargetAt(e) {
      const el0 = e.target && e.target.nodeType === 1 ? e.target : (e.target && e.target.parentNode);
      if (!el0 || !el0.closest) return null;
      const blkEl = el0.closest('.blk');
      const b = blkEl && this.blocks.find((x) => x.el === blkEl);
      const td = el0.closest('td[data-r], th[data-r]');
      const pointRange = () => (document.caretRangeFromPoint ? document.caretRangeFromPoint(e.clientX, e.clientY) : null);
      if (td && b && b.type === 'table') {
        const ed = td.querySelector('.cell-edit');
        let caret = null;
        if (ed) { const r = pointRange(); if (r && ed.contains(r.startContainer)) { const rr = r.cloneRange(); rr.setStart(ed, 0); caret = rr.toString().length; } }
        return { type: 'cell', b, r: +td.dataset.r, c: +td.dataset.c, caret, el: td };
      }
      if (b && TEXT_TYPES.has(b.type) && b.type !== 'code') {
        const body = blkEl.querySelector('.blk-body');
        let offset = body.textContent.length;
        const r = pointRange();
        if (r && body.contains(r.startContainer)) {
          const rr = r.cloneRange(); rr.setStart(body, 0); offset = rr.toString().length;
          const n = r.startContainer.nodeType === 3 ? r.startContainer.parentNode : r.startContainer;
          const chip = n.closest ? n.closest('.md-embed') : null;
          if (chip && body.contains(chip)) { const r2 = document.createRange(); r2.setStart(body, 0); r2.setEndAfter(chip); offset = r2.toString().length; }
        }
        return { type: 'text', b, offset, el: body };
      }
      if (b) {
        const rect = blkEl.getBoundingClientRect();
        const after = e.clientY > rect.top + rect.height / 2;
        return { type: 'between', index: this.blocks.indexOf(b) + (after ? 1 : 0), el: blkEl, after };
      }
      if (el0 === this.root) return { type: 'between', index: this.blocks.length, el: this.blocks.length ? this.blocks[this.blocks.length - 1].el : null, after: true };
      return null;
    }
    markDrop(to) {
      this.clearDropMarks();
      if (to.type === 'cell') to.el.classList.add('drop-target');
      else if (to.type === 'text') to.el.classList.add('drop-text');
      else if (to.el) to.el.classList.add(to.after ? 'drop-after' : 'drop-before');
    }
    clearDropMarks() {
      this.root.querySelectorAll('.drop-target, .drop-text, .drop-before, .drop-after').forEach((x) => x.classList.remove('drop-target', 'drop-text', 'drop-before', 'drop-after'));
    }
    redrawText(b) {
      const body = b.el && b.el.querySelector('.blk-body');
      if (body) { this.decorateInto(body, b); this.renumberAfter(b); }
    }
    /* Take an embed out of `from` (unless copying) and put it at `to`. */
    moveEmbed(from, to, src, copy) {
      src = String((from && from.src) || src || '').trim();
      if (!FS.flexref.isEmbedLine(src)) return;
      const target = Object.assign({}, to);
      const cut = (s, i) => {                    // remove src at i, closing the gap it leaves; → [text, removed length]
        let before = s.slice(0, i), after = s.slice(i + src.length), removed = src.length;
        if (/[ \t]$/.test(before) && /^[ \t]/.test(after)) { after = after.replace(/^[ \t]/, ''); removed += 1; }
        else if (/[ \t]$/.test(before) && (after === '' || after.startsWith('\n'))) { before = before.replace(/[ \t]+$/, ''); removed += s.slice(0, i).length - before.length; }
        return [before + after, removed];
      };
      let blocksChanged = false;
      if (from && !copy) {
        if (from.type === 'block') {
          const i = this.blocks.indexOf(from.b);
          if (i >= 0) {
            if (target.type === 'between' && target.index > i) target.index -= 1;
            this.blocks.splice(i, 1);
            if (from.b.el) from.b.el.remove();
            blocksChanged = true;
          }
        } else if (from.type === 'inline') {
          const i = from.b.src.indexOf(src);
          if (i >= 0) {
            const [next, removed] = cut(from.b.src, i);
            from.b.src = next;
            if (target.type === 'text' && target.b === from.b && target.offset > i) target.offset = Math.max(i, target.offset - removed);
            if (!(target.type === 'text' && target.b === from.b)) this.redrawText(from.b);
          }
        } else if (from.type === 'cell') {
          const w = from.b.el && from.b.el._table;
          const cur = w ? (w.t.rows[from.r][from.c] || '') : '';
          const i = cur.indexOf(src);
          if (w && i >= 0) {
            const [next, removed] = cut(cur, i);
            w.t.rows[from.r][from.c] = next.trim() === '' ? '' : next;
            const sameCell = target.type === 'cell' && target.b === from.b && target.r === from.r && target.c === from.c;
            if (sameCell && target.caret != null && target.caret > i) target.caret = Math.max(i, target.caret - removed);
            if (!(target.type === 'cell' && target.b === from.b)) w.setCell(from.r, from.c, w.t.rows[from.r][from.c]);
          }
        }
      }
      if (target.type === 'text') {
        const s = target.b.src;
        const a = Math.max(0, Math.min(target.offset, s.length));
        const padL = a > 0 && !/\s$/.test(s.slice(0, a)) ? ' ' : '';
        const padR = a < s.length && !/^\s/.test(s.slice(a)) ? ' ' : '';
        target.b.src = s.slice(0, a) + padL + src + padR + s.slice(a);
        this.redrawText(target.b);
        this.changed({ force: true });
        if (blocksChanged) this.renderAll();
        this.resplit(target.b);                    // an embed alone on its line becomes a block
        return;
      }
      if (target.type === 'cell') {
        const w = target.b.el && target.b.el._table;
        if (w) w.insertInto(target.r, target.c, src, target.caret);
        if (blocksChanged) { this.renderAll(); }
        this.changed({ force: true });
        return;
      }
      const nb = { id: FS.uid(), type: 'flex', src };
      this.blocks.splice(Math.max(0, Math.min(target.index, this.blocks.length)), 0, nb);
      this.renderAll();
      this.changed({ force: true });
    }

    /* -- model ------------------------------------------------------------------ */
    load(md) {
      this.blocks = MD.splitBlocks(md || '').map((b) => Object.assign({ id: FS.uid() }, b));
      if (!this.blocks.length) this.blocks.push({ id: FS.uid(), type: 'p', src: '' });
      this.undo = []; this.redo = [];
      this.renderAll();
      this.pushSnapshot(true);
    }
    getMarkdown() { return MD.joinBlocks(this.blocks); }
    changed(opts) {
      opts = opts || {};
      if (!opts.silent) this.pushSnapshot(opts.force);
      this.renumberExamples();
      this.applyFolds();
      // never leave the caret in a hidden block (a heading turned into text inside a closed
      // section, say): open what hides it
      const act = document.activeElement, host = act && act.closest ? act.closest('.blk.fold-hidden') : null;
      if (host && this.root.contains(host)) { const hb = this.blocks.find((x) => x.el === host); if (hb) this.reveal(hb); }
      if (this.opts.onChange) this.opts.onChange(this.getMarkdown());
    }

    /* -- rendering --------------------------------------------------------------- */
    /* Run `fn` and leave the view where it was (Seth, 2026-10-16: "I don't want the scroll
     * jumping to the end of the document after edits or de-select/focus change"). The position
     * is put back at once and on the next two frames, which covers a blur, a widget's redraw and
     * a focus the browser moves on its own. Explicit navigation (focusBlock, Find) is not wrapped. */
    keepScroll(fn) {
      const sc = this.root;
      const top = sc.scrollTop, left = sc.scrollLeft;
      let out;
      try { out = fn(); } finally {
        const put = () => { if (sc.scrollTop !== top) sc.scrollTop = top; if (sc.scrollLeft !== left) sc.scrollLeft = left; };
        put();
        requestAnimationFrame(() => { put(); requestAnimationFrame(put); });
      }
      return out;
    }
    renderAll() {
      // a rebuild empties the page for a moment, which would clamp the scroll position to the top
      const sc = this.root, top = sc.scrollTop;
      this.root.innerHTML = '';
      this.assignNumCtx();
      this.blocks.forEach((b, i) => this.root.appendChild(this.renderBlock(b, i)));
      this.renumberExamples();
      this.applyFolds();
      sc.scrollTop = top;
    }
    /* -- collapsible headings (Seth, 2026-10-16) ----------------------------------------
     * A heading folds everything after it up to the next heading of the same or a higher level.
     * The state is the block's `folded` flag (" {collapsed}" in the file, markdown.js); hidden
     * blocks stay in the model and the markdown, they are only not shown. */
    applyFolds() {
      const hidden = MD.hiddenByFolds(this.blocks);
      this.blocks.forEach((b, i) => {
        if (!b.el) return;
        b.el.classList.toggle('fold-hidden', hidden[i]);
        if (b.type !== 'h') return;
        b.el.classList.toggle('folded', !!b.folded);
        const tog = b.el.querySelector(':scope > .fold-tog');
        if (tog) { tog.textContent = b.folded ? '\u25b8' : '\u25be'; tog.title = b.folded ? 'Expand this section' : 'Collapse this section'; tog.setAttribute('aria-expanded', String(!b.folded)); }
        let more = b.el.querySelector(':scope > .fold-more');
        const n = b.folded ? MD.sectionEnd(this.blocks, i) - i : 0;
        if (n > 0 && !more) { more = el('button', { class: 'fold-more', contenteditable: 'false', title: 'Expand this section', onmousedown: (e) => { e.preventDefault(); this.setFold(b, false); } }); b.el.appendChild(more); }
        if (more) { if (n > 0) more.textContent = '\u22ef ' + n + (n === 1 ? ' block' : ' blocks'); else more.remove(); }
      });
      this.scheduleSticky();
    }
    /* -- sticky headings (Seth, 2026-10-17: "make whatever headings apply to the current viewport
     * be sticky", with a way to turn it off) ------------------------------------------------
     * The headings that govern the first block under the top of the view — its nearest heading
     * above, that one's nearest heading of a higher level, and so on — are shown in a strip over
     * the top of the scroller once they have scrolled out of it, outermost first. Each row folds
     * its heading IN PLACE ("they can collapse the sticky heading even if they're not scrolled up
     * to the top") and then scrolls to that heading ("instead of skipping ahead or going to the
     * start or end of the note"); a click on the title scrolls to it. The strip is recomputed on
     * scroll, resize and every redraw; `scroll-padding-top` keeps focus moves from landing under it. */
    setSticky(on) {
      this.stickyOn = on !== false;
      if (!this.stickyOn) { this.sticky.hidden = true; this.sticky.innerHTML = ''; this._stickyKey = null; this.root.style.scrollPaddingTop = ''; }
      this.scheduleSticky();
    }
    scheduleSticky() {
      if (this._stickyReq || !this.stickyOn) return;
      this._stickyReq = requestAnimationFrame(() => { this._stickyReq = 0; this.updateSticky(); });
    }
    /* The chain of headings for the first block whose bottom lies under the line `top` (a page
     * coordinate), innermost last; a heading counts only once its own top has passed the line. */
    stickyChain(top) {
      const blocks = this.blocks;
      let i = -1;
      for (let k = 0; k < blocks.length; k++) {
        const b = blocks[k];
        if (!b.el || this.isHidden(b)) continue;
        if (b.el.getBoundingClientRect().bottom > top) { i = k; break; }
      }
      if (i < 0) return [];
      const chain = [];
      let lvl = 7;
      for (let j = i; j >= 0; j--) {
        const b = blocks[j], hl = MD.headingLevel(b);
        if (!hl || hl >= lvl || b.folded) { if (hl && hl < lvl && b.folded) lvl = hl; continue; }
        if (j === i && !(b.el.getBoundingClientRect().top < top - 1)) { lvl = hl; continue; }
        chain.unshift(b);
        lvl = hl;
        if (lvl === 1) break;
      }
      return chain;
    }
    updateSticky() {
      const strip = this.sticky;
      if (!this.stickyOn || !strip || !this.root.isConnected || !this.blocks.length) return;
      const sc = this.root, rr = sc.getBoundingClientRect();
      strip.style.top = sc.offsetTop + 'px';
      if (rr.height < 1) { strip.hidden = true; return; }
      // the strip's own height moves the line it measures against: settle in at most three passes
      let chain = [], h = strip.hidden ? 0 : strip.offsetHeight;
      for (let pass = 0; pass < 3; pass++) {
        chain = this.stickyChain(rr.top + h);
        const key = chain.map((b) => b.id + ':' + b.src).join('\n');
        if (key !== this._stickyKey) {
          this._stickyKey = key;
          strip.innerHTML = '';
          chain.forEach((b, depth) => {
            const lvl = MD.headingLevel(b);
            const row = el('div', { class: 'sh-row sh-l' + lvl, dataset: { id: b.id }, 'data-test': 'sticky-row', style: { paddingInlineStart: depth ? (depth * 14) + 'px' : '' } },
              el('button', { class: 'sh-fold', title: 'Collapse this section', 'data-test': 'sticky-fold', onmousedown: (e) => { e.preventDefault(); this.foldFromSticky(b); } }, '\u25be'),
              el('span', { class: 'sh-title', dir: 'auto', title: 'Go to this heading', onmousedown: (e) => { e.preventDefault(); this.scrollToHeading(b); } }, MD.plainText(b.src) || '\u00a0'));
            strip.appendChild(row);
          });
          strip.hidden = !chain.length;
        }
        const nh = strip.hidden ? 0 : strip.offsetHeight;
        if (nh === h) break;
        h = nh;
      }
      sc.style.scrollPaddingTop = h ? h + 'px' : '';
    }
    /* Scroll so heading `b` sits right under the strip rows of the headings above it. */
    scrollToHeading(b) {
      if (!b || !b.el || this.isHidden(b)) return;
      const sc = this.root;
      const chainAbove = this.stickyOn ? this.ancestorsOf(b) : [];
      // the rows for its ancestors stay; measure what they will take by the rows now in the strip
      let above = 0;
      if (this.stickyOn && !this.sticky.hidden) {
        for (const row of this.sticky.children) if (chainAbove.some((a) => a.id === row.dataset.id)) above += row.offsetHeight;
        if (!above && chainAbove.length) above = this.sticky.offsetHeight / Math.max(1, this.sticky.children.length) * chainAbove.length;
      } else if (chainAbove.length) {
        above = 30 * chainAbove.length;
      }
      const delta = b.el.getBoundingClientRect().top - (sc.getBoundingClientRect().top + above);
      sc.scrollTop = Math.max(0, sc.scrollTop + delta);
      this.updateSticky();
      // a second pass once the strip has its final rows
      const d2 = b.el.getBoundingClientRect().top - (sc.getBoundingClientRect().top + (this.sticky.hidden ? 0 : this.sticky.offsetHeight));
      if (Math.abs(d2) > 1) { sc.scrollTop = Math.max(0, sc.scrollTop + d2); this.updateSticky(); }
    }
    /* The headings above `b` in the outline: its nearest heading of a higher level, and so on. */
    ancestorsOf(b) {
      const i = this.blocks.indexOf(b), out = [];
      let lvl = MD.headingLevel(b) || 7;
      for (let j = i - 1; j >= 0 && lvl > 1; j--) {
        const hl = MD.headingLevel(this.blocks[j]);
        if (hl && hl < lvl) { out.unshift(this.blocks[j]); lvl = hl; }
      }
      return out;
    }
    foldFromSticky(b) {
      if (!b || b.type !== 'h') return;
      const act = document.activeElement;
      if (act && act.blur && this.root.contains(act)) act.blur();   // setFold would otherwise move the caret (and the view) to the heading's end
      this.setFold(b, true);
      this.scrollToHeading(b);
    }
    isHidden(b) { return !!(b && b.el && b.el.classList.contains('fold-hidden')); }
    setFold(b, folded) {
      if (!b || b.type !== 'h' || !!b.folded === !!folded) return;
      b.folded = !!folded;
      // the caret must not be left inside a block that is about to be hidden
      const act = document.activeElement;
      this.applyFolds();
      if (act && act.closest && act.closest('.fold-hidden')) this.focusBlock(this.blocks.indexOf(b), 'end');
      this.changed({ force: true });
    }
    setAllFolds(folded) {
      let any = false;
      for (const b of this.blocks) if (b.type === 'h' && !!b.folded !== !!folded && (!folded || MD.sectionEnd(this.blocks, this.blocks.indexOf(b)) > this.blocks.indexOf(b))) { b.folded = !!folded; any = true; }
      if (!any) return;
      this.applyFolds();
      const act = document.activeElement;
      if (act && act.closest && act.closest('.fold-hidden')) this.focusBlock(0, 0);
      this.changed({ force: true });
    }
    /* Unfold whatever hides block `b` (find, a drop, a focus from elsewhere). */
    reveal(b) {
      let i = this.blocks.indexOf(b), changed = false;
      if (i < 0 || !this.isHidden(b)) return;
      let lvl = MD.headingLevel(b) || 7;
      for (let j = i - 1; j >= 0; j--) {
        const h = this.blocks[j], hl = MD.headingLevel(h);
        if (hl && hl < lvl) { if (h.folded) { h.folded = false; changed = true; } lvl = hl; if (lvl === 1) break; }
      }
      if (changed) { this.applyFolds(); this.changed({ force: true }); }
    }
    /* -- outline numbering across blocks ------------------------------------------------
     * Each text block remembers the numbering state BEFORE it (b.numCtx); decorating with a
     * copy advances it for the next block. After an edit the blocks that follow are
     * re-decorated when their state changed (an item added above renumbers the ones below). */
    numCtxFor(b) { return { counters: (b && b.numCtx && b.numCtx.counters ? b.numCtx.counters : []).slice() }; }
    assignNumCtx(from) {
      let i = Math.max(0, from || 0);
      let ctx = i > 0 ? this.numCtxFor(this.blocks[i]) : { counters: [] };
      const changed = [];
      for (; i < this.blocks.length; i++) {
        const b = this.blocks[i];
        const before = JSON.stringify(ctx.counters);
        if (JSON.stringify((b.numCtx && b.numCtx.counters) || []) !== before) changed.push(b);
        b.numCtx = { counters: ctx.counters.slice() };
        if (b.type === 'list' || b.type === 'p') MD.numberLines(b.src.split('\n'), b.type, ctx);
        else ctx = { counters: [] };
      }
      return changed;
    }
    renumberAfter(b) {
      const i = this.blocks.indexOf(b);
      if (i < 0) return;
      for (const other of this.assignNumCtx(i)) {
        if (other === b || !other.el || !TEXT_TYPES.has(other.type)) continue;
        const body = other.el.querySelector('.blk-body');
        if (body && document.activeElement !== body) this.decorateInto(body, other);
      }
    }
    renderBlock(b, i) {
      const wrap = el('div', { class: 'blk blk-' + b.type, dataset: { id: b.id } });
      b.el = wrap;
      // ⋮ opens the block menu and is the block's drag grip (with a selection: every selected
      // block). No preventDefault on its mousedown: that would also stop the drag.
      const handle = el('div', { class: 'blk-handle' }, el('button', { title: 'Block menu \u2014 or drag to move (Ctrl: copy)', draggable: 'true', tabindex: '-1', 'data-test': 'blk-grip', onmousedown: (e) => { if (e.button === 0) this.blockMenu(e.currentTarget, b); } }, '⋮'));
      wrap.appendChild(handle);
      if (b.type === 'h') {
        wrap.appendChild(el('button', { class: 'fold-tog', contenteditable: 'false', 'data-test': 'fold', onmousedown: (e) => { e.preventDefault(); this.setFold(b, !b.folded); } }, b.folded ? '\u25b8' : '\u25be'));
      }
      if (TEXT_TYPES.has(b.type)) {
        const body = el('div', { class: 'blk-body', contenteditable: 'true', spellcheck: b.type === 'code' ? 'false' : 'true', dir: 'auto', 'data-ph': b.type === 'p' && i === 0 && this.blocks.length === 1 ? PLACEHOLDER : '' });
        this.decorateInto(body, b);
        this.wireText(body, b);
        wrap.appendChild(body);
        this.applyFind(body);
      } else {
        wrap.classList.add('widget');
        wrap.tabIndex = 0;
        this.renderWidget(wrap, b);
        this.wireWidget(wrap, b);
      }
      return wrap;
    }
    rerender(b) {
      const old = b.el;
      const i = this.blocks.indexOf(b);
      const fresh = this.renderBlock(b, i);
      if (old && old.parentNode) old.replaceWith(fresh); else this.root.appendChild(fresh);
      this.applyFolds();
      return fresh;
    }
    renderWidget(wrap, b) {
      const bar = el('div', { class: 'widget-bar' });
      const edit = el('button', { title: 'Edit source', onclick: () => this.editSource(b) }, '✎ Source');
      bar.appendChild(edit);
      bar.appendChild(el('button', { title: 'Delete block', onclick: () => this.deleteBlock(b) }, '✕'));
      const host = el('div', { class: 'widget-host' });
      wrap.append(bar, host);
      if (b.type === 'table') {
        wrap._table = FS.tables.render(host, b.src, {
          onChange: (src) => { b.src = src; this.changed(); },
          openLink: (href) => this.openLink(href),
          onPasteLink: (text, insert) => this.opts.onPasteLink && this.opts.onPasteLink(text, insert),
          onPasteLocate: (text, insert, fallback) => this.opts.onPasteLocate ? this.opts.onPasteLocate(text, insert, fallback) : fallback(),
          onSplit: (r) => this.splitTable(b, r),
          canMerge: (dir) => !!this.neighbourTable(b, dir),
          onMerge: (dir) => this.mergeTables(b, dir),
          insertSection: (pop, close) => this.insertSection(pop, close, b),
        });
      } else if (b.type === 'flex') {
        const spec = FS.flexref.parse(b.src);
        if (!spec) { host.appendChild(el('div', { class: 'flex-err' }, 'Unreadable FLEx embed: ' + b.src)); return; }
        this.applyLayout(wrap, spec);
        FS.interlinear.render(host, spec, this._flexOpts(b, host));
      } else if (b.type === 'chart') {
        bar.insertBefore(el('button', { onclick: () => FS.charts.editDialog(b.src, (src) => { b.src = src; this.changed(); this.rerender(b); }) }, '✎ Edit chart'), edit);
        FS.charts.render(host, b.src, { onEdit: () => FS.charts.editDialog(b.src, (src) => { b.src = src; this.changed(); this.rerender(b); }) });
      } else if (b.type === 'hr') {
        wrap.classList.add('blk-hr');
        bar.remove();
      } else if (b.type === 'image') {
        const m = /^!\[([^\]]*)\]\(([^)\s]+)/.exec(b.src.trim());
        host.appendChild(el('img', { src: m ? m[2] : '', alt: m ? m[1] : '', style: { maxWidth: '100%', borderRadius: '8px' } }));
      } else {
        host.appendChild(el('pre', {}, b.src));
      }
    }
    /* Numbered, indented examples (Seth, 2026-10-13): `indent=N` on the embed steps the block
     * in like a list level; `ex` gives it a running (1), (2)… through the note. */
    applyLayout(wrap, spec) {
      const x = (spec && spec.extra) || {};
      wrap.className = wrap.className.replace(/\bblk-indent\d\b/g, '').trim();
      const n = Math.max(0, Math.min(4, parseInt(x.indent, 10) || 0));
      if (n) wrap.classList.add('blk-indent' + n);
      let num = wrap.querySelector(':scope > .ex-num');
      if (x.ex && !num) { num = el('span', { class: 'ex-num' }, '(·)'); wrap.insertBefore(num, wrap.querySelector('.widget-host')); }
      if (!x.ex && num) num.remove();
      wrap.classList.toggle('ex-numbered', !!x.ex);
    }
    renumberExamples() {
      let n = 0;
      for (const b of this.blocks) {
        if (b.type !== 'flex' || !b.el) continue;
        const num = b.el.querySelector(':scope > .ex-num');
        if (num) num.textContent = '(' + (++n) + ')';
      }
    }
    indentFlex(b, d) {
      const spec = FS.flexref.parse(b.src);
      if (!spec) return;
      spec.extra = spec.extra || {};
      const n = Math.max(0, Math.min(4, (parseInt(spec.extra.indent, 10) || 0) + d));
      if (n) spec.extra.indent = String(n); else delete spec.extra.indent;
      b.src = FS.flexref.serialize(spec);
      this.applyLayout(b.el, spec);
      this.changed();
    }
    _flexOpts(b, host) {
      return {
        editable: true, layout: true, keepView: true,
        onSpecChange: (s) => { b.src = FS.flexref.serialize(s); this.applyLayout(b.el, s); this.changed(); FS.interlinear.render(host, s, this._flexOpts(b, host)); },
        editSource: () => this.editSource(b),
        duplicate: () => { this.insertBlockAfter(b, { type: 'flex', src: b.src }, false); FS.toast('Duplicated'); },
        remove: () => this.deleteBlock(b),
      };
    }

    /* -- text block wiring ---------------------------------------------------------- */
    wireText(body, b) {
      const refresh = () => {
        if (this.composing) return;
        const text = body.textContent;
        if (text !== b.src) { b.src = text; this.changed(); }
        // a single-line type change (typing "# " or "- ") happens live; multi-block splits wait for Enter/blur
        const parts = MD.splitBlocks(text);
        if (parts.length === 1 && parts[0].type !== b.type && TEXT_TYPES.has(parts[0].type) && text.trim() !== '') {
          const caret = getCaret(body);
          b.type = parts[0].type; b.level = parts[0].level;
          const fresh = this.rerender(b);
          setCaret(fresh.querySelector('.blk-body'), caret);
          return;
        }
        const caret = getCaret(body), caretEnd = getCaretEnd(body);
        const html = MD.decorate(text, b.type, this.numCtxFor(b));
        if (html !== body.innerHTML) { this.decorateInto(body, b, html); setCaret(body, caret, caretEnd); }
        this.applyFind(body);
        this.renumberAfter(b);
      };
      body.addEventListener('compositionstart', () => { this.composing = true; });
      body.addEventListener('compositionend', () => { this.composing = false; refresh(); });
      body.addEventListener('input', () => { if (!this.composing) queueMicrotask(refresh); });
      body.addEventListener('focus', () => { b.el.classList.add('focus'); this.active = b; if (this.opts.onFocusChange) this.opts.onFocusChange(b); });
      // where the caret was, for an insert after a dialog (the picker) has taken the focus
      body.addEventListener('keyup', () => { b.lastCaret = [getCaret(body), getCaretEnd(body)]; });
      body.addEventListener('mouseup', () => { b.lastCaret = [getCaret(body), getCaretEnd(body)]; });
      body.addEventListener('input', () => { b.lastCaret = [getCaret(body), getCaretEnd(body)]; });
      body.addEventListener('blur', () => { b.el.classList.remove('focus'); setTimeout(() => this.resplit(b), 0); });
      body.addEventListener('beforeinput', (e) => this.onBeforeInput(e, body, b));
      body.addEventListener('keydown', (e) => this.onKeyDown(e, body, b));
      body.addEventListener('mousedown', (e) => {
        const t = e.target.closest('.md-task');
        if (t) { e.preventDefault(); this.toggleTask(body, b, t); return; }
        if ((e.ctrlKey || e.metaKey) && e.target.closest('.md-link, .md-wiki, .md-tag')) {
          e.preventDefault();
          const span = e.target.closest('.md-link, .md-wiki, .md-tag');
          this.followDecorated(span, b);
        }
      });
      body.addEventListener('paste', (e) => {
        const dt = e.clipboardData;
        // A table copied from Excel / Word / a browser comes with a bitmap AND an HTML table on
        // the clipboard: the table wins (Seth, 2026-10-12: "I'd like it to land as a table").
        const table = FS.tables.fromHtml(dt && dt.getData('text/html'));
        if (table) { e.preventDefault(); this.insertBlockSourceAtCaret(body, b, table); return; }
        // image paste (files) — beforeinput does not expose them
        const files = dt && dt.files;
        if (files && files.length && this.opts.onPasteFiles) { e.preventDefault(); this.opts.onPasteFiles([...files], (md) => this.insertTextAtCaret(body, b, md)); }
      });
    }

    /* With markers hidden (Seth, 2026-10-18: "the cursor goes to the left of the ### and makes the
     * ### appear … text should automatically start typing to the RIGHT of a heading or list markup
     * tag"): a caret that lands inside a line's hidden prefix — a click, Home, a new heading — is
     * moved to just after it, so what is typed goes after the markup, never before it. Returns
     * the caret's place in the body, or -1 when there was nothing to do. */
    snapPastPrefix(body, b) {
      if (!document.body.classList.contains('md-hide')) return -1;
      body = body || document.activeElement;
      if (!body || !body.classList || !body.classList.contains('blk-body') || !this.root.contains(body)) return -1;
      const sel = window.getSelection();
      if (!sel || !sel.isCollapsed || !sel.rangeCount || !body.contains(sel.anchorNode)) return -1;
      b = b || this.blocks.find((x) => x.el && x.el.contains(body));
      if (!b) return -1;
      const a = getCaret(body), s = body.textContent;
      const ls = s.lastIndexOf('\n', a - 1) + 1, le = s.indexOf('\n', ls);
      const pre = MD.linePrefix(s.slice(ls, le < 0 ? s.length : le), b.type);
      if (!pre || a - ls >= pre.len) return -1;
      setCaret(body, ls + pre.len);
      return ls + pre.len;
    }
    onBeforeInput(e, body, b) {
      const it = e.inputType;
      if (it.startsWith('insert')) this.snapPastPrefix(body, b);
      if (it === 'historyUndo') { e.preventDefault(); this.undoStep(); return; }
      if (it === 'historyRedo') { e.preventDefault(); this.redoStep(); return; }
      if (it === 'insertParagraph') { e.preventDefault(); this.enter(body, b); return; }
      if (it === 'insertLineBreak') { e.preventDefault(); this.insertTextAtCaret(body, b, '\n'); return; }
      if (it === 'insertFromPaste' || it === 'insertFromDrop') {
        e.preventDefault();
        const dt = e.dataTransfer;
        // An HTML table (Excel / Word / a browser) becomes a table block. Tab-separated TEXT is
        // first offered to the FLEx locator (lines copied from the interlinear view) and only
        // becomes a table when nothing in the project matches — see pasteText.
        const htmlTable = FS.tables.fromHtml(dt && dt.getData && dt.getData('text/html'));
        if (htmlTable) { this.insertBlockSourceAtCaret(body, b, htmlTable); return; }
        const text = (dt && dt.getData('text/plain')) || '';
        if (!text) return;
        this.pasteText(body, b, text.replace(/\r\n?/g, '\n'));
        return;
      }
      if (it === 'formatBold') { e.preventDefault(); this.wrapSelection('**'); return; }
      if (it === 'formatItalic') { e.preventDefault(); this.wrapSelection('*'); return; }
      if (it === 'deleteContentBackward') {
        const sel = window.getSelection();
        if (sel && sel.isCollapsed && getCaret(body) === 0) { e.preventDefault(); this.backspaceAtStart(body, b); }
        return;
      }
      if (it === 'deleteContentForward') {
        const sel = window.getSelection();
        if (sel && sel.isCollapsed && getCaret(body) === body.textContent.length) { e.preventDefault(); this.deleteAtEnd(body, b); }
        return;
      }
      if (/^(insertText|insertCompositionText|insertReplacementText|deleteContent|deleteWord|deleteByCut|deleteSoftLine|deleteHardLine|deleteByDrag)/.test(it)) return;
      e.preventDefault();
    }

    onKeyDown(e, body, b) {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); e.stopPropagation(); this.undoStep(); return; }
      if (mod && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); e.stopPropagation(); this.redoStep(); return; }
      if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); this.wrapSelection('**'); return; }
      if (mod && e.key.toLowerCase() === 'i') { e.preventDefault(); this.wrapSelection('*'); return; }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'h') { e.preventDefault(); this.wrapSelection('=='); return; }
      if (mod && e.key === 'Enter') { e.preventDefault(); this.insertBlockAfter(b, { type: 'p', src: '' }, true); return; }
      if (e.key === 'Tab' && (b.type === 'list' || b.type === 'code')) { e.preventDefault(); this.indent(body, b, e.shiftKey ? -1 : 1); return; }
      if (mod && (e.key === ']' || e.key === '[') && b.type === 'list') { e.preventDefault(); this.indent(body, b, e.key === ']' ? 1 : -1); return; }
      if (e.key === 'Escape') { body.blur(); return; }
      if ((e.key === 'ArrowLeft' || e.key === 'Home') && !mod && !e.shiftKey && !e.altKey && document.body.classList.contains('md-hide')) {
        // markers hidden: Home lands after the prefix; Left from there steps over it to the line before
        const sel = window.getSelection();
        if (sel && sel.isCollapsed) {
          const a = getCaret(body), s = body.textContent;
          const ls = s.lastIndexOf('\n', a - 1) + 1, le = s.indexOf('\n', ls);
          const pre = MD.linePrefix(s.slice(ls, le < 0 ? s.length : le), b.type);
          if (pre) {
            if (e.key === 'Home') { e.preventDefault(); setCaret(body, ls + pre.len); return; }
            if (a <= ls + pre.len) {
              e.preventDefault();
              if (ls > 0) setCaret(body, ls - 1);
              else { const i = this.blocks.indexOf(b); if (i > 0) this.focusBlock(i - 1, 'end'); }
              return;
            }
          }
        }
      }
      if (e.key === 'Backspace' && !mod && !e.altKey && document.body.classList.contains('md-hide')) {
        // markers hidden: Backspace right after a line prefix removes the whole prefix (the
        // bullet, the heading, the quote bar) instead of eating one invisible character
        const sel = window.getSelection();
        if (sel && sel.isCollapsed) {
          const a = getCaret(body), s = body.textContent;
          const ls = s.lastIndexOf('\n', a - 1) + 1, le = s.indexOf('\n', ls);
          const line = s.slice(ls, le < 0 ? s.length : le);
          const pre = MD.linePrefix(line, b.type);
          if (pre && a - ls === pre.len) { e.preventDefault(); this.setText(body, b, s.slice(0, ls) + s.slice(ls + pre.len), ls); this.resplit(b); return; }
        }
      }
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        if (e.shiftKey || e.altKey) return;
        const sel = window.getSelection();
        if (!sel || !sel.isCollapsed) return;
        const rect = caretRect(), br = body.getBoundingClientRect();
        if (!rect) return;
        const lh = parseFloat(getComputedStyle(body).lineHeight) || 22;
        const first = rect.top - br.top < lh * 0.9, last = br.bottom - rect.bottom < lh * 0.9;
        if ((e.key === 'ArrowUp' && first) || (e.key === 'ArrowDown' && last)) {
          const i = this.blocks.indexOf(b) + (e.key === 'ArrowUp' ? -1 : 1);
          if (i >= 0 && i < this.blocks.length) { e.preventDefault(); this.focusBlock(i, e.key === 'ArrowUp' ? 'end' : 0); }
        }
        return;
      }
      if (e.key === '/' && body.textContent === '' && this.opts.onSlash) { e.preventDefault(); this.opts.onSlash(body, b); return; }
    }

    /* -- editing primitives ----------------------------------------------------------- */
    /* Decorate a text block and bring its inline FLEx chips to life (titles + overlay). */
    decorateInto(body, b, html) {
      body.innerHTML = html != null ? html : MD.decorate(b.src, b.type, this.numCtxFor(b));
      if (body.querySelector('.md-embed')) FS.interlinear.hydrateInline(body, this._inlineOpts(body, b));
    }
    _inlineOpts(body, b) {
      const live = () => (b.el && b.el.querySelector('.blk-body')) || body;
      const replace = (src, next) => {
        const i = b.src.indexOf(src);
        if (i < 0) return;
        const el2 = live();
        const caret = document.activeElement === el2 ? getCaret(el2) : null;
        this.setText(el2, b, b.src.slice(0, i) + next + b.src.slice(i + src.length), caret);
      };
      return {
        onSpecChange: (spec, src) => replace(src, FS.flexref.serialize(spec)),
        duplicate: (src) => { replace(src, src + ' ' + src); FS.toast('Duplicated'); },
        remove: (src) => replace(src, ''),
        expandInline: (src) => this.expandInline(b, src),
        editInline: (span) => {
          // reveal the embed code so it can be edited; it turns back into a chip on the next edit
          const el2 = live();
          span.classList.add('reveal-src');
          span.removeAttribute('contenteditable');
          el2.focus();
          const r = document.createRange(); r.selectNodeContents(span); r.collapse(false);
          const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
        },
        findAnchor: (src) => { const el2 = live(); return [...el2.querySelectorAll('.md-embed')].find((x) => x.dataset.src === src) || null; },
      };
    }
    /* An inline chip becomes a block of its own: the text before and after it stay paragraphs. */
    expandInline(b, src) {
      const i = b.src.indexOf(src);
      if (i < 0) return;
      const before = b.src.slice(0, i).replace(/\s+$/, ''), after = b.src.slice(i + src.length).replace(/^\s+/, '');
      const k = this.blocks.indexOf(b);
      const seq = [];
      if (before) seq.push(Object.assign({ id: FS.uid() }, MD.splitBlocks(before)[0] || { type: 'p', src: before }));
      seq.push({ id: FS.uid(), type: 'flex', src });
      if (after) seq.push(Object.assign({ id: FS.uid() }, MD.splitBlocks(after)[0] || { type: 'p', src: after }));
      this.blocks.splice(k, 1, ...seq);
      this.renderAll();
      this.changed({ force: true });
      this.focusBlock(k + (before ? 1 : 0), 0);
    }
    setText(body, b, text, caret, caretEnd) {
      b.src = text;
      this.decorateInto(body, b);
      if (caret != null) setCaret(body, caret, caretEnd);
      this.changed();
      this.applyFind(body);
      this.renumberAfter(b);
    }
    insertTextAtCaret(body, b, text) {
      const a = getCaret(body), z = getCaretEnd(body);
      const s = body.textContent;
      this.setText(body, b, s.slice(0, a) + text + s.slice(z), a + text.length);
    }
    /* A FLEx embed inserted after text on a line goes INLINE as a chip (Seth, 2026-10-13: "put
     * chips inline with text"); at the start of a line, or when it is not a single embed, the
     * caller makes a block. A chip's overlay offers "Expand in note" to turn it into a block. */
    embedInline(body, b, md) {
      if (b.type === 'code' || !FS.flexref.isEmbedLine(md)) return false;
      const a = getCaret(body), s = body.textContent;
      const ls = s.lastIndexOf('\n', a - 1) + 1, le = s.indexOf('\n', a);
      if (!s.slice(ls, a).trim()) return false;           // at the start of a line: a block, as before
      const z = getCaretEnd(body);
      const padL = a > ls && !/\s$/.test(s.slice(ls, a)) ? ' ' : '', padR = z < (le < 0 ? s.length : le) && !/^\s/.test(s.slice(z)) ? ' ' : '';
      const ins = padL + md.trim() + padR;
      this.setText(body, b, s.slice(0, a) + ins + s.slice(z), a + ins.length);
      return true;
    }
    pasteText(body, b, text) {
      const trimmed = text.trim();
      // A chooser dialog may open first; its focus change can blur and re-render this block, so
      // the insert re-finds the block's live element and uses the caret captured now.
      const a = getCaret(body), z = getCaretEnd(body);
      const live = () => (b.el && b.el.isConnected && b.el.querySelector('.blk-body')) || body;
      const insert = (md, asBlock) => {
        const el2 = live();
        if (!this.blocks.includes(b)) { this.insertMarkdown(md, asBlock); return; }
        if (document.activeElement !== el2) { el2.focus(); setCaret(el2, a, z); }
        if (asBlock && this.embedInline(el2, b, md)) return;
        if (asBlock) this.insertBlockSourceAtCaret(el2, b, md); else this.insertTextAtCaret(el2, b, md);
      };
      if (this.opts.onPasteLink && (/^silfw:\/\//i.test(trimmed) || FS.flexref.GUID.test(trimmed))) {
        this.opts.onPasteLink(trimmed, insert);
        return;
      }
      const plain = () => { const el2 = live(); if (document.activeElement !== el2) { el2.focus(); setCaret(el2, a, z); } const tsv = FS.tables.fromTsv(text); if (tsv) this.insertBlockSourceAtCaret(el2, b, tsv); else this.pastePlain(el2, b, text); };
      if (this.opts.onPasteLocate && looksInterlinear(text)) {
        // lines copied out of FLEx's interlinear view: locate the segment(s) and offer the embed
        this.opts.onPasteLocate(text, insert, plain);
        return;
      }
      plain();
    }
    pastePlain(body, b, text) {
      if (/\n\s*\n/.test(text) || MD.splitBlocks(text).some((x) => !TEXT_TYPES.has(x.type) || x.type !== 'p')) {
        this.insertBlockSourceAtCaret(body, b, text);
        return;
      }
      this.insertTextAtCaret(body, b, text);
    }
    /* Split the block at the caret and put the given markdown (any number of blocks) between. */
    insertBlockSourceAtCaret(body, b, md) {
      const a = getCaret(body);
      const s = body.textContent;
      const before = s.slice(0, a).replace(/\s+$/, ''), after = s.slice(a).replace(/^\s+/, '');
      const i = this.blocks.indexOf(b);
      const parts = MD.splitBlocks(md).map((x) => Object.assign({ id: FS.uid() }, x));
      const seq = [];
      if (before) seq.push({ id: FS.uid(), type: MD.splitBlocks(before)[0] ? MD.splitBlocks(before)[0].type : 'p', src: before });
      seq.push(...parts);
      seq.push({ id: FS.uid(), type: 'p', src: after });
      this.blocks.splice(i, 1, ...seq);
      this.renderAll();
      this.changed({ force: true });
      const lastText = seq[seq.length - 1];
      this.focusBlock(this.blocks.indexOf(lastText), 0);
    }
    wrapSelection(m) {
      const b = this.active;
      if (this.activeTable && this.activeTable.insertText) { /* cells handle Ctrl+B themselves */ return; }
      if (!b || !b.el) return;
      const body = b.el.querySelector('.blk-body');
      if (!body || document.activeElement !== body) return;
      const a = getCaret(body), z = getCaretEnd(body);
      const r = wrapLines(body.textContent, a, z, m);
      this.setText(body, b, r.text, r.a, r.z);
    }
    /* Prefix commands: heading level, bullet/number/task list, quote. Toggle on the current line(s). */
    linePrefix(kind, level) {
      const b = this.active;
      if (!b || !b.el) return;
      const body = b.el.querySelector('.blk-body');
      if (!body) return;
      const a = getCaret(body), z = getCaretEnd(body);
      const s = body.textContent;
      const lines = s.split('\n');
      let pos = 0, first = -1, last = -1;
      lines.forEach((ln, i) => { const end = pos + ln.length; if (first < 0 && a <= end) first = i; if (z >= pos && z <= end + 1) last = i; pos = end + 1; });
      if (first < 0) first = 0;
      if (last < first) last = first;
      const strip = (ln) => ln.replace(/^(#{1,6}\s+|\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?|\s*>\s?)/, '');
      const prefixes = { h: '#'.repeat(level || 1) + ' ', list: '- ', num: '1. ', task: '- [ ] ', quote: '> ' };
      const allHave = lines.slice(first, last + 1).every((ln) => kind === 'h' ? ln.startsWith(prefixes.h) : kind === 'list' ? /^\s*[-*+]\s(?!\[)/.test(ln) : kind === 'num' ? /^\s*\d+[.)]\s/.test(ln) : kind === 'task' ? /^\s*[-*+]\s\[[ xX]\]/.test(ln) : /^\s*>/.test(ln));
      let n = 0;
      for (let i = first; i <= last; i++) {
        const core = strip(lines[i]);
        lines[i] = allHave ? core : (kind === 'num' ? (++n) + '. ' : prefixes[kind]) + core;
      }
      const text = lines.join('\n');
      const delta = text.length - s.length;
      const parts = MD.splitBlocks(text);
      if (parts.length === 1) { b.type = parts[0].type; b.level = parts[0].level; }
      b.src = text;
      const fresh = this.rerender(b);
      setCaret(fresh.querySelector('.blk-body'), Math.max(0, a + (first === last ? delta : 0)));
      this.changed();
    }
    /* Step the list items under the selection in or out by one level (two spaces; at most four
     * levels), keeping the selection on the same text (Seth, 2026-10-18: lists "need to include
     * the ability to increase and decrease the indent"). Tab / Shift+Tab, Ctrl+] / Ctrl+[, the
     * toolbar's ⇥ ⇤ and the block menu all come here. */
    indent(body, b, dir) {
      const a = getCaret(body), z = getCaretEnd(body);
      const s = body.textContent;
      const lines = s.split('\n');
      let pos = 0, first = -1, last = -1;
      lines.forEach((ln, i) => { const end = pos + ln.length; if (first < 0 && a <= end) first = i; if (z >= pos && z <= end + (i < lines.length - 1 ? 1 : 0)) last = i; pos = end + 1; });
      if (first < 0) first = 0;
      if (last < first) last = first;
      let dFirst = 0, dAll = 0;
      for (let i = first; i <= last; i++) {
        const line = lines[i];
        let out = line;
        if (dir > 0) { if ((line.match(/^ */)[0].length) < 8) out = '  ' + line; }
        else out = line.replace(/^ {1,2}/, '');
        const d = out.length - line.length;
        if (i === first) dFirst = d;
        dAll += d;
        lines[i] = out;
      }
      if (!dAll) return;
      const lineStart = s.split('\n').slice(0, first).reduce((n, ln) => n + ln.length + 1, 0);
      this.setText(body, b, lines.join('\n'), Math.max(lineStart, a + dFirst), a === z ? undefined : Math.max(lineStart, z + dAll));
    }
    /* The toolbar's / menu's indent: the active list block, or nothing. */
    indentActive(dir) {
      const b = this.active;
      if (!b || !b.el || (b.type !== 'list' && b.type !== 'code')) return false;
      const body = b.el.querySelector('.blk-body');
      if (!body) return false;
      if (document.activeElement !== body) body.focus();
      this.indent(body, b, dir);
      return true;
    }
    toggleTask(body, b, span) {
      // the span's text is "[ ]" or "[x]"; find its offset in the block text
      const r = document.createRange();
      r.selectNodeContents(span);
      r.setStart(body, 0);
      const off = r.toString().length - span.textContent.length;
      const s = body.textContent;
      const now = s.slice(off, off + 3);
      const repl = now === '[ ]' ? '[x]' : '[ ]';
      const caret = getCaret(body);
      this.setText(body, b, s.slice(0, off) + repl + s.slice(off + 3), caret);
    }
    followDecorated(span, b) {
      const text = span.textContent;
      if (span.classList.contains('md-tag')) return this.openLink('tag:' + text.replace(/^#/, ''));
      // find the full link in the source around the span
      const r = document.createRange();
      r.selectNodeContents(span);
      r.setStart(b.el.querySelector('.blk-body'), 0);
      const off = r.toString().length - text.length;
      const src = b.src;
      const re = /\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)|\[\[([^\]\n]+)\]\]|https?:\/\/[^\s<>"')\]]+|silfw:\/\/[^\s<>"']+/g;
      let m;
      while ((m = re.exec(src))) {
        if (off >= m.index && off <= m.index + m[0].length) {
          const href = m[2] ? m[2] : m[3] ? 'note:' + m[3] : m[0];
          return this.openLink(href);
        }
      }
    }
    openLink(href) { if (this.opts.openLink) this.opts.openLink(href); }

    /* -- Enter / Backspace / Delete ----------------------------------------------------- */
    enter(body, b) {
      const a = getCaret(body), z = getCaretEnd(body);
      const s = body.textContent;
      const before = s.slice(0, a), after = s.slice(z);
      if (b.type === 'code') { this.setText(body, b, before + '\n' + after, a + 1); return; }
      if (b.type === 'list' || b.type === 'quote') {
        const lineStart = before.lastIndexOf('\n') + 1;
        const line = before.slice(lineStart);
        const m = b.type === 'list' ? /^(\s*)([-*+]|(\d+)[.)])\s(\[[ xX]\]\s)?/.exec(line) : /^(\s*>\s?)/.exec(line);
        const restOfLine = after.slice(0, after.indexOf('\n') < 0 ? after.length : after.indexOf('\n'));
        if (m && line.slice(m[0].length).trim() === '' && restOfLine.trim() === '') {
          // empty item → leave the list: drop the marker, continue as a paragraph
          const kept = before.slice(0, lineStart).replace(/\n$/, '');
          const i = this.blocks.indexOf(b);
          const nb = { id: FS.uid(), type: 'p', src: after.replace(/^\n/, '') };
          if (kept.trim() === '') { b.type = 'p'; b.src = nb.src; this.rerender(b); this.changed(); this.focusBlock(i, 0); return; }
          b.src = kept;
          this.blocks.splice(i + 1, 0, nb);
          this.rerender(b);
          this.root.insertBefore(this.renderBlock(nb, i + 1), b.el.nextSibling);
          this.changed();
          this.focusBlock(i + 1, 0);
          return;
        }
        let marker;
        if (b.type === 'quote') marker = m ? m[1] : '> ';
        else if (m) {
          let next = parseInt(m[3], 10) + 1;
          if (m[3]) {
            // the displayed (computed) number of this line, + 1 — the typed number may be stale
            const nums = MD.numberLines(before.split('\n'), b.type, this.numCtxFor(b));
            const shown = nums[nums.length - 1];
            if (shown != null) next = shown + 1;
          }
          marker = m[1] + (m[3] ? next + m[2].slice(-1) : m[2]) + ' ' + (m[4] ? '[ ] ' : '');
        } else marker = '- ';
        this.setText(body, b, before + '\n' + marker + after, a + 1 + marker.length);
        return;
      }
      // paragraph / heading: split into two blocks
      let i = this.blocks.indexOf(b);
      if (b.type === 'h' && b.folded) {
        if (after.trim() === '') {
          // Enter at the end of a closed heading starts the NEXT heading of the same level after
          // its section (a paragraph there would belong to the closed section and be hidden)
          const end = MD.sectionEnd(this.blocks, i);
          const marker = '#'.repeat(MD.headingLevel(b)) + ' ';
          const nb = { id: FS.uid(), type: 'h', src: marker };
          this.blocks.splice(end + 1, 0, nb);
          const anchor = this.blocks[end].el;
          this.root.insertBefore(this.renderBlock(nb, end + 1), anchor ? anchor.nextSibling : null);
          this.changed({ force: true });
          this.focusBlock(end + 1, marker.length);
          return;
        }
        b.folded = false;               // splitting the heading's text opens the section
      }
      const nb = { id: FS.uid(), type: 'p', src: after.replace(/^\n/, '') };
      b.src = before.replace(/\s+$/, '');
      if (b.type === 'h' && !b.src.replace(/^#+\s*/, '')) b.type = 'p';
      this.blocks.splice(i + 1, 0, nb);
      this.rerender(b);
      this.root.insertBefore(this.renderBlock(nb, i + 1), b.el.nextSibling);
      this.changed({ force: true });
      this.focusBlock(i + 1, 0);
    }
    backspaceAtStart(body, b) {
      const i = this.blocks.indexOf(b);
      const s = body.textContent;
      // a list/quote/heading marker at the very start: strip it first
      const m = /^(#{1,6}\s|\s*([-*+]|\d+[.)])\s(\[[ xX]\]\s)?|\s*>\s?)/.exec(s);
      if (m && b.type !== 'p' && b.type !== 'code') {
        const rest = s.slice(m[0].length);
        const parts = MD.splitBlocks(rest);
        b.type = parts.length === 1 && TEXT_TYPES.has(parts[0].type) ? parts[0].type : 'p';
        b.src = rest;
        const fresh = this.rerender(b);
        setCaret(fresh.querySelector('.blk-body'), 0);
        this.changed();
        return;
      }
      if (i === 0) return;
      const prev = this.blocks[i - 1];
      if (this.isHidden(prev)) { this.focusBlock(i - 1, 'end'); return; }   // lands on the closed heading
      if (!TEXT_TYPES.has(prev.type)) { this.focusBlock(i - 1); return; }
      if (s === '' ) { this.blocks.splice(i, 1); b.el.remove(); this.changed({ force: true }); this.focusBlock(i - 1, 'end'); return; }
      const joinAt = prev.src.length;
      prev.src = prev.src + s;
      this.blocks.splice(i, 1);
      b.el.remove();
      const fresh = this.rerender(prev);
      setCaret(fresh.querySelector('.blk-body'), joinAt);
      this.changed({ force: true });
    }
    deleteAtEnd(body, b) {
      const i = this.blocks.indexOf(b);
      if (i >= this.blocks.length - 1) return;
      const next = this.blocks[i + 1];
      if (this.isHidden(next)) return;          // the end of a closed heading: its section stays whole
      if (!TEXT_TYPES.has(next.type)) { this.focusBlock(i + 1); return; }
      const at = b.src.length;
      b.src = b.src + next.src;
      this.blocks.splice(i + 1, 1);
      next.el.remove();
      const fresh = this.rerender(b);
      setCaret(fresh.querySelector('.blk-body'), at);
      this.changed({ force: true });
    }
    /* After editing, a text block may now contain several blocks (e.g. a heading typed on line 2). */
    resplit(b) {
      if (!b.el || !b.el.isConnected || !TEXT_TYPES.has(b.type)) return;
      const parts = MD.splitBlocks(b.src);
      if (parts.length <= 1) {
        if (parts.length === 1 && parts[0].type !== b.type) { b.type = parts[0].type; b.level = parts[0].level; this.rerender(b); }
        return;
      }
      const i = this.blocks.indexOf(b);
      const seq = parts.map((x) => Object.assign({ id: FS.uid() }, x));
      this.blocks.splice(i, 1, ...seq);
      this.renderAll();
      this.changed({ silent: true });
    }

    /* -- blocks ---------------------------------------------------------------------- */
    focusBlock(i, where, create) {
      if (i < 0 || i >= this.blocks.length) {
        if (create) { const nb = { id: FS.uid(), type: 'p', src: '' }; this.blocks.push(nb); this.root.appendChild(this.renderBlock(nb, this.blocks.length - 1)); i = this.blocks.length - 1; } else return;
      }
      if (this.isHidden(this.blocks[i])) {
        // a folded section is stepped over: up lands on its heading, down after the section
        const step = where === 'end' ? -1 : 1;
        let j = i;
        while (j >= 0 && j < this.blocks.length && this.isHidden(this.blocks[j])) j += step;
        if (j < 0 || j >= this.blocks.length) { if (!create) return; return this.focusBlock(this.blocks.length, where, true); }
        i = j;
      }
      const b = this.blocks[i];
      if (TEXT_TYPES.has(b.type)) {
        const body = b.el.querySelector('.blk-body');
        body.focus();
        setCaret(body, where === 'end' ? body.textContent.length : (where || 0));
        body.scrollIntoView({ block: 'nearest' });
      } else {
        b.el.focus();
        b.el.scrollIntoView({ block: 'nearest' });
      }
      this.active = b;
    }
    wireWidget(wrap, b) {
      wrap.addEventListener('focus', () => { wrap.classList.add('focus'); this.active = b; if (this.opts.onFocusChange) this.opts.onFocusChange(b); });
      wrap.addEventListener('blur', () => wrap.classList.remove('focus'));
      wrap.addEventListener('keydown', (e) => {
        if (e.target !== wrap) return;   // keys inside cells etc. are theirs
        const i = this.blocks.indexOf(b);
        if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); this.deleteBlock(b); }
        else if (e.key === 'Tab' && b.type === 'flex') { e.preventDefault(); this.indentFlex(b, e.shiftKey ? -1 : 1); }
        else if (e.key === 'Tab' && b.type === 'table' && wrap._table && wrap._table.ops) { e.preventDefault(); wrap._table.ops.indent(e.shiftKey ? -1 : 1); }
        else if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); this.focusBlock(i - 1, 'end'); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); this.focusBlock(i + 1, 0, true); }
        else if (e.key === 'Enter') { e.preventDefault(); if (b.type === 'table') { const cell = wrap.querySelector('.cell-view'); if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); } else if (b.type === 'chart') FS.charts.editDialog(b.src, (src) => { b.src = src; this.changed(); this.rerender(b); }); else this.insertBlockAfter(b, { type: 'p', src: '' }, true); }
        else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) { e.preventDefault(); e.stopPropagation(); (e.shiftKey || e.key.toLowerCase() === 'y') ? this.redoStep() : this.undoStep(); }
      });
      if (b.type === 'hr') wrap.addEventListener('click', () => wrap.focus());
    }
    /* A NEW block above or below `b` — paragraph, heading, list, checklist, quote, table, FLEx
     * example, divider (Seth, 2026-10-16: "insert a new block in a note … especially useful
     * after examples or tables (before existing text blocks or example blocks)"). From the
     * right-click menu on a block or between blocks, the ⋮ block menu, and a table's cell menu. */
    insertNewBlock(b, where, kind) {
      const def = NEW_BLOCKS.find((k) => k[0] === kind) || NEW_BLOCKS[0];
      const src = typeof def[2] === 'function' ? def[2]() : def[2];
      const nb = Object.assign({ type: 'p', src: '' }, src ? MD.splitBlocks(src)[0] : {}, { id: FS.uid() });
      let i = b ? this.blocks.indexOf(b) : this.blocks.length;
      if (i < 0) i = this.blocks.length;
      if (b && where !== 'before') i += 1;
      this.blocks.splice(i, 0, nb);
      const node = this.renderBlock(nb, i);
      const next = this.blocks[i + 1];
      if (next && next.el && next.el.parentNode === this.root) this.root.insertBefore(node, next.el); else this.root.appendChild(node);
      this.changed({ force: true });
      this.focusBlock(i, 'end');
      if (kind === 'flex' && this.opts.onInsertFlex) this.opts.onInsertFlex();   // the picker fills the new paragraph
      if (kind === 'file' && this.opts.onAttach) this.opts.onAttach();             // the file dialog fills it
      return nb;
    }
    /* The "Insert a block" section of a menu: one row per kind, Above / Below. */
    insertSection(pop, close, b) {
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Insert a new block')));
      const grid = el('div', { class: 'ins-grid' });
      for (const [kind, label] of NEW_BLOCKS) {
        grid.append(el('span', { class: 'ins-label' }, label),
          el('button', { class: 'tog', 'data-ins-kind': kind, 'data-ins-where': 'before', title: label + ' above this block', onclick: () => { close(); this.insertNewBlock(b, 'before', kind); } }, '\u2191 Above'),
          el('button', { class: 'tog', 'data-ins-kind': kind, 'data-ins-where': 'after', title: label + ' below this block', onclick: () => { close(); this.insertNewBlock(b, 'after', kind); } }, '\u2193 Below'));
      }
      pop.appendChild(grid);
    }
    insertBlockAfter(b, nb, focus) {
      const i = b ? this.blocks.indexOf(b) : this.blocks.length - 1;
      nb = Object.assign({ id: FS.uid() }, nb);
      this.blocks.splice(i + 1, 0, nb);
      const node = this.renderBlock(nb, i + 1);
      if (b && b.el && b.el.nextSibling) this.root.insertBefore(node, b.el.nextSibling); else this.root.appendChild(node);
      this.changed({ force: true });
      if (focus) this.focusBlock(i + 1, 0);
      return nb;
    }
    /* Insert markdown at the current position: into a table cell, at the caret of a text block,
     * replacing an empty paragraph, or after the active widget. */
    /* Rewrite several embeds at once (Seth, 2026-10-17: tag styles "applyable to a group of
     * examples by highlight"): fn(src) → the new source of each of `srcs`, wherever it stands. */
    mapEmbeds(srcs, fn) {
      let n = 0;
      for (const b of this.blocks) {
        let src = b.src;
        for (const old of new Set(srcs)) {
          if (!src.includes(old)) continue;
          const next = fn(old);
          if (next && next !== old) { src = src.split(old).join(next); n++; }
        }
        if (src !== b.src) b.src = src;
      }
      if (n) { this.changed(); this.renderAll(); }
      return n;
    }
    insertMarkdown(md, asBlock) {
      if (this.activeTable && this.activeTable.insertText) { this.activeTable.insertText(md.replace(/\n/g, ' ')); return; }
      let b = this.active && this.blocks.includes(this.active) ? this.active : this.blocks[this.blocks.length - 1];
      if (!b) { this.load(md); this.changed({ force: true }); return; }
      if (TEXT_TYPES.has(b.type) && b.el) {
        const body = b.el.querySelector('.blk-body');
        let placed = document.activeElement === body;      // the caret is where the user put it
        if (!placed) { body.focus(); const lc = b.lastCaret && b.lastCaret[0] <= body.textContent.length ? b.lastCaret : null; setCaret(body, lc ? lc[0] : body.textContent.length, lc ? lc[1] : undefined); placed = !!lc; }
        if (!asBlock) { this.insertTextAtCaret(body, b, md); return; }
        if (placed && this.embedInline(body, b, md)) return;
        if (body.textContent.trim() === '') {
          const i = this.blocks.indexOf(b);
          const parts = MD.splitBlocks(md).map((x) => Object.assign({ id: FS.uid() }, x));
          parts.push({ id: FS.uid(), type: 'p', src: '' });
          this.blocks.splice(i, 1, ...parts);
          this.renderAll();
          this.changed({ force: true });
          this.focusBlock(i + parts.length - 1, 0);
          return;
        }
        this.insertBlockSourceAtCaret(body, b, md);
        return;
      }
      const parts = MD.splitBlocks(md);
      let last = b;
      for (const p of parts) last = this.insertBlockAfter(last, p, false);
      this.insertBlockAfter(last, { type: 'p', src: '' }, true);
    }
    /* -- tables as blocks: split one into two, join two into one (Seth, 2026-10-12) ------ */
    splitTable(b, r) {
      const halves = FS.tables.splitAt(FS.tables.parse(b.src), r);
      if (!halves) return;
      const i = this.blocks.indexOf(b);
      const seq = [{ id: FS.uid(), type: 'table', src: FS.tables.serialize(halves[0]) }, { id: FS.uid(), type: 'p', src: '' }, { id: FS.uid(), type: 'table', src: FS.tables.serialize(halves[1]) }];
      this.blocks.splice(i, 1, ...seq);
      this.renderAll();
      this.changed({ force: true });
      this.focusBlock(i + 1, 0);
    }
    /* The table block next to b in direction dir (-1 above, +1 below), looking past empty
     * paragraphs; null when there is none. */
    neighbourTable(b, dir) {
      const i = this.blocks.indexOf(b);
      for (let j = i + dir; j >= 0 && j < this.blocks.length; j += dir) {
        const x = this.blocks[j];
        if (x.type === 'table') return x;
        if (x.type === 'p' && x.src.trim() === '') continue;
        return null;
      }
      return null;
    }
    mergeTables(b, dir) {
      const other = this.neighbourTable(b, dir);
      if (!other) return;
      const [top, bottom] = dir > 0 ? [b, other] : [other, b];
      const merged = FS.tables.serialize(FS.tables.mergeTables(FS.tables.parse(top.src), FS.tables.parse(bottom.src)));
      const i = this.blocks.indexOf(top), j = this.blocks.indexOf(bottom);
      this.blocks.splice(i, j - i + 1, { id: FS.uid(), type: 'table', src: merged });
      this.renderAll();
      this.changed({ force: true });
      this.focusBlock(i, 0);
    }
    deleteBlock(b) {
      const i = this.blocks.indexOf(b);
      if (i < 0) return;
      this.blocks.splice(i, 1);
      b.el.remove();
      if (!this.blocks.length) { this.blocks.push({ id: FS.uid(), type: 'p', src: '' }); this.renderAll(); }
      this.changed({ force: true });
      this.focusBlock(Math.min(i, this.blocks.length - 1), 'end');
    }
    /* The blocks an action on `b` takes: the cross-block selection when `b` is in it (whole
     * blocks, its ends included), else `b` — with its section when it is a closed heading. */
    blockRangeFor(b) {
      let i = this.blocks.indexOf(b);
      const m = this.msel;
      let a = i, z = i;
      if (m) {
        const ia = this.blocks.indexOf(m.a.b), iz = this.blocks.indexOf(m.z.b);
        if (i >= ia && i <= iz) { a = ia; z = iz; }
      }
      const last = this.blocks[z];
      if (last && last.type === 'h' && last.folded) z = MD.sectionEnd(this.blocks, z);
      return [a, z];
    }
    /* Select blocks a..z whole (after a move, so the next move or Ctrl+C takes them again). */
    selectBlocks(a, z) {
      // keep the keyboard in the note (a redraw dropped the focus), so the next Alt+Shift+↑/↓
      // or Ctrl+C reaches it; without moving the view
      const first = this.blocks[a];
      const tgt = first && first.el && (first.el.querySelector('.blk-body') || first.el);
      if (tgt && tgt.focus) tgt.focus({ preventScroll: true });
      this.active = first;
      if (a === z) { this.clearMsel(); return; }
      const last = this.blocks[z];
      this.setMsel({ b: this.blocks[a], off: 0 }, { b: last, off: TEXT_TYPES.has(last.type) ? last.src.length : Infinity });
    }
    /* Move blocks a..z to before index `to` (in the current order), or copy them there. */
    moveBlocksTo(a, z, to, copy) {
      const n = z - a + 1;
      if (!copy && to >= a && to <= z + 1) return;
      const moving = this.blocks.slice(a, z + 1);
      const put = copy ? moving.map((x) => ({ id: FS.uid(), type: x.type, src: x.src, level: x.level, folded: x.folded, lang: x.lang })) : moving;
      if (!copy) { this.blocks.splice(a, n); if (to > z) to -= n; }
      this.blocks.splice(to, 0, ...put);
      this.msel = null;
      this.renderAll();
      this.changed({ force: true });
      this.selectBlocks(to, to + n - 1);
      if (n === 1) this.focusBlock(to, 0);
    }
    /* Move a block, or the selected blocks, one step up or down. A CLOSED heading moves with its
     * section, and a closed section is stepped over whole, so moving never splits what is folded. */
    moveBlock(b, dir) { const [a, z] = this.blockRangeFor(b); this.moveRange(a, z, dir); }
    moveSelection(dir) {
      const m = this.msel;
      const b = m ? m.a.b : this.active;
      if (!b || !this.blocks.includes(b)) return;
      const [a, z] = this.blockRangeFor(b);
      this.moveRange(a, z, dir);
    }
    moveRange(a, z, dir) {
      const unit = (k) => {                 // [first, last] of the visible unit at k
        let s0 = k;
        while (s0 > 0 && this.isHidden(this.blocks[s0])) s0--;
        const h = this.blocks[s0];
        return [s0, h.type === 'h' && h.folded ? MD.sectionEnd(this.blocks, s0) : s0];
      };
      if (dir < 0 && a === 0) return;
      if (dir > 0 && z >= this.blocks.length - 1) return;
      const caretB = this.active, body = caretB && caretB.el && caretB.el.querySelector('.blk-body');
      const caret = body && document.activeElement === body ? getCaret(body) : 0;
      const n = z - a + 1;
      const moving = this.blocks.splice(a, n);
      let at;
      if (dir < 0) at = unit(a - 1)[0];
      else { const [, nz] = unit(a); at = nz + 1; }
      this.blocks.splice(at, 0, ...moving);
      const hadSel = !!this.msel;
      this.msel = null;
      this.renderAll();
      this.changed({ force: true });
      if (hadSel || n > 1) this.selectBlocks(at, at + n - 1);
      else this.focusBlock(at, caret);
    }
    /* Whole-block actions on the selection (or `b`): copy, cut, duplicate, delete. */
    blocksMarkdown(a, z) { return MD.joinBlocks(this.blocks.slice(a, z + 1)); }
    copyBlocks(b) { const [a, z] = this.blockRangeFor(b); FS.copyText(this.blocksMarkdown(a, z)); FS.toast((z - a + 1) + (z > a ? ' blocks' : ' block') + ' copied', 'ok'); }
    cutBlocks(b) { const [a, z] = this.blockRangeFor(b); FS.copyText(this.blocksMarkdown(a, z)); this.deleteBlocks(a, z); }
    duplicateBlocks(b) { const [a, z] = this.blockRangeFor(b); this.moveBlocksTo(a, z, z + 1, true); }
    deleteBlocks(a, z) {
      this.blocks.splice(a, z - a + 1);
      this.msel = null;
      if (!this.blocks.length) this.blocks.push({ id: FS.uid(), type: 'p', src: '' });
      this.renderAll();
      this.paintMsel();
      this.changed({ force: true });
      this.focusBlock(Math.min(a, this.blocks.length - 1), 'end');
    }
    editSource(b) {
      const ta = el('textarea', { class: 'source-edit', spellcheck: 'false' });
      ta.value = b.src;
      const host = b.el.querySelector('.widget-host') || b.el;
      host.innerHTML = '';
      host.appendChild(ta);
      ta.style.height = Math.min(400, 40 + ta.value.split('\n').length * 20) + 'px';
      ta.focus();
      const done = () => {
        const src = ta.value.replace(/\s+$/, '');
        const parts = MD.splitBlocks(src);
        const i = this.blocks.indexOf(b);
        if (!parts.length) { this.deleteBlock(b); return; }
        const seq = parts.map((x) => Object.assign({ id: FS.uid() }, x));
        this.blocks.splice(i, 1, ...seq);
        this.renderAll();
        this.changed({ force: true });
      };
      ta.addEventListener('blur', done);
      ta.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); ta.blur(); } e.stopPropagation(); });
    }
    setBlockSrc(b, src) {
      b.src = src;
      const body = b.el && b.el.querySelector('.blk-body');
      if (body) this.decorateInto(body, b); else this.rerender(b);
      this.renumberAfter(b);
      this.changed();
    }
    setHeadingLevel(b, lv) {
      if (b.type !== 'h') return;
      this.setBlockSrc(b, b.src.replace(/^#{1,6}\s+/, '#'.repeat(lv) + ' '));
    }
    blockMenu(anchor, b) {
      FS.popover(anchor, (pop, close) => {
        const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
        const [ra, rz] = this.blockRangeFor(b);
        const many = rz > ra;
        if (many) {
          // b is in a selection of several blocks (or heads a closed section): act on all of them
          const n = rz - ra + 1;
          pop.appendChild(el('div', { class: 'menu-label', 'data-test': 'blocks-label' }, n + ' blocks' + (this.msel ? ' selected' : ' (the closed section)')));
          item('Move up\u2003Alt+Shift+\u2191', () => this.moveRange(ra, rz, -1));
          item('Move down\u2003Alt+Shift+\u2193', () => this.moveRange(ra, rz, 1));
          item('Cut', () => this.cutBlocks(b));
          item('Copy', () => this.copyBlocks(b));
          item('Duplicate', () => this.duplicateBlocks(b));
          item('Delete', () => this.deleteBlocks(ra, rz), 'danger');
          pop.appendChild(el('hr'));
          this.insertSection(pop, close, b);
          return;
        }
        item('Move up', () => this.moveBlock(b, -1));
        item('Move down', () => this.moveBlock(b, 1));
        pop.appendChild(el('hr'));
        this.insertSection(pop, close, b);
        if (TEXT_TYPES.has(b.type)) {
          pop.appendChild(el('hr'));
          item('Turn into paragraph', () => { b.src = b.src.replace(/^(#{1,6}\s+|\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?|\s*>\s?)/gm, ''); b.type = 'p'; this.rerender(b); this.changed(); });
          if (b.type === 'h') {
            const cur = MD.headingLevel(b);
            const row = el('div', { class: 'menu-row', 'data-test': 'heading-levels' }, el('span', { class: 'menu-label' }, 'Heading level'));
            for (let lv = 1; lv <= 6; lv++) row.appendChild(el('button', { class: 'tog' + (lv === cur ? ' on' : ''), title: 'Heading ' + lv, onclick: () => { close(); this.setHeadingLevel(b, lv); } }, 'H' + lv));
            pop.appendChild(row);
            item(b.folded ? 'Expand this section' : 'Collapse this section', () => this.setFold(b, !b.folded));
            item('Collapse all headings', () => this.setAllFolds(true));
            item('Expand all headings', () => this.setAllFolds(false));
          } else {
            const row = el('div', { class: 'menu-row', 'data-test': 'heading-levels' }, el('span', { class: 'menu-label' }, 'Turn into heading'));
            for (let lv = 1; lv <= 6; lv++) row.appendChild(el('button', { class: 'tog', title: 'Heading ' + lv, onclick: () => { close(); this.active = b; this.focusBlock(this.blocks.indexOf(b), 0); this.linePrefix('h', lv); } }, 'H' + lv));
            pop.appendChild(row);
          }
          item('Turn into checklist', () => { this.active = b; this.focusBlock(this.blocks.indexOf(b), 0); this.linePrefix('task'); });
          if (b.type === 'list') {
            const row = el('div', { class: 'menu-row', 'data-test': 'list-indent' }, el('span', { class: 'menu-label' }, 'List indent'));
            row.appendChild(el('button', { class: 'tog', title: 'Decrease indent (Shift+Tab, Ctrl+[)', onclick: () => { close(); this.active = b; if (document.activeElement !== b.el.querySelector('.blk-body')) this.focusBlock(this.blocks.indexOf(b), 0); this.indentActive(-1); } }, '\u21e4 Less'));
            row.appendChild(el('button', { class: 'tog', title: 'Increase indent (Tab, Ctrl+])', onclick: () => { close(); this.active = b; if (document.activeElement !== b.el.querySelector('.blk-body')) this.focusBlock(this.blocks.indexOf(b), 0); this.indentActive(1); } }, '\u21e5 More'));
            pop.appendChild(row);
          }
          if (/^\s*\d+[.)]\s/.test(b.src)) {
            // the first item's typed number is where the list starts (markdown.numberLines)
            item('Start numbering at…', () => {
              const m = /^(\s*)(\d+)([.)]\s)/.exec(b.src);
              const cur = MD.numberLines(b.src.split('\n'), b.type, this.numCtxFor(b)).find((n) => n != null);
              const v = window.prompt('Start this list at:', String(cur || m[2]));
              const n = parseInt(v, 10);
              if (!(n >= 0)) return;
              this.setBlockSrc(b, b.src.replace(/^(\s*)\d+([.)]\s)/, '$1' + n + '$2'));
            });
            const prev = this.numCtxFor(b).counters;
            if (prev.length) item('Continue numbering from the list above', () => this.setBlockSrc(b, b.src.replace(/^(\s*)\d+([.)]\s)/, '$1' + ((prev[0] || 0) + 1) + '$2')));
          }
        } else {
          pop.appendChild(el('hr'));
          item('Edit source', () => this.editSource(b));
          if (b.type === 'table') {
            if (this.neighbourTable(b, -1)) item('Merge with table above', () => this.mergeTables(b, -1));
            if (this.neighbourTable(b, 1)) item('Merge with table below', () => this.mergeTables(b, 1));
          }
        }
        pop.appendChild(el('hr'));
        item('Copy block', () => this.copyBlocks(b));
        item('Cut block', () => this.cutBlocks(b));
        item('Duplicate', () => this.insertBlockAfter(b, { type: b.type, src: b.src, lang: b.lang }, false));
        item('Delete block', () => this.deleteBlock(b), 'danger');
      });
    }

    /* -- undo / redo --------------------------------------------------------------------- */
    snapshot() {
      const b = this.active;
      let caret = 0;
      if (b && b.el && TEXT_TYPES.has(b.type)) { const body = b.el.querySelector('.blk-body'); if (body && document.activeElement === body) caret = getCaret(body); }
      return { md: this.getMarkdown(), idx: b ? this.blocks.indexOf(b) : -1, caret };
    }
    pushSnapshot(force) {
      const now = Date.now();
      const snap = this.snapshot();
      const top = this.undo[this.undo.length - 1];
      if (top && top.md === snap.md) return;
      if (!force && top && now - this.lastSnap < 600 && top.idx === snap.idx) { this.undo[this.undo.length - 1] = snap; }
      else { this.undo.push(snap); if (this.undo.length > 200) this.undo.shift(); }
      this.lastSnap = now;
      this.redo = [];
    }
    restore(snap) {
      this.blocks = MD.splitBlocks(snap.md).map((b) => Object.assign({ id: FS.uid() }, b));
      if (!this.blocks.length) this.blocks.push({ id: FS.uid(), type: 'p', src: '' });
      this.renderAll();
      if (snap.idx >= 0 && snap.idx < this.blocks.length) this.focusBlock(snap.idx, snap.caret);
      if (this.opts.onChange) this.opts.onChange(this.getMarkdown());
    }
    undoStep() {
      if (this.undo.length < 2) return;
      const cur = this.undo.pop();
      this.redo.push(cur);
      this.restore(this.undo[this.undo.length - 1]);
    }
    redoStep() {
      const snap = this.redo.pop();
      if (!snap) return;
      this.undo.push(snap);
      this.restore(snap);
    }

    /* -- find in note ---------------------------------------------------------------------- */
    find(query) {
      this.findQuery = query || '';
      this.root.querySelectorAll('.blk-body').forEach((body) => this.applyFind(body));
      this.hits = [...this.root.querySelectorAll('.find-hit')];
      this.hitIdx = -1;
      return this.hits.length;
    }
    applyFind(body) {
      body.querySelectorAll('.find-hit').forEach((h) => { const t = document.createTextNode(h.textContent); h.replaceWith(t); });
      body.normalize();
      const q = FS.normalize(this.findQuery, true);
      if (!q) return;
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      const nodes = [];
      let n;
      while ((n = walker.nextNode())) nodes.push(n);
      for (const node of nodes) {
        const text = node.nodeValue;
        const norm = FS.normalize(text, true);
        if (norm.length !== text.length) {   // normalisation changed lengths (rare): fall back to case-insensitive
          const idx = text.toLowerCase().indexOf(this.findQuery.toLowerCase());
          if (idx < 0) continue;
          wrapRange(node, idx, idx + this.findQuery.length);
          continue;
        }
        let p = norm.indexOf(q);
        let cur = node;
        let base = 0;
        while (p >= 0 && cur) {
          const rest = wrapRange(cur, p - base, p - base + q.length);
          base = p + q.length;
          cur = rest;
          p = cur ? FS.normalize(cur.nodeValue, true).indexOf(q) + base : -1;
          if (p === base - 1) break;
        }
      }
    }
    findNext(dir) {
      this.hits = [...this.root.querySelectorAll('.find-hit')];
      if (!this.hits.length) return 0;
      this.hits.forEach((h) => h.classList.remove('cur'));
      this.hitIdx = ((this.hitIdx == null ? -1 : this.hitIdx) + dir + this.hits.length) % this.hits.length;
      const h = this.hits[this.hitIdx];
      const hb = this.blocks.find((x) => x.el && x.el.contains(h));
      if (hb) this.reveal(hb);
      h.classList.add('cur');
      h.scrollIntoView({ block: 'center' });
      return this.hitIdx + 1;
    }
  }

  /* Toggle an inline marker (**, *, ==, `) around the selection [a, z) of `text`.
   *
   * Emphasis never spans a line break in markdown, so a selection across lines is wrapped
   * LINE BY LINE (Seth, 2026-10-12: a selection of two paragraphs got one `*` at the start and one
   * at the end, "but that's not valid markdown"). Block prefixes (`- `, `1. `, `- [ ] `, `# `, `> `)
   * and leading/trailing spaces stay outside the markers; empty lines are skipped. When every
   * selected line is already wrapped, the markers come off instead. A collapsed selection inserts
   * an empty pair with the caret in the middle. Returns {text, a, z} with the new selection. */
  const PREFIX_RE = /^(\s*(?:#{1,6}\s+|(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?|>\s?))/;
  function wrapLines(text, a, z, m) {
    if (a === z) return { text: text.slice(0, a) + m + m + text.slice(a), a: a + m.length, z: a + m.length };
    const segs = [];
    let lineStart = text.lastIndexOf('\n', a - 1) + 1;
    while (lineStart < z) {
      let lineEnd = text.indexOf('\n', lineStart);
      if (lineEnd < 0) lineEnd = text.length;
      let la = Math.max(a, lineStart), lz = Math.min(z, lineEnd);
      if (la === lineStart) { const pm = PREFIX_RE.exec(text.slice(lineStart, lineEnd)); if (pm) la = Math.max(la, lineStart + pm[1].length); }
      while (la < lz && /\s/.test(text[la])) la++;
      while (lz > la && /\s/.test(text[lz - 1])) lz--;
      if (lz > la) segs.push({ la, lz });
      lineStart = lineEnd + 1;
    }
    if (!segs.length) return { text, a, z };
    const wrappedOutside = (g) => text.slice(g.la - m.length, g.la) === m && text.slice(g.lz, g.lz + m.length) === m;
    const wrappedInside = (g) => { const inner = text.slice(g.la, g.lz); return inner.length >= 2 * m.length && inner.startsWith(m) && inner.endsWith(m); };
    const allWrapped = segs.every((g) => wrappedOutside(g) || wrappedInside(g));
    let out = text, na = a, nz = z;
    for (const g of segs.slice().reverse()) {          // right to left so earlier offsets stay valid
      if (allWrapped) {
        if (wrappedInside(g)) { out = out.slice(0, g.la) + out.slice(g.la + m.length, g.lz - m.length) + out.slice(g.lz); nz -= 2 * m.length; }
        else { out = out.slice(0, g.la - m.length) + out.slice(g.la, g.lz) + out.slice(g.lz + m.length); nz -= 2 * m.length; if (g.la - m.length < na) na -= m.length; }
      } else if (!(wrappedOutside(g) || wrappedInside(g))) {
        out = out.slice(0, g.la) + m + out.slice(g.la, g.lz) + m + out.slice(g.lz);
        nz += 2 * m.length;
      }
    }
    if (allWrapped) { na = Math.max(0, na); nz = Math.max(na, nz); }
    else if (segs[0].la === a) { /* markers were inserted at the selection start: keep them inside it */ nz = Math.min(out.length, nz); }
    return { text: out, a: na, z: Math.min(out.length, nz) };
  }

  /* Could this be text copied from FLEx's interlinear view? Tabs between cells, or a few
   * short lines, and no markdown structure of its own. */
  function looksInterlinear(text) {
    const t = text.trim();
    if (!t || t.length > 2000 || /^(https?:|silfw:)/i.test(t)) return false;
    if (/\t/.test(t)) return true;
    const lines = t.split('\n').filter((l) => l.trim());
    if (lines.length > 12) return false;
    if (lines.some((l) => /^(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|\{\{)/.test(l.trim()))) return false;
    return lines.every((l) => l.length <= 200) && t.length >= 6;
  }

  function wrapRange(textNode, a, b) {
    if (a < 0 || b > textNode.nodeValue.length || a >= b) return null;
    const mid = textNode.splitText(a);
    const rest = mid.splitText(b - a);
    const span = document.createElement('span');
    span.className = 'find-hit';
    mid.parentNode.insertBefore(span, mid);
    span.appendChild(mid);
    return rest;
  }

  FS.Editor = Editor;
  /* A line break written `<br>` (in a table cell, or typed in text) is ONE thing to delete (Seth,
   * 2026-10-17: "Deleting <br> with one backspace just deletes part and leaves the text … behind"):
   * Backspace just after it, Delete just before it, or either with the caret inside it, first
   * selects the whole `<br>` — the key's own deletion then takes it in one go, through each
   * editable's usual input handling (text blocks and table cells alike). */
  const BR_TOKEN = /<br\s*\/?>/gi;
  function brAround(text, caret, back) {
    BR_TOKEN.lastIndex = 0;
    let m;
    while ((m = BR_TOKEN.exec(text))) {
      const a = m.index, z = a + m[0].length;
      if (back ? (caret > a && caret <= z) : (caret >= a && caret < z)) return [a, z];
      if (a > caret) break;
    }
    return null;
  }
  document.addEventListener('keydown', (e) => {
    if ((e.key !== 'Backspace' && e.key !== 'Delete') || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const host = e.target && e.target.closest ? e.target.closest('.blk-body, .cell-edit') : null;
    const sel = window.getSelection();
    if (!host || !sel || !sel.rangeCount || !sel.isCollapsed || !host.contains(sel.anchorNode)) return;
    const span = brAround(host.textContent, getCaret(host), e.key === 'Backspace');
    if (span) setCaret(host, span[0], span[1]);
  }, true);

  FS.editor = { getCaret, getCaretEnd, setCaret, pointAt, wrapLines, revealMarkers, TEXT_TYPES, brAround };
})();
