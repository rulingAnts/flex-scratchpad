/* chartnote.js — a CHART NOTE: a note that IS one FieldWorks text chart (Seth, 2026-10-18: "a text
 * chart note type (similar to the example collection, except that it would focus on one text
 * chart, allowing styling/highlights/etc of words, glosses, etc, as well as cells and rows)" with
 * "custom columns … (a) a user-custom-defined list of choices … project-wide … (b) some kind of
 * formula or rule … (c) just an extra notes column … These custom columns would be searchable").
 *
 * The note's header says `kind: chart` and `chart: <guid>`; its BODY is ours (like a collection's):
 *
 *     {{flex:chart <guid> lines=txt,gls free=row cols=… hl=r2 b=r3c4.1 …}}   ← the VIEW: every setting
 *                                                                            and the user's styles
 *     ## Custom columns
 *     | Column | Kind | Settings |
 *     |---|---|---|
 *     | Status | list | Information status |          ← a project-wide choice list, by name
 *     | Comment | notes | |
 *     | Role | rule | marker:Agent → A [row hl#fde68a]; col:Subject → S |
 *
 *     ## Values
 *     | Row | Status | Comment |
 *     |---|---|---|
 *     | 1a #000000000010 | new | Subject fronted |      ← keyed by the row's anchor (its GUID's tail)
 *
 * Two Markdown tables, so the file reads anywhere and the notebook index searches the values for
 * free. Rule columns are computed, never stored. Several chart notes may share one FLEx chart,
 * each with its own view, filters and custom columns.
 *
 * RULES (a rule column's Settings): cases separated by `;`, each `<expression> → <text> [styles]`,
 * the first matching case gives the cell its text (and its style, to the `cell` by default or
 * to the whole `row`). Terms: marker:Name (a chart tag on the row; `*` = any), col:Name (words in
 * that column: a name, Group/Name, c3), clause:dependent|speech|song|normal, moved (a moved-text
 * marker), moved:preposed|postposed, clauseref (a clause marker), endsent, endpara, depstart,
 * depend, words:"ka-", gloss:"sleep", label:"2a", and <List column>:value (a list column's value;
 * `*` = any) — joined with `and`, `or`, `not`, parentheses. Styles in brackets: row | cell,
 * hl / hl#rrggbb, b, i, u, c#rrggbb. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const el = FS.el;
  const R = FS.flexref;
  const C = FS.chart;
  const H_COLS = '## Custom columns';
  const H_VALS = '## Values';
  const KINDS = { list: 'Choice list', notes: 'Notes', rule: 'Rule' };
  const anchorOf = (guid) => String(guid || '').replace(/-/g, '').slice(-12);

  /* ------------------------------------------------------------------ the body */
  const cellText = (s) => String(s == null ? '' : s).replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>').trim();
  const unCell = (s) => String(s || '').replace(/<br\s*\/?>/gi, '\n').replace(/\\\|/g, '|').trim();
  const splitRow = (line) => {
    const cells = [];
    let cur = '';
    const s = line.trim().replace(/^\|/, '').replace(/\|\s*$/, '');
    for (let i = 0; i < s.length; i++) {
      if (s[i] === '\\' && s[i + 1] === '|') { cur += '\\|'; i++; continue; }
      if (s[i] === '|') { cells.push(cur); cur = ''; continue; }
      cur += s[i];
    }
    cells.push(cur);
    return cells.map((c) => c.trim());
  };
  const isSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
  function readTable(lines, i) {
    // the pipe table starting at line i (blank lines before it skipped): [header, rows, next i]
    while (i < lines.length && !lines[i].trim()) i++;
    if (i >= lines.length || !/^\s*\|/.test(lines[i])) return [null, [], i];
    const head = splitRow(lines[i++]);
    if (i < lines.length && isSep(lines[i])) i++;
    const rows = [];
    while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(splitRow(lines[i++]));
    return [head, rows, i];
  }

  function parse(body) {
    const st = { view: null, spec: null, columns: [], values: new Map(), labels: new Map(), other: '' };
    const lines = String(body || '').replace(/\r\n/g, '\n').split('\n');
    const other = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!st.view && R.isEmbedLine(line)) {
        const spec = R.parse(line.trim());
        if (spec && spec.kind === 'chart') { st.spec = spec; st.view = R.serialize(spec); i++; continue; }
      }
      if (line.trim() === H_COLS) {
        const [head, rows, next] = readTable(lines, i + 1);
        if (head) {
          for (const r of rows) {
            const name = unCell(r[0] || '');
            const kind = unCell(r[1] || '').toLowerCase();
            if (name && KINDS[kind]) st.columns.push({ name, kind, settings: unCell(r[2] || '') });
          }
          i = next;
          continue;
        }
      }
      if (line.trim() === H_VALS) {
        const [head, rows, next] = readTable(lines, i + 1);
        if (head) {
          const names = head.slice(1).map(unCell);
          for (const r of rows) {
            const m = /^(.*?)\s*#([0-9a-f]{4,32})\s*$/i.exec(unCell(r[0] || ''));
            if (!m) continue;
            const key = m[2].toLowerCase();
            st.labels.set(key, m[1].trim());
            const vals = {};
            names.forEach((n, k) => { const v = unCell(r[k + 1] || ''); if (n && v) vals[n] = v; });
            if (Object.keys(vals).length) st.values.set(key, vals);
          }
          i = next;
          continue;
        }
      }
      other.push(line);
      i++;
    }
    st.other = other.join('\n').replace(/^\n+|\n+$/g, '');
    return st;
  }

  function serialize(st) {
    const out = [];
    if (st.view) out.push(st.view);
    if (st.other) out.push('', st.other);
    if (st.columns.length) {
      out.push('', H_COLS, '', '| Column | Kind | Settings |', '|---|---|---|');
      const row = (cells) => '|' + cells.map((c) => (c ? ' ' + c + ' ' : ' ')).join('|') + '|';
      for (const c of st.columns) out.push(row([cellText(c.name), c.kind, cellText(c.settings || '')]));
      const stored = st.columns.filter((c) => c.kind !== 'rule');
      const keys = [...st.values.keys()].filter((k) => { const v = st.values.get(k) || {}; return stored.some((c) => v[c.name]); });
      if (stored.length && keys.length) {
        out.push('', H_VALS, '', '| Row | ' + stored.map((c) => cellText(c.name)).join(' | ') + ' |', '|' + '---|'.repeat(stored.length + 1));
        for (const k of keys) {
          const v = st.values.get(k) || {};
          out.push(row([cellText(st.labels.get(k) || '') + ' #' + k].concat(stored.map((c) => cellText(v[c.name] || '')))));
        }
      }
    }
    return out.join('\n').replace(/^\n+/, '') + '\n';
  }

  /* ------------------------------------------------------------------ rules */
  function tokenize(src) {
    const out = [];
    const re = /\s*(\(|\)|→|->|;|\[|\]|[^\s()\[\];"]+(?:"[^"]*")?|"[^"]*")/g;
    let m;
    while ((m = re.exec(src))) out.push(m[1] === '->' ? '→' : m[1]);
    return out;
  }
  const STYLE_TOKEN = /^(row|cell|b|i|u|hl|hl#[0-9a-f]{6}|c#[0-9a-f]{6})$/i;
  /* → [{expr, out, style: {scope, hl, b, i, u, c}, src}] ; throws on a malformed expression */
  function parseRule(text) {
    const cases = [];
    for (const part of String(text || '').split(';')) {
      if (!part.trim()) continue;
      const toks = tokenize(part);
      const arrow = toks.indexOf('→');
      const exprToks = arrow >= 0 ? toks.slice(0, arrow) : toks;
      const rest = arrow >= 0 ? toks.slice(arrow + 1) : [];
      let p = 0;
      const peek = () => exprToks[p];
      const next = () => exprToks[p++];
      const parseOr = () => { let a = parseAnd(); while (peek() && peek().toLowerCase() === 'or') { next(); const b = parseAnd(); a = { op: 'or', a, b }; } return a; };
      const parseAnd = () => { let a = parseNot(); while (peek() && peek().toLowerCase() === 'and') { next(); const b = parseNot(); a = { op: 'and', a, b }; } return a; };
      const parseNot = () => { if (peek() && peek().toLowerCase() === 'not') { next(); return { op: 'not', a: parseNot() }; } return parseAtom(); };
      const parseAtom = () => {
        const t = next();
        if (t == null) throw new Error('A term is missing in “' + part.trim() + '”');
        if (t === '(') { const e = parseOr(); if (next() !== ')') throw new Error('A “)” is missing in “' + part.trim() + '”'); return e; }
        if (t === ')') throw new Error('A “)” too many in “' + part.trim() + '”');
        const i = t.indexOf(':');
        const key = (i >= 0 ? t.slice(0, i) : t).toLowerCase();
        let val = i >= 0 ? t.slice(i + 1) : '';
        if (/^".*"$/.test(val)) val = val.slice(1, -1);
        return { op: 'term', key, val, raw: t };
      };
      const expr = exprToks.length ? parseOr() : { op: 'term', key: 'any', val: '' };
      if (p < exprToks.length) throw new Error('Unexpected “' + exprToks[p] + '” in “' + part.trim() + '”');
      // the output: text (quoted or bare words) up to the styles in brackets
      let out = '';
      const style = { scope: 'cell' };
      let k = 0;
      while (k < rest.length && rest[k] !== '[') { const t = rest[k++]; out += (out ? ' ' : '') + (/^".*"$/.test(t) ? t.slice(1, -1) : t); }
      if (rest[k] === '[') {
        k++;
        while (k < rest.length && rest[k] !== ']') {
          const t = rest[k++];
          if (!STYLE_TOKEN.test(t)) throw new Error('Unknown style “' + t + '” (row, cell, hl, hl#rrggbb, b, i, u, c#rrggbb)');
          const tl = t.toLowerCase();
          if (tl === 'row' || tl === 'cell') style.scope = tl;
          else if (tl.startsWith('hl')) style.hl = tl.length > 2 ? tl.slice(2) : '#fff2a8';
          else if (tl.startsWith('c#')) style.c = tl.slice(1);
          else style[tl] = true;
        }
      }
      cases.push({ expr, out: out || (arrow >= 0 ? '' : '✓'), style, src: part.trim() });
    }
    return cases;
  }
  const norm = (s) => (FS.normalize ? FS.normalize(String(s || ''), true) : String(s || '').toLowerCase());
  /* What a rule sees of one row. */
  function rowCtx(row, chart, values, columns) {
    const cols = (chart.template && chart.template.columns) || [];
    const byN = new Map(cols.map((c) => [c.n, c]));
    const ctx = { markers: new Set(), cols: new Set(), clause: row.clause || 'normal', moved: new Set(), flags: new Set(), words: [], glosses: [], label: row.label || '', lists: {} };
    for (const c of row.cells || []) {
      const col = byN.get(c.colN);
      if (c.kind === 'words' && col) {
        for (const k of [col.name, col.abbr, 'c' + col.n, (col.path || []).concat([col.name]).join('/'), col.guid]) if (k) ctx.cols.add(norm(k));
        for (const w of c.words || []) { if (!w.punct) { ctx.words.push(norm(w.txt)); ctx.glosses.push(norm(w.gls)); for (const m of w.morphs || []) { ctx.words.push(norm(m.form)); ctx.glosses.push(norm(m.gls)); } } }
      } else if (c.kind === 'tag' && c.tag) { ctx.markers.add(norm(c.tag.name)); ctx.markers.add(norm(c.tag.abbr)); for (const p of c.tag.path || []) ctx.markers.add(norm(p)); }
      else if (c.kind === 'moved') ctx.moved.add(c.preposed ? 'preposed' : 'postposed');
      else if (c.kind === 'clause') ctx.flags.add('clauseref');
    }
    if (row.endSent) ctx.flags.add('endsent');
    if (row.endPara) ctx.flags.add('endpara');
    if (row.depStart) ctx.flags.add('depstart');
    if (row.depEnd) ctx.flags.add('depend');
    const v = (values && values.get(anchorOf(row.guid))) || {};
    for (const c of columns || []) if (c.kind === 'list' || c.kind === 'notes') ctx.lists[norm(c.name)] = v[c.name] || '';
    return ctx;
  }
  function evalExpr(e, ctx) {
    switch (e.op) {
      case 'or': return evalExpr(e.a, ctx) || evalExpr(e.b, ctx);
      case 'and': return evalExpr(e.a, ctx) && evalExpr(e.b, ctx);
      case 'not': return !evalExpr(e.a, ctx);
      default: break;
    }
    const v = norm(e.val);
    switch (e.key) {
      case 'any': return true;
      case 'marker': return v === '*' ? ctx.markers.size > 0 : ctx.markers.has(v);
      case 'col': case 'column': return v === '*' ? ctx.cols.size > 0 : ctx.cols.has(v);
      case 'clause': return ctx.clause === v;
      case 'moved': return v ? ctx.moved.has(v) : ctx.moved.size > 0;
      case 'clauseref': case 'endsent': case 'endpara': case 'depstart': case 'depend': return ctx.flags.has(e.key);
      case 'words': case 'word': return ctx.words.some((w) => w.includes(v));
      case 'gloss': return ctx.glosses.some((w) => w.includes(v));
      case 'label': return norm(ctx.label) === v;
      default: {
        if (e.key in ctx.lists) { const have = norm(ctx.lists[e.key]); return v === '*' ? !!have : have === v; }
        return false;
      }
    }
  }
  /* The rule's answer for a row: {text, style} or null. */
  function applyRule(cases, ctx) {
    for (const c of cases) if (evalExpr(c.expr, ctx)) return { text: c.out, style: c.style };
    return null;
  }

  /* ------------------------------------------------------------------ the view */
  class ChartNote {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts || {};
      this.st = parse('');
      this.obj = null;
      this.lists = {};
      this.ruleCache = new Map();
    }
    load(body) { this.st = parse(body); this.ruleCache = new Map(); this.render(); return this; }
    markdown() { return serialize(this.st); }
    changed() { if (this.opts.onChange) this.opts.onChange(this.markdown()); }
    guid() { return this.st.spec ? this.st.spec.guid : (this.opts.chartGuid ? this.opts.chartGuid() : ''); }
    /* What the other exports read: the view as one block (the custom columns are not exported yet). */
    /* What the exporter sees (Seth, 2026-10-18: "pretty exports for chart-type notes"): the view
     * embed with the custom columns and the rule / marker row styles attached (`extras`, read by
     * export.js chartBlock), then the note's own text as ordinary markdown blocks. */
    asEditor() {
      const blocks = [];
      if (this.st.view) blocks.push({ type: 'flex', src: this.st.view, extras: this.exportExtras() });
      if (this.st.other && FS.markdown && FS.markdown.splitBlocks) for (const b of FS.markdown.splitBlocks(this.st.other)) blocks.push(b);
      return { blocks, flextextItems: () => [] };
    }
    exportExtras() {
      const self = this;
      const ruleAnswer = (col, row, chart) => { const r = self.cases(col); if (r.error) return null; return applyRule(r.cases, rowCtx(row, chart, self.st.values, self.st.columns)); };
      return {
        cols: this.st.columns.map((c) => ({ name: c.name, kind: c.kind })),
        cell(i, row, chart) {
          const col = self.st.columns[i];
          if (!col) return { text: '' };
          if (col.kind !== 'rule') return { text: self.value(row, col) };
          const ans = ruleAnswer(col, row, chart);
          if (!ans) return { text: '' };
          return Object.assign({ text: ans.text }, ans.style && ans.style.scope === 'cell' ? ans.style : {});
        },
        rowStyle(row, chart) {
          const st = {};
          for (const col of self.st.columns) { if (col.kind !== 'rule') continue; const ans = ruleAnswer(col, row, chart); if (ans && ans.style && ans.style.scope === 'row') Object.assign(st, ans.style); }
          return st;
        },
      };
    }
    cases(col) {
      if (!this.ruleCache.has(col)) { try { this.ruleCache.set(col, { cases: parseRule(col.settings) }); } catch (e) { this.ruleCache.set(col, { error: e.message }); } }
      return this.ruleCache.get(col);
    }
    async refreshLists() { try { this.lists = (await FS.api.chart_lists()) || {}; } catch (e) { this.lists = {}; } }

    async render() {
      const root = this.root;
      root.innerHTML = '';
      if (!this.st.spec) {
        const g = this.guid();
        if (!g) { root.appendChild(el('div', { class: 'muted' }, 'This chart note names no chart.')); return; }
        this.st.spec = R.parse('{{flex:chart ' + g + '}}');
        this.st.view = R.serialize(this.st.spec);
      }
      await this.refreshLists();
      const head = el('div', { class: 'coll-head cn-head' });
      this.headEl = head;
      root.appendChild(head);
      const host = el('div', { class: 'cn-body' });
      root.appendChild(host);
      this.host = host;
      this.drawHead();
      this.drawChart();
    }
    drawHead() {
      const head = this.headEl;
      head.innerHTML = '';
      const obj = this.obj;
      head.append(
        el('span', { class: 'kind-badge', title: 'A chart note: one FieldWorks text chart with your columns and styles' }, 'Chart'),
        el('b', {}, obj ? (obj.name || 'Chart') + ' · ' + (obj.title || '') : 'Text chart'),
        obj ? el('span', { class: 'muted small' }, (obj.rowCount || 0) + ' rows') : null,
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn small', title: 'Reload the chart from FieldWorks', onclick: () => { FS.interlinear.invalidate('chart', this.guid()); this.drawChart(true); } }, '↻ Refresh'),
        el('button', { class: 'btn small', 'data-test': 'cn-add-col', title: 'A column of your own: a choice list, free notes, or a rule computed from the markers and columns of each row', onclick: () => this.columnDialog(null) }, '+ Custom column…'),
        el('button', { class: 'btn small', title: 'The choice lists of this notebook (shared by every chart note)', onclick: () => this.listsDialog() }, 'Lists…'),
        obj && FS.chart.pivotDialog ? el('button', { class: 'btn small', 'data-test': 'cn-pivot', title: 'Counts of rows by marker and by column', onclick: () => FS.chart.pivotDialog(obj, this.st.spec) }, 'Pivot…') : null);
    }
    drawChart(refresh) {
      const host = this.host;
      const spec = this.st.spec;
      const self = this;
      const opts = {
        editable: true, keepView: !refresh, layout: false, collection: true,
        onSpecChange: (s) => { self.st.spec = s; self.st.view = R.serialize(s); self.changed(); self.drawChart(); },
        extraCols: this.extraCols(),
        rowDecor: (row) => self.rowDecor(row),
        onObject: (obj) => { self.obj = obj; self.drawHead(); },
      };
      FS.interlinear.render(host, spec, opts);
    }
    /* The custom columns as the chart renderer draws them. */
    extraCols() {
      const self = this;
      return this.st.columns.map((col, ci) => ({
        key: 'x' + ci,
        name: col.name,
        kind: col.kind,
        head: () => {
          const th = el('span', { class: 'xhead' }, el('span', { class: 'xname' }, col.name), el('span', { class: 'xkind muted' }, ' ' + (KINDS[col.kind] || col.kind).toLowerCase()));
          th.appendChild(el('button', { class: 'lnk xmenu', title: 'This column: rename, settings, move, remove', onclick: (e) => { e.stopPropagation(); self.columnMenu(e.currentTarget, ci); } }, '⋯'));
          if (col.kind === 'rule' && self.cases(col).error) th.appendChild(el('span', { class: 'xerr', title: self.cases(col).error }, ' ⚠'));
          return th;
        },
        cell: (row, chart) => self.cell(col, ci, row, chart),
      }));
    }
    value(row, col) { const v = this.st.values.get(anchorOf(row.guid)); return v ? (v[col.name] || '') : ''; }
    setValue(row, col, value) {
      const k = anchorOf(row.guid);
      const v = Object.assign({}, this.st.values.get(k) || {});
      if (value) v[col.name] = value; else delete v[col.name];
      if (Object.keys(v).length) this.st.values.set(k, v); else this.st.values.delete(k);
      this.st.labels.set(k, row.label || '');
      this.changed();
    }
    cell(col, ci, row, chart) {
      const self = this;
      if (col.kind === 'rule') {
        const r = this.cases(col);
        if (r.error) return el('span', { class: 'xerr small', title: r.error }, '⚠');
        const ans = applyRule(r.cases, rowCtx(row, chart, this.st.values, this.st.columns));
        const node = el('span', { class: 'xrule', dataset: { col: col.name } }, ans ? ans.text : '');
        if (ans && ans.style.scope === 'cell') styleNode(node, ans.style);
        return node;
      }
      const cur = this.value(row, col);
      const node = el('div', { class: 'xval ' + col.kind + (cur ? '' : ' empty'), tabindex: 0, title: col.kind === 'list' ? 'Click to choose' : 'Click to type', dataset: { col: col.name } }, cur || (col.kind === 'list' ? '—' : ''));
      const edit = () => {
        if (col.kind === 'list') {
          const list = this.lists[col.settings] || { options: [], open: true };
          const sel = el('select', { class: 'xsel' });
          sel.appendChild(el('option', { value: '' }, '—'));
          const opts = list.options.slice();
          if (cur && !opts.includes(cur)) opts.push(cur);
          for (const o of opts) sel.appendChild(el('option', { value: o, selected: o === cur }, o));
          if (list.open !== false) sel.appendChild(el('option', { value: '\u0000new' }, '+ Add an option…'));
          const done = async () => {
            let v = sel.value;
            if (v === '\u0000new') {
              v = (prompt('New option for the list “' + col.settings + '”', '') || '').trim();
              if (v && !list.options.includes(v)) { try { this.lists = await FS.api.set_chart_list(col.settings, list.options.concat([v])); } catch (e) { FS.toast(e.message, 'error'); } }
              if (!v) { node.replaceWith(self.cell(col, ci, row, chart)); return; }
            }
            self.setValue(row, col, v);
            sel.replaceWith(self.cell(col, ci, row, chart));
          };
          sel.addEventListener('change', done);
          sel.addEventListener('blur', () => { if (sel.isConnected) sel.replaceWith(self.cell(col, ci, row, chart)); });
          sel.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); sel.replaceWith(self.cell(col, ci, row, chart)); } });
          node.replaceWith(sel);
          sel.focus();
          return;
        }
        const ta = el('textarea', { class: 'xedit', rows: 1, 'data-test': 'xedit' });
        ta.value = cur;
        const finish = (keep) => { if (!ta.isConnected) return; if (keep) self.setValue(row, col, ta.value.trim()); ta.replaceWith(self.cell(col, ci, row, chart)); };
        ta.addEventListener('blur', () => finish(true));
        ta.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); finish(true); } else if (e.key === 'Escape') finish(false); });
        ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; });
        node.replaceWith(ta);
        ta.focus();
        ta.style.height = ta.scrollHeight + 'px';
      };
      node.addEventListener('click', (e) => { e.stopPropagation(); edit(); });
      node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); edit(); } });
      return node;
    }
    /* A rule case with `row` styles the whole row. */
    rowDecor(row) {
      const out = { style: {}, classes: [] };
      if (!this.obj) return out;
      for (const col of this.st.columns) {
        if (col.kind !== 'rule') continue;
        const r = this.cases(col);
        if (r.error) continue;
        const ans = applyRule(r.cases, rowCtx(row, this.obj, this.st.values, this.st.columns));
        if (ans && ans.style.scope === 'row') Object.assign(out.style, styleOf(ans.style));
      }
      return out;
    }

    /* -- the columns' dialogs -------------------------------------------------------- */
    columnMenu(anchor, ci) {
      const self = this;
      FS.popover(anchor, (pop, close) => {
        const col = self.st.columns[ci];
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, col.name), el('span', { class: 'muted small' }, ' ' + (KINDS[col.kind] || col.kind))));
        pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); self.columnDialog(ci); } }, 'Rename / settings…'));
        pop.appendChild(el('button', { class: 'menu-item', disabled: ci === 0, onclick: () => { close(); self.st.columns.splice(ci - 1, 0, self.st.columns.splice(ci, 1)[0]); self.changed(); self.drawChart(); } }, '← Move left'));
        pop.appendChild(el('button', { class: 'menu-item', disabled: ci === self.st.columns.length - 1, onclick: () => { close(); self.st.columns.splice(ci + 1, 0, self.st.columns.splice(ci, 1)[0]); self.changed(); self.drawChart(); } }, 'Move right →'));
        pop.appendChild(el('hr'));
        pop.appendChild(el('button', { class: 'menu-item danger', onclick: async () => { close(); if (await FS.confirmAt(anchor, 'Remove the column “' + col.name + '”' + (col.kind !== 'rule' ? ' and its values' : '') + '? (Undo in the message brings it back.)', 'Remove')) self.removeColumn(ci); } }, 'Remove this column…'));
      });
    }
    removeColumn(ci) {
      const col = this.st.columns[ci];
      const saved = { col, values: new Map([...this.st.values].map(([k, v]) => [k, Object.assign({}, v)])) };
      this.st.columns.splice(ci, 1);
      for (const [k, v] of this.st.values) { delete v[col.name]; if (!Object.keys(v).length) this.st.values.delete(k); }
      this.changed(); this.drawChart();
      FS.toast('Column “' + col.name + '” removed.', 'ok', { action: { label: 'Undo', fn: () => { this.st.columns.splice(ci, 0, saved.col); this.st.values = saved.values; this.changed(); this.drawChart(); } } });
    }
    columnDialog(ci) {
      const self = this;
      const col = ci == null ? { name: '', kind: 'notes', settings: '' } : Object.assign({}, this.st.columns[ci]);
      const m = FS.modal({ title: ci == null ? 'New custom column' : 'Column “' + col.name + '”', class: 'cn-col-dlg' });
      const name = el('input', { type: 'text', value: col.name, placeholder: 'Column heading', 'data-test': 'cn-col-name', style: { width: '260px' } });
      const kindSel = el('select', { 'data-test': 'cn-col-kind' });
      for (const [k, lab] of Object.entries(KINDS)) kindSel.appendChild(el('option', { value: k, selected: k === col.kind }, lab));
      const body = el('div');
      const settingsBox = el('div', { class: 'cn-settings' });
      const err = el('div', { class: 'cn-err', style: { color: 'var(--danger)', minHeight: '1.2em' } });
      let listSel = null, listNew = null, listOpts = null, listOpen = null, ruleTa = null, preview = null;
      const drawSettings = () => {
        settingsBox.innerHTML = '';
        const k = kindSel.value;
        if (k === 'notes') settingsBox.appendChild(el('p', { class: 'muted small' }, 'Free text you type in each row. The notes are saved in the note and found by search.'));
        if (k === 'list') {
          const names = Object.keys(self.lists);
          listSel = el('select', { 'data-test': 'cn-list-sel' });
          for (const n of names) listSel.appendChild(el('option', { value: n, selected: n === col.settings }, n + ' (' + (self.lists[n].options || []).length + ')'));
          listSel.appendChild(el('option', { value: '\u0000new', selected: !names.includes(col.settings) }, '+ New list…'));
          listNew = el('div', { class: 'cn-newlist' });
          const nameIn = el('input', { type: 'text', placeholder: 'Name of the list (e.g. Information status)', 'data-test': 'cn-list-name', style: { width: '260px' }, value: names.includes(col.settings) ? '' : col.settings });
          listOpts = el('textarea', { rows: 4, placeholder: 'One option per line', 'data-test': 'cn-list-opts', style: { width: '260px' } });
          listOpen = el('input', { type: 'checkbox', checked: true });
          listNew.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Name'), nameIn), el('div', { class: 'row', style: { alignItems: 'flex-start' } }, el('span', { class: 'lbl' }, 'Options'), listOpts), el('label', { class: 'row' }, listOpen, ' New options may be typed in as you go'));
          listNew.nameIn = nameIn;
          const show = () => { listNew.hidden = listSel.value !== '\u0000new'; };
          listSel.addEventListener('change', show);
          show();
          settingsBox.append(el('p', { class: 'muted small' }, 'A choice list is shared by the whole notebook: every chart note can use it, and an option added here is offered everywhere.'), el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'List'), listSel), listNew);
        }
        if (k === 'rule') {
          ruleTa = el('textarea', { rows: 3, 'data-test': 'cn-rule', style: { width: '100%', fontFamily: 'var(--mono)' }, placeholder: 'marker:Topic → Top [row hl#fde68a]; col:Subject and not marker:Topic → S' });
          ruleTa.value = col.settings;
          preview = el('div', { class: 'muted small cn-preview' });
          const test = () => {
            try {
              const cases = parseRule(ruleTa.value);
              if (!self.obj) { preview.textContent = cases.length + ' case' + (cases.length === 1 ? '' : 's') + '.'; err.textContent = ''; return; }
              const counts = cases.map(() => 0);
              let none = 0;
              for (const row of self.obj.rows || []) { const ctx = rowCtx(row, self.obj, self.st.values, self.st.columns); const i = cases.findIndex((c) => evalExpr(c.expr, ctx)); if (i >= 0) counts[i]++; else none++; }
              preview.textContent = cases.map((c, i) => '“' + (c.out || '') + '”: ' + counts[i] + ' row' + (counts[i] === 1 ? '' : 's')).join(' · ') + (none ? ' · no case: ' + none : '');
              err.textContent = '';
            } catch (e) { err.textContent = e.message; preview.textContent = ''; }
          };
          ruleTa.addEventListener('input', FS.debounce(test, 250));
          settingsBox.append(
            el('p', { class: 'muted small' }, 'Cases separated by “;”, each  condition → text [styles]. The first case that fits a row gives the cell its text. Terms: marker:Name · col:Name · clause:dependent|speech|song · moved · moved:preposed · clauseref · endsent · endpara · words:"ka-" · gloss:"sleep" · label:"2a" · a list column as Status:new — with and, or, not, ( ). Styles: row or cell, hl, hl#rrggbb, b, i, u, c#rrggbb.'),
            ruleTa, preview);
          test();
        }
      };
      kindSel.addEventListener('change', drawSettings);
      drawSettings();
      body.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Heading'), name), el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Kind'), kindSel), settingsBox, err);
      const save = async () => {
        const nm = name.value.trim();
        if (!nm) { err.textContent = 'The column needs a heading.'; return; }
        if (self.st.columns.some((c, i) => i !== ci && c.name.toLowerCase() === nm.toLowerCase())) { err.textContent = 'There is already a column called that.'; return; }
        const kind = kindSel.value;
        let settings = '';
        if (kind === 'list') {
          if (listSel.value === '\u0000new') {
            const ln = listNew.nameIn.value.trim();
            if (!ln) { err.textContent = 'The new list needs a name.'; return; }
            const options = listOpts.value.split('\n').map((x) => x.trim()).filter(Boolean);
            try { self.lists = await FS.api.set_chart_list(ln, options, listOpen.checked); } catch (e) { err.textContent = e.message; return; }
            settings = ln;
          } else settings = listSel.value;
        } else if (kind === 'rule') {
          try { parseRule(ruleTa.value); } catch (e) { err.textContent = e.message; return; }
          settings = ruleTa.value.trim().replace(/\s*\n\s*/g, ' ');
        }
        const next = { name: nm, kind, settings };
        if (ci == null) self.st.columns.push(next);
        else {
          const old = self.st.columns[ci];
          if (old.name !== nm) for (const v of self.st.values.values()) { if (v[old.name] != null) { v[nm] = v[old.name]; delete v[old.name]; } }
          self.st.columns[ci] = next;
        }
        self.ruleCache = new Map();
        self.changed();
        m.close();
        self.drawChart();
      };
      body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), el('button', { class: 'btn primary', 'data-test': 'cn-col-save', onclick: save }, ci == null ? 'Add column' : 'Save')));
      m.body.appendChild(body);
      name.focus();
    }
    listsDialog() {
      const self = this;
      const m = FS.modal({ title: 'Choice lists of this notebook' });
      const box = el('div');
      const draw = async () => {
        await self.refreshLists();
        box.innerHTML = '';
        const names = Object.keys(self.lists);
        if (!names.length) box.appendChild(el('p', { class: 'muted' }, 'No lists yet. A list is made when a chart note adds a choice-list column.'));
        for (const n of names) {
          const l = self.lists[n];
          const ta = el('textarea', { rows: Math.max(2, Math.min(8, (l.options || []).length + 1)), style: { width: '280px' } });
          ta.value = (l.options || []).join('\n');
          const open = el('input', { type: 'checkbox', checked: l.open !== false });
          const saveBtn = el('button', { class: 'btn small', onclick: async () => { try { self.lists = await FS.api.set_chart_list(n, ta.value.split('\n').map((x) => x.trim()).filter(Boolean), open.checked); FS.toast('List saved', 'ok'); self.drawChart(); } catch (e) { FS.toast(e.message, 'error'); } } }, 'Save');
          const del = el('button', { class: 'btn small danger', onclick: async () => { if (await FS.confirmAt(del, 'Delete the list “' + n + '”? Columns using it keep their values but offer no options.', 'Delete')) { try { self.lists = await FS.api.set_chart_list(n, null, null); } catch (e) { FS.toast(e.message, 'error'); } draw(); } } }, 'Delete');
          box.appendChild(el('div', { class: 'cn-list' }, el('div', { class: 'row' }, el('b', {}, n), el('span', { class: 'spacer' }), el('label', { class: 'small' }, open, ' open'), saveBtn, del), ta));
        }
      };
      draw();
      m.body.appendChild(box);
    }
  }
  const styleOf = (st) => { const s = {}; if (st.hl) s.background = st.hl; if (st.b) s.fontWeight = '700'; if (st.i) s.fontStyle = 'italic'; if (st.u) s.textDecoration = 'underline'; if (st.c) s.color = st.c; return s; };
  const styleNode = (node, st) => Object.assign(node.style, styleOf(st));

  FS.ChartNote = ChartNote;
  FS.chartnote = { parse, serialize, parseRule, evalExpr, applyRule, rowCtx, anchorOf, KINDS };
})();
