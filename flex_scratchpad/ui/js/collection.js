/* An EXAMPLE COLLECTION (Seth, 2026-10-16): a note that is JUST interlinear examples, expanded
 * and numbered in order, and the one kind of note that exports as a FLEx text — "to collect
 * and concentrate certain grammatical constructions … and then have one flex text where I can
 * analyze those in text chart".
 *
 * On disk it is an ordinary note file with `kind: examples` in its header, readable without
 * the app:
 *
 *     ## Shared subject                     a GROUP: a labelled, collapsible block of examples
 *                                           (` {collapsed}` at the end when it is closed); a
 *                                           heading of any level, #…######, and a group holds
 *                                           everything up to the next group of the same or a
 *                                           higher level, sub-groups included (Seth, 2026-10-16);
 *     {{flex:text … seg=4}}                 groups only organise the view — they are not
 *     > Both verbs take the same subject.   exported; every example still is, in order.
 *                                           `> ` lines after an example are its NOTE, which IS
 *     ## Switch reference {collapsed}       exported: a note on the example's first FLEx line.
 *     {{flex:text … seg=7-8}}
 *
 * Here it is a list of cards: the number (counted straight through, groups or not), a grip,
 * ↑ ↓ ✎ ✕, and the example rendered with the usual styling tools. Examples come in through the
 * paste box (FLEx rows or a FLEx link), the FLEx picker, or "Add to an example collection…" on
 * any example in any note. Anything else found in the body (a hand-edited file) is kept, shown
 * muted, and left out of the numbering and the export. */
