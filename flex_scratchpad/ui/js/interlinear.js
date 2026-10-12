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
  const keyOf = (kind, guid, a, b) => kind + '|' + guid + '|' + (a || '') + '|' + (b || '');
  const flexGet = async (kind, guid, a, b, refresh) => {
    const k = keyOf(kind, guid, a, b);
    if (!refresh && mem.has(k)) return mem.get(k);
    const p = FS.api.flex_get(kind, guid, a || null, b || null, false).then((obj) => { mem.set(k, obj); return obj; }, (e) => { mem.delete(k); throw e; });
    mem.set(k, p);
    return p;
  };
  const invalidate = (kind, guid) => { for (const k of [...mem.keys()]) if (!kind || k.startsWith((kind === 'sense' ? 'entry' : kind) + '|' + (guid || ''))) mem.delete(k); };

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
    const rangeLabel = segs.length ? (range[0] === range[1] ? 'segment ' + range[0] : 'segments ' + range[0] + '–' + range[1]) + ' of ' + obj.segmentCount : 'no segments';

    const head = el('div', { class: 'flex-head' },
      el('span', Object.assign({ class: 'ttl vern' }, wsAttrs(vern)), obj.title || '(untitled text)'),
      el('span', { class: 'badge' }, rangeLabel),
      obj.cached ? el('span', { class: 'badge warn', title: obj.liveError || 'Shown from the notebook cache' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')) : null,
      spec.label ? el('span', { class: 'badge' }, spec.label) : null,
      el('span', { class: 'spacer' }),
    );
    const anyTimed = segs.some((s) => s.begin != null && s.end != null);
    if (anyTimed && segs.length > 1) {
      head.appendChild(el('button', { class: 'lnk', title: 'Play this range', onclick: () => playRange(box, obj, segs, mediaByGuid, opts) }, '▶ Play ' + range[0] + '–' + range[1]));
    }
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
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
    const gutter = el('div', { class: 'seg-gutter' }, el('span', { class: 'segnum' }, String(seg.n)));
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
    (seg.words || []).forEach((word) => {
      if (word.punct) {
        wordRow.appendChild(el('div', { class: 'word-cell punct-cell' }, el('div', Object.assign({ class: 'il-line il-txt' }, wsAttrs(vern)), word.txt)));
        return;
      }
      w++;
      const wi = w;                      // this cell's ordinal — captured per cell, not the loop counter
      const cell = el('div', { class: 'word-cell', dataset: { w: wi } });
      const sf = (line) => R.stylesFor(index, seg.n, line, wi);
      for (const line of lines) {
        if (line === 'txt') cell.appendChild(el('div', Object.assign({ class: 'il-line il-txt', html: styled(word.txt || '', sf('txt')) }, wsAttrs(vern))));
        else if (line === 'morph' && word.morphs && word.morphs.length) cell.appendChild(el('div', Object.assign({ class: 'il-line il-morph', html: styledParts(word.morphs.map((m) => m.form || ''), sf('morph')) }, wsAttrs(vern))));
        else if (line === 'mgls' && word.morphs && word.morphs.length) cell.appendChild(el('div', { class: 'il-line il-mgls', lang: anal.tag || null, html: styledParts(word.morphs.map((m) => m.gls || ''), sf('mgls')) }));
        else if (line === 'cf' && word.morphs && word.morphs.some((m) => m.cf)) cell.appendChild(el('div', { class: 'il-line il-cf', html: styledParts(word.morphs.map((m) => m.cf || ''), sf('cf')) }));
        else if (line === 'gls' && word.gls) cell.appendChild(el('div', { class: 'il-line il-gls', lang: anal.tag || null, html: styled(word.gls, sf('gls')) }));
        else if (line === 'pos' && word.pos) cell.appendChild(el('div', { class: 'il-line il-pos', html: styled(word.pos, sf('pos')) }));
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
          stylePopover(cell, spec, target, word, opts, { box });
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
    let src = info.fileUrl, offBegin = begin, offEnd = end;
    if (!src && info.clipUrl) { src = info.clipUrl; offBegin = 0; offEnd = end - begin; }
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
      FS.toast('Could not play the audio: ' + (e.message || e), 'error');
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

  function mediaMissingPopover(anchor, m, info, opts) {
    FS.popover(anchor, (pop, close) => {
      pop.appendChild(el('div', { class: 'row' }, el('b', {}, 'Media file not found')));
      pop.appendChild(el('div', { class: 'hint' }, 'FLEx names it ' + (m.uri || '(no file)') + '. Point the Scratchpad at the real file; the choice is remembered for this notebook.'));
      if (info && info.clipUrl) pop.appendChild(el('div', { class: 'hint' }, 'A cached clip exists and will be used.'));
      pop.appendChild(el('hr'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: async () => { close(); try { const r = await FS.api.audio_browse_media(m.guid || ''); if (r) { invalidate(); FS.toast('Media file set', 'ok'); opts.refresh && opts.refresh(); } } catch (e) { FS.toast(e.message, 'error'); } } }, 'Browse for the audio file…'));
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
      const state = { line: target.line || 'txt', chars: null, color: '' };
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
      if (spec.kind === 'text') {
        const a = el('input', { type: 'number', min: 1, value: spec.seg ? spec.seg[0] : 1, style: { width: '60px' } });
        const b = el('input', { type: 'number', min: 1, value: spec.seg ? spec.seg[1] : (obj && obj.segmentCount) || 1, style: { width: '60px' } });
        const set = () => { spec.seg = [Math.min(+a.value, +b.value), Math.max(+a.value, +b.value)]; opts.onSpecChange && opts.onSpecChange(spec); };
        a.addEventListener('change', set); b.addEventListener('change', set);
        pop.appendChild(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Segments'), a, el('span', { class: 'muted' }, '–'), b));
        pop.appendChild(el('hr'));
      }
      if (obj && obj.url) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(obj.url); FS.toast('FLEx link copied'); close(); } }, 'Copy FLEx link'));
      pop.appendChild(el('button', { class: 'menu-item', onclick: () => { FS.copyText(R.serialize(spec)); FS.toast('Embed code copied'); close(); } }, 'Copy embed code'));
      if (opts.editSource) pop.appendChild(el('button', { class: 'menu-item', onclick: () => { close(); opts.editSource(); } }, 'Edit source'));
    });
  }

  /* ------------------------------------------------------------------ rendering: entry */
  function renderEntry(obj, spec, opts) {
    const vern = (obj.ws && obj.ws.vern) || {}, anal = (obj.ws && obj.ws.anal) || {};
    const box = el('div', { class: 'flex-obj entry-card' + (obj.cached ? ' cached' : '') });
    const hw = el('span', Object.assign({ class: 'headword' }, wsAttrs(vern)), obj.headword || obj.lexemeForm || '?');
    if (obj.homograph) hw.appendChild(el('sub', {}, String(obj.homograph)));
    const head = el('div', { class: 'flex-head' }, hw);
    if (obj.citationForm && obj.citationForm !== obj.headword && obj.citationForm !== obj.lexemeForm) head.appendChild(el('span', Object.assign({ class: 'ecf' }, wsAttrs(vern)), obj.citationForm));
    if (obj.morphType) head.appendChild(el('span', { class: 'mtype' }, obj.morphType));
    if (obj.cached) head.appendChild(el('span', { class: 'badge warn', title: obj.liveError || '' }, 'cached' + (obj.cachedAt ? ' ' + obj.cachedAt.slice(0, 10) : '')));
    head.appendChild(el('span', { class: 'spacer' }));
    head.appendChild(el('button', { class: 'lnk', title: 'Reload from FLEx', onclick: () => opts.refresh && opts.refresh() }, '↻'));
    if (obj.url) head.appendChild(el('a', { href: obj.url, onclick: (e) => { e.preventDefault(); openInFlex(obj.url); } }, 'Open in FLEx ↗'));
    if (opts.editable) head.appendChild(el('button', { class: 'lnk', onclick: (e) => embedMenu(e.currentTarget, spec, opts, obj) }, '⋯'));
    box.appendChild(head);
    for (const s of obj.senses || []) {
      const focus = spec.kind === 'sense' && s.guid === spec.guid;
      const sd = el('div', { class: 'sense' + (focus ? ' focus' : '') },
        el('span', { class: 'sn' }, s.number || ''),
        el('div', { style: { flex: 1 } },
          el('div', {}, s.pos ? el('span', { class: 'pos' }, s.pos) : null, el('span', { class: 'gl', lang: anal.tag || null }, s.gloss || ''), s.definition && s.definition !== s.gloss ? el('span', { class: 'def' }, (s.gloss ? ' — ' : '') + s.definition) : null),
          ...(s.examples || []).map((ex) => el('div', { class: 'ex' }, el('span', Object.assign({ class: 'v' }, wsAttrs(vern)), ex.text || ''), ex.translation ? el('span', {}, '  ‘' + ex.translation + '’') : null))));
      box.appendChild(sd);
    }
    if (!(obj.senses || []).length) box.appendChild(el('div', { class: 'seg-empty' }, 'No senses.'));
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

  /* ------------------------------------------------------------------ entry point */
  /* Render an embed spec into `container` (replacing its content). opts:
   *   editable      show the styling popovers and the ⋯ menu
   *   onSpecChange  called with the mutated spec when styles/lines/range change
   *   editSource    callback for "Edit source"
   *   compact       table-cell mode */
  async function render(container, spec, opts) {
    opts = opts || {};
    container.innerHTML = '';
    container.appendChild(el('div', { class: 'flex-obj' }, el('div', { class: 'flex-loading' }, 'Loading from FLEx…')));
    const doRender = async (refresh) => {
      try {
        const kind = spec.kind === 'sense' ? 'entry' : spec.kind;
        const obj = await flexGet(kind, spec.guid, spec.kind === 'text' && spec.seg ? spec.seg[0] : null, spec.kind === 'text' && spec.seg ? spec.seg[1] : null, refresh);
        const o = Object.assign({}, opts, { refresh: () => { invalidate(kind, spec.guid); doRender(true); } });
        const node = kind === 'text' ? renderText(obj, spec, o) : kind === 'wordform' ? renderWordform(obj, spec, o) : renderEntry(obj, spec, o);
        container.innerHTML = '';
        container.appendChild(node);
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

  FS.interlinear = { render, renderText, renderEntry, renderWordform, styled, styledParts, invalidate, flexGet, openInFlex, HL_COLORS };
})();
