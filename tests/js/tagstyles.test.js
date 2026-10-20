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
const SUBJ = { guid: 't1', name: 'Subject', abbr: 'S', group: 'Arguments', path: ['Syntax', 'Arguments'], fore: '', back: '#dbeafe' };
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

test('text styles round-trip through `tags=`: brackets, marker, tile, border, the words’ colour, the bar switch', () => {
  const rules = [{ tag: 'Subject', br: 'sq', hl: true }, { tag: 'Verb', box: true, bar: true, bs: 'dashed', bw: 3, bc: '#1d4ed8' }, { tag: 'Object', tile: true, c: '#b45309', b: true, bar: false, tc: '#fde68a' }, { tag: 'group:Discourse', br: 'an' }, { tag: 'filter:f1', hide: true }];
  const v = R.serializeTagRules(rules);
  // the border's line style / thickness and the tile's own colour (Seth, 2026-10-18) ride along
  assert.strictEqual(v, 'Subject:hl+brsq,Verb:box+bsdashed+bw3+bc#1d4ed8+bar,Object:c#b45309+b+tile+tc#fde68a+nobar,group%3ADiscourse:bran,filter%3Af1:off');
  assert.deepStrictEqual(plain(R.parseTagRules(v)), rules);
  assert.deepStrictEqual(plain(R.parseTagRules('Subject:brxx+purple+bswavy+bw9')), []);
  assert.deepStrictEqual(plain(R.parseTagRules('Verb:box+bc%23ff0000')), [{ tag: 'Verb', box: true, bc: '#ff0000' }]);   // a hand-encoded # is forgiven
  // a chart marker in a cell with no words: shown / hidden whatever the chart's own switch says (Seth, 2026-10-19)
  assert.strictEqual(R.serializeTagRules([{ tag: 'marker:New', empty: true }, { tag: 'marker:Given', empty: false, row: true }]), 'marker%3ANew:empty,marker%3AGiven:noempty+row');
  assert.deepStrictEqual(plain(R.parseTagRules('marker%3ANew:empty,marker%3AGiven:noempty+row')), [{ tag: 'marker:New', empty: true }, { tag: 'marker:Given', empty: false, row: true }]);          // unknown brackets / tokens / line styles / widths are dropped
  const VERB = { guid: 'v', name: 'Verb', abbr: 'V' };
  T.setList([VERB]);
  T.setConfig({ project: { Kalu: [{ tag: 'Verb', box: true, bs: 'dotted', bw: 4, tile: true, tc: '#abcdef' }] }, tab: {}, folder: {}, filters: [] });
  const res = T.resolve(VERB, null, { project: 'Kalu', tab: 'Notes', folder: '' });
  assert.ok(res.box && res.bs === 'dotted' && res.bw === 4 && res.tile && res.tc === '#abcdef', JSON.stringify(res));
  T.setConfig({ project: { Kalu: [{ tag: 'Verb', box: true, bs: 'wavy', bw: 9 }] }, tab: {}, folder: {}, filters: [] });
  const r2 = T.resolve(VERB, null, { project: 'Kalu', tab: 'Notes', folder: '' });
  assert.ok(r2.box && r2.bs === '' && r2.bw === 0);                                   // nonsense falls back to 2px solid
});

