/* files.js — files attached to notes (Seth, 2026-10-17: "attachments that are embedded in notes
 * with a chip that opens the file with its default associated app (or if it's an HTML file,
 * open it in an inline HTML previewer with the option to open it in a browser)").
 *
 *   {{file attachments/Survey.pdf "Survey"}}   a copy in the notebook's attachments/ (the default)
 *   {{file C:/Recordings/elicit%203.wav}}      a LINK to the file where it is (the user's choice)
 *
 * In a line of text it is a chip (markdown.decorate emits it, hydrateChip brings it to life); on a
 * line of its own it is a card (render), in a table cell a small chip. A click opens the file
 * in the program Windows gives it — a web page opens in the PREVIEW panel instead, with "Open in
 * browser". A web page runs in a sandboxed frame: its scripts work (a flextext-editor
 * .preview.html plays its lines), but it cannot reach this window or the notebook. Pictures,
 * PDFs, audio and video preview too, and any of them can be shown IN the note (`preview`, `h=`).
 * A program or script is never started from a note: the click shows it in its folder. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;

  // by extension, for the icon before Python has said what the file is (api.py _KINDS decides)
  const EXT = {
    html: ['html', 'htm', 'xhtml'], pdf: ['pdf'],
    image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'],
    audio: ['wav', 'mp3', 'm4a', 'ogg', 'oga', 'opus', 'flac', 'aac', 'weba'],
    video: ['mp4', 'webm', 'm4v', 'mov', 'ogv'],
    program: ['exe', 'com', 'bat', 'cmd', 'ps1', 'vbs', 'js', 'msi', 'scr', 'lnk', 'reg', 'hta', 'jar', 'py', 'sh'],
  };
  const ICON = { html: '🌐', pdf: '📕', image: '🖼', audio: '🔊', video: '🎞', folder: '📁', program: '⚙', file: '📄' };
  const PREVIEWABLE = new Set(['html', 'pdf', 'image', 'audio', 'video']);
  const baseName = (ref) => String(ref || '').split(/[\\/]/).filter(Boolean).pop() || String(ref || '');
  const isLinked = (ref) => /^([A-Za-z]:[\\/]|\\\\|\/)/.test(ref || '');
  function kindOf(ref) {
    const m = /\.([^.\\/]+)$/.exec(ref || '');
    const ext = m ? m[1].toLowerCase() : '';
    for (const [k, list] of Object.entries(EXT)) if (list.includes(ext)) return k;
    return 'file';
  }
  function chipInfo(spec) {
    const kind = kindOf(spec.ref);
    return { kind, icon: ICON[kind] || ICON.file, title: spec.label || baseName(spec.ref), linked: isLinked(spec.ref) };
  }
  function fmtSize(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB';
    return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + ' MB';
  }

  const cache = new Map();
  function info(ref, fresh) {
    if (fresh) cache.delete(ref);
    if (!cache.has(ref)) cache.set(ref, FS.api.file_info(ref).catch((e) => { cache.delete(ref); throw e; }));
    return cache.get(ref);
  }

  /* ------------------------------------------------------------------ actions */
  async function open(spec) {
    try {
      const r = await FS.api.open_file(spec.ref);
      if (r && r.reason === 'program') FS.toast('A program or script is never started from a note: it is shown in its folder instead.', 'warn');
    } catch (e) { FS.toast(e.message || String(e), 'error'); }
  }
  async function reveal(spec) {
    try { await FS.api.reveal_file(spec.ref); } catch (e) { FS.toast(e.message || String(e), 'error'); }
  }
  /* The click on a chip or a card's title: a web page previews, anything else opens. */
  function activate(spec) {
    return kindOf(spec.ref) === 'html' ? previewPanel(spec) : open(spec);
  }

  /* The file itself, shown: a sandboxed frame for a web page (scripts yes, this window no), the
   * browser's own viewer for a PDF, the media elements for the rest. */
  function previewNode(inf, height) {
    const h = height ? { height: height + 'px' } : {};
    if (inf.kind === 'html') return el('iframe', { class: 'file-frame', src: inf.fileUrl, sandbox: 'allow-scripts allow-popups allow-forms allow-modals', title: inf.name, style: h, 'data-test': 'file-frame' });
    if (inf.kind === 'pdf') return el('iframe', { class: 'file-frame', src: inf.fileUrl, title: inf.name, style: h });
    if (inf.kind === 'image') return el('img', { class: 'file-img', src: inf.fileUrl, alt: inf.name, style: height ? { maxHeight: height + 'px' } : {} });
    if (inf.kind === 'audio') return el('audio', { class: 'file-audio', src: inf.fileUrl, controls: true, preload: 'metadata' });
    if (inf.kind === 'video') return el('video', { class: 'file-video', src: inf.fileUrl, controls: true, preload: 'metadata', style: height ? { maxHeight: height + 'px' } : {} });
    return el('div', { class: 'muted' }, 'No preview for this kind of file.');
  }
  const openLabel = (kind) => (kind === 'html' ? 'Open in browser ↗' : kind === 'folder' ? 'Open folder ↗' : kind === 'program' ? 'Show in folder' : 'Open ↗');

  async function previewPanel(spec) {
    let inf;
    try { inf = await info(spec.ref, true); } catch (e) { FS.toast(e.message || String(e), 'error'); return null; }
    if (!inf.exists) { FS.toast('The file is missing: ' + inf.path, 'error'); return null; }
    const ci = chipInfo(spec);
    const m = FS.modal({ title: ci.icon + ' ' + ci.title, class: 'file-preview-modal' });
    m.box.setAttribute('data-test', 'file-preview');
    m.body.append(
      el('div', { class: 'file-preview-bar' },
        el('span', { class: 'muted small', dir: 'auto', title: inf.path }, (inf.linked ? '🔗 ' : '') + inf.name + (inf.size != null ? ' · ' + fmtSize(inf.size) : '')),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn', 'data-test': 'file-open', onclick: () => open(spec) }, openLabel(inf.kind)),
        el('button', { class: 'btn', onclick: () => reveal(spec) }, 'Show in folder')),
      previewNode(inf));
    return m;
  }

  function renameAt(anchor, spec, opts) {
    FS.popover(anchor, (pop, close) => {
      const input = el('input', { type: 'text', value: spec.label || '', placeholder: baseName(spec.ref), dir: 'auto', style: { width: '260px' } });
      const save = () => { spec.label = input.value.trim(); close(); if (opts.onSpecChange) opts.onSpecChange(spec); };
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
      pop.append(el('div', { class: 'row' }, el('b', {}, 'Label'), el('span', { class: 'muted small' }, ' (empty: the file name)')),
        el('div', { class: 'row' }, input, el('button', { class: 'btn primary', onclick: save }, 'Save')));
      setTimeout(() => { input.focus(); input.select(); }, 0);
    });
  }
  async function locate(spec, opts) {
    try {
      const r = await FS.api.locate_file(spec.ref);
      if (!r) return;
      spec.ref = r.ref;
      cache.delete(r.ref);
      if (opts.onSpecChange) opts.onSpecChange(spec);
    } catch (e) { FS.toast(e.message || String(e), 'error'); }
  }

  /* The ⋯ / right-click menu of an attachment, wherever it sits. */
  function menu(anchor, spec, opts, at) {
    const kind = kindOf(spec.ref);
    const build = (pop, close) => {
      const item = (label, fn, test, cls) => pop.appendChild(el('button', { class: 'menu-item' + (cls ? ' ' + cls : ''), 'data-test': test || null, onclick: () => { close(); fn(); } }, label));
      pop.appendChild(el('div', { class: 'row muted small', dir: 'auto', title: spec.ref }, (isLinked(spec.ref) ? '🔗 linked: ' : '📎 in the notebook: ') + spec.ref));
      item(openLabel(kind), () => open(spec), 'file-menu-open');
      if (PREVIEWABLE.has(kind)) item('Preview', () => previewPanel(spec), 'file-menu-preview');
      if (opts.block && PREVIEWABLE.has(kind) && opts.onSpecChange) {
        const shown = !!(spec.extra && spec.extra.preview);
        item(shown ? 'Hide the preview in the note' : 'Show the preview in the note', () => {
          spec.extra = spec.extra || {};
          if (shown) { delete spec.extra.preview; delete spec.extra.h; } else spec.extra.preview = true;
          opts.onSpecChange(spec);
        }, 'file-menu-inline');
      }
      item('Show in folder', () => reveal(spec));
      if (opts.onSpecChange) item('Label…', () => renameAt(anchor, spec, opts), 'file-menu-label');
      item('Copy path', async () => { try { const i = await info(spec.ref); FS.copyText(i.path); FS.toast('Copied ' + i.path); } catch (e) { FS.copyText(spec.ref); } });
      if (opts.onSpecChange) item('Find the file…', () => locate(spec, opts), 'file-menu-locate');
      if (opts.expandInline) item('⤢ Make it a block', () => opts.expandInline(), 'file-menu-block');
      if (opts.editCell) item('✎ Edit cell', () => opts.editCell());
      if (opts.duplicate) item('⧉ Duplicate', () => opts.duplicate());
      if (opts.remove) item('🗑 Remove from the note', () => opts.remove(), 'file-menu-remove', 'danger');
    };
    return at ? FS.popoverAt(at.x, at.y, build, { class: 'file-menu' }) : FS.popover(anchor, build, { class: 'file-menu' });
  }

  /* ------------------------------------------------------------------ rendering */
  function markState(node, inf) {
    node.classList.toggle('missing', !inf.exists);
    node.title = (inf.exists ? '' : 'Missing — ') + inf.path + (inf.size != null ? ' (' + fmtSize(inf.size) + ')' : '') + (inf.linked ? '\nLinked: the file stays where it is' : '\nA copy in the notebook\u2019s attachments folder');
  }

  /* A chip in a line of text (the `.md-embed` span; its text is still the markdown). */
  function hydrateChip(span, spec, opts) {
    opts = opts || {};
    info(spec.ref).then((inf) => { if (span.isConnected) { markState(span, inf); if (!inf.exists) span.classList.add('err'); } }).catch((e) => { span.classList.add('err'); span.title = e.message || String(e); });
    span.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (span.classList.contains('err')) menu(span, spec, opts); else activate(spec); });
    span.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); menu(span, spec, opts, { x: e.clientX, y: e.clientY }); });
  }

  /* A card (a line of its own) or, in a table cell, a small chip. */
  async function render(container, spec, opts) {
    opts = opts || {};
    const ci = chipInfo(spec);
    container.innerHTML = '';
    if (opts.inCell) {
      const chip = el('span', { class: 'file-chip drag-handle', tabindex: '0', role: 'button', draggable: opts.editable ? 'true' : null, 'data-test': 'file-chip' },
        el('span', { class: 'file-ico' }, ci.icon), el('span', { class: 'file-ttl', dir: 'auto' }, ci.title));
      chip.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (chip.classList.contains('missing')) menu(chip, spec, opts); else activate(spec); });
      chip.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); menu(chip, spec, opts, { x: e.clientX, y: e.clientY }); });
      chip.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); activate(spec); } });
      container.appendChild(chip);
      info(spec.ref).then((inf) => markState(chip, inf)).catch(() => chip.classList.add('missing'));
      return;
    }
    const meta = el('span', { class: 'file-meta muted small', dir: 'auto' }, (ci.linked ? '🔗 ' : '') + baseName(spec.ref));
    const ttl = el('button', { class: 'file-ttl lnk', dir: 'auto', 'data-test': 'file-title', onclick: () => activate(spec) }, ci.title);
    const more = el('button', { class: 'lnk', title: 'More', 'data-test': 'file-more', onclick: (e) => menu(e.currentTarget, spec, Object.assign({ block: true }, opts)) }, '⋯');
    const head = el('div', { class: 'file-head' },
      el('span', { class: 'file-ico drag-handle', draggable: opts.editable ? 'true' : null, title: 'Drag to move (Ctrl: copy)' }, ci.icon), ttl, meta, el('span', { class: 'spacer' }),
      PREVIEWABLE.has(ci.kind) && ci.kind !== 'html' ? el('button', { class: 'lnk', 'data-test': 'file-preview-btn', onclick: () => previewPanel(spec) }, 'Preview') : null,
      ci.kind === 'html' ? el('button', { class: 'lnk', 'data-test': 'file-preview-btn', onclick: () => previewPanel(spec) }, '⤢ Preview') : null,
      el('button', { class: 'lnk', 'data-test': 'file-open-btn', onclick: () => open(spec) }, openLabel(ci.kind)),
      more);
    const card = el('div', { class: 'file-obj', 'data-test': 'file-card' }, head);
    container.appendChild(card);
    card.addEventListener('contextmenu', (e) => { if (e.target.closest('iframe, audio, video')) return; e.preventDefault(); e.stopPropagation(); menu(card, spec, Object.assign({ block: true }, opts), { x: e.clientX, y: e.clientY }); });
    let inf;
    try { inf = await info(spec.ref); } catch (e) { card.classList.add('missing'); meta.textContent = e.message || String(e); return; }
    if (!card.isConnected && !container.contains(card)) return;
    markState(card, inf);
    meta.textContent = (inf.linked ? '🔗 ' : '') + inf.name + (inf.size != null ? ' · ' + fmtSize(inf.size) : '') + (inf.exists ? '' : ' · missing');
    if (!inf.exists) {
      card.appendChild(el('div', { class: 'file-missing' }, 'The file is not where the note expects it: ', el('code', { dir: 'auto' }, inf.path), ' ',
        opts.onSpecChange ? el('button', { class: 'lnk', 'data-test': 'file-locate', onclick: () => locate(spec, opts) }, 'Find the file…') : null));
      return;
    }
    if (spec.extra && spec.extra.preview && PREVIEWABLE.has(inf.kind)) {
      const want = parseInt(spec.extra.h, 10) || (inf.kind === 'audio' ? 0 : 420);
      const box = el('div', { class: 'file-inline kind-' + inf.kind, 'data-test': 'file-inline' }, previewNode(inf, inf.kind === 'audio' ? 0 : want));
      card.appendChild(box);
      // the frame's height is the one thing to drag: the new height is saved as h=
      const frame = box.querySelector('iframe');
      if (frame && opts.onSpecChange) {
        frame.style.height = want + 'px';
        box.classList.add('resizable');
        const grip = el('div', { class: 'file-grip', title: 'Drag to change the height' });
        box.appendChild(grip);
        grip.addEventListener('mousedown', (e) => {
          e.preventDefault();
          const y0 = e.clientY, h0 = frame.offsetHeight;
          box.classList.add('sizing');
          const mv = (ev) => { frame.style.height = Math.max(120, h0 + ev.clientY - y0) + 'px'; };
          const up = () => {
            document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up);
            box.classList.remove('sizing');
            const h = Math.round(frame.offsetHeight);
            if (h !== want) { spec.extra.h = String(h); opts.onSpecChange(spec); }
          };
          document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
        });
      }
    }
  }

  /* ------------------------------------------------------------------ attaching */
  // a picture or a video is SHOWN in the note on a line of its own (Seth, 2026-10-17: "dragging in
  // images and videos would also work"); in a line of text it is a chip all the same
  const embedFor = (item) => FS.flexref.serialize({ kind: 'file', ref: item.ref, label: '', extra: ['image', 'video'].includes(item.kind || kindOf(item.ref)) ? { preview: true } : {} });
  /* The file dialog; copies unless `link`. → [embed markdown] */
  async function pick(link) {
    try {
      const items = await FS.api.attach_files(!!link);
      for (const i of items || []) cache.delete(i.ref);
      return (items || []).map(embedFor);
    } catch (e) { FS.toast(e.message || String(e), 'error'); return []; }
  }
  const readB64 = (file) => new Promise((res, rej) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.onerror = () => rej(fr.error); fr.readAsDataURL(file); });
  /* Files dropped (or pasted) onto a note. Python knows a dropped file's path only through
   * pywebview's own drop handler (app.py); a file it did not see — or a pasted one — is sent as
   * bytes, which can only be COPIED. → [embed markdown] */
  async function fromFiles(files, link) {
    files = [...(files || [])];
    if (!files.length) return [];
    let got = { files: [], missing: files.map((f) => f.name) };
    try { got = await FS.api.attach_dropped(files.map((f) => f.name), !!link); } catch (e) { /* bytes, below */ }
    const out = (got.files || []).slice();
    for (const name of got.missing || []) {
      const f = files.find((x) => x.name === name);
      if (!f) continue;
      try { out.push(await FS.api.attach_data(f.name, await readB64(f))); } catch (e) { FS.toast(f.name + ': ' + (e.message || e), 'error'); }
    }
    if (link && (got.missing || []).length && out.length) FS.toast('Copied into the notebook: the program was not told where ' + (got.missing.length === 1 ? 'that file is' : 'those files are') + ', so ' + (got.missing.length === 1 ? 'it' : 'they') + ' could not be linked.', 'warn');
    for (const i of out) cache.delete(i.ref);
    return out.map(embedFor);
  }
  const hasFiles = (dt) => !!dt && [...(dt.types || [])].includes('Files');

  FS.files = { kindOf, chipInfo, info, open, reveal, activate, previewPanel, render, hydrateChip, menu, pick, fromFiles, hasFiles, embedFor, baseName, isLinked, ICON, PREVIEWABLE, fmtSize };
})();
