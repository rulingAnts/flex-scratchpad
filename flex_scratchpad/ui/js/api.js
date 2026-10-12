/* api.js — the one way the page talks to Python: window.pywebview.api (pywebview's js_api).
 *
 * No HTTP, no fetch. Each call is `pywebview.api.method(...positionalArgs)` → Promise.
 * When the page is opened in a plain browser (no pywebview at all) a pure-JS mock with demo
 * data stands in, so the UI can be worked on and demoed anywhere. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});

  let ready = null;
  /* pywebview creates an EMPTY window.pywebview.api first and fills in the methods a moment
   * later, firing `pywebviewready` when they are there — so "the object exists" is not the
   * test; "init is a function" is. The JS mock is used only when there is no pywebview at all. */
  const live = () => !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.init === 'function');
  function bridge() {
    if (ready) return ready;
    ready = new Promise((resolve) => {
      if (live()) return resolve(window.pywebview.api);
      let done = false;
      const finish = (api) => { if (!done) { done = true; resolve(api); } };
      window.addEventListener('pywebviewready', () => { if (live()) finish(window.pywebview.api); }, { once: false });
      const started = Date.now();
      const poll = () => {
        if (done) return;
        if (live()) return finish(window.pywebview.api);
        const hasPywebview = !!window.pywebview;
        const waited = Date.now() - started;
        // no pywebview object at all after the page loaded → plain browser → mock;
        // a pywebview object that stays empty for 15 s → give up and mock too (shows demo data)
        if ((!hasPywebview && document.readyState === 'complete' && waited > 600) || waited > 15000) return finish(FS.mockApi());
        setTimeout(poll, 100);
      };
      poll();
    });
    return ready;
  }

  FS.api = new Proxy({}, {
    get(_, method) {
      if (method === 'then') return undefined;
      return async (...args) => {
        const api = await bridge();
        const fn = api[method];
        if (typeof fn !== 'function') throw new Error('No API method ' + method);
        try {
          return await fn.apply(api, args);
        } catch (e) {
          // pywebview rejects with {message, name, stack}; normalise to an Error with .message
          const msg = (e && (e.message || e.msg)) || String(e);
          const err = new Error(msg.replace(/^RuntimeError: /, ''));
          err.name = (e && e.name) || 'ApiError';
          throw err;
        }
      };
    },
  });

  FS.isMock = () => !(window.pywebview && window.pywebview.api) && !!FS._mockActive;

  /* Events pushed from Python: window.evaluate_js('FS.onEvent({event, ...})'). */
  FS.onEvent = function (data) { FS.emit('py:' + (data && data.event), data); };

  /* ------------------------------------------------------------------ mock (browser only) */
  FS.mockApi = function () {
    FS._mockActive = true;
    const demo = FS.demoData ? FS.demoData() : { entries: [], texts: {} };
    const notes = {};
    const config = { tabs: [{ dir: 'Notes', name: 'Notes', color: '#2f6fdb' }, { dir: 'Grammar', name: 'Grammar', color: '#0f766e' }],
      tags: [{ name: 'todo', color: '#b45309' }], flex: { source: 'demo', project: 'Kalu Demo' }, media: { byGuid: {}, folders: [] }, settings: { diacriticsInsensitive: true } };
    const folders = { Notes: [], Grammar: ['Verbs', 'Verbs/Aspect'] };
    let seq = 0;
    const now = () => new Date().toISOString().slice(0, 19);
    function mk(tab, folder, title, body, tags) {
      const id = 'n_' + (++seq).toString(16).padStart(10, '0');
      notes[id] = { id, title, tab, folder, tags: tags || [], created: now(), updated: now(), pinned: false, body, path: '' };
      return notes[id];
    }
    mk('Notes', '', 'Welcome to FLEx Scratchpad', FS.welcomeNote ? FS.welcomeNote() : '# Welcome\n\nThis is the in-browser demo.', ['todo']);
    mk('Grammar', 'Verbs/Aspect', 'Past tense -mo', '# Past tense *-mo*\n\nThe suffix **-mo** marks past tense. See the dictionary entry:\n\n{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0004}}\n\nAnd in text:\n\n{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1-2 u=morph:"-mo"}}\n\n#grammar #tense');
    const summary = (n) => ({ ...n, excerpt: n.body.replace(/\{\{[^}]*\}\}/g, ' ').replace(/[#*_`>\-]/g, '').replace(/\s+/g, ' ').trim().slice(0, 160), inlineTags: (n.body.match(/(?<![\w#\/])#([\w][\w-]*)/g) || []).map((t) => t.slice(1)) });
    const list = () => Object.values(notes).sort((a, b) => (b.pinned - a.pinned) || b.updated.localeCompare(a.updated)).map(summary);
    const tags = () => {
      const seen = {}; config.tags.forEach((t) => (seen[t.name] = { ...t, count: 0 }));
      for (const n of Object.values(notes)) for (const t of new Set([...n.tags, ...summary(n).inlineTags])) { seen[t] = seen[t] || { name: t, color: '#6b7280', implicit: true, count: 0 }; seen[t].count++; }
      return Object.values(seen);
    };
    const status = () => ({ source: 'demo', project: 'Kalu Demo', open: true, backend: 'demo', error: '', texts: Object.keys(demo.texts).length, entries: demo.entries.length });
    const init = () => ({ app: 'FLEx Scratchpad', version: 'browser-demo', platform: 'browser', notebook: '(in-memory demo notebook)', config, notes: list(), folders, tags: tags(), flex: status(), canBrowse: false });
    const sliceText = (t, a, b) => { const segs = t.segments.filter((s) => (!a || s.n >= a) && (!b || s.n <= b)).slice(0, 60); return { ...t, segments: segs, segmentCount: t.segments.length, range: segs.length ? [segs[0].n, segs[segs.length - 1].n] : [0, 0], cached: false }; };
    return {
      init: async () => init(),
      list_notes: async () => list(), folders: async () => folders, tags: async () => tags(),
      get_note: async (id) => ({ ...notes[id], inlineTags: summary(notes[id]).inlineTags }),
      create_note: async (tab, folder, title, body) => ({ ...mk(tab || 'Notes', folder || '', title || '', body || '') }),
      save_note: async (id, patch) => { const n = notes[id]; for (const k of ['title', 'body', 'tags', 'pinned']) if (patch[k] != null) n[k] = patch[k]; n.updated = now(); return summary(n); },
      move_note: async (id, tab, folder) => { notes[id].tab = tab; notes[id].folder = folder || ''; return summary(notes[id]); },
      delete_note: async (id) => { delete notes[id]; return true; },
      search: async (q, f) => { const ql = FS.normalize(q.replace(/\b(tag|tab|folder):\S+/g, '').trim(), true); f = f || {}; return list().filter((n) => (!f.tab || n.tab === f.tab) && (!f.tags || !f.tags.length || f.tags.every((t) => n.tags.includes(t) || n.inlineTags.includes(t))) && (!ql || FS.normalize(n.title + ' ' + n.body, true).includes(ql))).map((n) => ({ ...n, snippet: n.excerpt, snippetMarks: [], score: 1 })); },
      rescan: async () => init(),
      add_tab: async (name, color) => { const t = { dir: name, name, color: color || '#7c3aed' }; config.tabs.push(t); folders[name] = []; return t; },
      update_tab: async (dir, patch) => { const t = config.tabs.find((x) => x.dir === dir); Object.assign(t, patch); return t; },
      reorder_tabs: async (dirs) => { config.tabs.sort((a, b) => dirs.indexOf(a.dir) - dirs.indexOf(b.dir)); return config.tabs; },
      delete_tab: async (dir) => { config.tabs = config.tabs.filter((t) => t.dir !== dir); return true; },
      create_folder: async (tab, folder) => { (folders[tab] = folders[tab] || []).push(folder); return folder; },
      rename_folder: async (tab, folder, nn) => { const parts = folder.split('/'); parts[parts.length - 1] = nn; const nf = parts.join('/'); folders[tab] = folders[tab].map((f) => f === folder ? nf : f); Object.values(notes).forEach((n) => { if (n.tab === tab && n.folder === folder) n.folder = nf; }); return nf; },
      delete_folder: async (tab, folder) => { folders[tab] = folders[tab].filter((f) => f !== folder && !f.startsWith(folder + '/')); return true; },
      set_tags: async (t) => (config.tags = t), rename_tag: async () => 0, set_setting: async (k, v) => (config.settings[k] = v, config.settings),
      save_attachment: async (name, data) => ({ path: name, fileUrl: data, name }),
      flex_status: async () => status(), flex_projects: async () => ['Kalu Demo'],
      flex_configure: async () => status(), flex_open: async () => status(), flex_refresh: async () => status(),
      flex_get: async (kind, guid, a, b) => { if (kind === 'entry' || kind === 'sense') { const e = demo.entries.find((x) => x.guid === guid || x.senses.some((s) => s.guid === guid)); if (!e) throw new Error('No such entry'); return { ...e, cached: false }; } const t = demo.texts[guid]; if (!t) throw new Error('No such text'); return sliceText(t, a, b); },
      flex_search_entries: async (q) => demo.entries.filter((e) => !q || (e.headword + ' ' + e.senses.map((s) => s.gloss).join(' ')).toLowerCase().includes(q.toLowerCase())).map((e) => ({ guid: e.guid, headword: e.headword, pos: e.pos, gloss: e.senses.map((s) => s.gloss).join('; '), senses: e.senses.length, morphType: e.morphType })),
      flex_texts: async (q) => Object.values(demo.texts).filter((t) => !q || t.title.toLowerCase().includes(q.toLowerCase())).map((t) => ({ guid: t.guid, title: t.title, abbrev: t.abbrev, segmentCount: t.segments.length, hasMedia: false })),
      flex_find_in_text: async (guid, phrase) => { const t = demo.texts[guid]; const p = FS.normalize(phrase, true); return t ? t.segments.filter((s) => FS.normalize(s.baseline + ' ' + s.free, true).includes(p)).map((s) => s.n) : []; },
      flex_resolve_link: async (text) => { const m = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(text || ''); if (!m) return null; const g = m[1].toLowerCase(); const e = demo.entries.find((x) => x.guid === g); if (e) return { kind: 'entry', guid: g, title: e.headword }; if (demo.texts[g]) return { kind: 'text', guid: g, title: demo.texts[g].title }; return null; },
      flex_choose_file: async () => null,
      open_in_flex: async (url) => { FS.toast('Would open in FLEx: ' + url); return true; },
      flex_open_object: async (kind, guid) => { FS.toast('Would open in FLEx: ' + kind + ' ' + guid); return true; },
      audio_clip: async () => ({ found: false, fileUrl: '', clipUrl: '', needsCapture: false, mediaGuid: '' }),
      audio_store_clip: async () => ({ clipUrl: '' }), audio_browse_media: async () => null, audio_set_media_path: async () => ({}),
      save_file_as: async () => null, choose_notebook_folder: async () => null, open_notebook: async () => init(), reveal_notebook: async () => false, reveal_note: async () => false,
    };
  };
})();