(function () {
  const el = FS.el;
  const R = FS.flexref;

  /* The embed as a collection keeps it: its styling and lines, without the layout keys a
   * collection decides for itself (numbering, indent, collapsed / expanded). An example IN a
   * collection can be collapsed to a chip there (Seth, 2026-10-17): `keepCollapsed` keeps that
   * flag when the collection rewrites its own examples; one arriving from a note comes open. */
  function cleanEmbed(src, keepCollapsed) {
    const spec = R.parse(String(src || '').trim());
    if (!spec) return null;
    const x = spec.extra || {};
    for (const k of ['ex', 'indent', 'expanded'].concat(keepCollapsed ? [] : ['collapsed'])) delete x[k];
    spec.extra = x;
    return R.serialize(spec);
  }
  const looksLikeFlexRows = (t) => /\t/.test(t) || /^(\d+(\.\d+)?\t)?\s*(Word|Morphemes|Lex\.|Free|Literal|Note)\b/im.test(t);
  const HEADING = /^(#{1,6})\s+(.*?)\s*$/;
  const COLLAPSED = /\s*\{collapsed\}$/;

  /* body → [{t:'group', label, level, collapsed} | {t:'ex', src, spec, note} | {t:'other', src}] */
  const levelOf = (g) => Math.max(1, Math.min(6, (g && g.level) || 2));
  /* Which items closed groups hide: everything after a closed group up to the next group of the
   * same or a higher level (a closed group inside a hidden one adds nothing). */
  function hiddenItems(items) {
    const out = [];
    let fold = 0;
    for (const it of items) {
      const lvl = it.t === 'group' ? levelOf(it) : 0;
      if (fold && lvl && lvl <= fold) fold = 0;
      out.push(!!fold);
      if (!fold && lvl && it.collapsed) fold = lvl;
    }
    return out;
  }
  function parse(body) {
    const items = [];
    let cur = null, other = null;
    for (const raw of String(body || '').replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.replace(/\s+$/, '');
      if (!line.trim()) { cur = null; other = null; continue; }
      const h = HEADING.exec(line);
      if (h) {
        items.push({ t: 'group', label: h[2].replace(COLLAPSED, '').trim(), level: h[1].length, collapsed: COLLAPSED.test(h[2]) });
        cur = null; other = null; continue;
      }
      if (R.isEmbedLine(line)) {
        const spec = R.parse(line.trim());
        if (spec && spec.kind === 'text') { cur = { t: 'ex', src: line.trim(), spec, note: '' }; items.push(cur); other = null; continue; }
      }
      const q = /^>\s?(.*)$/.exec(line);
      if (q && cur) { cur.note += (cur.note ? '\n' : '') + q[1]; continue; }
      cur = null;
      if (other) other.src += '\n' + line; else { other = { t: 'other', src: line }; items.push(other); }
    }
    return items;
  }
  function serialize(items) {
    const out = items.map((i) => {
      if (i.t === 'group') return '#'.repeat(levelOf(i)) + ' ' + (i.label || 'Untitled group') + (i.collapsed ? ' {collapsed}' : '');
      if (i.t === 'ex') {
        const note = (i.note || '').replace(/\s+$/, '');
        return note ? i.src + '\n' + note.split('\n').map((l) => (l ? '> ' + l : '>')).join('\n') : i.src;
      }
      return i.src;
    });
    return out.length ? out.join('\n\n') + '\n' : '';
  }

  class Collection {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts || {};
      this.items = [];
      this.undo = null;               // {items, at, what} or {snapshot, at, what} after a removal
      this.sel = new Set();           // the selected items (objects, so a reorder keeps them)
      this.lastSel = null;            // the anchor of a Shift+click range
      if (root && root.addEventListener) {
        if (root.tabIndex == null || root.tabIndex < 0) root.tabIndex = -1;   // so the keys below reach it
        root.addEventListener('keydown', (e) => this.onKey(e));
        root.addEventListener('paste', (e) => this.onPaste(e));
      }
    }
    load(body) {
      this.items = parse(body);
      this.undo = null;
      this.sel = new Set(); this.lastSel = null;
      this.render();
      return this;
    }
    markdown() { return serialize(this.items); }
    examples() { return this.items.filter((i) => i.t === 'ex'); }
    groups() { return this.items.filter((i) => i.t === 'group'); }
    changed() { if (this.opts.onChange) this.opts.onChange(this.markdown()); }
    /* The examples the FLEx text export takes, in order, each with its note. */
    flextextItems() {
      return this.examples().map((i) => ({ kind: 'text', guid: i.spec.guid, seg: i.spec.seg, at: i.spec.at, label: i.spec.label || '', note: (i.note || '').trim() }));
    }
    /* What the other exports read: blocks as the editor would hold them — groups as headings,
     * examples numbered, notes as paragraphs under them. */
    asEditor() {
      const blocks = [];
      for (const i of this.items) {
        if (i.t === 'group') blocks.push({ type: 'h', level: levelOf(i), src: '#'.repeat(levelOf(i)) + ' ' + i.label });
        else if (i.t === 'ex') {
          const s = R.parse(i.src); s.extra = Object.assign({}, s.extra, { ex: '1' });
          blocks.push({ type: 'flex', src: R.serialize(s) });
          if ((i.note || '').trim()) blocks.push({ type: 'p', src: i.note.trim() });
        } else blocks.push(...FS.markdown.splitBlocks(i.src));
      }
      return { blocks, flextextItems: () => this.flextextItems() };
    }

    /* -- structure ------------------------------------------------------------------ */
    /* The block a group heads: [start, end) — the heading and everything up to the next group of
     * the same or a higher level (its sub-groups included). */
    blockOf(g) {
      const lvl = levelOf(this.items[g]);
      let e = g + 1;
      while (e < this.items.length && !(this.items[e].t === 'group' && levelOf(this.items[e]) <= lvl)) e++;
      return [g, e];
    }
    groupIndexOf(i) { for (let k = i; k >= 0; k--) if (this.items[k].t === 'group') return k; return -1; }
    /* Every group whose block holds item i (innermost first). */
    groupsAround(i) {
      const out = [];
      let lvl = this.items[i] && this.items[i].t === 'group' ? levelOf(this.items[i]) : 7;
      for (let k = i - 1; k >= 0; k--) {
        const it = this.items[k];
        if (it.t === 'group' && levelOf(it) < lvl) { out.push(k); lvl = levelOf(it); }
      }
      return out;
    }
    /* Open every group that hides item i. */
    openAround(i) { let any = false; for (const g of this.groupsAround(i)) if (this.items[g].collapsed) { this.items[g].collapsed = false; any = true; } return any; }
    setLevel(g, d) {
      const it = this.items[g];
      const lv = Math.max(1, Math.min(6, levelOf(it) + d));
      if (lv === levelOf(it)) return;
      it.level = lv;
      this.changed(); this.render();
    }
    moveRange(from, len, to) {
      if (to >= from && to <= from + len) return false;          // into itself: nothing to do
      const block = this.items.splice(from, len);
      if (to > from) to -= len;
      this.items.splice(to, 0, ...block);
      this.undo = null;
      this.changed(); this.render();
      return true;
    }
    add(srcs, at) {
      const fresh = [];
      for (const s of [].concat(srcs)) {
        const src = cleanEmbed(s);
        const spec = src && R.parse(src);
        if (!spec) { FS.toast('Only rendered examples go into a collection, not links.', 'warn'); continue; }
        if (spec.kind !== 'text') { FS.toast('A collection holds interlinear examples only — that is a lexicon entry.', 'warn'); continue; }
        fresh.push({ t: 'ex', src, spec, note: '' });
      }
      if (!fresh.length) return 0;
      const i = at == null ? this.items.length : at;
      this.items.splice(i, 0, ...fresh);
      // an example added into a closed group opens it (and every group around it), so it is seen
      this.openAround(i);
      this.undo = null;
      this.changed(); this.render();
      const card = this.root.querySelector('.coll-item[data-i="' + i + '"]');
      if (card && card.scrollIntoView) card.scrollIntoView({ block: 'nearest' });
      return fresh.length;
    }
    remove(i) {
      const [item] = this.items.splice(i, 1);
      this.undo = { items: [item], at: i, what: item.t === 'group' ? 'Group removed (its examples stay).' : 'Example removed.' };
      this.changed(); this.render();
    }
    restore() {
      if (!this.undo) return;
      if (this.undo.snapshot) { this.items = this.undo.snapshot; this.undo = null; this.changed(); this.render(); return; }
      this.items.splice(Math.min(this.undo.at, this.items.length), 0, ...this.undo.items);
      this.undo = null;
      this.changed(); this.render();
    }
    addGroup(label, at) {
      label = (label || '').trim();
      if (!label) return;
      const i = at == null ? this.items.length : at;
      const prev = this.groupIndexOf(i - 1);
      this.items.splice(i, 0, { t: 'group', label, level: prev >= 0 ? levelOf(this.items[prev]) : 2, collapsed: false });
      this.undo = null;
      this.changed(); this.render();
    }
    askGroup(at) {
      const label = prompt('Label for the group (it organises the collection; it is not exported)', '');
      if (label != null) this.addGroup(label, at);
    }
    setCollapsed(g, on) { this.items[g].collapsed = on; this.changed(); this.render(); }
    setAllCollapsed(on) { for (const i of this.items) if (i.t === 'group') i.collapsed = on; this.changed(); this.render(); }
    /* every example to a chip, or every one open (the groups stay as they are) */
    setExamplesCollapsed(on) {
      for (const it of this.items) {
        if (it.t !== 'ex' || !it.spec) continue;
        it.spec.extra = it.spec.extra || {};
        if (on) it.spec.extra.collapsed = true; else delete it.spec.extra.collapsed;
        it.src = R.serialize(it.spec);
      }
      this.changed(); this.render();
    }
    /* ↑ / ↓ on an example swaps it with its neighbour (so it can cross into the next group);
     * on a group it moves the whole group past the neighbouring group. */
    step(i, d) {
      const it = this.items[i];
      if (it.t !== 'group') {
        const j = i + d;
        if (j < 0 || j >= this.items.length) return;
        this.items[i] = this.items[j]; this.items[j] = it;
        this.openAround(j);                                                       // never vanish into a closed group
        this.undo = null;
        this.changed(); this.render();
        return;
      }
      // a group moves whole (sub-groups too) past the neighbouring group of its level or above
      const [s, e] = this.blockOf(i);
      const lvl = levelOf(it);
      if (d < 0) {
        if (s === 0) return;
        let k = s - 1;
        while (k > 0 && !(this.items[k].t === 'group' && levelOf(this.items[k]) <= lvl)) k--;
        this.moveRange(s, e - s, k);
      } else {
        if (e >= this.items.length) return;
        const next = this.items[e];
        this.moveRange(s, e - s, levelOf(next) === lvl ? this.blockOf(e)[1] : e + 1);
      }
    }

    /* -- selecting several items (Seth, 2026-10-16) ----------------------------------
     * A checkbox on every card and group (Shift: a range, Ctrl+A: everything) selects; the bar
     * that appears, Alt+Shift+↑/↓, Ctrl+C / X / V, Delete and dragging any selected card act on
     * all of them. A selected GROUP stands for its whole block (its sub-groups and examples). */
    toggleSel(item, range) {
      const i = this.items.indexOf(item);
      if (range && this.lastSel && this.items.includes(this.lastSel)) {
        const j = this.items.indexOf(this.lastSel);
        const on = !this.sel.has(item) || this.sel.has(this.lastSel);
        for (let k = Math.min(i, j); k <= Math.max(i, j); k++) on ? this.sel.add(this.items[k]) : this.sel.delete(this.items[k]);
      } else if (this.sel.has(item)) this.sel.delete(item);
      else this.sel.add(item);
      this.lastSel = item;
      this.render();
      if (this.root.focus) this.root.focus({ preventScroll: true });
    }
    selectAll() { this.items.forEach((x) => this.sel.add(x)); this.render(); }
    clearSel() { if (!this.sel.size) return; this.sel.clear(); this.render(); }
    /* The selected items' indices in order, a group's block included. */
    selectedIdx() {
      const out = new Set();
      this.items.forEach((it, i) => {
        if (!this.sel.has(it)) return;
        if (it.t === 'group') { const [s0, e] = this.blockOf(i); for (let k = s0; k < e; k++) out.add(k); } else out.add(i);
      });
      return [...out].sort((a, b) => a - b);
    }
    selectedItems() { return this.selectedIdx().map((i) => this.items[i]); }
    /* Put `moving` (items of this collection) before `anchor` (or at the end), keeping order. */
    placeItems(moving, before) {
      const rest = this.items.filter((x) => !moving.includes(x));
      let at = before ? rest.indexOf(before) : rest.length;
      if (at < 0) at = rest.length;
      rest.splice(at, 0, ...moving);
      this.items = rest;
      for (const m of moving) this.openAround(this.items.indexOf(m));
      this.undo = null;
      this.changed(); this.render();
    }
    moveSel(dir) {
      const idx = this.selectedIdx();
      if (!idx.length) return;
      const first = idx[0], last = idx[idx.length - 1];
      if (dir < 0 && first === 0) return;
      if (dir > 0 && last >= this.items.length - 1) return;
      const moving = idx.map((i) => this.items[i]);
      if (dir < 0) this.placeItems(moving, this.items[first - 1]);
      else this.placeItems(moving, this.items[last + 2] || null);
    }
    intoGroup(g) {
      const moving = this.selectedItems().filter((x) => x !== this.items[g]);
      if (!moving.length) return;
      const grp = this.items[g];
      const rest = this.items.filter((x) => !moving.includes(x));
      const gi = rest.indexOf(grp);
      const lvl = levelOf(grp);
      let e = gi + 1;
      while (e < rest.length && !(rest[e].t === 'group' && levelOf(rest[e]) <= lvl)) e++;
      this.placeItems(moving, rest[e] || null);
      FS.toast(moving.length + (moving.length === 1 ? ' item' : ' items') + ' moved into \u201c' + grp.label + '\u201d', 'ok');
    }
    selMarkdown() { return serialize(this.selectedItems()); }
    copySel() {
      const md = this.selMarkdown();
      if (!md) return;
      FS.collClip = md;
      if (FS.copyText) FS.copyText(md);
      const n = this.selectedIdx().length;
      FS.toast(n + (n === 1 ? ' item' : ' items') + ' copied', 'ok');
      this.render();                                   // the bar now offers Paste
      if (this.root.focus) this.root.focus({ preventScroll: true });
    }
    deleteSel(what) {
      const idx = this.selectedIdx();
      if (!idx.length) return;
      const snapshot = this.items.slice();
      const gone = new Set(idx.map((i) => this.items[i]));
      this.items = this.items.filter((x) => !gone.has(x));
      this.undo = { snapshot, at: Math.min(idx[0], this.items.length), what: what || (idx.length + (idx.length === 1 ? ' item removed.' : ' items removed.')) };
      this.sel.clear();
      this.changed(); this.render();
    }
    cutSel() { this.copySel(); this.deleteSel(); }
    duplicateSel() {
      const items = this.selectedItems();
      if (!items.length) return;
      const copies = parse(serialize(items));
      const last = this.items.indexOf(items[items.length - 1]);
      this.items.splice(last + 1, 0, ...copies);
      this.sel = new Set(copies);
      this.undo = null;
      this.changed(); this.render();
    }
    /* Text pasted into the collection (its own copied items, examples from a note, a group): the
     * examples and groups in it go after the selection, or at the end. */
    pasteText(text) {
      const got = parse(String(text || '')).filter((x) => x.t !== 'other' || /\{\{flex:/.test(x.src))
        .map((x) => x.t === 'ex' ? Object.assign(x, { src: cleanEmbed(x.src, true) || x.src }) : x)
        .filter((x) => x.t !== 'ex' || (x.spec && x.spec.kind === 'text'));
      if (!got.length) return 0;
      const idx = this.selectedIdx();
      const at = idx.length ? idx[idx.length - 1] + 1 : this.items.length;
      this.items.splice(at, 0, ...got);
      this.openAround(at);
      this.sel = new Set(got);
      this.undo = null;
      this.changed(); this.render();
      FS.toast(got.length + (got.length === 1 ? ' item' : ' items') + ' pasted', 'ok');
      return got.length;
    }
    typing(e) { const t = e.target; return !!(t && t.closest && t.closest('textarea, input:not([type=checkbox]), select, [contenteditable="true"], .popover, .modal')); }
    onKey(e) {
      if (this.typing(e)) return;
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === 'a') { e.preventDefault(); this.selectAll(); return; }
      if (!this.sel.size) return;
      if (e.key === 'Escape') { e.preventDefault(); this.clearSel(); }
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.deleteSel(); }
      else if (mod && k === 'c') { e.preventDefault(); this.copySel(); }
      else if (mod && k === 'x') { e.preventDefault(); this.cutSel(); }
      else if (mod && k === 'd') { e.preventDefault(); this.duplicateSel(); }
      else if (e.altKey && e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); this.moveSel(e.key === 'ArrowUp' ? -1 : 1); }
    }
    onPaste(e) {
      if (this.typing(e) || (e.target && e.target.closest && e.target.closest('.coll-add'))) return;
      const text = (e.clipboardData && e.clipboardData.getData('text/plain')) || FS.collClip || '';
      if (this.pasteText(text)) e.preventDefault();
    }
    selBar() {
      const n = this.selectedIdx().length;
      const groups = this.items.map((x, i) => [x, i]).filter(([x]) => x.t === 'group' && !this.sel.has(x));
      const into = el('select', { class: 'coll-into', 'data-test': 'coll-into', title: 'Move the selected items to the end of a group' },
        el('option', { value: '' }, 'Move into group\u2026'), ...groups.map(([g, i]) => el('option', { value: String(i) }, '\u2003'.repeat(Math.max(0, levelOf(g) - 1)) + (g.label || 'Untitled group'))));
      into.addEventListener('change', () => { if (into.value !== '') this.intoGroup(+into.value); });
      return el('div', { class: 'coll-selbar', 'data-test': 'coll-selbar' },
        el('b', {}, n + (n === 1 ? ' item' : ' items') + ' selected'),
        el('button', { class: 'btn', title: 'Move up (Alt+Shift+\u2191)', onclick: () => this.moveSel(-1) }, '\u2191'),
        el('button', { class: 'btn', title: 'Move down (Alt+Shift+\u2193)', onclick: () => this.moveSel(1) }, '\u2193'),
        groups.length ? into : null,
        el('button', { class: 'btn', 'data-test': 'coll-sel-cut', title: 'Cut (Ctrl+X)', onclick: () => this.cutSel() }, 'Cut'),
        el('button', { class: 'btn', 'data-test': 'coll-sel-copy', title: 'Copy (Ctrl+C) \u2014 paste into a note or another collection', onclick: () => this.copySel() }, 'Copy'),
        FS.collClip ? el('button', { class: 'btn', 'data-test': 'coll-sel-paste', title: 'Paste after the selection (Ctrl+V)', onclick: () => this.pasteText(FS.collClip) }, 'Paste') : null,
        el('button', { class: 'btn', title: 'Duplicate (Ctrl+D)', onclick: () => this.duplicateSel() }, 'Duplicate'),
        this.opts.onTextsUsed ? el('button', { class: 'btn', 'data-test': 'coll-sel-texts', title: 'The FLEx texts the selected examples come from', onclick: () => this.opts.onTextsUsed(this.selMarkdown()) }, 'Texts used\u2026') : null,
        el('button', { class: 'btn danger', 'data-test': 'coll-sel-delete', title: 'Remove (Delete)', onclick: () => this.deleteSel() }, 'Remove'),
        el('span', { class: 'spacer' }),
        el('button', { class: 'icon-btn', title: 'Clear the selection (Esc)', onclick: () => this.clearSel() }, '\u2715'));
    }
    check(item) {
      const c = el('input', { type: 'checkbox', class: 'coll-check', 'data-test': 'coll-check', title: 'Select (Shift: a range, Ctrl+A: all)' });
      c.checked = this.sel.has(item);
      c.addEventListener('click', (e) => { e.preventDefault(); this.toggleSel(item, e.shiftKey); });
      return c;
    }

    /* -- drawing -------------------------------------------------------------------- */
    render() {
      const root = this.root;
      const scroll = root.scrollTop;
      const ae = document.activeElement;
      const hadFocus = !!(ae && (ae === root || root.contains(ae)));
      root.innerHTML = '';
      const n = this.examples().length, ng = this.groups().length;
      const head = el('div', { class: 'coll-head' },
        el('span', { class: 'coll-kind' }, 'Example collection'),
        el('span', { class: 'muted small', 'data-test': 'coll-count', title: 'Exported in this order: one paragraph per example, one FLEx line per segment' }, n + ' example' + (n === 1 ? '' : 's')),
        el('span', { class: 'spacer' }),
        ng ? (this.groups().some((g) => !g.collapsed)
          ? el('button', { class: 'btn', 'data-test': 'coll-all', title: 'Close every group', onclick: () => this.setAllCollapsed(true) }, '\u25b8 Collapse all')
          : el('button', { class: 'btn', 'data-test': 'coll-all', title: 'Open every group', onclick: () => this.setAllCollapsed(false) }, '\u25be Expand all')) : null,
        n ? (this.examples().some((x) => !(x.spec && x.spec.extra && x.spec.extra.collapsed))
          ? el('button', { class: 'btn', 'data-test': 'coll-ex-all', title: 'Show every example as a one-line chip (hover or click one to see it)', onclick: () => this.setExamplesCollapsed(true) }, '\u2921 Examples as chips')
          : el('button', { class: 'btn', 'data-test': 'coll-ex-all', title: 'Show every example in full', onclick: () => this.setExamplesCollapsed(false) }, '\u2922 Examples in full')) : null,
        el('button', { class: 'btn', 'data-test': 'coll-add-group', title: 'A labelled, collapsible block for sorting the examples (not exported)', onclick: () => this.askGroup() }, '➕ Group…'),
        el('button', { class: 'btn', 'data-test': 'coll-refresh', title: 'Take in what was changed in FieldWorks and reload every example', onclick: (e) => { e.currentTarget.disabled = true; this.opts.onRefreshAll && this.opts.onRefreshAll(); } }, '↻ Refresh all'),
        el('button', { class: 'btn', title: 'Find a text and its segments in the project', onclick: () => this.pick() }, '➕ Add from FLEx…'),
        el('button', { class: 'btn primary', 'data-test': 'coll-export', disabled: !n, title: n ? 'Export these examples as one FLEx text (.flextext)' : 'Add examples first', onclick: () => this.opts.onExport && this.opts.onExport() }, 'Export as FLEx text…'));
      root.appendChild(head);
      for (const x of [...this.sel]) if (!this.items.includes(x)) this.sel.delete(x);
      root.classList.toggle('has-sel', this.sel.size > 0);
      if (this.sel.size) head.appendChild(this.selBar());          // in the sticky header: always in reach

      const list = el('div', { class: 'coll-list' });
      this.list = list;
      let num = 0;
      const hidden = hiddenItems(this.items);
      const top = Math.min(7, ...this.groups().map(levelOf));        // the outermost level present
      let depth = 0;                                                  // nesting of the item being drawn
      this.items.forEach((item, i) => {
        if (this.undo && this.undo.at === i) list.appendChild(this.undoRow());
        if (item.t === 'group') {
          depth = levelOf(item) - top + 1;
          if (hidden[i]) return;
          const [s, e] = this.blockOf(i);
          const count = this.items.slice(s + 1, e).filter((x) => x.t === 'ex').length;
          const row = this.groupRow(item, i, count);
          if (this.sel.has(item)) row.classList.add('selected');
          row.style.setProperty('--depth', String(depth - 1));
          row.classList.add('lvl' + levelOf(item));
          list.appendChild(row);
          return;
        }
        if (item.t === 'ex') num++;
        if (hidden[i]) return;
        const card = item.t === 'ex' ? this.card(item, i, num) : this.otherCard(item, i);
        if (this.sel.has(item)) card.classList.add('selected');
        if (depth) { card.classList.add('in-group'); card.style.setProperty('--depth', String(depth)); }
        list.appendChild(card);
      });
      if (this.undo && this.undo.at >= this.items.length) list.appendChild(this.undoRow());
      if (!this.items.length && !this.undo) list.appendChild(el('div', { class: 'coll-empty muted' }, 'No examples yet. Paste lines copied from FLEx below, use “Add from FLEx…”, or choose “Add to an example collection…” on an example in any note.'));
      root.appendChild(list);
      this.wireDrag(list);
      root.appendChild(this.addBox());
      root.scrollTop = scroll;
      // a redraw removes the focused button or checkbox: keep the keys in the collection
      if (hadFocus && (!document.activeElement || document.activeElement === document.body) && root.focus) root.focus({ preventScroll: true });
    }
    undoRow() {
      return el('div', { class: 'coll-undo' }, this.undo.what + ' ', el('button', { class: 'lnk', onclick: () => this.restore() }, 'Undo'));
    }
    groupRow(item, i, count) {
      const label = el('span', { class: 'coll-group-label', title: 'Double-click to rename' }, item.label || 'Untitled group');
      const rename = () => {
        const input = el('input', { type: 'text', value: item.label, class: 'coll-group-input' });
        const done = (keep) => { if (keep) { const v = input.value.trim(); if (v && v !== item.label) { item.label = v; this.changed(); } } this.render(); };
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); done(true); } else if (e.key === 'Escape') { e.preventDefault(); done(false); } });
        input.addEventListener('blur', () => done(true));
        label.replaceWith(input); input.focus(); input.select();
      };
      label.addEventListener('dblclick', rename);
      const [, e] = this.blockOf(i);
      return el('div', { class: 'coll-group' + (item.collapsed ? ' collapsed' : ''), dataset: { i: String(i) } },
        this.check(item),
        el('button', { class: 'coll-toggle', 'data-test': 'coll-toggle', title: item.collapsed ? 'Expand' : 'Collapse', 'aria-expanded': String(!item.collapsed), onclick: () => this.setCollapsed(i, !item.collapsed) }, item.collapsed ? '▸' : '▾'),
        el('span', { class: 'coll-grip', title: 'Drag to move the whole group', draggable: 'true' }, '⠿'),
        label,
        el('span', { class: 'muted small' }, count + ' example' + (count === 1 ? '' : 's')),
        el('span', { class: 'spacer' }),
        el('div', { class: 'coll-tools row' },
          el('button', { class: 'icon-btn', title: 'Add an example from FLEx at the end of this group', onclick: () => this.pick(e) }, '➕'),
          el('button', { class: 'icon-btn', title: 'Rename', onclick: rename }, '✎'),
          el('button', { class: 'icon-btn', 'data-test': 'coll-outdent', title: 'One level up (heading ' + Math.max(1, levelOf(item) - 1) + ')', disabled: levelOf(item) <= 1, onclick: () => this.setLevel(i, -1) }, '⇤'),
          el('button', { class: 'icon-btn', 'data-test': 'coll-indent', title: 'One level down: a sub-group (heading ' + Math.min(6, levelOf(item) + 1) + ')', disabled: levelOf(item) >= 6, onclick: () => this.setLevel(i, 1) }, '⇥'),
          el('button', { class: 'icon-btn', title: 'Move the group up', disabled: i === 0, onclick: () => this.step(i, -1) }, '↑'),
          el('button', { class: 'icon-btn', title: 'Move the group down', disabled: e >= this.items.length, onclick: () => this.step(i, 1) }, '↓'),
          el('button', { class: 'icon-btn danger', title: 'Remove the group (its examples stay)', 'data-test': 'coll-ungroup', onclick: () => this.remove(i) }, '✕')));
    }
    card(item, i, num) {
      const host = el('div', { class: 'coll-ex' });
      const note = el('textarea', { class: 'coll-note', rows: 1, placeholder: 'Note on this example — exported to FLEx as a note on its first line', 'data-test': 'coll-note' });
      note.value = item.note || '';
      const grow = () => { note.style.height = 'auto'; note.style.height = (note.scrollHeight + 2) + 'px'; };
      note.addEventListener('input', () => { item.note = note.value; this.changed(); grow(); });
      note.addEventListener('blur', () => { if (!note.value.trim()) note.hidden = true; });
      note.hidden = !(item.note || '').trim();
      if (!note.hidden) requestAnimationFrame(grow);
      const body = el('div', { class: 'coll-body' }, host, note);
      const card = el('div', { class: 'coll-item', dataset: { i: String(i) } },
        el('div', { class: 'coll-gutter' },
          this.check(item),
          el('span', { class: 'coll-num' }, '(' + num + ')'),
          el('span', { class: 'coll-grip', title: 'Drag to reorder (onto a group’s heading: into that group)', draggable: 'true' }, '⠿')),
        body,
        el('div', { class: 'coll-tools' },
          el('button', { class: 'icon-btn', title: 'Move up', disabled: i === 0, onclick: () => this.step(i, -1) }, '↑'),
          el('button', { class: 'icon-btn', title: 'Move down', disabled: i === this.items.length - 1, onclick: () => this.step(i, 1) }, '↓'),
          el('button', { class: 'icon-btn', title: 'Note on this example (exported to FLEx)', 'data-test': 'coll-note-btn', onclick: () => { note.hidden = false; grow(); note.focus(); } }, '✎'),
          el('button', { class: 'icon-btn danger', title: 'Remove from the collection', 'data-test': 'coll-remove', onclick: () => this.remove(i) }, '✕')));
      const opts = () => ({
        editable: true, collection: true, keepView: true,
        onSpecChange: (s) => { const src = cleanEmbed(R.serialize(s), true); if (!src) return; item.src = src; item.spec = R.parse(src); this.changed(); FS.interlinear.render(host, item.spec, opts()); },
        duplicate: () => { this.items.splice(i + 1, 0, { t: 'ex', src: item.src, spec: R.parse(item.src), note: item.note }); this.undo = null; this.changed(); this.render(); },
      });                                                 // removing is the ✕ beside the card
      FS.interlinear.render(host, item.spec, opts());
      return card;
    }
    otherCard(item, i) {
      return el('div', { class: 'coll-item other', dataset: { i: String(i) } },
        el('div', { class: 'coll-gutter' }, this.check(item)),
        el('div', { class: 'coll-body' }, el('div', { class: 'muted small' }, 'Not an interlinear example — kept in the file, left out of the export:'), el('pre', { class: 'coll-other' }, item.src)),
        el('div', { class: 'coll-tools' }, el('button', { class: 'icon-btn danger', title: 'Remove', onclick: () => this.remove(i) }, '✕')));
    }

    /* Moving by the ⠿ grips. An example dropped on a card's top / bottom half goes before /
     * after it; dropped on a group's heading it goes to the end of that group (the start, on
     * the bottom half of an open one). A group moves whole: before the group it is dropped on
     * (top half of its heading), else after that group's last example. */
    wireDrag(list) {
      let from = null;
      const rows = '.coll-item, .coll-group';
      const mark = (row, after) => { list.querySelectorAll('.drop-before, .drop-after, .drop-into').forEach((x) => x.classList.remove('drop-before', 'drop-after', 'drop-into')); if (row) row.classList.add(after === 'into' ? 'drop-into' : after ? 'drop-after' : 'drop-before'); };
      const target = (e) => {
        const row = e.target.closest && e.target.closest(rows);
        if (!row || !list.contains(row)) return null;
        const r = row.getBoundingClientRect();
        return { row, i: +row.dataset.i, after: e.clientY > r.top + r.height / 2 };
      };
      const plan = (t) => {                     // → [insert index, mark kind]
        const src = this.items[from];
        const ti = this.items[t.i];
        if (src.t !== 'group') {
          if (ti.t === 'group') {
            if (ti.collapsed || !t.after) return ti.collapsed ? [this.blockOf(t.i)[1], 'into'] : [t.i, false];
            return [t.i + 1, true];
          }
          return [t.i + (t.after ? 1 : 0), t.after];
        }
        const g = this.groupIndexOf(t.i);
        if (g < 0) return [t.after ? t.i + 1 : t.i, t.after];               // among the ungrouped examples at the top
        if (ti.t === 'group' && !t.after) return [g, false];
        return [this.blockOf(g)[1], true];
      };
      list.addEventListener('dragstart', (e) => {
        const grip = e.target.closest && e.target.closest('.coll-grip');
        if (!grip) return;
        const row = grip.closest(rows);
        from = +row.dataset.i;
        // dragging a selected item moves every selected one
        this.dragSet = this.sel.has(this.items[from]) && this.selectedIdx().length > 1 ? this.selectedItems() : null;
        if (this.dragSet) list.querySelectorAll('.coll-item.selected, .coll-group.selected').forEach((x) => x.classList.add('dragging'));
        row.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('application/x-fs-collection', String(from));
        try { e.dataTransfer.setDragImage(row, 20, 20); } catch (err) { /* not everywhere */ }
      });
      list.addEventListener('dragover', (e) => { if (from == null) return; const t = target(e); if (!t) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; mark(t.row, plan(t)[1]); });
      list.addEventListener('drop', (e) => {
        if (from == null) return;
        const t = target(e);
        e.preventDefault();
        mark(null);
        const f = from;
        const p = t ? plan(t) : null;
        from = null;
        if (!p) return;
        const moved = this.items[f];
        if (this.dragSet) {
          const set = this.dragSet;
          this.dragSet = null;
          // before the first unselected item at the drop point (dropped inside the set: no move)
          this.placeItems(set, this.items.slice(p[0]).find((x) => !set.includes(x)) || null);
          return;
        }
        if (moved.t === 'group') { const [s, e2] = this.blockOf(f); this.moveRange(s, e2 - s, p[0]); return; }
        if (!this.moveRange(f, 1, p[0])) return;
        const g = this.groupIndexOf(this.items.indexOf(moved));
        if (g >= 0 && hiddenItems(this.items)[this.items.indexOf(moved)]) FS.toast('Moved into \u201c' + this.items[g].label + '\u201d', 'ok');
      });
      list.addEventListener('dragend', () => { from = null; this.dragSet = null; mark(null); list.querySelectorAll('.dragging').forEach((x) => x.classList.remove('dragging')); });
    }

    /* The paste box: FLEx interlinear rows or a FLEx link become an example at the end. */
    addBox() {
      const box = el('div', { class: 'coll-add', contenteditable: 'true', spellcheck: 'false', 'data-placeholder': 'Paste lines copied from FLEx (or a FLEx link) here to add an example at the end' });
      const insert = (md) => { if (!this.add(md)) return; FS.toast('Example added', 'ok'); };
      const take = (text) => {
        text = String(text || '').replace(/\r\n?/g, '\n');
        const t = text.trim();
        box.textContent = '';
        if (!t) return;
        if (R.parse(t)) { insert(t); return; }                                     // an embed line
        if (/^silfw:\/\//i.test(t) || R.GUID.test(t)) { FS.picker.pasteChooser(t, (md) => insert(md)); return; }
        if (looksLikeFlexRows(text) && FS.picker && this.opts.canLocate && this.opts.canLocate()) {
          FS.picker.locateChooser(text, (md) => insert(md), () => {});         // it says when nothing matched
          return;
        }
        FS.toast('Paste interlinear lines copied from FLEx (with the Word line showing), or a FLEx link.', 'warn');
      };
      box.addEventListener('paste', (e) => { e.preventDefault(); take(e.clipboardData && e.clipboardData.getData('text/plain')); });
      box.addEventListener('beforeinput', (e) => {
        e.preventDefault();                                                       // nothing is typed here
        if (e.inputType === 'insertFromPaste' || e.inputType === 'insertFromDrop') take(e.dataTransfer && e.dataTransfer.getData('text/plain'));
      });
      box.addEventListener('drop', (e) => { const t = e.dataTransfer && e.dataTransfer.getData('text/plain'); if (t) { e.preventDefault(); take(t); } });
      return box;
    }
    pick(at) {
      FS.picker.open((md) => { const n = this.add(md, at); if (n) FS.toast('Example added', 'ok'); }, { mode: 'texts' });
    }
  }

  FS.Collection = Collection;
  FS.collection = { cleanEmbed, parse, serialize, hiddenItems };
})();