test('a rule styles the TEXT and the bar steps back unless asked for; a group rule covers its tags; visual filters sit between the tab and the project', () => {
  T.setList([SUBJ, TOPIC]);
  T.setConfig({ project: { Kalu: [{ tag: '*', bg: '#111111' }] }, tab: {}, folder: {},
    filters: [{ id: 'f1', name: 'Discourse', enabled: true, rules: [{ tag: 'group:Discourse', br: 'an', hl: true }] }, { id: 'f2', name: 'Syntax', enabled: false, rules: [{ tag: 'Subject', box: true }] }] });
  const ctx = { project: 'Kalu', tab: 'Notes', folder: '' };
  let r = T.resolve(TOPIC, null, ctx);
  assert.ok(r.br === 'an' && r.hl && !r.showBar && r.styleVia.kind === 'filter' && r.styleVia.label.includes('Discourse'));
  assert.ok(T.textStyled(r) && r.ink.startsWith('rgb('));
  r = T.resolve(SUBJ, null, ctx);                                   // f2 is off: the project's `*` decides, a bar
  assert.ok(!r.box && r.showBar && r.styleVia.kind === 'project' && r.bg === '#111111');
  // the tab turns f2 on for itself with a `filter:` rule; the bar can be asked for alongside the text style
  T.setConfig({ project: { Kalu: [{ tag: '*', bg: '#111111' }] }, tab: { Notes: [{ tag: 'filter:f2', hide: false }, { tag: 'Subject', bar: true }] }, folder: {},
    filters: [{ id: 'f2', name: 'Syntax', enabled: false, rules: [{ tag: 'Subject', box: true }] }] });
  r = T.resolve(SUBJ, null, ctx);
  assert.ok(r.showBar && r.bar === true && r.styleVia.kind === 'tab');      // the tab's own rule wins over the filter's…
  r = T.resolve(SUBJ, null, { project: 'Kalu', tab: 'Other', folder: '' });
  assert.ok(!r.box && r.showBar);                                           // …and elsewhere f2 stays off
  // an example can switch a filter off for itself
  T.setConfig({ project: {}, tab: {}, folder: {}, filters: [{ id: 'f1', name: 'Discourse', enabled: true, rules: [{ tag: 'group:Discourse', br: 'an' }] }] });
  assert.strictEqual(T.resolve(TOPIC, R.parse('{{flex:text ' + G + ' tags=filter%3Af1:off}}'), ctx).br, '');
  assert.strictEqual(T.resolve(TOPIC, null, ctx).br, 'an');
  // the scopes list names the filters that are on, between the tab and the project
  assert.deepStrictEqual(plain(T.scopesFor(ctx).map((s) => s.kind)), ['tab', 'filter', 'project']);
  // a NOTE's view settings sit above its folder and tab: this page turns the filter off for itself
  T.setConfig({ project: {}, tab: {}, folder: {}, note: { n1: [{ tag: 'filter:f1', hide: true }] }, filters: [{ id: 'f1', name: 'Discourse', enabled: true, rules: [{ tag: 'group:Discourse', br: 'an' }] }] });
  assert.strictEqual(T.resolve(TOPIC, null, Object.assign({ note: 'n1' }, ctx)).br, '');
  assert.strictEqual(T.resolve(TOPIC, null, Object.assign({ note: 'n2' }, ctx)).br, 'an');
  assert.deepStrictEqual(plain(T.scopesFor(Object.assign({ note: 'n2' }, ctx)).map((s) => s.kind)), ['note', 'tab', 'filter', 'project']);
  assert.ok(!T.filterOn({ id: 'f1', enabled: true }, [{ rules: [{ tag: 'filter:f1', hide: true }] }]));
});

test('a TEXT is a scope of its own: its examples wherever they appear, between the tab and the filters', () => {
  T.setList([SUBJ, TOPIC]);
  T.setConfig({ project: { Kalu: [{ tag: 'Subject', bg: '#111111' }] }, tab: {}, folder: {}, note: {}, text: { [G]: [{ tag: 'Subject', hide: true }] },
    filters: [{ id: 'f1', name: 'F', enabled: true, rules: [{ tag: 'Subject', hide: false, box: true }] }] });
  const ctx = { project: 'Kalu', tab: 'Notes', folder: '' };
  const spec = R.parse('{{flex:text ' + G + ' seg=1}}');                    // the example's source text comes from its spec
  let r = T.resolve(SUBJ, spec, ctx);
  assert.ok(r.hide && r.hideVia.kind === 'text' && r.box && r.styleVia.kind === 'filter');
  r = T.resolve(SUBJ, R.parse('{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0002 seg=1}}'), ctx);
  assert.ok(!r.hide && r.hideVia.kind === 'filter');
  T.noteTextTitle(G, 'The dog and the river');
  assert.deepStrictEqual(plain(T.scopesFor(Object.assign({ text: G }, ctx)).map((s) => s.kind)), ['tab', 'text', 'filter', 'project']);
  assert.strictEqual(T.scopesFor(Object.assign({ text: G }, ctx))[1].label, 'the text “The dog and the river”');
});

