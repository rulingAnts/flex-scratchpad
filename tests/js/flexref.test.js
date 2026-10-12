const test = require('node:test');
// legacy (loose) assert: the scripts run in their own vm context, so their arrays and objects
// have different prototypes from the test's — strict deepEqual would reject every structure.
const assert = require('node:assert');
const { load } = require('./load.js');

const FS = load(['util', 'flexref']);
const R = FS.flexref;
const G = '9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001';

const text = {
  segments: [
    { n: 1, words: [{ txt: 'Kabir', morphs: [{ form: 'kabir', gls: 'dog' }] }, { txt: 'ka-nuwa-mo', gls: 'slept', morphs: [{ form: 'ka-', gls: '3SG' }, { form: 'nuwa', gls: 'sleep' }, { form: '-mo', gls: 'PST' }] }, { txt: '.', punct: true }], free: 'The dog slept.' },
    { n: 2, words: [{ txt: 'Haŋa' }, { txt: 'tiket' }, { txt: 'ka-sila-mo', morphs: [{ form: 'ka-' }, { form: 'sila' }, { form: '-mo' }] }], free: 'Yesterday.' },
  ],
};

test('parse + serialize round trip', () => {
  const src = '{{flex:text ' + G + ' seg=1-2 lines=txt,gls,ft hl=1.2,2.1-2.3 b[#f00]=gls:1.1 u=morph:"-mo" i=*"a" s=ft:2 color[red]=1.1:2-3 "my label"}}';
  const spec = R.parse(src);
  assert.equal(spec.kind, 'text');
  assert.deepEqual(spec.seg, [1, 2]);
  assert.deepEqual(spec.lines, ['txt', 'gls', 'ft']);
  assert.equal(spec.label, 'my label');
  assert.equal(spec.styles.length, 6);
  assert.deepEqual(spec.styles[0].targets, [{ line: 'txt', seg: 1, word: 2 }, { line: 'txt', seg: 2, word: 1, segEnd: 2, wordEnd: 3 }]);
  assert.deepEqual(spec.styles[2].targets[0], { line: 'morph', text: '-mo', all: false });
  assert.deepEqual(spec.styles[3].targets[0], { line: 'txt', text: 'a', all: true });
  assert.deepEqual(spec.styles[5].targets[0], { line: 'txt', seg: 1, word: 1, chars: [2, 3] });
  assert.equal(R.serialize(spec), src);
});

test('entry / sense / unknown keys / bad input', () => {
  assert.equal(R.parse('{{flex:entry 6A5F3A2E-1B1E-4C2A-9F10-0D2C1A7E0001}}').guid, '6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001');
  assert.equal(R.parse('{{flex:sense 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e00a1}}').kind, 'sense');
  const s = R.parse('{{flex:text ' + G + ' future=1 flag}}');
  assert.deepEqual(s.extra, { future: '1', flag: true });
  assert.equal(R.serialize(s), '{{flex:text ' + G + ' future=1 flag}}');
  assert.equal(R.parse('{{flex:text nope}}'), null);
  assert.equal(R.parse('{{flex:bogus ' + G + '}}'), null);
  assert.ok(R.isEmbedLine('  {{flex:entry ' + G + '}}  '));
  assert.ok(!R.isEmbedLine('x {{flex:entry ' + G + '}}'));
});

test('resolveStyles: words, ranges, lines, chars, text matches (grapheme aware)', () => {
  const spec = R.parse('{{flex:text ' + G + ' hl=1.2,2.1-2.3 b=gls:1.1 u=morph:"-mo" s=ft:1 i=1.1:2-3 color[red]=*"a"}}');
  const idx = R.resolveStyles(spec, text);
  const at = (n, line, w) => R.stylesFor(idx, n, line, w).map((s) => s.style + (s.chars ? ':' + s.chars.join('-') : ''));
  assert.deepEqual(at(1, 'txt', 2), ['hl', 'color:2-2', 'color:7-7']);   // ka-nuwa-mo: a at 2 and 7
  assert.deepEqual(at(2, 'txt', 1), ['hl', 'color:2-2', 'color:4-4']);   // Haŋa: a at 2 and 4
  assert.deepEqual(at(2, 'txt', 3), ['hl', 'color:2-2', 'color:7-7']);
  assert.deepEqual(at(1, 'gls', 1), ['b']);                                // targeted even though word 1 shows no gls line
  assert.deepEqual(at(1, 'morph', 2), ['u:10-12']);                       // "ka- nuwa -mo": -mo at graphemes 10..12
  assert.deepEqual(at(2, 'morph', 3), []);                                 // first match only (no *)
  assert.deepEqual(at(1, 'ft', 0), ['s']);
  assert.deepEqual(at(1, 'txt', 1), ['i:2-3', 'color:2-2']);
});

test('toggleStyle adds, removes, and swaps colours', () => {
  const spec = R.parse('{{flex:text ' + G + '}}');
  const t = { line: 'txt', seg: 1, word: 2 };
  assert.equal(R.toggleStyle(spec, t, 'hl', ''), true);
  assert.equal(R.serialize(spec), '{{flex:text ' + G + ' hl=1.2}}');
  assert.equal(R.toggleStyle(spec, t, 'hl', '#f00'), true);              // colour swap, not a second entry
  assert.equal(R.serialize(spec), '{{flex:text ' + G + ' hl[#f00]=1.2}}');
  assert.equal(R.toggleStyle(spec, t, 'hl', '#f00'), false);
  assert.equal(R.serialize(spec), '{{flex:text ' + G + '}}');
  R.toggleStyle(spec, { line: 'txt', seg: 1, word: 1, chars: [1, 2] }, 'b', '');
  R.toggleStyle(spec, { line: 'txt', seg: 2, word: 1, segEnd: 2, wordEnd: 2 }, 'u', '');
  assert.equal(R.serialize(spec), '{{flex:text ' + G + ' b=1.1:1-2 u=2.1-2.2}}');
  R.clearStyles(spec, null);
  assert.equal(spec.styles.length, 0);
});

test('findAll is grapheme and diacritic aware', () => {
  assert.deepEqual(R.findAll('ɲamú', 'u', true), [[4, 4]]);
  assert.deepEqual(R.findAll('éá', 'a', false), [[2, 2]]);       // combining marks stay with their base
  assert.deepEqual(R.findEmbeds('x {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} y').map((e) => e.spec.kind), ['entry']);
});
