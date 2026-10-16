/* An EXAMPLE COLLECTION (Seth, 2026-10-16): a note that is JUST interlinear examples, expanded
 * and numbered in order, and the one kind of note that exports as a FLEx text — "to collect
 * and concentrate certain grammatical constructions … and then have one flex text where I can
 * analyze those in text chart".
 *
 * On disk it is an ordinary note file with `kind: examples` in its header, readable without
 * the app:
 *
 *     ## Shared subject                     a GROUP: a labelled, collapsible block of examples
 *                                           (` {collapsed}` at the end when it is closed);
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
   * collection decides for itself (numbering, indent, collapsed / expanded). */
  function cleanEmbed(src) {
    const spec = R.parse(String(src || '').trim());
    if (!spec) return null;
    const x = spec.extra || {};
    for (const k of ['ex', 'indent', 'collapsed', 'expanded']) delete x[k];
    spec.extra = x;
    return R.serialize(spec);
  }
  const looksLikeFlexRows = (t) => /\t/.test(t) || /^(\d+(\.\d+)?\t)?\s*(Word|Morphemes|Lex\.|Free|Literal|Note)\b/im.test(t);
  const HEADING = /^#{1,6}\s+(.*?)\s*$/;
  const COLLAPSED = /\s*\{collapsed\}$/;

  /* body → [{t:'group', label, collapsed} | {t:'ex', src, spec, note} | {t:'other', src}] */
  function parse(body) {
    const items = [];
    let cur = null, other = null;
    for (const raw of String(body || '').replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.replace(/\s+$/, '');
      if (!line.trim()) { cur = null; other = null; continue; }
      const h = HEADING.exec(line);
      if (h) {
        items.push({ t: 'group', label: h[1].replace(COLLAPSED, '').trim(), collapsed: COLLAPSED.test(h[1]) });
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
      if (i.t === 'group') return '## ' + (i.label || 'Untitled group') + (i.collapsed ? ' {collapsed}' : '');
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
      this.undo = null;               // {items, at, what} after a removal
    }
    load(body) {
      this.items = parse(body);
      this.undo = null;
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
        if (i.t === 'group') blocks.push({ type: 'h', level: 2, src: '## ' + i.label });
        else if (i.t === 'ex') {
          const s = R.parse(i.src); s.extra = Object.assign({}, s.extra, { ex: '1' });
          blocks.push({ type: 'flex', src: R.serialize(s) });
          if ((i.note || '').trim()) blocks.push({ type: 'p', src: i.note.trim() });
        } else blocks.push(...FS.markdown.splitBlocks(i.src));
      }
      return { blocks, flextextItems: () => this.flextextItems() };
    }

    /* -- structure ------------------------------------------------------------------ */
    /* The block a group heads: [start, end) — the heading and its examples up to the next group. */
    blockOf(g) {
      let e = g + 1;
      while (e < this.items.length && this.items[e].t !== 'group') e++;
      return [g, e];
    }
    groupIndexOf(i) { for (let k = i; k >= 0; k--) if (this.items[k].t === 'group') return k; return -1; }
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
      // an example added into a closed group opens it, so it can be seen
      const g = this.groupIndexOf(i);
      if (g >= 0) this.items[g].collapsed = false;
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
      this.items.splice(Math.min(this.undo.at, this.items.length), 0, ...this.undo.items);
      this.undo = null;
      this.changed(); this.render();
    }
    addGroup(label, at) {
      label = (label || '').trim();
      if (!label) return;
      const i = at == null ? this.items.length : at;
      this.items.splice(i, 0, { t: 'group', label, collapsed: false });
      this.undo = null;
      this.changed(); this.render();
    }
    askGroup(at) {
      const label = prompt('Label for the group (it organises the collection; it is not exported)', '');
      if (label != null) this.addGroup(label, at);
    }
    setCollapsed(g, on) { this.items[g].collapsed = on; this.changed(); this.render(); }
    setAllCollapsed(on) { for (const i of this.items) if (i.t === 'group') i.collapsed = on; this.changed(); this.render(); }
    /* ↑ / ↓ on an example swaps it with its neighbour (so it can cross into the next group);
     * on a group it moves the whole group past the neighbouring group. */
    step(i, d) {
      const it = this.items[i];
      if (it.t !== 'group') {
        const j = i + d;
        if (j < 0 || j >= this.items.length) return;
        this.items[i] = this.items[j]; this.items[j] = it;
        const g = this.groupIndexOf(j);
        if (g >= 0 && this.items[g].collapsed) this.items[g].collapsed = false;     // never vanish into a closed group
        this.undo = null;
        this.changed(); this.render();
        return;
      }
      const [s, e] = this.blockOf(i);
      if (d < 0) {
        if (s === 0) return;
        const pg = this.groupIndexOf(s - 1);
        this.moveRange(s, e - s, pg < 0 ? 0 : pg);
      } else {
        if (e >= this.items.length) return;
        const [, ne] = this.blockOf(e);
        this.moveRange(s, e - s, ne);
      }
    }

    /* -- drawing -------------------------------------------------------------------- */
    render() {
      const root = this.root;
      const scroll = root.scrollTop;
      root.innerHTML = '';
      const n = this.examples().length, ng = this.groups().length;
      const head = el('div', { class: 'coll-head' },
        el('span', { class: 'coll-kind' }, 'Example collection'),
        el('span', { class: 'muted small', 'data-test': 'coll-count', title: 'Exported in this order: one paragraph per example, one FLEx line per segment' }, n + ' example' + (n === 1 ? '' : 's')),
        el('span', { class: 'spacer' }),
        ng ? (this.groups().some((g) => !g.collapsed)
          ? el('button', { class: 'btn', 'data-test': 'coll-all', title: 'Close every group', onclick: () => this.setAllCollapsed(true) }, '\u25b8 Collapse all')
          : el('button', { class: 'btn', 'data-test': 'coll-all', title: 'Open every group', onclick: () => this.setAllCollapsed(false) }, '\u25be Expand all')) : null,
        el('button', { class: 'btn', 'data-test': 'coll-add-group', title: 'A labelled, collapsible block for sorting the examples (not exported)', onclick: () => this.askGroup() }, '➕ Group…'),
        el('button', { class: 'btn', title: 'Find a text and its segments in the project', onclick: () => this.pick() }, '➕ Add from FLEx…'),
        el('button', { class: 'btn primary', 'data-test': 'coll-export', disabled: !n, title: n ? 'Export these examples as one FLEx text (.flextext)' : 'Add examples first', onclick: () => this.opts.onExport && this.opts.onExport() }, 'Export as FLEx text…'));
      root.appendChild(head);

      const list = el('div', { class: 'coll-list' });
      this.list = list;
      let num = 0, hidden = false, inGroup = false;
      this.items.forEach((item, i) => {
        if (this.undo && this.undo.at === i) list.appendChild(this.undoRow());
        if (item.t === 'group') {
          hidden = item.collapsed; inGroup = true;
          const [s, e] = this.blockOf(i);
          const count = this.items.slice(s + 1, e).filter((x) => x.t === 'ex').length;
          list.appendChild(this.groupRow(item, i, count));
          return;
        }
        if (item.t === 'ex') num++;
        if (hidden) return;
        const card = item.t === 'ex' ? this.card(item, i, num) : this.otherCard(item, i);
        if (inGroup) card.classList.add('in-group');
        list.appendChild(card);
      });
      if (this.undo && this.undo.at >= this.items.length) list.appendChild(this.undoRow());
      if (!this.items.length && !this.undo) list.appendChild(el('div', { class: 'coll-empty muted' }, 'No examples yet. Paste lines copied from FLEx below, use “Add from FLEx…”, or choose “Add to an example collection…” on an example in any note.'));
      root.appendChild(list);
      this.wireDrag(list);
      root.appendChild(this.addBox());
      root.scrollTop = scroll;
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
        el('button', { class: 'coll-toggle', 'data-test': 'coll-toggle', title: item.collapsed ? 'Expand' : 'Collapse', 'aria-expanded': String(!item.collapsed), onclick: () => this.setCollapsed(i, !item.collapsed) }, item.collapsed ? '▸' : '▾'),
        el('span', { class: 'coll-grip', title: 'Drag to move the whole group', draggable: 'true' }, '⠿'),
        label,
        el('span', { class: 'muted small' }, count + ' example' + (count === 1 ? '' : 's')),
        el('span', { class: 'spacer' }),
        el('div', { class: 'coll-tools row' },
          el('button', { class: 'icon-btn', title: 'Add an example from FLEx at the end of this group', onclick: () => this.pick(e) }, '➕'),
          el('button', { class: 'icon-btn', title: 'Rename', onclick: rename }, '✎'),
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
          el('span', { class: 'coll-num' }, '(' + num + ')'),
          el('span', { class: 'coll-grip', title: 'Drag to reorder (onto a group’s heading: into that group)', draggable: 'true' }, '⠿')),
        body,
        el('div', { class: 'coll-tools' },
          el('button', { class: 'icon-btn', title: 'Move up', disabled: i === 0, onclick: () => this.step(i, -1) }, '↑'),
          el('button', { class: 'icon-btn', title: 'Move down', disabled: i === this.items.length - 1, onclick: () => this.step(i, 1) }, '↓'),
          el('button', { class: 'icon-btn', title: 'Note on this example (exported to FLEx)', 'data-test': 'coll-note-btn', onclick: () => { note.hidden = false; grow(); note.focus(); } }, '✎'),
          el('button', { class: 'icon-btn danger', title: 'Remove from the collection', 'data-test': 'coll-remove', onclick: () => this.remove(i) }, '✕')));
      const opts = () => ({
        editable: true, force: true, collection: true,
        onSpecChange: (s) => { const src = cleanEmbed(R.serialize(s)); if (!src) return; item.src = src; item.spec = R.parse(src); this.changed(); FS.interlinear.render(host, item.spec, opts()); },
        duplicate: () => { this.items.splice(i + 1, 0, { t: 'ex', src: item.src, spec: R.parse(item.src), note: item.note }); this.undo = null; this.changed(); this.render(); },
      });                                                 // removing is the ✕ beside the card
      FS.interlinear.render(host, item.spec, opts());
      return card;
    }
    otherCard(item, i) {
      return el('div', { class: 'coll-item other', dataset: { i: String(i) } },
        el('div', { class: 'coll-gutter' }),
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
        if (moved.t === 'group') { const [s, e2] = this.blockOf(f); this.moveRange(s, e2 - s, p[0]); return; }
        if (!this.moveRange(f, 1, p[0])) return;
        const g = this.groupIndexOf(this.items.indexOf(moved));
        if (g >= 0 && this.items[g].collapsed) FS.toast('Moved into \u201c' + this.items[g].label + '\u201d', 'ok');
      });
      list.addEventListener('dragend', () => { from = null; mark(null); list.querySelectorAll('.dragging').forEach((x) => x.classList.remove('dragging')); });
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
  FS.collection = { cleanEmbed, parse, serialize };
})();
