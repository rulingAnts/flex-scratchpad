/* interlinear.js — renders FLEx objects (interlinear text ranges, entries, wordforms) from
 * the model the Python side builds, applies the embed's highlight/bold/underline targets, and
 * offers the click-to-style popover and the audio transport.
 *
 * Layout borrowed from flextext-editor's gloss tab (renderSegment / renderWordCell): one row of
 * word cells per segment, each cell a stack of lines; the free translation underneath. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el, esc } = FS;
  const R = FS.flexref;

  /* ------------------------------------------------------------------ fetch cache */
  const mem = new Map();
  const keyOf = (kind, guid, a, b, ws, at) => kind + '|' + guid + '|' + (a || '') + '|' + (b || '') + '|' + (ws ? JSON.stringify(ws) : '') + '|' + (at ? at.join('-') : '');
  const flexGet = async (kind, guid, a, b, refresh, ws, at) => {
    const k = keyOf(kind, guid, a, b, ws, at);
    if (!refresh && mem.has(k)) return mem.get(k);
    const p = FS.api.flex_get(kind, guid, a || null, b || null, false, ws || null, at || null).then((obj) => { mem.set(k, obj); return obj; }, (e) => { mem.delete(k); throw e; });
    mem.set(k, p);
    return p;
  };
  const invalidate = (kind, guid) => { for (const k of [...mem.keys()]) if (!kind || k.startsWith((kind === 'sense' ? 'entry' : kind) + '|' + (guid || ''))) mem.delete(k); };

  /* FLEx's number for a segment (paragraph.segment) from the text's index; the running count
   * when the index does not have it. And the reverse, for inputs that take either form. */
  const labelOf = (obj, n) => { const e = obj && obj.index && obj.index.find((x) => x.n === n); return e ? e.label : String(n); };
  const numberFor = (obj, v, fallback) => {
    v = String(v == null ? '' : v).trim();
    if (/^\d+\.\d+$/.test(v)) { const e = obj && obj.index && obj.index.find((x) => x.label === v); return e ? e.n : fallback; }
    const n = parseInt(v, 10);
    return n > 0 ? n : fallback;
  };
  /* After a fetch: a text embed records its anchors the first time, and follows them when
   * FLEx has renumbered its segments — rewriting `seg=` in the note (silently, via onSpecChange). */
  function syncAnchors(spec, obj, opts) {
    if (spec.kind !== 'text' || !obj || obj.kind !== 'text' || !opts.onSpecChange || !spec.seg) return false;
    const anchors = obj.anchors && obj.anchors[0] ? obj.anchors : null;
    let changed = false;
    if (obj.rangeMoved && obj.range && obj.range[0]) { spec.seg = [obj.range[0], obj.range[1]]; changed = true; }
    if (anchors && (!spec.at || (obj.rangeMoved && (spec.at[0] !== anchors[0] || spec.at[1] !== anchors[1])))) { spec.at = anchors; changed = true; }
    if (changed) { opts.onSpecChange(spec); if (obj.rangeMoved) FS.toast('Segments renumbered in FLEx — the example now reads ' + labelOf(obj, spec.seg[0]) + '–' + labelOf(obj, spec.seg[1])); }
    return changed;
  }

  /* ------------------------------------------------------------------ styled text */
  const STYLE_CLASS = { hl: 'st-hl', b: 'st-b', u: 'st-u', i: 'st-i', s: 'st-s', color: 'st-color' };

  /* HTML for one string with a list of {style, color, chars} applied (chars = 1-based
   * inclusive grapheme range or null for the whole string). */
  function styled(text, styles) {
    const gs = FS.graphemes(text);
    if (!styles || !styles.length) return esc(text);
    const marks = gs.map(() => []);
    for (const st of styles) {
      const a = st.chars ? Math.max(1, st.chars[0]) : 1;
      const b = st.chars ? Math.min(gs.length, st.chars[1]) : gs.length;
      for (let i = a - 1; i < b; i++) marks[i].push(st);
    }
    let html = '';
    let cur = null, buf = '';
    const sig = (arr) => arr.map((s) => s.style + ':' + s.color).sort().join(',');
    const open = (arr) => {
      if (!arr.length) return '';
      const cls = arr.map((s) => STYLE_CLASS[s.style]).join(' ');
      const css = [];
      for (const s of arr) {
        if (s.style === 'hl' && s.color) css.push('background:' + s.color);
        if (s.style === 'color' && s.color) css.push('color:' + s.color);
        if (s.style === 'u' && s.color) css.push('text-decoration-color:' + s.color);
      }
      return '<span class="' + cls + '"' + (css.length ? ' style="' + esc(css.join(';')) + '"' : '') + '>';
    };
    const flush = () => { if (buf === '') return; html += cur && cur.length ? open(cur) + esc(buf) + '</span>' : esc(buf); buf = ''; };
    for (let i = 0; i < gs.length; i++) {
      const s = sig(marks[i]);
      if (cur === null || s !== sig(cur)) { flush(); cur = marks[i]; }
      buf += gs[i];
    }
    flush();
    return html;
  }

  /* Several parts shown as separate spans (morph cells) but addressed as one text joined by spaces. */
  function styledParts(parts, styles, cls) {
    if (!styles || !styles.length) return parts.map((p) => '<span class="' + (cls || '') + '">' + esc(p) + '</span>').join('');
    const out = [];
    let offset = 0;
    for (const p of parts) {
      const len = FS.graphemes(p).length;
      const local = [];
      for (const st of styles) {
        if (!st.chars) { local.push(st); continue; }
        const a = st.chars[0] - offset, b = st.chars[1] - offset;
        if (b >= 1 && a <= len) local.push({ style: st.style, color: st.color, chars: [Math.max(1, a), Math.min(len, b)] });
      }
      out.push('<span class="' + (cls || '') + '">' + styled(p, local) + '</span>');
      offset += len + 1;
    }
    return out.join('');
  }

  /* ------------------------------------------------------------------ audio */
  const audio = {
    elForSrc: new Map(),
    current: null,                // {src, begin, end, onTick, onEnd, loop, el}
    get(src) {
      if (!this.elForSrc.has(src)) { const a = new Audio(); a.preload = 'auto'; a.src = src; this.elForSrc.set(src, a); }
      return this.elForSrc.get(src);
    },
    stop() {
      const c = this.current;
      if (!c) return;
      try { c.el.pause(); } catch (e) { /* ignore */ }
      cancelAnimationFrame(c.raf);
      this.current = null;
      if (c.onEnd) c.onEnd();
    },
    /* Play [begin,end] ms of src (both in ms of the file). Resolves when started. */
    async play(src, begin, end, handlers) {
      this.stop();
      const a = this.get(src);
      if (a.error && a.error.code) throw new Error(a.error.message || 'The element has no supported sources.');
      const c = { src, begin, end, el: a, raf: 0, loop: false, ...handlers };
      this.current = c;
      a.currentTime = Math.max(0, begin / 1000);
      const tick = () => {
        if (this.current !== c) return;
        const t = a.currentTime * 1000;
        if (c.onTick) c.onTick(t);
        if (t >= end - 15 || a.ended) {
          if (c.loop) { a.currentTime = begin / 1000; }
          else { a.pause(); this.current = null; if (c.onEnd) c.onEnd(); return; }
        }
        c.raf = requestAnimationFrame(tick);
      };
      try { await a.play(); } catch (e) { this.current = null; throw e; }
      c.raf = requestAnimationFrame(tick);
      return c;
    },
    seek(t) { const c = this.current; if (c) c.el.currentTime = Math.min(c.end, Math.max(c.begin, t)) / 1000; },
    pause() { const c = this.current; if (c) { c.el.pause(); cancelAnimationFrame(c.raf); } },
    resume() { const c = this.current; if (c) { c.el.play(); const tick = () => { if (this.current !== c) return; const t = c.el.currentTime * 1000; if (c.onTick) c.onTick(t); if (t >= c.end - 15) { if (c.loop) c.el.currentTime = c.begin / 1000; else { c.el.pause(); this.current = null; if (c.onEnd) c.onEnd(); return; } } c.raf = requestAnimationFrame(tick); }; c.raf = requestAnimationFrame(tick); } },
  };
  FS.audio = audio;

  /* Capture a played range with MediaRecorder when Python could not cut the clip itself. */
  async function captureClip(srcEl, begin, end, textGuid) {
    if (!srcEl.captureStream || typeof MediaRecorder === 'undefined') return null;
    return new Promise((resolve) => {
      let rec;
      try { rec = new MediaRecorder(srcEl.captureStream(), { mimeType: 'audio/webm;codecs=opus' }); } catch (e) { return resolve(null); }
      const chunks = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        try {
          const blob = new Blob(chunks, { type: 'audio/webm' });
          const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
          resolve(await FS.api.audio_store_clip(textGuid, begin, end, b64, 'audio/webm'));
        } catch (e) { resolve(null); }
      };
      rec.start();
      resolve.rec = rec;
      captureClip.active = rec;
    });
  }

  /* ------------------------------------------------------------------ rendering: text */
  function wsAttrs(ws) {
    const a = {};
    if (ws && ws.tag) a.lang = ws.tag;
    if (ws && ws.rtl) a.dir = 'rtl';
    if (ws && ws.font) a.style = { fontFamily: '"' + ws.font.replace(/"/g, '') + '", var(--font-vern)' };
    return a;
  }

  function renderText(obj, spec, opts, root) {
    const vern = (obj.ws && obj.ws.vern) || {}, anal = (obj.ws && obj.ws.anal) || {};
    const lines = spec.lines && spec.lines.length ? spec.lines : R.DEFAULT_LINES;
    const index = R.resolveStyles(spec, obj);
    const segs = obj.segments || [];
    const mediaByGuid = new Map((obj.media || []).map((m) => [m.guid, m]));
    const box = el('div', { class: 'flex-obj text-obj' + (obj.cached ? ' cached' : '') });
    const range = obj.range || [segs[0] && segs[0].n, segs.length && segs[segs.length - 1].n];
    // FLEx's own numbers (paragraph.segment, as its Gloss / Print views show them) are what a
    // reader knows the segments by; the running count is what `seg=` addresses.
    const lab = (seg) => (seg && seg.label) || (seg && String(seg.n)) || '';
    const first = segs.find((x) => x.n === range[0]) || segs[0], last = segs.find((x) => x.n === range[1]) || segs[segs.length - 1];
    const flexRange = segs.length ? (range[0] === range[1] ? lab(first) : lab(first) + '–' + lab(last)) : '';
    const rangeLabel = segs.length ? (range[0] === range[1] ? 'segment ' + flexRange : 'segments ' + flexRange) + (first && first.label && first.label !== String(first.n) ? ' (' + range[0] + (range[0] === range[1] ? '' : '–' + range[1]) + ' of ' + obj.segmentCount + ')' : ' of ' + obj.segmentCount) : 'no segments';

    const head = el('div', { class: 'flex-head' + (opts.inCell ? ' compact' : '') },
      el('span', Object.assign({ class: 'ttl vern' }, wsAttrs(vern)), obj.title || '(untitled text)'),
      el('span', { class: 'badge' }, rangeLabel),
      obj.cached ? el('span', { class: 'badge warn', title: obj.liveError || 'Shown from the notebook cache' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')) : null,
      spec.label ? el('span', { class: 'badge' }, spec.label) : null,
      el('span', { class: 'spacer' }),
    );
    const anyTimed = segs.some((s) => s.begin != null && s.end != null);
    if (anyTimed && segs.length > 1) {
      head.appendChild(el('button', { class: 'lnk', title: 'Play this range', onclick: () => playRange(box, obj, segs, mediaByGuid, opts) }, '▶ Play ' + flexRange));
    }
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
    if (opts.editable && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Collapse to a chip', onclick: () => setCollapsed(spec, opts, true) }, '⤡'));
    if (opts.editable && opts.inCell && opts.editCell && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Edit the cell\u2019s text (type before or after this example, add another)', onclick: () => opts.editCell() }, '✎'));
    if (opts.editable && !opts.overlay && opts.duplicate) head.appendChild(el('button', { class: 'lnk', title: 'Duplicate this object', onclick: () => opts.duplicate() }, '⧉'));
    if (opts.editable && !opts.overlay && opts.remove) head.appendChild(el('button', { class: 'lnk danger', title: 'Remove this object…', onclick: (e) => removeObject(e.currentTarget, spec, opts) }, '🗑'));
    if (!opts.context) head.appendChild(el('button', { class: 'lnk', title: 'See this example in its context: the whole text, scrolled to it', onclick: () => openContext(spec, obj) }, '⊡ Context'));
    if (!opts.inCell) head.appendChild(el('button', { class: 'lnk', title: 'Copy as FLEx TSV (the rows FLEx itself copies)', onclick: () => { FS.copyText(flexTsv(spec, obj)); FS.toast('Copied as FLEx TSV'); } }, '⎘ TSV'));
    if (obj.url) head.appendChild(el('a', { href: obj.url, title: 'Open in FieldWorks', onclick: (e) => { e.preventDefault(); openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    if (opts.editable) head.appendChild(el('button', { class: 'lnk', title: 'Options', onclick: (e) => embedMenu(e.currentTarget, spec, opts, obj) }, '⋯'));
    box.appendChild(head);

    if (!segs.length) box.appendChild(el('div', { class: 'seg-empty' }, 'No segments in this range.'));
    const sel = { anchor: null };
    for (const seg of segs) {
      box.appendChild(renderSegment(seg, obj, spec, lines, index, vern, anal, mediaByGuid, opts, box, sel));
    }
    return box;
  }

  function renderSegment(seg, obj, spec, lines, index, vern, anal, mediaByGuid, opts, box, sel) {
    const row = el('div', { class: 'segment', dataset: { n: seg.n } });
    const gutter = el('div', { class: 'seg-gutter' }, el('span', { class: 'segnum', title: 'FLEx segment ' + (seg.label || seg.n) + (seg.label && seg.label !== String(seg.n) ? ' (segment ' + seg.n + ' of the text, as seg= counts them)' : '') }, seg.label || String(seg.n)));
    const timed = seg.begin != null && seg.end != null && seg.end > seg.begin;
    if (timed) {
      const btn = el('button', { class: 'seg-play', title: 'Play ' + FS.fmtTime(seg.begin) + '–' + FS.fmtTime(seg.end) }, '▶');
      btn.addEventListener('click', (e) => { e.stopPropagation(); playRange(box, obj, [seg], mediaByGuid, opts, btn); });
      gutter.appendChild(btn);
    }
    row.appendChild(gutter);
    const main = el('div', { class: 'seg-main' });
    const wordRow = el('div', Object.assign({ class: 'word-row' }, vern.rtl ? { dir: 'rtl' } : {}));
    let w = 0;
    // Every word cell carries the SAME rows, in the same order — a row a word has nothing for
    // is an empty placeholder, so the rows stay level across the segment (Seth, 2026-10-13:
    // "if there's a blank cell, then the row beneath it fills it in. We don't want that").
    // Rows no word in the segment has at all are left out.
    const hasLine = (word, line) => line === 'txt' || (line === 'morph' && !!(word.morphs && word.morphs.length)) || (line === 'mgls' && !!(word.morphs && word.morphs.some((m) => m.gls))) || (line === 'cf' && !!(word.morphs && word.morphs.some((m) => m.cf))) || (line === 'gls' && !!word.gls) || (line === 'pos' && !!word.pos);
    const realWords = (seg.words || []).filter((x) => !x.punct);
    const present = lines.filter((line) => ['txt', 'morph', 'mgls', 'cf', 'gls', 'pos'].includes(line) && realWords.some((x) => hasLine(x, line)));
    (seg.words || []).forEach((word) => {
      if (word.punct) {
        wordRow.appendChild(el('div', { class: 'word-cell punct-cell' }, el('div', Object.assign({ class: 'il-line il-txt' }, wsAttrs(vern)), word.txt)));
        return;
      }
      w++;
      const wi = w;                      // this cell's ordinal — captured per cell, not the loop counter
      const cell = el('div', { class: 'word-cell', dataset: { w: wi } });
      const sf = (line) => R.stylesFor(index, seg.n, line, wi);
      const blank = (cls) => el('div', { class: 'il-line il-empty ' + cls, html: '&nbsp;' });
      for (const line of present) {
        if (line === 'txt') cell.appendChild(el('div', Object.assign({ class: 'il-line il-txt', html: styled(word.txt || '', sf('txt')) }, wsAttrs(vern))));
        else if (!hasLine(word, line)) cell.appendChild(blank('il-' + line));
        else if (line === 'morph') cell.appendChild(el('div', Object.assign({ class: 'il-line il-morph', html: styledParts(word.morphs.map((m) => m.form || ''), sf('morph')) }, wsAttrs(vern))));
        else if (line === 'mgls') cell.appendChild(el('div', { class: 'il-line il-mgls', lang: anal.tag || null, html: styledParts(word.morphs.map((m) => m.gls || ''), sf('mgls')) }));
        else if (line === 'cf') cell.appendChild(el('div', { class: 'il-line il-cf', html: styledParts(word.morphs.map((m) => m.cf || ''), sf('cf')) }));
        else if (line === 'gls') cell.appendChild(el('div', { class: 'il-line il-gls', lang: anal.tag || null, html: styled(word.gls, sf('gls')) }));
        else if (line === 'pos') cell.appendChild(el('div', { class: 'il-line il-pos', html: styled(word.pos, sf('pos')) }));
      }
      if (opts.editable) {
        cell.addEventListener('click', (e) => {
          e.stopPropagation();
          const target = { line: 'txt', seg: seg.n, word: wi };
          if (e.shiftKey && sel.anchor && (sel.anchor.seg !== seg.n || sel.anchor.word !== wi)) {
            const a = sel.anchor, b = { seg: seg.n, word: wi };
            const first = (a.seg < b.seg || (a.seg === b.seg && a.word <= b.word)) ? a : b;
            const last = first === a ? b : a;
            const t = { line: 'txt', seg: first.seg, word: first.word, segEnd: last.seg, wordEnd: last.word };
            box.querySelectorAll('.word-cell.sel').forEach((c) => c.classList.remove('sel'));
            stylePopover(cell, spec, t, word, opts, { range: true, box });
            return;
          }
          sel.anchor = { seg: seg.n, word: wi };
          box.querySelectorAll('.word-cell.sel').forEach((c) => c.classList.remove('sel'));
          cell.classList.add('sel');
          // clicked ON a particular line: start the popover there; on one morpheme of a morph
          // line: with that morpheme's characters preselected, so one click styles just it
          const lineEl = e.target.closest('.il-line');
          const extra = { box };
          if (lineEl) {
            const m = /il-(txt|morph|mgls|cf|gls|pos)\b/.exec(lineEl.className);
            if (m) target.line = m[1];
            const part = e.target.closest('.il-line > span');
            if (part && /^(morph|mgls|cf)$/.test(target.line)) {
              const parts = [...lineEl.children];
              const idx = parts.indexOf(part);
              if (idx >= 0) {
                let start = 1;
                for (let i = 0; i < idx; i++) start += FS.graphemes(parts[i].textContent).length + 1;   // + the joining space
                const len = FS.graphemes(part.textContent).length;
                if (len && parts.length > 1) extra.chars = [start, start + len - 1];
              }
            }
          }
          stylePopover(cell, spec, target, word, opts, extra);
        });
      }
      wordRow.appendChild(cell);
    });
    if (!(seg.words || []).length) wordRow.appendChild(el('span', Object.assign({ class: 'il-txt' }, wsAttrs(vern)), seg.baseline || ''));
    main.appendChild(wordRow);
    const lineEl = (cls, line, text) => {
      const d = el('div', { class: cls, lang: anal.tag || null, html: styled(text, R.stylesFor(index, seg.n, line, 0)) });
      if (opts.editable) d.addEventListener('click', (e) => { e.stopPropagation(); stylePopover(d, spec, { line, seg: seg.n }, null, opts, { lineOnly: true, text, box }); });
      return d;
    };
    if (lines.includes('ft') && seg.free) main.appendChild(lineEl('seg-free', 'ft', seg.free));
    if (lines.includes('lit') && seg.lit) main.appendChild(lineEl('seg-lit', 'lit', seg.lit));
    if (lines.includes('note')) for (const n of seg.notes || []) main.appendChild(lineEl('seg-note', 'note', n));
    row.appendChild(main);
    return row;
  }

  /* ------------------------------------------------------------------ audio in a text box */
  async function playRange(box, obj, segs, mediaByGuid, opts, btn) {
    const timed = segs.filter((s) => s.begin != null && s.end != null);
    if (!timed.length) return;
    const begin = Math.min(...timed.map((s) => s.begin)), end = Math.max(...timed.map((s) => s.end));
    const mediaGuid = timed[0].media || (obj.media && obj.media[0] && obj.media[0].guid) || null;
    let info;
    try { info = await FS.api.audio_clip(obj.guid, mediaGuid, begin, end); }
    catch (e) { FS.toast(e.message, 'error'); return; }
    // the cached clip first (exact, local, FLAC/WAV — it is what the example keeps), else the
    // live file; a live file that will not decode falls back to the clip when there is one
    let src = info.fileUrl, offBegin = begin, offEnd = end;
    if (info.clipUrl) { src = info.clipUrl; offBegin = 0; offEnd = end - begin; }
    if (!src) {
      const m = mediaByGuid.get(mediaGuid) || (obj.media && obj.media[0]) || {};
      return mediaMissingPopover(btn || box.querySelector('.flex-head'), m, info, opts);
    }
    const transport = mountTransport(box, begin, end, offBegin, offEnd);
    let capture = null;
    const a = audio.get(src);
    if (info.needsCapture && !FS.isMock()) {
      try { capture = captureClip(a, begin, end, obj.guid); } catch (e) { capture = null; }
    }
    try {
      await audio.play(src, offBegin, offEnd, {
        onTick: (t) => transport.tick(t),
        onEnd: () => { transport.done(); if (btn) btn.classList.remove('playing'); if (captureClip.active) { try { captureClip.active.stop(); } catch (e) { /* ignore */ } captureClip.active = null; } },
      });
      if (btn) btn.classList.add('playing');
      box.querySelectorAll('.seg-play.playing').forEach((b) => { if (b !== btn) b.classList.remove('playing'); });
    } catch (e) {
      transport.remove();
      // the file exists but WebView2 cannot decode it (a format it has no codec for, a broken
      // file): offer a playable copy, keeping FLEx's segment times (Seth, 2026-10-13)
      const m = mediaByGuid.get(mediaGuid) || (obj.media && obj.media[0]) || {};
      if (src !== info.clipUrl && info.clipUrl) { audio.elForSrc.delete(src); return playRange(box, Object.assign({}, obj, { _clipOnly: true }), segs, mediaByGuid, opts, btn); }
      mediaMissingPopover(btn || box.querySelector('.flex-head'), m, info, opts, {
        title: 'Could not play this audio',
        hint: (e.message || String(e)) + ' — the file FLEx names (' + (m.uri || info.path || 'unknown') + ') is there but will not play here. Point the Scratchpad at a playable copy (a WAV, MP3 or FLAC export of the same recording): the segment times stay exactly as FLEx has them, and the slice this example needs is cached with the notebook (FLAC when ffmpeg is installed, see Settings).',
      });
    }
    if (capture) capture.then((r) => { if (r && r.clipUrl) FS.toast('Clip cached in the notebook', 'ok'); });
  }

  function mountTransport(box, begin, end, offBegin, offEnd) {
    box.querySelectorAll('.transport').forEach((t) => t.remove());
    const bar = el('div', { class: 'bar' }, el('i'));
    const time = el('span', { class: 't' }, '0:00.0 / ' + FS.fmtTime(end - begin));
    const playBtn = el('button', { class: 'on', title: 'Pause' }, '❚❚');
    const loopBtn = el('button', { title: 'Loop' }, '↻');
    const t = el('div', { class: 'transport' }, playBtn, loopBtn, bar, time,
      el('span', { class: 'muted small' }, FS.fmtTime(begin) + '–' + FS.fmtTime(end)));
    box.appendChild(t);
    let paused = false, finished = false;
    playBtn.addEventListener('click', () => {
      if (finished) { box.querySelector('.seg-play') && box.querySelector('.seg-play').click(); return; }
      if (paused) { audio.resume(); playBtn.textContent = '❚❚'; playBtn.classList.add('on'); }
      else { audio.pause(); playBtn.textContent = '▶'; playBtn.classList.remove('on'); }
      paused = !paused;
    });
    loopBtn.addEventListener('click', () => { if (audio.current) { audio.current.loop = !audio.current.loop; loopBtn.classList.toggle('on', audio.current.loop); } });
    bar.addEventListener('click', (e) => { const r = bar.getBoundingClientRect(); const f = (e.clientX - r.left) / r.width; audio.seek(offBegin + f * (offEnd - offBegin)); });
    return {
      tick(tm) { const f = Math.min(1, Math.max(0, (tm - offBegin) / (offEnd - offBegin))); bar.firstChild.style.width = (f * 100) + '%'; time.textContent = FS.fmtTime(tm - offBegin) + ' / ' + FS.fmtTime(end - begin); },
      done() { finished = true; playBtn.textContent = '▶'; playBtn.classList.remove('on'); bar.firstChild.style.width = '100%'; setTimeout(() => { if (finished && t.isConnected) t.remove(); }, 4000); },
      remove() { t.remove(); },
    };
  }

  function mediaMissingPopover(anchor, m, info, opts, how) {
    how = how || {};
    FS.popover(anchor, (pop, close) => {
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, how.title || 'Media file not found')));
      pop.appendChild(el('div', { class: 'hint' }, how.hint || ('FLEx names it ' + (m.uri || '(no file)') + '. Point the Scratchpad at the real file; the choice is remembered for this notebook.')));
      if (info && info.clipUrl) pop.appendChild(el('div', { class: 'hint' }, 'A cached clip exists and will be used.'));
      pop.appendChild(el('hr'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: async () => { close(); try { const r = await FS.api.audio_browse_media(m.guid || ''); if (r) { audio.stop(); audio.elForSrc.clear(); invalidate(); FS.toast('Media file set', 'ok'); opts.refresh && opts.refresh(); } } catch (e) { FS.toast(e.message, 'error'); } } }, how.title ? 'Browse for a playable copy…' : 'Browse for the audio file…'));
    });
  }

  function openInFlex(url) {
    FS.api.open_in_flex(url).then(() => FS.toast('Sent to FieldWorks'), (e) => FS.toast(e.message, 'error'));
  }

  /* ------------------------------------------------------------------ popovers */
  const HL_COLORS = ['', '#ffd6a5', '#caffbf', '#9bf6ff', '#bdb2ff', '#ffadad', '#fdffb6'];
  const TXT_COLORS = ['#c0392b', '#1f7a4d', '#1f4f8f', '#7a3e9d', '#b45309'];

  function stylePopover(anchor, spec, target, word, opts, extra) {
    extra = extra || {};
    FS.popover(anchor, (pop, close) => {
      const state = { line: target.line || 'txt', chars: extra.chars || null, color: '' };
      const apply = (style, color) => {
        const t = Object.assign({}, target, { line: state.line });
        if (state.chars) t.chars = state.chars;
        R.toggleStyle(spec, t, style, color || '');
        opts.onSpecChange && opts.onSpecChange(spec);
        refresh();
      };
      const has = (style, color) => {
        const t = Object.assign({}, target, { line: state.line });
        if (state.chars) t.chars = state.chars;
        return R.hasStyle(spec, t, style, color == null ? undefined : color);
      };
      const rows = el('div');
      function refresh() {
        rows.innerHTML = '';
        const desc = extra.range ? 'Words ' + target.seg + '.' + target.word + ' – ' + target.segEnd + '.' + target.wordEnd
          : extra.lineOnly ? ({ ft: 'Free translation', lit: 'Literal translation', note: 'Note' }[target.line] || target.line) + ' of segment ' + target.seg
            : (word ? '“' + (word.txt || '') + '”  (' + target.seg + '.' + target.word + ')' : 'segment ' + target.seg);
        rows.appendChild(el('div', { class: 'row' }, el('b', {}, desc)));
        if (!extra.lineOnly) {
          const sel = el('select', { onchange: (e) => { state.line = e.target.value; state.chars = null; refresh(); } });
          const names = { txt: 'Word', morph: 'Morphemes', mgls: 'Morph gloss', cf: 'Lex. entries', gls: 'Word gloss', pos: 'Category' };
          for (const l of ['txt', 'morph', 'mgls', 'gls', 'pos', 'cf']) sel.appendChild(el('option', { value: l, selected: l === state.line }, names[l]));
          rows.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Line'), sel));
        }
        const hlRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Highlight'));
        for (const c of HL_COLORS) hlRow.appendChild(el('button', { class: 'sw' + (has('hl', c) ? ' on' : ''), style: { background: c || 'var(--hl)' }, title: c || 'default', onclick: () => apply('hl', c) }));
        rows.appendChild(hlRow);
        const tRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Style'));
        for (const [st, label] of [['b', 'Bold'], ['u', 'Underline'], ['i', 'Italic'], ['s', 'Strike']]) tRow.appendChild(el('button', { class: 'tog' + (has(st, '') ? ' on' : ''), onclick: () => apply(st, '') }, label));
        rows.appendChild(tRow);
        const cRow = el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Colour'));
        for (const c of TXT_COLORS) cRow.appendChild(el('button', { class: 'sw' + (has('color', c) ? ' on' : ''), style: { background: c }, onclick: () => apply('color', c) }));
        rows.appendChild(cRow);
        if (!extra.range) {
          const text = extra.lineOnly ? (extra.text || '') : (word ? R.lineTextOfWord(word, state.line) : '');
          const n = FS.graphemes(text).length;
          const from = el('input', { type: 'number', min: 1, max: n, value: state.chars ? state.chars[0] : 1, style: { width: '56px' } });
          const to = el('input', { type: 'number', min: 1, max: n, value: state.chars ? state.chars[1] : n, style: { width: '56px' } });
          const setChars = () => { const a = +from.value || 1, b = +to.value || n; state.chars = (a === 1 && b >= n) ? null : [Math.min(a, b), Math.max(a, b)]; refresh(); };
          from.addEventListener('change', setChars); to.addEventListener('change', setChars);
          rows.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Characters'), from, el('span', { class: 'muted' }, '–'), to, el('span', { class: 'muted small' }, 'of ' + n)));
          const match = el('input', { type: 'text', placeholder: 'match text… e.g. ka-', style: { width: '120px' } });
          const all = el('input', { type: 'checkbox', title: 'all occurrences' });
          const matchBtn = el('button', { class: 'tog', onclick: () => { if (!match.value) return; const t = { line: state.line, text: match.value, all: all.checked }; R.toggleStyle(spec, t, 'hl', state.color); opts.onSpecChange && opts.onSpecChange(spec); close(); } }, 'Highlight match');
          rows.appendChild(el('div', { class: 'row' }, match, el('label', { class: 'small muted' }, all, ' all'), matchBtn));
        }
        rows.appendChild(el('hr'));
        rows.appendChild(el('div', { class: 'row' },
          el('button', { class: 'tog', onclick: () => { const t = Object.assign({}, target, { line: state.line }); if (state.chars) t.chars = state.chars; R.clearStyles(spec, t); opts.onSpecChange && opts.onSpecChange(spec); refresh(); } }, 'Clear this'),
          el('button', { class: 'tog', onclick: () => { R.clearStyles(spec, null); opts.onSpecChange && opts.onSpecChange(spec); close(); } }, 'Clear all styles'),
          el('span', { class: 'hint' }, extra.range ? '' : 'Shift+click another word to style a range.')));
      }
      refresh();
      pop.appendChild(rows);
    }, { onClose: () => { if (extra.box) extra.box.querySelectorAll('.word-cell.sel').forEach((c) => c.classList.remove('sel')); } });
  }

  function embedMenu(anchor, spec, opts, obj) {
    FS.popover(anchor, (pop, close) => {
      // A short label of the author's own: shown on the chip when collapsed and as a badge
      // when expanded (`"label"` at the end of the embed line).
      const label = el('input', { type: 'text', value: spec.label || '', placeholder: 'e.g. causative example 3', style: { width: '200px' } });
      label.addEventListener('change', () => { spec.label = label.value.trim(); opts.onSpecChange && opts.onSpecChange(spec); });
      label.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); label.blur(); close(); } });
      pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Label'), label));
      if (spec.kind === 'text' && obj && obj.titleAlternatives && Object.keys(obj.titleAlternatives).length > 1) {
        const sel = el('select', { style: { width: '200px' } });
        sel.appendChild(el('option', { value: '' }, 'default'));
        for (const [tag, title] of Object.entries(obj.titleAlternatives)) sel.appendChild(el('option', { value: tag, selected: !!(spec.ws && spec.ws.title === tag) }, title + '  (' + tag + ')'));
        sel.addEventListener('change', () => { spec.ws = spec.ws || {}; if (sel.value) spec.ws.title = sel.value; else delete spec.ws.title; if (!Object.keys(spec.ws).length) spec.ws = null; opts.onSpecChange && opts.onSpecChange(spec); });
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Title'), sel));
      }
      pop.appendChild(el('hr'));
      if (spec.kind === 'entry' || spec.kind === 'sense') {
        // Entries pick FIELDS, not interlinear lines (Seth, 2026-10-13: "fine-tune which
        // fields (including senses and sub senses) we want to include instead of IGT fields")
        const fnames = { cf: 'Citation form', lf: 'Lexeme form', mt: 'Morph type', hn: 'Homograph number', note: 'Entry note', sn: 'Sense numbers', spos: 'Category (per sense)', gl: 'Gloss', def: 'Definition', ex: 'Examples', tr: 'Example translations', sub: 'Sub-senses', snote: 'Sense notes', sem: 'Semantic domains' };
        const cur = new Set(R.entryFields(spec));
        const groups = [['Entry', ['cf', 'lf', 'mt', 'hn', 'note']], ['Senses', ['sn', 'spos', 'gl', 'def', 'ex', 'tr', 'sub', 'snote', 'sem']]];
        for (const [title, keys] of groups) {
          pop.appendChild(el('div', { class: 'row' }, el('b', {}, title + ' fields')));
          for (const k of keys) {
            const cb = el('input', { type: 'checkbox', checked: cur.has(k) });
            cb.addEventListener('change', () => { cb.checked ? cur.add(k) : cur.delete(k); spec.fields = R.ENTRY_FIELDS.filter((x) => cur.has(x)); opts.onSpecChange && opts.onSpecChange(spec); });
            pop.appendChild(el('label', { class: 'row', style: { gap: '8px' } }, cb, fnames[k]));
          }
        }
        const sensesIn = el('input', { type: 'text', value: (spec.senses || []).join(', '), placeholder: 'all — or 1, 2.1, 3', style: { width: '160px' }, title: 'Which senses to show, by FLEx number; blank = all' });
        sensesIn.addEventListener('change', () => { const v = sensesIn.value.split(/[,\s]+/).map((x) => x.trim()).filter((x) => /^\d+(\.\d+)*$/.test(x)); spec.senses = v.length ? v : null; opts.onSpecChange && opts.onSpecChange(spec); });
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Senses'), sensesIn));
        if (obj && (obj.senses || []).length) pop.appendChild(el('div', { class: 'hint' }, 'This entry has: ' + obj.senses.map((x) => x.number + (x.gloss ? ' ' + x.gloss : '')).join(' · ')));
        pop.appendChild(el('hr'));
      } else {
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Lines to show')));
        const names = { txt: 'Word', morph: 'Morphemes', mgls: 'Morph glosses', cf: 'Lex. entries', gls: 'Word gloss', pos: 'Category', ft: 'Free translation', lit: 'Literal translation', note: 'Notes' };
        const current = spec.lines && spec.lines.length ? spec.lines : R.DEFAULT_LINES;
        for (const l of R.LINES) {
          const cb = el('input', { type: 'checkbox', checked: current.includes(l) });
          cb.addEventListener('change', () => {
            const set = new Set(current);
            cb.checked ? set.add(l) : set.delete(l);
            spec.lines = R.LINES.filter((x) => set.has(x));
            opts.onSpecChange && opts.onSpecChange(spec);
          });
          pop.appendChild(el('label', { class: 'row', style: { gap: '8px' } }, cb, names[l]));
        }
        pop.appendChild(el('hr'));
      }
      if (spec.kind === 'text' && obj && obj.wsOptions) {
        // Which writing system each line shows. FLEx keeps every alternative on each string;
        // the text's own vernacular WS and the default analysis WS are the defaults.
        pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Writing systems')));
        const vern = obj.wsOptions.vernacular || [], anal = obj.wsOptions.analysis || [];
        const detected = (obj.wsDetected && obj.wsDetected.tag) || '';
        const wsNames = { txt: 'Word', morph: 'Morphemes', cf: 'Lex. entries', gls: 'Word gloss', mgls: 'Morph gloss', pos: 'Category', ft: 'Free', lit: 'Literal', note: 'Notes' };
        for (const line of ['txt', 'morph', 'cf', 'gls', 'mgls', 'pos', 'ft', 'lit', 'note']) {
          const isVern = ['txt', 'morph', 'cf'].includes(line);
          const options = isVern ? vern : anal;
          if (!options.length) continue;
          const sel = el('select', { style: { width: '150px' } });
          sel.appendChild(el('option', { value: '' }, isVern ? ('text’s own' + (detected ? ' (' + detected + ')' : '')) : 'default'));
          for (const w of options) sel.appendChild(el('option', { value: w.tag, selected: !!(spec.ws && spec.ws[line] === w.tag) }, (w.name || w.tag) + (w.name && w.name !== w.tag ? '  ' + w.tag : '')));
          sel.addEventListener('change', () => {
            spec.ws = spec.ws || {};
            if (sel.value) spec.ws[line] = sel.value; else delete spec.ws[line];
            if (!Object.keys(spec.ws).length) spec.ws = null;
            opts.onSpecChange && opts.onSpecChange(spec);
          });
          pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, wsNames[line]), sel));
        }
        pop.appendChild(el('hr'));
      }
      if (spec.kind === 'text') {
        // FLEx's numbers (4.1), as in its Gloss / Print views; the running count is accepted too
        const cur = spec.seg || (obj && obj.range) || [1, (obj && obj.segmentCount) || 1];
        const a = el('input', { type: 'text', value: labelOf(obj, cur[0]), style: { width: '60px' }, title: 'First segment — FLEx number (4.1) or running count' });
        const b = el('input', { type: 'text', value: labelOf(obj, cur[1]), style: { width: '60px' }, title: 'Last segment — FLEx number (4.1) or running count' });
        const set = () => {
          const x = numberFor(obj, a.value, cur[0]), y = numberFor(obj, b.value, cur[1]);
          spec.seg = [Math.min(x, y), Math.max(x, y)];
          const at = (n) => { const e = obj && obj.index && obj.index.find((i) => i.n === n); return e ? e.guid.replace(/-/g, '').slice(-12) : ''; };
          spec.at = at(spec.seg[0]) ? [at(spec.seg[0]), at(spec.seg[1]) || at(spec.seg[0])] : null;
          opts.onSpecChange && opts.onSpecChange(spec);
        };
        a.addEventListener('change', set); b.addEventListener('change', set);
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Segments'), a, el('span', { class: 'muted' }, '–'), b, el('span', { class: 'small muted' }, 'FLEx numbers')));
        pop.appendChild(el('hr'));
      }
      if (opts.layout) {
        // Numbered, indented examples in body text (Seth, 2026-10-13): `ex` numbers the block
        // as (1), (2)… through the note; `indent=N` steps it in like a list level.
        const x = spec.extra = spec.extra || {};
        const cb = el('input', { type: 'checkbox', checked: !!x.ex });
        cb.addEventListener('change', () => { if (cb.checked) x.ex = true; else delete x.ex; opts.onSpecChange && opts.onSpecChange(spec); });
        pop.appendChild(el('label', { class: 'row', style: { gap: '8px' } }, cb, 'Number as example (1), (2)…'));
        const lvl = () => Math.max(0, Math.min(4, parseInt(x.indent, 10) || 0));
        const show = el('span', { class: 'muted small' }, 'level ' + lvl());
        const step = (d) => { const n = Math.max(0, Math.min(4, lvl() + d)); if (n) x.indent = String(n); else delete x.indent; show.textContent = 'level ' + n; opts.onSpecChange && opts.onSpecChange(spec); };
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Indent'), el('button', { class: 'btn small', title: 'Outdent (Shift+Tab on the block)', onclick: () => step(-1) }, '◂'), el('button', { class: 'btn small', title: 'Indent (Tab on the block)', onclick: () => step(1) }, '▸'), show));
        pop.appendChild(el('hr'));
      }
      if (obj && obj.url) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(obj.url); FS.toast('FLEx link copied'); close(); } }, 'Copy FLEx link'));
      if (spec.kind === 'text') pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); openContext(spec, obj); } }, 'View in context (whole text)'));
      if (spec.kind === 'text' && obj && obj.kind === 'text') pop.appendChild(el('button', { class: 'menu-item', title: 'The rows FLEx itself puts on the clipboard (Word / Morphemes / Lex. Gloss / Free …), one block per segment, the lines this example shows', onclick: () => { FS.copyText(flexTsv(spec, obj)); FS.toast('Copied as FLEx TSV'); close(); } }, 'Copy as FLEx TSV'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(R.serialize(spec)); FS.toast('Embed code copied'); close(); } }, 'Copy embed code'));
      if (opts.editSource) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); opts.editSource(); } }, 'Edit source'));
      if (opts.duplicate || opts.remove) pop.appendChild(el('hr'));
      if (opts.duplicate) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); opts.duplicate(); } }, 'Duplicate this object'));
      if (opts.remove) pop.appendChild(el('button', { class: 'menu-item danger', onclick: () => { close(); removeObject(anchor, spec, opts); } }, 'Remove this object…'));
    });
  }
  /* The example as FLEx copies it from its interlinear view (Seth, 2026-10-13: "As FLEx TSV.
   * Just like if I copied it directly from FLEx"): per segment one row per interlinear line,
   * FLEx's row label first, one cell per word (a word's morphemes space-separated in its
   * cell, punctuation as its own cell on the Word row), the free translation as a Free row;
   * segments separated by a blank line. Only the lines this example shows, in its order. */
  const TSV_LABELS = { txt: 'Word', morph: 'Morphemes', cf: 'Lex. Entries', mgls: 'Lex. Gloss', gls: 'Word Gloss', pos: 'Word Cat.', ft: 'Free', lit: 'Literal', note: 'Note' };
  function flexTsv(spec, obj) {
    const lines = spec.lines && spec.lines.length ? spec.lines : R.DEFAULT_LINES;
    const cell = (v) => String(v == null ? '' : v).replace(/[\t\r\n]+/g, ' ');
    const out = [];
    for (const seg of obj.segments || []) {
      const words = seg.words || [];
      const block = [];
      for (const line of lines) {
        if (line === 'ft' || line === 'lit' || line === 'note') continue;
        const cells = words.map((w) => {
          if (w.punct) return line === 'txt' ? w.txt : '';
          if (line === 'txt') return w.txt || '';
          if (line === 'morph') return (w.morphs || []).map((m) => m.form || '').join(' ');
          if (line === 'mgls') return (w.morphs || []).map((m) => m.gls || '').join(' ');
          if (line === 'cf') return (w.morphs || []).map((m) => m.cf || '').join(' ');
          if (line === 'gls') return w.gls || '';
          if (line === 'pos') return w.pos || '';
          return '';
        });
        if (line !== 'txt' && !cells.some((c) => c)) continue;
        block.push([TSV_LABELS[line] || line, ...cells.map(cell)].join('\t'));
      }
      if (lines.includes('ft') && seg.free) block.push('Free\t' + cell(seg.free));
      if (lines.includes('lit') && seg.lit) block.push('Literal\t' + cell(seg.lit));
      if (lines.includes('note')) for (const n of seg.notes || []) block.push('Note\t' + cell(n));
      out.push(block.join('\n'));
    }
    return out.join('\n\n') + '\n';
  }

  /* Remove, after an in-place confirmation (Seth, 2026-10-13: "for delete, it should ask"). */
  async function removeObject(anchor, spec, opts) {
    const what = spec.label || (spec.kind === 'text' ? 'this example' : spec.kind === 'entry' || spec.kind === 'sense' ? 'this entry' : 'this object');
    if (await FS.confirmAt(anchor, 'Remove ' + what + ' from the note? (Undo brings it back.)', 'Remove')) { closeOverlay(); opts.remove(); }
  }

  /* ------------------------------------------------------------------ rendering: entry */
  function renderEntry(obj, spec, opts) {
    const vern = (obj.ws && obj.ws.vern) || {}, anal = (obj.ws && obj.ws.anal) || {};
    const box = el('div', { class: 'flex-obj entry-card' + (obj.cached ? ' cached' : '') });
    const hw = el('span', Object.assign({ class: 'headword' }, wsAttrs(vern)), obj.headword || obj.lexemeForm || '?');
    if (obj.homograph) hw.appendChild(el('sub', {}, String(obj.homograph)));
    const F = new Set(R.entryFields(spec));
    const head = el('div', { class: 'flex-head' + (opts.inCell ? ' compact' : '') }, hw);
    if (!F.has('hn')) hw.querySelectorAll('sub').forEach((x) => x.remove());
    if (F.has('cf') && obj.citationForm && obj.citationForm !== obj.headword && obj.citationForm !== obj.lexemeForm) head.appendChild(el('span', Object.assign({ class: 'ecf', title: 'citation form' }, wsAttrs(vern)), obj.citationForm));
    if (F.has('lf') && obj.lexemeForm && obj.lexemeForm !== obj.headword) head.appendChild(el('span', Object.assign({ class: 'ecf', title: 'lexeme form' }, wsAttrs(vern)), obj.lexemeForm));
    if (F.has('mt') && obj.morphType) head.appendChild(el('span', { class: 'mtype' }, obj.morphType));
    if (spec.label) head.appendChild(el('span', { class: 'badge' }, spec.label));
    if (obj.cached) head.appendChild(el('span', { class: 'badge warn', title: obj.liveError || '' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')));
    head.appendChild(el('span', { class: 'spacer' }));
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
    if (opts.editable && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Collapse to a chip', onclick: () => setCollapsed(spec, opts, true) }, '⤡'));
    if (opts.editable && opts.inCell && opts.editCell && !opts.overlay) head.appendChild(el('button', { class: 'lnk', title: 'Edit the cell\u2019s text', onclick: () => opts.editCell() }, '✎'));
    if (opts.editable && !opts.overlay && opts.duplicate) head.appendChild(el('button', { class: 'lnk', title: 'Duplicate this object', onclick: () => opts.duplicate() }, '⧉'));
    if (opts.editable && !opts.overlay && opts.remove) head.appendChild(el('button', { class: 'lnk danger', title: 'Remove this object…', onclick: (e) => removeObject(e.currentTarget, spec, opts) }, '🗑'));
    if (obj.url) head.appendChild(el('a', { href: obj.url, onclick: (e) => { e.preventDefault(); openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    if (opts.editable) head.appendChild(el('button', { class: 'lnk', title: 'Options', onclick: (e) => embedMenu(e.currentTarget, spec, opts, obj) }, '⋯'));
    box.appendChild(head);
    if (F.has('note') && obj.note) box.appendChild(el('div', { class: 'enote' }, obj.note));
    const shown = R.visibleSenses(spec, obj.senses);
    for (const s of shown) {
      const focus = spec.kind === 'sense' && s.guid === spec.guid;
      const line = el('div', {});
      if (F.has('spos') && s.pos) line.appendChild(el('span', { class: 'pos' }, s.pos));
      if (F.has('gl')) line.appendChild(el('span', { class: 'gl', lang: anal.tag || null }, s.gloss || ''));
      if (F.has('def') && s.definition && (s.definition !== s.gloss || !F.has('gl'))) line.appendChild(el('span', { class: 'def' }, (F.has('gl') && s.gloss ? ' — ' : '') + s.definition));
      const body = el('div', { style: { flex: 1 } }, line);
      if (F.has('sem') && (s.domains || []).length) body.appendChild(el('div', { class: 'sem' }, s.domains.join('; ')));
      if (F.has('ex')) for (const ex of s.examples || []) body.appendChild(el('div', { class: 'ex' }, el('span', Object.assign({ class: 'v' }, wsAttrs(vern)), ex.text || ''), F.has('tr') && ex.translation ? el('span', {}, '  ‘' + ex.translation + '’') : null));
      if (F.has('snote') && s.note) body.appendChild(el('div', { class: 'snote' }, s.note));
      const sd = el('div', { class: 'sense level' + Math.min(3, s.level || 0) + (focus ? ' focus' : '') },
        el('span', { class: 'sn' }, F.has('sn') ? (s.number || '') : ''), body);
      box.appendChild(sd);
    }
    if (!(obj.senses || []).length) box.appendChild(el('div', { class: 'seg-empty' }, 'No senses.'));
    else if (!shown.length) box.appendChild(el('div', { class: 'seg-empty' }, 'No sense selected (⋯ → Senses).'));
    return box;
  }

  function renderWordform(obj, spec, opts) {
    const vern = (obj.ws && obj.ws.vern) || {};
    const box = el('div', { class: 'flex-obj wordform-card' + (obj.cached ? ' cached' : '') });
    const head = el('div', { class: 'flex-head' }, el('span', Object.assign({ class: 'wf' }, wsAttrs(vern)), obj.form || '?'), el('span', { class: 'badge' }, 'wordform'), el('span', { class: 'spacer' }));
    if (obj.url) head.appendChild(el('a', { href: obj.url, onclick: (e) => { e.preventDefault(); openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    box.appendChild(head);
    box.appendChild(el('div', { class: 'il-gls' }, (obj.glosses || []).join('; ') || '(no glosses)'));
    if (obj.pos && obj.pos.length) box.appendChild(el('div', { class: 'il-pos' }, obj.pos.join(', ')));
    return box;
  }

  /* ------------------------------------------------------------------ an example in its context
   * (Seth, 2026-10-13): the WHOLE text in a modal, scrolled to the example's range, the range
   * set off from the rest so it is not lost while scrolling. The backend pages texts (60
   * segments a call), so the text is fetched in pages and stitched. The example's own styles
   * still apply (they address segment numbers), nothing is editable here. */
  async function wholeText(guid, ws, first) {
    const PAGE = 60;
    let a = 1, all = null;
    for (;;) {
      const part = await flexGet('text', guid, a, a + PAGE - 1, false, ws || null, null);
      if (!all) all = Object.assign({}, part, { segments: [] });
      all.segments.push(...(part.segments || []));
      const total = part.segmentCount || first.segmentCount || all.segments.length;
      a += PAGE;
      if (!(part.segments || []).length || a > total) break;
    }
    all.range = all.segments.length ? [all.segments[0].n, all.segments[all.segments.length - 1].n] : null;
    return all;
  }
  function openContext(spec, obj) {
    const range = spec.seg || (obj && obj.range) || null;
    const m = FS.modal({ title: (obj && obj.title ? obj.title : 'Text') + ' — in context', class: 'context' });
    m.body.appendChild(el('div', { class: 'flex-loading' }, 'Loading the whole text…'));
    const full = Object.assign({}, spec, { seg: null, at: null, extra: {} });
    wholeText(spec.guid, spec.ws, obj || {}).then((text) => {
      m.body.innerHTML = '';
      const segs = text.segments || [];
      const inRange = (n) => !!range && n >= range[0] && n <= range[1];
      const host = el('div', { class: 'context-text' });
      host.appendChild(renderText(text, full, { editable: false, context: true }));
      const rows = [...host.querySelectorAll('.segment[data-n]')].filter((r) => inRange(+r.dataset.n));
      rows.forEach((r, i) => { r.classList.add('in-focus'); if (i === 0) r.classList.add('first'); if (i === rows.length - 1) r.classList.add('last'); });
      const label = range ? (range[0] === range[1] ? 'segment ' + labelOf(text, range[0]) : 'segments ' + labelOf(text, range[0]) + '–' + labelOf(text, range[1])) : 'the whole text';
      const back = () => { if (rows[0]) rows[0].scrollIntoView({ block: 'center', behavior: 'smooth' }); };
      const bar = el('div', { class: 'context-bar' },
        el('span', { class: 'ctx-mark' }), el('span', {}, 'This example: ' + label + ' of ' + segs.length),
        el('span', { class: 'spacer' }),
        rows.length ? el('button', { class: 'lnk', onclick: back }, '⌖ Back to the example') : null,
        el('button', { class: 'lnk', title: 'Copy the whole text as FLEx TSV', onclick: () => { FS.copyText(flexTsv(full, text)); FS.toast('Copied as FLEx TSV'); } }, '⎘ TSV'),
        text.url ? el('a', { href: text.url, onclick: (e) => { e.preventDefault(); openInFlex(text.url); } }, 'Open in FLEx ↗') : null);
      m.body.append(bar, host);
      if (rows[0]) requestAnimationFrame(() => rows[0].scrollIntoView({ block: 'center' }));
    }).catch((e) => { m.body.innerHTML = ''; m.body.appendChild(el('div', { class: 'flex-err' }, 'Could not load the text. ', el('span', { class: 'hint' }, e.message || String(e)))); });
    return m;
  }

  /* ------------------------------------------------------------------ collapsed chips + overlay
   * A block embed is expanded unless it carries the `collapsed` flag; an embed inside a table
   * cell is a chip unless it carries `expanded`. Both flags live in the embed line, so the
   * layout is saved with the note. A chip expands in place with its ⤢ button; clicking the
   * chip opens a floating overlay (no layout change), and so does hovering it for a moment. */
  function isCollapsed(spec, opts) {
    if (opts.force) return false;
    const x = spec.extra || {};
    return opts.inCell ? !x.expanded : !!x.collapsed;
  }
  function setCollapsed(spec, opts, collapsed) {
    spec.extra = spec.extra || {};
    if (opts.inCell) { if (collapsed) delete spec.extra.expanded; else spec.extra.expanded = true; }
    else { if (collapsed) spec.extra.collapsed = true; else delete spec.extra.collapsed; }
    opts.onSpecChange && opts.onSpecChange(spec);
  }
  function chipTitle(spec, obj) {
    if (spec.label) return spec.label;
    if (!obj) return spec.kind + ' ' + spec.guid.slice(0, 8) + '…';
    if (obj.kind === 'entry') {
      if (spec.kind === 'sense') { const sn = (obj.senses || []).find((x) => x.guid === spec.guid); if (sn) return (obj.headword || '') + ' ' + (sn.number ? sn.number + '. ' : '') + (sn.gloss || ''); }
      return (obj.headword || obj.lexemeForm || '?') + (obj.senses && obj.senses[0] && obj.senses[0].gloss ? ' ‘' + obj.senses[0].gloss + '’' : '');
    }
    if (obj.kind === 'wordform') return obj.form || '?';
    return obj.title || '(untitled text)';
  }
  function chipRange(spec, obj) {
    if (spec.kind !== 'text') return '';
    const r = spec.seg || (obj && obj.range) || null;
    if (!r) return 'all';
    return r[0] === r[1] ? labelOf(obj, r[0]) : labelOf(obj, r[0]) + '–' + labelOf(obj, r[1]);
  }

  function renderChip(container, spec, opts) {
    container.innerHTML = '';
    const icon = spec.kind === 'text' ? '¶' : spec.kind === 'wordform' ? 'ω' : '📖';
    const chip = el('span', { class: 'flex-collapsed kind-' + spec.kind, tabindex: 0, title: 'Click to preview; ⤡ to expand' });
    const ttl = el('span', { class: 'cttl' }, chipTitle(spec, null));
    chip.appendChild(el('span', { class: 'cicon' }, icon));
    chip.appendChild(ttl);
    const range = chipRange(spec, null);
    const rangeEl = el('span', { class: 'crange' }, range);
    if (spec.kind === 'text') chip.appendChild(rangeEl);
    if (opts.editable) chip.appendChild(el('button', { class: 'cexp', title: opts.inCell ? 'Show the full example in this cell' : 'Expand in place', onclick: (e) => { e.stopPropagation(); closeOverlay(); setCollapsed(spec, opts, false); } }, '⤢'));
    container.appendChild(chip);
    // fill the title from the (cached) object without blocking the chip
    const kind = spec.kind === 'sense' ? 'entry' : spec.kind;
    flexGet(kind, spec.guid, spec.kind === 'text' && spec.seg ? spec.seg[0] : null, spec.kind === 'text' && spec.seg ? spec.seg[1] : null, false, null, spec.kind === 'text' ? spec.at : null)
      .then((obj) => { if (syncAnchors(spec, obj, opts)) return; ttl.textContent = chipTitle(spec, obj); rangeEl.textContent = chipRange(spec, obj); const ws = obj.ws && obj.ws.vern; if (ws && obj.kind !== 'wordform') { if (ws.rtl) ttl.dir = 'rtl'; if (ws.tag) ttl.lang = ws.tag; } if (obj.cached) chip.classList.add('cached'); })
      .catch((e) => { chip.classList.add('err'); chip.title = e.message || String(e); });
    // click → pinned overlay; hover → temporary overlay
    chip.addEventListener('click', (e) => { if (e.target.closest('.cexp')) return; openOverlay(chip, spec, opts, { pinned: true }); });
    chip.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openOverlay(chip, spec, opts, { pinned: true }); } });
    let hoverTimer = null;
    chip.addEventListener('mouseenter', () => { if (overlay.current && overlay.current.pinned) return; hoverTimer = setTimeout(() => openOverlay(chip, spec, opts, { pinned: false }), 380); });
    chip.addEventListener('mouseleave', () => { clearTimeout(hoverTimer); scheduleHoverClose(); });
    return chip;
  }

  const overlay = { current: null, closeTimer: null };
  function closeOverlay() {
    const o = overlay.current;
    if (!o) return;
    overlay.current = null;
    clearTimeout(overlay.closeTimer);
    if (o.cleanup) o.cleanup();
    o.node.remove();
    document.removeEventListener('mousedown', o.onDown, true);
    document.removeEventListener('keydown', o.onKey, true);
  }
  function scheduleHoverClose() {
    const o = overlay.current;
    if (!o || o.pinned) return;
    clearTimeout(overlay.closeTimer);
    overlay.closeTimer = setTimeout(() => {
      const oo = overlay.current;
      if (!oo || oo.pinned || oo.hovering || document.querySelector('.popover')) return;
      closeOverlay();
    }, 320);
  }
  /* The floating preview of a collapsed embed: full rendering, editable (styles save back),
   * positioned near the chip, never changing the note's layout. */
  function openOverlay(anchor, spec, opts, mode) {
    if (overlay.current && (overlay.current.anchor === anchor || overlay.current.home === anchor.parentElement)) {
      if (mode.pinned) overlay.current.pinned = true;
      return overlay.current.node;
    }
    closeOverlay();
    const node = el('div', { class: 'flex-overlay' + (mode.pinned ? ' pinned' : '') });
    const inner = el('div', { class: 'flex-overlay-inner' });
    const bar = el('div', { class: 'flex-overlay-bar' },
      el('span', { class: 'muted small' }, mode.pinned ? 'Preview' : 'Preview — click the chip to keep it open'),
      el('span', { class: 'spacer' }),
      opts.editable && opts.editCell ? el('button', { class: 'lnk', title: 'Edit the cell\u2019s text (type before or after this example, add another)', onclick: () => { closeOverlay(); opts.editCell(); } }, '✎ Edit cell') : null,
      opts.editable && opts.editInline ? el('button', { class: 'lnk', title: 'Show the embed code in the text so it can be edited', onclick: () => { closeOverlay(); opts.editInline(); } }, '✎ Edit code') : null,
      spec.kind === 'text' ? el('button', { class: 'lnk', title: 'See this example in its context: the whole text, scrolled to it', onclick: () => { closeOverlay(); openContext(spec, inner._obj || null); } }, '⊡ Context') : null,
      spec.kind === 'text' ? el('button', { class: 'lnk', title: 'Copy as FLEx TSV', onclick: () => { const o = inner._obj; if (o) { FS.copyText(flexTsv(spec, o)); FS.toast('Copied as FLEx TSV'); } } }, '⎘ TSV') : null,
      opts.editable && opts.duplicate ? el('button', { class: 'lnk', title: 'Duplicate this object', onclick: () => { closeOverlay(); opts.duplicate(); } }, '⧉ Duplicate') : null,
      opts.editable && opts.remove ? el('button', { class: 'lnk danger', title: 'Remove this object…', onclick: (e) => removeObject(e.currentTarget, spec, opts) }, '🗑 Remove') : null,
      opts.editable ? el('button', { class: 'lnk', onclick: () => { closeOverlay(); if (opts.expandInline) opts.expandInline(); else setCollapsed(spec, opts, false); } }, opts.inCell ? '⤢ Show in cell' : '⤢ Expand in note') : null,
      el('button', { class: 'lnk', onclick: () => closeOverlay() }, '✕'));
    node.append(bar, inner);
    document.body.appendChild(node);
    const o = { node, anchor, home: anchor.parentElement, pinned: !!mode.pinned, hovering: false, find: opts.findAnchor || null };
    o.onDown = (e) => { if (!node.contains(e.target) && !(o.anchor && o.anchor.contains(e.target)) && !e.target.closest('.popover, .modal')) closeOverlay(); };
    o.onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeOverlay(); } };
    document.addEventListener('mousedown', o.onDown, true);
    document.addEventListener('keydown', o.onKey, true);
    node.addEventListener('mouseenter', () => { o.hovering = true; clearTimeout(overlay.closeTimer); });
    node.addEventListener('mouseleave', () => { o.hovering = false; scheduleHoverClose(); });
    node.addEventListener('mousedown', () => { o.pinned = true; node.classList.add('pinned'); });
    overlay.current = o;
    // A style, label or range change saves through the owner's onSpecChange (which re-draws
    // the chip underneath) AND re-draws this overlay, so what was clicked shows at once
    // (Seth, 2026-10-13: "I can click them, but the styling doesn't show afterward").
    const oo = Object.assign({}, opts, { force: true, overlay: true, editable: !!opts.editable });
    oo.onSpecChange = (s) => { if (opts.onSpecChange) opts.onSpecChange(s); if (node.isConnected) render(inner, s, oo); };
    render(inner, spec, oo);
    /* Placement: below the chip when it fits, else above, else on whichever side has more
     * room with the overlay capped to that room (its body scrolls). Re-run whenever the
     * content changes size (the object arrives after "Loading…"), the window resizes or the
     * note scrolls, so the overlay never runs off the viewport (Seth, 2026-10-13). */
    const M = 12, GAP = 8;
    const home = anchor.parentElement;
    const place = () => {
      if (!node.isConnected) return;
      if (!anchor.isConnected) {                      // the chip was re-drawn: follow its replacement
        const again = o.find ? o.find() : (home && home.isConnected ? home.querySelector('.flex-collapsed') : null);
        if (!again) { if (overlay.current === o) closeOverlay(); return; }   // the object is gone: so is its preview
        anchor = again; o.anchor = again;
      }
      const r = anchor.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      const w = Math.min(760, vw - 2 * M);
      node.style.width = w + 'px';
      node.style.left = Math.max(M, Math.min(r.left, vw - w - M)) + 'px';
      // natural height from the content's scroll height — never by clearing max-height, which
      // would reset the overlay's own scroll position (Seth, 2026-10-13: "scrolling within the
      // overlay pane is locked")
      const want = bar.offsetHeight + inner.scrollHeight + 2;
      const below = vh - M - (r.bottom + GAP), above = r.top - GAP - M;
      let top, room;
      if (want <= below) { top = r.bottom + GAP; room = below; }
      else if (want <= above) { top = r.top - GAP - want; room = above; }
      else if (below >= above) { top = r.bottom + GAP; room = below; }
      else { room = above; top = M; }
      room = Math.max(120, Math.min(room, vh - 2 * M));
      const h = Math.min(want, room);
      if (top + h > vh - M) top = Math.max(M, vh - M - h);
      node.style.top = top + 'px';
      node.style.maxHeight = room + 'px';
    };
    place();
    const ro = new ResizeObserver(() => place());
    ro.observe(inner);
    const onScroll = (e) => { if (!node.contains(e.target)) place(); };   // the overlay's own scrolling is its own business
    window.addEventListener('resize', place);
    document.addEventListener('scroll', onScroll, true);
    o.cleanup = () => { ro.disconnect(); window.removeEventListener('resize', place); document.removeEventListener('scroll', onScroll, true); };
    return node;
  }

  /* ------------------------------------------------------------------ entry point */
  /* Render an embed spec into `container` (replacing its content). opts:
   *   editable      show the styling popovers, the ⋯ menu and collapse/expand controls
   *   onSpecChange  called with the mutated spec when styles/lines/range/collapse change
   *   editSource    callback for "Edit source"
   *   inCell        table-cell mode: a chip unless the embed says `expanded`
   *   force         render fully whatever the flags say (overlays) */
  async function render(container, spec, opts) {
    opts = opts || {};
    if (isCollapsed(spec, opts)) { renderChip(container, spec, opts); return; }
    container.innerHTML = '';
    container.appendChild(el('div', { class: 'flex-obj' }, el('div', { class: 'flex-loading' }, 'Loading from FLEx…')));
    const doRender = async (refresh) => {
      try {
        const kind = spec.kind === 'sense' ? 'entry' : spec.kind;
        const obj = await flexGet(kind, spec.guid, spec.kind === 'text' && spec.seg ? spec.seg[0] : null, spec.kind === 'text' && spec.seg ? spec.seg[1] : null, refresh, spec.kind === 'text' ? spec.ws : null, spec.kind === 'text' ? spec.at : null);
        if (syncAnchors(spec, obj, opts)) return;          // the spec changed: the owner re-renders
        const o = Object.assign({}, opts, { refresh: () => { invalidate(kind, spec.guid); doRender(true); } });
        const node = kind === 'text' ? renderText(obj, spec, o) : kind === 'wordform' ? renderWordform(obj, spec, o) : renderEntry(obj, spec, o);
        container.innerHTML = '';
        container.appendChild(node);
        container._obj = obj;
      } catch (e) {
        container.innerHTML = '';
        const err = el('div', { class: 'flex-obj' },
          el('div', { class: 'flex-head' }, el('span', { class: 'ttl' }, spec.label || (spec.kind + ' ' + spec.guid.slice(0, 8) + '…')), el('span', { class: 'spacer' }),
            el('button', { class: 'lnk', onclick: () => doRender(true) }, '↻ Retry'),
            opts.editable && opts.editSource ? el('button', { class: 'lnk', onclick: () => opts.editSource() }, 'Edit source') : null),
          el('div', { class: 'flex-err' }, 'Could not show this FLEx object. ', el('span', { class: 'hint' }, e.message || String(e))));
        container.appendChild(err);
      }
    };
    await doRender(false);
  }

  /* Inline chips in editable text (the `.md-embed` spans markdown.decorate emits): fill the
   * title / range from the object and open the same overlay as a collapsed chip. `opts`
   * (optional) is the owner's: onSpecChange(spec, oldSrc), duplicate(src), remove(src),
   * expandInline(src), editInline(span); without it the chips only get their titles. */
  function hydrateInline(root, opts) {
    root.querySelectorAll('.md-embed[data-src]').forEach((span) => {
      if (span.dataset.ready) return;
      span.dataset.ready = '1';
      const src = span.dataset.src;
      const spec = R.parse(src);
      if (!spec) { span.classList.add('err'); return; }
      const kind = spec.kind === 'sense' ? 'entry' : spec.kind;
      flexGet(kind, spec.guid, spec.kind === 'text' && spec.seg ? spec.seg[0] : null, spec.kind === 'text' && spec.seg ? spec.seg[1] : null, false, null, spec.kind === 'text' ? spec.at : null)
        .then((obj) => { if (!span.isConnected) return; span.dataset.title = chipTitle(spec, obj); if (spec.kind === 'text') span.dataset.range = chipRange(spec, obj); if (obj.cached) span.classList.add('cached'); })
        .catch((e) => { span.classList.add('err'); span.title = e.message || String(e); });
      if (!opts) return;
      const o = {
        editable: true, inline: true,
        onSpecChange: (s) => opts.onSpecChange && opts.onSpecChange(s, src),
        duplicate: opts.duplicate ? () => opts.duplicate(src) : null,
        remove: opts.remove ? () => opts.remove(src) : null,
        expandInline: opts.expandInline ? () => opts.expandInline(src) : null,
        editInline: opts.editInline ? () => opts.editInline(span) : null,
        findAnchor: () => (opts.findAnchor ? opts.findAnchor(src) : null),
      };
      const open = (e) => { e.preventDefault(); e.stopPropagation(); openOverlay(span, spec, o, { pinned: true }); };
      span.addEventListener('mousedown', (e) => { if (e.button === 0) e.preventDefault(); });   // keep the caret where it is
      span.addEventListener('click', open);
      let hoverTimer = null;
      span.addEventListener('mouseenter', () => { if (overlay.current && overlay.current.pinned) return; hoverTimer = setTimeout(() => openOverlay(span, spec, o, { pinned: false }), 380); });
      span.addEventListener('mouseleave', () => { clearTimeout(hoverTimer); scheduleHoverClose(); });
    });
  }

  FS.interlinear = { render, renderText, renderEntry, renderWordform, renderChip, hydrateInline, openContext, wholeText, openOverlay, closeOverlay, isCollapsed, setCollapsed, styled, styledParts, invalidate, flexGet, openInFlex, labelOf, numberFor, flexTsv, HL_COLORS };
})();
