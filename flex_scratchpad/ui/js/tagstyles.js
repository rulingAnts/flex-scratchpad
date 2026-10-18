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
 *   folder   → notebook.json tagStyles.folder["<tab>/<path>"] (the nearest folder first, then its parents)
 *   tab      → tagStyles.tab["<dir>"]
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
  const EMPTY = () => ({ project: {}, tab: {}, folder: {}, filters: [] });
  let config = EMPTY();
  let list = [];                   // the project's tag list [{guid, name, abbr, group, fore, back}]
  let listPromise = null;
  const norm = (s) => String(s || '').trim().toLowerCase();
  const T = {
    PALETTE, BRACKETS,
    setConfig(c) { config = Object.assign(EMPTY(), c || {}); if (!Array.isArray(config.filters)) config.filters = []; },
    filters: () => config.filters,
    config: () => config,
    context: () => ({ project: '', tab: '', folder: '' }),       // app.js: the open note's place
    list: () => list,
    setList(l) { list = l || []; },
    loadList(force) {
      if (listPromise && !force) return listPromise;
      listPromise = FS.api.flex_text_tags().then((l) => { list = l || []; return list; }, () => list);
      return listPromise;
    },
  };

  /* The scopes that apply at `ctx`, most specific first. `override` stands in for one scope's
   * stored rules (an editor showing the effect of unsaved changes). */
  function scopesFor(ctx, exampleRules, override) {
    const rulesOf = (kind, key) => (override && override.kind === kind && override.key === key) ? override.rules : ((config[kind] || {})[key] || []);
    const out = [];
    if (exampleRules) out.push({ kind: 'example', key: '', label: 'this example', rules: exampleRules });
    const parts = String(ctx.folder || '').split('/').filter(Boolean);
    for (let i = parts.length; i >= 1; i--) {
      const key = (ctx.tab || '') + '/' + parts.slice(0, i).join('/');
      out.push({ kind: 'folder', key, label: 'the folder “' + parts[i - 1] + '”', rules: rulesOf('folder', key) });
    }
    out.push({ kind: 'tab', key: ctx.tab || '', label: 'the tab', rules: rulesOf('tab', ctx.tab || '') });
    const project = { kind: 'project', key: ctx.project || '', label: 'the project', rules: rulesOf('project', ctx.project || '') };
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
    const k = norm(rule.tag);
    if (k === '*') return true;
    if (k.startsWith('group:')) return !!tag.group && k.slice(6) === norm(tag.group);
    if (k.startsWith('filter:')) return false;
    return k === norm(tag.name) || (!!tag.abbr && k === norm(tag.abbr)) || (!!tag.guid && k === norm(tag.guid));
  };
  const rank = (r) => { const k = norm(r.tag); return k === '*' ? 2 : k.startsWith('group:') ? 1 : 0; };
  /* One scope's rules for a tag, in the order they are consulted: the tag's own, its group's, then `*`. */
  function rulesIn(rules, tag) {
    return (rules || []).filter((r) => r && r.enabled !== false && matches(r, tag)).sort((a, b) => rank(a) - rank(b));
  }
  const TEXT_KEYS = ['br', 'hl', 'tile', 'box', 'c'];
  const hasStyle = (r) => !!(r && (r.bg || r.fg || r.b || r.i || r.u || r.label === false || r.bar != null || TEXT_KEYS.some((k) => r[k])));
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
    const scopes = scopesFor(ctx || T.context(), spec ? R.tagRules(spec) : null, override);
    const out = { hide: false, bg: '', fg: '', b: false, i: false, u: false, label: true, br: '', hl: false, tile: false, box: false, c: '', bar: null, hideVia: null, styleVia: null };
    for (const sc of scopes) {
      for (const r of rulesIn(sc.rules, tag)) {
        if (!out.hideVia && r.hide != null) { out.hide = !!r.hide; out.hideVia = sc; }
        if (!out.styleVia && hasStyle(r)) Object.assign(out, { bg: r.bg || '', fg: r.fg || '', b: !!r.b, i: !!r.i, u: !!r.u, label: r.label !== false, br: BRACKETS[r.br] ? r.br : '', hl: !!r.hl, tile: !!r.tile, box: !!r.box, c: r.c || '', bar: r.bar == null ? null : !!r.bar, styleVia: sc });
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
    box.appendChild(el('button', { class: 'tog' + (r.label === false ? '' : ' on'), title: 'Show the tag’s abbreviation (off: a thin bar only)', onclick: () => set({ label: r.label === false ? undefined : false }) }, 'label'));
    // the TEXT itself (Seth, 2026-10-18): brackets round the span, a marker, a tile, a border, a colour
    const txt = el('div', { class: 'tag-ctl tag-ctl-text' });
    const br = el('select', { title: 'Brackets around the tagged words (and the lines under them)', 'data-test': 'tag-br' });
    br.appendChild(el('option', { value: '', selected: !r.br }, 'no brackets'));
    for (const [k, [a, z]] of Object.entries(BRACKETS)) br.appendChild(el('option', { value: k, selected: r.br === k }, a + ' word ' + z));
    br.addEventListener('change', () => set({ br: br.value || undefined }));
    txt.appendChild(br);
    for (const [k, l, ttl] of [['hl', 'highlight', 'A marker over the words'], ['tile', 'tile', 'A tinted box behind the words and their lines'], ['box', 'border', 'A border around the words and their lines']]) {
      txt.appendChild(el('button', { class: 'tog' + (r[k] ? ' on' : ''), 'data-test': 'tag-' + k, title: ttl, onclick: () => set({ [k]: r[k] ? undefined : true }) }, l));
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
    const ctx = T.context();
    FS.popover(anchor, (pop, close) => {
      const rules = R.tagRules(spec);
      const openTags = new Set();
      const write = () => { R.setTagRules(spec, rules); opts.onSpecChange && opts.onSpecChange(spec); };
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'FLEx text markup tags in this example')));
      const host = el('div', { class: 'tag-rules', 'data-test': 'tag-popover' });
      const draw = () => {
        host.innerHTML = '';
        for (const { tag, count } of tagsIn(obj)) {
          const res = resolve(tag, spec, ctx);
          const row = el('div', { class: 'tagrow', dataset: { tag: tag.name } });
          const cb = el('input', { type: 'checkbox', checked: !res.hide, 'data-test': 'tag-toggle', title: res.hide ? 'Show this tag in this example' : 'Hide this tag in this example' });
          cb.addEventListener('change', () => {
            // hidden by a broader scope → "on" here; hidden by this example → just drop that; shown → "off"
            patchRule(rules, tag.name, { hide: cb.checked ? (res.hideVia && res.hideVia.kind !== 'example' ? false : undefined) : true });
            write(); draw();
          });
          const sw = el('span', { class: 'tag-sw', style: swatchStyle(res) });
          const via = el('span', { class: 'via', 'data-test': 'tag-via' }, res.hide ? 'hidden by ' + res.hideVia.label : (res.hideVia && res.hideVia.kind === 'example' ? 'shown here · ' : '') + 'styled by ' + res.styleVia.label);
          const name = el('span', { class: 'tag-name' }, el('span', {}, tag.name + (tag.abbr && tag.abbr !== tag.name ? ' (' + tag.abbr + ')' : '') + (count > 1 ? '  ×' + count : '')), el('br'), via);
          const styleBtn = el('button', { class: 'lnk', 'data-test': 'tag-style', title: 'This example’s own look for the tag', onclick: () => { if (openTags.has(tag.name)) openTags.delete(tag.name); else openTags.add(tag.name); draw(); } }, 'Style ▾');
          const find = FS.openPicker ? el('button', { class: 'lnk', title: 'Find the other places this tag is used, and insert them', onclick: () => { close(); FS.openPicker({ mode: 'tags', tag: tag.guid }); } }, '\u{1F50D}') : null;
          row.append(cb, sw, name, styleBtn, find);
          host.appendChild(row);
          if (openTags.has(tag.name)) host.appendChild(el('div', { class: 'tag-style-box' }, controls(() => rules.find((x) => norm(x.tag) === norm(tag.name)), (patch) => { patchRule(rules, tag.name, patch); write(); draw(); }, { noShow: true })));
        }
      };
      draw();
      pop.appendChild(host);
      if ((config.filters || []).length) pop.appendChild(filterSwitches(rules, (key, patch) => { patchRule(rules, key, patch); write(); draw(); }, { inheritLabel: 'as the folder / tab says' }));
      pop.appendChild(el('hr'));
      if (rules.length) pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'tag-clear', onclick: () => { rules.splice(0); write(); close(); } }, 'Clear this example’s own tag styles'));
      const links = el('div', { class: 'row', style: { gap: '10px', flexWrap: 'wrap' } }, el('span', { class: 'lbl' }, 'Styles for'));
      for (const sc of scopesFor(ctx)) { if (sc.kind !== 'filter') links.appendChild(el('button', { class: 'lnk', 'data-test': 'tag-scope-' + sc.kind, onclick: () => { close(); dialog(sc); } }, (sc.kind === 'folder' ? sc.label.replace(/^the /, '') : sc.label.replace(/^the /, 'this ')) + '…')); }
      links.appendChild(el('button', { class: 'lnk', 'data-test': 'tag-scope-filters', onclick: () => { close(); filtersDialog(); } }, 'visual filters…'));
      pop.appendChild(links);
    });
  }

  function ctxFor(scope) {
    if (scope.kind === 'project') return { project: scope.key, tab: '', folder: '' };
    if (scope.kind === 'filter') return T.context();
    if (scope.kind === 'tab') return { project: T.context().project, tab: scope.key, folder: '' };
    const i = scope.key.indexOf('/');
    return { project: T.context().project, tab: scope.key.slice(0, i), folder: scope.key.slice(i + 1) };
  }

  /* The editor for one scope: every tag of the project (and `*`), the rule here, the effect.
   * scope = {kind: 'project'|'tab'|'folder', key, label}, or {kind: 'example', label, rules,
   * apply(rules)} for a selection of examples (app.js writes the rules into each embed). */
  async function dialog(scope) {
    await T.loadList();
    const example = scope.kind === 'example', filter = scope.kind === 'filter';
    const m = FS.modal({ title: 'FLEx tag styles — ' + scope.label });
    const stored = example ? (scope.rules || []) : filter ? (((config.filters || []).find((f) => f.id === scope.key) || {}).rules || []) : ((config[scope.kind] || {})[scope.key] || []);
    const rules = stored.map((r) => Object.assign({}, r));
    const ctx = example ? T.context() : ctxFor(scope);
    const override = { kind: scope.kind, key: scope.key, rules };
    m.body.appendChild(el('p', { class: 'small muted' }, example
      ? 'These settings are written into each selected example and win over its folder, tab and project. Leave a control as it is to keep what the broader scopes say.'
      : filter ? 'A visual filter is a named set of rules switched on and off as a whole (the ⚑ Filters button, or per tab, folder and example). Its rules apply after an example’s, folder’s and tab’s own, before the project’s.'
        : 'Rules here apply to every example in ' + scope.label + ' unless a more specific place (a folder inside it, or an example itself) says otherwise. Untick a rule to keep it without using it.'));
    const host = el('div', { class: 'tag-rules', 'data-test': 'tag-dialog' });
    m.body.appendChild(host);
    const commit = async () => {
      try { if (example) scope.apply(rules.filter((r) => Object.keys(r).some((k) => k !== 'tag' && k !== 'enabled'))); else await save(scope.kind, scope.key, rules); }
      catch (e) { FS.toast(e.message, 'error'); }
      draw();
    };
    const draw = () => {
      host.innerHTML = '';
      if (!list.length) host.appendChild(el('div', { class: 'muted small' }, 'No text markup tags have been read from the project yet. Open the project (or show an example that carries tags) and come back.'));
      if (!example && !filter) host.appendChild(filterSwitches(rules, (key, patch) => { patchRule(rules, key, patch); commit(); }));
      let group;
      const groups = [...new Set(list.map((t) => t.group).filter(Boolean))];
      // `*`, then each FLEx group as a rule of its own (`group:<name>`) followed by its tags
      const items = [{ guid: '*', name: '*', abbr: '', group: '' }];
      for (const tag of list) {
        if (tag.group !== group) { group = tag.group; if (group && groups.includes(group)) items.push({ guid: 'group:' + group, name: 'group:' + group, abbr: '', group, isGroup: true }); }
        items.push(tag);
      }
      group = undefined;
      for (const tag of items) {
        if (tag.guid !== '*' && tag.group !== group) { group = tag.group; host.appendChild(el('div', { class: 'tag-group' }, group || 'Tags')); }
        const r = rules.find((x) => norm(x.tag) === norm(tag.name)) || null;
        const row = el('div', { class: 'tagrow', dataset: { tag: tag.name } });
        if (!example) {
          const on = el('input', { type: 'checkbox', checked: !r || r.enabled !== false, disabled: !r, 'data-test': 'tag-rule-on', title: r ? 'This rule is in use (untick to keep it but not use it)' : 'No rule here yet' });
          on.addEventListener('change', () => { if (r) { r.enabled = on.checked; commit(); } });
          row.appendChild(on);
        }
        const res = tag.guid === '*' || tag.isGroup ? null : resolve(tag, example ? { extra: { tags: R.serializeTagRules(rules) } } : null, ctx, example ? null : override);
        row.appendChild(el('span', { class: 'tag-sw', style: res ? swatchStyle(res) : { background: 'var(--panel-2)' } }));
        row.appendChild(el('span', { class: 'tag-name' },
          el('span', {}, tag.guid === '*' ? 'All tags' : tag.isGroup ? 'All of “' + tag.group + '”' : tag.name + (tag.abbr && tag.abbr !== tag.name ? ' (' + tag.abbr + ')' : '')), el('br'),
          el('span', { class: 'via', 'data-test': 'tag-via' }, res ? (res.hide ? 'hidden by ' + res.hideVia.label : 'styled by ' + res.styleVia.label) : tag.isGroup ? 'one rule for the group’s tags; a tag’s own rule wins' : 'one rule for every tag; a tag’s own rule wins')));
        row.appendChild(controls(() => r, (patch) => { patchRule(rules, tag.name, patch); commit(); }, { inheritLabel: example ? 'as the folder / tab / project says' : 'as inherited' }));
        row.appendChild(r ? el('button', { class: 'icon-btn danger', 'data-test': 'tag-rule-remove', title: 'Remove this rule', onclick: () => { rules.splice(rules.indexOf(r), 1); commit(); } }, '✕') : el('span', { style: { width: '26px' } }));
        host.appendChild(row);
      }
    };
    draw();
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn primary', onclick: () => m.close() }, 'Done')));
    return m;
  }
  /* The swatch of a resolved look: its colour, and a hint of brackets / border when the text is styled. */
  function swatchStyle(res) {
    const st = { background: res.hide ? 'transparent' : (res.hl || res.tile || res.showBar ? res.bg : rgba(res.bg, 0.35)), borderStyle: res.hide ? 'dashed' : 'solid' };
    if (!res.hide && res.box) st.borderColor = res.ink;
    if (!res.hide && res.br) st.boxShadow = 'inset 0 0 0 2px ' + res.ink;
    return st;
  }

  /* ⚑ Filters: the visual filters switched on and off as a whole (Seth, 2026-10-18: "various
   * 'visual filters' based on text tags like you can do with visual filters in Logos"). */
  function filtersPopover(anchor) {
    FS.popover(anchor, (pop, close) => {
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Visual filters')));
      const list = config.filters || [];
      if (!list.length) pop.appendChild(el('div', { class: 'muted small', style: { padding: '4px 0 8px' } }, 'No visual filters yet. A filter is a named set of tag styles you switch on and off together.'));
      for (const f of list) {
        const cb = el('input', { type: 'checkbox', checked: f.enabled !== false, 'data-test': 'filter-on', dataset: { filter: f.id } });
        cb.addEventListener('change', async () => { try { await saveFilters(list.map((x) => (x.id === f.id ? Object.assign({}, x, { enabled: cb.checked }) : x))); } catch (e) { FS.toast(e.message, 'error'); } });
        pop.appendChild(el('label', { class: 'menu-item', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, cb, el('span', { style: { flex: 1 } }, f.name || 'untitled filter'), el('span', { class: 'muted small' }, (f.rules || []).length + (f.rules && f.rules.length === 1 ? ' rule' : ' rules'))));
      }
      pop.appendChild(el('hr'));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'filters-manage', onclick: () => { close(); filtersDialog(); } }, 'Manage visual filters…'));
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

  FS.tagstyles = Object.assign(T, { resolve, tagsIn, scopesFor, matches, hasStyle, textStyled, rgba, ink, patchRule, save, saveFilters, examplePopover, dialog, filtersPopover, filtersDialog, filterOn });
})();
