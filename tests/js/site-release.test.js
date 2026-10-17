// The site's download links (docs/assets/release.js): the newest release that has BOTH files.
const test = require('node:test');
const assert = require('node:assert');
const { pickRelease } = require('../../docs/assets/release.js');

const R = 'https://github.com/rulingAnts/flex-scratchpad/releases/';
const rel = (tag, d, files, extra) => Object.assign({ tag_name: tag, published_at: d, html_url: R + 'tag/' + tag,
  assets: files.map((n) => ({ name: n, browser_download_url: R + 'download/' + tag + '/' + n })) }, extra || {});

test('the newest release with both downloads wins; drafts, half-empty and foreign releases do not', () => {
  const list = [
    rel('v0.1.0-beta.2', '2026-10-20T00:00:00Z', ['FLEx-Scratchpad-Setup-0.1.0-beta.2.exe']),           // the zip is missing
    rel('v0.1.0-beta.1', '2026-10-17T00:00:00Z', ['FLEx-Scratchpad-Setup-0.1.0-beta.1.exe', 'FLEx-Scratchpad-0.1.0-beta.1-windows-portable.zip']),
    rel('v0.1.0-beta.3', '2026-10-21T00:00:00Z', ['FLEx-Scratchpad-Setup-0.1.0-beta.3.exe', 'FLEx-Scratchpad-0.1.0-beta.3-windows-portable.zip'], { draft: true }),
    Object.assign(rel('v9', '2026-10-22T00:00:00Z', ['FLEx-Scratchpad-Setup-9.exe', 'FLEx-Scratchpad-9-windows-portable.zip']), { html_url: 'https://example.com/x' }),
  ];
  const l = pickRelease(list);
  assert.equal(l.version, '0.1.0-beta.1');
  assert.ok(l.exe.endsWith('/v0.1.0-beta.1/FLEx-Scratchpad-Setup-0.1.0-beta.1.exe'));
  assert.ok(l.zip.endsWith('-windows-portable.zip') && l.notes.endsWith('/tag/v0.1.0-beta.1'));
  assert.equal(pickRelease([]), null);
  assert.equal(pickRelease({ message: 'rate limited' }), null);
});
