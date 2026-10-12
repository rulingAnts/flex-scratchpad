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
        // may hold only a <br>), never at the tail of the "\n" text node
        const next = n.nextSibling;
        if (next && next.nodeType === 1) {
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
  function setCaret(root, start, end) {
    const sel = window.getSelection();
    if (!sel) return;
    const a = pointAt(root, Math.max(0, Math.min(start, root.textContent.length)));
    const b = end == null ? a : pointAt(root, Math.max(0, Math.min(end, root.textContent.length)));
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

  const TEXT_TYPES = new Set(['p', 'h', 'list', 'quote', 'code']);
  const PLACEHOLDER = 'Write something, or type / for a menu';

  /* ------------------------------------------------------------------ the editor */
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
      root.addEventListener('click', (e) => { if (e.target === root) this.focusBlock(this.blocks.length - 1, 'end', true); });
      root.addEventListener('focusin', (e) => { const w = e.target.closest('.widget'); this.activeTable = w && w._table ? w._table : null; });
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
      if (this.opts.onChange) this.opts.onChange(this.getMarkdown());
    }

    /* -- rendering --------------------------------------------------------------- */
    renderAll() {
      this.root.innerHTML = '';
      this.blocks.forEach((b, i) => this.root.appendChild(this.renderBlock(b, i)));
    }
    renderBlock(b, i) {
      const wrap = el('div', { class: 'blk blk-' + b.type, dataset: { id: b.id } });
      b.el = wrap;
      const handle = el('div', { class: 'blk-handle' }, el('button', { title: 'Block menu', onmousedown: (e) => { e.preventDefault(); this.blockMenu(e.currentTarget, b); } }, '⋮'));
      wrap.appendChild(handle);
      if (TEXT_TYPES.has(b.type)) {
        const body = el('div', { class: 'blk-body', contenteditable: 'true', spellcheck: b.type === 'code' ? 'false' : 'true', dir: 'auto', 'data-ph': b.type === 'p' && i === 0 && this.blocks.length === 1 ? PLACEHOLDER : '' });
        body.innerHTML = MD.decorate(b.src, b.type);
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
        });
      } else if (b.type === 'flex') {
        const spec = FS.flexref.parse(b.src);
        if (!spec) { host.appendChild(el('div', { class: 'flex-err' }, 'Unreadable FLEx embed: ' + b.src)); return; }
        FS.interlinear.render(host, spec, {
          editable: true,
          onSpecChange: (s) => { b.src = FS.flexref.serialize(s); this.changed(); FS.interlinear.render(host, s, this._flexOpts(b, host)); },
          editSource: () => this.editSource(b),
        });
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
    _flexOpts(b, host) {
      return { editable: true, onSpecChange: (s) => { b.src = FS.flexref.serialize(s); this.changed(); FS.interlinear.render(host, s, this._flexOpts(b, host)); }, editSource: () => this.editSource(b) };
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
        const html = MD.decorate(text, b.type);
        if (html !== body.innerHTML) { body.innerHTML = html; setCaret(body, caret, caretEnd); }
        this.applyFind(body);
      };
      body.addEventListener('compositionstart', () => { this.composing = true; });
      body.addEventListener('compositionend', () => { this.composing = false; refresh(); });
      body.addEventListener('input', () => { if (!this.composing) queueMicrotask(refresh); });
      body.addEventListener('focus', () => { b.el.classList.add('focus'); this.active = b; if (this.opts.onFocusChange) this.opts.onFocusChange(b); });
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
        const table = FS.tables.fromClipboard(dt);
        if (table) { e.preventDefault(); this.insertBlockSourceAtCaret(body, b, table); return; }
        // image paste (files) — beforeinput does not expose them
        const files = dt && dt.files;
        if (files && files.length && this.opts.onPasteImage) { e.preventDefault(); this.opts.onPasteImage(files[0], (md) => this.insertTextAtCaret(body, b, md)); }
      });
    }

    onBeforeInput(e, body, b) {
      const it = e.inputType;
      if (it === 'historyUndo') { e.preventDefault(); this.undoStep(); return; }
      if (it === 'historyRedo') { e.preventDefault(); this.redoStep(); return; }
      if (it === 'insertParagraph') { e.preventDefault(); this.enter(body, b); return; }
      if (it === 'insertLineBreak') { e.preventDefault(); this.insertTextAtCaret(body, b, '\n'); return; }
      if (it === 'insertFromPaste' || it === 'insertFromDrop') {
        e.preventDefault();
        const dt = e.dataTransfer;
        const table = FS.tables.fromClipboard(dt);          // a table copied from Excel / Word / a browser
        if (table) { this.insertBlockSourceAtCaret(body, b, table); return; }
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
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); this.undoStep(); return; }
      if (mod && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); this.redoStep(); return; }
      if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); this.wrapSelection('**'); return; }
      if (mod && e.key.toLowerCase() === 'i') { e.preventDefault(); this.wrapSelection('*'); return; }
      if (mod && e.shiftKey && e.key.toLowerCase() === 'h') { e.preventDefault(); this.wrapSelection('=='); return; }
      if (mod && e.key === 'Enter') { e.preventDefault(); this.insertBlockAfter(b, { type: 'p', src: '' }, true); return; }
      if (e.key === 'Tab' && (b.type === 'list' || b.type === 'code')) { e.preventDefault(); this.indent(body, b, e.shiftKey ? -1 : 1); return; }
      if (e.key === 'Escape') { body.blur(); return; }
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
    setText(body, b, text, caret, caretEnd) {
      b.src = text;
      body.innerHTML = MD.decorate(text, b.type);
      if (caret != null) setCaret(body, caret, caretEnd);
      this.changed();
      this.applyFind(body);
    }
    insertTextAtCaret(body, b, text) {
      const a = getCaret(body), z = getCaretEnd(body);
      const s = body.textContent;
      this.setText(body, b, s.slice(0, a) + text + s.slice(z), a + text.length);
    }
    pasteText(body, b, text) {
      const trimmed = text.trim();
      if (this.opts.onPasteLink && (/^silfw:\/\//i.test(trimmed) || FS.flexref.GUID.test(trimmed))) {
        this.opts.onPasteLink(trimmed, (md, asBlock) => { if (asBlock) this.insertBlockSourceAtCaret(body, b, md); else this.insertTextAtCaret(body, b, md); });
        return;
      }
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
      const s = body.textContent;
      const sel = s.slice(a, z);
      if (s.slice(a - m.length, a) === m && s.slice(z, z + m.length) === m) { this.setText(body, b, s.slice(0, a - m.length) + sel + s.slice(z + m.length), a - m.length, z - m.length); return; }
      if (sel.startsWith(m) && sel.endsWith(m) && sel.length >= 2 * m.length) { this.setText(body, b, s.slice(0, a) + sel.slice(m.length, -m.length) + s.slice(z), a, z - 2 * m.length); return; }
      this.setText(body, b, s.slice(0, a) + m + sel + m + s.slice(z), a + m.length, z + m.length);
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
    indent(body, b, dir) {
      const a = getCaret(body);
      const s = body.textContent;
      const lineStart = s.lastIndexOf('\n', a - 1) + 1;
      const line = s.slice(lineStart, s.indexOf('\n', lineStart) < 0 ? s.length : s.indexOf('\n', lineStart));
      let newLine;
      if (dir > 0) newLine = '  ' + line;
      else newLine = line.replace(/^ {1,2}/, '');
      const delta = newLine.length - line.length;
      this.setText(body, b, s.slice(0, lineStart) + newLine + s.slice(lineStart + line.length), Math.max(lineStart, a + delta));
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
        else if (m) marker = m[1] + (m[3] ? (parseInt(m[3], 10) + 1) + m[2].slice(-1) : m[2]) + ' ' + (m[4] ? '[ ] ' : '');
        else marker = '- ';
        this.setText(body, b, before + '\n' + marker + after, a + 1 + marker.length);
        return;
      }
      // paragraph / heading: split into two blocks
      const i = this.blocks.indexOf(b);
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
        else if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); this.focusBlock(i - 1, 'end'); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); this.focusBlock(i + 1, 0, true); }
        else if (e.key === 'Enter') { e.preventDefault(); if (b.type === 'table') { const cell = wrap.querySelector('.cell-view'); if (cell) cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); } else if (b.type === 'chart') FS.charts.editDialog(b.src, (src) => { b.src = src; this.changed(); this.rerender(b); }); else this.insertBlockAfter(b, { type: 'p', src: '' }, true); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? this.redoStep() : this.undoStep(); }
      });
      if (b.type === 'hr') wrap.addEventListener('click', () => wrap.focus());
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
    insertMarkdown(md, asBlock) {
      if (this.activeTable && this.activeTable.insertText) { this.activeTable.insertText(md.replace(/\n/g, ' ')); return; }
      let b = this.active && this.blocks.includes(this.active) ? this.active : this.blocks[this.blocks.length - 1];
      if (!b) { this.load(md); this.changed({ force: true }); return; }
      if (TEXT_TYPES.has(b.type) && b.el) {
        const body = b.el.querySelector('.blk-body');
        if (document.activeElement !== body) { body.focus(); setCaret(body, body.textContent.length); }
        if (!asBlock) { this.insertTextAtCaret(body, b, md); return; }
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
    deleteBlock(b) {
      const i = this.blocks.indexOf(b);
      if (i < 0) return;
      this.blocks.splice(i, 1);
      b.el.remove();
      if (!this.blocks.length) { this.blocks.push({ id: FS.uid(), type: 'p', src: '' }); this.renderAll(); }
      this.changed({ force: true });
      this.focusBlock(Math.min(i, this.blocks.length - 1), 'end');
    }
    moveBlock(b, dir) {
      const i = this.blocks.indexOf(b), j = i + dir;
      if (j < 0 || j >= this.blocks.length) return;
      this.blocks.splice(i, 1); this.blocks.splice(j, 0, b);
      this.renderAll();
      this.changed({ force: true });
      this.focusBlock(j, 0);
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
    blockMenu(anchor, b) {
      FS.popover(anchor, (pop, close) => {
        const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
        item('Move up', () => this.moveBlock(b, -1));
        item('Move down', () => this.moveBlock(b, 1));
        if (TEXT_TYPES.has(b.type)) {
          pop.appendChild(el('hr'));
          item('Turn into paragraph', () => { b.src = b.src.replace(/^(#{1,6}\s+|\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?|\s*>\s?)/gm, ''); b.type = 'p'; this.rerender(b); this.changed(); });
          item('Turn into heading', () => { this.active = b; this.focusBlock(this.blocks.indexOf(b), 0); this.linePrefix('h', 2); });
          item('Turn into checklist', () => { this.active = b; this.focusBlock(this.blocks.indexOf(b), 0); this.linePrefix('task'); });
        } else {
          pop.appendChild(el('hr'));
          item('Edit source', () => this.editSource(b));
        }
        pop.appendChild(el('hr'));
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
      h.classList.add('cur');
      h.scrollIntoView({ block: 'center' });
      return this.hitIdx + 1;
    }
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
  FS.editor = { getCaret, getCaretEnd, setCaret, pointAt, TEXT_TYPES };
})();
