// FLEx text markup tag styles (ui/js/tagstyles.js; Seth, 2026-10-17): the embed's `tags=` rules
// round-trip, and a tag's look is decided by the most specific scope — example over folder over
// tab over project — with on/off and the look settled separately.
const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./load.js');

const FS = load(['util', 'flexref', 'tagstyles']);
const R = FS.flexref, T = FS.tagstyles;
const plain = (x) => JSON.parse(JSON.stringify(x));   // vm objects have their own prototypes
const G = '9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001';
const SUBJ = { guid: 't1', name: 'Subject', abbr: 'S', group: 'Syntax', fore: '', back: '#dbeafe' };
const TOPIC = { guid: 't4', name: 'Topic shift', abbr: 'Top', group: 'Discourse', fore: '', back: '' };

test('an example’s own rules live in `tags=` and round-trip through the embed grammar', () => {
  const spec = R.parse('{{flex:text ' + G + ' seg=1-2}}');
  R.setTagRules(spec, [{ tag: 'Subject', hide: true }, { tag: 'Topic shift', bg: '#d1fae5', b: true, label: false }, { tag: '*', hide: false }]);
  const src = R.serialize(spec);
  assert.strictEqual(src, '{{flex:text ' + G + ' seg=1-2 tags=Subject:off,Topic_shift:bg#d1fae5+b+nolabel,*:on}}');
  assert.deepStrictEqual(plain(R.tagRules(R.parse(src))), [{ tag: 'Subject', hide: true }, { tag: 'Topic shift', bg: '#d1fae5', b: true, label: false }, { tag: '*', hide: false }]);
  R.setTagRules(spec, []);
  assert.strictEqual(R.serialize(spec), '{{flex:text ' + G + ' seg=1-2}}');
  // unknown tokens are dropped, a rule with nothing left goes; odd names are encoded
  assert.deepStrictEqual(plain(R.parseTagRules('Subject:purple,Object:u')), [{ tag: 'Object', u: true }]);
  assert.strictEqual(R.serializeTagRules([{ tag: 'a_b,c:d', i: true }]), 'a%5Fb%2Cc%3Ad:i');
  assert.deepStrictEqual(plain(R.parseTagRules('a%5Fb%2Cc%3Ad:i')), [{ tag: 'a_b,c:d', i: true }]);
  // the `tag` line is on by default and off when an explicit lines= leaves it out
  assert.ok(R.showsTags(R.parse('{{flex:text ' + G + '}}')));
  assert.ok(!R.showsTags(R.parse('{{flex:text ' + G + ' lines=txt,gls,ft}}')));
  assert.ok(R.showsTags(R.parse('{{flex:text ' + G + ' lines=txt,ft,tag}}')));
});

test('the most specific scope wins: example > folder (nearest first) > tab > project > FLEx > palette', () => {
  T.setList([SUBJ, TOPIC]);
  T.setConfig({
    project: { Kalu: [{ tag: 'Subject', bg: '#111111' }, { tag: '*', b: true }] },
    tab: { Notes: [{ tag: 'S', bg: '#222222' }] },                                   // by abbreviation
    folder: { 'Notes/Verbs': [{ tag: 'subject', bg: '#333333' }], 'Notes/Verbs/Past': [{ tag: 'Subject', bg: '#444444', enabled: false }] },
  });
  const ctx = { project: 'Kalu', tab: 'Notes', folder: 'Verbs/Past' };
  let r = T.resolve(SUBJ, null, ctx);
  assert.strictEqual(r.bg, '#333333');                         // the disabled rule in Past is skipped; Verbs decides
  assert.strictEqual(r.styleVia.kind, 'folder');
  assert.ok(r.styleVia.label.includes('Verbs'));
  r = T.resolve(SUBJ, null, { project: 'Kalu', tab: 'Notes', folder: '' });
  assert.strictEqual(r.bg, '#222222');
  r = T.resolve(SUBJ, null, { project: 'Kalu', tab: 'Other', folder: '' });
  assert.strictEqual(r.bg, '#111111');
  // no rule of its own: `*` in the project gives bold; the colour is FLEx's own (Subject has one)
  r = T.resolve(SUBJ, null, { project: 'Nope', tab: 'Other', folder: '' });
  assert.strictEqual(r.bg, '#dbeafe'); assert.strictEqual(r.styleVia.kind, 'flex');
  r = T.resolve(TOPIC, null, ctx);
  assert.ok(r.b && r.styleVia.kind === 'project' && T.PALETTE.includes(r.bg));   // `*` styles it; its colour from the palette
  r = T.resolve(TOPIC, null, { project: 'Nope', tab: 'x', folder: '' });
  assert.strictEqual(r.styleVia.kind, 'default');
  // the example itself beats everything
  const spec = R.parse('{{flex:text ' + G + ' tags=Subject:bg#abcdef+u}}');
  r = T.resolve(SUBJ, spec, ctx);
  assert.strictEqual(r.bg, '#abcdef'); assert.ok(r.u && r.styleVia.kind === 'example');
});

