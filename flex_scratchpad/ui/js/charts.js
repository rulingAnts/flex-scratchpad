/* charts.js — the ```chart block: a small readable DSL drawn on a canvas. No dependencies.
 *
 *   ```chart
 *   type: bar            bar | stacked | line | pie | donut | hbar
 *   title: Vowel counts
 *   labels: a, e, i, o, u
 *   series: tokens = 12, 5, 8, 3, 2
 *   series: types = 4, 2, 3, 1, 1
 *   colors: #2f6fdb, #0f766e
 *   ylabel: count
 *   legend: right          top | right | none
 *   ```
 * A JSON object is accepted too ({"type":"bar", ...}). */
(function () {
  'use strict';
  const FS = (window.FS = window.FS || {});
  const { el } = FS;

  const PALETTE = ['#2f6fdb', '#0f766e', '#b45309', '#7c3aed', '#be185d', '#4d7c0f', '#0e7490', '#9f1239', '#6b7280'];

  function parse(src) {
    const body = String(src || '').replace(/^\s*```\s*chart\s*\n?/, '').replace(/\n?\s*```\s*$/, '').trim();
    if (!body) return { type: 'bar', title: '', labels: [], series: [], colors: [], ylabel: '', legend: 'top', errors: [] };
    if (body.startsWith('{')) {
      try { const j = JSON.parse(body); return normalize(j); } catch (e) { return { errors: ['Invalid JSON: ' + e.message], series: [], labels: [] }; }
    }
    const spec = { type: 'bar', title: '', labels: [], series: [], colors: [], ylabel: '', xlabel: '', legend: 'top', errors: [] };
    for (const raw of body.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const m = /^([\w-]+)\s*:\s*(.*)$/.exec(line);
      if (!m) { spec.errors.push('Cannot read line: ' + line); continue; }
      const k = m[1].toLowerCase(), v = m[2].trim();
      if (k === 'series') {
        const sm = /^(.*?)\s*=\s*(.*)$/.exec(v);
        const name = sm ? sm[1].trim() : 'series ' + (spec.series.length + 1);
        const nums = (sm ? sm[2] : v).split(/[,\s]+/).filter(Boolean).map((x) => { const n = parseFloat(x.replace(/[^\d.eE+-]/g, '')); return isNaN(n) ? null : n; });
        spec.series.push({ name, values: nums });
      } else if (k === 'labels') spec.labels = v.split(',').map((s) => s.trim()).filter((s) => s !== '');
      else if (k === 'colors' || k === 'colours') spec.colors = v.split(',').map((s) => s.trim()).filter(Boolean);
      else if (k === 'type') spec.type = v.toLowerCase();
      else spec[k] = v;
    }
    return normalize(spec);
  }

  function normalize(spec) {
    spec.errors = spec.errors || [];
    spec.type = ['bar', 'stacked', 'line', 'pie', 'donut', 'hbar', 'area'].includes(spec.type) ? spec.type : 'bar';
    spec.series = (spec.series || []).map((s, i) => ({ name: s.name || 'series ' + (i + 1), values: (s.values || s.data || []).map((x) => (typeof x === 'number' ? x : parseFloat(x))).map((x) => (isNaN(x) ? null : x)) }));
    spec.labels = spec.labels || [];
    const n = Math.max(spec.labels.length, ...spec.series.map((s) => s.values.length), 0);
    while (spec.labels.length < n) spec.labels.push(String(spec.labels.length + 1));
    spec.colors = spec.colors || [];
    spec.legend = spec.legend || 'top';
    if (!spec.series.length) spec.errors.push('Add at least one "series: name = 1, 2, 3" line.');
    return spec;
  }

  function serialize(spec) {
    const lines = ['```chart', 'type: ' + spec.type];
    if (spec.title) lines.push('title: ' + spec.title);
    if (spec.labels.length) lines.push('labels: ' + spec.labels.join(', '));
    for (const s of spec.series) lines.push('series: ' + s.name + ' = ' + s.values.map((v) => (v == null ? '' : v)).join(', '));
    if (spec.colors && spec.colors.length) lines.push('colors: ' + spec.colors.join(', '));
    if (spec.ylabel) lines.push('ylabel: ' + spec.ylabel);
    if (spec.xlabel) lines.push('xlabel: ' + spec.xlabel);
    if (spec.legend && spec.legend !== 'top') lines.push('legend: ' + spec.legend);
    lines.push('```');
    return lines.join('\n');
  }

  /* ------------------------------------------------------------------ drawing */
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function draw(canvas, spec, width) {
    const dpr = window.devicePixelRatio || 1;
    const W = width || canvas.clientWidth || 640;
    const H = spec.type === 'pie' || spec.type === 'donut' ? Math.min(360, Math.max(220, W * 0.55)) : Math.min(380, Math.max(200, W * 0.5));
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    const text = cssVar('--text', '#1a1d21'), muted = cssVar('--muted', '#68717d'), grid = cssVar('--border-soft', '#e8ebef');
    const font = '12px ' + cssVar('--font', 'sans-serif');
    ctx.font = font; ctx.textBaseline = 'middle';
    const colors = (i) => (spec.colors && spec.colors[i]) || PALETTE[i % PALETTE.length];
    let top = 10;
    if (spec.title) { ctx.fillStyle = text; ctx.font = '600 14px ' + cssVar('--font', 'sans-serif'); ctx.textAlign = 'left'; ctx.fillText(spec.title, 12, top + 8); top += 26; ctx.font = font; }
    // legend
    const showLegend = spec.legend !== 'none' && (spec.series.length > 1 || spec.type === 'pie' || spec.type === 'donut');
    let legendRight = 0;
    if (showLegend) {
      const items = (spec.type === 'pie' || spec.type === 'donut') ? spec.labels.map((l, i) => ({ name: l, color: colors(i) })) : spec.series.map((s, i) => ({ name: s.name, color: colors(i) }));
      if (spec.legend === 'right') {
        legendRight = Math.min(200, Math.max(...items.map((it) => ctx.measureText(it.name).width)) + 30);
        let y = top + 10;
        for (const it of items) { ctx.fillStyle = it.color; ctx.fillRect(W - legendRight + 4, y - 5, 10, 10); ctx.fillStyle = muted; ctx.textAlign = 'left'; ctx.fillText(it.name, W - legendRight + 20, y); y += 18; }
      } else {
        let x = 12;
        for (const it of items) { const w = ctx.measureText(it.name).width; if (x + w + 24 > W) break; ctx.fillStyle = it.color; ctx.fillRect(x, top + 2, 10, 10); ctx.fillStyle = muted; ctx.textAlign = 'left'; ctx.fillText(it.name, x + 14, top + 7); x += w + 28; }
        top += 22;
      }
    }
    if (spec.type === 'pie' || spec.type === 'donut') return drawPie(ctx, spec, W - legendRight, H, top, colors, text, muted);
    const hbar = spec.type === 'hbar';
    const left = 44 + (spec.ylabel && !hbar ? 16 : 0) + (hbar ? Math.min(140, Math.max(...spec.labels.map((l) => ctx.measureText(l).width)) + 10) : 0);
    const bottom = H - 30 - (spec.xlabel ? 16 : 0);
    const right = W - 14 - legendRight;
    const plotW = right - left, plotH = bottom - top;
    const n = spec.labels.length;
    const stacked = spec.type === 'stacked';
    let max = 0, min = 0;
    for (let i = 0; i < n; i++) {
      if (stacked) { let pos = 0, neg = 0; for (const s of spec.series) { const v = s.values[i] || 0; if (v >= 0) pos += v; else neg += v; } max = Math.max(max, pos); min = Math.min(min, neg); }
      else for (const s of spec.series) { const v = s.values[i]; if (v != null) { max = Math.max(max, v); min = Math.min(min, v); } }
    }
    if (max === 0 && min === 0) max = 1;
    const step = niceStep((max - min) / 5);
    max = Math.ceil(max / step) * step; min = Math.floor(min / step) * step;
    const vTo = (v) => hbar ? left + ((v - min) / (max - min)) * plotW : bottom - ((v - min) / (max - min)) * plotH;
    // grid + axis labels
    ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.fillStyle = muted;
    for (let v = min; v <= max + 1e-9; v += step) {
      const p = vTo(v);
      ctx.beginPath();
      if (hbar) { ctx.moveTo(p, top); ctx.lineTo(p, bottom); ctx.stroke(); ctx.textAlign = 'center'; ctx.fillText(fmt(v), p, bottom + 12); }
      else { ctx.moveTo(left, p); ctx.lineTo(right, p); ctx.stroke(); ctx.textAlign = 'right'; ctx.fillText(fmt(v), left - 6, p); }
    }
    if (spec.ylabel) { ctx.save(); ctx.translate(12, (top + bottom) / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center'; ctx.fillStyle = muted; ctx.fillText(spec.ylabel, 0, 0); ctx.restore(); }
    if (spec.xlabel) { ctx.textAlign = 'center'; ctx.fillStyle = muted; ctx.fillText(spec.xlabel, (left + right) / 2, H - 8); }
    const slot = (hbar ? plotH : plotW) / Math.max(1, n);
    // category labels
    ctx.fillStyle = text; ctx.textAlign = hbar ? 'right' : 'center';
    spec.labels.forEach((lab, i) => {
      if (hbar) ctx.fillText(trunc(ctx, lab, left - 12), left - 6, top + slot * (i + 0.5));
      else { const c = left + slot * (i + 0.5); ctx.fillText(trunc(ctx, lab, slot - 4), c, bottom + 12); }
    });
    if (spec.type === 'line' || spec.type === 'area') {
      spec.series.forEach((s, si) => {
        ctx.strokeStyle = colors(si); ctx.fillStyle = colors(si); ctx.lineWidth = 2;
        ctx.beginPath();
        let started = false;
        s.values.forEach((v, i) => { if (v == null) { started = false; return; } const x = left + slot * (i + 0.5), y = vTo(v); if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); });
        ctx.stroke();
        if (spec.type === 'area') { ctx.globalAlpha = 0.15; ctx.lineTo(left + slot * (s.values.length - 0.5), vTo(Math.max(0, min))); ctx.lineTo(left + slot * 0.5, vTo(Math.max(0, min))); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1; }
        s.values.forEach((v, i) => { if (v == null) return; ctx.beginPath(); ctx.arc(left + slot * (i + 0.5), vTo(v), 3.5, 0, Math.PI * 2); ctx.fill(); });
      });
      return;
    }
    const groups = stacked ? 1 : spec.series.length;
    const bw = Math.max(2, (slot * 0.72) / groups);
    const base = vTo(Math.max(0, Math.min(0, min)) >= min ? 0 : min);
    for (let i = 0; i < n; i++) {
      let accPos = 0, accNeg = 0;
      spec.series.forEach((s, si) => {
        const v = s.values[i];
        if (v == null) return;
        ctx.fillStyle = colors(si);
        if (stacked) {
          const from = v >= 0 ? accPos : accNeg, to = from + v;
          if (v >= 0) accPos = to; else accNeg = to;
          rect(ctx, hbar, left, top, slot, i, 0, 1, bw, vTo(from), vTo(to));
        } else rect(ctx, hbar, left, top, slot, i, si, groups, bw, base, vTo(v));
      });
    }
    // axis line
    ctx.strokeStyle = cssVar('--border', '#d9dde3');
    ctx.beginPath();
    if (hbar) { ctx.moveTo(left, top); ctx.lineTo(left, bottom); } else { ctx.moveTo(left, bottom); ctx.lineTo(right, bottom); }
    ctx.stroke();
  }

  function rect(ctx, hbar, left, top, slot, i, si, groups, bw, p0, p1) {
    const offset = slot * 0.14 + si * bw;
    if (hbar) ctx.fillRect(Math.min(p0, p1), top + slot * i + offset, Math.abs(p1 - p0), bw - 1);
    else ctx.fillRect(left + slot * i + offset, Math.min(p0, p1), bw - 1, Math.abs(p1 - p0));
  }

  function drawPie(ctx, spec, W, H, top, colors, text, muted) {
    const s = spec.series[0];
    if (!s) return;
    const total = s.values.reduce((a, b) => a + (b > 0 ? b : 0), 0) || 1;
    const cx = W / 2, cy = top + (H - top) / 2, r = Math.min(W, H - top) / 2 - 24;
    let a0 = -Math.PI / 2;
    s.values.forEach((v, i) => {
      if (!(v > 0)) return;
      const a1 = a0 + (v / total) * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, r, a0, a1); ctx.closePath();
      ctx.fillStyle = colors(i); ctx.fill();
      ctx.strokeStyle = cssVar('--bg', '#fff'); ctx.lineWidth = 2; ctx.stroke();
      const mid = (a0 + a1) / 2, lx = cx + Math.cos(mid) * (r * 0.72), ly = cy + Math.sin(mid) * (r * 0.72);
      if ((a1 - a0) > 0.25) { ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.font = '600 12px ' + cssVar('--font', 'sans-serif'); ctx.fillText(Math.round((v / total) * 100) + '%', lx, ly); }
      a0 = a1;
    });
    if (spec.type === 'donut') { ctx.beginPath(); ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2); ctx.fillStyle = cssVar('--bg', '#fff'); ctx.fill(); ctx.fillStyle = text; ctx.textAlign = 'center'; ctx.font = '600 16px ' + cssVar('--font', 'sans-serif'); ctx.fillText(fmt(total), cx, cy); }
  }

  function niceStep(raw) {
    if (!(raw > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function fmt(v) { return Math.abs(v) >= 1000 ? v.toLocaleString() : (Math.round(v * 100) / 100).toString(); }
  function trunc(ctx, s, w) { if (ctx.measureText(s).width <= w) return s; while (s.length > 1 && ctx.measureText(s + '…').width > w) s = s.slice(0, -1); return s + '…'; }

  /* ------------------------------------------------------------------ widget */
  function render(container, src, opts) {
    opts = opts || {};
    const spec = parse(src);
    container.innerHTML = '';
    const box = el('div', { class: 'chart-box' });
    if (spec.errors && spec.errors.length) box.appendChild(el('div', { class: 'chart-err' }, spec.errors.join(' ')));
    const canvas = el('canvas');
    box.appendChild(canvas);
    container.appendChild(box);
    const paint = () => { try { draw(canvas, spec, Math.min(760, box.clientWidth - 16)); } catch (e) { box.appendChild(el('div', { class: 'chart-err' }, 'Chart error: ' + e.message)); } };
    requestAnimationFrame(paint);
    if (window.ResizeObserver) { const ro = new ResizeObserver(() => paint()); ro.observe(box); }
    if (opts.onEdit) canvas.addEventListener('dblclick', () => opts.onEdit());
    return { spec, repaint: paint };
  }

  /* Edit form → new source. */
  function editDialog(src, onSave) {
    const spec = parse(src);
    const m = FS.modal({ title: 'Chart', class: 'narrow' });
    const type = el('select');
    for (const t of ['bar', 'stacked', 'hbar', 'line', 'area', 'pie', 'donut']) type.appendChild(el('option', { value: t, selected: t === spec.type }, t));
    const title = el('input', { type: 'text', value: spec.title || '' });
    const labels = el('input', { type: 'text', value: spec.labels.join(', ') });
    const series = el('textarea', {}, spec.series.map((s) => s.name + ' = ' + s.values.map((v) => (v == null ? '' : v)).join(', ')).join('\n'));
    const ylabel = el('input', { type: 'text', value: spec.ylabel || '' });
    const legend = el('select');
    for (const t of ['top', 'right', 'none']) legend.appendChild(el('option', { value: t, selected: t === spec.legend }, t));
    const form = el('div', { class: 'chart-form' },
      el('label', {}, 'Type'), type, el('label', {}, 'Title'), title, el('label', {}, 'Labels'), labels,
      el('label', {}, 'Series'), series, el('label', {}, 'Y label'), ylabel, el('label', {}, 'Legend'), legend);
    m.body.appendChild(form);
    m.body.appendChild(el('div', { class: 'hint small muted', style: { marginTop: '6px' } }, 'One series per line: name = v1, v2, v3'));
    m.body.appendChild(el('div', { class: 'btn-row' },
      el('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'),
      el('button', { class: 'btn primary', onclick: () => {
        const out = { type: type.value, title: title.value.trim(), labels: labels.value.split(',').map((s) => s.trim()).filter(Boolean), series: [], colors: spec.colors, ylabel: ylabel.value.trim(), xlabel: spec.xlabel, legend: legend.value };
        for (const line of series.value.split('\n')) { const sm = /^(.*?)\s*=\s*(.*)$/.exec(line.trim()); if (!sm) continue; out.series.push({ name: sm[1].trim(), values: sm[2].split(/[,\s]+/).filter(Boolean).map((x) => parseFloat(x)) }); }
        onSave(serialize(normalize(out)));
        m.close();
      } }, 'Save')));
    return m;
  }

  FS.charts = { parse, serialize, draw, render, editDialog, PALETTE, template: () => '```chart\ntype: bar\ntitle: Counts\nlabels: a, b, c\nseries: count = 3, 5, 2\n```' };
})();
