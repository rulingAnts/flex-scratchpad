/* app.js — the notebook shell: rail (tabs, folders, tags, search), note list, note editor,
 * settings, keyboard shortcuts. Talks to Python only through FS.api. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el, esc } = FS;
  const $ = (id) => document.getElementById(id);

  const S = {
    init: null, notes: [], folders: {}, tags: [], config: null, flex: null,
    tab: null, folder: null, tag: null, query: '', results: null,
    ftag: null, ftags: {},          // the FLEx text markup tag the list is filtered by; {token: [note ids]} from the index
    note: null, editor: null, dirty: false, saving: false, sort: 'updated',
    openFolders: new Set(),
    // a folder (or tab) lists only its OWN notes unless this is on (Seth, 2026-10-16: "VERY
    // cluttery if every parent folder shows ALL daughter notes"); remembered on this computer
    subfolders: (() => { try { return localStorage.getItem('fs:showSubfolders') === '1'; } catch (e) { return false; } })(),
  };

  /* ------------------------------------------------------------------ boot */
  async function boot() {
    try {
      const init = await FS.api.init();
      applyInit(init);
    } catch (e) {
      document.body.innerHTML = '<div class="empty"><b>Could not start</b>' + esc(e.message) + '</div>';
      return;
    }
    wire();
    setTimeout(() => flexPrompt(false), 400);
    if (!S.notes.length) {
      try {
        const n = await FS.api.create_note(S.tab, '', 'Welcome to FLEx Scratchpad', FS.welcomeNote());
        await refreshLists();
        openNote(n.id);
      } catch (e) { /* ignore */ }
    } else {
      const last = localStorage.getItem('fs:lastNote');
      if (last && S.notes.some((n) => n.id === last)) openNote(last);
    }
  }

  function applyMarkers() {
    const hide = !!((S.config && S.config.settings) || {}).hideMarkers;
    document.body.classList.toggle('md-hide', hide);
    const btn = $('btn-markers');
    if (btn) { btn.classList.toggle('on', !hide); btn.title = (hide ? 'Markdown markers are hidden — click to show them' : 'Markdown markers are shown — click to hide them') + ' (**bold**, # heading, - list)'; }
    if (FS.editor && FS.editor.revealMarkers) FS.editor.revealMarkers();
  }
  /* Sticky headings (Seth, 2026-10-17): on unless turned off in Settings or the H ▾ menu. */
  function stickyOn() { return (S.config && S.config.settings || {}).stickyHeadings !== false; }
  function gapBarOn() { return (S.config && S.config.settings || {}).gapBar !== false; }
  function applyGapBar() { if (S.editor) S.editor.gapBarOn = gapBarOn(); }
  function applySticky() { if (S.editor) S.editor.setSticky(stickyOn()); }
  async function toggleSticky() {
    try { S.config.settings = await FS.api.set_setting('stickyHeadings', !stickyOn()); } catch (e) { FS.toast(e.message, 'error'); return; }
    applySticky();
  }
  async function toggleMarkers() {
    const hide = !((S.config.settings || {}).hideMarkers);
    try { S.config.settings = await FS.api.set_setting('hideMarkers', hide); } catch (e) { FS.toast(e.message, 'error'); return; }
    applyMarkers();
    FS.toast(hide ? 'Markdown markers hidden' : 'Markdown markers shown');
  }
  // FLEx tag styles (tagstyles.js) resolve against the open note's place; a change anywhere redraws
  FS.tagstyles.context = () => ({ project: (S.flex && S.flex.project) || '', tab: S.note ? S.note.tab : (S.tab || ''), folder: S.note ? (S.note.folder || '') : (S.folder || ''), note: S.note ? S.note.id : '' });
  FS.on('tagstyles', () => { if (isCollection()) { if (S.coll) S.coll.render(); } else if (isChartNote()) { if (S.chartNote) S.chartNote.drawChart(); } else if (S.editor) S.editor.renderAll(); renderRail(); });
  function applyInit(init) {
    S.init = init; S.config = init.config; S.notes = init.notes; S.folders = init.folders; S.tags = init.tags; S.flex = init.flex;
    FS.tagstyles.setConfig(S.config.tagStyles);
    if (S.flex && S.flex.open) { FS.tagstyles.loadList(true).then(renderRail); FS.tagstyles.loadMarkers(true); }
    loadFtags();
    applyMarkers();
    applySticky();
    applyGapBar();
    if (!S.tab || !S.config.tabs.some((t) => t.dir === S.tab)) S.tab = (S.config.tabs[0] || {}).dir || null;
    renderRail();
    renderList();
    renderFlexPill();
    FS.backup.refreshPill();
  }
  function openBackup() {
    FS.backup.open({ onOpenNotebook: async (path) => { try { const r = await FS.api.open_notebook(path); S.note = null; $('editor-pane').classList.add('no-note'); applyInit(r); FS.toast('Opened ' + path, 'ok'); } catch (e) { FS.toast(e.message, 'error'); } } });
  }

  async function refreshLists() {
    const [notes, folders, tags] = await Promise.all([FS.api.list_notes(), FS.api.folders(), FS.api.tags()]);
    S.notes = notes; S.folders = folders; S.tags = tags;
    loadFtags();
    renderRail();
    if (S.query || S.ftag) await runSearch(); else renderList();
  }
  /* The FLEx text markup tags on the notes' examples (Seth, 2026-10-18: "filter notes and specific
   * flex objects in notes by text markup tags"): {token: [note ids]} from the search index. */
  let ftagsReq = 0;
  async function loadFtags() {
    if (!FS.api.flex_tags_used) return;
    const n = ++ftagsReq;
    try { const m = await FS.api.flex_tags_used(); if (n === ftagsReq) { S.ftags = m || {}; renderRail(); } } catch (e) { /* no index yet */ }
  }
  const ftagToken = (name) => String(name || '').toLowerCase().replace(/ /g, '_');
  /* The rail's rows: one per tag of the project's list that the notes of this tab use (its name
   * and abbreviation tokens merged), plus tokens the list does not know, with note counts. */
  function ftagRows() {
    const inTab = new Set(S.notes.filter((n) => n.tab === S.tab).map((n) => n.id));
    const rows = new Map();
    for (const [tok, ids] of Object.entries(S.ftags || {})) {
      const here = ids.filter((id) => inTab.has(id));
      if (!here.length) continue;
      const item = FS.tagstyles.list().find((t) => ftagToken(t.name) === tok || ftagToken(t.abbr) === tok);
      const key = item ? item.guid : tok;
      const row = rows.get(key) || { key, name: item ? item.name : tok.replace(/_/g, ' '), item, tokens: [], ids: new Set() };
      row.tokens.push(tok);
      here.forEach((id) => row.ids.add(id));
      rows.set(key, row);
    }
    return [...rows.values()].sort((a, b) => b.ids.size - a.ids.size || a.name.localeCompare(b.name));
  }
  function renderFtags() {
    const sec = $('ftags-section'), host = $('ftags');
    if (!sec || !host) return;
    const rows = ftagRows();
    const filters = (FS.tagstyles.filters && FS.tagstyles.filters()) || [];
    const was = sec.hidden;
    sec.hidden = !rows.length && !filters.length && !(S.flex && S.flex.open);
    if (was !== sec.hidden) applyRail();
    host.innerHTML = '';
    const leaf = (t) => {
      const r = t._row, active = S.ftag && r.tokens.includes(S.ftag);
      const item = el('div', { class: 'tag-item ftag-item' + (active ? ' active' : ''), 'data-test': 'ftag', dataset: { tag: r.name }, title: (t.path || []).join(' › ') },
        el('span', { class: 'mark' }, '\u2691'), el('span', {}, r.name), el('span', { class: 'count' }, String(r.ids.size)));
      item.addEventListener('click', () => { setFtag(active ? null : r.tokens[0]); });
      return item;
    };
    // in FLEx's own hierarchy, the groups fold-able (unknown tokens at the top level)
    const items = rows.map((r) => Object.assign({}, r.item || { guid: r.key, name: r.name, path: [] }, { _row: r }));
    if (FS.tagstyles.renderTagTree) { const tree = el('div'); FS.tagstyles.renderTagTree(tree, items, { leaf }); host.appendChild(tree); }
    else for (const t of items) host.appendChild(leaf(t));
    if (!rows.length && !sec.hidden) host.appendChild(el('div', { class: 'muted small', style: { padding: '2px 10px' } }, 'No note in this tab shows a tagged example yet.'));
  }
  function setFtag(tok) {
    S.ftag = tok || null;
    renderRail();
    runSearch();
    applyTagFocus();
  }
  /* In the open note: the examples that carry the rail's tag stand out, the others step back,
   * and a bar over the note walks through them. */
  let focusReq = 0;
  function applyTagFocus() {
    const bar = $('tagfocus');
    // every FLEx text example in the note: drawn in full, folded to a chip, or a chip in a line of text
    const objs = [...document.querySelectorAll('#editor .text-obj, #editor .flex-collapsed.kind-text, #editor .md-embed[data-src*="flex:text"], #collection .text-obj, #collection .flex-collapsed.kind-text')];
    if (!S.ftag || !S.note) { if (bar) { bar.hidden = true; } objs.forEach((o) => o.classList.remove('tag-hit', 'tag-miss')); return; }
    const want = S.ftag;
    const row = ftagRows().find((r) => r.tokens.includes(want));
    const toks = new Set(row ? row.tokens : [want]);
    let hits = 0;
    for (const o of objs) {
      const hit = (o.dataset.tags || '').split('\n').some((n) => toks.has(ftagToken(n)));
      o.classList.toggle('tag-hit', hit); o.classList.toggle('tag-miss', !hit);
      if (hit) hits++;
    }
    if (!bar) return;
    bar.hidden = false;
    bar.innerHTML = '';
    const go = (dir) => {
      const hitEls = objs.filter((o) => o.classList.contains('tag-hit'));
      if (!hitEls.length) return;
      const sc = document.getElementById(isCollection() ? 'collection' : isChartNote() ? 'chartnote' : 'editor');
      const top = sc.getBoundingClientRect().top + 40;
      let i = dir > 0 ? hitEls.findIndex((o) => o.getBoundingClientRect().top > top + 1) : hitEls.map((o) => o.getBoundingClientRect().top < top - 1).lastIndexOf(true);
      if (i < 0) i = dir > 0 ? 0 : hitEls.length - 1;
      hitEls[i].scrollIntoView({ block: 'start', behavior: 'smooth' });
    };
    bar.append(el('span', {}, '\u2691 '), el('b', {}, row ? row.name : want.replace(/_/g, ' ')),
      el('span', { 'data-test': 'tagfocus-count' }, hits + ' of ' + objs.length + (objs.length === 1 ? ' example' : ' examples') + ' in this note'),
      el('button', { class: 'icon-btn', title: 'Previous tagged example', onclick: () => go(-1) }, '\u25b2'), el('button', { class: 'icon-btn', title: 'Next tagged example', onclick: () => go(1) }, '\u25bc'),
      el('span', { class: 'spacer' }), el('button', { class: 'lnk', 'data-test': 'tagfocus-clear', onclick: () => setFtag(null) }, 'Show all notes and examples'));
  }
  // examples are drawn asynchronously: re-apply the focus whenever the note's objects change
  // (watching the note and the collection only — the bar itself lives beside them)
  if (typeof MutationObserver === 'function') {
    const mo = new MutationObserver(() => { if (!S.ftag || focusReq) return; focusReq = requestAnimationFrame(() => { focusReq = 0; applyTagFocus(); }); });
    document.addEventListener('DOMContentLoaded', () => { for (const id of ['editor', 'collection']) { const h = $(id); if (h) mo.observe(h, { childList: true, subtree: true }); } });
  }

  /* ------------------------------------------------------------------ rail */
  function renderRail() {
    const tabs = $('tabs');
    tabs.innerHTML = '';
    for (const t of S.config.tabs) {
      const count = S.notes.filter((n) => n.tab === t.dir).length;
      const item = el('div', { class: 'tab-item' + (S.tab === t.dir && !S.query ? ' active' : ''), draggable: 'true', dataset: { dir: t.dir } },
        el('span', { class: 'dot', style: { background: t.color } }), el('span', { class: 'label' }, t.name), el('span', { class: 'count' }, String(count)));
      item.addEventListener('click', () => { S.tab = t.dir; S.folder = null; S.tag = null; S.ftag = null; clearSearch(); renderRail(); renderList(); applyTagFocus(); });
      item.addEventListener('contextmenu', (e) => { e.preventDefault(); tabMenu(item, t); });
      item.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/tab', t.dir); e.dataTransfer.effectAllowed = 'move'; });
      item.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/tab') || e.dataTransfer.types.includes('text/note')) { e.preventDefault(); item.style.outline = '2px solid var(--accent)'; } });
      item.addEventListener('dragleave', () => { item.style.outline = ''; });
      item.addEventListener('drop', async (e) => {
        e.preventDefault(); item.style.outline = '';
        const noteId = e.dataTransfer.getData('text/note');
        if (noteId) { await FS.api.move_note(noteId, t.dir, ''); await refreshLists(); if (S.note && S.note.id === noteId) { S.note.tab = t.dir; S.note.folder = ''; renderNoteMeta(); } return; }
        const from = e.dataTransfer.getData('text/tab');
        if (from && from !== t.dir) { const dirs = S.config.tabs.map((x) => x.dir); dirs.splice(dirs.indexOf(from), 1); dirs.splice(dirs.indexOf(t.dir), 0, from); S.config.tabs = await FS.api.reorder_tabs(dirs); renderRail(); }
      });
      tabs.appendChild(item);
    }
    // folders of the active tab
    const folders = $('folders');
    folders.innerHTML = '';
    const list = (S.folders[S.tab] || []);
    const tree = {};
    for (const p of list) { let cur = tree; for (const part of p.split('/')) cur = cur[part] = cur[part] || {}; }
    const countIn = (path) => S.notes.filter((n) => n.tab === S.tab && (n.folder === path || n.folder.startsWith(path + '/'))).length;
    const walk = (node, prefix, depth) => {
      for (const name of Object.keys(node).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))) {
        const path = prefix ? prefix + '/' + name : name;
        const kids = Object.keys(node[name]).length;
        const open = S.openFolders.has(path) || (S.folder && S.folder.startsWith(path + '/'));
        const item = el('div', { class: 'folder-item' + (S.folder === path && !S.query ? ' active' : ''), style: { '--depth': depth }, dataset: { path } },
          el('span', { class: 'chev' + (open ? ' open' : ''), onclick: (e) => { e.stopPropagation(); S.openFolders.has(path) ? S.openFolders.delete(path) : S.openFolders.add(path); renderRail(); } }, kids ? '▶' : ''),
          el('span', {}, '📁'), el('span', { class: 'label' }, name), el('span', { class: 'count' }, String(countIn(path))));
        item.addEventListener('click', () => { S.folder = path; S.tag = null; clearSearch(); renderRail(); renderList(); });
        item.addEventListener('contextmenu', (e) => { e.preventDefault(); folderMenu(item, path); });
        item.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/note')) { e.preventDefault(); item.style.outline = '2px solid var(--accent)'; } });
        item.addEventListener('dragleave', () => { item.style.outline = ''; });
        item.addEventListener('drop', async (e) => { e.preventDefault(); item.style.outline = ''; const id = e.dataTransfer.getData('text/note'); if (id) { await FS.api.move_note(id, S.tab, path); await refreshLists(); if (S.note && S.note.id === id) { S.note.folder = path; renderNoteMeta(); } } });
        folders.appendChild(item);
        if (open && kids) walk(node[name], path, depth + 1);
      }
    };
    walk(tree, '', 0);
    // tags
    const tags = $('tags');
    tags.innerHTML = '';
    for (const t of S.tags.slice().sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))) {
      const item = el('div', { class: 'tag-item' + (S.tag === t.name ? ' active' : '') },
        el('span', { class: 'chip', style: { background: t.color, color: FS.readableTextColor(t.color) } }, '#' + t.name), el('span', { class: 'count' }, String(t.count)));
      item.addEventListener('click', () => { S.tag = S.tag === t.name ? null : t.name; renderRail(); if (S.query || S.ftag) runSearch(); else renderList(); });
      tags.appendChild(item);
    }
    renderFtags();
  }

  function tabMenu(anchor, t) {
    FS.popover(anchor, (pop, close) => {
      const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
      item('Rename…', async () => { const name = prompt('Tab name', t.name); if (name && name.trim()) { await FS.api.update_tab(t.dir, { name: name.trim() }); applyInit(await FS.api.init()); } });
      const colors = el('div', { class: 'color-row', style: { padding: '4px 8px' } });
      for (const c of ['#2f6fdb', '#0f766e', '#b45309', '#7c3aed', '#be185d', '#4d7c0f', '#0e7490', '#9f1239', '#6b7280']) colors.appendChild(el('button', { class: 'sw' + (t.color === c ? ' on' : ''), style: { background: c }, onclick: async () => { await FS.api.update_tab(t.dir, { color: c }); close(); applyInit(await FS.api.init()); } }));
      pop.appendChild(colors);
      pop.appendChild(el('hr'));
      item('New folder in this tab…', () => newFolder(t.dir));
      item('Texts used in this tab\u2026', () => textsUsedDialog({ tab: t.dir, folder: '' }, 'in the tab \u201c' + t.name + '\u201d'), 'texts-used-tab');
      item('FLEx tag styles for this tab\u2026', () => FS.tagstyles.dialog({ kind: 'tab', key: t.dir, label: 'the tab \u201c' + t.name + '\u201d' }), 'tag-styles-tab');
      item('Delete tab', async () => { if (!confirm('Delete the tab “' + t.name + '”? It must be empty.')) return; try { await FS.api.delete_tab(t.dir); S.tab = null; applyInit(await FS.api.init()); } catch (e) { FS.toast(e.message, 'error'); } }, 'danger');
    });
  }
  function folderMenu(anchor, path) {
    FS.popover(anchor, (pop, close) => {
      const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
      item('New subfolder…', () => newFolder(S.tab, path));
      item('Texts used in this folder\u2026', () => textsUsedDialog({ tab: S.tab, folder: path }, 'in \u201c' + path.split('/').pop() + '\u201d and its subfolders'), 'texts-used-folder');
      item('FLEx tag styles for this folder\u2026', () => FS.tagstyles.dialog({ kind: 'folder', key: S.tab + '/' + path, label: 'the folder \u201c' + path.split('/').pop() + '\u201d' }), 'tag-styles-folder');
      item('Rename…', async () => { const name = prompt('Folder name', path.split('/').pop()); if (name && name.trim()) { try { const np = await FS.api.rename_folder(S.tab, path, name.trim()); if (S.folder === path) S.folder = np; await refreshLists(); } catch (e) { FS.toast(e.message, 'error'); } } });
      item('Delete folder', async () => { try { await FS.api.delete_folder(S.tab, path); if (S.folder === path) S.folder = null; await refreshLists(); } catch (e) { FS.toast(e.message, 'error'); } }, 'danger');
    });
  }
  async function newFolder(tab, parent) {
    const name = prompt(parent ? 'New folder inside ' + parent : 'New folder name');
    if (!name || !name.trim()) return;
    try { const p = await FS.api.create_folder(tab || S.tab, (parent ? parent + '/' : '') + name.trim()); S.openFolders.add(parent || ''); S.folder = p; await refreshLists(); } catch (e) { FS.toast(e.message, 'error'); }
  }

  /* ------------------------------------------------------------------ FLEx connection state
   * One assessment of the connection, used by the pill, the banner, the first-run prompt and
   * Settings (Seth, 2026-10-13: "make it obvious for new users how to pair a FLEx project").
   *   level: 'ok' | 'warn' | 'err' | 'none'  (none = nothing linked yet) */
  const SHARING_FIX = ['In FieldWorks open the project.', 'File → Project Management → FieldWorks Project Properties… → Sharing tab.', 'Tick “Share project contents with programs on this computer” and click OK.', 'Back here, press Retry.'];
  function flexState() {
    const f = S.flex || {};
    const src = f.backend === 'demo' ? ' (demo)' : f.backend === 'flextext' ? ' (.flextext)' : '';
    if (f.open) {
      if (f.shared === false) {
        return { level: 'warn', short: 'FLEx: ' + f.project + ' — sharing is off', title: 'This project is not shared with other programs',
          text: 'The Scratchpad can read “' + f.project + '” right now' + (f.flexHasItOpen === false ? ' because FieldWorks does not have it open' : '') + ', but as soon as FieldWorks opens this project without sharing, reads here will fail with “locked by FieldWorks”.', fix: SHARING_FIX };
      }
      return { level: 'ok', short: 'FLEx: ' + (f.project || '') + src, title: 'Connected to ' + f.project + src,
        text: f.backend === 'lcm' ? ('Reading the project directly' + (f.shared ? '; sharing is on, so FieldWorks and the Scratchpad can both have it open.' : '.')) : (f.backend === 'demo' ? 'The built-in demo project (for trying things out).' : 'A .flextext export file: texts only, no lexicon.'), fix: null };
    }
    if (!f.configured) return { level: 'none', short: 'FLEx: no project linked', title: 'No FieldWorks project is linked yet', text: 'Link one to insert entries and interlinear examples into your notes. The notebook works without it, but FLEx objects stay as they were last seen.', fix: null };
    if (f.errorCode === 'locked') return { level: 'err', short: 'FLEx: ' + f.project + ' is locked', title: 'FieldWorks has “' + f.project + '” open without sharing', text: f.error, fix: SHARING_FIX };
    if (f.errorCode === 'no-flexicon') return { level: 'err', short: 'FLEx: flexicon not installed', title: 'The FieldWorks link is not installed', text: f.error, fix: ['On the Windows machine with FieldWorks, run:  pip install "flex-scratchpad[flex]"', 'Restart the Scratchpad and press Retry.'] };
    return { level: 'err', short: 'FLEx: ' + (f.error || 'not reachable'), title: 'The project “' + (f.project || f.flextextPath || '') + '” could not be opened', text: f.error || 'Unknown error', fix: f.errorCode === 'migration' ? ['Open the project in FieldWorks once (it migrates the data).', 'Back here, press Retry.'] : f.errorCode === 'not-found' ? ['Check the project name in Settings, or pick it from the list.'] : null };
  }
  function renderFlexPill() {
    const pill = $('flex-pill');
    const st = flexState();
    pill.classList.toggle('on', st.level === 'ok');
    pill.classList.toggle('warn', st.level === 'warn');
    pill.classList.toggle('err', st.level === 'err' || st.level === 'none');
    pill.querySelector('.label').textContent = st.short;
    pill.classList.remove('busy');
    if (!pill.querySelector('.warn-icon')) pill.appendChild(el('span', { class: 'warn-icon', title: 'There is a problem — click for details' }, '!'));
    pill.title = st.title + (st.level === 'ok' ? '' : ' — click for details');
    renderFlexBanner(st);
  }
  function renderFlexBanner(st) {
    const b = $('flex-banner');
    if (!b) return;
    const hidden = sessionStorage.getItem('fs:flexBannerHidden') === '1';
    const show = (st.level === 'none' || st.level === 'err') && !hidden;
    b.hidden = !show;
    if (!show) return;
    b.classList.toggle('err', st.level === 'err');
    b.querySelector('.text').textContent = st.title + (st.level === 'err' && st.fix ? ' — ' + st.fix[0] : '');
    $('flex-banner-fix').textContent = st.level === 'none' ? 'Link a project…' : 'Open Settings…';
  }
  async function retryFlex() {
    try { S.flex = await FS.api.flex_open(); } catch (e) { FS.toast(e.message, 'error'); return; }
    renderFlexPill(); FS.interlinear.invalidate();
    if (S.flex.open) { FS.toast('Connected to ' + S.flex.project, 'ok'); if (S.note) ensureEditor().load(S.note.body); }
    else FS.toast(S.flex.error || 'Still not connected', 'error');
  }
  /* The pill explains itself: state, what it means, how to fix it. */
  function flexStatusPopover(anchor) {
    const st = flexState();
    FS.popover(anchor, (pop, close) => {
      pop.classList.add('flex-explain');
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, (st.level === 'warn' ? '⚠ ' : st.level === 'err' ? '✖ ' : st.level === 'none' ? '○ ' : '● ') + st.title)));
      pop.appendChild(el('div', { class: 'row small' }, st.text || ''));
      if (st.fix) pop.appendChild(el('div', { class: 'fix' }, el('b', {}, 'How to fix it'), el('ol', {}, ...st.fix.map((x) => el('li', {}, x)))));
      const row = el('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '8px' } });
      if (st.level !== 'ok') row.appendChild(el('button', { class: 'btn', onclick: () => { close(); retryFlex(); } }, 'Retry'));
      row.appendChild(el('button', { class: 'btn primary', onclick: () => { close(); openSettings(); } }, st.level === 'none' ? 'Link a project…' : 'Settings…'));
      pop.appendChild(row);
    });
  }
  /* First run, or a linked project that cannot be reached: ask, rather than leaving it to the
   * pill. Shown once per start while the state stays that way. */
  function flexPrompt(force) {
    const st = flexState();
    if (st.level === 'ok' || st.level === 'warn') return false;
    if (!force && sessionStorage.getItem('fs:flexPromptShown') === '1') return false;
    sessionStorage.setItem('fs:flexPromptShown', '1');
    const m = FS.modal({ title: st.level === 'none' ? 'Link a FieldWorks project?' : 'FieldWorks project not reachable' });
    m.body.appendChild(el('p', {}, st.level === 'none' ? 'FLEx Scratchpad shows live entries and interlinear examples from a FieldWorks project inside your notes. No project is linked yet.' : st.title + '.'));
    if (st.level !== 'none') m.body.appendChild(el('p', { class: 'small muted' }, st.text));
    if (st.fix) m.body.appendChild(el('div', { class: 'fix flex-explain' }, el('b', {}, 'How to fix it'), el('ol', {}, ...st.fix.map((x) => el('li', {}, x)))));
    const row = el('div', { class: 'btn-row' });
    row.appendChild(el('button', { class: 'btn', onclick: () => m.close() }, 'Not now'));
    if (st.level !== 'none') row.appendChild(el('button', { class: 'btn', onclick: () => { m.close(); retryFlex(); } }, 'Retry'));
    if (st.level === 'none') row.appendChild(el('button', { class: 'btn', onclick: async () => { m.close(); try { S.flex = await FS.api.flex_configure('demo', 'Kalu Demo', ''); renderFlexPill(); FS.toast('Demo project linked', 'ok'); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Try the demo project'));
    row.appendChild(el('button', { class: 'btn primary', onclick: () => { m.close(); openSettings(); } }, st.level === 'none' ? 'Choose a project…' : 'Open Settings…'));
    m.body.appendChild(row);
    return true;
  }

  /* ------------------------------------------------------------------ note list */
  function visibleNotes() {
    if (S.results) return S.results;
    let list = S.notes.filter((n) => n.tab === S.tab);
    // its own notes, or the whole tree under it; a tag looks through the whole tab regardless
    const here = S.folder || '';
    if (S.subfolders || S.tag) { if (here) list = list.filter((n) => n.folder === here || n.folder.startsWith(here + '/')); }
    else list = list.filter((n) => (n.folder || '') === here);
    if (S.tag) list = list.filter((n) => n.tags.includes(S.tag) || (n.inlineTags || []).includes(S.tag));
    if (S.sort === 'title') list = list.slice().sort((a, b) => (b.pinned - a.pinned) || a.title.localeCompare(b.title));
    else if (S.sort === 'created') list = list.slice().sort((a, b) => (b.pinned - a.pinned) || b.created.localeCompare(a.created));
    return list;
  }
  /* Notes in the folders below the current place (for the checkbox and the empty list). */
  function notesBelow() {
    const here = S.folder || '';
    return S.notes.filter((n) => n.tab === S.tab && (n.folder || '') !== here && (!here || (n.folder || '').startsWith(here + '/')));
  }
  function setSubfolders(on) {
    S.subfolders = !!on;
    try { localStorage.setItem('fs:showSubfolders', on ? '1' : '0'); } catch (e) { /* a convenience only */ }
    renderList();
  }
  function renderList() {
    const host = $('notes');
    host.innerHTML = '';
    const list = visibleNotes();
    const below = S.results || S.tag ? [] : notesBelow();
    const hasSub = !S.results && !S.tag && (S.folders[S.tab] || []).some((f) => !S.folder || f.startsWith(S.folder + '/'));
    $('list-subfolders').hidden = !hasSub;
    $('chk-subfolders').checked = S.subfolders;
    const tabInfo = S.config.tabs.find((t) => t.dir === S.tab) || {};
    $('list-title').textContent = S.results ? 'Search results' : (S.folder ? S.folder.split('/').pop() : (tabInfo.name || 'Notes'));
    $('list-sub').textContent = S.results ? list.length + ' match' + (list.length === 1 ? '' : 'es') + (S.ftag && !S.query ? ' with \u2691 ' + ((ftagRows().find((r) => r.tokens.includes(S.ftag)) || {}).name || S.ftag) : '') : [S.folder ? tabInfo.name + ' / ' + S.folder : '', S.tag ? '#' + S.tag : ''].filter(Boolean).join('  ·  ');
    if (!list.length && !S.results && !S.subfolders && below.length) {
      host.appendChild(el('div', { class: 'empty' }, el('b', {}, S.folder ? 'No notes directly in this folder' : 'No notes at the top of this tab'),
        el('button', { class: 'btn', 'data-test': 'show-below', onclick: () => setSubfolders(true) }, 'Show the ' + below.length + ' note' + (below.length === 1 ? '' : 's') + ' in its subfolders')));
      return;
    }
    if (!list.length) { host.appendChild(el('div', { class: 'empty' }, el('b', {}, S.results ? 'Nothing found' : 'No notes here'), S.results ? 'Try other words, or clear the tag filter.' : 'Press Ctrl+N to write one.')); return; }
    for (const n of list) {
      const card = el('div', { class: 'note-card' + (S.note && S.note.id === n.id ? ' active' : ''), draggable: 'true', dataset: { id: n.id } });
      card.appendChild(el('div', { class: 't' }, n.pinned ? el('span', { class: 'pin' }, '📌') : null, n.kind === 'examples' ? el('span', { class: 'kind-badge', title: 'Example collection: exports as a FLEx text' }, 'IGT') : n.kind === 'chart' ? el('span', { class: 'kind-badge chart', title: 'Chart note: one FieldWorks text chart with your columns and styles' }, 'Chart') : null, n.title || 'Untitled'));
      const x = el('div', { class: 'x' });
      if (n.snippet != null) x.innerHTML = markSnippet(n.snippet, n.snippetMarks); else x.textContent = n.kind === 'examples' ? (n.exampleCount || 0) + ' example' + (n.exampleCount === 1 ? '' : 's') : (n.excerpt || '');
      card.appendChild(x);
      const meta = el('div', { class: 'm' }, FS.relTime(n.updated));
      if (S.results || S.tag) meta.appendChild(el('span', {}, '· ' + (S.config.tabs.find((t) => t.dir === n.tab) || {}).name + (n.folder ? ' / ' + n.folder : '')));
      else if (S.subfolders && (n.folder || '') !== (S.folder || '')) meta.appendChild(el('span', { class: 'sub-loc', title: 'In a subfolder' }, '· ' + (S.folder ? (n.folder || '').slice(S.folder.length + 1) : n.folder)));
      for (const t of n.tags.slice(0, 4)) meta.appendChild(el('span', { class: 'chip', style: tagStyle(t) }, '#' + t));
      card.appendChild(meta);
      card.addEventListener('click', () => openNote(n.id));
      card.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/note', n.id); e.dataTransfer.effectAllowed = 'move'; });
      card.addEventListener('contextmenu', (e) => { e.preventDefault(); noteMenu(card, n); });
      host.appendChild(card);
    }
  }
  function markSnippet(s, marks) {
    if (!marks || !marks.length) return esc(s);
    let out = '', pos = 0;
    for (const [a, b] of marks) { if (a < pos) continue; out += esc(s.slice(pos, a)) + '<mark>' + esc(s.slice(a, b)) + '</mark>'; pos = b; }
    return out + esc(s.slice(pos));
  }
  function tagStyle(name) {
    const t = S.tags.find((x) => x.name === name);
    const c = t ? t.color : '#6b7280';
    return { background: c, color: FS.readableTextColor(c) };
  }

  /* ------------------------------------------------------------------ search */
  const runSearch = FS.debounce(async () => {
    const q = $('search').value.trim();
    S.query = q;
    // the rail's FLEx tag is a `tagged:` term of the search (notebook.parse_query)
    const full = [q, S.ftag ? 'tagged:' + S.ftag : ''].filter(Boolean).join(' ');
    if (!full && !S.tag) { S.results = null; renderRail(); renderList(); return; }
    if (!full) { S.results = null; renderList(); return; }
    try {
      S.results = await FS.api.search(full, { tags: S.tag ? [S.tag] : [] });
      renderRail(); renderList();
      if (q) try { const recent = JSON.parse(localStorage.getItem('fs:recentSearches') || '[]').filter((x) => x !== q); recent.unshift(q); localStorage.setItem('fs:recentSearches', JSON.stringify(recent.slice(0, 10))); } catch (e) { /* ignore */ }
    } catch (e) { FS.toast(e.message, 'error'); }
  }, 150);
  function clearSearch() { S.query = ''; S.results = null; $('search').value = ''; }

  /* ------------------------------------------------------------------ editor */
  function ensureEditor() {
    if (S.editor) return S.editor;
    S.editor = new FS.Editor($('editor'), {
      onChange: (md) => { if (!S.note || isSpecial()) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      openLink: openLink,
      onPasteLink: (text, insert) => FS.picker.pasteChooser(text, insert),
      onPasteLocate: (text, insert, fallback) => (S.flex && S.flex.open) ? FS.picker.locateChooser(text, insert, fallback) : fallback(),
      onPasteFiles: async (files, insert) => {
        // a screenshot (a picture with no file behind it) is shown in the note, as before; a copied
        // FILE becomes an attachment chip, copied into the notebook (Seth, 2026-10-17)
        const shot = files.length === 1 && /^image\//.test(files[0].type) && (!files[0].name || /^image\.\w+$/i.test(files[0].name));
        if (!shot) { const srcs = await FS.files.fromFiles(files, false); if (srcs.length) insert(srcs.join(' ')); return; }
        const file = files[0];
        const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(file); });
        try { const r = await FS.api.save_attachment(file.name || 'pasted.png', b64); insert('![' + (file.name || 'image') + '](' + (r.fileUrl || b64) + ')'); } catch (e) { FS.toast(e.message, 'error'); }
      },
      onAttach: () => attachFiles(false),
      onSlash: (body, b) => slashMenu(body, b),
      onInsertFlex: () => insertFlex(),
    });
    window.__fsEditor = S.editor;        // for the tests and the console
    applySticky();
    applyGapBar();
    return S.editor;
  }
  async function openNote(id) {
    if (S.note && S.note.id === id) return;
    await flushSave();
    let n;
    try { n = await FS.api.get_note(id); } catch (e) { FS.toast(e.message, 'error'); return; }
    n.body = FS.flexcopy.strip(n.body || '', n.id);   // the plain-text copies of its FLEx objects are never shown (flexcopy.js)
    S.note = n; S.dirty = false;
    localStorage.setItem('fs:lastNote', id);
    $('editor-pane').classList.remove('no-note');
    $('note-title').value = n.title || '';
    const coll = n.kind === 'examples', cn = n.kind === 'chart';
    $('editor-pane').classList.toggle('is-collection', coll || cn);
    $('editor').hidden = coll || cn; $('collection').hidden = !coll; $('chartnote').hidden = !cn;
    $('note-title').placeholder = coll ? 'Untitled collection' : cn ? 'Untitled chart note' : 'Untitled note';
    closeFind();
    if (coll) { ensureEditor().load(''); ensureCollection().load(n.body || ''); }
    else if (cn) { ensureEditor().load(''); ensureChartNote().load(n.body || ''); }
    else ensureEditor().load(n.body || '');
    renderNoteMeta();
    renderList();
    $('save-state').textContent = '';
    if (!n.title) $('note-title').focus(); else if (!coll && !cn) S.editor.focusBlock(0, 0);
  }
  /* Example collections (Seth, 2026-10-16): a note that is JUST interlinear examples, the one
   * kind of note that exports as a FLEx text. collection.js draws it; this wires it in. */
  function isCollection() { return !!(S.note && S.note.kind === 'examples'); }
  /* CHART NOTES (Seth, 2026-10-18): a note that is one FieldWorks text chart with the user's own
   * columns and styles; chartnote.js draws it. `isSpecial` = the block editor is not the view. */
  function isChartNote() { return !!(S.note && S.note.kind === 'chart'); }
  function isSpecial() { return isCollection() || isChartNote(); }
  function ensureChartNote() {
    if (S.chartNote) return S.chartNote;
    S.chartNote = new FS.ChartNote($('chartnote'), {
      onChange: (md) => { if (!isChartNote()) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      chartGuid: () => (S.note && S.note.chart) || '',
      // another chart for this note: the front matter first (the API checks the chart exists), then the body
      changeChart: async (guid) => { const n = await FS.api.set_note_chart(S.note.id, guid); S.note.chart = n.chart; },
    });
    window.__fsChartNote = S.chartNote;
    return S.chartNote;
  }
  /* A new chart note on a chart (from the New menu's dialog, or a chart embed's ⋯ menu with its
   * view carried over). */
  async function newChartNote(guid, view) {
    await flushSave();
    try {
      const n = await FS.api.create_chart_note(S.tab, S.folder || '', '', guid, view || '');
      clearSearch();
      await refreshLists();
      await openNote(n.id);
      return n;
    } catch (e) { FS.toast(e.message, 'error'); return null; }
  }
  FS.newChartNote = newChartNote;
  function newChartNoteDialog() {
    chartChooser({ title: 'New chart note', intro: 'A chart note shows one FieldWorks text chart (Texts & Words › Text Chart) with your own columns — choice lists, notes, rules — and your styling of its words, cells, rows and columns.', test: 'pick-chart-note', onPick: (c) => newChartNote(c.guid, '') });
  }
  /* The project's charts to pick one from: a new chart note, or another chart for a chart object /
   * chart note (Seth, 2026-10-18: "change the text chart source for a text chart note or a text
   * chart object, just like I can for interlinear objects"). */
  function chartChooser(o) {
    const m = FS.modal({ title: o.title || 'Pick a chart' });
    const search = el('input', { type: 'text', placeholder: 'Search charts by text or name…', style: { width: '100%' } });
    const list = el('div', { class: 'pick-list', style: { maxHeight: '50vh', overflow: 'auto', marginTop: '8px' } });
    m.body.append(o.intro ? el('p', { class: 'muted small' }, o.intro) : null, search, list);
    const draw = async () => {
      list.innerHTML = '<div class="pick-item muted">Loading…</div>';
      let all = [];
      try { all = await FS.api.flex_charts(o.text || ''); } catch (e) { list.innerHTML = ''; list.appendChild(el('div', { class: 'pick-item', style: { color: 'var(--danger)' } }, e.message)); return; }
      const q = search.value.trim().toLowerCase();
      const hits = all.filter((c) => !q || ((c.title || '') + ' ' + (c.name || '') + ' ' + (c.template || '')).toLowerCase().includes(q)).sort((a, b) => (b.rows ? 1 : 0) - (a.rows ? 1 : 0) || (a.title || '').localeCompare(b.title || '') || (a.template || '').localeCompare(b.template || ''));
      list.innerHTML = '';
      if (!hits.length) list.appendChild(el('div', { class: 'pick-item muted' }, all.length ? 'No chart matches.' : 'This project has no text charts yet.'));
      for (const c of hits) {
        const it = el('div', { class: 'pick-item' + (c.rows ? '' : ' muted') + (o.current && c.guid === o.current ? ' on' : ''), 'data-test': o.test || 'pick-chart' }, el('span', { class: 'hw' }, c.title || '(untitled text)'), el('span', { class: 'pos' }, c.name || 'chart'), el('span', { class: 'n' }, c.rows ? c.rows + ' row' + (c.rows === 1 ? '' : 's') : 'empty'), o.current && c.guid === o.current ? el('span', { class: 'muted small' }, ' (this one)') : null);
        it.addEventListener('click', () => { m.close(); o.onPick(c); });
        list.appendChild(it);
      }
    };
    search.addEventListener('input', FS.debounce(draw, 180));
    draw();
    search.focus();
  }
  FS.pickChart = chartChooser;
  function ensureCollection() {
    if (S.coll) return S.coll;
    S.coll = new FS.Collection($('collection'), {
      onChange: (md) => { if (!isCollection()) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      onExport: () => exportCollection(),
      onRefreshAll: () => refreshAll(),
      rule: () => (S.note && S.note.rule) || null,
      onRuleUpdate: () => updateRuleCollection(),
      onRuleEdit: () => ruleCollectionDialog({ note: S.note }),
      onTextsUsed: (md) => textsUsedDialog({ note: S.note.id, markdown: md }, 'in the selected items'),
      onTagStyles: (srcs, map) => tagStylesForEmbeds(srcs, map),
      canLocate: () => !!(S.flex && S.flex.open),
    });
    window.__fsCollection = S.coll;      // for the tests and the console
    return S.coll;
  }
  async function exportCollection() {
    if (!isCollection()) return;
    await flushSave();
    try { await FS.exporter.exportNote(S.note, S.coll.asEditor(), 'flextext'); } catch (e) { FS.toast('Export failed: ' + e.message, 'error'); }
  }
  async function newCollection(title, body) {
    await flushSave();
    try {
      const n = await FS.api.create_note(S.tab, S.folder || '', title || '', FS.flexcopy.attach(body || ''), 'examples');
      clearSearch();
      await refreshLists();
      await openNote(n.id);
      return n;
    } catch (e) { FS.toast(e.message, 'error'); return null; }
  }
  /* RULE COLLECTIONS (Seth, 2026-10-18: "create a collection with ALL lines that match a
   * specific rule. And to be able to have that collection add new matches found in the database
   * that aren't already in that collection"). The dialog: the project's tags as a tree with a
   * box per tag (a group's box = every tag under it, `group:<name>`), a visual filter as a
   * shortcut that ticks the tags its rules name, the live count and a preview of the lines;
   * Create → Api.create_rule_collection. With `note`, it edits that collection's rule instead. */
  /* CHART COLLECTIONS (Seth, 2026-10-18: "returning cells or rows with a certain text chart markers
   * or which column a certain lexical item is found in"): a collection of every chart ROW a chart
   * search matches (Api.chart_search's query language), kept as the collection's rule
   * (`rule-charts:`), so "⟳ Find new rows" takes in what is new. `note` edits that rule instead. */
  async function chartCollectionDialog(opts) {
    opts = opts || {};
    const editing = opts.note && opts.note.kind === 'examples' && opts.note.rule && opts.note.rule.charts ? opts.note : null;
    const m = FS.modal({ title: editing ? 'The chart search of this collection' : 'New collection of chart rows', class: 'rule-dlg' });
    const q = el('input', { type: 'text', value: editing ? editing.rule.charts : (opts.query || ''), placeholder: 'e.g. col:Subject lex:kabir   or   marker:Topic', 'data-test': 'chart-rule-q', style: { width: '100%' } });
    const title = el('input', { type: 'text', placeholder: 'Title of the collection', 'data-test': 'chart-rule-title', style: { width: '100%' } });
    const count = el('div', { class: 'muted small', 'data-test': 'chart-rule-count' });
    const preview = el('div', { class: 'rule-preview', style: { maxHeight: '30vh', overflow: 'auto' } });
    const err = el('div', { style: { color: 'var(--danger)' } });
    const run = FS.debounce(async () => {
      err.textContent = '';
      if (!q.value.trim()) { count.textContent = 'Type a search: words, col:Name, marker:Name, lex:form, gloss:…, clause:…, moved, -marker:… to exclude.'; preview.innerHTML = ''; return; }
      try {
        const rows = await FS.api.chart_search(q.value.trim());
        count.textContent = rows.length + ' row' + (rows.length === 1 ? '' : 's') + ' match now';
        preview.innerHTML = '';
        for (const r of rows.slice(0, 40)) preview.appendChild(el('div', { class: 'pick-item' }, el('span', { class: 'hw' }, (r.chartName || 'Chart') + ' \u00b7 ' + (r.title || '')), el('span', { class: 'pos' }, r.label), el('span', { class: 'gl' }, r.cells.filter((c) => !r.hits.length || r.hits.includes(c.colN)).map((c) => c.words.join(' ')).join(' | '))));
        if (rows.length > 40) preview.appendChild(el('div', { class: 'muted small' }, '\u2026 and ' + (rows.length - 40) + ' more'));
      } catch (e) { err.textContent = e.message; }
    }, 250);
    q.addEventListener('input', run);
    m.body.append(el('p', { class: 'muted small' }, 'Every chart row the search matches becomes a card, in chart order; later, \u27f3 Find new rows adds the rows that are new. Words match the row\u2019s words, glosses, morphemes and notes; col:Subject keeps a column; marker:Topic a chart marker (marker:* any); lex:kabir a lexical item; gloss:dog; pos:n; clause:dependent; moved; clauseref; endsent; endpara; chart:, text:, template:, row:; a leading - on a key excludes.'),
      el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Search'), q), count, preview, err);
    if (!editing) m.body.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Title'), title));
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'),
      el('button', { class: 'btn primary', 'data-test': 'chart-rule-create', onclick: async () => {
        const query = q.value.trim();
        if (!query) { err.textContent = 'Type a search first.'; return; }
        try {
          if (editing) { const n = await FS.api.set_note_rule(editing.id, { charts: query }); if (S.note && S.note.id === n.id) S.note.rule = n.rule; m.close(); if (S.coll) S.coll.render(); return; }
          await flushSave();
          const n = await FS.api.create_rule_collection(S.tab, S.folder || '', title.value.trim() || ('Chart rows: ' + query), { charts: query });
          m.close();
          clearSearch();
          await refreshLists();
          await openNote(n.id);
          FS.toast(n.matched + ' row' + (n.matched === 1 ? '' : 's') + ' collected', 'ok');
        } catch (e) { err.textContent = e.message; }
      } }, editing ? 'Save' : 'Create')));
    run();
    (editing ? q : (opts.query ? title : q)).focus();
  }
  FS.chartCollection = (query) => chartCollectionDialog({ query });
  /* A FLEx CONCORDANCE EXPORT as a collection (Seth, 2026-10-20: "the ability to paste the results of
   * a FLEx concordance (or complex concordance) search and get an example collection … you could open
   * the CSV results"): File › Export Concordance Results… in FieldWorks writes Ref,Occurrence rows;
   * Api.concordance_preview places them in the open project, Api.create_concordance_collection writes
   * the collection. The file is chosen with the dialog (the page only ever holds its path) or its
   * contents are pasted into the box (a browser, or a file on another machine). */
  async function concordanceDialog() {
    const m = FS.modal({ title: 'New collection from a FLEx concordance export', class: 'rule-dlg' });
    let src = null, res = null;
    const file = el('span', { class: 'muted small', 'data-test': 'conc-file' }, 'No file chosen yet.');
    const ta = el('textarea', { 'data-test': 'conc-text', placeholder: 'Ref,Occurrence\nBoa Cons 1.20,korokoi a bu i bi dirou …', spellcheck: 'false',
      style: { width: '100%', height: '84px', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '12px' } });
    const title = el('input', { type: 'text', 'data-test': 'conc-title', placeholder: 'Concordance', style: { width: '100%' } });
    const noteBox = el('input', { type: 'checkbox', 'data-test': 'conc-note' });
    const count = el('div', { class: 'rule-count', 'data-test': 'conc-count' }, 'Choose the CSV FieldWorks wrote, or paste its contents.');
    const preview = el('div', { class: 'rule-preview', 'data-test': 'conc-preview', style: { maxHeight: '30vh', overflow: 'auto' } });
    const err = el('div', { style: { color: 'var(--danger)' } });
    const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
    const show = async () => {
      err.textContent = ''; preview.innerHTML = ''; res = null;
      if (!src) { count.textContent = 'Choose the CSV FieldWorks wrote, or paste its contents.'; return; }
      count.textContent = 'Placing the rows in the project…';
      try { res = await FS.api.concordance_preview(src); } catch (e) { count.textContent = ''; err.textContent = e.message; return; }
      count.textContent = res.matched + ' of ' + plural(res.total, 'row') + ' placed' + (res.unmatched ? ', ' + res.unmatched + ' not found' : '')
        + (res.texts.length ? ' · ' + plural(res.texts.length, 'text') : '') + (res.total > res.matched + res.unmatched ? ' (a line matched more than once is one example)' : '');
      for (const r of res.rows.slice(0, 80)) preview.appendChild(el('div', { class: 'pick-item' }, el('span', { class: 'hw' }, r.title), el('span', { class: 'pos' }, r.label + (r.hits > 1 ? ' ×' + r.hits : '')),
        el('span', { class: 'muted small' }, r.ref + (r.how === 'text' ? ' · found by its text, not its number' : r.how === 'number?' ? ' · by its number alone' : ''))));
      if (res.rows.length > 80) preview.appendChild(el('div', { class: 'muted small' }, '… and ' + (res.rows.length - 80) + ' more'));
      for (const x of res.misses.slice(0, 40)) preview.appendChild(el('div', { class: 'pick-item conc-miss' }, el('span', { class: 'hw muted' }, '✕ ' + x.ref), el('span', { class: 'muted small' }, x.why)));
      if (res.misses.length > 40) preview.appendChild(el('div', { class: 'muted small' }, '… and ' + (res.misses.length - 40) + ' more not found'));
      title.placeholder = 'Concordance' + (src.name ? ' — ' + src.name.replace(/\.csv$/i, '') : '');
    };
    const openBtn = el('button', { class: 'btn', 'data-test': 'conc-open', onclick: async () => {
      try { const f = await FS.api.read_concordance_file(); if (!f) return; src = { path: f.path, name: f.name }; file.textContent = f.name; ta.value = ''; show(); } catch (e) { err.textContent = e.message; }
    } }, '📂 Open the CSV…');
    ta.addEventListener('input', FS.debounce(() => { const t = ta.value.trim(); src = t ? { text: t } : null; file.textContent = t ? 'The pasted text' : 'No file chosen yet.'; show(); }, 300));
    m.body.append(
      el('p', { class: 'muted small' }, 'In FieldWorks run the concordance (or complex concordance), then File › Export Concordance Results… Each row of that file names a text and a line; every line found in the open project becomes an example here, once, in the file’s order. Rows that cannot be placed are listed at the end of the collection.'),
      el('div', { class: 'row' }, openBtn, file),
      el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'or paste'), ta),
      count, preview, err,
      el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Title'), title),
      el('label', { class: 'row muted small' }, noteBox, ' Keep each row’s reference (“Boa Cons 1.20”) as the example’s note'),
      el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'),
        el('button', { class: 'btn primary', 'data-test': 'conc-create', onclick: async () => {
          if (!src) { err.textContent = 'Choose the file or paste its contents first.'; return; }
          try {
            await flushSave();
            const n = await FS.api.create_concordance_collection(S.tab, S.folder || '', title.value.trim() || title.placeholder, src, { note: noteBox.checked });
            m.close(); clearSearch(); await refreshLists(); await openNote(n.id);
            FS.toast(plural(n.matched, 'example') + ' collected' + (n.unmatched ? ', ' + n.unmatched + ' not found (listed at the end)' : ''), 'ok');
          } catch (e) { err.textContent = e.message; }
        } }, 'Create')));
  }
  FS.concordanceCollection = () => concordanceDialog();
  /* Where a lexical item sits in the charts (Seth, 2026-10-18: "which column a certain lexical
   * item is found in"): a count per column of every template, each a click from its rows. */
  async function chartProfileDialog(term) {
    let p;
    try { p = await FS.api.chart_profile(term); } catch (e) { FS.toast(e.message, 'error'); return; }
    const m = FS.modal({ title: 'Where \u201c' + term + '\u201d sits in the charts' });
    if (!p.total) { m.body.appendChild(el('p', { class: 'muted' }, 'No chart cell holds \u201c' + term + '\u201d (words, morpheme forms, lexeme forms and glosses were looked at).')); return; }
    m.body.appendChild(el('p', { class: 'muted small' }, p.total + ' cell' + (p.total === 1 ? '' : 's') + ' in all. Click a count for the rows; \u201cCollect\u201d makes a collection of them.'));
    for (const t of p.templates) {
      const tbl = el('table', { class: 'profile-table' });
      tbl.appendChild(el('tr', {}, el('th', {}, 'Template \u201c' + (t.name || '?') + '\u201d'), el('th', {}, 'rows'), el('th', {})));
      for (const c of t.columns) {
        const rowsBox = el('div', { class: 'profile-rows', hidden: true });
        for (const r of c.rows) rowsBox.appendChild(el('div', { class: 'pick-item' }, el('span', { class: 'hw' }, (r.chartName || 'Chart') + ' \u00b7 ' + (r.title || '')), el('span', { class: 'pos' }, r.label), el('span', { class: 'gl' }, r.words + (r.glosses ? '  \u2018' + r.glosses + '\u2019' : ''))));
        const bar = el('span', { class: 'profile-bar', style: { width: Math.round(100 * c.count / t.total) + '%' } });
        const tr = el('tr', {}, el('td', {}, c.path.replace(/\//g, ' \u203a ')), el('td', { class: 'n' }, el('button', { class: 'lnk', 'data-test': 'profile-count', onclick: () => { rowsBox.hidden = !rowsBox.hidden; } }, String(c.count)), bar),
          el('td', {}, el('button', { class: 'lnk', title: 'A collection of these rows', onclick: () => { m.close(); chartCollectionDialog({ query: 'col:' + c.path + ' lex:' + term }); } }, 'Collect\u2026')));
        tbl.appendChild(tr);
        tbl.appendChild(el('tr', {}, el('td', { colspan: 3 }, rowsBox)));
      }
      m.body.appendChild(tbl);
    }
  }
  FS.chartProfile = chartProfileDialog;
  async function ruleCollectionDialog(opts) {
    opts = opts || {};
    if (opts.note && opts.note.rule && opts.note.rule.charts) return chartCollectionDialog(opts);
    let tags;
    try { tags = await FS.api.flex_text_tags(); } catch (e) { FS.toast(e.message, 'error'); return; }
    if (FS.tagstyles && !FS.tagstyles.list().length) FS.tagstyles.setList(tags);
    if (!tags.length) { FS.toast('This project has no text markup tags' + (S.flex && S.flex.open ? '' : ' (connect a FieldWorks project first)'), 'warn'); return; }
    const editing = opts.note && opts.note.kind === 'examples' ? opts.note : null;
    const chosen = new Set(((editing && editing.rule && editing.rule.tags) || (opts.tags || [])).map(String));
    const m = FS.modal({ title: editing ? 'The rule of this collection' : 'New collection from tagged lines', class: 'rule-dlg' });
    const title = el('input', { type: 'text', 'data-test': 'rule-title', placeholder: 'Title of the collection', style: { width: '100%' }, value: editing ? editing.title || '' : '' });
    if (editing) title.disabled = true;
    const count = el('div', { class: 'rule-count', 'data-test': 'rule-count' }, 'Choose one or more tags.');
    const preview = el('div', { class: 'rule-preview', 'data-test': 'rule-preview' });
    const tree = el('div', { 'data-test': 'rule-tags' });
    const byGuid = new Map(tags.map((t) => [t.guid, t]));
    const nameOf = (sel) => (byGuid.get(sel) || {}).name || sel;
    const isOn = (t) => chosen.has(t.name) || chosen.has(t.guid) || (t.path || [t.group]).some((g) => g && chosen.has('group:' + g));
    let lastRows = [];
    const recount = FS.debounce(async () => {
      const sels = [...chosen];
      if (!sels.length) { count.textContent = 'Choose one or more tags.'; preview.innerHTML = ''; lastRows = []; return; }
      count.textContent = 'Counting…';
      try { lastRows = await FS.api.rule_matches({ tags: sels }); } catch (e) { count.textContent = e.message; return; }
      count.textContent = lastRows.length + (lastRows.length === 1 ? ' line matches' : ' lines match') + ' now';
      preview.innerHTML = '';
      for (const r of lastRows.slice(0, 60)) preview.appendChild(el('div', {}, el('span', { class: 't' }, (r.title || '(untitled)') + ' ' + r.label + (r.segTo !== r.seg ? '\u2013' + r.labelTo : '')), el('span', { class: 'w', dir: 'auto' }, r.words || ''), el('span', { class: 'muted small' }, (r.tags || []).join(', '))));
      if (lastRows.length > 60) preview.appendChild(el('div', { class: 'muted small' }, '\u2026 and ' + (lastRows.length - 60) + ' more'));
      if (!editing && !title.value.trim()) title.placeholder = 'Lines tagged ' + sels.map(nameOf).map((x) => x.replace(/^group:/, '')).join(', ');
    }, 150);
    const draw = () => {
      tree.innerHTML = '';
      FS.tagstyles.renderTagTree(tree, tags, {
        open: true,
        leaf: (t) => {
          const cb = el('input', { type: 'checkbox', 'data-test': 'rule-tag', dataset: { tag: t.name }, checked: isOn(t), disabled: (t.path || [t.group]).some((g) => g && chosen.has('group:' + g)) || chosen.has('*') });
          cb.addEventListener('change', () => { cb.checked ? chosen.add(t.name) : chosen.delete(t.name); chosen.delete(t.guid); recount(); });
          return el('div', { class: 'tag-tree-leaf' }, el('label', {}, cb, el('span', {}, t.name), t.abbr && t.abbr !== t.name ? el('span', { class: 'muted small' }, t.abbr) : null, t.count != null ? el('span', { class: 'muted small' }, t.count + ' place' + (t.count === 1 ? '' : 's')) : null));
        },
        head: (n) => {
          const key = 'group:' + n.name;
          const cb = el('input', { type: 'checkbox', 'data-test': 'rule-group', dataset: { tag: key }, checked: chosen.has(key), title: 'Every tag under \u201c' + n.name + '\u201d, those added later too' });
          cb.addEventListener('click', (e) => e.stopPropagation());
          cb.addEventListener('change', () => { cb.checked ? chosen.add(key) : chosen.delete(key); draw(); recount(); });
          return el('label', { class: 'small', onclick: (e) => e.stopPropagation() }, cb, ' all of these');
        },
      });
    };
    const filters = (FS.tagstyles.filters && FS.tagstyles.filters()) || [];
    if (filters.length) {
      const sel = el('select', { 'data-test': 'rule-filter' }, el('option', { value: '' }, 'Tick the tags of a visual filter\u2026'));
      for (const f of filters) sel.appendChild(el('option', { value: f.id }, f.name || f.id));
      sel.addEventListener('change', () => {
        const f = filters.find((x) => x.id === sel.value);
        if (!f) return;
        for (const r of f.rules || []) if (r.enabled !== false && r.hide !== true && r.tag && !/^filter:/.test(r.tag)) chosen.add(/^group:/i.test(r.tag) || r.tag === '*' ? r.tag : nameOf(r.tag));
        sel.value = '';
        draw(); recount();
      });
      m.body.appendChild(el('div', { class: 'row', style: { marginBottom: '6px' } }, sel));
    }
    m.body.appendChild(el('div', { class: 'row', style: { marginBottom: '6px' } }, title));
    m.body.appendChild(el('div', { class: 'small muted' }, 'Every FLEx line (a segment, or the segments a tag spans) carrying one of the ticked tags becomes an example. Later, \u201cFind new lines\u201d adds the matches that are not in the collection yet.'));
    m.body.appendChild(tree);
    m.body.append(count, preview);
    const ok = el('button', { class: 'btn primary', 'data-test': 'rule-ok' }, editing ? 'Save rule' : 'Create collection');
    ok.addEventListener('click', async () => {
      const rule = { tags: [...chosen] };
      if (!rule.tags.length) { FS.toast('Choose at least one tag', 'warn'); return; }
      ok.disabled = true;
      try {
        if (editing) {
          const n = await FS.api.set_note_rule(editing.id, rule);
          if (S.note && S.note.id === n.id) { S.note.rule = n.rule; ensureCollection().render(); }
          m.close();
          FS.toast('Rule saved \u2014 \u201cFind new lines\u201d adds what it matches now', 'ok');
          return;
        }
        await flushSave();
        const n = await FS.api.create_rule_collection(S.tab, S.folder || '', title.value.trim() || title.placeholder, rule);
        m.close();
        clearSearch();
        await refreshLists();
        await openNote(n.id);
        FS.toast(n.matched + (n.matched === 1 ? ' line collected' : ' lines collected'), 'ok');
      } catch (e) { ok.disabled = false; FS.toast(e.message, 'error'); }
    });
    m.body.appendChild(el('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), ok));
    draw();
    recount();
    setTimeout(() => (editing ? ok : title).focus(), 0);
  }
  FS.ruleCollection = (o) => ruleCollectionDialog(o);
  /* "Find new lines": the matches of the rule that are not in the collection yet, appended and selected. */
  async function updateRuleCollection() {
    if (!isCollection() || !S.note.rule) return;
    await flushSave();
    let r;
    try { r = await FS.api.update_rule_collection(S.note.id); } catch (e) { FS.toast(e.message, 'error'); ensureCollection().render(); return; }
    const n = r.note;
    n.body = FS.flexcopy.strip(n.body || '', n.id);
    S.note = n; S.dirty = false;
    const coll = ensureCollection().load(n.body || '');
    if (r.added.length) { coll.selectBySrc(r.added); FS.toast(r.added.length + (r.added.length === 1 ? ' new line added' : ' new lines added') + ' (selected)', 'ok'); }
    else FS.toast('Nothing new: all ' + r.matched + ' matching line' + (r.matched === 1 ? ' is' : 's are') + ' here already', 'ok');
    await refreshLists();
  }
  /* "Collect the examples into a new collection…": every interlinear example in a note (blocks,
   * inline chips, table cells), in order, copied into a new collection next to it. */
  const examplesIn = (md) => FS.flexref.findEmbeds(md || '').filter((e) => e.spec && e.spec.kind === 'text').map((e) => FS.collection.cleanEmbed(FS.flexref.serialize(e.spec))).filter(Boolean);
  /* The markdown of what is highlighted in the open note, or null when nothing is (Seth,
   * 2026-10-16: collect "a highlighted PART of a note … OR a whole document"): a selection
   * across blocks, a selection inside one text block (inline chips included), a range of
   * table cells, or a selection inside a rendered example (that example). */
  function highlightedSource() {
    const ed = S.editor;
    if (!ed || !S.note || isSpecial()) return null;
    if (ed.msel) { const md = ed.selectionMarkdown(); if (md.trim()) return md; }
    for (const b of ed.blocks) {
      const w = b.el && b.el._table;
      if (w && w.sel) { const rows = w.selectedRows(); if (rows.length) return rows.map((r) => r.join('\n')).join('\n'); }
    }
    const sel = window.getSelection();
    if (sel && sel.rangeCount && !sel.isCollapsed) {
      const r = sel.getRangeAt(0);
      const c = r.commonAncestorContainer;
      const node = c.nodeType === 1 ? c : c.parentElement;
      if (node && $('editor').contains(node)) {
        if (node.closest('.blk-body')) return r.toString();          // a text block's text IS its markdown
        const blk = ed.blocks.find((b) => b.el && b.el.contains(node));
        if (blk) return blk.src;
      }
    }
    return null;
  }
  // the highlight as it was when the note menu was pressed (opening the menu can clear it)
  document.addEventListener('mousedown', (e) => { if (e.target.closest && e.target.closest('#btn-note-menu')) S.menuHighlight = highlightedSource(); }, true);
  async function collectExamples(n, md) {
    await flushSave();
    const part = md != null;
    const srcs = examplesIn(part ? md : (await FS.api.get_note(n.id)).body);
    if (!srcs.length) { FS.toast((part ? 'The selection has' : 'This note has') + ' no interlinear examples to collect.', 'warn'); return; }
    const c = await newCollection((n.title || 'Untitled') + ' \u2014 examples', srcs.join('\n\n') + '\n');
    if (c) FS.toast(srcs.length + ' example' + (srcs.length === 1 ? '' : 's') + (part ? ' from the selection' : '') + ' collected — export it with \u201cExport as FLEx text\u2026\u201d', 'ok');
  }
  /* "Add to an example collection…" on any example: a pick of the collections, or a new one. */
  FS.addToCollection = (anchor, src) => {
    const clean = FS.collection.cleanEmbed(src);
    if (!clean) return;
    FS.popover(anchor, async (pop, close) => {
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Add this example to')));
      const host = el('div', {}, el('div', { class: 'muted small', style: { padding: '4px 8px' } }, 'Loading…'));
      pop.appendChild(host);
      const add = async (c) => {
        close();
        try {
          const s = await FS.api.add_to_collection(c.id, [FS.flexcopy.attach(clean)]);
          FS.toast('Added to \u201c' + (c.title || 'Untitled collection') + '\u201d (' + (s.exampleCount || 0) + ' example' + (s.exampleCount === 1 ? '' : 's') + ')', 'ok');
          await refreshLists();
        } catch (e) { FS.toast(e.message, 'error'); }
      };
      let cols = [];
      try { cols = await FS.api.list_collections(); } catch (e) { cols = []; }
      host.innerHTML = '';
      for (const c of cols) host.appendChild(el('button', { class: 'menu-item', onclick: () => add(c) }, (c.title || 'Untitled collection') + '  ', el('span', { class: 'muted small' }, '(' + c.count + ')')));
      if (cols.length) host.appendChild(el('hr'));
      host.appendChild(el('button', { class: 'menu-item', onclick: async () => {
        close();
        const title = prompt('Name of the new example collection', 'Examples');
        if (title == null) return;
        await flushSave();
        try {
          const n = await FS.api.create_note(S.tab, S.folder || '', title.trim(), FS.flexcopy.attach(clean) + '\n', 'examples');
          await refreshLists();
          FS.toast('Added to the new collection \u201c' + (n.title || 'Untitled collection') + '\u201d', 'ok');
        } catch (e) { FS.toast(e.message, 'error'); }
      } }, '\u2795 New example collection\u2026'));
    });
  };
  function renderNoteMeta() {
    const n = S.note;
    if (!n) return;
    $('btn-pin').style.opacity = n.pinned ? '1' : '0.45';
    $('note-updated').textContent = 'Edited ' + FS.relTime(n.updated);
    const tab = S.config.tabs.find((t) => t.dir === n.tab) || {};
    $('note-location').textContent = (tab.name || n.tab) + (n.folder ? ' / ' + n.folder : '');
    const host = $('note-tags');
    host.innerHTML = '';
    for (const t of n.tags) host.appendChild(el('span', { class: 'chip', style: tagStyle(t) }, '#' + t, el('span', { class: 'x', title: 'Remove tag', onclick: () => { n.tags = n.tags.filter((x) => x !== t); saveMeta({ tags: n.tags }); renderNoteMeta(); } }, '✕')));
    for (const t of n.inlineTags || []) if (!n.tags.includes(t)) host.appendChild(el('span', { class: 'chip', style: Object.assign({ opacity: '0.7' }, tagStyle(t)), title: 'Tag written in the text' }, '#' + t));
    host.appendChild(el('button', { class: 'add-tag', onclick: (e) => tagPicker(e.currentTarget) }, '+ tag'));
  }
  function tagPicker(anchor) {
    FS.popover(anchor, (pop, close) => {
      const input = el('input', { type: 'text', placeholder: 'new or existing tag' });
      const add = (name) => { name = name.trim().replace(/^#/, ''); if (!name) return; if (!S.note.tags.includes(name)) { S.note.tags.push(name); saveMeta({ tags: S.note.tags }); } renderNoteMeta(); close(); refreshLists(); };
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(input.value); } });
      pop.appendChild(el('div', { class: 'row' }, input));
      const avail = S.tags.filter((t) => !S.note.tags.includes(t.name));
      if (avail.length) { const row = el('div', { class: 'row' }); for (const t of avail) row.appendChild(el('span', { class: 'chip', style: Object.assign({ cursor: 'pointer' }, tagStyle(t.name)), onclick: () => add(t.name) }, '#' + t.name)); pop.appendChild(row); }
      setTimeout(() => input.focus(), 0);
    });
  }
  async function saveMeta(patch) {
    if (!S.note) return;
    try { const s = await FS.api.save_note(S.note.id, patch); S.note.updated = s.updated; S.note.inlineTags = s.inlineTags; const i = S.notes.findIndex((n) => n.id === S.note.id); if (i >= 0) S.notes[i] = s; renderList(); renderNoteMeta(); } catch (e) { FS.toast(e.message, 'error'); }
  }
  const scheduleSave = FS.debounce(() => saveNow(), 600);
  /* What FLEx says now differs from a plain-text copy the note's file holds (or the note was saved
   * this session and an object has no copy yet): save, so the file stays readable without the app
   * (Seth, 2026-10-17). Opening a note alone never rewrites it. */
  const ftagsSoon = FS.debounce(loadFtags, 800);
  FS.flexcopy.onFetched(() => {
    ftagsSoon();                       // the rail's FLEx tags: a fetched text's tags are in the index now
    // a save already pending writes the copies anyway: never postpone it
    if (!S.note || S.dirty || S.saving || !FS.flexcopy.stale(S.note.body || '', S.note.id)) return;
    S.dirty = true;
    scheduleSave();
  });
  async function saveNow() {
    if (!S.note || !S.dirty || S.saving) return;
    S.saving = true;
    const n = S.note;
    try {
      const s = await FS.api.save_note(n.id, { body: FS.flexcopy.attach(n.body, n.id), title: $('note-title').value });
      S.dirty = false;
      n.updated = s.updated; n.title = s.title; n.inlineTags = s.inlineTags;
      const i = S.notes.findIndex((x) => x.id === n.id);
      if (i >= 0) S.notes[i] = s; else S.notes.unshift(s);
      $('save-state').textContent = 'Saved';
      $('note-updated').textContent = 'Edited ' + FS.relTime(s.updated);
      renderList();
      const before = JSON.stringify(S.tags.map((t) => t.name)); S.tags = await FS.api.tags(); if (JSON.stringify(S.tags.map((t) => t.name)) !== before) renderRail();
      renderNoteMeta();
    } catch (e) { $('save-state').textContent = 'Not saved: ' + e.message; FS.toast('Save failed: ' + e.message, 'error'); }
    finally { S.saving = false; if (S.dirty) scheduleSave(); }
  }
  async function flushSave() { scheduleSave.cancel(); await saveNow(); }

  async function newNote() {
    await flushSave();
    try {
      const n = await FS.api.create_note(S.tab, S.folder || '', '', '');
      clearSearch();
      await refreshLists();
      await openNote(n.id);
    } catch (e) { FS.toast(e.message, 'error'); }
  }
  function noteMenu(anchor, n) {
    FS.popover(anchor, (pop, close) => {
      const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
      item(n.pinned ? 'Unpin' : 'Pin to top', async () => { await FS.api.save_note(n.id, { pinned: !n.pinned }); if (S.note && S.note.id === n.id) S.note.pinned = !n.pinned; await refreshLists(); renderNoteMeta(); });
      item('Move to…', () => moveDialog(n));
      item('Duplicate', async () => { await flushSave(); const c = await FS.api.duplicate_note(n.id); await refreshLists(); openNote(c.id); FS.toast('Duplicated — this is the copy'); });
      item('Copy to…', () => moveDialog(n, true));
      if (n.kind !== 'examples' && n.kind !== 'chart') {
        // the highlighted part of the open note when it holds examples, else the whole note
        const hl = S.note && S.note.id === n.id ? (S.menuHighlight !== undefined ? S.menuHighlight : highlightedSource()) : null;
        const k = hl ? examplesIn(hl).length : 0;
        if (k) item('Collect the ' + k + ' selected example' + (k === 1 ? '' : 's') + ' into a new collection…', () => collectExamples(n, hl), 'collect-selection');
        else item('Collect the examples into a new collection…' + (hl ? '  (none selected: the whole note)' : ''), () => collectExamples(n));
      }
      {
        const hl2 = S.note && S.note.id === n.id ? (S.menuHighlight !== undefined ? S.menuHighlight : highlightedSource()) : null;
        if (hl2 && examplesIn(hl2).length) item('Texts used in the selection\u2026', () => textsUsedDialog({ note: n.id, markdown: hl2 }, 'in the selection'), 'texts-used-selection');
        if (hl2 && examplesIn(hl2).length) item('FLEx tag styles for the selected examples\u2026', () => tagStylesForEmbeds(examplesIn(hl2)), 'tag-styles-selection');
        else item('Texts used in this note\u2026', () => textsUsedDialog({ note: n.id }, 'in \u201c' + (n.title || 'Untitled') + '\u201d'), 'texts-used-note');
      }
      S.menuHighlight = undefined;
      item('Copy markdown', async () => { const full = await FS.api.get_note(n.id); FS.copyText(full.body); FS.toast('Copied'); });
      item('Copy link to this note', () => { FS.copyText('flexscratchpad://note/' + n.id); FS.toast('Link copied — it opens this note in FLEx Scratchpad'); });
      pop.appendChild(el('hr'));
      pop.appendChild(el('div', { class: 'row', style: { padding: '0 8px' } }, el('b', {}, 'Export')));
      const doExport = async (fmt) => { if (!S.note || S.note.id !== n.id) await openNote(n.id); await flushSave(); try { await FS.exporter.exportNote(S.note, isCollection() ? ensureCollection().asEditor() : isChartNote() ? ensureChartNote().asEditor() : ensureEditor(), fmt); } catch (e) { FS.toast('Export failed: ' + e.message, 'error'); } };
      // only an example collection exports as a FLEx text (Seth, 2026-10-16)
      if (n.kind === 'examples') item('FLEx text (.flextext)…', () => doExport('flextext'));
      item('Markdown (.md)', () => doExport('md'));
      item('Web page (.html)', () => doExport('html'));
      item('Word (.docx)', () => doExport('docx'));
      item('Excel (.xlsx)', () => doExport('xlsx'));
      item('PDF (.pdf)', () => doExport('pdf'));
      item('Slideshow (.html)', () => doExport('slides'));
      item('PowerPoint (.pptx)', () => doExport('pptx'));
      if (S.init.canBrowse) item('Show file', () => FS.api.reveal_note(n.id));
      pop.appendChild(el('hr'));
      item('Delete (to trash)', async () => { if (!confirm('Move “' + (n.title || 'Untitled') + '” to the trash?')) return; await FS.api.delete_note(n.id); if (S.note && S.note.id === n.id) { S.note = null; $('editor-pane').classList.add('no-note'); } await refreshLists(); }, 'danger');
    });
  }
  /* Which FLEx texts the examples come from (Seth, 2026-10-16: "list which texts are referenced in
   * a [note], a folder, or a selected range … not individual items, but texts they come from",
   * "a FLEx hyperlink for each"): one row per text with its count, the notes it is in, and its
   * FLEx link; Copy list puts the titles (or titles with their links) on the clipboard. */
  async function textsUsedDialog(scope, where) {
    await flushSave();
    let r;
    try { r = await FS.api.texts_used(scope); } catch (e) { FS.toast(e.message, 'error'); return; }
    const texts = r.texts || [];
    const m = FS.modal({ title: 'Texts used ' + where });
    const n = texts.length;
    m.body.appendChild(el('p', { class: 'small muted', 'data-test': 'texts-used-summary' },
      n ? n + (n === 1 ? ' text' : ' texts') + ' — the texts the examples come from' + (r.notes > 1 ? ', in ' + r.notes + ' notes' : '') + '.'
        : 'No interlinear examples here' + (r.notes > 1 ? ' (' + r.notes + ' notes looked at).' : '.')));
    const count = (t) => {
      const parts = [];
      if (t.examples) parts.push(t.examples + (t.examples === 1 ? ' example' : ' examples'));
      if (t.links) parts.push(t.links + (t.links === 1 ? ' link' : ' links'));
      if (t.notes.length > 1 || (r.notes > 1 && t.notes.length)) parts.push(t.notes.length === 1 ? 'in \u201c' + (t.notes[0].title || 'Untitled') + '\u201d' : 'in ' + t.notes.length + ' notes');
      return parts.join(' \u00b7 ');
    };
    if (n) {
      const list = el('div', { class: 'texts-used', 'data-test': 'texts-used' });
      for (const t of texts) {
        const row = el('div', { class: 'texts-used-row' },
          el('div', { class: 'tu-main' },
            el('a', { class: 'tu-title', dir: 'auto', href: t.url, title: 'Open this text in FLEx', 'data-test': 'texts-used-title', onclick: (e) => { e.preventDefault(); FS.api.open_in_flex(t.url); } }, t.title),
            el('div', { class: 'small muted' }, count(t))),
          el('button', { class: 'btn', title: 'Copy the FLEx link to this text', onclick: () => { FS.copyText(t.url); FS.toast('FLEx link copied'); } }, 'Copy link'),
          el('button', { class: 'btn', title: 'Open this text in FLEx', onclick: () => FS.api.open_in_flex(t.url) }, 'Open in FLEx \u2197'));
        if (t.notes.length > 1) {
          const notesEl = el('div', { class: 'tu-notes small' });
          for (const x of t.notes) notesEl.appendChild(el('a', { href: '#', onclick: (e) => { e.preventDefault(); m.close(); openNote(x.id); } }, x.title || 'Untitled'));
          row.querySelector('.tu-main').appendChild(notesEl);
        }
        list.appendChild(row);
      }
      m.body.appendChild(list);
    }
    const row = el('div', { class: 'btn-row' });
    if (n) {
      row.appendChild(el('button', { class: 'btn', 'data-test': 'texts-used-copy', title: 'The titles, one per line', onclick: () => { FS.copyText(texts.map((t) => t.title).join('\n')); FS.toast('List copied'); } }, 'Copy list'));
      row.appendChild(el('button', { class: 'btn', 'data-test': 'texts-used-copy-links', title: 'A Markdown list of the titles, each a FLEx link (paste it into a note)', onclick: () => { FS.copyText(texts.map((t) => '- [' + t.title.replace(/[\[\]]/g, '') + '](' + t.url + ')').join('\n')); FS.toast('List with FLEx links copied'); } }, 'Copy with FLEx links'));
    }
    row.appendChild(el('span', { class: 'spacer' }));
    row.appendChild(el('button', { class: 'btn primary', onclick: () => m.close() }, 'Close'));
    m.body.appendChild(row);
  }
  function moveDialog(n, copy) {
    const m = FS.modal({ title: copy ? 'Copy note to' : 'Move note', class: 'narrow' });
    const tab = el('select');
    for (const t of S.config.tabs) tab.appendChild(el('option', { value: t.dir, selected: t.dir === n.tab }, t.name));
    const folder = el('select');
    const fill = () => { folder.innerHTML = ''; folder.appendChild(el('option', { value: '' }, '(tab root)')); for (const f of S.folders[tab.value] || []) folder.appendChild(el('option', { value: f, selected: f === n.folder }, f)); };
    tab.addEventListener('change', fill); fill();
    m.body.appendChild(el('div', { class: 'form-row' }, el('label', {}, 'Tab'), tab, el('label', {}, 'Folder'), folder));
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), el('button', { class: 'btn primary', onclick: async () => {
      if (copy) { await flushSave(); const c = await FS.api.duplicate_note(n.id, tab.value, folder.value); m.close(); await refreshLists(); openNote(c.id); FS.toast('Copied — this is the copy'); return; }
      await FS.api.move_note(n.id, tab.value, folder.value); if (S.note && S.note.id === n.id) { S.note.tab = tab.value; S.note.folder = folder.value; renderNoteMeta(); } m.close(); await refreshLists();
    } }, copy ? 'Copy' : 'Move')));
  }

  /* ------------------------------------------------------------------ links */
  async function openLink(href) {
    if (!href) return;
    if (href.startsWith('note:')) {
      const title = href.slice(5).trim();
      const hit = S.notes.find((n) => n.title.toLowerCase() === title.toLowerCase());
      if (hit) return openNote(hit.id);
      if (confirm('No note called “' + title + '”. Create it?')) { const n = await FS.api.create_note(S.tab, S.folder || '', title, ''); await refreshLists(); openNote(n.id); }
      return;
    }
    if (href.startsWith('tag:')) { S.tag = href.slice(4); renderRail(); if (S.query) runSearch(); else renderList(); return; }
    if (href.startsWith('flex:')) {
      const m = /^flex:(entry|sense|text|wordform|chart)\/([0-9a-f-]{36})/i.exec(href);
      if (m) { try { await FS.api.flex_open_object(m[1], m[2]); FS.toast('Sent to FieldWorks'); } catch (e) { FS.toast(e.message, 'error'); } }
      return;
    }
    if (href.startsWith('silfw:')) { try { await FS.api.open_in_flex(href); } catch (e) { FS.toast(e.message, 'error'); } return; }
    if (/^https?:/i.test(href)) { window.open(href, '_blank'); return; }
  }

  /* ------------------------------------------------------------------ insert / slash */
  function insertFlex() { FS.openPicker(); }
  // the chart search, one click away (Seth, 2026-10-19: "easy to find"): the picker on its Text charts tab;
  // in a chart note or a collection the rows are browsed and inserted into a NEW note
  FS.searchCharts = () => {
    if (!S.note || isChartNote() || isCollection()) {
      FS.picker.open(async (md) => { try { await flushSave(); const n = await FS.api.create_note(S.tab, S.folder || '', 'Chart rows', md); clearSearch(); await refreshLists(); await openNote(n.id); } catch (e) { FS.toast(e.message, 'error'); } }, { mode: 'charts' });
      return;
    }
    FS.openPicker({ mode: 'charts' });
  };
  /* The picker, into whatever is open: a note's editor, or a collection (its own add). */
  FS.openPicker = (o) => { if (isChartNote()) { FS.toast('A chart note holds one chart; objects go into ordinary notes.'); return; } if (isCollection()) { if (S.coll) S.coll.pick(undefined, o); return; } FS.picker.open((md, asBlock) => ensureEditor().insertMarkdown(md, asBlock), o); };
  /* Tag styles for SEVERAL examples at once (Seth, 2026-10-17: "applyable to a group of examples by
   * highlight"): the dialog in example scope, its rules written into each embed's `tags=`. */
  function tagStylesForEmbeds(srcs, applyFn) {
    srcs = (srcs || []).map((x) => (typeof x === 'string' ? x : x.src)).filter((src) => { const sp = FS.flexref.parse(src); return sp && sp.kind === 'text'; });
    if (!srcs.length) { FS.toast('No interlinear examples are selected'); return; }
    const fnFor = (rules) => (src) => { const sp = FS.flexref.parse(src); if (!sp || sp.kind !== 'text') return src; FS.flexref.setTagRules(sp, rules); return FS.flexref.serialize(sp); };
    FS.tagstyles.dialog({ kind: 'example', label: srcs.length + ' selected example' + (srcs.length === 1 ? '' : 's'), rules: FS.flexref.tagRules(FS.flexref.parse(srcs[0])),
      apply: (rules) => { const fn = fnFor(rules); if (applyFn) applyFn(fn); else ensureEditor().mapEmbeds(srcs, fn); srcs = srcs.map(fn); } });
  }
  /* Attach files (Seth, 2026-10-17): COPIED into the notebook's attachments/ unless `link`,
   * then a file alone on its line becomes a card, after text a chip. */
  async function attachFiles(link) {
    if (!S.note || isSpecial()) return;
    const ed = ensureEditor();
    const srcs = await FS.files.pick(link);
    if (srcs.length) ed.insertMarkdown(srcs.join('\n\n'), true);
  }
  function attachMenu(anchor) {
    FS.popover(anchor, (pop, close) => {
      const item = (label, hint, fn, test) => pop.appendChild(el('button', { class: 'menu-item', 'data-test': test, onclick: () => { close(); fn(); } },
        el('div', {}, label), el('div', { class: 'muted small' }, hint)));
      item('📎 Copy into the notebook…', 'The note keeps its file wherever the notebook goes (the default).', () => attachFiles(false), 'attach-copy');
      item('🔗 Link to the file where it is…', 'No copy: for big recordings, or a file you keep editing. The link breaks if the file moves.', () => attachFiles(true), 'attach-link');
      pop.appendChild(el('div', { class: 'muted small', style: { padding: '6px 8px 2px' } }, 'Or drop files on the note (Alt+drop links them).'));
    });
  }
  /* Refresh all: every example in every note is re-fetched from FLEx and re-snapshotted,
   * then the open note is redrawn in place (scroll kept). */
  async function refreshAll() {
    const btn = $('btn-refresh-all');
    if (!(S.flex && S.flex.open)) { FS.toast('Connect a FieldWorks project first (Settings)', 'error'); return; }
    btn.disabled = true; btn.textContent = '↻ Refreshing…';
    try {
      await flushSave();
      const r = await FS.api.flex_refresh_all();
      FS.interlinear.invalidate();
      if (S.note && isCollection()) ensureCollection().load(S.note.body || '');   // keeps its scroll
      else if (S.note && isChartNote()) ensureChartNote().load(S.note.body || '');
      else if (S.note) {
        const edEl = $('editor'); const top = edEl.scrollTop;
        ensureEditor().load(S.note.body || '');
        edEl.scrollTop = top;
      }
      const failed = (r.failed || []).length;
      FS.toast('Refreshed ' + r.refreshed + ' of ' + r.objects + ' FLEx object' + (r.objects === 1 ? '' : 's') + (failed ? ' — ' + failed + ' could not be read: ' + r.failed.slice(0, 3).map((f) => f.error).join('; ') : ''), failed ? 'error' : 'ok');
    } catch (e) { FS.toast(e.message, 'error'); }
    btn.disabled = false; btn.textContent = '↻ Refresh all';
    const cb = document.querySelector('[data-test="coll-refresh"]');
    if (cb) cb.disabled = false;
  }
  function slashMenu(body, b) {
    FS.popover(body, (pop, close) => {
      const item = (label, fn) => pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); fn(); } }, label));
      item('FLEx object…', insertFlex);
      item('Attach a file…', () => attachFiles(false));
      item('Link to a file…', () => attachFiles(true));
      item('Table', () => S.editor.insertMarkdown(FS.tables.template(3, 3), true));
      item('Checklist', () => S.editor.insertMarkdown('- [ ] ', false));
      item('Heading', () => S.editor.insertMarkdown('## ', false));
      item('Quote', () => S.editor.insertMarkdown('> ', false));
      item('Code block', () => S.editor.insertMarkdown('```\n\n```', true));
      item('Divider', () => S.editor.insertMarkdown('---', true));
    });
  }
  function toolbarAction(kind, btn) {
    const ed = ensureEditor();
    switch (kind) {
      case 'h': return btn ? headingMenu(btn, ed) : ed.linePrefix('h', 2);
      case 'bold': return ed.wrapSelection('**');
      case 'italic': return ed.wrapSelection('*');
      case 'mark': return ed.wrapSelection('==');
      case 'code': return ed.wrapSelection('`');
      case 'link': return linkDialog();
      case 'list': return ed.linePrefix('list');
      case 'task': return ed.linePrefix('task');
      case 'quote': return ed.linePrefix('quote');
      case 'indent': return ed.indentActive(1) || FS.toast('Put the caret in a list item first');
      case 'outdent': return ed.indentActive(-1) || FS.toast('Put the caret in a list item first');
      case 'table': return ed.insertMarkdown(FS.tables.template(3, 3), true);
      case 'hr': return ed.insertMarkdown('---', true);
    }
  }

  /* HYPERLINKS (Seth, 2026-10-18: "a hyperlink feature … button and keyboard shortcut"): Ctrl+K /
   * the 🔗 button opens a small dialog for the caret's place — the selected text becomes the link
   * text, a URL on the clipboard or in the selection fills the address, a link under the caret is
   * EDITED (or removed) rather than nested. Two kinds: a web / file / FLEx address → `[text](url)`,
   * another note of this notebook → `[[Title]]` (the wikilink, which opens the note). A table cell
   * takes the same dialog and gets the markdown typed into it. */
  const URLISH = /^(https?:\/\/|mailto:|silfw:\/\/|flexscratchpad:\/\/|file:\/\/\/|ftp:\/\/)/i;
  function normalizeUrl(u) {
    u = (u || '').trim();
    if (!u) return '';
    if (URLISH.test(u) || /^[a-z][a-z0-9+.-]*:/i.test(u)) return u;
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(u)) return 'mailto:' + u;
    return 'https://' + u;
  }
  async function linkDialog() {
    if (!S.note || isSpecial()) return;
    const ed = ensureEditor();
    const ae = document.activeElement;
    const cell = ae && ae.classList && ae.classList.contains('cell-edit') ? ae : null;
    let ctx = null, cellSel = null;
    if (cell) {
      // the dialog takes the focus, which closes the cell editor (its blur commits the cell and
      // remembers the caret): the selected text is taken out now and the link goes in at that
      // caret through the table's own insertText; Cancel puts the text back
      const sel = window.getSelection();
      cellSel = { text: sel && !sel.isCollapsed ? sel.toString() : '' };
      if (cellSel.text) document.execCommand('delete');
    } else {
      ctx = ed.linkContext();
      if (!ctx) { FS.toast('Put the caret in a line of text first', 'warn'); return; }
    }
    const editing = ctx && ctx.link;
    const selected = editing ? editing.text : (cell ? cellSel.text : ctx.selected).replace(/\n/g, ' ');
    let done = false;
    const m = FS.modal({ title: editing ? 'Edit link' : 'Insert link', class: 'link-dlg', onClose: () => { if (!done && cell && cellSel.text) ed.insertMarkdown(cellSel.text, false); } });
    const kind = el('select', { 'data-test': 'link-kind' }, el('option', { value: 'url' }, 'A web, file or FLEx address'), el('option', { value: 'note' }, 'Another note in this notebook'));
    const text = el('input', { type: 'text', 'data-test': 'link-text', placeholder: 'Text to show (the address when empty)', value: selected && !URLISH.test(selected) ? selected : '' });
    const url = el('input', { type: 'text', 'data-test': 'link-url', placeholder: 'https://… · mailto:… · silfw://… · a file', value: '' });
    const noteList = el('datalist', { id: 'link-notes' });
    for (const n of S.notes || []) if (n.title) noteList.appendChild(el('option', { value: n.title }));
    const note = el('input', { type: 'text', 'data-test': 'link-note', list: 'link-notes', placeholder: 'Title of the note', value: '' });
    if (editing) {
      if (editing.href.startsWith('note:')) { kind.value = 'note'; note.value = editing.href.slice(5); } else url.value = editing.href;
    } else if (selected && URLISH.test(selected)) url.value = selected;
    const urlRow = el('div', { class: 'form-row' }, el('label', {}, 'Address'), url);
    const noteRow = el('div', { class: 'form-row' }, el('label', {}, 'Note'), note, noteList);
    const textRow = el('div', { class: 'form-row' }, el('label', {}, 'Text'), text);
    const syncKind = () => { const isNote = kind.value === 'note'; urlRow.hidden = isNote; textRow.hidden = isNote; noteRow.hidden = !isNote; };
    kind.addEventListener('change', syncKind);
    syncKind();
    const hint = el('p', { class: 'small muted' }, 'Links open with Ctrl+click in the note (a FLEx link goes to FieldWorks, a note link opens the note).');
    const ok = el('button', { class: 'btn primary', 'data-test': 'link-ok' }, editing ? 'Update' : 'Insert');
    const open = el('button', { class: 'btn', 'data-test': 'link-open', title: 'Open the address now', onclick: () => { const u = normalizeUrl(url.value); if (u) openLink(u); } }, 'Open');
    const remove = editing ? el('button', { class: 'btn danger', 'data-test': 'link-remove', title: 'Keep the text, drop the link', onclick: () => { m.close(); ed.replaceRange(ctx.body, ctx.b, editing.start, editing.end, editing.wiki ? editing.text : editing.text); } }, 'Remove link') : null;
    const put = (md) => {
      done = true;
      m.close();
      if (cell) { ed.insertMarkdown(md, false); return; }
      if (editing) ed.replaceRange(ctx.body, ctx.b, editing.start, editing.end, md);
      else ed.replaceRange(ctx.body, ctx.b, ctx.start, ctx.end, md);
    };
    ok.addEventListener('click', () => {
      if (kind.value === 'note') {
        const t = note.value.trim();
        if (!t) { FS.toast('Which note?', 'warn'); note.focus(); return; }
        put('[[' + t.replace(/[\[\]]/g, '') + ']]');
        return;
      }
      const u = normalizeUrl(url.value);
      if (!u) { FS.toast('An address is needed', 'warn'); url.focus(); return; }
      if (/\s/.test(u)) { FS.toast('An address cannot contain spaces (a file path can be dropped on the note instead)', 'warn'); url.focus(); return; }
      const t = (text.value.trim() || u).replace(/[\[\]]/g, '');
      put('[' + t + '](' + u + ')');
    });
    for (const inp of [text, url, note]) inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ok.click(); } });
    m.body.append(el('div', { class: 'form-row' }, el('label', {}, 'Link to'), kind), textRow, urlRow, noteRow, hint,
      el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '6px', marginTop: '10px' } }, remove, open, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), ok));
    // a URL on the clipboard fills the address when nothing else did (WebView2 may never answer: 400 ms, like the tables' paste)
    if (!editing && !url.value && navigator.clipboard && navigator.clipboard.readText) {
      Promise.race([navigator.clipboard.readText().catch(() => ''), new Promise((r) => setTimeout(() => r(''), 400))]).then((clip) => { clip = (clip || '').trim(); if (clip && URLISH.test(clip) && !/\s/.test(clip) && !url.value) url.value = clip; });
    }
    setTimeout(() => (kind.value === 'note' ? note : (text.value ? url : text)).focus(), 0);
  }
  FS.linkDialog = linkDialog;

  /* THE LINK PILL (Seth, 2026-10-18: "make it easy to click to follow or edit links"): while the
   * caret sits in a link of a text block, a small strip under the link shows its address with
   * Open · Edit · Copy · Unlink — so one click on a link (which puts the caret there) shows it and
   * a second click opens; Ctrl+click still follows at once. One element beside the editor root
   * (renderAll empties the root), placed under the link's first span, hidden when the caret
   * leaves, the note scrolls or the dialog opens. */
  function setupLinkPill() {
    const pane = $('editor-pane');
    const pill = el('div', { id: 'link-pill', 'data-test': 'link-pill', hidden: true });
    pane.appendChild(pill);
    const hide = () => { pill.hidden = true; pill._key = null; };
    let raf = 0;
    const update = () => {
      raf = 0;
      if (!S.note || isSpecial() || !S.editor) return hide();
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount || !sel.isCollapsed) return hide();
      const ctx = S.editor.linkContext();
      if (!ctx || !ctx.link) return hide();
      const link = ctx.link;
      const node = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentNode;
      let span = node && node.closest ? node.closest('.md-link, .md-wiki') : null;
      if (!span) return hide();
      const cls = span.classList.contains('md-wiki') ? 'md-wiki' : 'md-link';
      while (span.previousSibling && span.previousSibling.nodeType === 1 && span.previousSibling.classList.contains(cls)) span = span.previousSibling;
      const key = ctx.b.id + ':' + link.start + ':' + link.href;
      if (pill._key !== key) {
        pill._key = key;
        pill.innerHTML = '';
        const isNote = link.href.startsWith('note:');
        const shown = isNote ? link.href.slice(5) : link.href;
        const btn = (label, title, fn, test) => el('button', { title, 'data-test': test, onmousedown: (e) => e.preventDefault(), onclick: fn }, label);
        pill.append(
          el('span', { class: 'lp-href', dir: 'ltr', title: link.href }, shown),
          btn(isNote ? 'Open note' : 'Follow \u2197', isNote ? 'Open this note' : 'Follow the link: ' + link.href + ' (Ctrl+click does it at once)', () => { hide(); openLink(link.href); }, 'lp-open'),
          btn('Edit', 'Change the text or the address (Ctrl+K)', () => { hide(); linkDialog(); }, 'lp-edit'),
          btn('Copy', 'Copy the address', () => { FS.copyText(isNote ? shown : link.href); FS.toast('Link copied', 'ok'); }, 'lp-copy'),
          btn('Unlink', 'Keep the text, drop the link', () => { hide(); S.editor.replaceRange(ctx.body, ctx.b, link.start, link.end, link.text); }, 'lp-unlink'));
      }
      const r = span.getBoundingClientRect(), pr = pane.getBoundingClientRect();
      pill.hidden = false;
      let left = r.left - pr.left;
      if (left + pill.offsetWidth > pr.width - 8) left = Math.max(8, pr.width - pill.offsetWidth - 8);
      pill.style.left = left + 'px';
      pill.style.top = (r.bottom - pr.top + 4) + 'px';
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(update); };
    document.addEventListener('selectionchange', schedule);
    $('editor').addEventListener('scroll', hide, { passive: true });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pill.hidden) hide(); });
  }

  /* Every keyboard shortcut in one place (Ctrl+/ and Settings), so they can be found. */
  const SHORTCUTS = [
    ['Notes', [['Ctrl+N', 'New note'], ['Ctrl+Shift+N', 'New example collection'], ['Ctrl+S', 'Save now (notes save by themselves)'], ['F2', 'Rename the note (its title)'], ['Ctrl+Shift+F', 'Search the notebook'], ['Ctrl+F', 'Find in the note (Enter / Shift+Enter: next / previous)'], ['Ctrl+,', 'Settings'], ['Ctrl+\\', 'Show / hide the left panes'], ['Ctrl+/', 'This list']]],
    ['Text', [['Ctrl+B', 'Bold'], ['Ctrl+I', 'Italic'], ['Ctrl+E', 'Inline code'], ['Ctrl+Shift+X', 'Strikethrough'], ['Ctrl+Shift+H', 'Highlight'], ['Ctrl+K', 'Insert or edit a link'], ['Ctrl+Z / Ctrl+Y', 'Undo / redo (Ctrl+Shift+Z too)'], ['Ctrl+A', 'Select the block; again: the whole note'], ['Ctrl+click', 'Follow a link']]],
    ['Blocks', [['Enter', 'New paragraph / list item'], ['Shift+Enter', 'Line break inside the block'], ['Ctrl+Enter', 'New paragraph below the block'], ['Ctrl+Shift+Enter', 'New paragraph above the block'], ['Ctrl+D', 'Duplicate the block (or the selected blocks)'], ['Alt+Shift+↑ / ↓', 'Move the block or the selected blocks'], ['Shift+click, Shift+↑ / ↓', 'Select across blocks'], ['/', 'The insert menu, on an empty line'], ['Esc', 'Leave the block / clear the selection']]],
    ['Headings & lists', [['Ctrl+Alt+1 … 6', 'Heading 1 … 6'], ['Ctrl+Alt+0', 'Plain text (no heading, list or quote)'], ['Ctrl+Alt+[ / ]', 'Promote / demote every heading (note or selection)'], ['Ctrl+Shift+8', 'Bulleted list'], ['Ctrl+Shift+7', 'Numbered list'], ['Ctrl+Shift+9', 'Checklist'], ['Tab / Shift+Tab', 'List item in / out (also Ctrl+] / Ctrl+[)']]],
    ['FLEx & tables', [['Ctrl+Shift+L', 'Insert a FLEx object'], ['Ctrl+Shift+K', 'Search the text charts'], ['Ctrl+V', 'Paste FLEx rows or a FLEx link as an example; a grid as a table'], ['Tab (in a table)', 'Next cell; at the end, a new row'], ['Alt+↑ / ↓ (in a cell)', 'The cell above / below'], ['Esc (while playing)', 'Stop playback']]],
  ];
  function shortcutsDialog() {
    const m = FS.modal({ title: 'Keyboard shortcuts', class: 'shortcuts-dlg' });
    for (const [group, rows] of SHORTCUTS) {
      const t = el('table', { class: 'shortcuts' });
      for (const [k, what] of rows) t.appendChild(el('tr', {}, el('td', {}, ...k.split(' / ').flatMap((p, i) => [i ? ' / ' : null, el('kbd', {}, p)])), el('td', {}, what)));
      m.body.append(el('h3', {}, group), t);
    }
    m.body.appendChild(el('p', { class: 'small muted' }, 'On a Mac, Cmd stands in for Ctrl.'));
  }
  FS.shortcutsDialog = shortcutsDialog;

  /* Heading levels 1-6 (Seth, 2026-10-16), plain text, and folding every heading at once. The
   * buttons act on mousedown so the caret stays where it is in the note. */
  /* Promote / demote every heading of the note or the selection, and say what happened. */
  function shiftHeadings(ed, dir) {
    const r = ed.shiftHeadings(dir);
    const where = r.scope === 'selection' ? 'in the selection' : 'in the note';
    if (!r.n) FS.toast('No headings ' + where, 'warn');
    else if (r.blocked) FS.toast('A heading ' + where + ' is already at level ' + r.blocked + ' \u2014 ' + (dir < 0 ? 'promoting' : 'demoting') + ' would merge two levels', 'warn');
    else FS.toast(r.n + (r.n === 1 ? ' heading ' : ' headings ') + (dir < 0 ? 'promoted' : 'demoted') + ' ' + where, 'ok');
  }
  function headingMenu(btn, ed) {
    FS.popover(btn, (pop, close) => {
      const act = (fn) => (e) => { e.preventDefault(); close(); fn(); };
      const cur = ed.active && ed.active.type === 'h' ? FS.markdown.headingLevel(ed.active) : 0;
      for (let lv = 1; lv <= 6; lv++) {
        pop.appendChild(FS.el('button', { class: 'menu-item heading-pick hp' + lv + (lv === cur ? ' on' : ''), 'data-test': 'heading-' + lv, onmousedown: act(() => ed.linePrefix('h', lv)) },
          FS.el('span', { class: 'hp-label' }, 'Heading ' + lv), FS.el('kbd', {}, 'Ctrl+Alt+' + lv)));
      }
      if (cur) pop.appendChild(FS.el('button', { class: 'menu-item', onmousedown: act(() => ed.linePrefix('h', cur)) }, 'Plain text'));
      pop.appendChild(FS.el('hr'));
      // every heading one level up or down, in the selection or the whole note (Seth, 2026-10-18)
      const where = ed.msel ? 'in the selection' : 'in the note';
      pop.appendChild(FS.el('button', { class: 'menu-item heading-pick', 'data-test': 'promote-all', title: 'Every heading one level up (H2 \u2192 H1); the levels keep their distances', onmousedown: act(() => shiftHeadings(ed, -1)) }, FS.el('span', {}, '\u21e4 Promote all headings ' + where), FS.el('kbd', {}, 'Ctrl+Alt+[')));
      pop.appendChild(FS.el('button', { class: 'menu-item heading-pick', 'data-test': 'demote-all', title: 'Every heading one level down (H1 \u2192 H2)', onmousedown: act(() => shiftHeadings(ed, 1)) }, FS.el('span', {}, '\u21e5 Demote all headings ' + where), FS.el('kbd', {}, 'Ctrl+Alt+]')));
      pop.appendChild(FS.el('hr'));
      pop.appendChild(FS.el('button', { class: 'menu-item', 'data-test': 'fold-all', onmousedown: act(() => ed.setAllFolds(true)) }, '\u25b8 Collapse all headings'));
      pop.appendChild(FS.el('button', { class: 'menu-item', 'data-test': 'unfold-all', onmousedown: act(() => ed.setAllFolds(false)) }, '\u25be Expand all headings'));
      pop.appendChild(FS.el('hr'));
      pop.appendChild(FS.el('button', { class: 'menu-item', 'data-test': 'sticky-toggle', title: 'Keep the headings above the part of the note in view at the top of the window; their \u25be collapses the section in place', onmousedown: act(toggleSticky) }, (stickyOn() ? '\u2713 ' : '\u2003 ') + 'Sticky headings'));
    }, { class: 'heading-menu' });
  }

  /* ------------------------------------------------------------------ find in note */
  function openFind() { const bar = $('findbar'); bar.hidden = false; const inp = $('find-input'); inp.focus(); inp.select(); doFind(); }
  function closeFind() { $('findbar').hidden = true; if (S.editor) S.editor.find(''); $('find-count').textContent = ''; }
  function doFind() { if (!S.editor) return; const n = S.editor.find($('find-input').value); $('find-count').textContent = n ? n + ' found' : ($('find-input').value ? 'none' : ''); if (n) S.editor.findNext(1); }

  /* ------------------------------------------------------------------ settings */
  function openSettings() {
    const m = FS.modal({ title: 'Settings' });
    const body = m.body;
    // notebook
    const nb = el('div', { class: 'setting-block' }, el('h3', {}, 'Notebook'), el('div', { class: 'muted small' }, S.init.notebook));
    const row = el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } });
    if (S.init.canBrowse) row.appendChild(el('button', { class: 'btn', onclick: async () => { const r = await FS.api.choose_notebook_folder(); if (r) { m.close(); S.note = null; $('editor-pane').classList.add('no-note'); applyInit(r); } } }, 'Choose folder…'));
    if (S.init.canBrowse) row.appendChild(el('button', { class: 'btn', onclick: () => FS.api.reveal_notebook() }, 'Show in Explorer'));
    row.appendChild(el('button', { class: 'btn', onclick: async () => { applyInit(await FS.api.rescan()); FS.toast('Rescanned'); } }, 'Rescan files'));
    nb.appendChild(row);
    const move = el('div', { class: 'btn-row', style: { justifyContent: 'flex-start', marginTop: '8px' } });
    if (S.init.canBrowse) move.appendChild(el('button', { class: 'btn', onclick: async () => { try { const p = await FS.api.export_notebook_zip(); if (p) FS.toast('Saved ' + p, 'ok'); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Export notebook (.zip)…'));
    if (S.init.canBrowse) move.appendChild(el('button', { class: 'btn', onclick: async () => { try { const r = await FS.api.import_notebook_zip(); if (r) { m.close(); S.note = null; $('editor-pane').classList.add('no-note'); applyInit(r); } } catch (e) { FS.toast(e.message, 'error'); } } }, 'Import notebook from .zip…'));
    nb.appendChild(move);
    nb.appendChild(el('p', { class: 'muted small' }, 'The notebook is a plain folder of markdown files (the FLEx snapshots and audio clips live in its .scratchpad folder). To move it to another computer, copy the folder or export it as a zip and import it there. To sync it, put the folder inside a cloud-synced folder (Google Drive, OneDrive, Dropbox) and choose it here on each machine: the app watches the folder and picks up changes made elsewhere. If two machines edit the same note at once the sync client keeps a conflicted copy, which shows up as a second note.'));
    const dia = el('input', { type: 'checkbox', checked: !!(S.config.settings || {}).diacriticsInsensitive });
    dia.addEventListener('change', async () => { S.config.settings = await FS.api.set_setting('diacriticsInsensitive', dia.checked); });
    nb.appendChild(el('label', { class: 'small', style: { display: 'flex', gap: '6px', marginTop: '8px' } }, dia, 'Search ignores diacritics (ā = a)'));
    const mk = el('input', { type: 'checkbox', checked: !!(S.config.settings || {}).hideMarkers });
    mk.addEventListener('change', async () => { S.config.settings = await FS.api.set_setting('hideMarkers', mk.checked); applyMarkers(); });
    nb.appendChild(el('label', { class: 'small', style: { display: 'flex', gap: '6px', marginTop: '8px' } }, mk, 'Hide Markdown markers while editing (**bold**, # heading, - list) — the toolbar still formats, and typing the markers still works'));
    const gb = el('input', { type: 'checkbox', checked: gapBarOn(), 'data-test': 'setting-gapbar' });
    gb.addEventListener('change', async () => { S.config.settings = await FS.api.set_setting('gapBar', gb.checked); applyGapBar(); });
    nb.appendChild(el('label', { class: 'small', style: { display: 'flex', gap: '6px', marginTop: '8px' } }, gb, 'Show the bar between blocks when the pointer rests in a gap (+ Paragraph, + Example, + Table, \u2212 Above / \u2212 Below; the right-click and \u22ee menus insert blocks either way)'));
    const sh = el('input', { type: 'checkbox', checked: stickyOn(), 'data-test': 'setting-sticky' });
    sh.addEventListener('change', async () => { S.config.settings = await FS.api.set_setting('stickyHeadings', sh.checked); applySticky(); });
    nb.appendChild(el('label', { class: 'small', style: { display: 'flex', gap: '6px', marginTop: '8px' } }, sh, 'Sticky headings: keep the headings above the part of the note in view at the top of the window (their \u25be collapses the section in place)'));
    body.appendChild(nb);
    // FLEx
    body.appendChild(el('div', { class: 'setting-block' }, el('h3', {}, 'Keyboard shortcuts'),
      el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } }, el('button', { class: 'btn', 'data-test': 'open-shortcuts', onclick: () => { m.close(); shortcutsDialog(); } }, 'Keyboard shortcuts\u2026 (Ctrl+/)'))));
    body.appendChild(el('div', { class: 'setting-block' }, el('h3', {}, 'Backup & storage'),
      el('p', { class: 'muted small' }, 'Back the notebook up to a OneDrive, Google Drive or Dropbox folder, or to S3-compatible storage; see how much space the notebook and its backup take, and clean up.'),
      el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } }, el('button', { class: 'btn primary', 'data-test': 'open-backup', onclick: () => { m.close(); openBackup(); } }, 'Backup & storage…'))));
    body.appendChild(el('div', { class: 'setting-block' }, el('h3', {}, 'FLEx text markup tags'),
      el('p', { class: 'muted small' }, 'Tags from FieldWorks\u2019 Text Tagging view are drawn under the words of an example. How each tag looks can be set for the whole project here, for a tab or a folder (their right-click menus), or for chosen examples (the \u2691 on an example, or a selection); the most specific setting wins.'),
      el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } },
        el('button', { class: 'btn', 'data-test': 'open-tag-styles', onclick: () => { m.close(); FS.tagstyles.dialog({ kind: 'project', key: (S.flex && S.flex.project) || '', label: 'the project' + (S.flex && S.flex.project ? ' \u201c' + S.flex.project + '\u201d' : '') }); } }, 'Tag styles for this project\u2026'),
        el('button', { class: 'btn', 'data-test': 'open-tag-filters', onclick: () => { m.close(); FS.tagstyles.filtersDialog(); } }, 'Visual filters\u2026'))));
    const fx = el('div', { class: 'setting-block' }, el('h3', {}, 'FieldWorks project'));
    const source = el('select');
    for (const [v, l] of [['lcm', 'FieldWorks project (direct, via flexicon)'], ['flextext', '.flextext export file (fallback)'], ['demo', 'Built-in demo project']]) source.appendChild(el('option', { value: v, selected: (S.flex.source || 'lcm') === v }, l));
    const project = el('select');
    const projectRow = el('div', { class: 'form-row' }, el('label', {}, 'Project'), el('div', { style: { display: 'flex', gap: '6px' } }, project, el('button', { class: 'btn', onclick: loadProjects }, 'List')));
    const fileRow = el('div', { class: 'form-row' }, el('label', {}, '.flextext file'), el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center' } }, el('span', { class: 'small muted', id: 'ft-path' }, S.flex.flextextPath || '(none)'), el('button', { class: 'btn', onclick: async () => { const r = await FS.api.flex_choose_file(); if (r && r.path) { S.flex.flextextPath = r.path; body.querySelector('#ft-path').textContent = r.path; } } }, 'Choose…')));
    const status = el('div', { class: 'small muted' });
    async function loadProjects() {
      project.innerHTML = '<option>Loading…</option>';
      try {
        const names = await FS.api.flex_projects();
        project.innerHTML = '';
        for (const n of names) project.appendChild(el('option', { value: n, selected: n === S.flex.project }, n));
        if (!names.length) project.appendChild(el('option', { value: '' }, '(no projects found)'));
      } catch (e) { project.innerHTML = ''; project.appendChild(el('option', { value: S.flex.project || '' }, S.flex.project || '')); status.textContent = e.message; }
    }
    const updateRows = () => { projectRow.style.display = source.value === 'lcm' ? '' : 'none'; fileRow.style.display = source.value === 'flextext' ? '' : 'none'; };
    source.addEventListener('change', updateRows); updateRows();
    if (S.flex.project) project.appendChild(el('option', { value: S.flex.project, selected: true }, S.flex.project));
    const connect = el('button', { class: 'btn primary', onclick: async () => {
      status.textContent = 'Opening…';
      try {
        S.flex = await FS.api.flex_configure(source.value, source.value === 'lcm' ? project.value : (source.value === 'demo' ? 'Kalu Demo' : ''), S.flex.flextextPath || '');
        renderFlexPill(); FS.interlinear.invalidate();
        status.textContent = S.flex.open ? 'Connected: ' + S.flex.project + (S.flex.texts != null ? ' (' + S.flex.texts + ' texts, ' + S.flex.entries + ' entries)' : '') : (S.flex.error || 'Not connected');
        if (S.note) ensureEditor().load(S.note.body);
      } catch (e) { status.textContent = e.message; }
    } }, 'Connect');
    fx.append(el('div', { class: 'form-row' }, el('label', {}, 'Source'), source), projectRow, fileRow, el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } }, connect, el('button', { class: 'btn', onclick: async () => { S.flex = await FS.api.flex_refresh(); renderFlexPill(); FS.interlinear.invalidate(); FS.toast('Reloaded from FLEx'); } }, 'Reload data')), status);
    // audio tooling: ffmpeg turns any media into cached FLAC slices
    const ffRow = el('div', { class: 'form-row' }, el('label', {}, 'ffmpeg'));
    const ffIn = el('input', { type: 'text', value: (S.config.settings || {}).ffmpegPath || '', placeholder: 'auto-detect (PATH, winget, C:\\ffmpeg)', style: { width: '260px' } });
    const ffSt = el('span', { class: 'small muted' });
    const ffCheck = async () => { try { const r = await FS.api.audio_tools(); ffSt.textContent = r.ffmpeg ? '✓ ' + r.ffmpeg + ' — clips are cached as FLAC' : '○ not found — clips are cut from WAV files only (stdlib); other formats are recorded while they play'; } catch (e) { ffSt.textContent = e.message; } };
    ffIn.addEventListener('change', async () => { S.config.settings = await FS.api.set_setting('ffmpegPath', ffIn.value.trim()); ffCheck(); });
    ffRow.appendChild(el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' } }, ffIn, ffSt));
    fx.appendChild(ffRow);
    ffCheck();
    // flexscratchpad://note/<id> links (from FLEx notes, documents, the browser) open the note here
    const lkSt = el('span', { class: 'small muted' }, 'A “Copy link to this note” link opens the note in this app once the scheme is registered (done at start on Windows).');
    fx.appendChild(el('div', { class: 'form-row' }, el('label', {}, 'Note links'), el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' } }, el('button', { class: 'btn', onclick: async () => { try { const ok = await FS.api.register_links(); lkSt.textContent = ok ? '✓ flexscratchpad:// links are registered for this user' : '○ could not register here (Windows only)'; } catch (e) { lkSt.textContent = e.message; } } }, 'Register flexscratchpad:// links'), lkSt)));
    const st0 = flexState();
    if (st0.level !== 'ok') { const ex = el('div', { class: 'flex-explain' }, el('div', { class: 'small' }, el('b', {}, (st0.level === 'warn' ? '⚠ ' : st0.level === 'err' ? '✖ ' : '') + st0.title), ' ', st0.text || '')); if (st0.fix) ex.appendChild(el('div', { class: 'fix' }, el('b', {}, 'How to fix it'), el('ol', {}, ...st0.fix.map((x) => el('li', {}, x))))); fx.appendChild(ex); }
    fx.appendChild(el('p', { class: 'muted small' }, 'Reading the project directly needs FieldWorks installed on this computer plus the flexicon and pythonnet packages (pip install "flex-scratchpad[flex]"). If FLEx is open at the same time, turn on Project Properties → Sharing → “Share project contents with programs on this computer”.'));
    if (S.flex.error) fx.appendChild(el('p', { class: 'small', style: { color: 'var(--danger)' } }, S.flex.error));
    body.appendChild(fx);
    // tabs
    const tb = el('div', { class: 'setting-block list-editor' }, el('h3', {}, 'Tabs'));
    for (const t of S.config.tabs) {
      const name = el('input', { type: 'text', value: t.name });
      name.addEventListener('change', async () => { await FS.api.update_tab(t.dir, { name: name.value }); applyInit(await FS.api.init()); });
      const color = el('input', { type: 'color', value: t.color });
      color.addEventListener('change', async () => { await FS.api.update_tab(t.dir, { color: color.value }); applyInit(await FS.api.init()); });
      tb.appendChild(el('div', { class: 'item' }, color, name, el('span', { class: 'muted small' }, t.dir)));
    }
    tb.appendChild(el('button', { class: 'btn', onclick: () => { m.close(); addTab(); } }, '+ New tab'));
    body.appendChild(tb);
    // tags
    const tg = el('div', { class: 'setting-block list-editor' }, el('h3', {}, 'Tags'), el('div', { class: 'muted small' }, 'Configured tags get a colour and show in the picker; tags typed as #word in a note appear automatically.'));
    const tagList = (S.config.tags || []).map((t) => Object.assign({}, t));
    const renderTags = () => {
      tg.querySelectorAll('.item, .btn').forEach((x) => x.remove());
      tagList.forEach((t, i) => {
        const name = el('input', { type: 'text', value: t.name });
        name.addEventListener('change', async () => { const old = t.name; t.name = name.value.trim().replace(/^#/, ''); if (old && t.name && old !== t.name) { await FS.api.rename_tag(old, t.name); } await FS.api.set_tags(tagList); applyInit(await FS.api.init()); });
        const color = el('input', { type: 'color', value: t.color || '#6b7280' });
        color.addEventListener('change', async () => { t.color = color.value; await FS.api.set_tags(tagList); applyInit(await FS.api.init()); });
        tg.appendChild(el('div', { class: 'item' }, color, name, el('button', { class: 'icon-btn', title: 'Remove from the configured list', onclick: async () => { tagList.splice(i, 1); await FS.api.set_tags(tagList); applyInit(await FS.api.init()); renderTags(); } }, '✕')));
      });
      tg.appendChild(el('button', { class: 'btn', onclick: async () => { const n = prompt('Tag name'); if (n && n.trim()) { tagList.push({ name: n.trim().replace(/^#/, ''), color: '#2a6e2a' }); await FS.api.set_tags(tagList); applyInit(await FS.api.init()); renderTags(); } } }, '+ New tag'));
    };
    renderTags();
    body.appendChild(tg);
    body.appendChild(el('p', { class: 'muted small' }, S.init.app + ' ' + S.init.version + (S.init.build ? ' (build ' + S.init.build + ')' : '') + ' · ' + (S.init.platform || '')));
  }
  async function addTab() {
    const name = prompt('New tab name');
    if (!name || !name.trim()) return;
    try { const t = await FS.api.add_tab(name.trim()); S.tab = t.dir; S.folder = null; applyInit(await FS.api.init()); } catch (e) { FS.toast(e.message, 'error'); }
  }

  /* ------------------------------------------------------------------ panes
   * Both navigation columns can be dragged narrower or wider (widths remembered), collapsed
   * one at a time by double-clicking their splitter, or hidden together with the « button /
   * Ctrl+\ and brought back with the ☰ handle that then appears in the editor pane. */
  const PANES = { rail: { min: 170, max: 480, dflt: 240 }, list: { min: 200, max: 640, dflt: 300 } };
  function paneState() {
    try { return JSON.parse(localStorage.getItem('fs:panes') || '{}'); } catch (e) { return {}; }
  }
  function savePanes(st) { try { localStorage.setItem('fs:panes', JSON.stringify(st)); } catch (e) { /* ignore */ } }
  function applyPanes() {
    const st = paneState();
    const app = $('app');
    for (const k of ['rail', 'list']) {
      const w = Math.min(PANES[k].max, Math.max(PANES[k].min, +st[k + 'W'] || PANES[k].dflt));
      document.documentElement.style.setProperty('--' + k + '-w', w + 'px');
      app.classList.toggle(k + '-collapsed', !!st[k + 'Collapsed']);
    }
  }
  function setupPanes() {
    applyPanes();
    const start = (k, e) => {
      e.preventDefault();
      const sp = $('split-' + k);
      const st = paneState();
      if (st[k + 'Collapsed']) { st[k + 'Collapsed'] = false; savePanes(st); applyPanes(); }
      const startX = e.clientX;
      const startW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--' + k + '-w')) || PANES[k].dflt;
      // the drag styling (and the pointer-events lock) only once the mouse really moves, so a
      // double-click on the splitter still reaches the splitter
      let moved = false;
      const move = (ev) => {
        if (!moved) { if (Math.abs(ev.clientX - startX) < 3) return; moved = true; sp.classList.add('dragging'); document.body.classList.add('resizing'); }
        const w = Math.min(PANES[k].max, Math.max(PANES[k].min, startW + ev.clientX - startX)); document.documentElement.style.setProperty('--' + k + '-w', w + 'px');
      };
      const up = (ev) => {
        document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
        sp.classList.remove('dragging'); document.body.classList.remove('resizing');
        if (!moved) return;
        const s2 = paneState(); s2[k + 'W'] = Math.min(PANES[k].max, Math.max(PANES[k].min, startW + ev.clientX - startX)); savePanes(s2);
      };
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    };
    for (const k of ['rail', 'list']) {
      const sp = $('split-' + k);
      sp.addEventListener('mousedown', (e) => start(k, e));
      sp.addEventListener('dblclick', () => togglePane(k));
    }
    $('btn-nav').addEventListener('click', () => toggleNav());
    $('btn-nav-hide').addEventListener('click', () => toggleNav(true));
    setupRail();
  }
  /* The rail's parts (Seth, 2026-10-18): each header folds its part (a click), a divider drags
   * room between the two parts it separates (double-click: back to automatic), all remembered on
   * this computer — and no part can ever vanish: its header stays, a fold is one click away. */
  const RAIL_SECS = ['tabs', 'folders', 'tags', 'ftags'];
  function railState() { try { return JSON.parse(localStorage.getItem('fs:rail') || '{}'); } catch (e) { return {}; } }
  function saveRail(st) { try { localStorage.setItem('fs:rail', JSON.stringify(st)); } catch (e) { /* ignore */ } }
  function railSection(sec) { return $(sec + '-section'); }
  function applyRail() {
    const st = railState(), sizes = st.sizes || {}, folded = st.collapsed || {};
    const visible = RAIL_SECS.filter((k) => railSection(k) && !railSection(k).hidden);
    const open = visible.filter((k) => !folded[k]);
    const last = open[open.length - 1];
    for (const k of RAIL_SECS) {
      const sec = railSection(k);
      if (!sec) continue;
      sec.classList.toggle('collapsed', !!folded[k]);
      sec.classList.remove('auto');
      const h4 = sec.querySelector('h4');
      if (h4) h4.title = folded[k] ? 'Show ' + k.replace('ftags', 'FLEx tags') : 'Hide this part (its header stays)';
      if (folded[k]) { sec.style.flex = ''; continue; }
      const px = +sizes[k];
      if (px > 0) sec.style.flex = (k === last ? '1 1 ' : '0 0 ') + Math.round(px) + 'px';
      else if (k === 'tabs' || k === 'folders') { sec.style.flex = ''; sec.classList.add('auto'); }
      else sec.style.flex = '';
    }
    // a divider only between two visible parts
    const divs = [...document.querySelectorAll('#rail-body .rail-divider')];
    divs.forEach((d, i) => { const below = visible.includes(RAIL_SECS[i + 1]); d.hidden = !below; });
  }
  function setupRail() {
    applyRail();
    for (const k of RAIL_SECS) {
      const sec = railSection(k);
      if (!sec) continue;
      sec.querySelector('h4').addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const st = railState(); st.collapsed = st.collapsed || {}; st.collapsed[k] = !st.collapsed[k];
        if (st.sizes) delete st.sizes[k];
        saveRail(st); applyRail();
      });
    }
    const divs = [...document.querySelectorAll('#rail-body .rail-divider')];
    divs.forEach((d, i) => {
      const pair = () => {
        // the nearest open part above and below this divider
        const st = railState(), folded = st.collapsed || {};
        const vis = (k) => railSection(k) && !railSection(k).hidden && !folded[k];
        let a = i, b = i + 1;
        while (a >= 0 && !vis(RAIL_SECS[a])) a--;
        while (b < RAIL_SECS.length && !vis(RAIL_SECS[b])) b++;
        return a >= 0 && b < RAIL_SECS.length ? [RAIL_SECS[a], RAIL_SECS[b]] : null;
      };
      d.addEventListener('mousedown', (e) => {
        const p = pair();
        if (!p || e.button !== 0) return;
        e.preventDefault();
        const [ka, kb] = p, A = railSection(ka), B = railSection(kb);
        const hA = A.getBoundingClientRect().height, hB = B.getBoundingClientRect().height, y0 = e.clientY;
        const minH = (sec) => sec.querySelector('h4').getBoundingClientRect().height + 12;
        let moved = false;
        const move = (ev) => {
          if (!moved) { if (Math.abs(ev.clientY - y0) < 3) return; moved = true; d.classList.add('dragging'); document.body.classList.add('resizing'); }
          const na = Math.min(hA + hB - minH(B), Math.max(minH(A), hA + ev.clientY - y0));
          const st = railState(); st.sizes = st.sizes || {}; st.sizes[ka] = na; st.sizes[kb] = hA + hB - na;
          saveRail(st); applyRail();
        };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); d.classList.remove('dragging'); document.body.classList.remove('resizing'); };
        document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
      });
      d.addEventListener('dblclick', () => { const p = pair(); if (!p) return; const st = railState(); if (st.sizes) { delete st.sizes[p[0]]; delete st.sizes[p[1]]; } saveRail(st); applyRail(); });
    });
  }
  function togglePane(k, collapsed) {
    const st = paneState();
    st[k + 'Collapsed'] = collapsed == null ? !st[k + 'Collapsed'] : !!collapsed;
    savePanes(st); applyPanes();
  }
  function toggleNav(hide) {
    const st = paneState();
    const both = hide == null ? !(st.railCollapsed && st.listCollapsed) : !!hide;
    st.railCollapsed = both; st.listCollapsed = both;
    savePanes(st); applyPanes();
  }

  /* ------------------------------------------------------------------ wiring */
  function wire() {
    setupPanes();
    $('search').addEventListener('input', runSearch);
    $('search').addEventListener('keydown', (e) => { if (e.key === 'Escape') { clearSearch(); renderRail(); renderList(); } });
    $('btn-new-note').addEventListener('click', newNote);
    $('btn-new-menu').addEventListener('click', (e) => FS.popover(e.currentTarget, (pop, close) => {
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); newNote(); } }, 'New note', el('span', { class: 'muted small' }, '  Ctrl+N')));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'new-collection', title: 'A note that is just interlinear examples, numbered in order — the kind that exports as a FLEx text', onclick: () => { close(); newCollection('', ''); } }, 'New example collection'));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'new-rule-collection', title: 'A collection of every line in the project that carries the FLEx text markup tags you choose; later it can take in the new matches', onclick: () => { close(); ruleCollectionDialog({}); } }, 'New collection from tagged lines\u2026'));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'new-concordance', title: 'Open the CSV FieldWorks writes with File › Export Concordance Results…: every line it lists becomes an example', onclick: () => { close(); concordanceDialog(); } }, 'New collection from a FLEx concordance export…'));
      pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'new-chart-note', title: 'A note that is one FieldWorks text chart, with your own columns (choice lists, notes, rules) and styles', onclick: () => { close(); newChartNoteDialog(); } }, 'New chart note\u2026'));
    }));
    $('btn-add-tab').addEventListener('click', addTab);
    $('btn-add-folder').addEventListener('click', () => newFolder(S.tab, S.folder || ''));
    $('chk-subfolders').addEventListener('change', (e) => setSubfolders(e.target.checked));
    $('btn-edit-tags').addEventListener('click', openSettings);
    $('btn-filters').addEventListener('click', (e) => FS.tagstyles.filtersPopover(e.currentTarget));
    $('btn-settings').addEventListener('click', openSettings);
    $('flex-pill').addEventListener('click', (e) => flexStatusPopover(e.currentTarget));
    $('flex-banner-fix').addEventListener('click', openSettings);
    $('flex-banner-retry').addEventListener('click', retryFlex);
    $('flex-banner-hide').addEventListener('click', () => { sessionStorage.setItem('fs:flexBannerHidden', '1'); $('flex-banner').hidden = true; });
    $('btn-sort').addEventListener('click', (e) => FS.popover(e.currentTarget, (pop, close) => { for (const [v, l] of [['updated', 'Last edited'], ['created', 'Date created'], ['title', 'Title']]) pop.appendChild(el('button', { class: 'menu-item' + (S.sort === v ? ' on' : ''), onclick: () => { S.sort = v; close(); renderList(); } }, (S.sort === v ? '✓ ' : '') + l)); }));
    $('note-title').addEventListener('input', () => { if (S.note) { S.note.title = $('note-title').value; S.dirty = true; scheduleSave(); } });
    $('note-title').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (!isSpecial()) ensureEditor().focusBlock(0, 0); else e.target.blur(); } });
    $('btn-pin').addEventListener('click', () => { if (!S.note) return; S.note.pinned = !S.note.pinned; saveMeta({ pinned: S.note.pinned }); refreshLists(); });
    $('btn-note-menu').addEventListener('click', (e) => { if (S.note) noteMenu(e.currentTarget, S.note); });
    $('btn-insert-flex').addEventListener('click', insertFlex);
    $('btn-chart-search').addEventListener('click', () => FS.searchCharts());
    $('backup-pill').addEventListener('click', openBackup);
    $('btn-attach').addEventListener('click', (e) => attachFiles(e.altKey));
    $('btn-attach-more').addEventListener('click', (e) => attachMenu(e.currentTarget));
    // A file dropped anywhere the note does not take it must never replace the page with the
    // file (WebView2 would navigate to it): refuse the drop there.
    document.addEventListener('dragover', (e) => { if (!e.defaultPrevented && FS.files.hasFiles(e.dataTransfer)) { e.preventDefault(); e.dataTransfer.dropEffect = 'none'; } });
    document.addEventListener('drop', (e) => { if (!e.defaultPrevented && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) e.preventDefault(); });
    $('toolbar').querySelectorAll('[data-ins]').forEach((b) => b.addEventListener('mousedown', (e) => { e.preventDefault(); toolbarAction(b.dataset.ins, b); }));
    setupLinkPill();
    $('btn-find').addEventListener('click', openFind);
    $('btn-markers').addEventListener('click', toggleMarkers);
    $('btn-refresh-all').addEventListener('click', refreshAll);
    $('find-input').addEventListener('input', doFind);
    $('find-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); S.editor.findNext(e.shiftKey ? -1 : 1); } if (e.key === 'Escape') closeFind(); });
    $('find-next').addEventListener('click', () => S.editor && S.editor.findNext(1));
    $('find-prev').addEventListener('click', () => S.editor && S.editor.findNext(-1));
    $('find-close').addEventListener('click', closeFind);
    $('btn-undo').addEventListener('mousedown', (e) => { e.preventDefault(); if (S.editor) S.editor.undoStep(); });
    $('btn-redo').addEventListener('mousedown', (e) => { e.preventDefault(); if (S.editor) S.editor.redoStep(); });
    document.addEventListener('keydown', (e) => {
      const mod = e.ctrlKey || e.metaKey;
      // Undo / redo for everything that is not a plain text field: the note's own history
      // (every change — typing, styling a word, a table edit, a collapse — is a snapshot).
      // Text blocks and widgets handle the keys themselves; inputs, the search box and a cell
      // being edited keep the browser's native undo.
      if (mod && !e.altKey && (e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) {
        const ae = document.activeElement;
        const native = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.classList.contains('cell-edit'));
        const own = ae && (ae.closest('.blk-body') || ae.classList.contains('widget'));
        if (!native && !own && S.note && S.editor && !isSpecial()) {
          e.preventDefault();
          if (e.key.toLowerCase() === 'y' || e.shiftKey) S.editor.redoStep(); else S.editor.undoStep();
          return;
        }
      }
      if (mod && e.key.toLowerCase() === 'n' && !e.shiftKey) { e.preventDefault(); newNote(); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'n') { e.preventDefault(); newCollection('', ''); }
      else if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') { if (S.note && !isSpecial()) { e.preventDefault(); linkDialog(); } }
      else if (mod && !e.altKey && e.code === 'Slash') { e.preventDefault(); shortcutsDialog(); }
      else if (e.key === 'F2' && !mod) { if (S.note) { e.preventDefault(); $('note-title').focus(); $('note-title').select(); } }
      else if (mod && e.shiftKey && !e.altKey && (e.code === 'Digit7' || e.code === 'Digit8' || e.code === 'Digit9')) { if (S.note && !isSpecial()) { e.preventDefault(); ensureEditor().linePrefix(e.code === 'Digit7' ? 'num' : e.code === 'Digit8' ? 'list' : 'task'); } }
      else if (mod && e.altKey && e.code === 'Digit0') { if (S.note && !isSpecial()) { e.preventDefault(); ensureEditor().plainText(); } }
      else if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'd') { const ed = S.editor; if (ed && ed.active && S.note && !isSpecial() && !(document.activeElement && document.activeElement.matches('input, textarea, .cell-edit'))) { e.preventDefault(); ed.duplicateBlocks(ed.active); } }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('search').focus(); $('search').select(); }
      else if (mod && !e.shiftKey && e.key.toLowerCase() === 'f') { if (S.note && !isSpecial()) { e.preventDefault(); openFind(); } }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'l') { if (S.note) { e.preventDefault(); if (isCollection()) ensureCollection().pick(); else if (!isChartNote()) insertFlex(); } }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); FS.searchCharts(); }
      else if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); flushSave().then(() => FS.toast('Saved')); }
      else if (mod && e.altKey && /^[1-6]$/.test(e.key)) { if (!isSpecial()) { e.preventDefault(); ensureEditor().linePrefix('h', +e.key); } }
      else if (mod && e.altKey && (e.key === '[' || e.key === ']')) { if (!isSpecial()) { e.preventDefault(); shiftHeadings(ensureEditor(), e.key === '[' ? -1 : 1); } }
      else if (mod && e.key === ',') { e.preventDefault(); openSettings(); }
      else if (mod && (e.key === '\\' || e.code === 'Backslash')) { e.preventDefault(); toggleNav(); }
    });
    window.addEventListener('beforeunload', () => { scheduleSave.flush(); });
    // Cloud-sync awareness: when files change on disk (another machine, a sync client), refresh
    // the lists, and reload the open note if it changed and has no unsaved edits here.
    let stamp = null;
    const checkDisk = async () => {
      if (document.hidden) return;
      try {
        const r = await FS.api.notebook_stamp();
        if (stamp === null) { stamp = r.stamp; return; }
        if (r.stamp === stamp) return;
        stamp = r.stamp;
        if (S.note && !S.dirty) {
          const fresh = await FS.api.note_changed_on_disk(S.note.id, S.note.updated);
          if (fresh && fresh.deleted) { S.note = null; $('editor-pane').classList.add('no-note'); FS.toast('This note was removed on disk'); }
          else if (fresh) { fresh.body = FS.flexcopy.strip(fresh.body || '', fresh.id); S.note = fresh; $('note-title').value = fresh.title || ''; ensureEditor().load(fresh.body || ''); renderNoteMeta(); FS.toast('Note updated from disk'); }
        } else if (S.note && S.dirty) { await flushSave(); }
        await refreshLists();
      } catch (e) { /* offline folder or a transient read error: try again next tick */ }
    };
    setInterval(checkDisk, 20000);
    window.addEventListener('focus', () => setTimeout(checkDisk, 300));
    // a progress message (opening, "Indexing texts… 40/140") shows in the pill while it lasts;
    // an empty one, or 20 s of silence, puts the connection state back (Seth, 2026-10-16: the
    // last progress line stuck in the tile next to the warning icon read as "indexing paused")
    let progressTimer = null;
    FS.on('py:progress', (d) => {
      const pill = $('flex-pill');
      clearTimeout(progressTimer);
      if (!d || !d.message) { renderFlexPill(); return; }
      pill.querySelector('.label').textContent = d.message;
      pill.classList.add('busy');
      progressTimer = setTimeout(() => renderFlexPill(), 20000);
    });
    document.addEventListener('click', (e) => { const a = e.target.closest('a[data-href], a.flex-chip, a.wikilink, a.ext-link'); if (a && !e.target.closest('.blk-body')) { e.preventDefault(); openLink(a.dataset.href || a.getAttribute('href')); } });
  }

  /* ------------------------------------------------------------------ welcome note */
  FS.flexUi = { flexState, flexPrompt, renderFlexPill, setFlex: (f) => { S.flex = f; renderFlexPill(); } };
  // a flexscratchpad://note/<id> link handed over by Python (see links.py)
  FS.openNoteById = async (id) => { try { await openNote(id); await refreshLists(); } catch (e) { FS.toast('That note is not in this notebook', 'warn'); } };
  FS.bringToFront = () => { try { window.focus(); } catch (e) { /* nothing to do */ } };
  /* A second start found this window running, but the code installed on disk is a different
   * build: this window keeps the old one until it is closed and started again. */
  FS.otherBuild = (installed, running) => {
    if (document.querySelector('.modal.other-build')) return;
    const m = FS.modal({ title: 'A different build is installed', class: 'narrow other-build' });
    m.body.append(
      el('p', {}, 'This window is running build ', el('b', {}, running), ', but build ', el('b', {}, installed), ' has been installed since it started.'),
      el('p', {}, 'Close FLEx Scratchpad and start it again to use the installed build. Your notes are saved.'),
      el('div', { class: 'btn-row' }, el('button', { class: 'btn primary', onclick: () => m.close() }, 'OK')));
  };
  FS.welcomeNote = () => [
    '# Welcome to FLEx Scratchpad',
    '',
    'A notebook for FieldWorks: tabs, folders, tags, tables and FieldWorks text charts, with **live FLEx objects** inside your notes.',
    '',
    '## Getting FLEx objects into a note',
    '- Press **Ctrl+Shift+L** (or the *FLEx object* button) to search the lexicon or the texts and insert an entry or a range of interlinear segments.',
    '- In FLEx, use *Edit → Copy Location as Hyperlink* and paste the link into a note.',
    '- Click a word in a rendered example to highlight, bold, underline or colour it; Shift+click a second word for a range.',
    '- The `↗ Open in FLEx` link jumps back to the object in FieldWorks.',
    '',
    '## Writing',
    '- Markdown, shown with its markers kept faint: **bold**, *italic*, ==highlight==, `code`, [[another note]], `#tags`.',
    '- `- [ ]` makes a checklist; `# ` a heading; `> ` a quote; `---` a divider. Type `/` on an empty line for a menu.',
    '- Tables: cells accept line breaks and FLEx examples; use the *Column ▾ / Row ▾ / Table ▾* buttons for styling.',
    '',
    '- [ ] Connect a FieldWorks project in Settings (the ⚙ button, or the FLEx pill at the bottom left)',
    '- [ ] Make a tab for each project or topic',
    '',
    '| Column | What goes here |',
    '|---|---|',
    '| Form | A vernacular form |',
    '| Example | An interlinear example inserted with Ctrl+Shift+L |',
    '{table: striped; col 1: bold}',
  ].join('\n');

  document.addEventListener('DOMContentLoaded', boot);
})();
