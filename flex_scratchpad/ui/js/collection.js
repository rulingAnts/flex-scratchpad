/* An EXAMPLE COLLECTION (Seth, 2026-10-16): a note that is JUST interlinear examples, expanded
 * and numbered in order, and the one kind of note that exports as a FLEx text — "to collect
 * and concentrate certain grammatical constructions … and then have one flex text where I can
 * analyze those in text chart".
 *
 * On disk it is an ordinary note file with `kind: examples` in its header and a body of embeds,
 * one `{{flex:text …}}` per paragraph, so it stays readable without the app. Here it is a list
 * of cards: the number, a drag handle, ↑ ↓ ✕, and the example rendered with the usual styling
 * tools. Examples come in through the paste box (FLEx rows or a FLEx link), the FLEx picker,
 * or "Add to an example collection…" on any example in any note. Anything else found in the
 * body (a hand-edited file) is kept, shown muted, and left out of the numbering and export. */
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

  class Collection {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts || {};
      this.items = [];                // [{src, spec}] in order; spec null = not an example
      this.undo = null;               // {item, at} after a removal
    }
    load(body) {
      this.items = FS.markdown.splitBlocks(String(body || '').replace(/\r\n?/g, '\n'))
        .map((b) => b.src.trim()).filter(Boolean)
        .map((src) => { const spec = R.parse(src); return { src, spec: spec && spec.kind === 'text' ? spec : null }; });
      this.undo = null;
      this.render();
      return this;
    }
    markdown() { return this.items.length ? this.items.map((i) => i.src).join('\n\n') + '\n' : ''; }
    examples() { return this.items.filter((i) => i.spec); }
    changed() { if (this.opts.onChange) this.opts.onChange(this.markdown()); }
    /* What the other exports read: blocks as the editor would hold them, examples numbered. */
    asEditor() {
      return { blocks: this.items.map((i) => {
        if (!i.spec) return FS.markdown.splitBlocks(i.src)[0] || { type: 'p', src: i.src };
        const s = R.parse(i.src); s.extra = Object.assign({}, s.extra, { ex: '1' });
        return { type: 'flex', src: R.serialize(s) };
      }) };
    }

    add(srcs, at) {
      const fresh = [];
      for (const s of [].concat(srcs)) {
        const src = cleanEmbed(s);
        const spec = src && R.parse(src);
        if (!spec) { FS.toast('Only rendered examples go into a collection, not links.', 'warn'); continue; }
        if (spec.kind !== 'text') { FS.toast('A collection holds interlinear examples only — that is a lexicon entry.', 'warn'); continue; }
        fresh.push({ src, spec });
      }
      if (!fresh.length) return 0;
      const i = at == null ? this.items.length : at;
      this.items.splice(i, 0, ...fresh);
      this.undo = null;
      this.changed(); this.render();
      const card = this.list && this.list.children[this.cardIndex(i)];
      if (card && card.scrollIntoView) card.scrollIntoView({ block: 'nearest' });
      return fresh.length;
    }
    remove(i) {
      const [item] = this.items.splice(i, 1);
      this.undo = { item, at: i };
      this.changed(); this.render();
    }
    restore() {
      if (!this.undo) return;
      this.items.splice(Math.min(this.undo.at, this.items.length), 0, this.undo.item);
      this.undo = null;
      this.changed(); this.render();
    }
    move(from, to) {
      if (to < 0 || to >= this.items.length || from === to) return;
      const [item] = this.items.splice(from, 1);
      this.items.splice(to, 0, item);
      this.undo = null;
      this.changed(); this.render();
    }
    cardIndex(i) { return i + (this.undo && this.undo.at <= i ? 1 : 0); }

    render() {
      const root = this.root;
      root.innerHTML = '';
      const n = this.examples().length;
      // the head: what this is, how many, and the export
      const head = el('div', { class: 'coll-head' },
        el('span', { class: 'coll-kind' }, 'Example collection'),
        el('span', { class: 'muted small', 'data-test': 'coll-count', title: 'Exported in this order: one paragraph per example, one FLEx line per segment' }, n + ' example' + (n === 1 ? '' : 's')),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn', title: 'Find a text and its segments in the project', onclick: () => this.pick() }, '➕ Add from FLEx…'),
        el('button', { class: 'btn primary', 'data-test': 'coll-export', disabled: !n, title: n ? 'Export these examples as one FLEx text (.flextext)' : 'Add examples first', onclick: () => this.opts.onExport && this.opts.onExport() }, 'Export as FLEx text…'));
      root.appendChild(head);

      const list = el('div', { class: 'coll-list' });
      this.list = list;
      let num = 0;
      this.items.forEach((item, i) => {
        if (this.undo && this.undo.at === i) list.appendChild(this.undoRow());
        list.appendChild(item.spec ? this.card(item, i, ++num) : this.otherCard(item, i));
      });
      if (this.undo && this.undo.at >= this.items.length) list.appendChild(this.undoRow());
      if (!this.items.length && !this.undo) list.appendChild(el('div', { class: 'coll-empty muted' }, 'No examples yet. Paste lines copied from FLEx below, use “Add from FLEx…”, or choose “Add to an example collection…” on an example in any note.'));
      root.appendChild(list);
      this.wireDrag(list);
      root.appendChild(this.addBox());
    }
    undoRow() {
      return el('div', { class: 'coll-undo' }, 'Example removed. ',
        el('button', { class: 'lnk', onclick: () => this.restore() }, 'Undo'));
    }
    card(item, i, num) {
      const host = el('div', { class: 'coll-body' });
      const card = el('div', { class: 'coll-item', dataset: { i: String(i) } },
        el('div', { class: 'coll-gutter' },
          el('span', { class: 'coll-num' }, '(' + num + ')'),
          el('span', { class: 'coll-grip', title: 'Drag to reorder', draggable: 'true' }, '⠿')),
        host,
        el('div', { class: 'coll-tools' },
          el('button', { class: 'icon-btn', title: 'Move up', disabled: i === 0, onclick: () => this.move(i, i - 1) }, '↑'),
          el('button', { class: 'icon-btn', title: 'Move down', disabled: i === this.items.length - 1, onclick: () => this.move(i, i + 1) }, '↓'),
          el('button', { class: 'icon-btn danger', title: 'Remove from the collection', 'data-test': 'coll-remove', onclick: () => this.remove(i) }, '✕')));
      const opts = () => ({
        editable: true, force: true, collection: true,
        onSpecChange: (s) => { const src = cleanEmbed(R.serialize(s)); if (!src) return; item.src = src; item.spec = R.parse(src); this.changed(); FS.interlinear.render(host, item.spec, opts()); },
        duplicate: () => { this.items.splice(i + 1, 0, { src: item.src, spec: R.parse(item.src) }); this.undo = null; this.changed(); this.render(); },
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

    /* Re-ordering by the ⠿ grip: drop on a card's top half = before it, bottom half = after. */
    wireDrag(list) {
      let from = null;
      const mark = (card, after) => { list.querySelectorAll('.drop-before, .drop-after').forEach((x) => x.classList.remove('drop-before', 'drop-after')); if (card) card.classList.add(after ? 'drop-after' : 'drop-before'); };
      const target = (e) => {
        const card = e.target.closest && e.target.closest('.coll-item');
        if (!card || !list.contains(card)) return null;
        const r = card.getBoundingClientRect();
        return { card, i: +card.dataset.i, after: e.clientY > r.top + r.height / 2 };
      };
      list.addEventListener('dragstart', (e) => {
        const grip = e.target.closest && e.target.closest('.coll-grip');
        if (!grip) return;
        const card = grip.closest('.coll-item');
        from = +card.dataset.i;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('application/x-fs-collection', String(from));
        try { e.dataTransfer.setDragImage(card, 20, 20); } catch (err) { /* not everywhere */ }
      });
      list.addEventListener('dragover', (e) => { if (from == null) return; const t = target(e); if (!t) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; mark(t.card, t.after); });
      list.addEventListener('drop', (e) => {
        if (from == null) return;
        const t = target(e);
        e.preventDefault();
        mark(null);
        const f = from; from = null;
        if (!t) return;
        let to = t.i + (t.after ? 1 : 0);
        if (to > f) to -= 1;
        this.move(f, to);
      });
      list.addEventListener('dragend', () => { from = null; mark(null); list.querySelectorAll('.dragging').forEach((x) => x.classList.remove('dragging')); });
    }

    /* The paste box: FLEx interlinear rows or a FLEx link become an example at the end. */
    addBox() {
      const box = el('div', { class: 'coll-add', contenteditable: 'true', spellcheck: 'false', 'data-placeholder': 'Paste lines copied from FLEx (or a FLEx link) here to add an example' });
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
    pick() {
      FS.picker.open((md) => { const n = this.add(md); if (n) FS.toast('Example added', 'ok'); }, { mode: 'texts' });
    }
  }

  FS.Collection = Collection;
  FS.collection = { cleanEmbed };
})();
