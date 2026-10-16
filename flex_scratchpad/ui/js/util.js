/* util.js — small shared helpers. Classic script: everything hangs off window.FS.
 * (The page is a file:// document inside pywebview, so there are no ES modules.) */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  FS.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);

  FS.el = function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
        else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
        else if (k === 'dataset') Object.assign(e.dataset, v);
        else if (k === 'html') e.innerHTML = v;
        else if (k === 'text') e.textContent = v;
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return e;
  };

  FS.debounce = function (fn, ms) {
    let t = null;
    const d = function (...args) {
      clearTimeout(t);
      t = setTimeout(() => { t = null; fn.apply(this, args); }, ms);
    };
    d.flush = function (...args) { if (t) { clearTimeout(t); t = null; fn.apply(this, args); } };
    d.cancel = function () { clearTimeout(t); t = null; };
    return d;
  };

  FS.uid = () => 'u' + Math.random().toString(36).slice(2, 10);

  /* Grapheme clusters, so character ranges never split a base letter from its combining
   * marks (and never cut a surrogate pair). Intl.Segmenter exists in Chromium/WebView2. */
  const seg = typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;
  FS.graphemes = function (s) {
    s = String(s == null ? '' : s);
    if (!s) return [];
    if (seg) return Array.from(seg.segment(s), (x) => x.segment);
    return Array.from(s);
  };

  /* Casefold + NFKC, optionally stripping combining marks — the same rule the Python index uses. */
  FS.normalize = function (s, stripMarks) {
    s = String(s == null ? '' : s);
    try {
      if (stripMarks) return s.normalize('NFKD').replace(/\p{M}+/gu, '').toLowerCase();
      return s.normalize('NFKC').toLowerCase();
    } catch (e) { return s.toLowerCase(); }
  };

  FS.fmtTime = function (ms) {
    if (ms == null || isNaN(ms)) return '';
    const s = Math.max(0, ms) / 1000;
    const m = Math.floor(s / 60);
    const r = s - m * 60;
    return m + ':' + (r < 10 ? '0' : '') + r.toFixed(1);
  };

  FS.relTime = function (iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.round(diff / 60) + ' min ago';
    if (diff < 86400 && d.getDate() === new Date().getDate()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (diff < 7 * 86400) return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString();
  };

  FS.readableTextColor = function (hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return '#fff';
    const n = parseInt(m[1], 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) > 160 ? '#1a1d21' : '#fff';
  };

  /* A tiny event bus for app-wide notifications. */
  const listeners = {};
  FS.on = (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); return () => FS.off(ev, fn); };
  FS.off = (ev, fn) => { listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn); };
  FS.emit = (ev, data) => { for (const fn of listeners[ev] || []) { try { fn(data); } catch (e) { console.error(e); } } };

  /* Toasts. */
  FS.toast = function (msg, kind) {
    let host = document.getElementById('toasts');
    if (!host) { host = FS.el('div', { id: 'toasts' }); document.body.appendChild(host); }
    const t = FS.el('div', { class: 'toast ' + (kind || '') }, msg);
    host.appendChild(t);
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, kind === 'error' ? 6000 : 2600);
  };

  /* A "working on it" pill with a spinner, for a wait the user caused (a paste being looked up
   * in the project). It appears only after `delay` ms so a quick answer never flashes it, sits
   * by the caret, changes to `slowMsg` after `slowAfter` ms, and with `onCancel` carries a button
   * (and Esc) to give up waiting. Returns done(), which removes it; call it in every path. */
  FS.busy = function (msg, opts) {
    opts = opts || {};
    let node = null, slow = null, finished = false;
    // where the caret is NOW: the paste point, before anything moves
    let at = null;
    try {
      const sel = window.getSelection();
      if (sel && sel.rangeCount) { const r = sel.getRangeAt(0).getBoundingClientRect(); if (r.width || r.height || r.top) at = r; }
      if (!at || (!at.top && !at.left)) { const a = document.activeElement; if (a && a !== document.body) at = a.getBoundingClientRect(); }
    } catch (e) { at = null; }
    const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancel(); } };
    const cancel = () => { if (finished) return; done(); if (opts.onCancel) opts.onCancel(); };
    function done() {
      finished = true;
      clearTimeout(timer); clearTimeout(slow);
      if (node) node.remove();
      document.removeEventListener('keydown', onKey, true);
    }
    const timer = setTimeout(() => {
      if (finished) return;
      const text = FS.el('span', { class: 'busy-msg' }, msg);
      node = FS.el('div', { class: 'busy-pill', role: 'status', 'aria-live': 'polite' },
        FS.el('span', { class: 'spinner', 'aria-hidden': 'true' }), text,
        opts.onCancel ? FS.el('button', { class: 'lnk', title: 'Stop waiting (Esc)', onclick: cancel }, opts.cancelLabel || 'Cancel') : null);
      document.body.appendChild(node);
      if (at && (at.top || at.left)) {
        const w = node.offsetWidth, h = node.offsetHeight;
        const left = Math.max(8, Math.min(at.left, window.innerWidth - w - 8));
        let top = at.bottom + 8;
        if (top + h > window.innerHeight - 8) top = Math.max(8, at.top - h - 8);
        Object.assign(node.style, { left: left + 'px', top: top + 'px' });
      } else node.classList.add('centred');
      if (opts.onCancel) document.addEventListener('keydown', onKey, true);
      if (opts.slowMsg) slow = setTimeout(() => { text.textContent = opts.slowMsg; }, opts.slowAfter || 3000);
    }, opts.delay == null ? 200 : opts.delay);
    return done;
  };

  /* Lightweight modal: returns {root, body, close}. */
  FS.modal = function (opts) {
    const root = FS.el('div', { class: 'modal-backdrop' });
    const box = FS.el('div', { class: 'modal ' + (opts.class || ''), role: 'dialog', 'aria-modal': 'true' });
    const head = FS.el('div', { class: 'modal-head' },
      FS.el('div', { class: 'modal-title' }, opts.title || ''),
      FS.el('button', { class: 'icon-btn', title: 'Close', onclick: () => close() }, '✕'));
    const body = FS.el('div', { class: 'modal-body' });
    box.append(head, body);
    root.appendChild(box);
    function close(result) { root.remove(); document.removeEventListener('keydown', onKey); if (opts.onClose) opts.onClose(result); }
    function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); close(); } }
    document.addEventListener('keydown', onKey);
    root.addEventListener('mousedown', (e) => { if (e.target === root && !opts.sticky) close(); });
    document.body.appendChild(root);
    return { root, box, body, close };
  };

  /* Simple positioned popover near an anchor element; closes on outside click / Escape. */
  FS.popover = function (anchor, build, opts) {
    opts = opts || {};
    document.querySelectorAll('.popover').forEach((p) => p._close && p._close());
    const pop = FS.el('div', { class: 'popover ' + (opts.class || '') });
    pop._close = close;
    build(pop, close);
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    let left = r.left, top = r.bottom + 6;
    if (left + pw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - pw - 8);
    if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 6);
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
    function onDown(e) { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) close(); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    setTimeout(() => { document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey); }, 0);
    function close() { pop.remove(); document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); if (opts.onClose) opts.onClose(); }
    return pop;
  };

  /* A popover at a screen point (context menus): a zero-size fixed anchor, removed on close. */
  FS.popoverAt = function (x, y, build, opts) {
    const anchor = FS.el('div', { style: { position: 'fixed', left: x + 'px', top: (y - 6) + 'px', width: '0', height: '0' } });
    document.body.appendChild(anchor);
    return FS.popover(anchor, build, Object.assign({}, opts || {}, { onClose: () => { anchor.remove(); if (opts && opts.onClose) opts.onClose(); } }));
  };

  /* A small in-page confirmation anchored at the control (no native dialog): resolves true/false. */
  FS.confirmAt = function (anchor, message, yesLabel) {
    return new Promise((resolve) => {
      let done = false;
      FS.popover(anchor, (pop, close) => {
        pop.appendChild(FS.el('div', { class: 'row' }, message));
        pop.appendChild(FS.el('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '6px' } },
          FS.el('button', { class: 'btn', onclick: () => { done = true; close(); resolve(false); } }, 'Cancel'),
          FS.el('button', { class: 'btn danger', onclick: () => { done = true; close(); resolve(true); } }, yesLabel || 'Remove')));
      }, { onClose: () => { if (!done) resolve(false); } });
    });
  };

  FS.copyText = async function (text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    const ta = FS.el('textarea', { style: { position: 'fixed', left: '-1000px' } }, text);
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    ta.remove();
    return true;
  };
})();
