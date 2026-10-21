// The site's download links (docs/assets/release.js): the newest release that has BOTH files.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { pickRelease, pickReleases } = require('../../docs/assets/release.js');

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

test('the current release and the pre-release newer than it are both offered (Seth, 2026-10-20: "the buttons should offer both")', () => {
  const both = (tag) => ['FLEx-Scratchpad-Setup-' + tag.slice(1) + '.exe', 'FLEx-Scratchpad-' + tag.slice(1) + '-windows-portable.zip'];
  const list = [
    rel('v0.1.0-beta.1', '2026-10-17T02:00:00Z', both('v0.1.0-beta.1'), { prerelease: true }),
    rel('v0.1.0-beta.2', '2026-10-17T11:00:00Z', both('v0.1.0-beta.2'), { prerelease: false }),
    rel('v0.1.0-beta.3', '2026-10-19T23:00:00Z', both('v0.1.0-beta.3'), { prerelease: true }),
    rel('v0.1.0-beta.4', '2026-10-20T23:00:00Z', ['FLEx-Scratchpad-Setup-0.1.0-beta.4.exe'], { prerelease: true }),   // the zip is missing
  ];
  const r = pickReleases(list);
  assert.equal(r.release.version, '0.1.0-beta.2');
  assert.equal(r.pre.version, '0.1.0-beta.3');
  assert.ok(r.pre.exe.endsWith('/v0.1.0-beta.3/FLEx-Scratchpad-Setup-0.1.0-beta.3.exe') && r.pre.notes.endsWith('/tag/v0.1.0-beta.3'));
  assert.equal(pickRelease(list).version, '0.1.0-beta.2');
  // a pre-release older than the release is not offered; with no full release the newest pre-release stands in
  assert.equal(pickReleases(list.slice(0, 2)).pre, null);
  const onlyPre = pickReleases([list[0], list[2]]);
  assert.equal(onlyPre.release.version, '0.1.0-beta.3');
  assert.equal(onlyPre.pre, null);
  assert.equal(pickReleases([]), null);
});

test('the home page carries the release\'s links and one pre-release button, and only known keys', () => {
  // Seth, 2026-10-20: "have just one download button that points to it" (0.1.0, a full release); then "push
  // another pre-release (and add a download button for it on the main page)" — beside the release, hidden by
  // release.js whenever no pre-release is newer than the release
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'docs', 'index.html'), 'utf8');
  const keys = [...html.matchAll(/data-dl="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(keys.filter((k) => !['exe', 'zip', 'notes', 'version', 'pre-exe', 'pre-notes', 'pre-version'].includes(k)), []);
  for (const k of ['exe', 'zip', 'pre-exe']) assert.ok(keys.includes(k), k);
  const hero = [...html.matchAll(/<section class="hero">[\s\S]*?<\/section>/g)][0][0];
  assert.equal(hero.match(/data-dl="exe"/g).length, 1, 'one release download button in the hero');
  assert.equal(hero.match(/data-dl="pre-exe"/g).length, 1, 'one pre-release download button in the hero');
  assert.ok(/<a [^>]*data-pre[^>]*data-dl="pre-exe"/.test(hero), 'the pre-release button hides itself when there is none');
  assert.ok(!/beta/i.test(html.replace(/class="beta-band"/g, '').replace(/<[^>]*data-pre[\s\S]*?<\/(a|p)>/g, '')), 'a beta outside the pre-release links');
});
