/* flexcopy.js — the plain-text copy of every FLEx object, written INTO the note's file so the
 * file reads without the app (Seth, 2026-10-17: "make sure that our FLEx links save cached
 * interlinear text (and text reference) so that a markdown file IS actually readable elsewhere").
 *
 * In the file, right after a `{{flex:…}}` object:
 *   - an object on a line of its own (a block):
 *       {{flex:text … }}
 *       [The dog and the river 1.1–1.2](silfw://… "flex-copy")
 *       ```flex-copy
 *       1.1  Kabir  ka-nuwa-mo   lo.
 *            dog    3SG-sleep-PST DECL
 *            ‘The dog slept.’
 *       ```
 *   - an object inside a line of text or a table cell: one link, right after it:
 *       {{flex:text … }}[The dog and the river 1.1: ‘The dog slept.’](silfw://… "flex-copy")
 *
 * "The inverse of the old convention of putting JavaScript inside HTML comment tags" (Seth): the
 * app never shows a copy. `strip` takes them out when a note is opened, so the editor, a drag, a
 * cut and an undo only ever see the `{{ }}` object; `attach` writes them back on save, from the
 * object as last fetched (`FS.interlinear.peek`), in the form the object's place calls for, so a
 * move into or out of a table cell switches the form. Only a fence whose info string is exactly
 * `flex-copy`, and only a link titled "flex-copy" right after an object, is ours: any other code
 * a user types is left alone. `flex_scratchpad/notebook.py` (`without_flex_copies`) strips the
 * same two shapes for excerpts, search and tags; tests/js/flexcopy.test.js and
 * tests/test_flexcopy.py pin both.
 *
 * WHEN a copy is written (Seth): when the example has changed, and when it moves into or out of a
 * table. So `stale()` only reports an object whose STORED copy no longer matches a fresh fetch;
 * a note with no copies yet gets them at its next save, and opening a note never rewrites it. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const R = FS.flexref;

  const EMB = '\\{\\{\\s*flex:[^{}]*\\}\\}';
  const LINK = '\\[((?:\\\\.|[^\\]\\\\\\n])*)\\]\\(([^\\s()]*) "flex-copy"\\)';
  const BLOCK_RE = new RegExp('(' + EMB + ')[ \\t]*\\n[ \\t]*' + LINK + '[ \\t]*(?:\\n[ \\t]*```flex-copy[ \\t]*\\n([\\s\\S]*?)\\n[ \\t]*```[ \\t]*)?(?=\\n|$)', 'g');
  const INLINE_RE = new RegExp('(' + EMB + ')' + LINK, 'g');
  const EMB_RE = new RegExp(EMB, 'g');
  const FENCE_RE = /^\s*(```|~~~)/;

  /* ------------------------------------------------------------------ text helpers */
  const seg = typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter('und', { granularity: 'grapheme' }) : null;
  const width = (s) => { s = String(s || ''); if (seg) { let n = 0; for (const _ of seg.segment(s)) n++; return n; } return Array.from(s.replace(/\p{M}/gu, '')).length; };
  const pad = (s, w) => s + ' '.repeat(Math.max(0, w - width(s)));
  const flat = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const noFence = (s) => String(s).replace(/`{3,}/g, (m) => m.split('').join('​'));   // a ``` in FLEx data never closes our fence
  const linkText = (s, inTable) => {
    let t = flat(s).replace(/\\/g, '\\\\').replace(/\[/g, '\\[').replace(/\]/g, '\\]');
    if (inTable) t = t.replace(/\|/g, '\\|');
    return t;
  };
  const unLinkText = (t) => String(t || '').replace(/\\(.)/g, '$1');
  // a Markdown link destination holds no space or bracket: FLEx's URL is percent-encoded already,
  // a project name with a space or parentheses gets the same treatment here
  const linkUrl = (u) => String(u || '').replace(/[\s()<>]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase().padStart(2, '0'));
  const link = (text, url, inTable) => '[' + linkText(text, inTable) + '](' + linkUrl(url) + ' "flex-copy")';

  /* ------------------------------------------------------------------ building a copy */
  const blank = (s) => (FS.interlinear && FS.interlinear.blankSeg ? FS.interlinear.blankSeg(s) : false);
  const labelOf = (obj, n) => { const e = obj && obj.index && obj.index.find((x) => x.n === n); return e ? e.label : String(n); };

  function textRef(spec, obj) {
    const segs = (obj.segments || []).filter((s) => !blank(s));
    let range = '';
    if (segs.length) {
      const a = segs[0].label || labelOf(obj, segs[0].n), z = segs[segs.length - 1].label || labelOf(obj, segs[segs.length - 1].n);
      range = a === z ? a : a + '–' + z;
    }
    return [(spec.label ? spec.label + ' — ' : '') + (obj.title || '(untitled text)'), range].filter(Boolean).join(' ');
  }
  /* The interlinear lines the example shows (`lines=`), each word a column padded to the widest
   * of its lines, the segment's FLEx number in front; punctuation rides on its word on the Word
   * line; the free / literal translation and notes beneath. */
  function textBody(spec, obj) {
    const lines = spec.lines && spec.lines.length ? spec.lines : R.DEFAULT_LINES;
    const out = [];
    const segs = (obj.segments || []).filter((s) => !blank(s));
    const labels = segs.map((s) => s.label || labelOf(obj, s.n));
    const lw = Math.max(0, ...labels.map(width));
    segs.forEach((s, si) => {
      const cols = [];
      let lead = '';
      (s.words || []).forEach((w, ti) => {
        if (w.punct) {
          if (/^[(\[{«“‘'"¿¡]/.test(w.txt || '') || !cols.length) lead += w.txt || '';
          else cols[cols.length - 1].txt += w.txt || '';
          return;
        }
        cols.push({ w, txt: lead + (w.txt || ''), ai: w.ai != null ? w.ai : ti });
        lead = '';
      });
      if (lead) { if (cols.length) cols[cols.length - 1].txt += lead; else cols.push({ w: {}, txt: lead }); }
      const rows = [];
      for (const line of lines) {
        if (line === 'ft' || line === 'lit' || line === 'note') continue;
        const cells = cols.map(({ w, txt }) => {
          if (line === 'txt') return txt;
          if (line === 'morph') return (w.morphs || []).map((m) => m.form || '').join(' ');
          if (line === 'mgls') return (w.morphs || []).map((m) => m.gls || '').join(' ');
          if (line === 'cf') return (w.morphs || []).map((m) => m.cf || '').join(' ');
          if (line === 'gls') return w.gls || '';
          if (line === 'pos') return w.pos || '';
          return '';
        }).map(flat);
        if (line !== 'txt' && !cells.some((c) => c)) continue;
        rows.push(cells);
      }
      // FLEx's text markup tags, a row per lane: the abbreviation under the first word, `—` on
      if (lines.includes('tag') && FS.interlinear && FS.interlinear.segTags) {
        const tg = FS.interlinear.segTags(obj, spec, s);
        const lanes = tg.reduce((m, o) => Math.max(m, o.lane + 1), 0);
        for (let l = 0; l < lanes; l++) rows.push(cols.map(({ ai }) => { const o = tg.find((x) => x.lane === l && ai >= x.a && ai <= x.z); return o ? (ai === o.firstAi ? (o.t.tag.abbr || o.t.tag.name) : '\u2014') : ''; }));
      }
      const widths = cols.map((_, i) => Math.max(0, ...rows.map((r) => width(r[i]))));
      const lab = (k) => pad(k === 0 ? labels[si] : '', lw) + (lw ? '  ' : '');
      rows.forEach((r, k) => out.push((lab(k) + r.map((c, i) => (i === r.length - 1 ? c : pad(c, widths[i]))).join('  ')).replace(/\s+$/, '')));
      const ind = lab(rows.length ? 1 : 0);
      if (lines.includes('ft') && s.free) out.push(ind + '‘' + flat(s.free) + '’');
      if (lines.includes('lit') && s.lit) out.push(ind + 'lit. ‘' + flat(s.lit) + '’');
      if (lines.includes('note')) for (const n of s.notes || []) out.push(ind + 'Note: ' + flat(n));
      if (si < segs.length - 1) out.push('');
    });
    return out.join('\n');
  }
  const textInline = (spec, obj) => {
    const segs = (obj.segments || []).filter((s) => !blank(s));
    const ft = segs.map((s) => flat(s.free)).filter(Boolean).join(' ');
    const said = ft ? '‘' + ft + '’' : segs.map((s) => flat(s.baseline)).filter(Boolean).join(' ');
    return textRef(spec, obj) + (said ? ': ' + said : '');
  };

  function entrySenses(spec, obj) {
    const shown = R.visibleSenses(spec, obj.senses || []);
    return spec.kind === 'sense' ? shown.filter((s) => s.guid === spec.guid) : shown;
  }
  function entryRef(spec, obj) {
    const hw = (obj.headword || obj.lexemeForm || '?') + (obj.homograph ? String(obj.homograph) : '');
    const senses = entrySenses(spec, obj);
    const pos = obj.pos || (senses[0] && senses[0].pos) || '';
    return (spec.label ? spec.label + ' — ' : '') + hw + (pos ? ' (' + pos + ')' : '');
  }
  function entryBody(spec, obj) {
    const F = new Set(R.entryFields(spec));
    const out = [];
    for (const s of entrySenses(spec, obj)) {
      const parts = [];
      if (F.has('sn') && s.number) parts.push(s.number + '.');
      if (F.has('spos') && s.pos) parts.push(s.pos);
      if (F.has('gl') && s.gloss) parts.push('‘' + flat(s.gloss) + '’');
      if (F.has('def') && s.definition && s.definition !== s.gloss) parts.push('— ' + flat(s.definition));
      out.push('  '.repeat(Math.min(3, s.level || 0)) + parts.join(' '));
      if (F.has('ex')) for (const ex of s.examples || []) out.push('  '.repeat(Math.min(3, s.level || 0) + 1) + flat(ex.text) + (F.has('tr') && ex.translation ? '  ‘' + flat(ex.translation) + '’' : ''));
    }
    return out.filter((l) => l.trim()).join('\n');
  }
  const entryInline = (spec, obj) => {
    const gl = entrySenses(spec, obj).map((s) => flat(s.gloss)).filter(Boolean).join('; ');
    return entryRef(spec, obj) + (gl ? ' ‘' + gl + '’' : '');
  };

  /* The copy of one object, in its block form (`{text, url, body}`) or its inline form. */
  function build(spec, obj) {
    if (!spec || !obj || spec.kind === 'file') return null;
    const url = obj.url || '';
    if (obj.kind === 'text') return { ref: textRef(spec, obj), inline: textInline(spec, obj), url, body: noFence(textBody(spec, obj)) };
    if (obj.kind === 'entry') return { ref: entryRef(spec, obj), inline: entryInline(spec, obj), url, body: noFence(entryBody(spec, obj)) };
    if (obj.kind === 'wordform') {
      const g = (obj.glosses || []).map(flat).filter(Boolean).join('; ');
      const ref = (spec.label ? spec.label + ' — ' : '') + (obj.form || '?') + ((obj.pos || []).length ? ' (' + obj.pos.join(', ') + ')' : '');
      return { ref, inline: ref + (g ? ' ‘' + g + '’' : ''), url, body: '' };
    }
    return null;
  }
  const blockText = (c) => '\n' + link(c.ref, c.url, false) + (c.body ? '\n```flex-copy\n' + c.body + '\n```' : '');
  const inlineText = (c, inTable) => link(c.inline, c.url, inTable);

  /* ------------------------------------------------------------------ the copies a note had */
  const notes = new Map();       // note id → { copies: Map(embed src → {form, raw, ref, url}), touched }
  const state = (id) => { const k = id || ''; if (!notes.has(k)) notes.set(k, { copies: new Map(), touched: false }); return notes.get(k); };

  /* The note as the app edits it: every copy taken out (and remembered, for an object this session
   * has not fetched). */
  function strip(md, id) {
    const st = state(id);
    st.copies = new Map();
    st.touched = false;
    let s = String(md || '');
    s = s.replace(BLOCK_RE, (all, src, text, url) => {
      st.copies.set(src, { form: 'block', raw: all.slice(src.length), ref: unLinkText(text), url });
      return src;
    });
    s = s.replace(INLINE_RE, (all, src, text, url) => {
      st.copies.set(src, { form: 'inline', raw: all.slice(src.length), ref: unLinkText(text).replace(/: (‘[\s\S]*’|.*)$/, ''), url });
      return src;
    });
    return s;
  }

  /* Every object in the note, where it sits: on a line of its own (block) or in a line / a cell. */
  function places(md) {
    const out = [];
    let inFence = false, pos = 0;
    for (const line of String(md || '').split('\n')) {
      if (FENCE_RE.test(line)) inFence = !inFence;
      else if (!inFence) {
        const table = /^\s*\|/.test(line);
        EMB_RE.lastIndex = 0;
        let m;
        const found = [];
        while ((m = EMB_RE.exec(line))) found.push({ src: m[0], at: pos + m.index + m[0].length });
        const block = found.length === 1 && !table && line.trim() === found[0].src;
        for (const f of found) out.push({ src: f.src, end: block ? pos + line.length : f.at, form: block ? 'block' : 'inline', table });
      }
      pos += line.length + 1;
    }
    return out;
  }
  const peek = (spec) => (FS.interlinear && FS.interlinear.peek ? FS.interlinear.peek(spec) : null);
  /* {raw, ref, url} of one object's copy: built from the object as last fetched, else the copy the
   * file had (switched to the other form when the object has moved into or out of a cell). */
  function copyFor(p, st) {
    const spec = R.parse(p.src);
    const fresh = spec && build(spec, peek(spec));
    if (fresh) return { raw: p.form === 'block' ? blockText(fresh) : inlineText(fresh, p.table), ref: fresh.ref, url: fresh.url };
    const old = st && st.copies.get(p.src);
    if (!old) return null;
    if (old.form === p.form && !(p.form === 'inline' && p.table && /(^|[^\\])\|/.test(old.raw))) return old;
    return { raw: p.form === 'block' ? '\n' + link(old.ref, old.url, false) : link(old.ref, old.url, p.table), ref: old.ref, url: old.url };
  }

  /* The note as it is written to its file: each object followed by its copy. */
  function attach(md, id) {
    const st = id === undefined ? null : state(id);
    const s = String(md || '');
    let out = '', last = 0;
    const wrote = new Map();
    for (const p of places(s)) {
      const c = copyFor(p, st);
      out += s.slice(last, p.end) + (c ? c.raw : '');
      last = p.end;
      if (c) wrote.set(p.src, { form: p.form, raw: c.raw, ref: c.ref, url: c.url });
    }
    out += s.slice(last);
    if (st) {
      for (const [k, v] of wrote) st.copies.set(k, v);
      st.touched = true;
    }
    return out;
  }

  /* Should the note be saved because what FLEx now says differs from a copy it holds? (Or, once
   * the note has been saved this session, because an object has no copy yet.) */
  function stale(md, id) {
    const st = state(id);
    for (const p of places(md)) {
      const spec = R.parse(p.src);
      const fresh = spec && build(spec, peek(spec));
      if (!fresh) continue;
      const old = st.copies.get(p.src);
      if (!old) { if (st.touched) return true; continue; }
      const now = p.form === 'block' ? blockText(fresh) : inlineText(fresh, p.table);
      if (old.raw !== now) return true;
    }
    return false;
  }

  const listeners = [];
  const fetched = FS.debounce ? FS.debounce(() => listeners.forEach((f) => { try { f(); } catch (e) { /* a listener never stops the others */ } }), 400) : () => {};
  FS.flexcopy = { strip, attach, stale, build, places, onFetched: (f) => listeners.push(f), fetched, _notes: notes };
})();