test('the tag list’s hierarchy: a group rule covers every tag under it, and tagTree keeps FLEx’s order', () => {
  // group:Syntax reaches Subject through its path (Syntax › Arguments); group:Arguments too; group:Discourse not
  assert.ok(T.matches({ tag: 'group:Syntax' }, SUBJ) && T.matches({ tag: 'group:arguments' }, SUBJ) && !T.matches({ tag: 'group:Discourse' }, SUBJ));
  assert.ok(T.matches({ tag: 'group:Discourse' }, TOPIC));
  const verb = { guid: 't3', name: 'Verb', abbr: 'V', group: 'Syntax', path: ['Syntax'] };
  const root = T.tagTree([SUBJ, { guid: 't2', name: 'Object', abbr: 'O', path: ['Syntax', 'Arguments'] }, verb, TOPIC]);
  const shape = (n) => n.entries.map((e) => (e.tag ? e.tag.name : [e.node.name, e.node.count, shape(e.node)]));
  assert.deepStrictEqual(plain(shape(root)), [['Syntax', 3, [['Arguments', 2, ['Subject', 'Object']], 'Verb']], ['Discourse', 1, ['Topic shift']]]);
});

test('chart markers: their own rule namespace, and a whole-row style (Seth, 2026-10-18)', () => {
  T.setConfig({ project: { '': [{ tag: 'marker:Topic', bg: '#fde68a', row: true }, { tag: 'marker:*', hide: true }, { tag: 'Topic', bg: '#ff0000' }] }, tab: {}, folder: {}, note: {}, text: {}, filters: [] });
  const marker = { guid: 'm1', name: 'Topic', abbr: 'Top', group: 'Discourse', path: ['Discourse'], marker: true };
  const res = T.resolve(marker, null, { project: '', tab: 'T', folder: '' });
  assert.strictEqual(res.bg, '#fde68a');
  assert.strictEqual(res.row, true);
  assert.strictEqual(res.hide, true);              // marker:* hides every marker; Topic's own rule gives the look
  // a text TAG called Topic is untouched by marker rules, and a marker by tag rules
  const tag = { guid: 't4', name: 'Topic', abbr: 'Top', group: 'Discourse', path: ['Discourse'] };
  const tres = T.resolve(tag, null, { project: '', tab: 'T', folder: '' });
  assert.strictEqual(tres.bg, '#ff0000');
  assert.strictEqual(tres.hide, false);
  assert.strictEqual(tres.row, false);
  // a group rule for markers; the marker's own rule wins over it
  T.setConfig({ project: { '': [{ tag: 'marker:group:Discourse', bg: '#caffbf' }] }, tab: {}, folder: {}, note: {}, text: {}, filters: [] });
  assert.strictEqual(T.resolve(marker, null, { project: '', tab: 'T', folder: '' }).bg, '#caffbf');
  assert.strictEqual(T.resolve(Object.assign({}, marker, { name: 'Focus' }), null, { project: '', tab: 'T', folder: '' }).bg, '#caffbf');
  // markersIn reads a chart's tag cells; `row` rides in tags=
  const chart = { rows: [{ cells: [{ kind: 'tag', tag: { guid: 'm1', name: 'Topic', abbr: 'Top' } }, { kind: 'words' }] }, { cells: [{ kind: 'tag', tag: { guid: 'm1', name: 'Topic', abbr: 'Top' } }] }] };
  const here = T.markersIn(chart);
  assert.strictEqual(here.length, 1);
  assert.strictEqual(here[0].count, 2);
  assert.strictEqual(here[0].tag.marker, true);
  const spec = R.parse('{{flex:chart ' + G + '}}');
  R.setTagRules(spec, [{ tag: 'marker:Topic', row: true, bg: '#fde68a' }]);
  assert.strictEqual(R.serialize(spec), '{{flex:chart ' + G + ' tags=marker%3ATopic:bg#fde68a+row}}');
  assert.deepStrictEqual(plain(R.tagRules(R.parse(R.serialize(spec)))), [{ tag: 'marker:Topic', bg: '#fde68a', row: true }]);
  assert.strictEqual(T.resolve(marker, spec, { project: '', tab: 'T', folder: '' }).row, true);
});

