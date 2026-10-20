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
  // `check` (Seth, 2026-10-20: "just a checkbox (ticked or not)"): stored as `x` in the Values table when ticked
  const KINDS = { list: 'Choice list', notes: 'Notes', check: 'Checkbox', rule: 'Rule' };
  const isTicked = (v) => !!String(v || '').trim();
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
            if (name && KINDS[kind]) {
              // a 4th column "Place" (since 2026-10-18): `left` / `right`, `frozen` — older files have three
              const place = unCell(r[3] || '').toLowerCase();
              st.columns.push({ name, kind, settings: unCell(r[2] || ''), side: /\bleft\b/.test(place) ? 'left' : 'right', frozen: /\bfrozen\b/.test(place) });
            }
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
      const row = (cells) => '|' + cells.map((c) => (c ? ' ' + c + ' ' : ' ')).join('|') + '|';
      const placed = st.columns.some((c) => c.side === 'left' || c.frozen);   // the Place column only when some column needs it: older files stay as they were
      const place = (c) => [c.side === 'left' ? 'left' : '', c.frozen ? 'frozen' : ''].filter(Boolean).join(' ');
      out.push('', H_COLS, '', placed ? '| Column | Kind | Settings | Place |' : '| Column | Kind | Settings |', placed ? '|---|---|---|---|' : '|---|---|---|');
      for (const c of st.columns) out.push(row([cellText(c.name), c.kind, cellText(c.settings || '')].concat(placed ? [place(c)] : [])));
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
    // a `key:/pattern/flags` value is one token, whatever the pattern holds (Seth, 2026-10-19: regex)
    const re = /\s*(\(|\)|→|->|;|\[|\]|[^\s()\[\];"\/]+:\/(?:\\.|[^\/\\])*\/[a-z]*|[^\s()\[\];"]+(?:"[^"]*")?|"[^"]*")/g;
    let m;
    while ((m = re.exec(src))) out.push(m[1] === '->' ? '→' : m[1]);
    return out;
  }
  const STYLE_TOKEN = /^(row|cell|b|i|u|hl|hl#[0-9a-f]{6}|c#[0-9a-f]{6}|chip|join)$/i;
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
        if (t === ']') throw new Error('A “]” too many in “' + part.trim() + '”');
        const i = t.indexOf(':');
        let key = (i >= 0 ? t.slice(0, i) : t).toLowerCase();
        let val = i >= 0 ? t.slice(i + 1) : '';
        // a word field in one writing system: txt@en, gls@fr (Seth, 2026-10-19: "any interlinear word field/writing system")
        let ws = '';
        const at = key.indexOf('@');
        if (at > 0) { ws = key.slice(at + 1); key = key.slice(0, at); }
        let rx = null;
        const rm = /^\/((?:\\.|[^\/\\])*)\/([a-z]*)$/.exec(val);
        if (rm) {
          try { rx = new RegExp(rm[1], rm[2].replace(/[^imsu]/g, '')); } catch (e2) { throw new Error('Bad pattern ' + val + ': ' + e2.message); }
          val = '';
        } else if (/^".*"$/.test(val)) val = val.slice(1, -1);
        const term = { op: 'term', key, val, raw: t, ws, rx };
        // col:Subject[ … ]: the inner condition is tested on THAT column's cells only (a combination to query)
        if ((key === 'col' || key === 'column') && peek() === '[') {
          next();
          const a = parseOr();
          if (next() !== ']') throw new Error('A “]” is missing after ' + t + ' in “' + part.trim() + '”');
          return { op: 'in', col: term, a };
        }
        return term;
      };
      const expr = exprToks.length ? parseOr() : { op: 'term', key: 'any', val: '' };
      if (p < exprToks.length) throw new Error('Unexpected “' + exprToks[p] + '” in “' + part.trim() + '”');
      // the output: text (quoted or bare words) up to the styles in brackets
      let out = '';
      const style = { scope: 'cell' };
      const chips = [];                       // @markers[:selector]: the row's markers drawn as chips (Seth, 2026-10-19)
      let k = 0;
      while (k < rest.length && rest[k] !== '[') {
        const t = rest[k++];
        const cm = /^@markers?(?::(.*))?$/i.exec(t);
        if (cm) {
          const sel = cm[1] == null ? '' : cm[1];
          const rm = /^\/((?:\\.|[^\/\\])*)\/([a-z]*)$/.exec(sel);
          let rx = null;
          if (rm) { try { rx = new RegExp(rm[1], rm[2].replace(/[^imsu]/g, '')); } catch (e2) { throw new Error('Bad pattern ' + sel + ': ' + e2.message); } }
          chips.push({ sel: rx ? '' : sel.replace(/^"(.*)"$/, '$1'), rx, raw: t });
          continue;
        }
        out += (out ? ' ' : '') + (/^".*"$/.test(t) ? t.slice(1, -1) : t);
      }
      if (rest[k] === '[') {
        k++;
        while (k < rest.length && rest[k] !== ']') {
          const t = rest[k++];
          if (!STYLE_TOKEN.test(t)) throw new Error('Unknown style “' + t + '” (row, cell, hl, hl#rrggbb, b, i, u, c#rrggbb, chip, join)');
          const tl = t.toLowerCase();
          if (tl === 'row' || tl === 'cell') style.scope = tl;
          else if (tl.startsWith('hl')) style.hl = tl.length > 2 ? tl.slice(2) : '#fff2a8';
          else if (tl.startsWith('c#')) style.c = tl.slice(1);
          else style[tl] = true;
        }
      }
      cases.push({ expr, out: out || (arrow >= 0 || chips.length ? '' : '✓'), chips, style, src: part.trim() });
    }
    return cases;
  }
  const norm = (s) => (FS.normalize ? FS.normalize(String(s || ''), true) : String(s || '').toLowerCase());
  /* What a rule sees of one row. */
  function rowCtx(row, chart, values, columns, opts) {
    const cols = (chart.template && chart.template.columns) || [];
    const byN = new Map(cols.map((c) => [c.n, c]));
    // a MERGED cell counts for both columns unless the chart says owner only (Seth, 2026-10-19: "it could be either")
    const ownerOnly = !!(opts && opts.mergeOwner);
    const colsOf = (c, col) => { if (ownerOnly || !FS.chart || !FS.chart.mergedNeighbour) return [col]; const nb = FS.chart.mergedNeighbour(c, cols); return nb ? [col, nb] : [col]; };
    const keysOf = (cc) => { const keys = new Set(); for (const col of cc) for (const k of [col.name, col.abbr, 'c' + col.n, (col.path || []).concat([col.name]).join('/'), col.guid].concat(col.path || [])) if (k) keys.add(norm(k)); return keys; };
    const rawOf = (cc) => cc.flatMap((col) => [col.name, col.abbr, (col.path || []).concat([col.name]).join('/')].concat(col.path || [])).filter(Boolean);
    const ctx = { markers: new Set(), cols: new Set(), clause: row.clause || 'normal', moved: new Set(), flags: new Set(), wl: [], cells: [], free: [], label: row.label || '', lists: {}, markerItems: [] };
    const segs = new Set();
    for (const c of row.cells || []) {
      const col = byN.get(c.colN);
      if (c.kind === 'words' && col) {
        const cc = colsOf(c, col);
        const keys = keysOf(cc);
        for (const k of keys) ctx.cols.add(k);
        const words = (c.words || []).filter((w) => !w.punct);
        ctx.wl.push(...words);
        ctx.cells.push({ keys, words, col, raw: rawOf(cc) });
        for (let n = c.seg || 0; n && n <= (c.segTo || c.seg); n++) segs.add(n);
      } else if (c.kind === 'tag' && c.tag) {
        ctx.markers.add(norm(c.tag.name)); ctx.markers.add(norm(c.tag.abbr)); for (const p of c.tag.path || []) ctx.markers.add(norm(p)); ctx.markerItems.push(c.tag);
        // a marker cell is a cell too, so col:X[marker:Y] finds a marker IN that column
        if (col) { const cc = colsOf(c, col); ctx.cells.push({ keys: keysOf(cc), words: [], tags: [c.tag], col, raw: rawOf(cc) }); }
      }
      else if (c.kind === 'moved') ctx.moved.add(c.preposed ? 'preposed' : 'postposed');
      else if (c.kind === 'clause') ctx.flags.add('clauseref');
    }
    if (row.endSent) ctx.flags.add('endsent');
    if (row.endPara) ctx.flags.add('endpara');
    if (row.depStart) ctx.flags.add('depstart');
    if (row.depEnd) ctx.flags.add('depend');
    for (const s of chart.segments || []) if (segs.has(s.n)) ctx.free.push(s);
    const v = (values && values.get(anchorOf(row.guid))) || {};
    for (const c of columns || []) if (c.kind === 'list' || c.kind === 'notes' || c.kind === 'check') ctx.lists[norm(c.name)] = c.kind === 'check' ? (isTicked(v[c.name]) ? 'x' : '') : (v[c.name] || '');
    return ctx;
  }
  /* The word fields a rule may test (Seth, 2026-10-19: "regex for text in a column on any interlinear
   * word field/writing system"): `txt` (the word and its morpheme forms — `words:` of old), `gls`
   * (the word gloss and the morpheme glosses — `gloss:`), `pos`, `form` (morpheme forms), `mgls`,
   * `cf` (lexeme / citation forms), `lex` (any form), `free` (the free translation of the line the
   * words come from). `field@ws` reads that writing system's alternative (`txtAlts` & co., present
   * when the chart carries them; the chart reader hands out the default writing systems only
   * until it is asked for more). */
  const FIELDS = { txt: 'txt', word: 'txt', words: 'txt', gls: 'gls', gloss: 'gls', pos: 'pos', form: 'form', morph: 'form', mgls: 'mgls', cf: 'cf', lex: 'lex', free: 'free' };
  const altOf = (o, base, ws) => { if (!o) return []; if (ws) { const a = o[base + 'Alts']; return a && a[ws] != null && a[ws] !== '' ? [a[ws]] : []; } return o[base] != null && o[base] !== '' ? [o[base]] : []; };
  function fieldValues(w, f, ws) {
    const ms = w.morphs || [];
    switch (f) {
      case 'txt': return altOf(w, 'txt', ws).concat(ms.flatMap((m) => altOf(m, 'form', ws)));
      case 'gls': return altOf(w, 'gls', ws).concat(ms.flatMap((m) => altOf(m, 'gls', ws)));
      case 'pos': return altOf(w, 'pos', ws).concat(ms.flatMap((m) => altOf(m, 'msa', ws)));
      case 'form': return ms.flatMap((m) => altOf(m, 'form', ws));
      case 'mgls': return ms.flatMap((m) => altOf(m, 'gls', ws));
      case 'cf': return ms.flatMap((m) => altOf(m, 'cf', ws));
      case 'lex': return altOf(w, 'txt', ws).concat(ms.flatMap((m) => altOf(m, 'form', ws).concat(altOf(m, 'cf', ws))));
      default: return [];
    }
  }
  /* A value against a term: its regex (on the text as written), or the normalised substring; `exact` = the whole value. */
  const matchVal = (s, e, exact) => { const str = String(s == null ? '' : s); if (e.rx) return e.rx.test(str.normalize ? str.normalize('NFC') : str); const v = norm(e.val); return exact ? norm(str) === v : str !== '' && v !== '' && norm(str).includes(v); };
  const colMatch = (cell, e) => e.rx ? (cell.raw || []).some((k) => e.rx.test(k)) : (norm(e.val) === '*' || cell.keys.has(norm(e.val)));
  function evalExpr(e, ctx) {
    switch (e.op) {
      case 'or': return evalExpr(e.a, ctx) || evalExpr(e.b, ctx);
      case 'and': return evalExpr(e.a, ctx) && evalExpr(e.b, ctx);
      case 'not': return !evalExpr(e.a, ctx);
      case 'in': {                                 // col:X[ … ]: the words of that column's cells only
        const cells = ctx.cells.filter((c) => colMatch(c, e.col));
        if (!cells.length) return false;
        const items = cells.flatMap((c) => c.tags || []);
        const names = new Set(items.flatMap((m) => [m.name, m.abbr].concat(m.path || []).filter(Boolean).map(norm)));
        return evalExpr(e.a, Object.assign({}, ctx, { cells, wl: cells.flatMap((c) => c.words), cols: new Set(cells.filter((c) => c.words.length).flatMap((c) => [...c.keys])), markerItems: items, markers: names }));
      }
      default: break;
    }
    const v = norm(e.val);
    if (FIELDS[e.key]) {
      const f = FIELDS[e.key];
      if (f === 'free') return ctx.free.some((s) => altOf(s, 'free', e.ws).some((t) => matchVal(t, e)));
      return ctx.wl.some((w) => fieldValues(w, f, e.ws).some((t) => matchVal(t, e, f === 'pos')));
    }
    switch (e.key) {
      case 'any': return true;
      case 'marker': return e.rx ? (ctx.markerItems || []).some((m) => [m.name, m.abbr].concat(m.path || []).some((x) => x && e.rx.test(x))) : v === '*' ? ctx.markers.size > 0 : ctx.markers.has(v);
      case 'col': case 'column': return e.rx ? ctx.cells.some((c) => colMatch(c, e)) : v === '*' ? ctx.cols.size > 0 : ctx.cols.has(v);
      case 'clause': return ctx.clause === v;
      case 'moved': return v ? ctx.moved.has(v) : ctx.moved.size > 0;
      case 'clauseref': case 'endsent': case 'endpara': case 'depstart': case 'depend': return ctx.flags.has(e.key);
      case 'label': return e.rx ? e.rx.test(ctx.label) : norm(ctx.label) === v;
      default: {
        if (e.key in ctx.lists) { const have = ctx.lists[e.key]; return e.rx ? e.rx.test(have) : v === '*' ? !!norm(have) : norm(have) === v; }
        return false;
      }
    }
  }

  /* ---------------------------------------------------------- the rule BUILDER (Seth, 2026-10-19:
   * "a UI for building formulas rather than just a query language"): a structured editor that
   * WRITES the rule text (the file keeps the language, so a rule is readable anywhere) and reads a
   * rule back when it is flat enough — each case a list of conditions joined by all / any, a
   * condition a term, "not" a term, or a term tested inside one column (`col:X[ … ]`). */
  const WHATS = [
    ['marker', 'Chart marker'], ['col', 'Column holds words'], ['clause', 'Clause type'], ['moved', 'Moved text'], ['flag', 'Row flag'],
    ['txt', 'Word (or morpheme form)'], ['gls', 'Gloss (word or morpheme)'], ['form', 'Morpheme form'], ['mgls', 'Morpheme gloss'],
    ['pos', 'Word category'], ['cf', 'Lexeme / citation form'], ['lex', 'Any form'], ['free', 'Free translation'], ['label', 'Row label'], ['list', 'A column of this note'],
  ];
  const TEXT_WHATS = ['txt', 'gls', 'form', 'mgls', 'pos', 'cf', 'lex', 'free'];
  const FLAGS = [['clauseref', 'has a clause marker [2a]'], ['endsent', 'ends a sentence'], ['endpara', 'ends a paragraph'], ['depstart', 'starts a dependent group'], ['depend', 'ends a dependent group']];
  const CLAUSES = ['normal', 'dependent', 'speech', 'song'];
  const qv = (v) => { v = String(v == null ? '' : v); return v === '' || /[\s()\[\];"]/.test(v) ? '"' + v.replace(/"/g, '') + '"' : v; };
  const rxText = (c) => '/' + String(c.val || '').replace(/\//g, '\\/') + '/' + (c.ci ? 'i' : '');
  /* One condition → its term text. */
  function condText(c) {
    let t;
    const anyOr = (key) => key + ':' + (c.how === 'any' ? '*' : c.how === 'regex' ? rxText(c) : qv(c.val));
    switch (c.what) {
      case 'marker': t = anyOr('marker'); break;
      case 'col': t = anyOr('col'); break;
      case 'clause': t = 'clause:' + (CLAUSES.includes(c.val) ? c.val : 'normal'); break;
      case 'moved': t = c.how === 'any' || !c.val ? 'moved' : 'moved:' + c.val; break;
      case 'flag': t = FLAGS.some((f) => f[0] === c.val) ? c.val : 'clauseref'; break;
      case 'label': t = 'label:' + (c.how === 'regex' ? rxText(c) : qv(c.val)); break;
      case 'list': t = qv(c.list || '').replace(/\s/g, '') + ':' + (c.how === 'any' ? '*' : c.how === 'regex' ? rxText(c) : qv(c.val)); break;
      default: t = c.what + (c.ws ? '@' + c.ws : '') + ':' + (c.how === 'regex' ? rxText(c) : qv(c.val));
    }
    if (c.incol && c.what !== 'col' && c.what !== 'marker' && c.what !== 'clause' && c.what !== 'moved' && c.what !== 'flag' && c.what !== 'label' && c.what !== 'list') t = 'col:' + qv(c.incol) + '[' + t + ']';
    return (c.neg ? 'not ' : '') + t;
  }
  function styleText(st) {
    const toks = [];
    if (st.scope === 'row') toks.push('row');
    if (st.chip) toks.push('chip');
    if (st.join) toks.push('join');
    if (st.hl) toks.push('hl' + (st.hl === '#fff2a8' ? '' : st.hl));
    for (const k of ['b', 'i', 'u']) if (st[k]) toks.push(k);
    if (st.c) toks.push('c' + st.c);
    return toks.length ? ' [' + toks.join(' ') + ']' : '';
  }
  /* The builder's cases → the rule text. */
  function casesText(cases) {
    return cases.map((k) => {
      const cond = k.conds.length ? k.conds.map(condText).join(k.join === 'or' ? ' or ' : ' and ') : 'any';
      const st = styleText(k.style || {});
      const chips = k.chips === 'all' ? ' @markers' : k.chips === 'some' ? ' @markers:' + (k.chipsHow === 'regex' ? rxText({ val: k.chipsVal, ci: k.chipsCi }) : qv(k.chipsVal || '*')) : '';
      return k.out || st || chips ? cond + ' →' + (k.out ? ' ' + qv(k.out) : '') + chips + st : cond;
    }).join('; ');
  }
  /* The rule text → the builder's cases, or null when the rule is more than the builder shows. */
  function casesFrom(text, listNames) {
    let parsed;
    try { parsed = parseRule(text); } catch (e) { return null; }
    const lists = new Set((listNames || []).map((n) => norm(n)));
    const condOf = (t, neg, incol) => {
      if (t.op !== 'term') return null;
      const c = { neg: !!neg, what: '', how: 'is', val: t.rx ? t.rx.source.replace(/\\\//g, '/') : t.val, ws: t.ws || '', incol: incol || '', ci: !!(t.rx && t.rx.flags.includes('i')) };
      if (t.rx) c.how = 'regex';
      if (t.key === 'marker' || t.key === 'col' || t.key === 'column') { c.what = t.key === 'marker' ? 'marker' : 'col'; if (!t.rx && t.val === '*') { c.how = 'any'; c.val = ''; } }
      else if (t.key === 'clause') c.what = 'clause';
      else if (t.key === 'moved') { c.what = 'moved'; c.how = t.val ? 'is' : 'any'; }
      else if (FLAGS.some((f) => f[0] === t.key)) { c.what = 'flag'; c.val = t.key; }
      else if (t.key === 'label') c.what = 'label';
      else if (FIELDS[t.key] && FIELDS[t.key] !== 'free' || t.key === 'free') { c.what = FIELDS[t.key]; if (!t.rx) c.how = c.what === 'pos' ? 'is' : 'contains'; }
      else if (lists.has(t.key)) { c.what = 'list'; c.list = (listNames || []).find((n) => norm(n) === t.key) || t.key; if (!t.rx && t.val === '*') { c.how = 'any'; c.val = ''; } }
      else if (t.key === 'any') return 'any';
      else return null;
      if (c.incol && !TEXT_WHATS.includes(c.what)) return null;
      return c;
    };
    const atom = (e) => {
      if (e.op === 'not') { const inner = atom(e.a); return inner && inner !== 'any' ? Object.assign(inner, { neg: !inner.neg }) : null; }
      if (e.op === 'in') { if (e.col.rx || e.a.op === 'not' && e.a.a.op !== 'term') return null; const neg = e.a.op === 'not'; return condOf(neg ? e.a.a : e.a, neg, e.col.val); }
      return condOf(e, false, '');
    };
    const out = [];
    for (const k of parsed) {
      const conds = [];
      let join = 'and';
      const walk = (e, top) => {
        if (e.op === 'and' || e.op === 'or') { if (top) join = e.op; else if (join !== e.op) return false; return walk(e.a, false) && walk(e.b, false); }
        const c = atom(e);
        if (!c) return false;
        if (c !== 'any') conds.push(c);
        return true;
      };
      if (!walk(k.expr, true)) return null;
      const ch = (k.chips || [])[0];
      if ((k.chips || []).length > 1) return null;
      out.push({ conds, join, out: k.out || '', style: Object.assign({ scope: 'cell' }, k.style || {}),
        chips: !ch ? '' : (!ch.sel && !ch.rx) ? 'all' : 'some', chipsHow: ch && ch.rx ? 'regex' : 'is', chipsVal: ch ? (ch.rx ? ch.rx.source.replace(/\\\//g, '/') : ch.sel) : '', chipsCi: !!(ch && ch.rx && ch.rx.flags.includes('i')) });
    }
    return out;
  }
  /* The writing systems the chart's words carry alternatives in (txtAlts & co.). */
  function chartWritingSystems(chart) {
    const ws = new Set();
    const take = (o) => { for (const k of Object.keys(o || {})) if (k.endsWith('Alts') && o[k] && typeof o[k] === 'object') for (const t of Object.keys(o[k])) ws.add(t); };
    for (const r of (chart && chart.rows) || []) for (const c of r.cells || []) for (const w of c.words || []) { take(w); for (const m of w.morphs || []) take(m); }
    for (const s of (chart && chart.segments) || []) take(s);
    return [...ws];
  }
  /* Draw the builder into `host`. opts: {chart, columns (the note's custom columns), text(), setText(t), onChange()}. */
  function ruleBuilder(host, opts) {
    const chart = opts.chart || {};
    const listNames = (opts.columns || []).filter((c) => c.kind === 'list' || c.kind === 'notes' || c.kind === 'check').map((c) => c.name);
    const markerNames = [...new Set(((chart.markers || []).map((m) => m.name)).concat((chart.rows || []).flatMap((r) => (r.cells || []).filter((c) => c.kind === 'tag' && c.tag).map((c) => c.tag.name))))].filter(Boolean);
    const tcols = ((chart.template && chart.template.columns) || []);
    const colNames = tcols.map((c) => { const dup = tcols.filter((x) => x.name === c.name).length > 1; return { value: dup ? (c.path || []).concat([c.name]).join('/') : c.name, label: (c.path || []).concat([c.name]).join(' › ') }; });
    const wss = chartWritingSystems(chart);
    let cases = casesFrom(opts.text(), listNames);
    const unreadable = cases == null && !!String(opts.text() || '').trim();
    if (!cases || !cases.length) cases = [{ conds: [], join: 'and', out: '', style: { scope: 'cell' } }];
    const write = () => { opts.setText(casesText(cases)); if (opts.onChange) opts.onChange(); };
    const sel = (options, value, onchange, attrs) => { const s = el('select', Object.assign({}, attrs || {})); for (const o of options) { const [v, l] = Array.isArray(o) ? o : [o.value, o.label]; s.appendChild(el('option', { value: v, selected: v === value }, l)); } s.addEventListener('change', () => onchange(s.value)); return s; };
    const draw = () => {
      host.innerHTML = '';
      if (unreadable) host.appendChild(el('p', { class: 'small muted', 'data-test': 'rb-unreadable' }, 'The rule as written says more than the builder can show. Building here replaces it; the Text tab keeps it as it is.'));
      cases.forEach((k, ki) => {
        const box = el('div', { class: 'cn-case', 'data-test': 'rb-case' });
        const head = el('div', { class: 'row cn-case-head' }, el('b', {}, 'Case ' + (ki + 1)), el('span', { class: 'spacer' }),
          ki > 0 ? el('button', { class: 'icon-btn', title: 'Move up (an earlier case wins)', onclick: () => { cases.splice(ki, 1); cases.splice(ki - 1, 0, k); write(); draw(); } }, '↑') : null,
          el('button', { class: 'icon-btn danger', title: 'Remove this case', 'data-test': 'rb-case-remove', onclick: () => { cases.splice(ki, 1); if (!cases.length) cases.push({ conds: [], join: 'and', out: '', style: { scope: 'cell' } }); write(); draw(); } }, '✕'));
        box.appendChild(head);
        const when = el('div', { class: 'row' }, el('span', {}, 'When '), sel([['and', 'all'], ['or', 'any']], k.join, (v) => { k.join = v; write(); }, { 'data-test': 'rb-join' }), el('span', {}, ' of these hold' + (k.conds.length ? ':' : ' (none: every row)')));
        box.appendChild(when);
        k.conds.forEach((c, ci) => {
          const row = el('div', { class: 'cn-cond', 'data-test': 'rb-cond' });
          const neg = el('label', { class: 'small', title: 'The opposite' }, el('input', { type: 'checkbox', checked: !!c.neg, onchange: (e) => { c.neg = e.target.checked; write(); } }), ' not');
          row.appendChild(neg);
          row.appendChild(sel(WHATS, c.what || 'marker', (v) => { c.what = v; c.how = v === 'moved' ? 'any' : TEXT_WHATS.includes(v) && v !== 'pos' ? 'contains' : 'is'; c.val = v === 'clause' ? 'normal' : v === 'flag' ? 'clauseref' : v === 'moved' ? '' : ''; c.ws = ''; c.incol = ''; write(); draw(); }, { 'data-test': 'rb-what' }));
          const w = c.what || 'marker';
          const hows = w === 'marker' || w === 'col' ? [['is', 'is'], ['any', 'any'], ['regex', 'matches pattern']]
            : w === 'label' ? [['is', 'is'], ['regex', 'matches pattern']]
              : w === 'list' ? [['is', 'is'], ['any', 'is set'], ['regex', 'matches pattern']]
                : w === 'pos' ? [['is', 'is'], ['regex', 'matches pattern']]
                  : TEXT_WHATS.includes(w) ? [['contains', 'contains'], ['regex', 'matches pattern']]
                    : w === 'moved' ? [['any', 'any'], ['is', 'is']] : null;
          if (hows) row.appendChild(sel(hows, c.how, (v) => { c.how = v; write(); draw(); }, { 'data-test': 'rb-how' }));
          const needsVal = !(c.how === 'any') && w !== 'flag' && w !== 'clause';
          if (w === 'clause') row.appendChild(sel(CLAUSES.map((x) => [x, x]), c.val || 'normal', (v) => { c.val = v; write(); }, { 'data-test': 'rb-val' }));
          else if (w === 'flag') row.appendChild(sel(FLAGS, c.val || 'clauseref', (v) => { c.val = v; write(); }, { 'data-test': 'rb-val' }));
          else if (w === 'moved' && c.how === 'is') row.appendChild(sel([['preposed', 'preposed'], ['postposed', 'postposed']], c.val || 'preposed', (v) => { c.val = v; write(); }, { 'data-test': 'rb-val' }));
          else if (needsVal && c.how !== 'regex' && w === 'marker' && markerNames.length) row.appendChild(sel(markerNames.map((x) => [x, x]).concat(markerNames.includes(c.val) || !c.val ? [] : [[c.val, c.val]]), c.val || markerNames[0], (v) => { c.val = v; write(); }, { 'data-test': 'rb-val' }));
          else if (needsVal && c.how !== 'regex' && w === 'col' && colNames.length) row.appendChild(sel(colNames.concat(colNames.some((x) => x.value === c.val) || !c.val ? [] : [{ value: c.val, label: c.val }]), c.val || colNames[0].value, (v) => { c.val = v; write(); }, { 'data-test': 'rb-val' }));
          else if (w === 'list') {
            row.appendChild(sel(listNames.map((x) => [x, x]), c.list || listNames[0] || '', (v) => { c.list = v; write(); }, { 'data-test': 'rb-list' }));
            if (needsVal) row.appendChild(el('input', { type: 'text', value: c.val || '', placeholder: c.how === 'regex' ? 'pattern' : 'value', 'data-test': 'rb-val', oninput: (e) => { c.val = e.target.value; write(); } }));
          } else if (needsVal) row.appendChild(el('input', { type: 'text', value: c.val || '', placeholder: c.how === 'regex' ? 'pattern, e.g. ^ka-' : 'text', 'data-test': 'rb-val', oninput: (e) => { c.val = e.target.value; write(); }, style: { fontFamily: c.how === 'regex' ? 'var(--mono)' : '' } }));
          if (c.how === 'regex') row.appendChild(el('label', { class: 'small', title: 'Upper and lower case alike' }, el('input', { type: 'checkbox', checked: !!c.ci, onchange: (e) => { c.ci = e.target.checked; write(); } }), ' any case'));
          if (TEXT_WHATS.includes(w)) {
            if (wss.length) row.appendChild(sel([['', 'default writing system']].concat(wss.map((x) => [x, x])), c.ws || '', (v) => { c.ws = v; write(); }, { 'data-test': 'rb-ws', title: 'The writing system to read' }));
            if (w !== 'free' && colNames.length) row.appendChild(sel([['', 'in any column']].concat(colNames.map((x) => [x.value, 'in ' + x.label])), c.incol || '', (v) => { c.incol = v; write(); }, { 'data-test': 'rb-incol', title: 'Only the words in this column' }));
          }
          row.appendChild(el('button', { class: 'icon-btn danger', title: 'Remove this condition', onclick: () => { k.conds.splice(ci, 1); write(); draw(); } }, '✕'));
          box.appendChild(row);
        });
        box.appendChild(el('button', { class: 'btn small', 'data-test': 'rb-add-cond', onclick: () => { k.conds.push({ neg: false, what: 'marker', how: markerNames.length ? 'is' : 'any', val: markerNames[0] || '', ws: '', incol: '' }); write(); draw(); } }, '+ condition'));
        // what the cell shows and how the row or cell is styled
        const st = k.style;
        const outIn = el('input', { type: 'text', value: k.out || '', placeholder: 'text in the cell (✓ when empty)', 'data-test': 'rb-out', oninput: (e) => { k.out = e.target.value; write(); } });
        const hlOn = el('input', { type: 'checkbox', checked: !!st.hl, 'data-test': 'rb-hl', onchange: (e) => { st.hl = e.target.checked ? (hlColor.value || '#fff2a8') : ''; write(); draw(); } });
        const hlColor = el('input', { type: 'color', value: st.hl || '#fff2a8', title: 'Highlight colour', onchange: (e) => { st.hl = e.target.value; hlOn.checked = true; write(); } });
        const cOn = el('input', { type: 'checkbox', checked: !!st.c, onchange: (e) => { st.c = e.target.checked ? (cColor.value || '#c0392b') : ''; write(); draw(); } });
        const cColor = el('input', { type: 'color', value: st.c || '#c0392b', title: 'Text colour', onchange: (e) => { st.c = e.target.value; cOn.checked = true; write(); } });
        const tog = (key, label, title) => el('button', { class: 'tog' + (st[key] ? ' on' : ''), title, 'data-test': 'rb-' + key, onclick: () => { st[key] = !st[key]; write(); draw(); } }, label);
        const chipSel = sel([['', 'no marker chips'], ['all', 'chips of all the row’s markers'], ['some', 'chips of the markers…']], k.chips || '', (v) => { k.chips = v; if (v === 'some' && !k.chipsHow) k.chipsHow = markerNames.length ? 'is' : 'regex'; write(); draw(); }, { 'data-test': 'rb-chips' });
        const chipHow = k.chips === 'some' ? sel([['is', 'named'], ['regex', 'matching pattern']], k.chipsHow || 'is', (v) => { k.chipsHow = v; write(); draw(); }, { 'data-test': 'rb-chips-how' }) : null;
        const chipVal = k.chips !== 'some' ? null : (k.chipsHow !== 'regex' && markerNames.length)
          ? sel(markerNames.map((x) => [x, x]).concat(markerNames.includes(k.chipsVal) || !k.chipsVal ? [] : [[k.chipsVal, k.chipsVal]]), k.chipsVal || markerNames[0], (v) => { k.chipsVal = v; write(); }, { 'data-test': 'rb-chips-val' })
          : el('input', { type: 'text', value: k.chipsVal || '', placeholder: 'pattern, e.g. ^ShdArg', 'data-test': 'rb-chips-val', style: { fontFamily: 'var(--mono)' }, oninput: (e) => { k.chipsVal = e.target.value; write(); } });
        if (k.chips === 'some' && !k.chipsVal && chipVal && chipVal.tagName === 'SELECT') k.chipsVal = chipVal.value;
        box.appendChild(el('div', { class: 'row' }, el('span', {}, 'Show'), outIn, chipSel, chipHow, chipVal, k.chips === 'some' && k.chipsHow === 'regex' ? el('label', { class: 'small' }, el('input', { type: 'checkbox', checked: !!k.chipsCi, onchange: (e) => { k.chipsCi = e.target.checked; write(); } }), ' any case') : null));
        box.appendChild(el('div', { class: 'row cn-style' }, el('span', {}, 'Style'),
          sel([['cell', 'this cell'], ['row', 'the whole row']], st.scope || 'cell', (v) => { st.scope = v; write(); }, { 'data-test': 'rb-scope' }),
          el('label', { class: 'small' }, hlOn, ' highlight'), hlColor, tog('b', 'B', 'Bold'), tog('i', 'I', 'Italic'), tog('u', 'U', 'Underline'), el('label', { class: 'small' }, cOn, ' text colour'), cColor,
          tog('chip', 'as a chip', 'Draw the text as a chip'), tog('join', 'join with the row above', 'No line between this row and the one above; a row style covers both')));
        host.appendChild(box);
      });
      host.appendChild(el('button', { class: 'btn small', 'data-test': 'rb-add-case', onclick: () => { cases.push({ conds: [], join: 'and', out: '', style: { scope: 'cell' } }); write(); draw(); } }, '+ case'));
      host.appendChild(el('p', { class: 'muted small' }, 'The first case that fits a row decides. A pattern (^ start, $ end, . any character, [aeiou], (a|b)…) is tested on the text as written — a ', FS.regexHelp ? FS.regexHelp('js') : 'JavaScript regular expression', '; “contains” ignores case and diacritics.'));
    };
    draw();
    return { reload: () => { const c = casesFrom(opts.text(), listNames); if (c) { cases = c.length ? c : cases; draw(); return true; } return false; } };
  }


  /* ---------------------------------------------------------- the chart SEARCH builder (Seth,
   * 2026-10-19: the search "as GUI/visually creatable as possible without requiring the user to use
   * a query language"). The search language (flex/__init__.py `chart_search`) is flat: terms ANDed,
   * `-` for not, `col:X` narrows the cells the content terms apply to, a value may be `/pattern/i`
   * (Python's re). So the builder is a list of conditions and one "in column", and it reads any
   * query back. */
  const SEARCH_WHATS = [
    ['', 'Words anywhere (words, glosses, forms, notes)'], ['word', 'Word'], ['gloss', 'Gloss (word or morpheme)'], ['form', 'Morpheme form'], ['mgls', 'Morpheme gloss'],
    ['cf', 'Lexeme / citation form'], ['lex', 'Any form'], ['pos', 'Word category'], ['marker', 'Chart marker'], ['clause', 'Clause type'], ['moved', 'Moved text'],
    ['flag', 'Row flag'], ['row', 'Row label'], ['note', 'Row note'], ['chart', 'Chart name'], ['text', 'Text title'], ['template', 'Template'],
  ];
  const SEARCH_FLAGS = [['clauseref', 'has a clause marker [2a]'], ['endsent', 'ends a sentence'], ['endpara', 'ends a paragraph']];
  const sq = (v) => { v = String(v == null ? '' : v); return /\s/.test(v) || v === '' ? '"' + v.replace(/"/g, '') + '"' : v; };
  function searchText(q) {
    const parts = [];
    if (q.col) parts.push('col:' + sq(q.col));
    for (const c of q.conds) {
      const neg = c.neg ? '-' : '';
      const val = c.how === 'regex' ? '/' + String(c.val || '').replace(/\//g, '\\/') + '/' + (c.ci ? 'i' : '') : sq(c.val);
      if (c.what === '') { if (c.how === 'regex') parts.push(neg + 'word:' + val); else parts.push(c.neg ? '-word:' + val : val); }
      else if (c.what === 'flag') parts.push(neg + (c.val || 'clauseref'));
      else if (c.what === 'moved') parts.push(neg + (c.how === 'any' || !c.val ? 'moved' : 'moved:' + c.val));
      else if (c.what === 'marker' && c.how === 'any') parts.push(neg + 'marker:*');
      else if (c.what === 'clause') parts.push(neg + 'clause:' + (c.val || 'dependent'));
      else parts.push(neg + c.what + ':' + val);
    }
    return parts.join(' ');
  }
  function searchFrom(text) {
    const q = { col: '', conds: [] };
    const re = /(-)?(?:([A-Za-z]+):)?("([^"]*)"|\/((?:\\.|[^\/\\])*)\/([a-z]*)|\S+)/g;
    let m;
    while ((m = re.exec(text || ''))) {
      const neg = !!m[1];
      let key = (m[2] || '').toLowerCase();
      const quoted = m[4], pat = m[5], flags = m[6] || '';
      let val = quoted != null ? quoted : pat != null ? pat : m[3];
      if (key === 'col' || key === 'column') { if (!neg && !q.col) { q.col = val; continue; } key = 'col'; }
      if (!key && ['moved', 'clauseref', 'endsent', 'endpara'].includes(val.toLowerCase())) { key = val.toLowerCase(); val = ''; }
      const c = { neg, what: '', how: pat != null ? 'regex' : 'contains', val, ci: flags.includes('i') };
      if (key === 'words' || key === 'word' || key === 'txt') c.what = key === 'txt' ? 'word' : key === 'words' ? 'word' : 'word';
      else if (key === 'gls') c.what = 'gloss';
      else if (key === 'morph') c.what = 'form';
      else if (key === 'label') c.what = 'row';
      else if (key === 'notes') c.what = 'note';
      else if (['gloss', 'form', 'mgls', 'cf', 'lex', 'pos', 'marker', 'clause', 'row', 'note', 'chart', 'text', 'template'].includes(key)) c.what = key;
      else if (key === 'moved') { c.what = 'moved'; c.how = val ? 'is' : 'any'; }
      else if (['clauseref', 'endsent', 'endpara'].includes(key)) { c.what = 'flag'; c.val = key; }
      else if (key === 'col') { c.what = 'col'; }
      else if (key) { c.what = ''; c.val = m[0].replace(/^-/, ''); }
      if (c.what === 'marker' && !c.neg && c.val === '*' && c.how !== 'regex') { c.how = 'any'; c.val = ''; }
      if (c.what === 'marker' && c.how === 'contains') c.how = 'is';
      if (c.what === 'pos' || c.what === 'clause' || c.what === 'row') { if (c.how === 'contains') c.how = 'is'; }
      q.conds.push(c);
    }
    return q;
  }
  /* The dialog. opts: {query, chart? (markers / columns to offer), onApply(q)}. */
  async function searchBuilder(opts) {
    const m = FS.modal({ title: 'Search the text charts', class: 'cn-col-dlg' });
    const q = searchFrom(opts.query || '');
    if (!q.conds.length) q.conds.push({ neg: false, what: 'marker', how: 'any', val: '', ci: false });
    let markers = [], columns = [];
    try { markers = (await FS.api.flex_chart_markers()).map((x) => x.name).filter(Boolean); } catch (e) { markers = []; }
    try { const charts = await FS.api.flex_charts(''); const seen = new Set(); for (const c of charts) for (const col of c.columns && Array.isArray(c.columns) ? c.columns : []) { const n = col.name || col; if (!seen.has(n)) { seen.add(n); columns.push(n); } } } catch (e) { columns = []; }
    if (!columns.length && opts.chart && opts.chart.template) columns = (opts.chart.template.columns || []).map((c) => c.name);
    const host = el('div', { class: 'cn-builder', 'data-test': 'search-builder' });
    const out = el('code', { class: 'search-q', 'data-test': 'search-q' });
    const count = el('span', { class: 'muted small', 'data-test': 'search-count' });
    const sel = (options, value, onchange, attrs) => { const s = el('select', Object.assign({}, attrs || {})); for (const o of options) { const [v, l] = Array.isArray(o) ? o : [o.value, o.label]; s.appendChild(el('option', { value: v, selected: v === value }, l)); } s.addEventListener('change', () => onchange(s.value)); return s; };
    const test = FS.debounce(async () => { const t = searchText(q); out.textContent = t || '(everything)'; try { const rows = await FS.api.chart_search(t); count.textContent = rows.length + ' row' + (rows.length === 1 ? '' : 's') + ' match'; } catch (e) { count.textContent = e.message; } }, 200);
    const draw = () => {
      host.innerHTML = '';
      const colIn = el('input', { type: 'text', value: q.col || '', list: 'sb-cols', placeholder: 'any column', 'data-test': 'sb-col', oninput: (e) => { q.col = e.target.value; test(); } });
      const dl = el('datalist', { id: 'sb-cols' }); for (const c of columns) dl.appendChild(el('option', { value: c }));
      host.appendChild(el('div', { class: 'row' }, el('span', {}, 'Rows whose cells in column'), colIn, dl, el('span', { class: 'muted small' }, '(the word conditions below look only there)')));
      host.appendChild(el('div', { class: 'row' }, el('span', {}, 'hold all of these:')));
      q.conds.forEach((c, ci) => {
        const row = el('div', { class: 'cn-cond', 'data-test': 'sb-cond' });
        row.appendChild(el('label', { class: 'small', title: 'The opposite' }, el('input', { type: 'checkbox', checked: !!c.neg, onchange: (e) => { c.neg = e.target.checked; test(); } }), ' not'));
        row.appendChild(sel(SEARCH_WHATS, c.what, (v) => { c.what = v; c.how = v === 'marker' ? (markers.length ? 'is' : 'any') : v === 'moved' ? 'any' : ['pos', 'clause', 'row', 'flag'].includes(v) ? 'is' : 'contains'; c.val = v === 'clause' ? 'dependent' : v === 'flag' ? 'clauseref' : ''; test(); draw(); }, { 'data-test': 'sb-what' }));
        const w = c.what;
        const hows = w === 'marker' ? [['is', 'is'], ['any', 'any'], ['regex', 'matches pattern']] : w === 'moved' ? [['any', 'any'], ['is', 'is']] : w === 'flag' || w === 'clause' ? null
          : ['pos', 'row'].includes(w) ? [['is', 'is'], ['regex', 'matches pattern']] : [['contains', 'contains'], ['regex', 'matches pattern']];
        if (hows) row.appendChild(sel(hows, c.how, (v) => { c.how = v; test(); draw(); }, { 'data-test': 'sb-how' }));
        if (w === 'clause') row.appendChild(sel(CLAUSES.map((x) => [x, x]), c.val || 'dependent', (v) => { c.val = v; test(); }, { 'data-test': 'sb-val' }));
        else if (w === 'flag') row.appendChild(sel(SEARCH_FLAGS, c.val || 'clauseref', (v) => { c.val = v; test(); }, { 'data-test': 'sb-val' }));
        else if (w === 'moved' && c.how === 'is') row.appendChild(sel([['preposed', 'preposed'], ['postposed', 'postposed']], c.val || 'preposed', (v) => { c.val = v; test(); }, { 'data-test': 'sb-val' }));
        else if (w === 'marker' && c.how === 'is' && markers.length) row.appendChild(sel(markers.map((x) => [x, x]).concat(markers.includes(c.val) || !c.val ? [] : [[c.val, c.val]]), c.val || (c.val = markers[0]), (v) => { c.val = v; test(); }, { 'data-test': 'sb-val' }));
        else if (c.how !== 'any') row.appendChild(el('input', { type: 'text', value: c.val || '', placeholder: c.how === 'regex' ? 'pattern, e.g. ^ka-' : 'text', 'data-test': 'sb-val', style: { fontFamily: c.how === 'regex' ? 'var(--mono)' : '' }, oninput: (e) => { c.val = e.target.value; test(); } }));
        if (c.how === 'regex') row.appendChild(el('label', { class: 'small' }, el('input', { type: 'checkbox', checked: !!c.ci, onchange: (e) => { c.ci = e.target.checked; test(); } }), ' any case'));
        row.appendChild(el('button', { class: 'icon-btn danger', title: 'Remove', onclick: () => { q.conds.splice(ci, 1); test(); draw(); } }, '✕'));
        host.appendChild(row);
      });
      host.appendChild(el('button', { class: 'btn small', 'data-test': 'sb-add', onclick: () => { q.conds.push({ neg: false, what: '', how: 'contains', val: '', ci: false }); test(); draw(); } }, '+ condition'));
      host.appendChild(el('p', { class: 'muted small' }, 'A pattern here is a ', FS.regexHelp ? FS.regexHelp('py') : 'Python regular expression', '. “contains” ignores case and diacritics. The search looks at every chart of the project.'));
      test();
    };
    draw();
    m.body.append(host, el('div', { class: 'row' }, el('span', { class: 'muted small' }, 'The search as text: '), out, el('span', { class: 'spacer' }), count));
    m.body.appendChild(el('div', { class: 'btn-row' }, el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), el('button', { class: 'btn primary', 'data-test': 'sb-apply', onclick: () => { const t = searchText(q); m.close(); if (opts.onApply) opts.onApply(t); } }, 'Search')));
    return m;
  }

  /* The rule's answer for a row: {text, style} or null. */
  const markerIs = (m, sel) => { if (!sel.sel && !sel.rx) return true; if (sel.rx) return [m.name, m.abbr].concat(m.path || []).some((x) => x && sel.rx.test(x)); const v = norm(sel.sel); return v === '*' || norm(m.name) === v || norm(m.abbr) === v || (m.path || []).some((p) => norm(p) === v) || (v.startsWith('group:') && (m.path || []).some((p) => norm(p) === v.slice(6))); };
  function applyRule(cases, ctx) {
    for (const c of cases) {
      if (!evalExpr(c.expr, ctx)) continue;
      const chips = [];
      for (const sel of c.chips || []) for (const m of ctx.markerItems || []) if (markerIs(m, sel) && !chips.includes(m)) chips.push(m);
      return { text: c.out, style: c.style, chips };
    }
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
    /* What the rules see of merged cells: the chart's `merge=` choice. */
    ctxOpts() { return { mergeOwner: !!(this.st.spec && FS.chart && FS.chart.mergeMode && FS.chart.mergeMode(this.st.spec) === 'owner') }; }
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
      const ruleAnswer = (col, row, chart) => { const r = self.cases(col); if (r.error) return null; return applyRule(r.cases, rowCtx(row, chart, self.st.values, self.st.columns, self.ctxOpts())); };
      return {
        cols: this.st.columns.map((c) => ({ name: c.name, kind: c.kind, side: c.side === 'left' ? 'left' : 'right', frozen: !!c.frozen })),
        cell(i, row, chart) {
          const col = self.st.columns[i];
          if (!col) return { text: '' };
          if (col.kind === 'check') return { text: isTicked(self.value(row, col)) ? '\u2713' : '' };
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
        // "Change the chart…" in the ⋯ menu: the note's front matter, then the view embed (retarget → onSpecChange)
        changeChart: async (guid, retarget) => { if (self.opts.changeChart) await self.opts.changeChart(guid); self.obj = null; retarget(guid); },
      };
      FS.interlinear.render(host, spec, opts);
    }
    /* The custom columns as the chart renderer draws them. */
    extraCols() {
      const self = this;
      return this.st.columns.map((col, ci) => ({
        key: 'x' + ci,
        name: col.name,
        side: col.side === 'left' ? 'left' : 'right',
        frozen: !!col.frozen,
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
        const ans = applyRule(r.cases, rowCtx(row, chart, this.st.values, this.st.columns, this.ctxOpts()));
        const node = el('span', { class: 'xrule', dataset: { col: col.name } });
        if (ans) {
          // the row's markers as chips, in the look their rules give them (Seth, 2026-10-19: "show chips … for specific markers")
          for (const m of ans.chips || []) {
            const look = FS.chart && FS.chart.markerLook ? FS.chart.markerLook(chart, m, this.st.spec) : { bg: '#eee', fg: '#111' };
            node.appendChild(el('span', { class: 'ctag xmark', style: { background: look.bg, color: look.fg }, title: m.name + ((m.path || []).length ? ' — ' + m.path.join(' › ') : ''), dataset: { marker: m.name } }, m.abbr || m.name));
          }
          if (ans.text) node.appendChild(ans.style.chip ? el('span', { class: 'ctag xchip', style: Object.assign({ background: ans.style.hl || 'var(--panel-2)' }, ans.style.c ? { color: ans.style.c } : {}, ans.style.b ? { fontWeight: '800' } : {}) }, ans.text) : document.createTextNode(ans.text));
          if (ans.style.scope === 'cell' && !ans.style.chip) styleNode(node, ans.style);
        }
        return node;
      }
      if (col.kind === 'check') {
        // a checkbox: one click ticks or clears it, saved at once
        const on = isTicked(this.value(row, col));
        const box = el('input', { type: 'checkbox', class: 'xcheck', checked: on, 'data-test': 'xcheck', title: (on ? 'Ticked' : 'Not ticked') + ' — click to change', 'aria-label': col.name + ', row ' + (row.label || '') });
        box.addEventListener('click', (e) => e.stopPropagation());
        box.addEventListener('change', () => { self.setValue(row, col, box.checked ? 'x' : ''); box.title = (box.checked ? 'Ticked' : 'Not ticked') + ' — click to change'; });
        const lab = el('label', { class: 'xval check', dataset: { col: col.name } }, box);
        lab.addEventListener('click', (e) => e.stopPropagation());
        return lab;
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
        const ans = applyRule(r.cases, rowCtx(row, this.obj, this.st.values, this.st.columns, this.ctxOpts()));
        if (ans && ans.style.scope === 'row') Object.assign(out.style, styleOf(ans.style));
        // `join`: no line between this row and the one above, and the case's row style covers both
        // (Seth, 2026-10-19: a ^ShdArg row continues the previous row's clause — "remove the border
        // between them and custom style a range on those rows")
        if (ans && ans.style.join) { out.classes.push('join-up'); out.joinStyle = Object.assign(out.joinStyle || {}, ans.style.scope === 'row' ? styleOf(ans.style) : {}); }
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
        pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'cn-col-toggle-side', onclick: () => { close(); col.side = col.side === 'left' ? 'right' : 'left'; self.changed(); self.drawChart(); } }, col.side === 'left' ? 'Move to the right of the chart' : 'Move to the left of the chart'));
        pop.appendChild(el('button', { class: 'menu-item', 'data-test': 'cn-col-toggle-frozen', onclick: () => { close(); col.frozen = !col.frozen; self.changed(); self.drawChart(); } }, col.frozen ? 'Unfreeze (scrolls with the chart)' : 'Freeze (stays put when the chart scrolls sideways)'));
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
      const col = ci == null ? { name: '', kind: 'notes', settings: '', side: 'right', frozen: false } : Object.assign({}, this.st.columns[ci]);
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
        if (k === 'check') settingsBox.appendChild(el('p', { class: 'muted small' }, 'A box in each row that you tick or leave empty. A rule can test it: “' + (name.value.trim() || 'Done') + ':*” is a ticked row.'));
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
              for (const row of self.obj.rows || []) { const ctx = rowCtx(row, self.obj, self.st.values, self.st.columns, self.ctxOpts()); const i = cases.findIndex((c) => evalExpr(c.expr, ctx)); if (i >= 0) counts[i]++; else none++; }
              preview.textContent = cases.map((c, i) => '“' + (c.out || '') + '”: ' + counts[i] + ' row' + (counts[i] === 1 ? '' : 's')).join(' · ') + (none ? ' · no case: ' + none : '');
              err.textContent = '';
            } catch (e) { err.textContent = e.message; preview.textContent = ''; }
          };
          // the builder writes the text; typing in the text re-reads the builder when it can (Seth, 2026-10-19)
          const bhost = el('div', { class: 'cn-builder', 'data-test': 'cn-builder' });
          const help = el('p', { class: 'muted small' }, 'Cases separated by “;”, each  condition → text [styles]. The first case that fits a row gives the cell its text. Terms: marker:Name · col:Name · clause:dependent|speech|song · moved · moved:preposed · clauseref · endsent · endpara · txt:"ka-" · gls:"sleep" · form: · mgls: · pos: · cf: · lex: · free: · label:"2a" · a list column as Status:new; a value may be a pattern, txt:/^ka-/i; a field in one writing system, gls@fr:…; the words of one column only, col:Subject[txt:/^ka-/] — with and, or, not, ( ). Outputs: text, @markers (the row’s markers as chips), @markers:Name or @markers:/pattern/. Styles: row or cell, hl, hl#rrggbb, b, i, u, c#rrggbb, chip (the text as a chip), join (no line between this row and the one above). A pattern is a ', FS.regexHelp ? FS.regexHelp('js') : 'JavaScript regular expression', '.');
          let builder = null;
          let mode = (col.settings || '').trim() ? 'text' : 'builder';
          try { if (localStorage.getItem('fs:ruleMode') === 'builder' && !(col.settings || '').trim()) mode = 'builder'; } catch (e) { /* ignore */ }
          const tabs = el('div', { class: 'seg', 'data-test': 'cn-rule-mode' });
          const showMode = (m2) => {
            mode = m2;
            try { localStorage.setItem('fs:ruleMode', m2); } catch (e) { /* ignore */ }
            for (const b of tabs.children) b.classList.toggle('on', b.dataset.mode === m2);
            ruleTa.hidden = help.hidden = m2 !== 'text';
            bhost.hidden = m2 !== 'builder';
            if (m2 === 'builder') { bhost.innerHTML = ''; builder = ruleBuilder(bhost, { chart: self.obj, columns: self.st.columns, text: () => ruleTa.value, setText: (t) => { ruleTa.value = t; }, onChange: test }); }
          };
          for (const [m2, l] of [['builder', 'Builder'], ['text', 'Text']]) tabs.appendChild(el('button', { class: 'seg-btn', dataset: { mode: m2 }, 'data-test': 'cn-rule-' + m2, onclick: () => showMode(m2) }, l));
          ruleTa.addEventListener('input', FS.debounce(() => { test(); if (builder && mode === 'builder') builder.reload(); }, 250));
          settingsBox.append(tabs, help, ruleTa, bhost, preview);
          showMode(mode);
          test();
        }
      };
      kindSel.addEventListener('change', drawSettings);
      drawSettings();
      // where the column sits, and whether it stays put when the chart scrolls sideways (Seth, 2026-10-18)
      const sideSel = el('select', { 'data-test': 'cn-col-side' }, el('option', { value: 'right', selected: col.side !== 'left' }, 'Right of the chart'), el('option', { value: 'left', selected: col.side === 'left' }, 'Left of the chart'));
      const frozenCb = el('input', { type: 'checkbox', checked: !!col.frozen, 'data-test': 'cn-col-frozen' });
      body.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Heading'), name), el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Kind'), kindSel), settingsBox,
        el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Place'), sideSel, el('label', { style: { marginLeft: '12px' } }, frozenCb, ' Freeze (stays put when the chart scrolls sideways)')), err);
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
        const next = { name: nm, kind, settings, side: sideSel.value === 'left' ? 'left' : 'right', frozen: frozenCb.checked };
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
  FS.chartnote = { parse, serialize, parseRule, evalExpr, applyRule, rowCtx, anchorOf, KINDS, casesText, casesFrom, ruleBuilder, chartWritingSystems, searchText, searchFrom, searchBuilder };
  FS.chartSearchBuilder = searchBuilder;
})();
