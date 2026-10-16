const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./load.js');

const FS = load(['util', 'flexref', 'markdown', 'collection']);
const C = FS.collection;
const G = '9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001';

// The collection file format (Seth, 2026-10-16): groups are headings (` {collapsed}` when
// closed), an example's note is the `> ` lines after it, anything else is kept as it is.
const BODY = [
  '{{flex:text ' + G + ' seg=1}}',
  '',
  '## Shared subject',
  '',
  '{{flex:text ' + G + ' seg=2 hl=2.1}}',
  '> Both verbs take the same subject.',
  '>',
  '> Compare (3).',
  '',
  '## Switch reference {collapsed}',
  '',
  '{{flex:text ' + G + ' seg=4}}',
  '',
  'A stray line someone typed',
  '',
].join('\n');

test('parse reads groups, examples, notes and keeps other text', () => {
  const items = C.parse(BODY);
  assert.deepEqual(items.map((i) => i.t), ['ex', 'group', 'ex', 'group', 'ex', 'other']);
  assert.equal(items[1].label, 'Shared subject'); assert.equal(items[1].collapsed, false);
  assert.equal(items[3].label, 'Switch reference'); assert.equal(items[3].collapsed, true);
  assert.equal(items[2].note, 'Both verbs take the same subject.\n\nCompare (3).');
  assert.equal(items[0].note, '');
  assert.equal(items[2].spec.guid, G);
  assert.equal(items[5].src, 'A stray line someone typed');
});

test('serialize writes it back unchanged', () => {
  assert.equal(C.serialize(C.parse(BODY)), BODY);
});

test('notes and groups survive edits', () => {
  const items = C.parse(BODY);
  items[0].note = 'first\n';                         // a trailing newline while typing is not written
  items[3].collapsed = false;
  const out = C.serialize(items);
  assert.ok(out.startsWith('{{flex:text ' + G + ' seg=1}}\n> first\n\n## Shared subject'));
  assert.ok(out.includes('\n## Switch reference\n'));
  assert.deepEqual(C.parse(out).map((i) => i.t), ['ex', 'group', 'ex', 'group', 'ex', 'other']);
});

test('a > line with no example before it is kept as other text', () => {
  const items = C.parse('> loose quote\n\n{{flex:text ' + G + ' seg=1}}\n');
  assert.deepEqual(items.map((i) => i.t), ['other', 'ex']);
});
