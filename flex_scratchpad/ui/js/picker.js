/* picker.js — the "Insert FLEx object" dialog: search the lexicon or the texts of the open
 * project, preview, pick a segment range (click first and last, or find by pasted text), and
 * insert as a rendered embed or as a link chip. Also the chooser shown when a FLEx hyperlink
 * (Edit → Copy Location as Hyperlink) is pasted into a note. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;

  function embedFor(kind, guid, extra) {
    const spec = { kind, guid, seg: null, at: null, lines: null, styles: [], label: '', extra: {} };
    if (extra && extra.seg) spec.seg = extra.seg;
    if (extra && extra.at && extra.at[0]) spec.at = [extra.at[0], extra.at[1] || extra.at[0]];   // the located segments' own GUIDs
    else if (extra && extra.index && spec.seg) {          // anchor the range to its segments' GUIDs
      const at = (n) => { const e = extra.index.find((i) => i.n === n); return e ? e.guid.replace(/-/g, '').slice(-12) : ''; };
      if (at(spec.seg[0])) spec.at = [at(spec.seg[0]), at(spec.seg[1]) || at(spec.seg[0])];
    }
    return FS.flexref.serialize(spec);
  }
  function linkFor(kind, guid, label) {
    return '[' + (label || kind).replace(/[\[\]]/g, '') + '](flex:' + (kind === 'sense' ? 'entry' : kind) + '/' + guid + ')';
  }

  /* onInsert(markdown, asBlock) */
  function open(onInsert, opts) {
    opts = opts || {};
    const m = FS.modal({ title: 'Insert from FieldWorks' });
    const state = { mode: opts.mode || 'lexicon', sel: null, text: null, range: null, anchor: null, lines: null, tag: null, occ: [] };
    const left = el('div', { class: 'picker-left' });
    const right = el('div', { class: 'picker-right' });
    const tabs = el('div', { class: 'picker-tabs' });
    const search = el('input', { type: 'text', placeholder: 'Search headword or gloss…', autofocus: true });
    const results = el('div', { class: 'picker-results' });
    const preview = el('div', { class: 'picker-preview' }, el('div', { class: 'muted small' }, 'Pick something on the left.'));
    const optsRow = el('div', { class: 'picker-opts' });
    const btnRow = el('div', { class: 'btn-row' });
    left.append(tabs, search, results);
    right.append(preview, optsRow, btnRow);
    m.body.appendChild(el('div', { class: 'picker' }, left, right));
    // FLEx text markup TAGS as a way in (Seth, 2026-10-17): a tag, then every place it is used
    const modes = [['lexicon', 'Lexicon'], ['texts', 'Texts'], ['charts', 'Text charts'], ['tags', 'FLEx tags']];
    const setMode = (mode) => {
      state.mode = mode; state.sel = null; state.text = null; state.range = null; state.tag = null; state.obj = null; preview.onscroll = null;
      tabs.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
      search.placeholder = mode === 'lexicon' ? 'Search headword or gloss…' : mode === 'tags' ? 'Search tags by name…' : mode === 'charts' ? 'Search charts by text or name…' : 'Search text titles…';
      preview.innerHTML = '<div class="muted small">' + (mode === 'lexicon' ? 'Pick an entry on the left.' : mode === 'tags' ? 'Pick a tag, then one of the places it is used.' : mode === 'charts' ? 'Pick a chart, then click the first and last row of the range (or insert it whole).' : 'Pick a text, then click the first and last segment of the range.') + '</div>';
      optsRow.innerHTML = ''; btnRow.innerHTML = '';
      doSearch();
      search.focus();
    };
    for (const [mode, label] of modes) tabs.appendChild(el('button', { dataset: { mode }, onclick: () => setMode(mode) }, label));
    const doSearch = FS.debounce(async () => {
      results.innerHTML = '<div class="pick-item muted">Searching…</div>';
      try {
        if (state.mode === 'lexicon') {
          const hits = await FS.api.flex_search_entries(search.value.trim(), 60);
          results.innerHTML = '';
          if (!hits.length) results.appendChild(el('div', { class: 'pick-item muted' }, search.value ? 'No entries match.' : 'Type to search the lexicon.'));
          for (const h of hits) {
            const it = el('div', { class: 'pick-item' }, el('span', { class: 'hw' }, h.headword || h.lexeme || '?'), h.pos ? el('span', { class: 'pos' }, h.pos) : null, el('span', { class: 'gl' }, h.gloss || ''), h.senses > 1 ? el('span', { class: 'n' }, h.senses + ' senses') : null);
            it.addEventListener('click', () => { results.querySelectorAll('.on').forEach((x) => x.classList.remove('on')); it.classList.add('on'); pickEntry(h); });
            results.appendChild(it);
          }
        } else if (state.mode === 'charts') {
          const q = search.value.trim();
          const ql = q.toLowerCase();
          const all = await FS.api.flex_charts('');
          // charts with rows first (FLEx makes an empty chart whenever a template's tab is opened)
          const hits = all.filter((c) => !ql || ((c.title || '') + ' ' + (c.name || '') + ' ' + (c.template || '')).toLowerCase().includes(ql)).sort((a, b) => (b.rows ? 1 : 0) - (a.rows ? 1 : 0) || (a.title || '').localeCompare(b.title || '') || (a.template || '').localeCompare(b.template || ''));
          results.innerHTML = '';
          if (!hits.length && !q) results.appendChild(el('div', { class: 'pick-item muted' }, all.length ? 'No chart matches.' : 'This project has no text charts yet (Texts & Words › Text Chart in FieldWorks).'));
          for (const c of hits) {
            const it = el('div', { class: 'pick-item' + (c.rows ? '' : ' muted'), 'data-test': 'pick-chart' }, el('span', { class: 'hw' }, c.title || '(untitled text)'), el('span', { class: 'pos' }, c.name || 'chart'), el('span', { class: 'n' }, (c.rows ? c.rows + ' row' + (c.rows === 1 ? '' : 's') : 'empty') + (c.cached ? ' · cached' : '')));
            it.addEventListener('click', () => { results.querySelectorAll('.on').forEach((x) => x.classList.remove('on')); it.classList.add('on'); pickChart(c); });
            results.appendChild(it);
          }
          // CHART SEARCH (Seth, 2026-10-18): the rows matching the words / col: / marker: / lex: query
          if (q && FS.api.chart_search) {
            let rows = [];
            try { rows = await FS.api.chart_search(q); } catch (e) { results.appendChild(el('div', { class: 'pick-item', style: { color: 'var(--danger)' } }, e.message)); rows = null; }
            if (rows) {
              state.rowHits = rows;
              const lex = /(?:^|\s)(?:lex|word|words):("[^"]+"|\S+)/i.exec(q);
              results.appendChild(el('div', { class: 'pick-group', style: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' } }, el('b', {}, 'Chart rows'), el('span', { class: 'muted' }, rows.length + ' match' + (rows.length === 1 ? '' : 'es')),
                el('span', { class: 'spacer' }),
                lex && FS.chartProfile ? el('button', { class: 'btn', 'data-test': 'chart-profile', title: 'Which columns this item sits in, across every chart', onclick: () => { m.close(); FS.chartProfile(lex[1].replace(/^"|"$/g, '')); } }, 'Column profile\u2026') : null));
              if (rows.length) results.appendChild(el('div', { class: 'pick-item', style: { justifyContent: 'flex-end', gap: '6px' } },
                FS.chartCollection ? el('button', { class: 'btn', 'data-test': 'collect-chart-rows', title: 'A new collection of these rows, which can take in new matches later', onclick: () => { m.close(); FS.chartCollection(q); } }, 'Collect into a new collection\u2026') : null,
                el('button', { class: 'btn', 'data-test': 'insert-all-chart-rows', title: 'One chart row per match, in chart order, with the headings', onclick: () => { onInsert(rows.map((r) => embedFor('chart', r.chart, { seg: [r.row, r.row], at: [r.at, r.at] })).join('\n\n'), true); m.close(); } }, 'Insert all ' + rows.length + ' as rows')));
              if (!rows.length) results.appendChild(el('div', { class: 'pick-item muted' }, 'No chart row matches. Try words, col:Name, marker:Name, lex:form, gloss:…'));
              for (const r of rows) {
                const cells = r.cells.filter((c) => !r.hits.length || r.hits.includes(c.colN));
                const it = el('div', { class: 'pick-item', 'data-test': 'pick-chart-row' }, el('span', { class: 'hw' }, (r.chartName || 'Chart') + ' \u00b7 ' + (r.title || '')), el('span', { class: 'pos' }, r.label), el('span', { class: 'gl' }, cells.map((c) => c.col + ': ' + c.words.join(' ')).join(' | ') + (r.markers.length ? '  \u2690' + [...new Set(r.markers)].slice(0, 2).join(',') : '')));
                it.addEventListener('click', async () => { results.querySelectorAll('.on').forEach((x) => x.classList.remove('on')); it.classList.add('on'); await pickChart({ guid: r.chart, name: r.chartName, title: r.title }); state.range = [r.row, r.row]; state.anchor = null; if (state.redraw) state.redraw(); const tr = preview.querySelector('tr.crow[data-row="' + r.row + '"]'); if (tr) tr.scrollIntoView({ block: 'center' }); });
                results.appendChild(it);
              }
            }
          }
        } else if (state.mode === 'tags' && !state.tag) {
          const q = search.value.trim().toLowerCase();
          const all = await FS.api.flex_text_tags();
          const tags = all.filter((t) => !q || (t.name + ' ' + t.abbr + ' ' + (t.path || [t.group]).join(' ')).toLowerCase().includes(q));
          if (FS.tagstyles && !FS.tagstyles.list().length) FS.tagstyles.setList(all);
          results.innerHTML = '';
          if (!tags.length) results.appendChild(el('div', { class: 'pick-item muted' }, q ? 'No tag matches.' : 'This project has no text markup tags.'));
          // the list's own hierarchy, its groups fold-able (a search opens them all)
          const leaf = (t) => {
            const look = FS.tagstyles ? FS.tagstyles.resolve(t, null) : { bg: '#ffd6a5' };
            const it = el('div', { class: 'pick-item', 'data-test': 'pick-tag' }, el('span', { class: 'tag-sw', style: { background: look.bg } }), el('span', { class: 'hw' }, t.name), t.abbr && t.abbr !== t.name ? el('span', { class: 'pos' }, t.abbr) : null, t.count != null ? el('span', { class: 'n' }, t.count + ' place' + (t.count === 1 ? '' : 's')) : null);
            it.addEventListener('click', () => { state.tag = t; search.value = ''; search.placeholder = 'Filter the places…'; doSearch(); });
            return it;
          };
          if (FS.tagstyles && FS.tagstyles.renderTagTree) { const tree = el('div'); FS.tagstyles.renderTagTree(tree, tags, { leaf, open: !!q }); results.appendChild(tree); }
          else for (const t of tags) results.appendChild(leaf(t));
        } else if (state.mode === 'tags') {
          const rows = await FS.api.flex_tag_occurrences(state.tag.guid, search.value.trim());
          state.occ = rows;
          results.innerHTML = '';
          const back = el('button', { class: 'lnk', onclick: () => { state.tag = null; search.value = ''; search.placeholder = 'Search tags by name…'; doSearch(); } }, '\u2190 All tags');
          results.appendChild(el('div', { class: 'pick-group', style: { display: 'flex', gap: '8px', alignItems: 'center' } }, back, el('b', {}, state.tag.name), el('span', { class: 'muted' }, rows.length + ' place' + (rows.length === 1 ? '' : 's'))));
          if (rows.length) results.appendChild(el('div', { class: 'pick-item', style: { justifyContent: 'flex-end', gap: '6px' } },
            FS.ruleCollection ? el('button', { class: 'btn', 'data-test': 'collect-tagged', title: 'A new example collection of every line with this tag, which can take in new matches later', onclick: () => { m.close(); FS.ruleCollection({ tags: [state.tag.name] }); } }, 'Collect into a new collection\u2026') : null,
            el('button', { class: 'btn', 'data-test': 'insert-all-tagged', title: 'One example per place, in text order', onclick: () => { onInsert(rows.map((o) => embedFor('text', o.text, { seg: [o.seg, o.segTo], at: o.at })).join('\n\n'), true); m.close(); } }, 'Insert all ' + rows.length + ' as examples')));
          if (!rows.length) results.appendChild(el('div', { class: 'pick-item muted' }, search.value ? 'No place matches.' : 'This tag is not used anywhere.'));
          for (const o of rows) {
            const where = o.label + (o.segTo !== o.seg ? '\u2013' + o.labelTo : '');
            const it = el('div', { class: 'pick-item', 'data-test': 'pick-occurrence' }, el('span', { class: 'hw' }, o.title || '(untitled)'), el('span', { class: 'pos' }, where), el('span', { class: 'gl' }, o.words || ''));
            it.addEventListener('click', () => { results.querySelectorAll('.on').forEach((x) => x.classList.remove('on')); it.classList.add('on'); pickText({ guid: o.text, title: o.title, segmentCount: 0 }, [o.seg, o.segTo]); });
            results.appendChild(it);
          }
        } else {
          const hits = await FS.api.flex_texts(search.value.trim());
          results.innerHTML = '';
          if (!hits.length) results.appendChild(el('div', { class: 'pick-item muted' }, 'No texts.'));
          for (const h of hits) {
            const it = el('div', { class: 'pick-item' }, el('span', { class: 'hw' }, h.title || '(untitled)'), h.abbrev ? el('span', { class: 'pos' }, h.abbrev) : null, el('span', { class: 'n' }, (h.segmentCount || 0) + ' seg' + (h.hasMedia ? ' ♫' : '')));
            it.addEventListener('click', () => { results.querySelectorAll('.on').forEach((x) => x.classList.remove('on')); it.classList.add('on'); pickText(h); });
            results.appendChild(it);
          }
        }
      } catch (e) {
        results.innerHTML = '';
        results.appendChild(el('div', { class: 'pick-item', style: { color: 'var(--danger)' } }, e.message));
      }
    }, 180);
    search.addEventListener('input', doSearch);

    async function pickEntry(h) {
      state.sel = { kind: 'entry', guid: h.guid, title: h.headword };
      preview.innerHTML = '';
      const host = el('div');
      preview.appendChild(host);
      await FS.interlinear.render(host, { kind: 'entry', guid: h.guid, styles: [], lines: null, seg: null, label: '', extra: {} }, { editable: false });
      // allow choosing a sense
      host.querySelectorAll('.sense').forEach((s, i) => {
        s.classList.add('clickable');
        s.title = 'Insert just this sense';
        s.addEventListener('click', () => { host.querySelectorAll('.sense').forEach((x) => x.classList.remove('focus')); s.classList.add('focus'); state.sel.senseIndex = i; });
      });
      optsRow.innerHTML = '';
      btnRow.innerHTML = '';
      btnRow.append(
        el('button', { class: 'btn', onclick: () => { onInsert(linkFor('entry', h.guid, h.headword), false); m.close(); } }, 'Insert link'),
        el('button', { class: 'btn primary', onclick: async () => {
          let guid = h.guid, kind = 'entry';
          if (state.sel.senseIndex != null) { try { const e = await FS.api.flex_get('entry', h.guid); const s = e.senses[state.sel.senseIndex]; if (s && s.guid) { guid = s.guid; kind = 'sense'; } } catch (e) { /* fall back to the entry */ } }
          onInsert(embedFor(kind, guid), true); m.close();
        } }, 'Insert rendered'));
    }

    async function pickText(h, range) {
      state.text = h; state.range = null; state.anchor = null;
      preview.innerHTML = '<div class="flex-loading">Loading…</div>';
      let obj;
      try {
        obj = await FS.api.flex_get('text', h.guid, 1, Math.min(h.segmentCount || 60, 60));
        if (range && range[1] > (obj.range ? obj.range[1] : 60)) obj = await FS.api.flex_get('text', h.guid, Math.max(1, range[0] - 5), range[1] + 30);   // a tagged place further down
      } catch (e) { preview.innerHTML = ''; preview.appendChild(el('div', { class: 'flex-err' }, e.message)); return; }
      state.obj = obj;
      renderPreview();
      // THE REST OF THE TEXT ON SCROLL (Seth, 2026-10-19: the preview "only return[s] the first few
      // rows … I can't scroll to other rows"): the backend pages 60 lines at a time, so the next
      // page is fetched and appended as the preview nears its end, until the text is whole
      let loadingMore = false;
      const loadMore = async () => {
        const cur = state.obj;
        if (!cur || cur !== obj || loadingMore) return;
        const last = cur.segments.length ? cur.segments[cur.segments.length - 1].n : 0;
        if (!last || last >= (cur.segmentCount || 0)) return;
        loadingMore = true;
        try {
          const more = await FS.api.flex_get('text', h.guid, last + 1, Math.min(cur.segmentCount, last + 60));
          if (state.obj !== cur) return;
          const seen = new Set(cur.segments.map((s) => s.n));
          cur.segments = cur.segments.concat((more.segments || []).filter((s) => !seen.has(s.n)));
          cur.range = [cur.range ? cur.range[0] : 1, (more.range || [0, last])[1]];
          const st = preview.scrollTop;
          renderPreview();
          preview.scrollTop = st;
        } catch (e) { FS.toast(e.message, 'error'); } finally { loadingMore = false; }
      };
      preview.onscroll = () => { if (preview.scrollTop + preview.clientHeight > preview.scrollHeight - 240) loadMore(); };
      optsRow.innerHTML = '';
      // The range fields take either numbering: FLEx's paragraph.segment ("4.1") or the running
      // count; they display FLEx's, and `seg=` in the embed always gets the running count.
      const show = (n) => FS.interlinear.labelOf(state.obj, n);
      const read = (v, fallback) => {
        const n = FS.interlinear.numberFor(state.obj, v, 0);
        if (!n) { if (/^\d+\.\d+$/.test(String(v).trim())) FS.toast('No segment ' + String(v).trim() + ' in this text'); return fallback; }
        return Math.min(n, obj.segmentCount);
      };
      const from = el('input', { type: 'text', value: show(1), style: { width: '56px' }, title: 'First segment — FLEx number (4.1) or running count' });
      const to = el('input', { type: 'text', value: show(Math.min(obj.segmentCount, 3)), style: { width: '56px' }, title: 'Last segment — FLEx number (4.1) or running count' });
      const find = el('input', { type: 'text', placeholder: 'find segment by text…', style: { width: '180px', border: '1px solid var(--border)', borderRadius: '6px', padding: '3px 6px', background: 'var(--bg)' } });
      const findBtn = el('button', { class: 'btn', onclick: async () => {
        if (!find.value.trim()) return;
        try {
          const hits = await FS.api.flex_find_in_text(h.guid, find.value.trim());
          if (!hits.length) { FS.toast('No segment contains that text'); return; }
          state.range = [hits[0], hits[0]];
          if (hits[0] > (obj.range ? obj.range[1] : 60)) { obj = await FS.api.flex_get('text', h.guid, Math.max(1, hits[0] - 5), hits[0] + 30); state.obj = obj; }
          from.value = show(hits[0]); to.value = show(hits[0]);
          renderPreview();
          const seg = preview.querySelector('.segment[data-n="' + hits[0] + '"]');
          if (seg) seg.scrollIntoView({ block: 'center' });
          FS.toast(hits.length + ' segment' + (hits.length > 1 ? 's' : '') + ' match: ' + hits.slice(0, 8).map(show).join(', '));
        } catch (e) { FS.toast(e.message, 'error'); }
      } }, 'Find');
      const applyRange = () => { const a = Math.max(1, read(from.value, 1)), b = Math.max(a, read(to.value, a)); state.range = [a, b]; from.value = show(a); to.value = show(b); renderPreview(); };
      from.addEventListener('change', applyRange); to.addEventListener('change', applyRange);
      state.setRange = (a, b) => { from.value = show(a); to.value = show(b); state.range = [a, b]; renderPreview(); };
      if (range) { state.setRange(range[0], range[1]); const segEl = preview.querySelector('.segment[data-n="' + range[0] + '"]'); if (segEl) segEl.scrollIntoView({ block: 'center' }); }
      find.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); findBtn.click(); } });
      optsRow.append(el('label', {}, 'Segments ', from, ' – ', to), el('span', { class: 'muted' }, 'of ' + obj.segmentCount), find, findBtn);
      btnRow.innerHTML = '';
      btnRow.append(
        el('button', { class: 'btn', onclick: () => { onInsert(linkFor('text', h.guid, h.title), false); m.close(); } }, 'Insert link'),
        el('button', { class: 'btn', onclick: () => { onInsert(embedFor('text', h.guid), true); m.close(); } }, 'Whole text'),
        el('button', { class: 'btn primary', onclick: () => { const r = state.range || [read(from.value, 1), read(to.value, 1)]; onInsert(embedFor('text', h.guid, { seg: [Math.min(r[0], r[1]), Math.max(r[0], r[1])], index: state.obj && state.obj.index }), true); m.close(); } }, 'Insert segments'));
    }

    /* A text chart: the whole chart in the preview; click the first and last row of a range. */
    async function pickChart(c) {
      state.chart = c; state.range = null; state.anchor = null;
      preview.innerHTML = '<div class="flex-loading">Loading…</div>';
      let obj;
      try { obj = await FS.api.flex_get('chart', c.guid); } catch (e) { preview.innerHTML = ''; preview.appendChild(el('div', { class: 'flex-err' }, e.message)); return; }
      state.obj = obj;
      const draw = () => {
        preview.innerHTML = '';
        preview.appendChild(el('div', { class: 'muted small', style: { marginBottom: '6px' } }, 'Click the first and then the last row of the range you want; the column headings always come along.'));
        const node = FS.chart.renderChart(obj, { kind: 'chart', guid: obj.guid, seg: null, at: null, lines: null, styles: [], label: '', extra: {} }, { editable: false, context: true });
        node.querySelectorAll('tr.crow').forEach((tr) => {
          const n = +tr.dataset.row;
          tr.classList.add('pick');
          if (state.range && n >= state.range[0] && n <= state.range[1]) tr.classList.add('in-range');
          tr.addEventListener('click', (e) => {
            if (e.target.closest('a, button')) return;
            if (state.anchor == null || (state.range && state.range[0] !== state.range[1])) { state.anchor = n; state.range = [n, n]; }
            else { state.range = [Math.min(state.anchor, n), Math.max(state.anchor, n)]; state.anchor = null; }
            draw();
          });
        });
        preview.appendChild(node);
        const lab = (n) => { const e = (obj.index || []).find((i) => i.n === n); return e ? e.label : String(n); };
        rangeInfo.textContent = state.range ? (state.range[0] === state.range[1] ? 'Row ' + lab(state.range[0]) : 'Rows ' + lab(state.range[0]) + ' – ' + lab(state.range[1])) : 'No rows picked yet';
      };
      const rangeInfo = el('span', { class: 'muted' });
      optsRow.innerHTML = '';
      optsRow.append(rangeInfo, el('span', { class: 'muted small' }, 'of ' + (obj.rowCount || 0) + ' rows'));
      state.redraw = draw;
      draw();
      const anchors = () => { const at = (n) => { const e = (obj.index || []).find((i) => i.n === n); return e ? e.guid.replace(/-/g, '').slice(-12) : ''; }; return state.range && at(state.range[0]) ? [at(state.range[0]), at(state.range[1]) || at(state.range[0])] : null; };
      btnRow.innerHTML = '';
      btnRow.append(
        el('button', { class: 'btn', onclick: () => { onInsert(linkFor('chart', c.guid, (c.name || 'Chart') + ' — ' + (c.title || '')), false); m.close(); } }, 'Insert link'),
        el('button', { class: 'btn', 'data-test': 'insert-whole-chart', onclick: () => { onInsert(embedFor('chart', c.guid), true); m.close(); } }, 'Whole chart'),
        el('button', { class: 'btn primary', 'data-test': 'insert-chart-rows', onclick: () => { if (!state.range) { FS.toast('Click the first and last row first'); return; } onInsert(embedFor('chart', c.guid, { seg: state.range, at: anchors() }), true); m.close(); } }, 'Insert rows'));
    }

    function renderPreview() {
      const obj = state.obj;
      preview.innerHTML = '';
      const node = FS.interlinear.renderText(obj, { kind: 'text', guid: obj.guid, seg: obj.range, lines: null, styles: [], label: '', extra: {} }, { editable: false });
      node.querySelectorAll('.segment').forEach((segEl) => {
        const n = +segEl.dataset.n;
        segEl.classList.add('pick');
        if (state.range && n >= state.range[0] && n <= state.range[1]) segEl.classList.add('in-range');
        segEl.addEventListener('click', (e) => {
          if (e.target.closest('.seg-play, a, button')) return;
          if (state.anchor == null || e.shiftKey === false && state.range && state.range[0] !== state.range[1]) { state.anchor = n; state.setRange(n, n); }
          else { const a = Math.min(state.anchor, n), b = Math.max(state.anchor, n); state.setRange(a, b); state.anchor = null; }
        });
      });
      preview.appendChild(el('div', { class: 'muted small', style: { marginBottom: '6px' } }, 'Click the first and then the last segment of the range you want.'));
      preview.appendChild(node);
    }

    setMode(state.mode);
    if (opts.mode === 'tags' && opts.tag) {      // opened on one tag (an example's ⚑ → 🔍)
      FS.api.flex_text_tags().then((l) => { state.tag = l.find((t) => t.guid === opts.tag) || { guid: opts.tag, name: 'this tag', abbr: '' }; search.placeholder = 'Filter the places…'; doSearch(); }, () => {});
    }
    return m;
  }

  /* A FLEx link was pasted: resolve it and ask how to insert it. insert(md, asBlock). */
  async function pasteChooser(text, insert) {
    let info = null, gaveUp = false;
    const done = FS.busy('Looking up the FieldWorks link…', { slowMsg: 'Still looking… the first lookup takes longest', onCancel: () => { gaveUp = true; insert(text, false); }, cancelLabel: 'Paste as text' });
    try { info = await FS.api.flex_resolve_link(text); } catch (e) { info = null; } finally { done(); }
    if (gaveUp) return;
    if (!info) { insert(text, false); return; }
    const m = FS.modal({ title: 'FieldWorks link', class: 'narrow' });
    const what = info.kind === 'entry' ? 'Entry' : info.kind === 'text' ? 'Text' : info.kind === 'wordform' ? 'Wordform' : 'Object';
    m.body.appendChild(el('p', {}, el('b', {}, what + ': '), info.title || info.guid, info.sense ? ' (sense ' + info.sense + ')' : '', info.seg ? ' — segment ' + info.seg + (info.segTo && info.segTo !== info.seg ? '–' + info.segTo : '') : ''));
    if (info.database && info.unresolved) m.body.appendChild(el('p', { class: 'muted small' }, 'This link points at the project “' + info.database + '”, which is not the open project; the object will show once that project is open (it is inserted anyway).'));
    const row = el('div', { class: 'btn-row' });
    row.appendChild(el('button', { class: 'btn', onclick: () => { insert(text, false); m.close(); } }, 'Paste as text'));
    row.appendChild(el('button', { class: 'btn', onclick: () => { insert(linkFor(info.kind === 'other' ? 'entry' : info.kind, info.guid, info.title || what), false); m.close(); } }, 'Insert link'));
    if (info.kind !== 'other') row.appendChild(el('button', { class: 'btn primary', onclick: () => { const extra = info.seg ? { seg: [info.seg, info.segTo || info.seg] } : null; insert(embedFor(info.kind, info.guid, extra), true); m.close(); } }, 'Insert rendered'));
    m.body.appendChild(row);
  }

  /* Interlinear lines were pasted: ask Python where they come from; offer the embed, or
   * fall back to a plain paste (fallback()) when nothing matches well enough. */
  async function locateChooser(text, insert, fallback) {
    let hits = [], gaveUp = false;
    // the lookup reads the project's segment index, which can take a while the first time
    // (Seth, 2026-10-16: "could we get a loading or 'searching…' spinner?")
    const done = FS.busy('Searching the project for these lines…', { slowMsg: 'Still searching… the first search takes longest', onCancel: () => { gaveUp = true; fallback(); }, cancelLabel: 'Paste as text' });
    try { hits = await FS.api.flex_locate(text); } catch (e) { hits = []; } finally { done(); }
    if (gaveUp) return;
    const best = hits[0];
    if (!best || best.score < 2) {
      // rows copied from FLEx that match nothing: say what makes a paste reliable (Seth,
      // 2026-10-14: "inform users that to paste … they need to have the word line showing")
      if (/^(\d+(\.\d+)?\t)?\s*(Word|Morphemes|Lex\.|Free|Literal|Note)\b/im.test(text) && !/^(\d+(\.\d+)?\t)?\s*Word(\s|\t)/im.test(text)) {
        FS.toast('Nothing in the project matched these FLEx lines. Copying works best with the Word line showing in FLEx (Configure interlinear lines → Word), then copy again.', 'warn');
      } else if (/^(\d+(\.\d+)?\t)?\s*(Word|Morphemes|Lex\.|Free)\b/im.test(text)) {
        FS.toast('Nothing in the project matched these FLEx lines; pasted as text.', 'warn');
      }
      fallback(); return;
    }
    const m = FS.modal({ title: 'Found in FieldWorks', class: 'narrow' });
    const lines = text.trim().split('\n').filter((l) => l.trim()).length;
    const pick = { hit: best };
    // FLEx's own numbers ("12.3–14") when the index has them: what was copied, as FLEx shows it
    const where = (h) => (h.label ? (h.labelTo && h.labelTo !== h.label ? h.label + '\u2013' + h.labelTo : h.label) : (h.segTo !== h.seg ? h.seg + '\u2013' + h.segTo : String(h.seg)));
    const plural = (h) => (h.label ? h.labelTo && h.labelTo !== h.label : h.segTo !== h.seg);
    m.body.appendChild(el('p', { 'data-test': 'locate-where' }, 'These lines match ', el('b', {}, best.title), ', segment' + (plural(best) ? 's ' : ' ') + where(best) + (best.matched < best.of ? ' (' + best.matched + ' of ' + best.of + ' lines matched)' : '') + '.'));
    if (hits.length > 1) {
      const sel = el('select', { style: { width: '100%' } });
      hits.forEach((h, i) => sel.appendChild(el('option', { value: i }, h.title + ' \u2014 ' + where(h) + (h.matched < h.of ? ' (' + h.matched + '/' + h.of + ')' : ''))));
      sel.addEventListener('change', () => { pick.hit = hits[+sel.value]; });
      m.body.appendChild(el('div', { class: 'form-row' }, el('label', {}, 'Other matches'), sel));
    }
    const row = el('div', { class: 'btn-row' });
    row.appendChild(el('button', { class: 'btn', onclick: () => { m.close(); fallback(); } }, 'Paste as text'));
    row.appendChild(el('button', { class: 'btn', onclick: () => { insert(linkFor('text', pick.hit.guid, pick.hit.title), false); m.close(); } }, 'Insert link'));
    row.appendChild(el('button', { class: 'btn primary', onclick: () => { insert(embedFor('text', pick.hit.guid, { seg: [pick.hit.seg, pick.hit.segTo], at: pick.hit.at }), true); m.close(); } }, 'Insert rendered'));
    m.body.appendChild(row);
    void lines;
  }

  FS.picker = { open, pasteChooser, locateChooser, embedFor, linkFor };
})();
