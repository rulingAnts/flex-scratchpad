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

test('ws= pins a writing system per line and round-trips', () => {
  const src = '{{flex:text ' + G + ' seg=2 lines=txt,gls,ft ws=txt:fau-fonipa,gls:id,ft:id hl=2.1}}';
  const spec = R.parse(src);
  assert.deepEqual(spec.ws, { txt: 'fau-fonipa', gls: 'id', ft: 'id' });
  assert.equal(R.serialize(spec), src);
  assert.equal(R.parse('{{flex:text ' + G + ' ws=bogus:x}}').ws, null);
});

test('ws=title picks the title writing system; label survives', () => {
  const spec = R.parse('{{flex:text ' + G + ' ws=title:kal "causative ex. 3"}}');
  assert.deepEqual(spec.ws, { title: 'kal' });
  assert.equal(spec.label, 'causative ex. 3');
  assert.equal(R.serialize(spec), '{{flex:text ' + G + ' ws=title:kal "causative ex. 3"}}');
});

test('at= anchors round-trip and sit next to seg=', () => {
  const spec = FS.flexref.parse('{{flex:text ' + G + ' seg=6-11 at=4ad2c1f0-9f0c33ab lines=txt,ft}}');
  assert.deepEqual(spec.seg, [6, 11]);
  assert.deepEqual(spec.at, ['4ad2c1f0', '9f0c33ab']);
  assert.equal(FS.flexref.serialize(spec), '{{flex:text ' + G + ' seg=6-11 at=4ad2c1f0-9f0c33ab lines=txt,ft}}');
  const one = FS.flexref.parse('{{flex:text ' + G + ' seg=3 at=4ad2c1f0}}');
  assert.deepEqual(one.at, ['4ad2c1f0', '4ad2c1f0']);
  assert.equal(FS.flexref.serialize(one), '{{flex:text ' + G + ' seg=3 at=4ad2c1f0}}');
});

test('entry embeds: fields= and senses= round-trip and select', () => {
  const spec = R.parse('{{flex:entry ' + G + ' fields=cf,gl,def,sub senses=1,2 "lex"}}');
  assert.deepEqual(spec.fields, ['cf', 'gl', 'def', 'sub']);
  assert.deepEqual(spec.senses, ['1', '2']);
  assert.equal(R.serialize(spec), '{{flex:entry ' + G + ' fields=cf,gl,def,sub senses=1,2 "lex"}}');
  assert.deepEqual(R.entryFields(R.parse('{{flex:entry ' + G + '}}')), R.DEFAULT_FIELDS);
  assert.deepEqual(R.parse('{{flex:entry ' + G + ' fields=none}}').fields, []);
  assert.equal(R.serialize(R.parse('{{flex:entry ' + G + ' fields=none}}')), '{{flex:entry ' + G + ' fields=none}}');
  const senses = [{ number: '1', level: 0 }, { number: '2', level: 0 }, { number: '2.1', level: 1 }, { number: '3', level: 0 }];
  assert.deepEqual(R.visibleSenses(spec, senses).map((s) => s.number), ['1', '2', '2.1']);
  assert.deepEqual(R.visibleSenses(R.parse('{{flex:entry ' + G + ' fields=gl senses=2}}'), senses).map((s) => s.number), ['2']);
  assert.deepEqual(R.visibleSenses(R.parse('{{flex:entry ' + G + ' senses=2.1}}'), senses).map((s) => s.number), ['2.1']);
  assert.deepEqual(R.visibleSenses(R.parse('{{flex:entry ' + G + ' fields=gl,def}}'), senses).map((s) => s.number), ['1', '2', '3']);
});

test('example layout flags ride in extra and round-trip: ex, indent=N', () => {
  const src = '{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1-2 ex indent=2}}';
  const spec = R.parse(src);
  assert.equal(spec.extra.ex, true);
  assert.equal(spec.extra.indent, '2');
  assert.equal(R.serialize(spec), src);
  delete spec.extra.ex; spec.extra.indent = '1';
  assert.equal(R.serialize(spec), '{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1-2 indent=1}}');
});

test('an attached file is an embed: {{file <ref> …}} round-trips, Unicode readable, spaces encoded', () => {
  const src = '{{file attachments/Survey%20notes%20ŋa.pdf preview h=480 indent=1 "Survey"}}';
  const spec = R.parse(src);
  assert.equal(spec.kind, 'file');
  assert.equal(spec.ref, 'attachments/Survey notes ŋa.pdf');
  assert.equal(spec.label, 'Survey');
  assert.equal(spec.extra.preview, true);
  assert.equal(spec.extra.h, '480');
  assert.equal(spec.extra.indent, '1');
  assert.equal(R.serialize(spec), src);
  // a linked file: an absolute Windows path; % " { } | are encoded so the embed stays one token
  const link = R.serialize({ kind: 'file', ref: 'C:\\Recordings\\100% "best" {x}|y.wav', label: '', extra: {} });
  assert.equal(link, '{{file C:\\Recordings\\100%25%20%22best%22%20%7Bx%7D%7Cy.wav}}');
  assert.equal(R.parse(link).ref, 'C:\\Recordings\\100% "best" {x}|y.wav');
  assert.ok(R.isEmbedLine('  ' + src + ' '));
  assert.ok(R.isEmbedLine('{{file a.txt}}'));
  assert.ok(!R.isEmbedLine('{{filex a.txt}}'));
  assert.equal(R.parse('{{file "label only"}}'), null);
  const found = R.findEmbeds('See ' + src + ' and {{flex:text ' + G + ' seg=1}}.');
  assert.deepEqual(found.map((e) => e.spec.kind), ['file', 'text']);
  // a FLEx embed is untouched by the new kind
  assert.equal(R.parse('{{flex:entry ' + G + '}}').kind, 'entry');
});
