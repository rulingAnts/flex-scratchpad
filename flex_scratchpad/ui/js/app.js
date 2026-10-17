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
  async function toggleMarkers() {
    const hide = !((S.config.settings || {}).hideMarkers);
    try { S.config.settings = await FS.api.set_setting('hideMarkers', hide); } catch (e) { FS.toast(e.message, 'error'); return; }
    applyMarkers();
    FS.toast(hide ? 'Markdown markers hidden' : 'Markdown markers shown');
  }
  function applyInit(init) {
    S.init = init; S.config = init.config; S.notes = init.notes; S.folders = init.folders; S.tags = init.tags; S.flex = init.flex;
    applyMarkers();
    if (!S.tab || !S.config.tabs.some((t) => t.dir === S.tab)) S.tab = (S.config.tabs[0] || {}).dir || null;
    renderRail();
    renderList();
    renderFlexPill();
  }

  async function refreshLists() {
    const [notes, folders, tags] = await Promise.all([FS.api.list_notes(), FS.api.folders(), FS.api.tags()]);
    S.notes = notes; S.folders = folders; S.tags = tags;
    renderRail();
    if (S.query) await runSearch(); else renderList();
  }

  /* ------------------------------------------------------------------ rail */
  function renderRail() {
    const tabs = $('tabs');
    tabs.innerHTML = '';
    for (const t of S.config.tabs) {
      const count = S.notes.filter((n) => n.tab === t.dir).length;
      const item = el('div', { class: 'tab-item' + (S.tab === t.dir && !S.query ? ' active' : ''), draggable: 'true', dataset: { dir: t.dir } },
        el('span', { class: 'dot', style: { background: t.color } }), el('span', { class: 'label' }, t.name), el('span', { class: 'count' }, String(count)));
      item.addEventListener('click', () => { S.tab = t.dir; S.folder = null; S.tag = null; clearSearch(); renderRail(); renderList(); });
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
      item.addEventListener('click', () => { S.tag = S.tag === t.name ? null : t.name; renderRail(); if (S.query) runSearch(); else renderList(); });
      tags.appendChild(item);
    }
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
      item('Delete tab', async () => { if (!confirm('Delete the tab “' + t.name + '”? It must be empty.')) return; try { await FS.api.delete_tab(t.dir); S.tab = null; applyInit(await FS.api.init()); } catch (e) { FS.toast(e.message, 'error'); } }, 'danger');
    });
  }
  function folderMenu(anchor, path) {
    FS.popover(anchor, (pop, close) => {
      const item = (label, fn, cls) => pop.appendChild(el('button', { class: 'menu-item ' + (cls || ''), onclick: () => { close(); fn(); } }, label));
      item('New subfolder…', () => newFolder(S.tab, path));
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
    $('list-sub').textContent = S.results ? list.length + ' match' + (list.length === 1 ? '' : 'es') : [S.folder ? tabInfo.name + ' / ' + S.folder : '', S.tag ? '#' + S.tag : ''].filter(Boolean).join('  ·  ');
    if (!list.length && !S.results && !S.subfolders && below.length) {
      host.appendChild(el('div', { class: 'empty' }, el('b', {}, S.folder ? 'No notes directly in this folder' : 'No notes at the top of this tab'),
        el('button', { class: 'btn', 'data-test': 'show-below', onclick: () => setSubfolders(true) }, 'Show the ' + below.length + ' note' + (below.length === 1 ? '' : 's') + ' in its subfolders')));
      return;
    }
    if (!list.length) { host.appendChild(el('div', { class: 'empty' }, el('b', {}, S.results ? 'Nothing found' : 'No notes here'), S.results ? 'Try other words, or clear the tag filter.' : 'Press Ctrl+N to write one.')); return; }
    for (const n of list) {
      const card = el('div', { class: 'note-card' + (S.note && S.note.id === n.id ? ' active' : ''), draggable: 'true', dataset: { id: n.id } });
      card.appendChild(el('div', { class: 't' }, n.pinned ? el('span', { class: 'pin' }, '📌') : null, n.kind === 'examples' ? el('span', { class: 'kind-badge', title: 'Example collection: exports as a FLEx text' }, 'IGT') : null, n.title || 'Untitled'));
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
    if (!q && !S.tag) { S.results = null; renderRail(); renderList(); return; }
    if (!q) { S.results = null; renderList(); return; }
    try {
      S.results = await FS.api.search(q, { tags: S.tag ? [S.tag] : [] });
      renderRail(); renderList();
      try { const recent = JSON.parse(localStorage.getItem('fs:recentSearches') || '[]').filter((x) => x !== q); recent.unshift(q); localStorage.setItem('fs:recentSearches', JSON.stringify(recent.slice(0, 10))); } catch (e) { /* ignore */ }
    } catch (e) { FS.toast(e.message, 'error'); }
  }, 150);
  function clearSearch() { S.query = ''; S.results = null; $('search').value = ''; }

  /* ------------------------------------------------------------------ editor */
  function ensureEditor() {
    if (S.editor) return S.editor;
    S.editor = new FS.Editor($('editor'), {
      onChange: (md) => { if (!S.note || isCollection()) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      openLink: openLink,
      onPasteLink: (text, insert) => FS.picker.pasteChooser(text, insert),
      onPasteLocate: (text, insert, fallback) => (S.flex && S.flex.open) ? FS.picker.locateChooser(text, insert, fallback) : fallback(),
      onPasteImage: async (file, insert) => {
        const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(file); });
        try { const r = await FS.api.save_attachment(file.name || 'pasted.png', b64); insert('![' + (file.name || 'image') + '](' + (r.fileUrl || b64) + ')'); } catch (e) { FS.toast(e.message, 'error'); }
      },
      onSlash: (body, b) => slashMenu(body, b),
      onInsertFlex: () => insertFlex(),
    });
    window.__fsEditor = S.editor;        // for the tests and the console
    return S.editor;
  }
  async function openNote(id) {
    if (S.note && S.note.id === id) return;
    await flushSave();
    let n;
    try { n = await FS.api.get_note(id); } catch (e) { FS.toast(e.message, 'error'); return; }
    S.note = n; S.dirty = false;
    localStorage.setItem('fs:lastNote', id);
    $('editor-pane').classList.remove('no-note');
    $('note-title').value = n.title || '';
    const coll = n.kind === 'examples';
    $('editor-pane').classList.toggle('is-collection', coll);
    $('editor').hidden = coll; $('collection').hidden = !coll;
    $('note-title').placeholder = coll ? 'Untitled collection' : 'Untitled note';
    closeFind();
    if (coll) { ensureEditor().load(''); ensureCollection().load(n.body || ''); }
    else ensureEditor().load(n.body || '');
    renderNoteMeta();
    renderList();
    $('save-state').textContent = '';
    if (!n.title) $('note-title').focus(); else if (!coll) S.editor.focusBlock(0, 0);
  }
  /* Example collections (Seth, 2026-10-16): a note that is JUST interlinear examples, the one
   * kind of note that exports as a FLEx text. collection.js draws it; this wires it in. */
  function isCollection() { return !!(S.note && S.note.kind === 'examples'); }
  function ensureCollection() {
    if (S.coll) return S.coll;
    S.coll = new FS.Collection($('collection'), {
      onChange: (md) => { if (!isCollection()) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      onExport: () => exportCollection(),
      onRefreshAll: () => refreshAll(),
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
      const n = await FS.api.create_note(S.tab, S.folder || '', title || '', body || '', 'examples');
      clearSearch();
      await refreshLists();
      await openNote(n.id);
      return n;
    } catch (e) { FS.toast(e.message, 'error'); return null; }
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
    if (!ed || !S.note || isCollection()) return null;
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
          const s = await FS.api.add_to_collection(c.id, [clean]);
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
          const n = await FS.api.create_note(S.tab, S.folder || '', title.trim(), clean + '\n', 'examples');
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
  async function saveNow() {
    if (!S.note || !S.dirty || S.saving) return;
    S.saving = true;
    const n = S.note;
    try {
      const s = await FS.api.save_note(n.id, { body: n.body, title: $('note-title').value });
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
      if (n.kind !== 'examples') {
        // the highlighted part of the open note when it holds examples, else the whole note
        const hl = S.note && S.note.id === n.id ? (S.menuHighlight !== undefined ? S.menuHighlight : highlightedSource()) : null;
        const k = hl ? examplesIn(hl).length : 0;
        if (k) item('Collect the ' + k + ' selected example' + (k === 1 ? '' : 's') + ' into a new collection…', () => collectExamples(n, hl), 'collect-selection');
        else item('Collect the examples into a new collection…' + (hl ? '  (none selected: the whole note)' : ''), () => collectExamples(n));
      }
      S.menuHighlight = undefined;
      item('Copy markdown', async () => { const full = await FS.api.get_note(n.id); FS.copyText(full.body); FS.toast('Copied'); });
      item('Copy link to this note', () => { FS.copyText('flexscratchpad://note/' + n.id); FS.toast('Link copied — it opens this note in FLEx Scratchpad'); });
      pop.appendChild(el('hr'));
      pop.appendChild(el('div', { class: 'row', style: { padding: '0 8px' } }, el('b', {}, 'Export')));
      const doExport = async (fmt) => { if (!S.note || S.note.id !== n.id) await openNote(n.id); await flushSave(); try { await FS.exporter.exportNote(S.note, isCollection() ? ensureCollection().asEditor() : ensureEditor(), fmt); } catch (e) { FS.toast('Export failed: ' + e.message, 'error'); } };
      // only an example collection exports as a FLEx text (Seth, 2026-10-16)
      if (n.kind === 'examples') item('FLEx text (.flextext)…', () => doExport('flextext'));
      item('Markdown (.md)', () => doExport('md'));
      item('Web page (.html)', () => doExport('html'));
      item('Word (.docx)', () => doExport('docx'));
      item('PDF (print…)', () => doExport('pdf'));
      if (S.init.canBrowse) item('Show file', () => FS.api.reveal_note(n.id));
      pop.appendChild(el('hr'));
      item('Delete (to trash)', async () => { if (!confirm('Move “' + (n.title || 'Untitled') + '” to the trash?')) return; await FS.api.delete_note(n.id); if (S.note && S.note.id === n.id) { S.note = null; $('editor-pane').classList.add('no-note'); } await refreshLists(); }, 'danger');
    });
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
      const m = /^flex:(entry|sense|text|wordform)\/([0-9a-f-]{36})/i.exec(href);
      if (m) { try { await FS.api.flex_open_object(m[1], m[2]); FS.toast('Sent to FieldWorks'); } catch (e) { FS.toast(e.message, 'error'); } }
      return;
    }
    if (href.startsWith('silfw:')) { try { await FS.api.open_in_flex(href); } catch (e) { FS.toast(e.message, 'error'); } return; }
    if (/^https?:/i.test(href)) { window.open(href, '_blank'); return; }
  }

  /* ------------------------------------------------------------------ insert / slash */
  function insertFlex() { FS.picker.open((md, asBlock) => ensureEditor().insertMarkdown(md, asBlock)); }
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
      item('Table', () => S.editor.insertMarkdown(FS.tables.template(3, 3), true));
      item('Chart', () => S.editor.insertMarkdown(FS.charts.template(), true));
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
      case 'list': return ed.linePrefix('list');
      case 'task': return ed.linePrefix('task');
      case 'quote': return ed.linePrefix('quote');
      case 'table': return ed.insertMarkdown(FS.tables.template(3, 3), true);
      case 'chart': return ed.insertMarkdown(FS.charts.template(), true);
      case 'hr': return ed.insertMarkdown('---', true);
    }
  }

  /* Heading levels 1-6 (Seth, 2026-10-16), plain text, and folding every heading at once. The
   * buttons act on mousedown so the caret stays where it is in the note. */
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
      pop.appendChild(FS.el('button', { class: 'menu-item', 'data-test': 'fold-all', onmousedown: act(() => ed.setAllFolds(true)) }, '\u25b8 Collapse all headings'));
      pop.appendChild(FS.el('button', { class: 'menu-item', 'data-test': 'unfold-all', onmousedown: act(() => ed.setAllFolds(false)) }, '\u25be Expand all headings'));
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
    body.appendChild(nb);
    // FLEx
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
    }));
    $('btn-add-tab').addEventListener('click', addTab);
    $('btn-add-folder').addEventListener('click', () => newFolder(S.tab, S.folder || ''));
    $('chk-subfolders').addEventListener('change', (e) => setSubfolders(e.target.checked));
    $('btn-edit-tags').addEventListener('click', openSettings);
    $('btn-settings').addEventListener('click', openSettings);
    $('flex-pill').addEventListener('click', (e) => flexStatusPopover(e.currentTarget));
    $('flex-banner-fix').addEventListener('click', openSettings);
    $('flex-banner-retry').addEventListener('click', retryFlex);
    $('flex-banner-hide').addEventListener('click', () => { sessionStorage.setItem('fs:flexBannerHidden', '1'); $('flex-banner').hidden = true; });
    $('btn-sort').addEventListener('click', (e) => FS.popover(e.currentTarget, (pop, close) => { for (const [v, l] of [['updated', 'Last edited'], ['created', 'Date created'], ['title', 'Title']]) pop.appendChild(el('button', { class: 'menu-item' + (S.sort === v ? ' on' : ''), onclick: () => { S.sort = v; close(); renderList(); } }, (S.sort === v ? '✓ ' : '') + l)); }));
    $('note-title').addEventListener('input', () => { if (S.note) { S.note.title = $('note-title').value; S.dirty = true; scheduleSave(); } });
    $('note-title').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (!isCollection()) ensureEditor().focusBlock(0, 0); else e.target.blur(); } });
    $('btn-pin').addEventListener('click', () => { if (!S.note) return; S.note.pinned = !S.note.pinned; saveMeta({ pinned: S.note.pinned }); refreshLists(); });
    $('btn-note-menu').addEventListener('click', (e) => { if (S.note) noteMenu(e.currentTarget, S.note); });
    $('btn-insert-flex').addEventListener('click', insertFlex);
    $('toolbar').querySelectorAll('[data-ins]').forEach((b) => b.addEventListener('mousedown', (e) => { e.preventDefault(); toolbarAction(b.dataset.ins, b); }));
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
        if (!native && !own && S.note && S.editor && !isCollection()) {
          e.preventDefault();
          if (e.key.toLowerCase() === 'y' || e.shiftKey) S.editor.redoStep(); else S.editor.undoStep();
          return;
        }
      }
      if (mod && e.key.toLowerCase() === 'n' && !e.shiftKey) { e.preventDefault(); newNote(); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('search').focus(); $('search').select(); }
      else if (mod && !e.shiftKey && e.key.toLowerCase() === 'f') { if (S.note && !isCollection()) { e.preventDefault(); openFind(); } }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'l') { if (S.note) { e.preventDefault(); if (isCollection()) ensureCollection().pick(); else insertFlex(); } }
      else if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); flushSave().then(() => FS.toast('Saved')); }
      else if (mod && e.altKey && /^[1-6]$/.test(e.key)) { if (!isCollection()) { e.preventDefault(); ensureEditor().linePrefix('h', +e.key); } }
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
          else if (fresh) { S.note = fresh; $('note-title').value = fresh.title || ''; ensureEditor().load(fresh.body || ''); renderNoteMeta(); FS.toast('Note updated from disk'); }
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
    'A notebook for FieldWorks: tabs, folders, tags, tables and charts, with **live FLEx objects** inside your notes.',
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
    '- Charts: a ```chart block with labels and series (double-click the chart to edit it).',
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
