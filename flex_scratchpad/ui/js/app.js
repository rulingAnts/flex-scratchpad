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

  function applyInit(init) {
    S.init = init; S.config = init.config; S.notes = init.notes; S.folders = init.folders; S.tags = init.tags; S.flex = init.flex;
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

  function renderFlexPill() {
    const pill = $('flex-pill');
    const f = S.flex || {};
    pill.classList.toggle('on', !!f.open);
    pill.classList.toggle('err', !!f.error && !f.open);
    const src = f.backend === 'demo' ? ' (demo)' : f.backend === 'flextext' ? ' (.flextext)' : '';
    pill.querySelector('.label').textContent = f.open ? 'FLEx: ' + (f.project || '') + src : f.error ? 'FLEx: ' + f.error : 'FLEx: not connected';
    pill.title = f.error || (f.open ? 'Connected to ' + f.project : 'Open Settings to connect a FieldWorks project');
  }

  /* ------------------------------------------------------------------ note list */
  function visibleNotes() {
    if (S.results) return S.results;
    let list = S.notes.filter((n) => n.tab === S.tab);
    if (S.folder) list = list.filter((n) => n.folder === S.folder || n.folder.startsWith(S.folder + '/'));
    if (S.tag) list = list.filter((n) => n.tags.includes(S.tag) || (n.inlineTags || []).includes(S.tag));
    if (S.sort === 'title') list = list.slice().sort((a, b) => (b.pinned - a.pinned) || a.title.localeCompare(b.title));
    else if (S.sort === 'created') list = list.slice().sort((a, b) => (b.pinned - a.pinned) || b.created.localeCompare(a.created));
    return list;
  }
  function renderList() {
    const host = $('notes');
    host.innerHTML = '';
    const list = visibleNotes();
    const tabInfo = S.config.tabs.find((t) => t.dir === S.tab) || {};
    $('list-title').textContent = S.results ? 'Search results' : (S.folder ? S.folder.split('/').pop() : (tabInfo.name || 'Notes'));
    $('list-sub').textContent = S.results ? list.length + ' match' + (list.length === 1 ? '' : 'es') : [S.folder ? tabInfo.name + ' / ' + S.folder : '', S.tag ? '#' + S.tag : ''].filter(Boolean).join('  ·  ');
    if (!list.length) { host.appendChild(el('div', { class: 'empty' }, el('b', {}, S.results ? 'Nothing found' : 'No notes here'), S.results ? 'Try other words, or clear the tag filter.' : 'Press Ctrl+N to write one.')); return; }
    for (const n of list) {
      const card = el('div', { class: 'note-card' + (S.note && S.note.id === n.id ? ' active' : ''), draggable: 'true', dataset: { id: n.id } });
      card.appendChild(el('div', { class: 't' }, n.pinned ? el('span', { class: 'pin' }, '📌') : null, n.title || 'Untitled'));
      const x = el('div', { class: 'x' });
      if (n.snippet != null) x.innerHTML = markSnippet(n.snippet, n.snippetMarks); else x.textContent = n.excerpt || '';
      card.appendChild(x);
      const meta = el('div', { class: 'm' }, FS.relTime(n.updated));
      if (S.results || S.tag) meta.appendChild(el('span', {}, '· ' + (S.config.tabs.find((t) => t.dir === n.tab) || {}).name + (n.folder ? ' / ' + n.folder : '')));
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
      onChange: (md) => { if (!S.note) return; S.note.body = md; S.dirty = true; $('save-state').textContent = 'Editing…'; scheduleSave(); },
      openLink: openLink,
      onPasteLink: (text, insert) => FS.picker.pasteChooser(text, insert),
      onPasteLocate: (text, insert, fallback) => (S.flex && S.flex.open) ? FS.picker.locateChooser(text, insert, fallback) : fallback(),
      onPasteImage: async (file, insert) => {
        const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(file); });
        try { const r = await FS.api.save_attachment(file.name || 'pasted.png', b64); insert('![' + (file.name || 'image') + '](' + (r.fileUrl || b64) + ')'); } catch (e) { FS.toast(e.message, 'error'); }
      },
      onSlash: (body, b) => slashMenu(body, b),
    });
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
    ensureEditor().load(n.body || '');
    renderNoteMeta();
    renderList();
    $('save-state').textContent = '';
    closeFind();
    if (!n.title) $('note-title').focus(); else S.editor.focusBlock(0, 0);
  }
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
      item('Copy markdown', async () => { const full = await FS.api.get_note(n.id); FS.copyText(full.body); FS.toast('Copied'); });
      pop.appendChild(el('hr'));
      pop.appendChild(el('div', { class: 'row', style: { padding: '0 8px' } }, el('b', {}, 'Export')));
      const doExport = async (fmt) => { if (!S.note || S.note.id !== n.id) await openNote(n.id); await flushSave(); try { await FS.exporter.exportNote(S.note, ensureEditor(), fmt); } catch (e) { FS.toast('Export failed: ' + e.message, 'error'); } };
      item('Markdown (.md)', () => doExport('md'));
      item('Web page (.html)', () => doExport('html'));
      item('Word (.docx)', () => doExport('docx'));
      item('PDF (print…)', () => doExport('pdf'));
      if (S.init.canBrowse) item('Show file', () => FS.api.reveal_note(n.id));
      pop.appendChild(el('hr'));
      item('Delete (to trash)', async () => { if (!confirm('Move “' + (n.title || 'Untitled') + '” to the trash?')) return; await FS.api.delete_note(n.id); if (S.note && S.note.id === n.id) { S.note = null; $('editor-pane').classList.add('no-note'); } await refreshLists(); }, 'danger');
    });
  }
  function moveDialog(n) {
    const m = FS.modal({ title: 'Move note', class: 'narrow' });
    const tab = el('select');
    for (const t of S.config.tabs) tab.appendChild(el('option', { value: t.dir, selected: t.dir === n.tab }, t.name));
    const folder = el('select');
    const fill = () => { folder.innerHTML = ''; folder.appendChild(el('option', { value: '' }, '(tab root)')); for (const f of S.folders[tab.value] || []) folder.appendChild(el('option', { value: f, selected: f === n.folder }, f)); };
    tab.addEventListener('change', fill); fill();
    m.body.appendChild(el('div', { class: 'form-row' }, el('label', {}, 'Tab'), tab, el('label', {}, 'Folder'), folder));
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), el('button', { class: 'btn primary', onclick: async () => { await FS.api.move_note(n.id, tab.value, folder.value); if (S.note && S.note.id === n.id) { S.note.tab = tab.value; S.note.folder = folder.value; renderNoteMeta(); } m.close(); await refreshLists(); } }, 'Move')));
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
  function toolbarAction(kind) {
    const ed = ensureEditor();
    switch (kind) {
      case 'h': return ed.linePrefix('h', 2);
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
    body.appendChild(el('p', { class: 'muted small' }, S.init.app + ' ' + S.init.version + ' · ' + (S.init.platform || '')));
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
    $('btn-add-tab').addEventListener('click', addTab);
    $('btn-add-folder').addEventListener('click', () => newFolder(S.tab, S.folder || ''));
    $('btn-edit-tags').addEventListener('click', openSettings);
    $('btn-settings').addEventListener('click', openSettings);
    $('flex-pill').addEventListener('click', openSettings);
    $('btn-sort').addEventListener('click', (e) => FS.popover(e.currentTarget, (pop, close) => { for (const [v, l] of [['updated', 'Last edited'], ['created', 'Date created'], ['title', 'Title']]) pop.appendChild(el('button', { class: 'menu-item' + (S.sort === v ? ' on' : ''), onclick: () => { S.sort = v; close(); renderList(); } }, (S.sort === v ? '✓ ' : '') + l)); }));
    $('note-title').addEventListener('input', () => { if (S.note) { S.note.title = $('note-title').value; S.dirty = true; scheduleSave(); } });
    $('note-title').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ensureEditor().focusBlock(0, 0); } });
    $('btn-pin').addEventListener('click', () => { if (!S.note) return; S.note.pinned = !S.note.pinned; saveMeta({ pinned: S.note.pinned }); refreshLists(); });
    $('btn-note-menu').addEventListener('click', (e) => { if (S.note) noteMenu(e.currentTarget, S.note); });
    $('btn-insert-flex').addEventListener('click', insertFlex);
    $('toolbar').querySelectorAll('[data-ins]').forEach((b) => b.addEventListener('mousedown', (e) => { e.preventDefault(); toolbarAction(b.dataset.ins); }));
    $('btn-find').addEventListener('click', openFind);
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
        if (!native && !own && S.note && S.editor) {
          e.preventDefault();
          if (e.key.toLowerCase() === 'y' || e.shiftKey) S.editor.redoStep(); else S.editor.undoStep();
          return;
        }
      }
      if (mod && e.key.toLowerCase() === 'n' && !e.shiftKey) { e.preventDefault(); newNote(); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('search').focus(); $('search').select(); }
      else if (mod && !e.shiftKey && e.key.toLowerCase() === 'f') { if (S.note) { e.preventDefault(); openFind(); } }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'l') { if (S.note) { e.preventDefault(); insertFlex(); } }
      else if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); flushSave().then(() => FS.toast('Saved')); }
      else if (mod && e.altKey && /^[1-3]$/.test(e.key)) { e.preventDefault(); ensureEditor().linePrefix('h', +e.key); }
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
    FS.on('py:progress', (d) => { const pill = $('flex-pill'); pill.querySelector('.label').textContent = d.message || '…'; });
    document.addEventListener('click', (e) => { const a = e.target.closest('a[data-href], a.flex-chip, a.wikilink, a.ext-link'); if (a && !e.target.closest('.blk-body')) { e.preventDefault(); openLink(a.dataset.href || a.getAttribute('href')); } });
  }

  /* ------------------------------------------------------------------ welcome note */
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
