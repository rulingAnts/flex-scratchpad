/* tagstyles.js — FLEx TEXT MARKUP TAGS in examples: how each tag looks, and WHERE that is decided
 * (Seth, 2026-10-17: "project-scoped, folder-scoped, tab-scoped, and specific example-scoped …
 * style settings that are easy to see and adjust and remove (or disable), and the most specific
 * one takes precedent over the broadest one … kind of like highlighting filters in Logos").
 *
 * A RULE = {tag, enabled?, hide?, bg?, fg?, b?, i?, u?, label?} for one tag (by name, abbreviation
 * or GUID; `*` = every tag). Rules live at four scopes, read most specific first:
 *   example  → the embed's own `tags=` (flexref.tagRules; several examples at once from a selection)
 *   folder   → notebook.json tagStyles.folder["<tab>/<path>"] (the nearest folder first, then its parents)
 *   tab      → tagStyles.tab["<dir>"]
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
  let config = { project: {}, tab: {}, folder: {} };
  let list = [];                   // the project's tag list [{guid, name, abbr, group, fore, back}]
  let listPromise = null;
  const norm = (s) => String(s || '').trim().toLowerCase();
  const T = {
    PALETTE,
    setConfig(c) { config = Object.assign({ project: {}, tab: {}, folder: {} }, c || {}); },
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
    out.push({ kind: 'project', key: ctx.project || '', label: 'the project', rules: rulesOf('project', ctx.project || '') });
    return out;
  }
  const matches = (rule, tag) => { const k = norm(rule.tag); return k === '*' || k === norm(tag.name) || (tag.abbr && k === norm(tag.abbr)) || (tag.guid && k === norm(tag.guid)); };
  /* One scope's rules for a tag, in the order they are consulted: the tag's own rules, then `*`. */
  function rulesIn(rules, tag) {
    const live = (rules || []).filter((r) => r && r.enabled !== false && matches(r, tag));
    return live.filter((r) => norm(r.tag) !== '*').concat(live.filter((r) => norm(r.tag) === '*'));
  }
  const hasStyle = (r) => !!(r && (r.bg || r.fg || r.b || r.i || r.u || r.label === false));
  function paletteIndex(tag) {
    const i = list.findIndex((t) => t.guid === tag.guid);
    if (i >= 0) return i;
    let h = 0;
    for (const c of norm(tag.name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return h;
  }
  function resolve(tag, spec, ctx, override) {
    const scopes = scopesFor(ctx || T.context(), spec ? R.tagRules(spec) : null, override);
    const out = { hide: false, bg: '', fg: '', b: false, i: false, u: false, label: true, hideVia: null, styleVia: null };
    for (const sc of scopes) {
      for (const r of rulesIn(sc.rules, tag)) {
        if (!out.hideVia && r.hide != null) { out.hide = !!r.hide; out.hideVia = sc; }
        if (!out.styleVia && hasStyle(r)) Object.assign(out, { bg: r.bg || '', fg: r.fg || '', b: !!r.b, i: !!r.i, u: !!r.u, label: r.label !== false, styleVia: sc });
      }
      if (out.hideVia && out.styleVia) break;
    }
    if (!out.styleVia) {
      if (tag.back) { out.bg = tag.back; out.fg = tag.fore || ''; out.styleVia = { kind: 'flex', label: 'FLEx’s own colours' }; }
      else { out.bg = PALETTE[paletteIndex(tag) % PALETTE.length]; out.styleVia = { kind: 'default', label: 'the standard palette' }; }
    } else if (!out.bg) out.bg = tag.back || PALETTE[paletteIndex(tag) % PALETTE.length];
    if (!out.fg) out.fg = FS.readableTextColor ? FS.readableTextColor(out.bg) : '#1a1d21';
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
    const c = await FS.api.set_tag_styles(kind, key, rules);
    T.setConfig(c);
    FS.emit('tagstyles');
  }
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
    return box;
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
          const sw = el('span', { class: 'tag-sw', style: { background: res.hide ? 'transparent' : res.bg, borderStyle: res.hide ? 'dashed' : 'solid' } });
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
      pop.appendChild(el('hr'));
      if (rules.length) pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'tag-clear', onclick: () => { rules.splice(0); write(); close(); } }, 'Clear this example’s own tag styles'));
      const links = el('div', { class: 'row', style: { gap: '10px' } }, el('span', { class: 'lbl' }, 'Styles for'));
      for (const sc of scopesFor(ctx)) links.appendChild(el('button', { class: 'lnk', 'data-test': 'tag-scope-' + sc.kind, onclick: () => { close(); dialog(sc); } }, (sc.kind === 'folder' ? sc.label.replace(/^the /, '') : sc.label.replace(/^the /, 'this ')) + '…'));
      pop.appendChild(links);
    });
  }

  function ctxFor(scope) {
    if (scope.kind === 'project') return { project: scope.key, tab: '', folder: '' };
    if (scope.kind === 'tab') return { project: T.context().project, tab: scope.key, folder: '' };
    const i = scope.key.indexOf('/');
    return { project: T.context().project, tab: scope.key.slice(0, i), folder: scope.key.slice(i + 1) };
  }

  /* The editor for one scope: every tag of the project (and `*`), the rule here, the effect.
   * scope = {kind: 'project'|'tab'|'folder', key, label}, or {kind: 'example', label, rules,
   * apply(rules)} for a selection of examples (app.js writes the rules into each embed). */
  async function dialog(scope) {
    await T.loadList();
    const example = scope.kind === 'example';
    const m = FS.modal({ title: 'FLEx tag styles — ' + scope.label });
    const rules = (example ? (scope.rules || []) : ((config[scope.kind] || {})[scope.key] || [])).map((r) => Object.assign({}, r));
    const ctx = example ? T.context() : ctxFor(scope);
    const override = { kind: scope.kind, key: scope.key, rules };
    m.body.appendChild(el('p', { class: 'small muted' }, example
      ? 'These settings are written into each selected example and win over its folder, tab and project. Leave a control as it is to keep what the broader scopes say.'
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
      let group;
      for (const tag of [{ guid: '*', name: '*', abbr: '', group: '' }].concat(list)) {
        if (tag.guid !== '*' && tag.group !== group) { group = tag.group; host.appendChild(el('div', { class: 'tag-group' }, group || 'Tags')); }
        const r = rules.find((x) => norm(x.tag) === norm(tag.name)) || null;
        const row = el('div', { class: 'tagrow', dataset: { tag: tag.name } });
        if (!example) {
          const on = el('input', { type: 'checkbox', checked: !r || r.enabled !== false, disabled: !r, 'data-test': 'tag-rule-on', title: r ? 'This rule is in use (untick to keep it but not use it)' : 'No rule here yet' });
          on.addEventListener('change', () => { if (r) { r.enabled = on.checked; commit(); } });
          row.appendChild(on);
        }
        const res = tag.guid === '*' ? null : resolve(tag, example ? { extra: { tags: R.serializeTagRules(rules) } } : null, ctx, example ? null : override);
        row.appendChild(el('span', { class: 'tag-sw', style: res ? { background: res.hide ? 'transparent' : res.bg, borderStyle: res.hide ? 'dashed' : 'solid' } : { background: 'var(--panel-2)' } }));
        row.appendChild(el('span', { class: 'tag-name' },
          el('span', {}, tag.guid === '*' ? 'All tags' : tag.name + (tag.abbr && tag.abbr !== tag.name ? ' (' + tag.abbr + ')' : '')), el('br'),
          el('span', { class: 'via', 'data-test': 'tag-via' }, res ? (res.hide ? 'hidden by ' + res.hideVia.label : 'styled by ' + res.styleVia.label) : 'one rule for every tag; a tag’s own rule wins')));
        row.appendChild(controls(() => r, (patch) => { patchRule(rules, tag.name, patch); commit(); }, { inheritLabel: example ? 'as the folder / tab / project says' : 'as inherited' }));
        row.appendChild(r ? el('button', { class: 'icon-btn danger', 'data-test': 'tag-rule-remove', title: 'Remove this rule', onclick: () => { rules.splice(rules.indexOf(r), 1); commit(); } }, '✕') : el('span', { style: { width: '26px' } }));
        host.appendChild(row);
      }
    };
    draw();
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn primary', onclick: () => m.close() }, 'Done')));
    return m;
  }

  FS.tagstyles = Object.assign(T, { resolve, tagsIn, scopesFor, matches, hasStyle, patchRule, save, examplePopover, dialog });
})();
