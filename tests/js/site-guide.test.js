// The user guide (docs/guide/index.html): every picture it names exists, every in-page link lands,
// the contents list the sections, and the home page links to it (Seth, 2026-10-20: "thorough
// documentation with screenshots … a clear sort of table of contents … in the user-facing website").
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const DOCS = path.join(__dirname, '..', '..', 'docs');
const html = fs.readFileSync(path.join(DOCS, 'guide', 'index.html'), 'utf8');

test('every picture the guide shows is in docs/media/guide', () => {
  const imgs = [...html.matchAll(/src="\.\.\/media\/guide\/([^"]+)"/g)].map((m) => m[1]);
  assert.ok(imgs.length >= 40, `only ${imgs.length} pictures`);
  const missing = imgs.filter((f) => !fs.existsSync(path.join(DOCS, 'media', 'guide', f)));
  assert.deepEqual(missing, []);
  const unused = fs.readdirSync(path.join(DOCS, 'media', 'guide')).filter((f) => f.endsWith('.webp') && !imgs.includes(f));
  assert.deepEqual(unused, []);
  // every picture has a caption and an alt text that says what it shows
  for (const m of html.matchAll(/<img src="\.\.\/media\/guide\/[^"]+"[^>]*>/g)) assert.match(m[0], /alt="[^"]{20,}"/, m[0]);
});

test('every in-page link lands on an id, and the contents name the sections', () => {
  const ids = new Set([...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]));
  const hrefs = [...html.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(hrefs.filter((h) => !ids.has(h)), []);
  const toc = html.slice(html.indexOf('<nav class="toc"'), html.indexOf('</nav>', html.indexOf('<nav class="toc"')));
  const tocIds = [...toc.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
  const sections = [...html.matchAll(/<section id="([^"]+)"/g)].map((m) => m[1]);
  for (const s of sections) assert.ok(tocIds.includes(s), `section ${s} is not in the contents`);
  const h3s = [...html.matchAll(/<h3 id="([^"]+)"/g)].map((m) => m[1]);
  for (const h of h3s) assert.ok(tocIds.includes(h), `heading ${h} is not in the contents`);
  // the mobile contents list the same sections
  const mob = html.slice(html.indexOf('<details class="toc-mobile"'), html.indexOf('</details>'));
  for (const s of sections) assert.ok(mob.includes(`href="#${s}"`), `section ${s} is not in the mobile contents`);
});

test('the guide describes the one current release, with no version flags', () => {
  // Seth, 2026-10-20 (0.1.0, the first full release): "no need for version chips now, all version are just the
  // current release, with no beta in the tag"
  assert.ok(html.includes('Describes FLEx Scratchpad <b>0.1.0</b>, the current release'));
  assert.ok(!/<span class="rel /.test(html), 'a version flag is left');
  assert.ok(!/id="legend"|id="get-next"/.test(html), 'the legend or the development-version dialog is left');
  assert.ok(!/beta|pre-release/i.test(html.replace(/class="beta-band"/g, '')), 'a beta or pre-release is still mentioned');
  assert.ok(!/data-dl="version"/.test(html), 'the guide names its version itself, not the newest download');
});

test('the home page links to the guide, and the guide back', () => {
  const home = fs.readFileSync(path.join(DOCS, 'index.html'), 'utf8');
  assert.ok(home.includes('href="guide/"'));
  assert.ok(html.includes('href="../"') && html.includes('../assets/site.css') && html.includes('../assets/guide.css'));
  assert.ok(fs.existsSync(path.join(DOCS, 'assets', 'guide.css')));
});