test('chart columns: the `column:` namespace, apart from tags and markers', () => {
  T.setConfig({ project: { '': [{ tag: 'column:Nucleus/Subject', bg: '#a0c4ff', br: 'sq' }, { tag: 'column:group:Nucleus', bg: '#caffbf' }, { tag: 'Subject', bg: '#ff0000' }] }, tab: {}, folder: {}, note: {}, text: {}, filters: [] });
  const subj = { guid: 'column:c3', name: 'Nucleus/Subject', abbr: 'S', group: 'Nucleus', path: ['Nucleus'], column: true };
  const verb = { guid: 'column:c4', name: 'Nucleus/Verb', abbr: 'V', group: 'Nucleus', path: ['Nucleus'], column: true };
  const ctx = { project: '', tab: 'T', folder: '' };
  assert.strictEqual(T.resolve(subj, null, ctx).bg, '#a0c4ff');
  assert.strictEqual(T.resolve(subj, null, ctx).br, 'sq');
  assert.strictEqual(T.resolve(verb, null, ctx).bg, '#caffbf');          // the group's rule
  assert.strictEqual(T.resolve({ guid: 't1', name: 'Subject', abbr: 'S' }, null, ctx).bg, '#ff0000');   // the tag is its own
  assert.notStrictEqual(T.resolve({ guid: 'm', name: 'Subject', marker: true }, null, ctx).bg, '#ff0000');
  T.noteColumn({ guid: 'c3', name: 'Subject', abbr: 'S', path: ['Nucleus'] });
  assert.strictEqual(T.columns().length, 1);
  assert.strictEqual(T.columns()[0].guid, 'column:c3');
});


test('merged cells are a filter target: any, by side, by owner column, by both (Seth, 2026-10-20)', () => {
  const ctx = { project: 'Kalu', tab: 'Notes', folder: '' };
  const verb = { n: 4, name: 'Verb', abbr: 'V', path: ['Nucleus'] }, subj = { n: 3, name: 'Subject', abbr: 'S', path: ['Nucleus'] };
  const vR = T.mergedItem(verb, 'right'), vL = T.mergedItem(verb, 'left'), sR = T.mergedItem(subj, 'right');
  assert.strictEqual(vR.name, 'merged:Nucleus/Verb:right');
  assert.strictEqual(vR.label, 'V merged right');
  const look = (item, tags) => T.resolve(item, R.parse('{{flex:chart ' + G + ' tags=' + tags + '}}'), ctx);
  // merged:* reaches every merged part; merged:right only those extended to the right
  assert.ok(look(vR, 'merged%3A*:box').box && look(vL, 'merged%3A*:box').box);
  assert.ok(look(vR, 'merged%3Aright:box').box && !look(vL, 'merged%3Aright:box').box);
  // by owner column: name, abbreviation or Group/Name; with a side, that side only
  assert.ok(look(vR, 'merged%3AVerb:tile').tile && look(vL, 'merged%3AV:tile').tile && look(vR, 'merged%3ANucleus%2FVerb:tile').tile);
  assert.ok(!look(sR, 'merged%3AVerb:tile').tile);
  assert.ok(look(vR, 'merged%3AVerb%3Aright:tile').tile && !look(vL, 'merged%3AVerb%3Aright:tile').tile);
  // the most specific rule wins: column+side over column over side over any
  const r = look(vR, 'merged%3A*:bg%23111111,merged%3Aright:bg%23222222,merged%3AVerb:bg%23333333,merged%3AVerb%3Aright:bg%23444444');
  assert.strictEqual(r.bg, '#444444');
  assert.strictEqual(look(vL, 'merged%3A*:bg%23111111,merged%3Aleft:bg%23222222').bg, '#222222');
  // a merged rule never touches a tag, a marker or a column; a plain `*` rule never touches a merged part
  assert.ok(!look(SUBJ, 'merged%3A*:box').box);
  assert.strictEqual(look(vR, '*:box').styleVia.kind, 'default');
  // the popover's own rows: generic structure items match their key exactly; a written key reads back
  assert.ok(T.structureItem('merged:*') && T.structureItem('merged:right').skind === 'merged');
  assert.strictEqual(T.mergedFromKey('merged:Nucleus/Verb:right').label, 'Verb merged right');
  assert.strictEqual(T.mergedFromKey('merged:right').label, 'Merged into the column to the right');
  // structureIn counts a chart's merged parts, any / by side / per owner column and side
  const obj = { rows: [{ cells: [{ kind: 'words', colN: 3, mergeAfter: true }, { kind: 'words', colN: 4 }] }, { cells: [{ kind: 'words', colN: 4, mergeBefore: true }] }], template: { columns: [subj, verb] } };
  const counts = Object.fromEntries(T.structureIn(obj).map((x) => [x.tag.guid, x.count]));
  assert.deepEqual(counts, { 'merged:*': 2, 'merged:right': 1, 'merged:left': 1, 'merged:Nucleus/Subject:right': 1, 'merged:Nucleus/Verb:left': 1 });
});
