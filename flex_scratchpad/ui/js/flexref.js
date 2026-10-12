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
 * `|`, so an embed can live inside a table cell. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});

  const LINES = ['txt', 'morph', 'mgls', 'gls', 'pos', 'ft', 'lit', 'note', 'cf'];
  const STYLES = ['hl', 'b', 'u', 'i', 's', 'color'];
  const DEFAULT_LINES = ['txt', 'morph', 'mgls', 'gls', 'pos', 'ft'];
  const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const EMBED_RE = /\{\{\s*flex:[^{}]*\}\}/g;

  const TARGET_RE = new RegExp('^(?:(' + LINES.join('|') + '):)?(\\d+)(?:\\.(\\d+))?(?::(\\d+)(?:-(\\d+))?)?(?:-(\\d+)(?:\\.(\\d+))?)?$');
  const QUOTED_RE = new RegExp('^(?:(' + LINES.join('|') + '):)?(\\*)?"(.*)"$');

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

  function parse(src) {
    const s = String(src || '').trim().replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '');
    const m = /^flex:(entry|sense|text|wordform)\s+([0-9a-fA-F-]{36})\s*([\s\S]*)$/i.exec(s);
    if (!m || !GUID.test(m[2])) return null;
    const spec = { kind: m[1].toLowerCase(), guid: m[2].toLowerCase(), seg: null, lines: null, ws: null, styles: [], label: '', extra: {} };
    for (const tok of tokenize(m[3])) {
      if (tok.label != null) { spec.label = tok.label; continue; }
      if (tok.flag) { spec.extra[tok.flag] = true; continue; }
      if (tok.key === 'seg') {
        const r = /^(\d+)(?:-(\d+))?$/.exec(tok.val);
        if (r) spec.seg = [+r[1], r[2] ? +r[2] : +r[1]];
      } else if (tok.key === 'ws') {
        // ws=txt:fau-fonipa,gls:id — which writing system each interlinear line shows
        spec.ws = {};
        for (const item of splitItems(tok.val)) { const i = item.indexOf(':'); if (i > 0) { const line = item.slice(0, i).toLowerCase(); if (LINES.includes(line) || line === 'title') spec.ws[line] = item.slice(i + 1); } }
        if (!Object.keys(spec.ws).length) spec.ws = null;
      } else if (tok.key === 'lines') {
        spec.lines = splitItems(tok.val).map((x) => x.toLowerCase()).filter((x) => LINES.includes(x));
      } else if (STYLES.includes(tok.key)) {
        const targets = splitItems(tok.val).map(parseTarget).filter(Boolean);
        if (targets.length) spec.styles.push({ style: tok.key, color: tok.color || '', targets });
      } else {
        spec.extra[tok.key] = tok.val;
      }
    }
    return spec;
  }

  function serialize(spec) {
    const parts = ['flex:' + spec.kind + ' ' + spec.guid];
    if (spec.seg) parts.push('seg=' + spec.seg[0] + (spec.seg[1] !== spec.seg[0] ? '-' + spec.seg[1] : ''));
    if (spec.lines && spec.lines.length) parts.push('lines=' + spec.lines.join(','));
    if (spec.ws && Object.keys(spec.ws).length) parts.push('ws=' + Object.keys(spec.ws).filter((k) => spec.ws[k]).map((k) => k + ':' + spec.ws[k]).join(','));
    for (const g of spec.styles) {
      if (!g.targets.length) continue;
      parts.push(g.style + (g.color ? '[' + g.color + ']' : '') + '=' + g.targets.map(serializeTarget).join(','));
    }
    for (const [k, v] of Object.entries(spec.extra || {})) parts.push(v === true ? k : k + '=' + v);
    if (spec.label) parts.push('"' + spec.label.replace(/"/g, '”') + '"');
    return '{{' + parts.join(' ') + '}}';
  }

  function sameTarget(a, b) {
    return a.line === b.line && a.seg === b.seg && (a.word || null) === (b.word || null)
      && (a.segEnd || null) === (b.segEnd || null) && (a.wordEnd || null) === (b.wordEnd || null)
      && String(a.chars || '') === String(b.chars || '') && (a.text || null) === (b.text || null) && !!a.all === !!b.all;
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

  FS.flexref = {
    LINES, STYLES, DEFAULT_LINES, GUID, EMBED_RE,
    parse, serialize, parseTarget, serializeTarget, sameTarget,
    hasStyle, toggleStyle, clearStyles, resolveStyles, stylesFor, findAll,
    lineTextOfWord, lineTextOfSegment, findEmbeds,
    isEmbedLine: (line) => /^\s*\{\{\s*flex:[^{}]*\}\}\s*$/.test(line || ''),
  };
})();
