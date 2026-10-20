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
  /* The screen shown while the app's Python side is late (never demo data: see poll()). */
  function showWait(waited) {
    let box = document.getElementById('bridge-wait');
    if (!box) {
      box = document.createElement('div');
      box.id = 'bridge-wait';
      box.setAttribute('data-test', 'bridge-wait');
      box.innerHTML = '<div class="bw-card"><b>Waiting for the app…</b>'
        + '<p>The page is open but the program behind it has not answered yet. Nothing is lost: your notebook is on disk and is not touched until the app answers.</p>'
        + '<p>If this stays, close the window and start the app from a terminal with <code>flex-scratchpad -v</code>, or look at the log: '
        + '<code>%LOCALAPPDATA%\\FLEx Scratchpad\\log\\flex-scratchpad.log</code>.</p>'
        + '<p class="bw-time"></p>'
        + '<p><button type="button" class="btn" data-test="bridge-reload">Reload the page</button></p></div>';
      box.querySelector('[data-test="bridge-reload"]').addEventListener('click', () => location.reload());
      (document.body || document.documentElement).appendChild(box);
    }
    const reloads = bridgeReloads();
    box.querySelector('.bw-time').textContent = 'Waited ' + Math.round(waited / 1000) + ' s.' + (reloads ? ' Reloaded ' + reloads + (reloads === 1 ? ' time' : ' times') + ' already.' : '');
    // the retry: reloading the page makes the window navigate again, and pywebview hands the api
    // over on every navigation — twice, then the button is left to the user
    const reloadMs = Number(window.FS_BRIDGE_RELOAD_MS) > 0 ? Number(window.FS_BRIDGE_RELOAD_MS) : 45000;
    if (waited > reloadMs && reloads < 2) { bridgeReloads(reloads + 1); location.reload(); }
  }
  function hideWait() { const box = document.getElementById('bridge-wait'); if (box) box.remove(); bridgeReloads(0); }
  function bridgeReloads(set) {
    try {
      if (set != null) { if (set) sessionStorage.setItem('fs:bridgeReloads', String(set)); else sessionStorage.removeItem('fs:bridgeReloads'); }
      return Number(sessionStorage.getItem('fs:bridgeReloads') || 0);
    } catch (e) { return 0; }
  }

  function bridge() {
    if (ready) return ready;
    ready = new Promise((resolve) => {
      if (live()) return resolve(window.pywebview.api);
      let done = false;
      const finish = (api) => { if (!done) { done = true; resolve(api); } };
      window.addEventListener('pywebviewready', () => { if (live()) finish(window.pywebview.api); }, { once: false });
      const started = Date.now();
      // A pywebview window is known before pywebview itself says so: WebView2 gives every page
      // window.chrome.webview, WebKit window.webkit.messageHandlers, from the first script on. pywebview
      // only injects window.pywebview after the page has LOADED and fills its api a moment later.
      const hosted = () => !!(window.pywebview || (window.chrome && window.chrome.webview) || (window.webkit && window.webkit.messageHandlers));
      const waitMs = Number(window.FS_BRIDGE_WAIT_MS) > 0 ? Number(window.FS_BRIDGE_WAIT_MS) : 15000;
      const poll = () => {
        if (done) return;
        if (live()) { hideWait(); return finish(window.pywebview.api); }
        const waited = Date.now() - started;
        // no pywebview and no browser host object once the page has loaded → a plain browser → the mock
        if (!hosted() && document.readyState === 'complete' && waited > 600) return finish(FS.mockApi());
        // inside the app but the api has not arrived: WAIT, visibly, as long as it takes — NEVER the
        // mock (Seth, 2026-10-19: the page quietly showed the demo notebook over his own and he
        // thought his data was gone; "It's just the most recent commit/wheel that does that")
        if (hosted() && waited > waitMs) showWait(waited);
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

  /* The page's own errors go to Python's log (Seth, 2026-10-18: the browser console is not easy to
   * route to the terminal): window.onerror, unhandled promise rejections and console.error /
   * console.warn each become one `client_log` call (at most 40 per minute; never for a failure of
   * client_log itself). The developer tools (--devtools) remain the place to look at them live. */
  const clientLog = (() => {
    let stamps = [];
    return (level, message, where) => {
      try {
        const api = window.pywebview && window.pywebview.api;
        if (!api || !api.client_log) return;
        const now = Date.now();
        stamps = stamps.filter((t) => now - t < 60000);
        if (stamps.length >= 40) return;
        stamps.push(now);
        const p = api.client_log(String(level), String(message).slice(0, 2000), where ? String(where).slice(0, 300) : '');
        if (p && p.catch) p.catch(() => {});
      } catch (e) { /* never recurse into the log */ }
    };
  })();
  FS.clientLog = clientLog;
  window.addEventListener('error', (e) => clientLog('error', (e.message || 'error') + (e.error && e.error.stack ? '\n' + e.error.stack : ''), (e.filename || '') + ':' + (e.lineno || 0)));
  window.addEventListener('unhandledrejection', (e) => { const r = e.reason; clientLog('error', 'unhandled rejection: ' + (r && r.stack ? r.stack : (r && r.message) || String(r))); });
  for (const lvl of ['error', 'warn']) {
    const orig = console[lvl] ? console[lvl].bind(console) : null;
    console[lvl] = (...args) => { if (orig) orig(...args); clientLog(lvl, args.map((a) => (a && a.stack) || (typeof a === 'object' ? (() => { try { return JSON.stringify(a); } catch (x) { return String(a); } })() : String(a))).join(' ')); };
  }

  /* ------------------------------------------------------------------ mock (browser only) */
  FS.mockApi = function () {
    FS._mockActive = true;
    const demo = FS.demoData ? FS.demoData() : { entries: [], texts: {} };
    const mockFiles = {};
    const fileInfo = (ref) => {
      const f = mockFiles[ref];
      const name = String(ref).split(/[\\/]/).pop();
      const ext = (/\.([^.]+)$/.exec(name) || [])[1] || '';
      const kind = FS.files ? FS.files.kindOf(name) : 'file';
      return { ref, name, linked: /^([A-Za-z]:|\/)/.test(ref), path: ref, kind: ext ? kind : 'file', exists: !!f, size: f ? f.size : null, fileUrl: f ? f.data : null };
    };
    const notes = {};
    const config = { tabs: [{ dir: 'Notes', name: 'Notes', color: '#2f6fdb' }, { dir: 'Grammar', name: 'Grammar', color: '#0f766e' }],
      tags: [{ name: 'todo', color: '#b45309' }], flex: { source: 'demo', project: 'Kalu Demo' }, media: { byGuid: {}, folders: [] }, settings: { diacriticsInsensitive: true }, tagStyles: { project: {}, tab: {}, folder: {}, note: {}, text: {}, filters: [] } };
    const folders = { Notes: [], Grammar: ['Verbs', 'Verbs/Aspect'] };
    let seq = 0;
    const ruleEmbed = (r) => '{{flex:text ' + r.text + ' seg=' + r.seg + (r.segTo !== r.seg ? '-' + r.segTo : '') + (r.at && r.at[0] ? ' at=' + r.at[0] + (r.at[1] && r.at[1] !== r.at[0] ? '-' + r.at[1] : '') : '') + '}}';
    const now = () => new Date().toISOString().slice(0, 19);
    function mk(tab, folder, title, body, tags, kind) {
      const id = 'n_' + (++seq).toString(16).padStart(10, '0');
      notes[id] = { id, title, tab, folder, tags: tags || [], created: now(), updated: now(), pinned: false, kind: kind || '', body, path: '' };
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
    /* the mock's model.slice_chart: the rows asked for, anchors first */
    const sliceChart = (chart, a, b, at) => {
      const out = JSON.parse(JSON.stringify(chart));
      const rows = out.rows || [];
      const find = (want, near) => { if (!want) return null; const hits = rows.filter((r) => r.guid.replace(/-/g, '').endsWith(String(want).toLowerCase())).map((r) => r.n); return hits.length ? hits.sort((x, y) => Math.abs(x - near) - Math.abs(y - near))[0] : null; };
      let from = Math.max(1, a || 1), to = b || rows.length;
      if (at && at.length) { const fa = find(at[0], from), fb = find(at[1], to); const len = to - from; if (fa != null && fb != null) { from = Math.min(fa, fb); to = Math.max(fa, fb); } else if (fa != null) { from = fa; to = fa + len; } else if (fb != null) { to = fb; from = Math.max(1, fb - len); } out.rangeMoved = (from !== Math.max(1, a || 1)) || (to !== (b || rows.length)); out.anchorsLost = (fa == null && !!at[0]) || (fb == null && !!at[1]); }
      out.rows = rows.filter((r) => r.n >= from && r.n <= to);
      out.range = out.rows.length ? [from, Math.min(to, rows.length)] : [0, 0];
      out.anchors = out.rows.length ? [out.rows[0].guid.replace(/-/g, '').slice(-12), out.rows[out.rows.length - 1].guid.replace(/-/g, '').slice(-12)] : ['', ''];
      out.cached = false;
      return out;
    };
    const sliceText = (t, a, b) => { const segs = t.segments.filter((s) => (!a || s.n >= a) && (!b || s.n <= b)).slice(0, 60); return { ...t, segments: segs, segmentCount: t.segments.length, range: segs.length ? [segs[0].n, segs[segs.length - 1].n] : [0, 0], cached: false }; };
    return {
      init: async () => init(),
      list_notes: async () => list(), folders: async () => folders, tags: async () => tags(),
      get_note: async (id) => ({ ...notes[id], inlineTags: summary(notes[id]).inlineTags }),
      create_note: async (tab, folder, title, body, kind) => ({ ...mk(tab || 'Notes', folder || '', title || '', body || '', null, kind || '') }),
      // rule collections (the mock's version of Api.rule_matches & co.: tags by name / guid / group:<name> / *)
      // the mock's chart search (Api.chart_search in short: words, col:, marker:, lex:, gloss:, clause:, moved)
      chart_search: async (q) => {
        const nz = (x) => FS.normalize(String(x || ''), true);
        const terms = [];
        for (const m of String(q || '').matchAll(/(-(?=[a-z]+:))?(?:([a-z]+):)?("([^"]*)"|\S+)/gi)) terms.push({ neg: !!m[1], key: (m[2] || '').toLowerCase(), val: nz(m[4] != null ? m[4] : m[3]) });
        const out = [];
        for (const c of Object.values(demo.charts || {})) {
          const cols = new Map(c.template.columns.map((x) => [x.n, x]));
          for (const r of c.rows) {
            const cells = r.cells.filter((x) => x.kind === 'words').map((x) => { const col = cols.get(x.colN) || {}; const ws = (x.words || []).filter((w) => !w.punct); return { colN: x.colN, col: col.name || '', abbr: col.abbr || '', path: (col.path || []).concat([col.name]).join('/'), words: ws.map((w) => w.txt), glosses: ws.map((w) => w.gls || ''), forms: ws.flatMap((w) => (w.morphs || []).map((m) => m.form || '')), cfs: [], mgls: ws.flatMap((w) => (w.morphs || []).map((m) => m.gls || '')), pos: ws.map((w) => w.pos || '').filter(Boolean) }; });
            const markers = r.cells.filter((x) => x.kind === 'tag' && x.tag).flatMap((x) => [x.tag.name, x.tag.abbr].concat(x.tag.path || []));
            const moved = r.cells.filter((x) => x.kind === 'moved').map((x) => (x.preposed ? 'preposed' : 'postposed'));
            const row = { chart: c.guid, chartName: c.name, text: c.text, title: c.title, template: c.template.name, row: r.n, label: r.label, guid: r.guid, at: r.guid.replace(/-/g, '').slice(-12), clause: r.clause, endSent: r.endSent, endPara: r.endPara, markers, moved, clauseref: r.cells.some((x) => x.kind === 'clause'), notes: r.notes || '', cells };
            const cellHas = (cell, t) => { const v = t.val; const has = (xs) => xs.some((x) => v && nz(x).includes(v)); if (t.key === 'col') return nz(cell.col) === v || nz(cell.abbr) === v || nz(cell.path) === v || nz(cell.path).endsWith('/' + v) || cell.path.split('/').slice(0, -1).some((p) => nz(p) === v) || ('c' + cell.colN) === v; if (t.key === 'lex') return has(cell.words) || has(cell.forms); if (t.key === 'gloss') return has(cell.glosses) || has(cell.mgls); if (t.key === 'pos') return cell.pos.some((x) => nz(x) === v); return has(cell.words) || has(cell.glosses) || has(cell.forms) || has(cell.mgls); };
            let ok = true, hits = [];
            const colT = terms.filter((t) => t.key === 'col' && !t.neg), content = terms.filter((t) => !t.key || ['lex', 'gloss', 'word', 'pos'].includes(t.key));
            for (const t of terms) {
              let v = null;
              if (t.key === 'marker') v = t.val === '*' ? markers.length > 0 : markers.some((m) => nz(m) === t.val);
              else if (t.key === 'clause') v = row.clause === t.val;
              else if (t.key === 'moved' || (!t.key && t.val === 'moved')) v = moved.length > 0;
              else if (t.key === 'chart') v = nz(c.name).includes(t.val); else if (t.key === 'text') v = nz(c.title).includes(t.val); else if (t.key === 'row') v = nz(r.label) === t.val;
              if (v != null && v === t.neg) { ok = false; break; }
            }
            if (!ok) continue;
            let cs = cells;
            if (colT.length) { cs = cs.filter((cell) => colT.some((t) => cellHas(cell, t))); if (!cs.length) continue; }
            const pos = content.filter((t) => !t.neg && !(t.key === '' && t.val === 'moved'));
            if (pos.length) { cs = cs.filter((cell) => pos.every((t) => cellHas(cell, t))); if (!cs.length) { if (!pos.every((t) => !t.key && nz(row.notes).includes(t.val))) continue; } }
            hits = (colT.length || pos.length) ? cs.map((x) => x.colN) : [];
            out.push(Object.assign(row, { hits }));
          }
        }
        return out;
      },
      chart_profile: async function (term) {
        const nz = (x) => FS.normalize(String(x || ''), true), t = nz(term);
        const out = { term, total: 0, templates: [] };
        if (!t) return out;
        const byT = {};
        for (const r of await this.chart_search('')) for (const c of r.cells) {
          if (![...c.words, ...c.forms, ...c.glosses, ...c.mgls].some((x) => nz(x).includes(t))) continue;
          const tp = byT[r.template] = byT[r.template] || { name: r.template, total: 0, columns: {} };
          const col = tp.columns[c.path] = tp.columns[c.path] || { name: c.col, path: c.path, colN: c.colN, count: 0, rows: [] };
          col.count++; tp.total++; out.total++;
          col.rows.push({ chart: r.chart, chartName: r.chartName, title: r.title, row: r.row, label: r.label, at: r.at, words: c.words.join(' '), glosses: c.glosses.join(' ') });
        }
        out.templates = Object.values(byT).map((tp) => ({ name: tp.name, total: tp.total, columns: Object.values(tp.columns).sort((a, b) => a.colN - b.colN) }));
        return out;
      },
      rule_matches: async function (rule) {
        if (rule && rule.charts) return (await this.chart_search(rule.charts)).map((r) => Object.assign(r, { embed: '{{flex:chart ' + r.chart + ' rows=' + r.row + ' at=' + r.at + '}}' }));
        const all = await this.flex_text_tags();
        const norm = (x) => String(x || '').trim().toLowerCase().replace(/_/g, ' ');
        const want = new Map();
        for (const sel of (rule && rule.tags) || []) {
          if (sel === '*') all.forEach((t) => want.set(t.guid, t));
          else if (/^group:/i.test(sel)) all.filter((t) => (t.path || [t.group]).some((g) => norm(g) === norm(sel.slice(6)))).forEach((t) => want.set(t.guid, t));
          else all.filter((t) => t.guid === sel.toLowerCase() || norm(t.name) === norm(sel) || norm(t.abbr) === norm(sel)).forEach((t) => want.set(t.guid, t));
        }
        const only = new Set(((rule && rule.texts) || []).map((x) => String(x).toLowerCase()));
        const rows = new Map();
        for (const t of want.values()) for (const r of await this.flex_tag_occurrences(t.guid, '')) {
          if (only.size && !only.has(r.text)) continue;
          const k = r.text + ':' + r.seg + '-' + r.segTo;
          if (rows.has(k)) { if (!rows.get(k).tags.includes(t.name)) rows.get(k).tags.push(t.name); } else rows.set(k, { ...r, tags: [t.name] });
        }
        return [...rows.values()].sort((a, b) => a.title.localeCompare(b.title) || a.seg - b.seg || a.segTo - b.segTo);
      },
      create_rule_collection: async function (tab, folder, title, rule) {
        const rows = await this.rule_matches(rule);
        const n = mk(tab || 'Notes', folder || '', title || '', rows.map((r) => r.embed || ruleEmbed(r)).join('\n\n') + (rows.length ? '\n' : ''), null, 'examples');
        n.rule = rule.charts ? { charts: rule.charts } : { tags: [...(rule.tags || [])], ...(rule.texts && rule.texts.length ? { texts: [...rule.texts] } : {}) };
        return { ...n, matched: rows.length };
      },
      update_rule_collection: async function (id) {
        const n = notes[id];
        if (!n || n.kind !== 'examples' || !n.rule) throw new Error('This collection has no rule');
        const rows = await this.rule_matches(n.rule);
        const have = new Set();
        for (const m of n.body.matchAll(/\{\{flex:(?:text|chart)\s+([0-9a-f-]{36})\b([^}]*)\}\}/gi)) {
          const seg = /\b(?:seg|rows)=(\d+)(?:-(\d+))?/.exec(m[2]), at = /\bat=([0-9a-f]+)(?:-([0-9a-f]+))?/i.exec(m[2]);
          if (at) have.add(m[1].toLowerCase() + '@' + at[1] + '-' + (at[2] || at[1]));
          if (seg) have.add(m[1].toLowerCase() + '#' + seg[1] + '-' + (seg[2] || seg[1]));
        }
        const add = rows.filter((r) => !have.has(r.text + '@' + r.at[0] + '-' + r.at[1]) && !have.has(r.text + '#' + r.seg + '-' + r.segTo)).map(ruleEmbed);
        if (add.length) await this.add_to_collection(id, add);
        return { added: add, matched: rows.length, total: (n.body.match(/^\s*\{\{flex:text\b[^\n]*\}\}\s*$/gm) || []).length, note: await this.get_note(id) };
      },
      set_note_rule: async function (id, rule) { const n = notes[id]; n.rule = rule && rule.tags && rule.tags.length ? { tags: [...rule.tags] } : null; n.updated = now(); return this.get_note(id); },
      list_collections: async () => Object.values(notes).filter((n) => n.kind === 'examples').sort((a, b) => b.updated.localeCompare(a.updated)).map((n) => ({ id: n.id, title: n.title, tab: n.tab, folder: n.folder, updated: n.updated, count: (n.body.match(/^\s*\{\{flex:text\b[^\n]*\}\}\s*$/gm) || []).length })),
      texts_used: async (scope) => {
        // the mock's version of Api.texts_used: one row per text the examples come from
        scope = scope || {};
        const src = scope.note ? [[notes[scope.note], scope.markdown != null ? scope.markdown : notes[scope.note].body]]
          : Object.values(notes).filter((n) => (!scope.tab || n.tab === scope.tab) && (!scope.folder || n.folder === scope.folder || n.folder.startsWith(scope.folder + '/'))).map((n) => [n, n.body]);
        const rows = {};
        for (const [n, body] of src) {
          for (const [re, key] of [[/\{\{\s*flex:text\s+([0-9a-fA-F-]{36})/g, 'examples'], [/\(flex:text\/([0-9a-fA-F-]{36})/g, 'links']]) {
            let m;
            while ((m = re.exec(body || ''))) {
              const g = m[1].toLowerCase();
              const r = rows[g] = rows[g] || { guid: g, examples: 0, links: 0, notes: [] };
              r[key]++;
              if (!r.notes.some((x) => x.id === n.id)) r.notes.push({ id: n.id, title: n.title });
            }
          }
        }
        const out = Object.values(rows).map((r) => Object.assign(r, { title: (demo.texts[r.guid] || {}).title || '(a text not in this project)', url: 'silfw://localhost/link?app=flex&server=&database=Demo&tool=interlinearEdit&guid=' + r.guid }));
        out.sort((a, b) => a.title.localeCompare(b.title));
        return { texts: out, notes: src.length };
      },
      add_to_collection: async (id, embeds) => { const n = notes[id]; if (!n || n.kind !== 'examples') throw new Error('Not an example collection'); const add = (embeds || []).map((e) => String(e).trim()).filter(Boolean); if (add.length) { const b = n.body.replace(/\n+$/, ''); n.body = (b.trim() ? b + '\n\n' : '') + add.join('\n\n') + '\n'; n.updated = now(); } return summary(n); },
      save_note: async (id, patch) => { const n = notes[id]; for (const k of ['title', 'body', 'tags', 'pinned']) if (patch[k] != null) n[k] = patch[k]; n.updated = now(); return summary(n); },
      move_note: async (id, tab, folder) => { notes[id].tab = tab; notes[id].folder = folder || ''; return summary(notes[id]); },
      delete_note: async (id) => { delete notes[id]; return true; },
      search: async function (q, f) {
        const tagged = [...q.matchAll(/\btagged:(\S+)/g)].map((m) => m[1].toLowerCase());
        const used = tagged.length ? await this.flex_tags_used() : {};
        const ql = FS.normalize(q.replace(/\b(tag|tab|folder|tagged):\S+/g, '').trim(), true); f = f || {};
        return list().filter((n) => (!f.tab || n.tab === f.tab) && (!f.tags || !f.tags.length || f.tags.every((t) => n.tags.includes(t) || n.inlineTags.includes(t))) && tagged.every((t) => (used[t] || []).includes(n.id)) && (!ql || FS.normalize(n.title + ' ' + n.body, true).includes(ql))).map((n) => ({ ...n, snippet: n.excerpt, snippetMarks: [], score: 1 }));
      },
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
      // attached files: kept in memory as data: URLs (the real program copies them into attachments/)
      attach_files: async () => [], attach_paths: async () => [], locate_file: async () => null,
      attach_dropped: async (names) => ({ files: [], missing: names || [] }),
      attach_data: async (name, data) => { const ref = 'attachments/' + name; mockFiles[ref] = { data, size: Math.floor(((data || '').split(',')[1] || '').length * 3 / 4) }; return fileInfo(ref); },
      file_info: async (ref) => fileInfo(ref),
      open_file: async (ref) => { FS.toast('Would open ' + ref + ' in its program'); return { opened: true }; },
      reveal_file: async () => false,
      flex_status: async () => status(), flex_projects: async () => ['Kalu Demo'],
      flex_configure: async () => status(), flex_open: async () => status(), flex_refresh: async () => status(), flex_reload: async () => status(),
      flex_get: async (kind, guid, a, b, _pc, _ws, at) => { if (kind === 'chart') { const c = (demo.charts || {})[guid]; if (!c) throw new Error('No such chart'); return sliceChart(c, a, b, at); } if (kind === 'entry' || kind === 'sense') { const e = demo.entries.find((x) => x.guid === guid || x.senses.some((s) => s.guid === guid)); if (!e) throw new Error('No such entry'); return { ...e, cached: false }; } const t = demo.texts[guid]; if (!t) throw new Error('No such text'); return sliceText(t, a, b); },
      flex_search_entries: async (q) => demo.entries.filter((e) => !q || (e.headword + ' ' + e.senses.map((s) => s.gloss).join(' ')).toLowerCase().includes(q.toLowerCase())).map((e) => ({ guid: e.guid, headword: e.headword, pos: e.pos, gloss: e.senses.map((s) => s.gloss).join('; '), senses: e.senses.length, morphType: e.morphType })),
      flex_texts: async (q) => Object.values(demo.texts).filter((t) => !q || t.title.toLowerCase().includes(q.toLowerCase())).map((t) => ({ guid: t.guid, title: t.title, abbrev: t.abbrev, segmentCount: t.segments.length, hasMedia: false })),
      flex_find_in_text: async (guid, phrase) => { const t = demo.texts[guid]; const p = FS.normalize(phrase, true); return t ? t.segments.filter((s) => FS.normalize(s.baseline + ' ' + s.free, true).includes(p)).map((s) => s.n) : []; },
      flex_resolve_link: async (text) => { const m = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(text || ''); if (!m) return null; const g = m[1].toLowerCase(); const e = demo.entries.find((x) => x.guid === g); if (e) return { kind: 'entry', guid: g, title: e.headword }; if (demo.texts[g]) return { kind: 'text', guid: g, title: demo.texts[g].title }; return null; },
      set_note_chart: async function (id, guid) { const n = notes[id]; if (!n || n.kind !== 'chart') throw new Error('Not a chart note'); if (!(demo.charts || {})[guid]) throw new Error('No such chart'); n.chart = guid; n.updated = now(); return this.get_note(id); },
      create_chart_note: async function (tab, folder, title, guid, view) { const c = (demo.charts || {})[guid]; if (!c) throw new Error('No such chart'); const n = mk(tab || config.tabs[0].dir, folder || '', title || (c.name + ' — ' + c.title), (view && view.startsWith('{{flex:chart ' + guid) ? view.trim() : '{{flex:chart ' + guid + '}}') + '\n', [], 'chart'); n.chart = guid; return this.get_note(n.id); },
      chart_lists: async () => (config.chartLists = config.chartLists || {}),
      set_chart_list: async (name, options, open) => { const lists = (config.chartLists = config.chartLists || {}); if (options == null && open == null) delete lists[name]; else { const cur = lists[name] || { options: [], open: true }; if (options) cur.options = options; if (open != null) cur.open = !!open; lists[name] = cur; } return lists; },
      flex_charts: async (text) => Object.values(demo.charts || {}).filter((c) => !text || c.text === text).map((c) => ({ guid: c.guid, name: c.name, text: c.text, title: c.title, rows: c.rowCount, template: c.template.name, columns: c.template.columns.length })),
      flex_chart_markers: async () => (demo.chartMarkers || []).map((m) => ({ ...m, count: Object.values(demo.charts || {}).reduce((n, c) => n + c.rows.reduce((k, r) => k + r.cells.filter((x) => x.kind === 'tag' && x.tag && x.tag.guid === m.guid).length, 0), 0) })),
      flex_text_tags: async () => (demo.tagList || []).map((t) => ({ ...t, count: Object.values(demo.texts).reduce((n, x) => n + (x.tags || []).filter((g) => g.tag.guid === t.guid).length, 0) })),
      flex_tag_occurrences: async (guid, q) => {
        const rows = [];
        for (const t of Object.values(demo.texts)) for (const g of t.tags || []) {
          if (g.tag.guid !== guid) continue;
          const a = t.segments.find((s) => s.n === g.from.seg), b = t.segments.find((s) => s.n === g.to.seg);
          if (!a || !b) continue;
          const toks = a.words || [], last = a === b ? g.to.w : toks.length - 1;
          rows.push({ text: t.guid, title: t.title, seg: a.n, segTo: b.n, label: a.label, labelTo: b.label, at: [a.guid.replace(/-/g, '').slice(-12), b.guid.replace(/-/g, '').slice(-12)], words: toks.slice(g.from.w, last + 1).filter((w) => !w.punct).map((w) => w.txt).join(' ') + (a === b ? '' : '…') });
        }
        const ql = (q || '').toLowerCase();
        return rows.filter((r) => !ql || (r.title + ' ' + r.words + ' ' + r.label).toLowerCase().includes(ql));
      },
      set_tag_filters: async (filters) => { config.tagStyles = config.tagStyles || { project: {}, tab: {}, folder: {}, note: {}, text: {}, filters: [] }; config.tagStyles.filters = (filters || []).map((f, i) => ({ id: f.id || 'f' + i, name: f.name || '', enabled: f.enabled !== false, rules: f.rules || [] })); return config.tagStyles; },
      flex_tags_used: async () => {
        const out = {};
        for (const n of list()) for (const m of (n.body || '').matchAll(/\{\{flex:text ([0-9a-f-]{36})/g)) for (const g of ((demo.texts[m[1]] || {}).tags || [])) for (const tok of [g.tag.name, g.tag.abbr]) if (tok) { const k = tok.toLowerCase().replace(/ /g, '_'); (out[k] = out[k] || []).includes(n.id) || out[k].push(n.id); }
        return out;
      },
      set_tag_styles: async (kind, key, rules) => { config.tagStyles = config.tagStyles || { project: {}, tab: {}, folder: {}, note: {}, text: {}, filters: [] }; config.tagStyles[kind] = config.tagStyles[kind] || {}; if (rules && rules.length) config.tagStyles[kind][key] = rules; else delete config.tagStyles[kind][key]; return config.tagStyles; },
      flex_choose_file: async () => null, flex_locate: async () => [],
      open_in_flex: async (url) => { FS.toast('Would open in FLEx: ' + url); return true; },
      open_web: async (url) => { try { window.open(url, '_blank', 'noopener'); } catch (e) { /* ignore */ } return true; },
      flex_open_object: async (kind, guid) => { FS.toast('Would open in FLEx: ' + kind + ' ' + guid); return true; },
      audio_clip: async () => ({ found: false, fileUrl: '', clipUrl: '', needsCapture: false, mediaGuid: '' }),
      audio_store_clip: async () => ({ clipUrl: '' }), export_clips: async (items) => (items || []).map((it) => ({ id: it.id, error: 'no audio in the browser demo' })), audio_browse_media: async () => null, audio_set_media_path: async () => ({}),
      save_file_as: async () => null, notebook_stamp: async () => ({ stamp: 'mock' }), note_changed_on_disk: async () => null,
      export_note_markdown: async () => null, export_note_html: async () => null, export_note_docx: async () => null, export_note_xlsx: async () => null, export_note_pptx: async () => null, export_note_pdf: async () => ({ fallback: true }), export_notebook_zip: async () => null, import_notebook_zip: async () => null, choose_notebook_folder: async () => null, open_notebook: async () => init(), reveal_notebook: async () => false, reveal_note: async () => false,
    };
  };
})();
