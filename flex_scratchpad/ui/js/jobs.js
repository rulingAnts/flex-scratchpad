/* FLEx Scratchpad — long work in a QUEUE with a progress bar (Seth, 2026-10-20: "Any time the user
 * clicks a button and something takes awhile to load, our UI shouldn't just do nothing … there should
 * be some kind of status indicator"; "building an export could take a long time. Our app should queue
 * that and have progress bars … similar to the Flex project connection and backup status").
 *
 *   FS.jobs.run(label, async (job) => { job.step(text, done, total); …; return job.done(result) })
 *
 * One job runs at a time, the rest wait their turn; the sidebar's #jobs-pill (beside the FLEx and
 * backup pills) shows the running one at once — an animated stripe until a step reports a count, then
 * the bar — with "+N waiting", and a click lists them all (a waiting job can be taken out, the running
 * one asked to stop). Python reports steps for the job it is working on as `py:job` events
 * ({job, text, done, total}; Api._job). A finished job stays in the list with what it made.
 *
 * FS.working: the plain "Working…" sign for any API call that takes longer than a moment (api.js),
 * so a click that waits on Python is never silent. */
(function () {
  const { el } = FS;
  const queue = [];
  let running = null;
  const finished = [];
  let seq = 0;
  let hideTimer = 0;

  function pill() { return document.getElementById('jobs-pill'); }
  function pct(j) { return j && j.total ? Math.max(0, Math.min(100, Math.round((j.doneN / j.total) * 100))) : null; }

  function render() {
    const p = pill();
    if (!p) return;
    clearTimeout(hideTimer);
    const last = finished[0];
    const active = running || queue[0];
    p.hidden = !active && !(last && Date.now() - last.endedAt < 8000);
    if (p.hidden) return;
    const label = p.querySelector('.label'), track = p.querySelector('.jb-track'), fill = p.querySelector('.jb-fill'), wait = p.querySelector('.jb-wait');
    p.classList.toggle('running', !!active);
    p.classList.toggle('bad', !active && !!(last && last.error));
    p.classList.toggle('ok', !active && !!(last && !last.error && last.result != null));
    if (active) {
      const j = running || queue[0];
      const v = pct(j);
      track.classList.toggle('indeterminate', v == null);
      fill.style.width = v == null ? '' : v + '%';
      // what is being made, short ("Word: Preparing the recordings 7 of 23"), the whole of it in the tooltip
      const what = (j.label.match(/ to (?:a |an )?(.+)$/) || [])[1] || '';
      label.textContent = (what ? what.charAt(0).toUpperCase() + what.slice(1) + ': ' : '') + (j === running ? (j.text || 'Starting…') : 'waiting');
      wait.hidden = !queue.length || (!running && queue.length === 1);
      wait.textContent = '+' + (running ? queue.length : queue.length - 1);
      wait.title = (running ? queue.length : queue.length - 1) + ' more waiting their turn';
      p.title = j.label + (j.text ? ' — ' + j.text : '') + '. Click for the list.';
    } else {
      track.classList.remove('indeterminate');
      fill.style.width = '100%';
      wait.hidden = true;
      label.textContent = last.error ? (last.error === 'Stopped' ? '■ ' + last.label + ' stopped' : '✕ ' + last.label + ' failed') : last.result == null ? last.label + ' — cancelled' : '✓ ' + last.label.replace(/^Export/, 'Exported');
      p.title = last.error ? last.error : (last.result && typeof last.result === 'string' ? last.result : 'Done');
      hideTimer = setTimeout(render, 8100 - (Date.now() - last.endedAt));
    }
    if (listHost && listHost.isConnected) drawList(listHost);
  }

  let listHost = null;
  function drawList(host) {
    host.innerHTML = '';
    const row = (j, state) => {
      const v = pct(j);
      const bar = el('div', { class: 'jb-track' + (state === 'running' && v == null ? ' indeterminate' : '') }, el('div', { class: 'jb-fill', style: { width: state === 'running' ? (v == null ? '' : v + '%') : state === 'waiting' ? '0%' : '100%' } }));
      const r = el('div', { class: 'job-row ' + state + (j.error ? ' bad' : ''), 'data-test': 'job-row' },
        el('div', { class: 'job-head' }, el('b', {}, j.label), el('span', { class: 'spacer' }),
          state === 'waiting' ? el('button', { class: 'btn small', 'data-test': 'job-remove', onclick: () => { const i = queue.indexOf(j); if (i >= 0) { queue.splice(i, 1); j.reject(new Error('cancelled')); render(); } } }, 'Remove') : null,
          state === 'running' ? el('button', { class: 'btn small', 'data-test': 'job-stop', disabled: j.cancelled, onclick: () => { j.cancelled = true; j.text = 'Stopping…'; render(); } }, j.cancelled ? 'Stopping…' : 'Stop') : null),
        bar,
        el('div', { class: 'small muted' }, state === 'waiting' ? 'Waiting its turn' : state === 'running' ? (j.text || 'Starting…') : j.error ? j.error : j.result == null ? 'Cancelled' : (typeof j.result === 'string' ? 'Saved ' + j.result : 'Done') + ' · ' + new Date(j.endedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })));
      host.appendChild(r);
    };
    if (running) row(running, 'running');
    for (const j of queue) row(j, 'waiting');
    for (const j of finished) row(j, 'done');
    if (!running && !queue.length && !finished.length) host.appendChild(el('p', { class: 'muted small' }, 'Nothing is running.'));
  }
  function openList() {
    const p = pill();
    if (!p) return;
    FS.popover(p, (pop) => { listHost = el('div', { class: 'jobs-list', 'data-test': 'jobs-list' }); drawList(listHost); pop.appendChild(listHost); }, { title: 'Exports and other work' });
  }

  async function next() {
    if (running || !queue.length) return;
    const j = running = queue.shift();
    j.text = 'Starting…';
    render();
    try {
      const r = await j.fn(j);
      j.result = r === undefined ? j.result : r;
      j.resolve(j.result);
    } catch (e) {
      const msg = e && e.message === 'cancelled' ? 'Stopped' : (e && e.message) || String(e);
      j.error = msg;
      if (msg !== 'Stopped') FS.toast(j.label + ' failed: ' + msg, 'error');
      j.resolve(null);
    }
    j.endedAt = Date.now();
    running = null;
    finished.unshift(j);
    if (finished.length > 8) finished.length = 8;
    render();
    next();
  }

  function run(label, fn) {
    const j = { id: 'j' + (++seq) + '-' + Date.now().toString(36), label, fn, text: '', doneN: 0, total: 0, cancelled: false };
    j.step = (text, done, total) => { if (text) j.text = text; if (total != null) { j.total = total; j.doneN = done || 0; } else { j.total = 0; j.doneN = 0; } render(); };
    j.done = (result) => { j.result = result; return result; };
    const promise = new Promise((resolve, reject) => { j.resolve = resolve; j.reject = reject; });
    promise.catch(() => {});
    queue.push(j);
    render();                                  // the click registers at once: the pill shows before any work
    if (queue.length > 1 || running) FS.toast(label + ' — waiting its turn (' + (queue.length + (running ? 1 : 0) - 1) + ' ahead).');
    setTimeout(next, 0);
    return promise;
  }

  // Python's steps for the job it is working on
  FS.on('py:job', (d) => {
    if (!d || !running || d.job !== running.id) return;
    if (d.text) running.text = d.text;
    if (d.total != null) { running.total = d.total; running.doneN = d.done || 0; } else if (d.step === 'write') { running.total = 0; running.doneN = 0; }
    render();
  });

  /* ------------------------------------------------------------------ FS.working */
  let pending = 0;
  function working(on) {
    pending = Math.max(0, pending + (on ? 1 : -1));
    const w = document.getElementById('working-pill');
    document.body && document.body.classList.toggle('fs-working', pending > 0);
    if (w) w.hidden = pending === 0;
  }

  FS.jobs = { run, list: () => ({ running, queue: queue.slice(), finished: finished.slice() }), openList };
  FS.working = working;
  document.addEventListener('DOMContentLoaded', () => { const p = pill(); if (p) p.addEventListener('click', openList); });
})();
