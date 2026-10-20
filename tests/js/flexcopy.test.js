// The plain-text copies of FLEx objects in a note's file (ui/js/flexcopy.js; Seth, 2026-10-17:
// "a markdown file IS actually readable elsewhere"). The app never shows them: strip() takes them
// out on open, attach() writes them back on save, in the form the object's place calls for.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { load } = require('./load.js');

const FS = load(['util', 'flexref', 'flexcopy']);
const C = FS.flexcopy;
const G = '9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001';
const E = '6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001';
const URL_T = 'silfw://localhost/link?app=flex&server=&database=Kalu%20Demo&tool=interlinearEdit&guid=' + G;
const URL_E = 'silfw://localhost/link?app=flex&server=&database=Kalu Demo (old)&tool=lexiconEdit&guid=' + E;
const W = (txt, gls, pos, morphs) => ({ txt, gls, pos, punct: false, morphs: morphs.map(([form, g]) => ({ form, gls: g })) });
const TEXT = {
  kind: 'text', guid: G, title: 'The dog and the river', url: URL_T,
  segments: [
    { n: 1, label: '1.1', baseline: 'Kabir ka-nuwa-mo lo.', free: 'The dog slept.', words: [W('Kabir', 'dog', 'n', [['kabir', 'dog']]), W('ka-nuwa-mo', 'slept', 'v', [['ka-', '3SG-'], ['nuwa', 'sleep'], ['-mo', '-PST']]), W('lo', 'DECL', 'part', [['lo', 'DECL']]), { txt: '.', punct: true }] },
    { n: 2, label: '1.2', baseline: ' ', free: '', words: [] },                       // a blank FLEx line: left out
    { n: 3, label: '1.3', baseline: 'Haŋa pemu.', free: 'Yesterday | the river.', words: [W('Haŋa', 'yesterday', 'adv', [['haŋa', 'yesterday']]), W('pemu', 'river', 'n', [['pemu', 'river']]), { txt: '.', punct: true }] },
  ],
};
const ENTRY = { kind: 'entry', guid: E, headword: 'kabir', pos: 'n', url: URL_E, senses: [
  { guid: 's1', number: '1', gloss: 'dog', definition: 'a domestic dog', pos: 'n', level: 0, examples: [] },
  { guid: 's2', number: '2', gloss: 'wild dog [dingo]', definition: '', pos: 'n', level: 0, examples: [] },
] };
const OBJ = { [G]: TEXT, [E]: ENTRY };
let live = true;                                     // false: nothing has been fetched this session
FS.interlinear = { blankSeg: (s) => !(s.words || []).length && !String(s.baseline || '').trim() && !s.free, peek: (spec) => (live ? OBJ[spec.guid] || null : null) };

const BLOCK = '{{flex:text ' + G + ' seg=1-3 lines=txt,mgls,ft}}';
const CELL = '{{flex:entry ' + E + '}}';
const NOTE = ['# Verbs', '', 'The past suffix:', '', BLOCK, '', '| form | example |', '|---|---|', '| -mo | ' + CELL + ' |', '',
  'Inline: ' + CELL + ' and done.', '', '```', BLOCK, '```', ''].join('\n');

test('attach writes a block copy after an object on its own line, a one-line copy in a cell or a sentence', () => {
  const md = C.attach(NOTE, 'n1');
  fs.writeFileSync(path.join(__dirname, '..', 'fixtures', 'flexcopy-note.md'), md);   // tests/test_flexcopy.py strips this same file
  fs.writeFileSync(path.join(__dirname, '..', 'fixtures', 'flexcopy-note.stripped.md'), NOTE);
  const block = md.split(BLOCK + '\n')[1].split('\n```\n')[0].concat('\n```').split('\n');
  assert.deepStrictEqual(block, [
    '[The dog and the river 1.1–1.3](' + URL_T + ' "flex-copy")',
    '```flex-copy',
    '1.1  Kabir  ka-nuwa-mo       lo.',
    '     dog    3SG- sleep -PST  DECL',
    '     ‘The dog slept.’',
    '',
    '1.3  Haŋa       pemu.',
    '     yesterday  river',
    '     ‘Yesterday | the river.’',
    '```',
  ]);
  // in a table cell: one link, its pipes escaped, brackets in the text escaped, the URL's space encoded
  const row = md.split('\n').find((l) => l.startsWith('| -mo |'));
  assert.strictEqual(row, '| -mo | ' + CELL + '[kabir (n) ‘dog; wild dog \\[dingo\\]’](silfw://localhost/link?app=flex&server=&database=Kalu%20Demo%20%28old%29&tool=lexiconEdit&guid=' + E + ' "flex-copy") |');
  assert.ok(md.includes('Inline: ' + CELL + '[kabir (n) ‘dog; wild dog \\[dingo\\]’]('));
  // an object a user typed inside a code block is text, and gets nothing
  assert.ok(md.includes('```\n' + BLOCK + '\n```'));
  // and strip gives back exactly what the editor had
  assert.strictEqual(C.strip(md, 'n1'), NOTE);
});