test('shown or hidden is settled apart from the look, so "off here" and "back on here" need no colours', () => {
  T.setList([SUBJ, TOPIC]);
  T.setConfig({ project: {}, tab: { Notes: [{ tag: '*', hide: true }, { tag: 'Subject', bg: '#222222' }] }, folder: {} });
  const ctx = { project: 'Kalu', tab: 'Notes', folder: '' };
  let r = T.resolve(TOPIC, null, ctx);
  assert.ok(r.hide && r.hideVia.kind === 'tab');
  r = T.resolve(SUBJ, null, ctx);
  assert.ok(r.hide && r.bg === '#222222');                      // hidden by `*`, styled by its own rule
  // the example turns it back on, keeping the tab's colour
  r = T.resolve(SUBJ, R.parse('{{flex:text ' + G + ' tags=Subject:on}}'), ctx);
  assert.ok(!r.hide && r.hideVia.kind === 'example' && r.bg === '#222222' && r.styleVia.kind === 'tab');
  // and a folder may hide what the tab shows
  T.setConfig({ project: {}, tab: { Notes: [{ tag: 'Subject', hide: false, bg: '#222222' }] }, folder: { 'Notes/Verbs': [{ tag: 'Subject', hide: true }] } });
  r = T.resolve(SUBJ, null, { project: 'Kalu', tab: 'Notes', folder: 'Verbs' });
  assert.ok(r.hide && r.hideVia.kind === 'folder' && r.styleVia.kind === 'tab');
  // patchRule: undefined deletes, an empty rule goes
  const rules = [{ tag: 'Subject', hide: true }];
  T.patchRule(rules, 'Subject', { hide: undefined });
  assert.deepStrictEqual(plain(rules), []);
  T.patchRule(rules, 'Topic shift', { bg: '#010101' });
  T.patchRule(rules, 'topic SHIFT', { b: true });
  assert.deepStrictEqual(plain(rules), [{ tag: 'Topic shift', bg: '#010101', b: true }]);
});

test('tagsIn: the distinct tags on the segments an example shows, blank lines left out', () => {
  FS.interlinear = { blankSeg: (s) => !(s.words || []).length };
  const obj = { segments: [{ n: 2, words: [{ txt: 'a' }] }, { n: 3, words: [] }],
    tags: [{ tag: SUBJ, from: { seg: 1, w: 0 }, to: { seg: 2, w: 0 } }, { tag: TOPIC, from: { seg: 3, w: 0 }, to: { seg: 3, w: 1 } }, { tag: SUBJ, from: { seg: 2, w: 1 }, to: { seg: 2, w: 1 } }, { tag: TOPIC, from: { seg: 9, w: 0 }, to: { seg: 9, w: 0 } }] };
  assert.deepStrictEqual(plain(T.tagsIn(obj).map((x) => [x.tag.name, x.count])), [['Subject', 2]]);
});
