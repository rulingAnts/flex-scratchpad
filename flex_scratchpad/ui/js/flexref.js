/* flexref.js — the `{{flex:…}}` embed grammar: parse, serialise, and resolve style targets.
 *
 *   {{flex:entry <guid>}}
 *   {{flex:sense <guid>}}
 *   {{flex:text <guid> seg=3-5 lines=txt,morph,mgls,gls,pos,ft hl=3.2 b=3.1-3.4 u="ka-" "label"}}
 *
 * target  = [line:]seg[.word[:c1[-c2]]]   ranges: 3-5 (segments), 3.2-3.4 (words), 3.2-4.1
 *         | [line:][*]"text"               text match on that line (first match; * = all)
 * line    = txt (default) | morph | mgls | gls | pos | ft | lit | note | cf
 * style   = hl | b | u | i | s | color, with an optional colour: hl[#fff2a8]=…  color[red]=…
 * Words are numbered 1.. counting only real words (punctuation is skipped); characters are
 * grapheme clusters, 1-based, inclusive. Only "…" quotes are allowed inside {{ }} and no raw
 * `|`, so an embed can live inside a table cell.
 *
 * An ATTACHED FILE (Seth, 2026-10-17) is the same kind of embed without the `flex:`:
 *   {{file attachments/Survey%20notes.pdf "Survey"}}     copied into the notebook (the default)
 *   {{file C:/Recordings/elicitation 3.wav}}            → written C:/Recordings/elicitation%203.wav: linked where it is
 *   {{file attachments/preview.html preview h=480}}     a web page shown in the note, 480 px high
 * The reference is percent-encoded only where it must be (% space " { } | and controls), so
 * Unicode names stay readable; a relative reference is inside the notebook, an absolute one is
 * a link. spec = {kind: 'file', ref, label, extra}; `guid` is ''.
 *
 * A TEXT CHART (Seth, 2026-10-18 — a FieldWorks constituent chart, whole, a range of rows, or
 * a block of cells), the same grammar with chart targets:
 *   {{flex:chart <guid> rows=2-5 at=<a>-<b> cols=Nucleus,Postnuclear/Inner lines=txt,gls free=row hl=r2 b=r3c4 u=r2c3.1 color[red]=c4 "label"}}
 * `rows=` counts rows 1.. through the chart (FLEx's own labels "1a", "2b" are what is shown);
 * `at=` anchors the first and last ROW by GUID (spec.seg / spec.at hold both, as for a text);
 * `cols=` lists the columns shown (a name, Group/Name, an abbreviation, a group's name for all
 * of its columns, c3 or c3-c5 by position); `headers=off` drops the header rows; `free=col|row|
 * tip|off` places the free translations; `notes=off` hides the row notes. A chart target is
 * rN (a row), cN (a column), rNcM (a cell), rNcM.W (a word), with ranges rN-rM / rNcM-rNcK /
 * rNcM.W-K; `line:` as for texts (txt by default). */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});

  // `tag` = FLEx's text markup tags, drawn under the words (Seth, 2026-10-17); on by default,
  // off when an explicit `lines=` leaves it out, like any other line
  // `cols` (Seth, 2026-10-18): the text's CHART COLUMNS drawn on the example as tags, off by default
  const LINES = ['txt', 'morph', 'mgls', 'gls', 'pos', 'ft', 'lit', 'note', 'cf', 'tag', 'cols'];
  const STYLES = ['hl', 'b', 'u', 'i', 's', 'color'];
  const DEFAULT_LINES = ['txt', 'morph', 'mgls', 'gls', 'pos', 'ft', 'tag'];
  // Entry embeds choose their FIELDS instead of lines (`fields=cf,mt,gl,def,ex,tr,sub`):
  // entry-level cf (citation form), lf (lexeme form), mt (morph type), hn (homograph number),
  // note; per sense sn (number), spos (category), gl (gloss), def (definition), ex (examples),
  // tr (example translations), sub (sub-senses), snote (sense note), sem (semantic domains).
  // `senses=1,2.1` keeps only those senses (a parent keeps its sub-senses while `sub` is on).
  const ENTRY_FIELDS = ['cf', 'lf', 'mt', 'hn', 'note', 'sn', 'spos', 'gl', 'def', 'ex', 'tr', 'sub', 'snote', 'sem'];
  const DEFAULT_FIELDS = ['cf', 'mt', 'hn', 'sn', 'spos', 'gl', 'def', 'ex', 'tr', 'sub'];
  const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const EMBED_RE = /\{\{\s*(?:flex:|file\s)[^{}]*\}\}/g;
  const EMBED_LINE_RE = /^\s*\{\{\s*(?:flex:|file\s)[^{}]*\}\}\s*$/;
  const encodeRef = (ref) => String(ref || '').replace(/[%\s"{}|\x00-\x1f]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase().padStart(2, '0'));
  const decodeRef = (s) => String(s || '').replace(/%([0-9A-Fa-f]{2})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));

  const TARGET_RE = new RegExp('^(?:(' + LINES.join('|') + '):)?(\\d+)(?:\\.(\\d+))?(?::(\\d+)(?:-(\\d+))?)?(?:-(\\d+)(?:\\.(\\d+))?)?$');
  const QUOTED_RE = new RegExp('^(?:(' + LINES.join('|') + '):)?(\\*)?"(.*)"$');
  // chart targets: rN[cM[.W]][-rN[cM[.W]] | -cM | -W] and cN[-cM]
  const CHART_TARGET_RE = new RegExp('^(?:(' + LINES.join('|') + '):)?(?:r(\\d+)(?:c(\\d+))?(?:\\.(\\d+))?(?:-(?:r(\\d+))?(?:c(\\d+))?(?:\\.?(\\d+))?)?|c(\\d+)(?:-c?(\\d+))?)$');
  const CHART_LINES = ['txt', 'gls', 'morph', 'mgls', 'pos', 'cf'];
  const DEFAULT_CHART_LINES = ['txt', 'gls'];
  const FREE_MODES = ['row', 'col', 'tip', 'off'];

  function parseChartTarget(item) {
    item = item.trim();
    const m = CHART_TARGET_RE.exec(item);
    if (!m) return null;
    const t = { line: m[1] || '' };
    if (m[8] != null) { t.col = +m[8]; if (m[9]) t.colEnd = +m[9]; return t; }
    t.row = +m[2];
    if (m[3]) t.col = +m[3];
    if (m[4]) t.word = +m[4];
    if (m[5] || m[6] || m[7]) {
      if (m[5]) t.rowEnd = +m[5];
      if (m[6]) t.colEnd = +m[6];
      if (m[7]) t.wordEnd = +m[7];
      if (t.rowEnd == null && t.colEnd == null && t.wordEnd != null && t.word == null) { t.colEnd = t.wordEnd; delete t.wordEnd; }   // r2c3-5 → columns 3–5
    }
    if (t.word != null && !t.line) t.line = 'txt';          // a word target styles its Words line unless told otherwise
    return t;
  }
  function serializeChartTarget(t) {
    let s = t.line && !(t.line === 'txt' && t.word != null) ? t.line + ':' : '';
    if (t.row == null) return s + 'c' + t.col + (t.colEnd != null && t.colEnd !== t.col ? '-c' + t.colEnd : '');
    s += 'r' + t.row + (t.col != null ? 'c' + t.col : '') + (t.word != null ? '.' + t.word : '');
    if (t.rowEnd != null || t.colEnd != null || t.wordEnd != null) {
      s += '-' + (t.rowEnd != null ? 'r' + t.rowEnd : '') + (t.colEnd != null ? 'c' + t.colEnd : '') + (t.wordEnd != null ? (t.rowEnd != null || t.colEnd != null ? '.' : '') + t.wordEnd : '');
    }
    return s;
  }

  function parseTarget(item) {
    item = item.trim();
    if (!item) return null;
    let m = QUOTED_RE.exec(item);
    if (m) return { line: m[1] || 'txt', text: m[3], all: !!m[2] };
    m = TARGET_RE.exec(item);
    if (!m) return null;
    const t = { line: m[1] || 'txt', seg: +m[2] };
    if (m[3]) t.word = +m[3];
    if (m[4]) t.chars = [+m[4], m[5] ? +m[5] : +m[4]];
    if (m[6]) { t.segEnd = +m[6]; if (m[7]) t.wordEnd = +m[7]; }
    return t;
  }

  function serializeTarget(t) {
    if (t.text != null) return (t.line && t.line !== 'txt' ? t.line + ':' : '') + (t.all ? '*' : '') + '"' + t.text.replace(/"/g, '”') + '"';
    let s = (t.line && t.line !== 'txt' ? t.line + ':' : '') + t.seg;
    if (t.word != null) s += '.' + t.word;
    if (t.chars) s += ':' + t.chars[0] + (t.chars[1] !== t.chars[0] ? '-' + t.chars[1] : '');
    if (t.segEnd != null) s += '-' + t.segEnd + (t.wordEnd != null ? '.' + t.wordEnd : '');
    return s;
  }

  /* Tokenise `key[color]=v1,v2,"a b" key2=… "label"` honouring quotes. */
  function tokenize(rest) {
    const out = [];
    let i = 0;
    const n = rest.length;
    while (i < n) {
      while (i < n && /\s/.test(rest[i])) i++;
      if (i >= n) break;
      if (rest[i] === '"') {               // bare quoted string = label
        const j = rest.indexOf('"', i + 1);
        out.push({ label: rest.slice(i + 1, j < 0 ? n : j) });
        i = j < 0 ? n : j + 1;
        continue;
      }
      let key = '';
      while (i < n && /[A-Za-z_]/.test(rest[i])) key += rest[i++];
      let color = '';
      if (rest[i] === '[') { const j = rest.indexOf(']', i); color = rest.slice(i + 1, j < 0 ? n : j); i = j < 0 ? n : j + 1; }
      if (rest[i] !== '=') {               // stray word — keep it so nothing is lost
        while (i < n && !/\s/.test(rest[i])) key += rest[i++];
        out.push({ flag: key });
        continue;
      }
      i++;
      let val = '';
      let q = false;
      while (i < n) {
        const ch = rest[i];
        if (ch === '"') q = !q;
        if (!q && /\s/.test(ch)) break;
        val += ch; i++;
      }
      out.push({ key: key.toLowerCase(), color, val });
    }
    return out;
  }

  function splitItems(val) {
    const items = [];
    let cur = '', q = false;
    for (const ch of val) {
      if (ch === '"') q = !q;
      if (ch === ',' && !q) { items.push(cur); cur = ''; } else cur += ch;
    }
    items.push(cur);
    return items.map((s) => s.trim()).filter(Boolean);
  }

  function parseFile(s) {
    const m = /^file\s+(\S+)\s*([\s\S]*)$/.exec(s);
    if (!m || m[1].startsWith('"')) return null;
    const spec = { kind: 'file', guid: '', ref: decodeRef(m[1]), seg: null, at: null, lines: null, fields: null, senses: null, ws: null, styles: [], label: '', extra: {} };
    for (const tok of tokenize(m[2])) {
      if (tok.label != null) spec.label = tok.label;
      else if (tok.flag) spec.extra[tok.flag] = true;
      else spec.extra[tok.key] = tok.val;
    }
    return spec;
  }

  function parse(src) {
    const s = String(src || '').trim().replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '');
    if (/^file\s/.test(s)) return parseFile(s);
    const m = /^flex:(entry|sense|text|wordform|chart)\s+([0-9a-fA-F-]{36})\s*([\s\S]*)$/i.exec(s);
    if (!m || !GUID.test(m[2])) return null;
    const spec = { kind: m[1].toLowerCase(), guid: m[2].toLowerCase(), seg: null, at: null, lines: null, fields: null, senses: null, ws: null, styles: [], label: '', extra: {} };
    const chart = spec.kind === 'chart';
    for (const tok of tokenize(m[3])) {
      if (tok.label != null) { spec.label = tok.label; continue; }
      if (tok.flag) { spec.extra[tok.flag] = true; continue; }
      if (tok.key === 'seg' || (chart && tok.key === 'rows')) {
        const r = /^(\d+)(?:-(\d+))?$/.exec(tok.val);
        if (r) spec.seg = [+r[1], r[2] ? +r[2] : +r[1]];
      } else if (tok.key === 'at') {
        // at=<first>-<last>: the last 12 hex of the first and last segment's GUIDs, so the range
        // follows its segments when FLEx renumbers them (see model.resolve_range)
        const r = /^([0-9a-f]{4,32})(?:-([0-9a-f]{4,32}))?$/i.exec(tok.val);
        if (r) spec.at = [r[1].toLowerCase(), (r[2] || r[1]).toLowerCase()];
      } else if (tok.key === 'ws') {
        // ws=txt:fau-fonipa,gls:id — which writing system each interlinear line shows
        spec.ws = {};
        for (const item of splitItems(tok.val)) { const i = item.indexOf(':'); if (i > 0) { const line = item.slice(0, i).toLowerCase(); if (LINES.includes(line) || line === 'title') spec.ws[line] = item.slice(i + 1); } }
        if (!Object.keys(spec.ws).length) spec.ws = null;
      } else if (tok.key === 'lines') {
        spec.lines = splitItems(tok.val).map((x) => x.toLowerCase()).filter((x) => LINES.includes(x));
      } else if (tok.key === 'fields') {
        spec.fields = tok.val.trim().toLowerCase() === 'none' ? [] : splitItems(tok.val).map((x) => x.toLowerCase()).filter((x) => ENTRY_FIELDS.includes(x));
      } else if (tok.key === 'senses') {
        spec.senses = splitItems(tok.val).map((x) => x.trim()).filter((x) => /^\d+(\.\d+)*$/.test(x));
        if (!spec.senses.length) spec.senses = null;
      } else if (STYLES.includes(tok.key)) {
        const targets = splitItems(tok.val).map(chart ? parseChartTarget : parseTarget).filter(Boolean);
        if (targets.length) spec.styles.push({ style: tok.key, color: tok.color || '', targets });
      } else {
        spec.extra[tok.key] = tok.val;
      }
    }
    return spec;
  }

  function serialize(spec) {
    if (spec.kind === 'file') {
      const parts = ['file ' + encodeRef(spec.ref)];
      for (const [k, v] of Object.entries(spec.extra || {})) parts.push(v === true ? k : k + '=' + v);
      if (spec.label) parts.push('"' + spec.label.replace(/"/g, '”') + '"');
      return '{{' + parts.join(' ') + '}}';
    }
    const parts = ['flex:' + spec.kind + ' ' + spec.guid];
    const chart = spec.kind === 'chart';
    if (spec.seg) parts.push((chart ? 'rows=' : 'seg=') + spec.seg[0] + (spec.seg[1] !== spec.seg[0] ? '-' + spec.seg[1] : ''));
    if (spec.at && spec.at[0]) parts.push('at=' + spec.at[0] + (spec.at[1] && spec.at[1] !== spec.at[0] ? '-' + spec.at[1] : ''));
    if (spec.lines && spec.lines.length) parts.push('lines=' + spec.lines.join(','));
    if (spec.fields) parts.push('fields=' + (spec.fields.length ? spec.fields.join(',') : 'none'));
    if (spec.senses && spec.senses.length) parts.push('senses=' + spec.senses.join(','));
    if (spec.ws && Object.keys(spec.ws).length) parts.push('ws=' + Object.keys(spec.ws).filter((k) => spec.ws[k]).map((k) => k + ':' + spec.ws[k]).join(','));
    for (const g of spec.styles) {
      if (!g.targets.length) continue;
      parts.push(g.style + (g.color ? '[' + g.color + ']' : '') + '=' + g.targets.map(chart ? serializeChartTarget : serializeTarget).join(','));
    }
    for (const [k, v] of Object.entries(spec.extra || {})) parts.push(v === true ? k : k + '=' + v);
    if (spec.label) parts.push('"' + spec.label.replace(/"/g, '”') + '"');
    return '{{' + parts.join(' ') + '}}';
  }

  function sameTarget(a, b) {
    return a.line === b.line && a.seg === b.seg && (a.word || null) === (b.word || null)
      && (a.segEnd || null) === (b.segEnd || null) && (a.wordEnd || null) === (b.wordEnd || null)
      && String(a.chars || '') === String(b.chars || '') && (a.text || null) === (b.text || null) && !!a.all === !!b.all
      && (a.row || null) === (b.row || null) && (a.col || null) === (b.col || null) && (a.rowEnd || null) === (b.rowEnd || null) && (a.colEnd || null) === (b.colEnd || null);
  }

  function hasStyle(spec, target, style, color) {
    return spec.styles.some((g) => g.style === style && (color == null || (g.color || '') === (color || '')) && g.targets.some((t) => sameTarget(t, target)));
  }

  /* Toggle one target in a style group. Returns true when it was added. */
  function toggleStyle(spec, target, style, color) {
    color = color || '';
    const group = spec.styles.find((g) => g.style === style && (g.color || '') === color);
    if (group) {
      const i = group.targets.findIndex((t) => sameTarget(t, target));
      if (i >= 0) { group.targets.splice(i, 1); if (!group.targets.length) spec.styles.splice(spec.styles.indexOf(group), 1); return false; }
      group.targets.push(target);
      return true;
    }
    // the same target in the same style with ANOTHER colour: replace the colour
    for (const g of spec.styles) {
      if (g.style === style) {
        const i = g.targets.findIndex((t) => sameTarget(t, target));
        if (i >= 0) { g.targets.splice(i, 1); if (!g.targets.length) spec.styles.splice(spec.styles.indexOf(g), 1); break; }
      }
    }
    spec.styles.push({ style, color, targets: [target] });
    return true;
  }

  function clearStyles(spec, target) {
    for (const g of [...spec.styles]) {
      g.targets = g.targets.filter((t) => !(target ? sameTarget(t, target) : true));
      if (!g.targets.length) spec.styles.splice(spec.styles.indexOf(g), 1);
    }
  }

  /* ------------------------------------------------------------------ resolution */

  /* The texts a line shows for a word (what char ranges and text matches index into). */
  function lineTextOfWord(word, line) {
    switch (line) {
      case 'txt': return word.txt || '';
      case 'morph': return (word.morphs || []).map((m) => m.form).join(' ');
      case 'mgls': return (word.morphs || []).map((m) => m.gls).join(' ');
      case 'cf': return (word.morphs || []).map((m) => m.cf || '').join(' ');
      case 'gls': return word.gls || '';
      case 'pos': return word.pos || '';
      default: return '';
    }
  }
  function lineTextOfSegment(seg, line) {
    if (line === 'ft') return seg.free || '';
    if (line === 'lit') return seg.lit || '';
    if (line === 'note') return (seg.notes || []).join('\n');
    return '';
  }
  const SEG_LINES = ['ft', 'lit', 'note'];

  function key(n, line, w) { return n + '|' + line + '|' + (w || 0); }

  /* Build an index { key → [{style, color, chars|null}] } for the segments in `text`
   * (a text object as returned by the API: segments with words). */
  function resolveStyles(spec, text) {
    const index = new Map();
    const add = (n, line, w, g, chars) => {
      const k = key(n, line, w);
      if (!index.has(k)) index.set(k, []);
      index.get(k).push({ style: g.style, color: g.color || '', chars: chars || null });
    };
    const segs = (text && text.segments) || [];
    const byN = new Map(segs.map((s) => [s.n, s]));
    const wordsOf = (seg) => (seg.words || []).filter((w) => !w.punct);
    for (const g of spec.styles || []) {
      for (const t of g.targets) {
        if (t.text != null) {
          let found = false;
          const needle = FS.normalize(t.text, true);
          if (!needle) continue;
          for (const seg of segs) {
            if (found && !t.all) break;
            if (SEG_LINES.includes(t.line)) {
              const hits = findAll(lineTextOfSegment(seg, t.line), needle, t.all);
              for (const h of hits) { add(seg.n, t.line, 0, g, h); found = true; }
              continue;
            }
            const words = wordsOf(seg);
            for (let i = 0; i < words.length; i++) {
              if (found && !t.all) break;
              const hits = findAll(lineTextOfWord(words[i], t.line), needle, t.all);
              for (const h of hits) { add(seg.n, t.line, i + 1, g, h); found = true; }
            }
          }
          continue;
        }
        const segA = t.seg, segB = t.segEnd != null ? t.segEnd : t.seg;
        for (let n = segA; n <= segB; n++) {
          const seg = byN.get(n);
          if (!seg) continue;
          if (SEG_LINES.includes(t.line)) { add(n, t.line, 0, g, t.chars); continue; }
          const words = wordsOf(seg);
          if (t.word == null && t.wordEnd == null) {   // whole segment on that line
            for (let i = 1; i <= words.length; i++) add(n, t.line, i, g, null);
            if (!words.length) add(n, t.line, 0, g, null);
            continue;
          }
          let from = 1, to = words.length;
          if (n === segA && t.word != null) from = t.word;
          if (n === segB) to = t.wordEnd != null ? t.wordEnd : (t.segEnd != null ? words.length : (t.word != null ? t.word : words.length));
          for (let i = from; i <= to; i++) add(n, t.line, i, g, (from === to && t.chars) ? t.chars : null);
        }
      }
    }
    return index;
  }

  /* Grapheme-aware substring search: returns [c1,c2] grapheme ranges (1-based inclusive). */
  function findAll(hay, needle, all) {
    const out = [];
    if (!hay || !needle) return out;
    const gs = FS.graphemes(hay);
    const norm = gs.map((g) => FS.normalize(g, true));
    // cumulative map from normalised char offsets back to grapheme index
    const map = [];
    let joined = '';
    norm.forEach((s, gi) => { for (let k = 0; k < s.length; k++) map.push(gi); joined += s; });
    let p = joined.indexOf(needle);
    while (p >= 0) {
      const c1 = map[p] + 1, c2 = map[Math.min(p + needle.length - 1, map.length - 1)] + 1;
      out.push([c1, c2]);
      if (!all) break;
      p = joined.indexOf(needle, p + Math.max(1, needle.length));
    }
    return out;
  }

  /* Styles that apply to a specific cell. */
  function stylesFor(index, n, line, w) {
    return index.get(key(n, line, w)) || [];
  }

  /* A chart's styles: { "row|col|word|line" → [{style, color}] } — 0 stands for "every" (a row
   * target keys row|0|0, a column 0|col|0, a cell row|col|0, a word row|col|w); `line` is ''
   * for the whole cell. `chartStylesFor` gathers the four levels for one word of one cell. */
  const ckey = (r, c, w, line) => r + '|' + c + '|' + w + '|' + (line || '');
  function resolveChartStyles(spec, chart) {
    const index = new Map();
    const add = (r, c, w, line, g) => { const k = ckey(r, c, w, line); if (!index.has(k)) index.set(k, []); index.get(k).push({ style: g.style, color: g.color || '' }); };
    const nrows = (chart && chart.rowCount) || 0;
    const ncols = (chart && chart.template && chart.template.columns && chart.template.columns.length) || 0;
    for (const g of spec.styles || []) {
      for (const t of g.targets) {
        if (t.row == null) { for (let c = t.col; c <= (t.colEnd != null ? t.colEnd : t.col); c++) add(0, c, 0, t.line, g); continue; }
        const r2 = t.rowEnd != null ? t.rowEnd : t.row;
        for (let r = t.row; r <= Math.min(r2, nrows || r2); r++) {
          if (t.col == null) { add(r, 0, 0, t.line, g); continue; }
          const c2 = t.colEnd != null ? t.colEnd : t.col;
          for (let c = t.col; c <= Math.min(c2, ncols || c2); c++) {
            if (t.word == null) { add(r, c, 0, t.line, g); continue; }
            const w2 = t.wordEnd != null ? t.wordEnd : t.word;
            for (let w = t.word; w <= w2; w++) add(r, c, w, t.line || 'txt', g);
          }
        }
      }
    }
    return index;
  }
  function chartStylesFor(index, r, c, w, line) {
    const out = [];
    const levels = [[r, 0, 0], [0, c, 0], [r, c, 0]];
    if (w) levels.push([r, c, w]);
    for (const [rr, cc, ww] of levels) {
      const e0 = index.get(ckey(rr, cc, ww, ''));
      if (e0) out.push(...e0);
      if (line) { const e = index.get(ckey(rr, cc, ww, line)); if (e) out.push(...e); }
    }
    return out;
  }
  const chartLines = (spec) => { const l = spec.lines && spec.lines.length ? spec.lines.filter((x) => CHART_LINES.includes(x)) : DEFAULT_CHART_LINES; return l.length ? l : ['txt']; };
  const freeMode = (spec) => { const v = (spec.extra && spec.extra.free) || 'row'; return FREE_MODES.includes(v) ? v : 'row'; };

  /* An example's OWN look for FLEx text markup tags (Seth, 2026-10-17: project-, tab-, folder- and
   * example-scoped styles, the most specific winning; tagstyles.js resolves them): the `tags=`
   * key, `tags=Subject:off,Topic:bg#d1fae5+b,*:nolabel` — per tag (its name with spaces as `_`,
   * its abbreviation, its GUID, or `*` for all) tokens joined by `+`: `off` / `on` (hidden /
   * shown here whatever the broader scopes say), `bg#rrggbb`, `fg#rrggbb`, `b`, `i`, `u`,
   * `nolabel` / `label`. A rule = {tag, hide?, bg?, fg?, b?, i?, u?, label?}. */
  // the look of one tag in `tags=`: on/off, the bar's colours (bg/fg), B I U and a colour (c) on the
  // words, brackets around the span (brsq [], brrd (), brcu {}, bran ⟨⟩, brdb ⟦⟧, brce ⌈⌉, brfl ⌊⌋,
  // brbar ||), hl (a marker over the words), tile (a box behind the whole column), box (a border),
  // bar / nobar (the lane under the words, otherwise shown only when no text style is on);
  // the border's line (Seth, 2026-10-18: "edit line style and thickness"): bs(solid|dashed|dotted|
  // double), bw1…bw6 (px); the tile's own colour ("edit the background color"): tc#rrggbb
  // `row` (Seth, 2026-10-18): a chart MARKER's rule styles the whole row the marker is in (`marker%3ATopic:row+bg#fde68a`)
  // moved text (Seth, 2026-10-19): ms = whose look a moved word group wears (from = the column it
  // came from, to = the column it sits in, own = the rule's), ml = its label (from / to / off)
  const TAG_TOKEN = /^(off|on|b|i|u|row|nolabel|label|hl|tile|box|bar|nobar|br(sq|rd|cu|an|db|ce|fl|bar)|bs(solid|dashed|dotted|double)|bw[1-6]|bg#[0-9a-f]{6}|fg#[0-9a-f]{6}|c#[0-9a-f]{6}|tc#[0-9a-f]{6}|bc#[0-9a-f]{6}|ms(from|to|own)|ml(from|to|off))$/;
  const encodeTagKey = (t) => String(t).replace(/%/g, '%25').replace(/_/g, '%5F').replace(/,/g, '%2C').replace(/:/g, '%3A').replace(/\+/g, '%2B').replace(/ /g, '_');
  const decodeTagKey = (k) => String(k).replace(/_/g, ' ').replace(/%([0-9A-Fa-f]{2})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
  function parseTagRules(val) {
    const out = [];
    for (const item of String(val || '').split(',')) {
      const i = item.indexOf(':');
      if (i <= 0) continue;
      const r = { tag: decodeTagKey(item.slice(0, i)) };
      for (const tok of item.slice(i + 1).split('+')) {
        const t = tok.trim().replace(/%23/gi, '#').toLowerCase();
        if (!TAG_TOKEN.test(t)) continue;
        if (t === 'off') r.hide = true; else if (t === 'on') r.hide = false;
        else if (t === 'nolabel') r.label = false; else if (t === 'label') r.label = true;
        else if (t.startsWith('bg#')) r.bg = t.slice(2); else if (t.startsWith('fg#')) r.fg = t.slice(2); else if (t.startsWith('c#')) r.c = t.slice(1);
        else if (t.startsWith('tc#')) r.tc = t.slice(2); else if (t.startsWith('bc#')) r.bc = t.slice(2);
        else if (t.startsWith('ms')) r.ms = t.slice(2); else if (t.startsWith('ml')) r.ml = t.slice(2);
        else if (t.startsWith('bs')) r.bs = t.slice(2); else if (t.startsWith('bw')) r.bw = +t.slice(2);
        else if (t.startsWith('br')) r.br = t.slice(2);
        else if (t === 'bar') r.bar = true; else if (t === 'nobar') r.bar = false;
        else r[t] = true;
      }
      if (Object.keys(r).length > 1) out.push(r);
    }
    return out;
  }
  function serializeTagRules(rules) {
    return (rules || []).map((r) => {
      const toks = [];
      if (r.hide === true) toks.push('off'); else if (r.hide === false) toks.push('on');
      if (r.bg) toks.push('bg' + String(r.bg).toLowerCase()); if (r.fg) toks.push('fg' + String(r.fg).toLowerCase());
      if (r.c) toks.push('c' + String(r.c).toLowerCase());
      for (const k of ['b', 'i', 'u', 'row', 'hl', 'tile', 'box']) if (r[k]) toks.push(k);
      if (r.br && /^(sq|rd|cu|an|db|ce|fl|bar)$/.test(r.br)) toks.push('br' + r.br);
      if (r.bs && /^(solid|dashed|dotted|double)$/.test(r.bs)) toks.push('bs' + r.bs);
      if (/^(from|to|own)$/.test(r.ms || '')) toks.push('ms' + r.ms);
      if (/^(from|to|off)$/.test(r.ml || '')) toks.push('ml' + r.ml);
      if (r.bw >= 1 && r.bw <= 6) toks.push('bw' + Math.round(r.bw));
      if (r.tc) toks.push('tc' + String(r.tc).toLowerCase());
      if (r.bc) toks.push('bc' + String(r.bc).toLowerCase());
      if (r.bar === true) toks.push('bar'); else if (r.bar === false) toks.push('nobar');
      if (r.label === false) toks.push('nolabel'); else if (r.label === true) toks.push('label');
      return toks.length ? encodeTagKey(r.tag) + ':' + toks.join('+') : '';
    }).filter(Boolean).join(',');
  }
  const tagRules = (spec) => parseTagRules(spec && spec.extra && spec.extra.tags);
  function setTagRules(spec, rules) { spec.extra = spec.extra || {}; const v = serializeTagRules(rules); if (v) spec.extra.tags = v; else delete spec.extra.tags; }
  const showsTags = (spec) => ((spec && spec.lines && spec.lines.length) ? spec.lines : DEFAULT_LINES).includes('tag');
  const showsCols = (spec) => !!(spec && spec.lines && spec.lines.includes('cols'));

  /* Find every embed in a markdown string: [{start, end, src, spec}]. */
  function findEmbeds(md) {
    const out = [];
    EMBED_RE.lastIndex = 0;
    let m;
    while ((m = EMBED_RE.exec(md || ''))) {
      const spec = parse(m[0]);
      if (spec) out.push({ start: m.index, end: m.index + m[0].length, src: m[0], spec });
    }
    return out;
  }

  /* The senses an entry embed shows, in order: all, or those listed in `senses=` (a listed
   * parent brings its sub-senses while `sub` is on); sub-senses drop out when `sub` is off. */
  function entryFields(spec) { return spec.fields == null ? DEFAULT_FIELDS.slice() : spec.fields; }
  function visibleSenses(spec, senses) {
    const f = entryFields(spec);
    const want = spec.senses && spec.senses.length ? spec.senses : null;
    return (senses || []).filter((s) => {
      if (!f.includes('sub') && (s.level || 0) > 0) return false;
      if (!want) return true;
      const num = s.number || '';
      return want.some((w) => num === w || num.startsWith(w + '.'));
    });
  }
  FS.flexref = {
    ENTRY_FIELDS, DEFAULT_FIELDS, entryFields, visibleSenses,
    LINES, STYLES, DEFAULT_LINES, GUID, EMBED_RE, encodeRef, decodeRef,
    parse, serialize, parseTarget, serializeTarget, sameTarget,
    CHART_LINES, DEFAULT_CHART_LINES, FREE_MODES, parseChartTarget, serializeChartTarget, resolveChartStyles, chartStylesFor, chartLines, freeMode,
    hasStyle, toggleStyle, clearStyles, resolveStyles, stylesFor, findAll,
    lineTextOfWord, lineTextOfSegment, findEmbeds,
    parseTagRules, serializeTagRules, tagRules, setTagRules, showsTags, showsCols,
    isEmbedLine: (line) => EMBED_LINE_RE.test(line || ''),
  };
})();
