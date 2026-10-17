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

test('groups have levels: a group holds sub-groups up to the next group of its level or higher', () => {
  // Seth, 2026-10-16: "I'd like collapsible headings to be allowed in the collection type,
  // though the headings won't export in the flextext"
  const body = ['# Clause chaining', '', '## Same subject {collapsed}', '', '{{flex:text ' + G + ' seg=1}}', '', '### Sequence', '', '{{flex:text ' + G + ' seg=2}}', '',
    '## Different subject', '', '{{flex:text ' + G + ' seg=3}}', '', '# Questions', '', '{{flex:text ' + G + ' seg=4}}', ''].join('\n');
  const items = C.parse(body);
  assert.deepEqual(items.map((i) => i.t === 'group' ? i.level : 'ex'), [1, 2, 'ex', 3, 'ex', 2, 'ex', 1, 'ex']);
  assert.equal(C.serialize(items), body);                                 // levels round-trip
  // the closed "## Same subject" hides its example AND its sub-group, not "## Different subject"
  assert.deepEqual(C.hiddenItems(items), [false, false, true, true, true, false, false, false, false]);
  items[0].collapsed = true;                                              // the chapter: all up to "# Questions"
  assert.deepEqual(C.hiddenItems(items), [false, true, true, true, true, true, true, false, false]);
  // an old file's "## Group" is level 2
  assert.equal(C.parse('## Old\n')[0].level, 2);
});

test('the view: a group block includes its sub-groups; moving and levels', () => {
  const body = ['## A', '', '{{flex:text ' + G + ' seg=1}}', '', '### A1', '', '{{flex:text ' + G + ' seg=2}}', '', '## B', '', '{{flex:text ' + G + ' seg=3}}', ''].join('\n');
  const c = new FS.Collection({ innerHTML: '', appendChild() {}, querySelector() { return null; }, scrollTop: 0 }, {});
  c.render = () => {};
  c.items = C.parse(body);
  assert.deepEqual(c.blockOf(0), [0, 4]);                                 // ## A … through ### A1's example
  assert.deepEqual(c.blockOf(2), [2, 4]);
  assert.deepEqual(c.groupsAround(3), [2, 0]);                            // A1's example sits in A1 inside A
  c.step(4, -1);                                                          // ## B moves up past ## A, sub-group and all
  assert.deepEqual(c.items.map((i) => i.t === 'group' ? i.label : i.spec.seg), ['B', [3, 3], 'A', [1, 1], 'A1', [2, 2]].map((x) => typeof x === 'string' ? x : x));
  c.setLevel(4, -1);                                                      // A1 becomes a level-2 group of its own
  assert.equal(c.items[4].level, 2);
  assert.deepEqual(c.blockOf(2), [2, 4]);
});
