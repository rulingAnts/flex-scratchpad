/* markdown.js — blocks and inline decoration.
 *
 * A note is a list of BLOCKS separated by blank lines (lists, tables and fences stay whole).
 * Text blocks are edited in place: the DOM text IS the markdown, and `decorate()` only wraps
 * characters in spans — it never adds or removes any — so caret offsets stay valid and the
 * markers (`**`, `#`, `- `) can be drawn faintly instead of hidden.
 *
 * Block types: p, h, list, quote, code, chart, table, flex, hr. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const esc = FS.esc;

  const RE = {
    fence: /^\s{0,3}(`{3,}|~{3,})\s*([\w-]*)\s*$/,
    tableSep: /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/,
    tableStyle: /^\s*\{table\b[^}]*\}\s*$/,
    hr: /^\s{0,3}([-*_])(\s*\1){2,}\s*$/,
    heading: /^(#{1,6})\s/,
    list: /^(\s*)([-*+]|\d+[.)])\s/,
    task: /^(\s*)([-*+])\s\[([ xX])\]\s?/,
    quote: /^\s*>/,
    image: /^\s*!\[[^\]]*\]\([^)\s]+(?:\s+"[^"]*")?\)\s*$/,
  };

  function isTableStart(lines, i) {
    return lines[i].includes('|') && i + 1 < lines.length && RE.tableSep.test(lines[i + 1]) && lines[i + 1].includes('-');
  }
  function startsSpecial(line, lines, i) {
    return RE.fence.test(line) || RE.hr.test(line) || RE.heading.test(line) || RE.list.test(line)
      || RE.quote.test(line) || FS.flexref.isEmbedLine(line) || RE.image.test(line) || isTableStart(lines, i);
  }

  function splitBlocks(md) {
    const lines = String(md || '').replace(/\r\n?/g, '\n').split('\n');
    const blocks = [];
    let i = 0;
    const push = (type, from, to, extra) => blocks.push(Object.assign({ type, src: lines.slice(from, to).join('\n') }, extra || {}));
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let m;
      if ((m = RE.fence.exec(line))) {
        const fence = m[1][0];
        let j = i + 1;
        while (j < lines.length && !(new RegExp('^\\s{0,3}' + (fence === '`' ? '`{3,}' : '~{3,}') + '\\s*$')).test(lines[j])) j++;
        const lang = (m[2] || '').toLowerCase();
        push(lang === 'chart' ? 'chart' : 'code', i, Math.min(lines.length, j + 1), { lang });
        i = j + 1;
        continue;
      }
      if (isTableStart(lines, i)) {
        let j = i + 2;
        while (j < lines.length && lines[j].trim() && lines[j].includes('|')) j++;
        if (j < lines.length && RE.tableStyle.test(lines[j])) j++;
        push('table', i, j);
        i = j;
        continue;
      }
      if (FS.flexref.isEmbedLine(line)) { push('flex', i, i + 1); i++; continue; }
      if (RE.image.test(line)) { push('image', i, i + 1); i++; continue; }
      if (RE.hr.test(line)) { push('hr', i, i + 1); i++; continue; }
      if (RE.heading.test(line)) { push('h', i, i + 1, { level: RE.heading.exec(line)[1].length }); i++; continue; }
      if (RE.list.test(line)) {
        let j = i + 1;
        while (j < lines.length && lines[j].trim() && (RE.list.test(lines[j]) || /^\s{2,}/.test(lines[j]))) j++;
        push('list', i, j, { ordered: /^\s*\d/.test(line) });
        i = j;
        continue;
      }
      if (RE.quote.test(line)) {
        let j = i + 1;
        while (j < lines.length && RE.quote.test(lines[j])) j++;
        push('quote', i, j);
        i = j;
        continue;
      }
      let j = i + 1;
      while (j < lines.length && lines[j].trim() && !startsSpecial(lines[j], lines, j)) j++;
      push('p', i, j);
      i = j;
    }
    return blocks;
  }

  function joinBlocks(blocks) {
    return blocks.map((b) => b.src.replace(/\s+$/, '')).filter((s) => s !== '').join('\n\n');
  }

  function classify(src) {
    const b = splitBlocks(src);
    if (b.length === 1) return b[0];
    if (!b.length) return { type: 'p', src: src };
    return { type: 'p', src: src };
  }

  /* ------------------------------------------------------------------ inline decoration */

  const LINE_CLASSES = { txt: 'in-txt' };

  /* Per-character class marks for one line of text. Returns {cls: Array<Set>, links: Map} */
  function markInline(text, out, offset) {
    const n = text.length;
    const marks = out.marks;
    const addRange = (a, b, c) => { for (let i = a; i < b && i < n; i++) marks[offset + i].add(c); };
    const markMarker = (a, b) => addRange(a, b, 'mk');
    const taken = new Uint8Array(n);      // chars already claimed by code/embeds/links
    // 1. embeds and code spans (atomic)
    let m;
    const embedRe = /\{\{\s*flex:[^{}]*\}\}/g;
    while ((m = embedRe.exec(text))) {
      addRange(m.index, m.index + m[0].length, 'embed');
      out.embeds.push({ start: offset + m.index, end: offset + m.index + m[0].length, src: m[0] });
      for (let i = m.index; i < m.index + m[0].length; i++) taken[i] = 1;
    }
    const codeRe = /(`+)([^`\n]|[^`\n][\s\S]*?[^`\n])\1(?!`)/g;
    while ((m = codeRe.exec(text))) {
      if (taken[m.index]) continue;
      addRange(m.index, m.index + m[0].length, 'code');
      markMarker(m.index, m.index + m[1].length);
      markMarker(m.index + m[0].length - m[1].length, m.index + m[0].length);
      for (let i = m.index; i < m.index + m[0].length; i++) taken[i] = 1;
    }
    // 2. links, wikilinks, autolinks, <br>
    const linkRe = /\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
    while ((m = linkRe.exec(text))) {
      if (taken[m.index]) continue;
      const s = m.index, e = m.index + m[0].length;
      addRange(s, e, 'link');
      markMarker(s, s + 1); markMarker(s + 1 + m[1].length, e);
      out.links.push({ start: offset + s, end: offset + e, text: m[1], href: m[2] });
      for (let i = s; i < e; i++) taken[i] = 1;
    }
    const wikiRe = /\[\[([^\]\n]+)\]\]/g;
    while ((m = wikiRe.exec(text))) {
      if (taken[m.index]) continue;
      const s = m.index, e = m.index + m[0].length;
      addRange(s, e, 'wiki');
      markMarker(s, s + 2); markMarker(e - 2, e);
      out.links.push({ start: offset + s, end: offset + e, text: m[1], href: 'note:' + m[1] });
      for (let i = s; i < e; i++) taken[i] = 1;
    }
    const autoRe = /(?<![\w"(\[])(https?:\/\/[^\s<>"')\]]+|silfw:\/\/[^\s<>"']+)/g;
    while ((m = autoRe.exec(text))) {
      if (taken[m.index]) continue;
      const s = m.index, e = m.index + m[0].length;
      addRange(s, e, 'link');
      out.links.push({ start: offset + s, end: offset + e, text: m[0], href: m[0] });
      for (let i = s; i < e; i++) taken[i] = 1;
    }
    const brRe = /<br\s*\/?>/gi;
    while ((m = brRe.exec(text))) { if (!taken[m.index]) { addRange(m.index, m.index + m[0].length, 'br'); addRange(m.index, m.index + m[0].length, 'mk'); } }
    // 3. tags
    const tagRe = /(?<![\w#\/&])#([\p{L}\p{N}_][\p{L}\p{N}_-]*)/gu;
    while ((m = tagRe.exec(text))) {
      if (taken[m.index] || /^\d+$/.test(m[1])) continue;
      addRange(m.index, m.index + m[0].length, 'tag');
      out.tags.push({ start: offset + m.index, end: offset + m.index + m[0].length, tag: m[1] });
      for (let i = m.index; i < m.index + m[0].length; i++) taken[i] = 1;
    }
    // 4. emphasis — a small delimiter stack over **, __, *, _, ~~, ==
    const delims = [];
    const isWordCh = (c) => !!c && /[\p{L}\p{N}_]/u.test(c);
    const isSpace = (c) => !c || /\s/.test(c);
    for (let i = 0; i < n; i++) {
      if (taken[i]) continue;
      const c = text[i];
      let run = 1;
      if (c === '*' || c === '_' || c === '~' || c === '=') {
        while (i + run < n && text[i + run] === c) run++;
        if ((c === '~' || c === '=') && run < 2) { continue; }
        // handle runs longer than needed by treating in pieces (*** → ** + *)
        let pos = i;
        let remaining = run;
        while (remaining > 0) {
          const use = (c === '*' || c === '_') ? (remaining >= 2 ? 2 : 1) : 2;
          if (remaining < use) break;
          const before = text[pos - 1], after = text[pos + use];
          const canOpen = !isSpace(after) && !(c === '_' && isWordCh(before));
          const canClose = !isSpace(before) && !(c === '_' && isWordCh(after));
          const style = (c === '~') ? 's' : (c === '=') ? 'mark' : (use === 2 ? 'b' : 'i');
          let matched = false;
          if (canClose) {
            for (let k = delims.length - 1; k >= 0; k--) {
              if (delims[k].style === style && delims[k].ch === c) {
                const d = delims.splice(k)[0];
                addRange(d.pos + d.len, pos, style);
                markMarker(d.pos, d.pos + d.len); markMarker(pos, pos + use);
                matched = true;
                break;
              }
            }
          }
          if (!matched && canOpen) delims.push({ style, ch: c, pos, len: use });
          pos += use; remaining -= use;
        }
        i += run - 1;
      }
    }
  }

  /* Block-level prefix of a line: returns {marker: n chars, cls, extra} */
  function linePrefix(line, blockType) {
    let m;
    if (blockType === 'h' && (m = RE.heading.exec(line))) return { len: m[0].length, cls: 'md-h md-h' + m[1].length, lineCls: 'md-line-h md-line-h' + m[1].length };
    if (blockType === 'list' || blockType === 'p') {
      if ((m = RE.task.exec(line))) return { len: m[0].length, cls: 'md-bullet', task: m[3] !== ' ', taskPos: [m[1].length + 2, m[1].length + 5], indent: m[1].length };
      if ((m = RE.list.exec(line))) return { len: m[0].length, cls: /\d/.test(m[2]) ? 'md-num' : 'md-bullet', indent: m[1].length };
    }
    if (blockType === 'quote' && (m = /^\s*>\s?/.exec(line))) return { len: m[0].length, cls: 'md-quote-mk', lineCls: 'md-line-quote' };
    return null;
  }

  /* Outline numbers (Seth, 2026-10-13: "our outline numbering is a bit wonky"). The typed
   * number stays in the file; what is SHOWN is computed like Markdown renders it: a counter per
   * nesting level (2 spaces = a level), continuing across blank lines (a loose list is one
   * list), deeper levels restarting under each item, everything restarting after a line that
   * is not part of the list. `ctx.counters` carries the state from block to block. */
  function listLevel(pre) { return Math.min(4, Math.round((pre.indent || 0) / 2)); }
  function numberLines(lines, blockType, ctx) {
    ctx = ctx || { counters: [] };
    if (!ctx.counters) ctx.counters = [];
    return lines.map((line) => {
      const pre = linePrefix(line, blockType);
      if (!pre || (pre.cls !== 'md-num' && pre.cls !== 'md-bullet')) {
        if (line.trim() !== '' && !/^\s{2,}/.test(line)) ctx.counters = [];   // continuation text keeps the list alive
        return null;
      }
      const level = listLevel(pre);
      ctx.counters.length = level + 1;
      if (pre.cls !== 'md-num') return null;
      ctx.counters[level] = (ctx.counters[level] || 0) + 1;
      return ctx.counters[level];
    });
  }

  /* Decorate a text block for in-place editing: HTML whose textContent === src.
   * `ctx` (optional) is the outline-numbering state before this block; it is advanced. */
  function decorate(src, blockType, ctx) {
    const lines = src.split('\n');
    const nums = numberLines(lines, blockType, ctx || { counters: [] });
    const html = [];
    let offset = 0;
    lines.forEach((line, li) => {
      const out = { marks: [], embeds: [], links: [], tags: [] };
      for (let i = 0; i < line.length; i++) out.marks.push(new Set());
      const pre = linePrefix(line, blockType);
      let start = 0;
      let lineCls = (pre && pre.lineCls) || '';
      if (pre) {
        for (let i = 0; i < pre.len; i++) { out.marks[i].add('mk'); out.marks[i].add(pre.cls); }
        if (pre.taskPos) { for (let i = pre.taskPos[0]; i < pre.taskPos[1]; i++) { out.marks[i].delete(pre.cls); out.marks[i].add(pre.task ? 'md-task md-task-on' : 'md-task'); } lineCls += ' md-line-task' + (pre.task ? ' md-done' : ''); }
        if (pre.cls === 'md-num') lineCls += ' md-line-num';
        if (pre.cls === 'md-bullet') lineCls += ' md-line-bullet';
        if (pre.indent) lineCls += ' md-indent' + Math.min(4, Math.round(pre.indent / 2));
        start = pre.len;
      }
      if (blockType === 'h') { const lvl = (RE.heading.exec(line) || [null, '#'])[1].length; for (let i = start; i < line.length; i++) out.marks[i].add('md-h md-h' + lvl); }
      if (blockType === 'code' || blockType === 'chart') {
        if (RE.fence.test(line) && (li === 0 || li === lines.length - 1)) for (let i = 0; i < line.length; i++) out.marks[i].add('mk');
      } else {
        markInline(line.slice(start), out, start);
      }
      // an empty line needs a <br> to have height and to count as a real line for Chromium
      // (a bare trailing "\n" text node gets collapsed away when typing after it); <br> adds
      // nothing to textContent, so the text-is-the-markdown invariant holds.
      // the computed number rides on the number span itself: CSS attr() reads only the
      // element the ::before belongs to (the line's copy is for tests and tooling)
      const numAttr = nums[li] != null ? ' data-num="' + nums[li] + '."' : '';
      let inner = line.length ? emit(line, out) : '<br>';
      if (numAttr) inner = inner.replace('<span class="md-marker md-num">', '<span class="md-marker md-num"' + numAttr + '>');
      html.push('<span class="md-line ' + lineCls + '"' + numAttr + '>' + inner + '</span>');
      offset += line.length + 1;
    });
    return html.join('\n');
  }

  function clsOf(set) {
    const c = [];
    for (const k of set) c.push(k === 'mk' ? 'md-marker' : k.startsWith('md-') ? k : 'md-' + k);
    return c.join(' ');
  }

  /* An embed inside a line of text is shown as a CHIP (Seth, 2026-10-13: "put chips inline
   * with text"): the span keeps the raw `{{flex …}}` as its text (textContent stays the
   * markdown) and is contenteditable=false, so the caret steps over it and Backspace removes
   * it whole; CSS draws the chip from data-icon / data-title, which FS.interlinear.hydrateInline
   * fills in from the object once it is known. */
  function embedAttrs(src) {
    const spec = FS.flexref && FS.flexref.parse ? FS.flexref.parse(src) : null;
    const icon = !spec ? '?' : spec.kind === 'text' ? '¶' : spec.kind === 'wordform' ? 'ω' : '📖';
    const title = !spec ? 'FLEx object' : spec.label || (spec.kind + ' ' + spec.guid.slice(0, 8) + '…');
    return ' contenteditable="false" data-src="' + esc(src) + '" data-icon="' + icon + '" data-title="' + esc(title) + '"' + (spec && spec.kind === 'text' && spec.seg ? ' data-range="' + spec.seg[0] + (spec.seg[1] !== spec.seg[0] ? '–' + spec.seg[1] : '') + '"' : '');
  }
  function emit(line, out) {
    if (!line.length) return '';
    let html = '';
    let cur = null, buf = '';
    const flush = () => {
      if (buf === '') return;
      if (cur && /\bmd-embed\b/.test(cur) && /^\{\{[\s\S]*\}\}$/.test(buf)) html += '<span class="' + cur + '"' + embedAttrs(buf) + '>' + esc(buf) + '</span>';
      else html += cur ? '<span class="' + cur + '">' + esc(buf) + '</span>' : esc(buf);
      buf = '';
    };
    for (let i = 0; i < line.length; i++) {
      const c = clsOf(out.marks[i]);
      if (c !== cur) { flush(); cur = c; }
      buf += line[i];
    }
    flush();
    return html;
  }

  /* Render inline markdown to display HTML (markers hidden, links live, embeds as placeholders).
   * Used by table cells when not being edited, search previews, and entry/example text. */
  function renderInline(text) {
    text = String(text || '');
    const out = { marks: [], embeds: [], links: [], tags: [] };
    for (let i = 0; i < text.length; i++) out.marks.push(new Set());
    markInline(text, out, 0);
    let html = '';
    let i = 0;
    const open = [];
    const styleTag = { b: 'strong', i: 'em', s: 's', mark: 'mark', code: 'code', tag: 'span', link: 'a', wiki: 'a', embed: 'span' };
    const order = ['link', 'wiki', 'embed', 'code', 'tag', 'mark', 'b', 'i', 's'];
    while (i < text.length) {
      const set = out.marks[i];
      const embed = out.embeds.find((e) => e.start === i);
      if (embed) { html += '<span class="flex-inline" data-src="' + esc(embed.src) + '"></span>'; i = embed.end; continue; }
      const link = out.links.find((l) => l.start === i);
      if (link) {
        const cls = link.href.startsWith('note:') ? 'wikilink' : link.href.startsWith('flex:') ? 'flex-chip' : 'ext-link';
        html += '<a class="' + cls + '" href="' + esc(link.href) + '" data-href="' + esc(link.href) + '">' + esc(link.text) + '</a>';
        i = link.end; continue;
      }
      if (set.has('br')) { html += '<br>'; while (i < text.length && out.marks[i].has('br')) i++; continue; }
      if (set.has('mk')) { i++; continue; }
      const want = order.filter((k) => set.has(k) && k !== 'link' && k !== 'wiki' && k !== 'embed');
      // close tags no longer wanted, open new ones
      while (open.length && !want.includes(open[open.length - 1])) html += '</' + styleTag[open.pop()] + '>';
      for (const k of want) if (!open.includes(k)) { open.push(k); html += '<' + styleTag[k] + (k === 'tag' ? ' class="inline-tag"' : '') + '>'; }
      html += esc(text[i]);
      i++;
    }
    while (open.length) html += '</' + styleTag[open.pop()] + '>';
    return html;
  }

  /* Plain text of a block for previews: markers dropped. */
  function plainText(src) {
    return String(src || '').replace(/\{\{[^}]*\}\}/g, ' ').replace(/`{1,3}/g, '').replace(/^#{1,6}\s+/gm, '')
      .replace(/^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s*)?/gm, '').replace(/[*_~=]{1,2}/g, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').trim();
  }

  FS.markdown = { RE, splitBlocks, joinBlocks, classify, decorate, renderInline, plainText, linePrefix, markInline, numberLines, listLevel };
})();