test('the form follows the object: out of a cell it gets the block, into a cell the one line', () => {
  const md = C.attach(NOTE, 'n2');
  const moved = C.strip(md, 'n2').replace('| -mo | ' + CELL + ' |', '| -mo | |').replace('The past suffix:', 'The past suffix:\n\n' + CELL).replace(BLOCK, '| x | ' + BLOCK + ' |');
  const out = C.attach(moved, 'n2');
  assert.ok(out.includes(CELL + '\n[kabir (n)](' + 'silfw://localhost/link?app=flex&server=&database=Kalu%20Demo%20%28old%29&tool=lexiconEdit&guid=' + E + ' "flex-copy")\n```flex-copy\n1. n ‘dog’ — a domestic dog\n2. n ‘wild dog [dingo]’\n```'));
  assert.ok(out.includes('| x | ' + BLOCK + '[The dog and the river 1.1–1.3: ‘The dog slept. Yesterday \\| the river.’](' + URL_T + ' "flex-copy") |'));
  assert.strictEqual(C.strip(out, 'n2'), moved);
});

test('an object not fetched this session keeps the copy its file had, switching form when it moved', () => {
  const md = C.attach(NOTE, 'n3');
  live = false;
  try {
    const st = C.strip(md, 'n3');
    assert.strictEqual(C.attach(st, 'n3'), md);                                       // nothing fetched: the file is unchanged
    const moved = st.replace('| -mo | ' + CELL + ' |', '| -mo | |').replace('The past suffix:', 'The past suffix:\n\n' + CELL);
    const out = C.attach(moved, 'n3');
    assert.ok(/\n\{\{flex:entry [^}]+\}\}\n\[kabir \(n\) ‘dog; wild dog \\\[dingo\\\]’\]\(silfw:[^ ]+ "flex-copy"\)\n/.test(out), out);
    assert.strictEqual(C.strip(out, 'n3'), moved);
  } finally { live = true; }
});

test('stale: only when FLEx now says something else than a copy the file holds (opening never rewrites)', () => {
  const md = C.attach(NOTE, 'n4');
  const st = C.strip(md, 'n4');
  assert.strictEqual(C.stale(st, 'n4'), false);
  TEXT.segments[0].free = 'The dog fell asleep.';
  try { assert.strictEqual(C.stale(st, 'n4'), true); } finally { TEXT.segments[0].free = 'The dog slept.'; }
  // a note whose file has no copies yet is not rewritten just because it was opened…
  assert.strictEqual(C.stale(C.strip(NOTE, 'n5'), 'n5'), false);
  // …but once it has been saved this session, an object without a copy gets one
  C.attach(NOTE.replace('\n' + BLOCK + '\n\n|', '\n|'), 'n5');
  assert.strictEqual(C.stale(NOTE, 'n5'), true);
});

test('a fence inside FLEx data never closes the copy, and other code blocks are not copies', () => {
  const t = JSON.parse(JSON.stringify(TEXT));
  t.segments[0].free = 'odd ``` text';
  const c = C.build(FS.flexref.parse(BLOCK), t);
  assert.ok(!/```/.test(c.body));
  const other = '{{flex:text ' + G + ' seg=1}}\n```python\nprint(1)\n```';
  assert.strictEqual(C.strip(other, 'n6'), other);
});
