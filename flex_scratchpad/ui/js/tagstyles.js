/* tagstyles.js — FLEx TEXT MARKUP TAGS in examples: how each tag looks, and WHERE that is decided
 * (Seth, 2026-10-17: "project-scoped, folder-scoped, tab-scoped, and specific example-scoped …
 * style settings that are easy to see and adjust and remove (or disable), and the most specific
 * one takes precedent over the broadest one … kind of like highlighting filters in Logos").
 *
 * A RULE = {tag, enabled?, hide?, bg?, fg?, b?, i?, u?, label?, br?, hl?, tile?, box?, c?, bar?} for
 * one tag (by name, abbreviation or GUID; `group:<name>` = every tag of a FLEx group; `*` = every
 * tag). bg/fg colour the BAR under the words; the rest style the TEXT itself (Seth, 2026-10-18:
 * "the option to style the TEXT, not the tags … brackets around words (and their glosses, etc),
 * highlight/background/border/tile"): br = brackets around the span (BRACKETS), hl = a marker over
 * the word line, tile = a box behind the whole column of lines, box = a border round it, c = the
 * words' colour, b/i/u. The bar is `bar` (true/false), and by default shows only when no text
 * style is on — "those styles can overlap with tags optionally displayed underneath".
 * Rules live at these scopes, read most specific first:
 *   example  → the embed's own `tags=` (flexref.tagRules; several examples at once from a selection)
 *   note     → tagStyles.note["<note id>"]: the page's VIEW settings, above all which visual
 *              filters are on for it (Seth, 2026-10-18: "a view setting for the whole app or for
 *              notebook pages. You set them up and then turn them on and off")
 *   folder   → notebook.json tagStyles.folder["<tab>/<path>"] (the nearest folder first, then its parents)
 *   tab      → tagStyles.tab["<dir>"]
 *   text     → tagStyles.text["<text guid>"]: every example drawn from that FLEx text, wherever it
 *              appears (Seth, 2026-10-18: "specific texts anywhere they appear")
 *   filters  → tagStyles.filters: NAMED rule sets switched on and off as a whole, like Logos's
 *              visual filters (Seth, 2026-10-18); each enabled one in turn. A scope above can turn
 *              one on or off for itself with a rule on the pseudo-tag `filter:<id>` (hide = off).
 *   project  → tagStyles.project["<project name>"]
 * `resolve()` takes two things separately, so "turn it off here" and "turn it back on here" need
 * no colours of their own: whether the tag is SHOWN comes from the most specific rule that says
 * on/off; how it LOOKS from the most specific rule that styles it; with no rule, FLEx's own
 * colours when the tag item has a background, else the palette. A rule with enabled:false is kept
 * but skipped. Within one scope a tag's own rule beats `*`. Every row in the editors says which
 * scope decided ("styled by the tab", "hidden by this example"). */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;
  const R = FS.flexref;
  const PALETTE = ['#ffd6a5', '#caffbf', '#9bf6ff', '#bdb2ff', '#ffadad', '#fdffb6', '#a0c4ff', '#ffc6ff', '#b9fbc0', '#f1c0e8'];
  const BRACKETS = { sq: ['[', ']'], rd: ['(', ')'], cu: ['{', '}'], an: ['\u27e8', '\u27e9'], db: ['\u27e6', '\u27e7'], ce: ['\u2308', '\u2309'], fl: ['\u230a', '\u230b'], bar: ['|', '|'] };
  const EMPTY = () => ({ project: {}, tab: {}, folder: {}, note: {}, text: {}, filters: [] });
  const textTitles = new Map();       // text guid → title, from the examples drawn (the scope's label)
  let config = EMPTY();
  let list = [];                   // the project's tag list [{guid, name, abbr, group, fore, back}]
  let listPromise = null;
  const norm = (s) => String(s || '').trim().toLowerCase();
  const T = {
    PALETTE, BRACKETS,
    setConfig(c) { config = Object.assign(EMPTY(), c || {}); if (!Array.isArray(config.filters)) config.filters = []; },
    filters: () => config.filters,
    noteTextTitle(guid, title) { if (guid && title) textTitles.set(String(guid).toLowerCase(), title); },
    textLabel: (guid) => 'the text “' + (textTitles.get(String(guid || '').toLowerCase()) || String(guid || '').slice(0, 8) + '…') + '”',
    config: () => config,
    context: () => ({ project: '', tab: '', folder: '', note: '' }),   // app.js: the open note's place
    list: () => list,
    setList(l) { list = l || []; },
    loadList(force) {
      if (listPromise && !force) return listPromise;
      listPromise = FS.api.flex_text_tags().then((l) => { list = l || []; return list; }, () => list);
      return listPromise;
    },
    // the project's Chart Markers list (chart.js; Seth, 2026-10-18: "visual filters using
    // textchartmarkers instead of textmarkuptags"): a marker is a tag item with `marker: true`,
    // its rules keyed `marker:<name>` / `marker:group:<g>` / `marker:*`
    markers: () => markers,
    setMarkers(l) { markers = (l || []).map((m) => Object.assign({}, m, { marker: true })); },
    loadMarkers(force) {
      if (markersPromise && !force) return markersPromise;
      markersPromise = (FS.api.flex_chart_markers ? FS.api.flex_chart_markers() : Promise.resolve([])).then((l) => { T.setMarkers(l); return markers; }, () => markers);
      return markersPromise;
    },
  };
  let markers = [];
  let markersPromise = null;
  // the chart COLUMNS seen on the examples drawn (their templates' columns), for the picker
  const columnsSeen = new Map();
  T.noteColumn = (col) => { if (col && col.name) columnsSeen.set((col.path || []).concat([col.name]).join('/'), Object.assign({}, col, { column: true, guid: 'column:' + (col.guid || col.name) })); };
  T.columns = () => [...columnsSeen.values()];

  /* The scopes that apply at `ctx`, most specific first. `override` stands in for one scope's
   * stored rules (an editor showing the effect of unsaved changes). */
  function scopesFor(ctx, exampleRules, override) {
    const rulesOf = (kind, key) => (override && override.kind === kind && override.key === key) ? override.rules : ((config[kind] || {})[key] || []);
    const out = [];
    if (exampleRules) out.push({ kind: 'example', key: '', label: 'this example', rules: exampleRules });
    if (ctx.note) out.push({ kind: 'note', key: ctx.note, label: 'this note', rules: rulesOf('note', ctx.note) });
    const parts = String(ctx.folder || '').split('/').filter(Boolean);
    for (let i = parts.length; i >= 1; i--) {
      const key = (ctx.tab || '') + '/' + parts.slice(0, i).join('/');
      out.push({ kind: 'folder', key, label: 'the folder “' + parts[i - 1] + '”', rules: rulesOf('folder', key) });
    }
    out.push({ kind: 'tab', key: ctx.tab || '', label: 'the tab', rules: rulesOf('tab', ctx.tab || '') });
    if (ctx.text) out.push({ kind: 'text', key: String(ctx.text).toLowerCase(), label: T.textLabel(ctx.text), rules: rulesOf('text', String(ctx.text).toLowerCase()) });
    const project = { kind: 'project', key: ctx.project || '', label: 'the whole notebook', rules: rulesOf('project', ctx.project || '') };
    // the visual filters that are on here: a scope's `filter:<id>` rule decides first, else the filter's own switch
    for (const f of config.filters || []) {
      const on = filterOn(f, out.concat([project]));
      if (on) out.push({ kind: 'filter', key: f.id, label: 'the filter “' + (f.name || 'untitled') + '”', rules: (override && override.kind === 'filter' && override.key === f.id) ? override.rules : (f.rules || []) });
    }
    out.push(project);
    return out;
  }
  /* Is filter `f` on at these scopes (most specific first)? */
  function filterOn(f, scopes) {
    const key = 'filter:' + norm(f.id);
    for (const sc of scopes) {
      const r = (sc.rules || []).find((x) => x && x.enabled !== false && norm(x.tag) === key && x.hide != null);
      if (r) return !r.hide;
    }
    return f.enabled !== false;
  }
  const matches = (rule, tag) => {
    let k = norm(rule.tag);
    if (k.startsWith('marker:')) { if (!tag.marker) return false; k = k.slice(7); } else if (tag.marker) return false;
    if (k.startsWith('column:')) { if (!tag.column) return false; k = k.slice(7); } else if (tag.column) return false;
    if (k === '*') return true;
    if (k.startsWith('group:')) { const g = k.slice(6); return (tag.path || (tag.group ? [tag.group] : [])).some((x) => norm(x) === g); }
    if (k.startsWith('filter:')) return false;
    return k === norm(tag.name) || (!!tag.abbr && k === norm(tag.abbr)) || (!!tag.guid && k === norm(tag.guid));
  };
  const rank = (r) => { const k = norm(r.tag).replace(/^(marker|column):/, ''); return k === '*' ? 2 : k.startsWith('group:') ? 1 : 0; };
  /* One scope's rules for a tag, in the order they are consulted: the tag's own, its group's, then `*`. */
  function rulesIn(rules, tag) {
    return (rules || []).filter((r) => r && r.enabled !== false && matches(r, tag)).sort((a, b) => rank(a) - rank(b));
  }
  const TEXT_KEYS = ['br', 'hl', 'tile', 'box', 'c'];
  const BORDER_STYLES = ['solid', 'dashed', 'dotted', 'double'];
  const hasStyle = (r) => !!(r && (r.bg || r.fg || r.b || r.i || r.u || r.row || r.label === false || r.bar != null || r.bs || r.bw || r.tc || TEXT_KEYS.some((k) => r[k])));
  const textStyled = (res) => !!(res && (res.br || res.hl || res.tile || res.box || res.c));
  /* '#rrggbb' at an opacity (the overlays blend where tags overlap). */
  const rgba = (hex, a) => { const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ''); return m ? 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')' : hex; };
  /* A darker, fuller version of a pastel for brackets and borders. */
  const ink = (hex) => { const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ''); if (!m) return hex; const d = (h) => Math.max(0, Math.round(parseInt(h, 16) * 0.55)); return 'rgb(' + d(m[1]) + ',' + d(m[2]) + ',' + d(m[3]) + ')'; };
  function paletteIndex(tag) {
    const i = list.findIndex((t) => t.guid === tag.guid);
    if (i >= 0) return i;
    let h = 0;
    for (const c of norm(tag.name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return h;
  }
  function resolve(tag, spec, ctx, override) {
    const c = Object.assign({}, ctx || T.context());
    if (spec && spec.guid && !c.text) c.text = spec.guid;       // the example's source text is a scope of its own
    const scopes = scopesFor(c, spec ? R.tagRules(spec) : null, override);
    const out = { hide: false, bg: '', fg: '', b: false, i: false, u: false, label: true, br: '', hl: false, tile: false, box: false, c: '', bar: null, bs: '', bw: 0, tc: '', row: false, hideVia: null, styleVia: null };
    for (const sc of scopes) {
      for (const r of rulesIn(sc.rules, tag)) {
        if (!out.hideVia && r.hide != null) { out.hide = !!r.hide; out.hideVia = sc; }
        // the border's line style / thickness and the tile's own colour ride with the style (Seth, 2026-10-18)
        if (!out.styleVia && hasStyle(r)) Object.assign(out, { bg: r.bg || '', fg: r.fg || '', b: !!r.b, i: !!r.i, u: !!r.u, label: r.label !== false, br: BRACKETS[r.br] ? r.br : '', hl: !!r.hl, tile: !!r.tile, box: !!r.box, c: r.c || '', bar: r.bar == null ? null : !!r.bar, bs: BORDER_STYLES.includes(r.bs) ? r.bs : '', bw: r.bw >= 1 && r.bw <= 6 ? Math.round(r.bw) : 0, tc: r.tc || '', row: !!r.row, styleVia: sc });
      }
      if (out.hideVia && out.styleVia) break;
    }
    out.showBar = out.bar != null ? out.bar : !textStyled(out);
    if (!out.styleVia) {
      if (tag.back) { out.bg = tag.back; out.fg = tag.fore || ''; out.styleVia = { kind: 'flex', label: 'FLEx’s own colours' }; }
      else { out.bg = PALETTE[paletteIndex(tag) % PALETTE.length]; out.styleVia = { kind: 'default', label: 'the standard palette' }; }
    } else if (!out.bg) out.bg = tag.back || PALETTE[paletteIndex(tag) % PALETTE.length];
    if (!out.fg) out.fg = FS.readableTextColor ? FS.readableTextColor(out.bg) : '#1a1d21';
    out.ink = ink(out.bg);
    return out;
  }

  /* FLEx's tag list is a HIERARCHY (two levels at least; Seth, 2026-10-18: "show that collapsible
   * hierarchy in the UI" wherever tags are chosen, searched, switched or added). `tagTree` folds a
   * flat list into nodes by each tag's `path`, keeping FLEx's order; `renderTagTree` draws it with
   * fold-able group headings, remembered on this computer (fs:tagTree, shared by every list). */
  function tagTree(items) {
    const root = { name: '', path: [], key: '', entries: [], count: 0 };
    for (const t of items) {
      let node = root;
      const path = (t.path && t.path.length) ? t.path : (t.group ? [t.group] : []);
      node.count++;
      for (const name of path) {
        let c = node.entries.find((e) => e.node && e.node.name === name);
        if (!c) { c = { node: { name, path: node.path.concat([name]), key: node.path.concat([name]).join('/'), entries: [], count: 0 } }; node.entries.push(c); }
        node = c.node;
        node.count++;
      }
      node.entries.push({ tag: t });
    }
    return root;
  }
  const treeState = () => { try { return JSON.parse(localStorage.getItem('fs:tagTree') || '{}'); } catch (e) { return {}; } };
  const saveTreeState = (st) => { try { localStorage.setItem('fs:tagTree', JSON.stringify(st)); } catch (e) { /* ignore */ } };
  /* opts.leaf(tag, depth) → the row for a tag (null to leave it out); opts.head(node) → extra
   * controls on a group heading; opts.open → every group open (a search is on); opts.flat → no
   * headings at all. Returns the redraw function. */
  function renderTagTree(host, items, opts) {
    opts = opts || {};
    const draw = () => {
      host.innerHTML = '';
      const st = treeState();
      const walk = (node, depth) => {
        for (const e of node.entries) {
          if (e.tag) { const row = opts.leaf(e.tag, depth); if (row) { if (depth && !opts.flat) row.style.paddingInlineStart = (depth * 14) + 'px'; host.appendChild(row); } continue; }
          const n = e.node;
          if (opts.flat) { walk(n, depth); continue; }
          const closed = !opts.open && !!st[n.key];
          const head = el('div', { class: 'tag-tree-head' + (closed ? ' closed' : ''), 'data-test': 'tag-tree-group', dataset: { group: n.name }, style: { paddingInlineStart: (depth * 14) + 'px' }, title: closed ? 'Show this group' : 'Fold this group' },
            el('span', { class: 'tag-tree-caret' }, closed ? '\u25b8' : '\u25be'), el('span', { class: 'tag-tree-name' }, n.name), el('span', { class: 'tag-tree-n' }, String(n.count)));
          head.addEventListener('click', (e) => { if (e.target.closest('button, input, select')) return; const s2 = treeState(); if (closed) delete s2[n.key]; else s2[n.key] = true; saveTreeState(s2); draw(); });
          if (opts.head) { const extra = opts.head(n); if (extra) head.appendChild(extra); }
          host.appendChild(head);
          if (!closed) walk(n, depth + 1);
        }
      };
      walk(tagTree(items), 0);
    };
    draw();
    return draw;
  }

  /* The distinct tags on the segments an example shows: [{tag, count}]. */
  function tagsIn(obj) {
    const blank = (s) => (FS.interlinear && FS.interlinear.blankSeg ? FS.interlinear.blankSeg(s) : false);
    const ns = new Set((obj.segments || []).filter((s) => !blank(s)).map((s) => s.n));
    const seen = new Map();
    for (const t of obj.tags || []) {
      let hit = false;
      for (let n = t.from.seg; n <= t.to.seg && !hit; n++) hit = ns.has(n);
      if (!hit) continue;
      const e = seen.get(t.tag.guid) || { tag: t.tag, count: 0 };
      e.count++;
      seen.set(t.tag.guid, e);
    }
    return [...seen.values()];
  }

  /* The chart markers a chart (or a slice of it) carries: [{tag (marker: true), count}]. */
  function markersIn(obj) {
    const seen = new Map();
    for (const r of obj.rows || []) for (const c of r.cells || []) {
      if (c.kind !== 'tag' || !c.tag) continue;
      const e = seen.get(c.tag.guid) || { tag: Object.assign({}, c.tag, { marker: true }), count: 0 };
      e.count++;
      seen.set(c.tag.guid, e);
    }
    return [...seen.values()];
  }

  async function save(kind, key, rules) {
    if (kind === 'filter') {
      const list = (config.filters || []).map((f) => (f.id === key ? Object.assign({}, f, { rules }) : f));
      return saveFilters(list);
    }
    const c = await FS.api.set_tag_styles(kind, key, rules);
    T.setConfig(c);
    FS.emit('tagstyles');
  }
  async function saveFilters(list) {
    const c = await FS.api.set_tag_filters(list);
    T.setConfig(c);
    FS.emit('tagstyles');
  }
  const newId = () => 'f' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  /* One tag's rule in a rule list, patched (undefined deletes a key); a rule left with nothing
   * but its tag goes. */
  function patchRule(rules, tagName, patch) {
    let r = rules.find((x) => norm(x.tag) === norm(tagName));
    if (!r) { r = { tag: tagName }; rules.push(r); }
    for (const [k, v] of Object.entries(patch)) { if (v === undefined) delete r[k]; else r[k] = v; }
    if (!Object.keys(r).some((k) => k !== 'tag' && k !== 'enabled')) rules.splice(rules.indexOf(r), 1);
    return rules;
  }

  /* The controls of one rule: shown?, colours, B I U, label. get() → the rule, set(patch) writes. */
  function controls(get, set, o) {
    o = o || {};
    const r = get() || {};
    const box = el('div', { class: 'tag-ctl' });
    if (!o.noShow) {
      const sel = el('select', { title: 'Shown here?', 'data-test': 'tag-show' });
      const cur = r.hide === true ? 'hide' : r.hide === false ? 'show' : '';
      for (const [v, l] of [['', o.inheritLabel || 'as inherited'], ['show', 'shown'], ['hide', 'hidden']]) sel.appendChild(el('option', { value: v, selected: cur === v }, l));
      sel.addEventListener('change', () => set({ hide: sel.value === '' ? undefined : sel.value === 'hide' }));
      box.appendChild(sel);
    }
    for (const c of ['', ...PALETTE]) box.appendChild(el('button', { class: 'sw' + ((r.bg || '') === c ? ' on' : ''), 'data-test': c ? 'tag-bg' : 'tag-nobg', style: c ? { background: c } : { background: 'repeating-linear-gradient(45deg, #fff 0 4px, #ccc 4px 8px)' }, title: c || 'no colour of its own (inherit)', onclick: () => set({ bg: c || undefined }) }));
    const custom = el('input', { type: 'color', value: r.bg || '#ffd6a5', title: 'Any colour' });
    custom.addEventListener('change', () => set({ bg: custom.value }));
    box.appendChild(custom);
    const fg = el('input', { type: 'color', value: r.fg || '#1a1d21', title: 'Text colour on the tag (automatic when unset)' });
    fg.addEventListener('change', () => set({ fg: fg.value }));
    box.appendChild(el('span', { class: 'tag-ctl', title: 'Text colour' }, 'A', fg, r.fg ? el('button', { class: 'tog', title: 'Back to the automatic text colour', onclick: () => set({ fg: undefined }) }, 'auto') : null));
    for (const [k, l, ttl, st] of [['b', 'B', 'Bold words', { fontWeight: '700' }], ['i', 'I', 'Italic words', { fontStyle: 'italic' }], ['u', 'U', 'Underline the words in the tag’s colour', { textDecoration: 'underline' }]]) {
      box.appendChild(el('button', { class: 'tog' + (r[k] ? ' on' : ''), 'data-test': 'tag-' + k, title: ttl, style: st, onclick: () => set({ [k]: r[k] ? undefined : true }) }, l));
    }
    if (o.marker) {
      // a chart marker (Seth, 2026-10-18: "row-level markers, so that when they are found anywhere in
      // a row, that whole row is styled"): the chip, or the whole row
      box.appendChild(el('button', { class: 'tog' + (r.row ? ' on' : ''), 'data-test': 'tag-row', title: 'Style the WHOLE ROW the marker is in, not just the marker', onclick: () => set({ row: r.row ? undefined : true }) }, 'whole row'));
      const c = el('input', { type: 'color', value: r.c || '#1a1d21', title: 'Colour of the row’s words' });
      c.addEventListener('change', () => set({ c: c.value }));
      box.appendChild(el('span', { class: 'tag-ctl', title: 'Colour of the words' }, 'text', c, r.c ? el('button', { class: 'tog', title: 'Back to the usual word colour', onclick: () => set({ c: undefined }) }, 'auto') : null));
      return box;
    }
    box.appendChild(el('button', { class: 'tog' + (r.label === false ? '' : ' on'), title: 'Show the tag’s abbreviation (off: a thin bar only)', onclick: () => set({ label: r.label === false ? undefined : false }) }, 'label'));
    // the TEXT itself (Seth, 2026-10-18): brackets round the span, a marker, a tile, a border, a colour
    const txt = el('div', { class: 'tag-ctl tag-ctl-text' });
    const br = el('select', { title: 'Brackets around the tagged words (and the lines under them)', 'data-test': 'tag-br' });
    br.appendChild(el('option', { value: '', selected: !r.br }, 'no brackets'));
    for (const [k, [a, z]] of Object.entries(BRACKETS)) br.appendChild(el('option', { value: k, selected: r.br === k }, a + ' word ' + z));
    br.addEventListener('change', () => set({ br: br.value || undefined }));
    txt.appendChild(br);
    for (const [k, l, ttl] of [['hl', 'highlight', 'A marker over the words'], ['tile', 'tile', 'A tinted box behind the words and their lines'], ['box', 'border', 'A border around the words and their lines']]) {
      txt.appendChild(el('button', { class: 'tog' + (r[k] ? ' on' : ''), 'data-test': 'tag-' + k, title: ttl, onclick: () => set({ [k]: r[k] ? undefined : true, ...(k === 'box' && r.box ? { bs: undefined, bw: undefined } : {}), ...(k === 'tile' && r.tile ? { tc: undefined } : {}) }) }, l));
      if (k === 'tile' && r.tile) {        // the tile's own colour (Seth, 2026-10-18: "edit the background color"); unset = the tag's colour, tinted
        const tc = el('input', { type: 'color', value: r.tc || r.bg || '#ffd6a5', 'data-test': 'tag-tc', title: 'Colour of the tile (the tag’s colour, tinted, when unset)' });
        tc.addEventListener('change', () => set({ tc: tc.value }));
        txt.appendChild(el('span', { class: 'tag-ctl', title: 'Colour of the tile' }, tc, r.tc ? el('button', { class: 'tog', 'data-test': 'tag-tc-auto', title: 'Back to the tag’s colour, tinted', onclick: () => set({ tc: undefined }) }, 'auto') : null));
      }
      if (k === 'box' && r.box) {          // the border's line (Seth, 2026-10-18: "edit line style and thickness")
        const bs = el('select', { 'data-test': 'tag-bs', title: 'Line style of the border' });
        for (const v of BORDER_STYLES) bs.appendChild(el('option', { value: v, selected: (r.bs || 'solid') === v }, v));
        bs.addEventListener('change', () => set({ bs: bs.value === 'solid' ? undefined : bs.value }));
        const bw = el('select', { 'data-test': 'tag-bw', title: 'Thickness of the border' });
        for (const v of [1, 2, 3, 4, 6]) bw.appendChild(el('option', { value: String(v), selected: (r.bw || 2) === v }, v + ' px'));
        bw.addEventListener('change', () => set({ bw: +bw.value === 2 ? undefined : +bw.value }));
        txt.append(bs, bw);
      }
    }
    const c = el('input', { type: 'color', value: r.c || '#1a1d21', title: 'Colour of the words' });
    c.addEventListener('change', () => set({ c: c.value }));
    txt.appendChild(el('span', { class: 'tag-ctl', title: 'Colour of the words' }, 'text', c, r.c ? el('button', { class: 'tog', title: 'Back to the usual word colour', onclick: () => set({ c: undefined }) }, 'auto') : null));
    const bar = el('select', { title: 'The tag’s bar under the words', 'data-test': 'tag-bar' });
    for (const [v, l] of [['', 'bar: when nothing else shows the tag'], ['on', 'bar: always'], ['off', 'bar: never']]) bar.appendChild(el('option', { value: v, selected: (r.bar === true ? 'on' : r.bar === false ? 'off' : '') === v }, l));
    bar.addEventListener('change', () => set({ bar: bar.value === '' ? undefined : bar.value === 'on' }));
    txt.appendChild(bar);
    box.appendChild(txt);
    return box;
  }

  /* A scope's switches for the visual filters: as inherited / on / off here, as `filter:<id>` rules. */
  function filterSwitches(rules, set, o) {
    const host = el('div', { class: 'tag-filter-switches' });
    if (!(config.filters || []).length) return host;
    host.appendChild(el('div', { class: 'tag-group' }, 'Visual filters here'));
    for (const f of config.filters) {
      const key = 'filter:' + f.id;
      const r = rules.find((x) => norm(x.tag) === norm(key));
      const cur = r && r.hide === true ? 'off' : r && r.hide === false ? 'on' : '';
      const sel = el('select', { 'data-test': 'tag-filter-switch', dataset: { filter: f.id } });
      for (const [v, l] of [['', o && o.inheritLabel || 'as inherited (' + (f.enabled !== false ? 'on' : 'off') + ')'], ['on', 'on here'], ['off', 'off here']]) sel.appendChild(el('option', { value: v, selected: cur === v }, l));
      sel.addEventListener('change', () => set(key, { hide: sel.value === '' ? undefined : sel.value === 'off' }));
      host.appendChild(el('div', { class: 'tagrow' }, el('span', { class: 'tag-name' }, f.name || 'untitled filter'), sel));
    }
    return host;
  }

  /* The ⚑ popover on an example: its tags, each with where its look comes from, a show / hide
   * toggle and its own style — all written into the embed's `tags=`. */
  function examplePopover(anchor, spec, obj, opts) {
    const markerMode = !!(opts && opts.markers);
    const ctx = Object.assign({}, T.context(), { text: markerMode ? (obj.text || spec.guid) : spec.guid });
    const keyOf = (tag) => (tag.marker ? 'marker:' : tag.column ? 'column:' : '') + tag.name;
    // where a change made here goes (Seth, 2026-10-18: "a rule should let the user choose its
    // scope (whole notebook, tab, folder, notes doc, selected range in a note, specific texts
    // anywhere they appear)"): this example by default; a selection of examples is the note
    // menu's "FLEx tag styles for the selected examples…"
    const targets = scopesFor(ctx, [], null).map((sc) => ({ kind: sc.kind, key: sc.key, label: sc.kind === 'example' ? 'this example' : sc.label }));
    let target = targets[0];
    FS.popover(anchor, (pop, close) => {
      const openTags = new Set();
      const rulesFor = () => {
        if (target.kind === 'example') return R.tagRules(spec);
        if (target.kind === 'filter') return (((config.filters || []).find((f) => f.id === target.key) || {}).rules || []).map((r) => Object.assign({}, r));
        return ((config[target.kind] || {})[target.key] || []).map((r) => Object.assign({}, r));
      };
      let rules = rulesFor();
      const write = async () => {
        if (target.kind === 'example') { R.setTagRules(spec, rules); opts.onSpecChange && opts.onSpecChange(spec); return; }
        try { await save(target.kind, target.key, rules); } catch (e) { FS.toast(e.message, 'error'); }
      };
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'FLEx text markup tags in this example')));
      const scopeSel = el('select', { 'data-test': 'tag-scope-pick', title: 'Where the changes made here apply' });
      targets.forEach((t, i) => scopeSel.appendChild(el('option', { value: String(i), selected: t === target }, t.label.replace(/^the folder /, 'folder ').replace(/^the tab$/, 'this tab'))));
      scopeSel.addEventListener('change', () => { target = targets[+scopeSel.value]; rules = rulesFor(); openTags.clear(); draw(); });
      pop.appendChild(el('div', { class: 'row', style: { gap: '6px' } }, el('span', { class: 'lbl' }, 'Changes apply to'), scopeSel));
      const host = el('div', { class: 'tag-rules', 'data-test': 'tag-popover' });
      const draw = () => {
        host.innerHTML = '';
        const here = markerMode ? markersIn(obj) : tagsIn(obj);
        const countOf = new Map(here.map((x) => [x.tag.guid, x.count]));
        if (markerMode) host.appendChild(el('div', { class: 'muted small', style: { padding: '2px 0 6px' } }, 'Chart markers in this chart. “Style ▾” → “whole row” colours every row the marker is in.'));
        renderTagTree(host, here.map((x) => x.tag), { leaf: (tag) => {
          const count = countOf.get(tag.guid) || 1;
          const res = resolve(tag, spec, ctx);
          const row = el('div', { class: 'tagrow', dataset: { tag: tag.name } });
          const cb = el('input', { type: 'checkbox', checked: !res.hide, 'data-test': 'tag-toggle', title: res.hide ? 'Show this tag (' + target.label + ')' : 'Hide this tag (' + target.label + ')' });
          cb.addEventListener('change', async () => {
            // hidden by a broader scope → "on" at the target; hidden by the target itself → just drop that; shown → "off"
            const decidedHere = res.hideVia && res.hideVia.kind === target.kind && res.hideVia.key === target.key;
            patchRule(rules, keyOf(tag), { hide: cb.checked ? (decidedHere ? undefined : false) : true });
            await write(); draw();
          });
          const sw = el('span', { class: 'tag-sw', style: swatchStyle(res) });
          const via = el('span', { class: 'via', 'data-test': 'tag-via' }, res.hide ? 'hidden by ' + res.hideVia.label : (res.hideVia && res.hideVia.kind === 'example' ? 'shown here · ' : '') + 'styled by ' + res.styleVia.label);
          const name = el('span', { class: 'tag-name' }, el('span', {}, tag.name + (tag.abbr && tag.abbr !== tag.name ? ' (' + tag.abbr + ')' : '') + (count > 1 ? '  ×' + count : '')), el('br'), via);
          const styleBtn = el('button', { class: 'lnk', 'data-test': 'tag-style', title: 'The look of this tag, for ' + target.label, onclick: () => { if (openTags.has(tag.name)) openTags.delete(tag.name); else openTags.add(tag.name); draw(); } }, 'Style ▾');
          const find = FS.openPicker && !tag.marker ? el('button', { class: 'lnk', title: 'Find the other places this tag is used, and insert them', onclick: () => { close(); FS.openPicker({ mode: 'tags', tag: tag.guid }); } }, '\u{1F50D}') : null;
          row.append(cb, sw, name, styleBtn, find);
          if (!openTags.has(tag.name)) return row;
          return el('div', {}, row, el('div', { class: 'tag-style-box' }, controls(() => rules.find((x) => norm(x.tag) === norm(keyOf(tag))), async (patch) => { patchRule(rules, keyOf(tag), patch); await write(); draw(); }, { noShow: true, marker: !!tag.marker })));
        } });
      };
      draw();
      pop.appendChild(host);
      if ((config.filters || []).length && target.kind !== 'filter') pop.appendChild(filterSwitches(rules, async (key, patch) => { patchRule(rules, key, patch); await write(); draw(); }, { inheritLabel: 'as inherited' }));
      pop.appendChild(el('hr'));
      if (R.tagRules(spec).length) pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'tag-clear', onclick: () => { R.setTagRules(spec, []); opts.onSpecChange && opts.onSpecChange(spec); close(); } }, markerMode ? 'Clear this chart’s own marker styles' : 'Clear this example’s own tag styles'));
      const links = el('div', { class: 'row', style: { gap: '10px', flexWrap: 'wrap' } }, el('span', { class: 'lbl' }, 'All rules for'));
      for (const sc of scopesFor(ctx)) { if (sc.kind !== 'filter') links.appendChild(el('button', { class: 'lnk', 'data-test': 'tag-scope-' + sc.kind, onclick: () => { close(); dialog(sc); } }, (sc.kind === 'folder' ? sc.label.replace(/^the /, '') : sc.kind === 'text' ? 'this text' : sc.label.replace(/^the /, 'this ')) + '…')); }
      links.appendChild(el('button', { class: 'lnk', 'data-test': 'tag-scope-filters', onclick: () => { close(); filtersDialog(); } }, 'visual filters…'));
      pop.appendChild(links);
    });
  }

  function ctxFor(scope) {
    if (scope.kind === 'project') return { project: scope.key, tab: '', folder: '' };
    if (scope.kind === 'filter' || scope.kind === 'note') return T.context();
    if (scope.kind === 'text') return Object.assign({}, T.context(), { text: scope.key });
    if (scope.kind === 'tab') return { project: T.context().project, tab: scope.key, folder: '' };
    const i = scope.key.indexOf('/');
    return { project: T.context().project, tab: scope.key.slice(0, i), folder: scope.key.slice(i + 1) };
  }

  /* The editor for one scope: every tag of the project (and `*`), the rule here, the effect.
   * scope = {kind: 'project'|'tab'|'folder', key, label}, or {kind: 'example', label, rules,
   * apply(rules)} for a selection of examples (app.js writes the rules into each embed). */
  /* The editor for one scope: ONLY the tags that were added to it, one at a time from a list (Seth,
   * 2026-10-18: "by default a new rule should have nothing in it and have tags added manually one
   * at a time, chosen from a list … If the user hasn't manually added a tag to a visual filter
   * rule, then that visual filter rule has no effect on that tag one way or another").
   * scope = {kind: 'project'|'tab'|'folder'|'filter', key, label}, or {kind: 'example', label,
   * rules, apply(rules)} for a selection of examples (app.js writes the rules into each embed). */
  async function dialog(scope) {
    await T.loadList();
    const example = scope.kind === 'example', filter = scope.kind === 'filter';
    const m = FS.modal({ title: (filter ? 'Visual filter — ' : 'FLEx tag styles — ') + scope.label });
    const stored = example ? (scope.rules || []) : filter ? (((config.filters || []).find((f) => f.id === scope.key) || {}).rules || []) : ((config[scope.kind] || {})[scope.key] || []);
    const rules = stored.map((r) => Object.assign({}, r));
    const pending = [];                 // tags added but not styled yet: shown, not saved
    const ctx = example ? T.context() : ctxFor(scope);
    const override = { kind: scope.kind, key: scope.key, rules };
    m.body.appendChild(el('p', { class: 'small muted' }, example
      ? 'These settings are written into each selected example and win over its folder, tab and project. Only the tags you add here are affected.'
      : filter ? 'A visual filter is a named set of tag styles, switched on and off as a whole — for one note or everywhere (⚑ Filters in the toolbar). Add the tags it should style; a tag you have not added is left exactly as it was. When several filters are on, the first that styles a tag decides; a note’s, folder’s or tab’s own rules still win over any filter.'
        : 'Rules here apply to every example in ' + scope.label + ' unless a more specific place (a folder inside it, a note, or an example itself) says otherwise. Only the tags you add here are affected; untick a rule to keep it without using it.'));
    const host = el('div', { class: 'tag-rules', 'data-test': 'tag-dialog' });
    m.body.appendChild(host);
    const commit = async () => {
      try { if (example) scope.apply(rules.filter((r) => Object.keys(r).some((k) => k !== 'tag' && k !== 'enabled'))); else await save(scope.kind, scope.key, rules); }
      catch (e) { FS.toast(e.message, 'error'); }
      draw();
    };
    // what a rule's key stands for: a tag of the list, a group, every tag, or a name the list no longer has
    const itemFor = (key) => {
      const k = norm(key);
      if (k.startsWith('column:')) {
        const ck = k.slice(7);
        if (ck === '*') return { guid: 'column:*', name: key, abbr: '', group: '', column: true, isBroad: true, label: 'All chart columns', note: 'one rule for every chart column drawn on an example' };
        if (ck.startsWith('group:')) { const g = key.slice(13); return { guid: 'column:group:' + g, name: key, abbr: '', group: g, column: true, isBroad: true, label: 'All chart columns of “' + g + '”', note: 'one rule for the group’s columns; a column’s own rule wins' }; }
        const c = T.columns().find((x) => norm(x.name) === ck || (x.abbr && norm(x.abbr) === ck) || norm((x.path || []).concat([x.name]).join('/')) === ck);
        return c ? Object.assign({}, c, { isMarker: true, label: (c.path || []).concat([c.name]).join(' › ') + ' (chart column)' }) : { guid: key, name: key.slice(7), abbr: '', group: '', column: true, isMarker: true, label: key.slice(7) + ' (chart column)', note: 'a chart column' };
      }
      if (k.startsWith('marker:')) {
        const mk = k.slice(7);
        if (mk === '*') return { guid: 'marker:*', name: key, abbr: '', group: '', marker: true, isBroad: true, label: 'All chart markers', note: 'one rule for every chart marker; a marker’s or group’s own rule wins' };
        if (mk.startsWith('group:')) { const g = key.slice(13); return { guid: 'marker:group:' + g, name: key, abbr: '', group: g, marker: true, isBroad: true, label: 'All chart markers of “' + g + '”', note: 'one rule for the group’s markers; a marker’s own rule wins' }; }
        const m = markers.find((x) => norm(x.name) === mk || (x.abbr && norm(x.abbr) === mk) || norm(x.guid) === mk);
        return m ? Object.assign({}, m, { marker: true, isMarker: true, label: m.name + (m.abbr && m.abbr !== m.name ? ' (' + m.abbr + ')' : '') + ' (chart marker)' }) : { guid: key, name: key.slice(7), abbr: '', group: '', marker: true, isMarker: true, label: key.slice(7) + ' (chart marker)', note: 'not in the project’s Chart Markers list' };
      }
      if (k === '*') return { guid: '*', name: '*', abbr: '', group: '', label: 'All tags', note: 'one rule for every tag; a tag’s or group’s own rule wins' };
      if (k.startsWith('group:')) { const g = key.slice(6); return { guid: 'group:' + g, name: key, abbr: '', group: g, isGroup: true, label: 'All of “' + g + '”', note: 'one rule for the group’s tags; a tag’s own rule wins' }; }
      if (k.startsWith('filter:')) return null;
      const t = list.find((x) => norm(x.name) === k || (x.abbr && norm(x.abbr) === k) || norm(x.guid) === k);
      return t ? Object.assign({}, t, { label: t.name + (t.abbr && t.abbr !== t.name ? ' (' + t.abbr + ')' : '') }) : { guid: key, name: key, abbr: '', group: '', label: key, note: 'not in the project’s tag list' };
    };
    const draw = () => {
      host.innerHTML = '';
      if (!example && !filter) host.appendChild(filterSwitches(rules, (key, patch) => { patchRule(rules, key, patch); commit(); }));
      const keys = [];
      for (const r of rules) if (!norm(r.tag).startsWith('filter:') && !keys.some((k) => norm(k) === norm(r.tag))) keys.push(r.tag);
      for (const k of pending) if (!keys.some((x) => norm(x) === norm(k))) keys.push(k);
      if (!keys.length) host.appendChild(el('div', { class: 'muted small', 'data-test': 'tag-dialog-empty', style: { padding: '8px 0' } }, filter ? 'This filter styles no tag yet. Add the tags it should style.' : 'No tag is styled here yet. Add one to begin.'));
      const rowFor = (key) => {
        const tag = itemFor(key);
        if (!tag) return null;
        const r = rules.find((x) => norm(x.tag) === norm(key)) || null;
        const row = el('div', { class: 'tagrow', dataset: { tag: tag.name } });
        if (!example) {
          const on = el('input', { type: 'checkbox', checked: !r || r.enabled !== false, disabled: !r, 'data-test': 'tag-rule-on', title: r ? 'This rule is in use (untick to keep it but not use it)' : 'Choose a style for this tag' });
          on.addEventListener('change', () => { if (r) { r.enabled = on.checked; commit(); } });
          row.appendChild(on);
        }
        const res = tag.guid === '*' || tag.isGroup || tag.isBroad || !tag.guid ? null : resolve(tag, example ? { extra: { tags: R.serializeTagRules(rules) } } : null, ctx, example ? null : override);
        row.appendChild(el('span', { class: 'tag-sw', style: res ? swatchStyle(res) : { background: 'var(--panel-2)' } }));
        row.appendChild(el('span', { class: 'tag-name' },
          el('span', {}, tag.label), el('br'),
          el('span', { class: 'via', 'data-test': 'tag-via' }, res ? (res.hide ? 'hidden by ' + res.hideVia.label : 'styled by ' + res.styleVia.label) : tag.note || '')));
        row.appendChild(controls(() => r, (patch) => { patchRule(rules, key, patch); commit(); }, { inheritLabel: example ? 'as the folder / tab / project says' : 'as inherited', marker: !!tag.marker }));
        row.appendChild(el('button', { class: 'icon-btn danger', 'data-test': 'tag-rule-remove', title: 'Remove this tag from here', onclick: () => { if (r) rules.splice(rules.indexOf(r), 1); const i = pending.findIndex((k) => norm(k) === norm(key)); if (i >= 0) pending.splice(i, 1); commit(); } }, '✕'));
        return row;
      };
      // `*` and the group rules first, then the tags in FLEx's own hierarchy
      const broad = keys.filter((k) => norm(k) === '*' || norm(k).startsWith('group:'));
      for (const key of broad) { const row = rowFor(key); if (row) host.appendChild(row); }
      // chart marker rules: their own rows, after the tags
      const markerKeys = keys.filter((k) => norm(k).startsWith('marker:') || norm(k).startsWith('column:'));
      const tagKeys = keys.filter((k) => !broad.includes(k) && !markerKeys.includes(k));
      const tagItems = tagKeys.map((k) => Object.assign({}, itemFor(k) || {}, { _key: k })).filter((t) => t.name);
      const tree = el('div');
      renderTagTree(tree, tagItems, { leaf: (t) => rowFor(t._key) });
      host.appendChild(tree);
      if (markerKeys.length) { host.appendChild(el('div', { class: 'tag-tree-head', style: { marginTop: '6px' } }, 'Chart markers and columns')); for (const key of markerKeys) { const row = rowFor(key); if (row) host.appendChild(row); } }
      const add = el('button', { class: 'btn', 'data-test': 'tag-add', onclick: (e) => addTagPicker(e.currentTarget, keys, (key) => { pending.push(key); draw(); }) }, '+ Add a tag…');
      host.appendChild(el('div', { class: 'btn-row', style: { justifyContent: 'flex-start', marginTop: '8px' } }, add));
      if (!list.length) host.appendChild(el('div', { class: 'muted small' }, 'No text markup tags have been read from the project yet. Open the project (or show an example that carries tags) and come back.'));
    };
    draw();
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn primary', onclick: () => m.close() }, 'Done')));
    return m;
  }
  /* The list to add a tag from: every tag of the project under its group, each group as a whole,
   * and all tags; a search box narrows it; what is already in the rule is left out. */
  function addTagPicker(anchor, have, pick) {
    const has = (k) => have.some((x) => norm(x) === norm(k));
    FS.popover(anchor, (pop, close) => {
      const q = el('input', { type: 'search', placeholder: 'Find a tag…', 'data-test': 'tag-pick-search', style: { width: '100%' } });
      const lst = el('div', { class: 'tag-pick-list' });
      const draw = () => {
        lst.innerHTML = '';
        const needle = norm(q.value);
        const row = (key, label, sub, cls) => el('button', { class: 'menu-item ' + (cls || ''), 'data-test': 'tag-pick', dataset: { tag: key }, onclick: () => { close(); pick(key); } }, el('span', {}, label), sub ? el('span', { class: 'muted small', style: { marginLeft: '6px' } }, sub) : null);
        if (!needle && !has('*')) lst.appendChild(row('*', 'All tags', 'every tag of the project', 'tag-pick-all'));
        const items = list.filter((t) => !(has(t.name) || has(t.guid) || (t.abbr && has(t.abbr))) && (!needle || norm(t.name).includes(needle) || norm(t.abbr).includes(needle) || (t.path || []).some((g) => norm(g).includes(needle))));
        const tree = el('div');
        renderTagTree(tree, items, {
          open: !!needle,
          leaf: (t) => row(t.name, t.name, t.abbr && t.abbr !== t.name ? t.abbr : '', 'tag-pick-tag'),
          head: (n) => (has('group:' + n.name) ? null : el('button', { class: 'lnk small', 'data-test': 'tag-pick-group', dataset: { tag: 'group:' + n.name }, title: 'One rule for every tag under “' + n.name + '”', onclick: (e) => { e.stopPropagation(); close(); pick('group:' + n.name); } }, '+ all of these')),
        });
        lst.appendChild(tree);
        if (markers.length) {
          const mitems = markers.filter((t) => !(has('marker:' + t.name) || has('marker:' + t.guid) || (t.abbr && has('marker:' + t.abbr))) && (!needle || norm(t.name).includes(needle) || norm(t.abbr).includes(needle) || (t.path || []).some((g) => norm(g).includes(needle))));
          if (mitems.length || (!needle && !has('marker:*'))) lst.appendChild(el('div', { class: 'tag-tree-head', style: { marginTop: '6px' } }, 'Chart markers'));
          if (!needle && !has('marker:*')) lst.appendChild(row('marker:*', 'All chart markers', 'every marker of the project', 'tag-pick-all'));
          const mtree = el('div');
          renderTagTree(mtree, mitems, {
            open: !!needle,
            leaf: (t) => row('marker:' + t.name, t.name, t.abbr && t.abbr !== t.name ? t.abbr : '', 'tag-pick-tag'),
            head: (n) => (has('marker:group:' + n.name) ? null : el('button', { class: 'lnk small', dataset: { tag: 'marker:group:' + n.name }, title: 'One rule for every chart marker under “' + n.name + '”', onclick: (e) => { e.stopPropagation(); close(); pick('marker:group:' + n.name); } }, '+ all of these')),
          });
          lst.appendChild(mtree);
        }
        const cols = T.columns();
        if (cols.length) {
          const citems = cols.filter((t) => !(has('column:' + t.name) || has('column:' + (t.path || []).concat([t.name]).join('/'))) && (!needle || norm(t.name).includes(needle) || (t.path || []).some((g) => norm(g).includes(needle))));
          if (citems.length || (!needle && !has('column:*'))) lst.appendChild(el('div', { class: 'tag-tree-head', style: { marginTop: '6px' } }, 'Chart columns'));
          if (!needle && !has('column:*')) lst.appendChild(row('column:*', 'All chart columns', 'every column, on examples that show them', 'tag-pick-all'));
          const ctree = el('div');
          renderTagTree(ctree, citems, {
            open: !!needle,
            leaf: (t) => row('column:' + (t.path || []).concat([t.name]).join('/'), t.name, (t.path || []).join(' › '), 'tag-pick-tag'),
            head: (n) => (has('column:group:' + n.name) ? null : el('button', { class: 'lnk small', dataset: { tag: 'column:group:' + n.name }, title: 'One rule for every chart column under “' + n.name + '”', onclick: (e) => { e.stopPropagation(); close(); pick('column:group:' + n.name); } }, '+ all of these')),
          });
          lst.appendChild(ctree);
        }
        if (!items.length && !lst.querySelector('.tag-pick-all')) lst.appendChild(el('div', { class: 'muted small', style: { padding: '6px' } }, list.length ? 'Nothing else to add.' : 'No tags have been read from the project yet.'));
      };
      q.addEventListener('input', draw);
      pop.appendChild(q);
      pop.appendChild(lst);
      draw();
      setTimeout(() => q.focus(), 0);
    }, { class: 'tag-pick' });
  }
  /* The swatch of a resolved look: its colour, and a hint of brackets / border when the text is styled. */
  function swatchStyle(res) {
    const st = { background: res.hide ? 'transparent' : (res.hl || res.tile || res.showBar ? res.bg : rgba(res.bg, 0.35)), borderStyle: res.hide ? 'dashed' : 'solid' };
    if (!res.hide && res.box) { st.borderColor = res.ink; st.borderStyle = res.bs || 'solid'; }
    if (!res.hide && res.tile && res.tc) st.background = rgba(res.tc, 0.55);
    if (!res.hide && res.br) st.boxShadow = 'inset 0 0 0 2px ' + res.ink;
    return st;
  }

  /* ⚑ Filters: the visual filters switched on and off as a whole (Seth, 2026-10-18: "various
   * 'visual filters' based on text tags like you can do with visual filters in Logos"). */
  let filtersMode = 'note';          // the popover's switch: 'note' (this page) or 'all' (the default everywhere)
  function filtersPopover(anchor) {
    const ctx = T.context();
    if (!ctx.note) filtersMode = 'all';
    FS.popover(anchor, (pop, close) => {
      const draw = () => {
        pop.innerHTML = '';
        const list = config.filters || [];
        const head = el('div', { class: 'row', style: { gap: '10px' } }, el('b', { style: { flex: 1 } }, 'Visual filters'));
        if (ctx.note) {
          const seg = el('span', { class: 'seg', 'data-test': 'filters-mode' });
          for (const [v, l, ttl] of [['note', 'This note', 'Switch filters on or off for this note only'], ['all', 'Everywhere', 'The default for every note (a note, folder or tab may still differ)']]) {
            seg.appendChild(el('button', { class: 'seg-btn' + (filtersMode === v ? ' on' : ''), title: ttl, dataset: { mode: v }, onclick: () => { filtersMode = v; draw(); } }, l));
          }
          head.appendChild(seg);
        }
        pop.appendChild(head);
        if (!list.length) pop.appendChild(el('div', { class: 'muted small', style: { padding: '4px 0 8px' } }, 'No visual filters yet. A filter is a named set of tag styles you switch on and off together.'));
        const noteRules = ctx.note ? ((config.note || {})[ctx.note] || []).map((r) => Object.assign({}, r)) : [];
        const scopes = scopesFor(ctx);
        for (const f of list) {
          const key = 'filter:' + f.id;
          const here = filtersMode === 'note';
          const own = here ? noteRules.find((r) => norm(r.tag) === norm(key) && r.hide != null) : null;
          const on = here ? filterOn(f, scopes) : f.enabled !== false;
          const cb = el('input', { type: 'checkbox', checked: on, 'data-test': 'filter-on', dataset: { filter: f.id } });
          cb.addEventListener('change', async () => {
            try {
              if (here) { patchRule(noteRules, key, { hide: !cb.checked }); await save('note', ctx.note, noteRules); }
              else await saveFilters(list.map((x) => (x.id === f.id ? Object.assign({}, x, { enabled: cb.checked }) : x)));
            } catch (e) { FS.toast(e.message, 'error'); }
            draw();
          });
          const row = el('label', { class: 'menu-item', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, cb, el('span', { style: { flex: 1 } }, f.name || 'untitled filter'));
          if (own) row.appendChild(el('button', { class: 'lnk small', title: 'Back to what the folder, tab or default says', 'data-test': 'filter-reset', onclick: async (e) => { e.preventDefault(); patchRule(noteRules, key, { hide: undefined }); try { await save('note', ctx.note, noteRules); } catch (err) { FS.toast(err.message, 'error'); } draw(); } }, 'this note only ↺'));
          else row.appendChild(el('span', { class: 'muted small' }, here ? (f.enabled !== false ? 'default on' : 'default off') : (f.rules || []).length + (f.rules && f.rules.length === 1 ? ' rule' : ' rules')));
          pop.appendChild(row);
        }
        pop.appendChild(el('hr'));
        pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'filters-manage', onclick: () => { close(); filtersDialog(); } }, 'Set up visual filters…'));
      };
      draw();
    });
  }
  async function filtersDialog() {
    await T.loadList();
    let off = () => {};
    const m = FS.modal({ title: 'Visual filters — FLEx text markup tags', onClose: () => off() });
    m.body.appendChild(el('p', { class: 'small muted' }, 'A visual filter is a named set of tag styles for this notebook, switched on and off as a whole — here, with the ⚑ Filters button, or for one tab, folder or example. When several are on, the first one that styles a tag decides; a tab’s, folder’s or example’s own rules still win over any filter.'));
    const host = el('div', { class: 'tag-rules', 'data-test': 'filters-dialog' });
    m.body.appendChild(host);
    const commit = async (list) => { try { await saveFilters(list); } catch (e) { FS.toast(e.message, 'error'); } draw(); };
    const draw = () => {
      host.innerHTML = '';
      const list = config.filters || [];
      list.forEach((f, i) => {
        const on = el('input', { type: 'checkbox', checked: f.enabled !== false, 'data-test': 'filter-on', dataset: { filter: f.id }, title: 'On' });
        on.addEventListener('change', () => commit(list.map((x) => (x === f ? Object.assign({}, x, { enabled: on.checked }) : x))));
        const name = el('input', { type: 'text', value: f.name || '', placeholder: 'Filter name', class: 'filter-name', 'data-test': 'filter-name' });
        name.addEventListener('change', () => commit(list.map((x) => (x === f ? Object.assign({}, x, { name: name.value.trim() }) : x))));
        const row = el('div', { class: 'tagrow', dataset: { filter: f.id } }, on, name,
          el('span', { class: 'muted small' }, (f.rules || []).length + (f.rules && f.rules.length === 1 ? ' rule' : ' rules')),
          el('button', { class: 'btn', 'data-test': 'filter-rules', onclick: () => dialog({ kind: 'filter', key: f.id, label: 'the filter “' + (f.name || 'untitled') + '”' }) }, 'Rules…'),
          el('button', { class: 'icon-btn', title: 'Move up (an earlier filter wins when two style the same tag)', disabled: i === 0, onclick: () => { const l = list.slice(); l.splice(i - 1, 0, l.splice(i, 1)[0]); commit(l); } }, '↑'),
          el('button', { class: 'icon-btn', title: 'Move down', disabled: i === list.length - 1, onclick: () => { const l = list.slice(); l.splice(i + 1, 0, l.splice(i, 1)[0]); commit(l); } }, '↓'),
          el('button', { class: 'icon-btn danger', title: 'Remove this filter', 'data-test': 'filter-remove', onclick: () => { if (confirm('Remove the filter “' + (f.name || 'untitled') + '” and its rules?')) commit(list.filter((x) => x !== f)); } }, '✕'));
        host.appendChild(row);
      });
      if (!list.length) host.appendChild(el('div', { class: 'muted small' }, 'No filters yet.'));
    };
    draw();
    m.body.appendChild(el('div', { class: 'btn-row', style: { justifyContent: 'space-between' } },
      el('button', { class: 'btn', 'data-test': 'filter-add', onclick: () => { const name = prompt('Name of the new visual filter', 'Grammatical relations'); if (name && name.trim()) commit((config.filters || []).concat([{ id: newId(), name: name.trim(), enabled: true, rules: [] }])); } }, '+ New filter'),
      el('button', { class: 'btn primary', onclick: () => m.close() }, 'Done')));
    off = FS.on('tagstyles', draw);
    return m;
  }

  FS.tagstyles = Object.assign(T, { resolve, tagsIn, markersIn, scopesFor, matches, hasStyle, textStyled, rgba, ink, patchRule, save, saveFilters, examplePopover, dialog, filtersPopover, filtersDialog, filterOn, tagTree, renderTagTree });
})();
