/* backup.js — the "Backup & storage" dialog (Seth, 2026-10-17).
 *
 * Where: a CLOUD SYNC FOLDER (OneDrive, Google Drive, Dropbox… — the ones on this computer are
 * offered, with a suggested folder inside), or S3-COMPATIBLE storage through rclone. The keys and
 * the encryption password go to Python once and from there only to the secret store (the Windows
 * Credential Manager); the page only ever learns WHETHER each is set. A backup mirrors the
 * notebook into current/ and keeps what it replaces or removes in versions/<date>.
 *
 * Storage: what the notebook folder takes by kind, what the backup takes (its copy and each
 * version), and the cleanup: old versions (chosen, or kept for N days), unused attachments (to the
 * trash), the trash itself, cached audio clips. Everything that deletes asks first. */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;
  const size = (n) => (FS.files ? FS.files.fmtSize(n || 0) : (n || 0) + ' B');
  const when = (iso) => (iso ? (FS.relTime ? FS.relTime(iso) : iso) : '');
  const verDate = (v) => v.replace(/^(\d{4}-\d\d-\d\d)_(\d\d)(\d\d)(\d\d)$/, '$1 $2:$3');

  /* The sidebar line: shown once a backup is set up. */
  function renderPill(st) {
    const pill = document.getElementById('backup-pill');
    if (!pill) return;
    const last = st && st.last;
    const on = st && st.settings && st.settings.kind;
    pill.hidden = !on;
    if (!on) return;
    pill.classList.toggle('bad', !!(last && !last.ok));
    pill.querySelector('.label').textContent = !last ? 'Not backed up yet' : last.ok ? 'Backed up ' + when(last.when) : 'Backup failed ' + when(last.when);
    pill.title = last ? (last.message || '') : 'Backup & storage';
  }
  async function refreshPill() {
    try { renderPill(await FS.api.backup_status()); } catch (e) { /* no backup api (mock) */ }
  }

  async function backupNow(statusEl) {
    if (statusEl) statusEl.textContent = 'Backing up…';
    try {
      const r = await FS.api.backup_now();
      const msg = r.busy ? 'A backup is already running.' : (r.ok ? '✓ ' : '✕ ') + (r.message || '');
      if (statusEl) statusEl.textContent = msg;
      FS.toast(msg, r.ok ? 'ok' : r.busy ? 'warn' : 'error');
      return r;
    } catch (e) { if (statusEl) statusEl.textContent = '✕ ' + e.message; FS.toast(e.message, 'error'); return null; }
    finally { refreshPill(); }
  }

  async function open(opts) {
    opts = opts || {};
    let st;
    try { st = await FS.api.backup_status(); } catch (e) { FS.toast(e.message, 'error'); return; }
    const m = FS.modal({ title: 'Backup & storage', class: 'backup-modal' });
    m.box.setAttribute('data-test', 'backup-dialog');
    const s = Object.assign({}, st.settings);
    const sep = /\\/.test(st.notebook) ? '\\' : '/';
    const nbName = st.notebook.split(/[\\/]/).filter(Boolean).pop() || 'Notebook';

    /* ---------------------------------------------------------------- where */
    const where = el('div', { class: 'setting-block' }, el('h3', {}, 'Back up to'));
    const kindFolder = el('input', { type: 'radio', name: 'bk-kind', value: 'folder', checked: s.kind !== 's3', 'data-test': 'bk-kind-folder' });
    const kindS3 = el('input', { type: 'radio', name: 'bk-kind', value: 's3', checked: s.kind === 's3', 'data-test': 'bk-kind-s3' });
    where.append(
      el('label', { class: 'bk-choice' }, kindFolder, el('span', {}, el('b', {}, 'A cloud sync folder'), el('span', { class: 'muted small' }, ' — OneDrive, Google Drive, Dropbox…: their own program uploads what is written there. Nothing to sign in to here.'))),
      el('label', { class: 'bk-choice' }, kindS3, el('span', {}, el('b', {}, 'S3-compatible storage'), el('span', { class: 'muted small' }, ' — Amazon S3, Cloudflare R2, Backblaze B2, Wasabi, MinIO… through rclone, with your access keys.'))));

    // the folder
    const folderIn = el('input', { type: 'text', value: s.folder || '', placeholder: 'a folder inside OneDrive, Google Drive, Dropbox…', dir: 'auto', 'data-test': 'bk-folder', style: { flex: '1 1 auto', minWidth: '0' } });
    const browse = el('button', { class: 'btn', onclick: async () => { const p = await FS.api.backup_choose_folder(); if (p) folderIn.value = p; } }, 'Browse…');
    const clouds = el('div', { class: 'bk-clouds' });
    if (st.clouds.length) {
      clouds.append(el('div', { class: 'muted small' }, 'Found on this computer — click to use a folder in it:'));
      for (const c of st.clouds) {
        clouds.append(el('button', { class: 'bk-cloud', 'data-test': 'bk-cloud', title: c.path, onclick: () => { folderIn.value = c.path + sep + 'FLEx Scratchpad backup' + sep + nbName; } },
          el('span', { class: 'bk-cloud-ico' }, { onedrive: '☁', gdrive: '△', dropbox: '◆', icloud: '☁', box: '▢' }[c.service] || '☁'),
          el('span', {}, el('b', {}, c.label), el('span', { class: 'muted small', dir: 'auto' }, ' ' + c.path))));
      }
    } else clouds.append(el('div', { class: 'muted small' }, 'No OneDrive, Google Drive or Dropbox folder was found on this computer; choose any folder (an external drive works too).'));
    const folderBox = el('div', { class: 'bk-pane' }, clouds, el('div', { class: 'form-row' }, el('label', {}, 'Backup folder'), el('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', minWidth: '0' } }, folderIn, browse)));

    // S3
    const provider = el('select', { 'data-test': 'bk-provider' });
    for (const p of st.providers) provider.appendChild(el('option', { value: p.id, selected: p.id === s.provider }, p.label));
    const endpoint = el('input', { type: 'text', value: s.endpoint || '', 'data-test': 'bk-endpoint' });
    const region = el('input', { type: 'text', value: s.region || '' });
    const bucket = el('input', { type: 'text', value: s.bucket || '', 'data-test': 'bk-bucket' });
    const prefix = el('input', { type: 'text', value: s.prefix || nbName, 'data-test': 'bk-prefix' });
    const secretInput = (name, test) => el('input', { type: 'password', autocomplete: 'off', placeholder: st.secrets[name] ? '•••••• saved in ' + st.secretsWhere + ' (type to replace)' : '', 'data-test': test });
    const keyId = secretInput('access_key_id', 'bk-key-id');
    const keySecret = secretInput('secret_access_key', 'bk-key-secret');
    const hints = () => { const p = st.providers.find((x) => x.id === provider.value) || {}; endpoint.placeholder = p.endpoint || '(not needed for Amazon S3)'; region.placeholder = p.region || ''; };
    provider.addEventListener('change', hints); hints();
    const forgetKeys = el('button', { class: 'lnk', onclick: async () => { if (await FS.confirmAt(forgetKeys, 'Remove the access keys from ' + st.secretsWhere + '?', 'Remove')) { st = await FS.api.backup_save({}, {}, ['access_key_id', 'secret_access_key']); FS.toast('Keys removed'); m.close(); open(opts); } } }, 'Forget the keys');
    const s3Box = el('div', { class: 'bk-pane' },
      el('div', { class: 'form-row' }, el('label', {}, 'Provider'), provider),
      el('div', { class: 'form-row' }, el('label', {}, 'Endpoint'), endpoint),
      el('div', { class: 'form-row' }, el('label', {}, 'Region'), region),
      el('div', { class: 'form-row' }, el('label', {}, 'Bucket'), bucket),
      el('div', { class: 'form-row' }, el('label', {}, 'Folder in the bucket'), prefix),
      el('div', { class: 'form-row' }, el('label', {}, 'Access key ID'), keyId),
      el('div', { class: 'form-row' }, el('label', {}, 'Secret access key'), keySecret),
      el('div', { class: 'muted small' }, 'The keys are kept in ', el('b', {}, st.secretsWhere), ', never in a file of this program’s, and handed only to rclone when it runs. ',
        st.secrets.access_key_id || st.secrets.secret_access_key ? forgetKeys : null),
      st.rclone ? null : el('div', { class: 'flex-err' }, 'rclone was not found. It comes with the Windows download of FLEx Scratchpad.'));
    const showKind = () => { folderBox.hidden = !kindFolder.checked; s3Box.hidden = !kindS3.checked; };
    kindFolder.addEventListener('change', showKind); kindS3.addEventListener('change', showKind); showKind();
    where.append(folderBox, s3Box);

    // options
    const encrypt = el('input', { type: 'checkbox', checked: !!s.encrypt, 'data-test': 'bk-encrypt' });
    const pw1 = el('input', { type: 'password', autocomplete: 'new-password', placeholder: st.secrets.crypt_password ? '•••••• saved (type to replace)' : 'encryption password' });
    const pw2 = el('input', { type: 'password', autocomplete: 'new-password', placeholder: 'the same again' });
    const pwRow = el('div', { class: 'bk-pane' }, el('div', { class: 'form-row' }, el('label', {}, 'Password'), pw1), el('div', { class: 'form-row' }, el('label', {}, 'Repeat'), pw2),
      el('div', { class: 'bk-warn small' }, 'Keep this password somewhere safe, apart from this computer: without it nobody, you included, can read the backup. Changing it later starts a new, separate backup.'));
    encrypt.addEventListener('change', () => { pwRow.hidden = !encrypt.checked; });
    pwRow.hidden = !encrypt.checked;
    const onClose = el('input', { type: 'checkbox', checked: s.onClose !== false, 'data-test': 'bk-onclose' });
    const keep = el('select', { 'data-test': 'bk-keep' });
    for (const [v, l] of [[0, 'Keep them all'], [30, 'Keep them 30 days'], [90, 'Keep them 90 days'], [180, 'Keep them 6 months'], [365, 'Keep them a year']]) keep.appendChild(el('option', { value: v, selected: +s.keepDays === v }, l));
    const opt = el('div', { class: 'setting-block' }, el('h3', {}, 'Options'),
      el('label', { class: 'bk-check' }, onClose, 'Back up when FLEx Scratchpad closes (skipped when nothing changed, or offline)'),
      el('label', { class: 'bk-check' }, encrypt, 'Encrypt the files before they leave this computer (needs rclone)'), pwRow,
      el('div', { class: 'form-row' }, el('label', {}, 'Older versions'), keep),
      el('div', { class: 'muted small' }, 'Every backup keeps what it replaces or removes in a dated version, so an earlier state of a note can be got back. Linked files (attached as links) stay where they are and are not in the backup.'));

    // actions
    const status = el('div', { class: 'small bk-status', 'data-test': 'bk-status' }, st.last ? (st.last.ok ? '✓ Last backup ' : '✕ Last backup failed ') + when(st.last.when) + ': ' + (st.last.message || '') : 'Not backed up yet.');
    const collect = () => ({
      kind: kindS3.checked ? 's3' : 'folder', folder: folderIn.value.trim(), provider: provider.value, endpoint: endpoint.value.trim(), region: region.value.trim(),
      bucket: bucket.value.trim(), prefix: prefix.value.trim(), encrypt: encrypt.checked, onClose: onClose.checked, keepDays: +keep.value,
    });
    async function save() {
      if (encrypt.checked && (pw1.value || pw2.value) && pw1.value !== pw2.value) { FS.toast('The two passwords differ.', 'error'); return false; }
      const sec = {};
      if (keyId.value) sec.access_key_id = keyId.value;
      if (keySecret.value) sec.secret_access_key = keySecret.value;
      if (encrypt.checked && pw1.value) sec.crypt_password = pw1.value;
      try {
        st = await FS.api.backup_save(collect(), sec, []);
        keyId.value = keySecret.value = pw1.value = pw2.value = '';      // never kept in the page
        if (st.secrets.access_key_id) keyId.placeholder = '•••••• saved in ' + st.secretsWhere + ' (type to replace)';
        if (st.secrets.secret_access_key) keySecret.placeholder = '•••••• saved in ' + st.secretsWhere + ' (type to replace)';
        if (st.secrets.crypt_password) pw1.placeholder = '•••••• saved (type to replace)';
        status.textContent = st.ready ? 'Saved.' : 'Saved. Still needed: ' + st.missing.join(', ') + '.';
        refreshPill();
        return st.ready;
      } catch (e) { status.textContent = '✕ ' + e.message; return false; }
    }
    const actions = el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } },
      el('button', { class: 'btn', 'data-test': 'bk-save', onclick: save }, 'Save'),
      el('button', { class: 'btn', 'data-test': 'bk-test', onclick: async () => { if (!(await save())) return; status.textContent = 'Testing…'; const r = await FS.api.backup_test(); status.textContent = (r.ok ? '✓ ' : '✕ ') + r.message; } }, 'Test'),
      el('button', { class: 'btn primary', 'data-test': 'bk-now', onclick: async () => { if (!(await save())) return; await backupNow(status); loadBackupUsage(); } }, 'Back up now'));

    /* ---------------------------------------------------------------- storage */
    const storage = el('div', { class: 'setting-block', 'data-test': 'storage' }, el('h3', {}, 'Storage'));
    const nbBox = el('div', {}, el('div', { class: 'muted small' }, 'Measuring…'));
    const bkBox = el('div', { class: 'bk-usage' });
    storage.append(nbBox, bkBox);

    async function loadNotebookUsage() {
      let u;
      try { u = await FS.api.storage_usage(); } catch (e) { nbBox.textContent = e.message; return; }
      const parts = u.notebook.parts.filter((p) => p.bytes || p.files);
      const bar = el('div', { class: 'st-bar' });
      const COLORS = { notes: 'var(--accent)', attachments: '#0f766e', images: '#7c3aed', snapshots: '#b45309', clips: '#be185d', trash: '#6b7280', other: '#9aa3ae' };
      for (const p of parts) bar.appendChild(el('span', { title: p.label + ': ' + size(p.bytes), style: { flexGrow: String(Math.max(p.bytes, 1)), background: COLORS[p.id] } }));
      const parts_ = parts.find((p) => p.id === 'trash'), clips = parts.find((p) => p.id === 'clips');
      const act = (label, test, fn, confirm, danger) => el('button', { class: 'btn' + (danger ? ' danger' : ''), 'data-test': test, onclick: async (e) => {
        if (confirm && !(await FS.confirmAt(e.currentTarget, confirm, label))) return;
        try { const r = await fn(); FS.toast(label + ': ' + r.files + ' file(s), ' + size(r.bytes), 'ok'); } catch (err) { FS.toast(err.message, 'error'); }
        loadNotebookUsage();
      } }, label);
      nbBox.innerHTML = '';
      nbBox.append(
        el('div', { class: 'st-head' }, el('b', {}, 'This notebook: ' + size(u.notebook.total)), el('span', { class: 'muted small', dir: 'auto' }, ' ' + u.notebook.files + ' files in ' + u.path)),
        bar,
        el('div', { class: 'st-rows' }, ...parts.map((p) => el('div', { class: 'st-row' }, el('span', { class: 'st-dot', style: { background: COLORS[p.id] } }), el('span', {}, p.label), el('span', { class: 'muted' }, p.files + ' file' + (p.files === 1 ? '' : 's')), el('b', {}, size(p.bytes))))),
        el('div', { class: 'btn-row', style: { justifyContent: 'flex-start', flexWrap: 'wrap' } },
          u.unused.files ? act('Move ' + u.unused.files + ' unused attachment' + (u.unused.files === 1 ? '' : 's') + ' (' + size(u.unused.bytes) + ') to the trash', 'st-unused', () => FS.api.storage_trash_unused(),
            'Attached files no note uses any more: ' + u.unused.list.slice(0, 6).map((f) => f.name).join(', ') + (u.unused.files > 6 ? '…' : '') + '. They go to the trash.') : null,
          clips && clips.bytes ? act('Clear cached audio clips (' + size(clips.bytes) + ')', 'st-clips', () => FS.api.storage_clear_clips(), 'The clips are cut again from the recordings when an example plays; a clip whose recording is no longer on this computer cannot be.') : null,
          parts_ && parts_.bytes ? act('Empty the trash (' + size(parts_.bytes) + ')', 'st-trash', () => FS.api.storage_empty_trash(), 'Deleted notes and files in the trash are removed for good' + (st.settings.kind ? ' (older backups still have them).' : '.'), true) : null));
    }

    async function loadBackupUsage() {
      bkBox.innerHTML = '';
      if (!st.ready) { bkBox.append(el('div', { class: 'muted small' }, 'The backup’s size shows here once it is set up.')); return; }
      bkBox.append(el('div', { class: 'muted small' }, 'Measuring the backup…'));
      let u;
      try { u = await FS.api.backup_usage(); } catch (e) { bkBox.innerHTML = ''; bkBox.append(el('div', { class: 'flex-err' }, 'The backup could not be measured: ' + e.message)); return; }
      bkBox.innerHTML = '';
      const vsum = u.versions.reduce((a, v) => a + v.bytes, 0);
      const picks = new Set();
      const removeBtn = el('button', { class: 'btn danger', disabled: true, 'data-test': 'bk-prune', onclick: async (e) => {
        if (!(await FS.confirmAt(e.currentTarget, 'Remove ' + picks.size + ' older version' + (picks.size === 1 ? '' : 's') + ' from the backup for good? The current copy stays.', 'Remove'))) return;
        try { await FS.api.backup_prune([...picks], null); FS.toast('Removed', 'ok'); } catch (err) { FS.toast(err.message, 'error'); }
        loadBackupUsage();
      } }, 'Remove selected');
      const list = el('div', { class: 'bk-versions' });
      for (const v of u.versions) {
        const cb = el('input', { type: 'checkbox', 'data-test': 'bk-version-check', onchange: () => { if (cb.checked) picks.add(v.name); else picks.delete(v.name); removeBtn.disabled = !picks.size; removeBtn.textContent = picks.size ? 'Remove ' + picks.size + ' selected' : 'Remove selected'; } });
        list.append(el('label', { class: 'st-row', 'data-test': 'bk-version' }, cb, el('span', {}, verDate(v.name)), el('span', { class: 'muted' }, v.files + ' file' + (v.files === 1 ? '' : 's')), el('b', {}, size(v.bytes)),
          el('button', { class: 'lnk', title: 'Copy the files this backup set aside into a new folder', onclick: (e) => { e.preventDefault(); restore(v.name); } }, 'Restore…')));
      }
      bkBox.append(...[
        el('div', { class: 'st-head' }, el('b', {}, 'The backup: ' + size(u.total)), el('span', { class: 'muted small' }, ' the current copy ' + size(u.current.bytes) + ', ' + u.versions.length + ' older version' + (u.versions.length === 1 ? '' : 's') + ' ' + size(vsum))),
        el('div', { class: 'btn-row', style: { justifyContent: 'flex-start' } }, el('button', { class: 'btn', 'data-test': 'bk-restore', onclick: () => restore('') }, 'Restore the latest backup…'), u.versions.length ? removeBtn : null),
        u.versions.length ? el('div', { class: 'muted small' }, 'Each older version holds the files a backup replaced or removed on that day.') : null,
        list].filter(Boolean));
    }

    async function restore(version) {
      try {
        const r = await FS.api.backup_restore(version);
        if (!r) return;
        const mm = FS.modal({ title: 'Restored', class: 'narrow' });
        mm.body.append(el('p', {}, 'The ' + (version ? 'files of ' + verDate(version) : 'latest backup') + ' are in a new folder:'), el('p', {}, el('code', { dir: 'auto' }, r.path)),
          el('p', { class: 'muted small' }, 'Your notebook was not changed. Copy what you need back into it, or open the restored folder as a notebook.'),
          el('div', { class: 'btn-row' },
            !version && opts.onOpenNotebook ? el('button', { class: 'btn', onclick: async () => { mm.close(); m.close(); opts.onOpenNotebook(r.path); } }, 'Open it as the notebook') : null,
            el('button', { class: 'btn primary', onclick: () => mm.close() }, 'Close')));
      } catch (e) { FS.toast(e.message, 'error'); }
    }

    m.body.append(where, opt, el('div', { class: 'setting-block' }, actions, status), storage);
    loadNotebookUsage();
    loadBackupUsage();
    return m;
  }

  FS.backup = { open, refreshPill, renderPill, backupNow };
})();
