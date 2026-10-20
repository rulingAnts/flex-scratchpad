const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./load.js');

// the chart note's body (two Markdown tables after the view embed) and its rule language
const FS = load(['util', 'flexref', 'interlinear', 'chart', 'chartnote', 'demo-data']);
const N = FS.chartnote;
const chart = () => Object.values(FS.demoData().charts)[0];
const G = chart().guid;

const BODY = [
  '{{flex:chart ' + G + ' lines=txt,gls hl=r2 free=row}}',
  '',
  'A line of my own, kept.',
  '',
  '## Custom columns',
  '',
  '| Column | Kind | Settings |',
  '|---|---|---|',
  '| Status | list | Information status |',
  '| Comment | notes | |',
  '| Role | rule | marker:new → N [row hl#fde68a]; col:Subject and not marker:* → S |',
  '',
  '## Values',
  '',
  '| Row | Status | Comment |',
  '|---|---|---|',
  '| 1a #000000000010 | new | Subject fronted \\| twice |',
  '| 2c #000000000050 | | Line one<br>line two |',
  '',
].join('\n');

test('the body parses and serialises back the same', () => {
  const st = N.parse(BODY);
  assert.equal(st.view, '{{flex:chart ' + G + ' lines=txt,gls hl=r2 free=row}}');
  assert.equal(st.spec.kind, 'chart');
  assert.equal(st.other, 'A line of my own, kept.');
  assert.deepEqual(st.columns.map((c) => [c.name, c.kind, c.settings]), [['Status', 'list', 'Information status'], ['Comment', 'notes', ''], ['Role', 'rule', 'marker:new → N [row hl#fde68a]; col:Subject and not marker:* → S']]);
  assert.deepEqual(st.values.get('000000000010'), { Status: 'new', Comment: 'Subject fronted | twice' });
  assert.deepEqual(st.values.get('000000000050'), { Comment: 'Line one\nline two' });
  assert.equal(st.labels.get('000000000050'), '2c');
  assert.equal(N.serialize(st), BODY);
  // a note with no columns is just its view
  assert.equal(N.serialize(N.parse('{{flex:chart ' + G + '}}\n')), '{{flex:chart ' + G + '}}\n');
  // rule columns are never stored in the values table
  const st2 = N.parse('{{flex:chart ' + G + '}}\n\n## Custom columns\n\n| Column | Kind | Settings |\n|---|---|---|\n| Role | rule | any → x |\n');
  st2.values.set('000000000010', { Role: 'x' });
  assert.ok(!N.serialize(st2).includes('## Values'));
});

test('rules: terms, operators, outputs and styles', () => {
  const c = chart();
  const ctxOf = (label, values, columns) => N.rowCtx(c.rows.find((r) => r.label === label), c, values || new Map(), columns || []);
  const run = (rule, label) => { const a = N.applyRule(N.parseRule(rule), ctxOf(label)); return a ? a.text : null; };
  assert.equal(run('marker:new → N', '1a'), 'N');
  assert.equal(run('marker:New → N', '1b'), null);
  assert.equal(run('marker:* → M', '2c'), 'M');                       // "Given" is in Reference
  assert.equal(run('marker:Reference → group', '2c'), 'group');       // a marker's group counts
  assert.equal(run('col:Subject and not marker:* → S; col:Subject → S+', '1a'), 'S+');
  assert.equal(run('col:Subject and not marker:* → S; col:Subject → S+', '1b'), 'S');
  assert.equal(run('col:Prenuclear/Outer → pre', '1b'), 'pre');
  assert.equal(run('col:c1 → pre', '1b'), 'pre');
  assert.equal(run('clause:speech → “ ”', '2a'), '“ ”');
  assert.equal(run('moved → mv', '1b'), 'mv');
  assert.equal(run('moved:postposed → mv', '1b'), null);
  assert.equal(run('clauseref → ref', '2b'), 'ref');
  assert.equal(run('endpara and endsent → ¶', '2c'), '¶');
  assert.equal(run('endpara → ¶', '1a'), null);
  assert.equal(run('words:"ka-" → has', '1a'), 'has');
  assert.equal(run('gloss:"river" → r', '2c'), 'r');
  assert.equal(run('label:"3b"', '3b'), '✓');                           // no → : a tick
  assert.equal(run('(marker:new or marker:giv) and not clause:speech → x', '2c'), 'x');
  // REGEX, WORD FIELDS PER WRITING SYSTEM AND COLUMN SCOPES (Seth, 2026-10-19: "regex for text in a column
  // on any interlinear word field/writing system (or any combination to query)")
  assert.equal(run('txt:/^ka-/ → pre', '1a'), 'pre');                               // the word (and its morpheme forms)
  assert.equal(run('txt:/^KA-/i → pre', '1a'), 'pre');                              // flags
  assert.equal(run('txt:/^uwa/ → x', '1a'), null);                                  // anchored: neither the word nor a morpheme starts with uwa
  assert.equal(run('gls:/sleep/ and pos:v → v', '1a'), 'v');                       // pos: the word category, exactly
  assert.equal(run('form:/^-mo$/ → suffix', '1a'), 'suffix');                       // a morpheme form on its own
  assert.equal(run('mgls:/pst/i → past', '1a'), 'past');                            // a morpheme gloss
  assert.equal(run('col:Subject[txt:/^kabir$/i] → K', '1a'), 'K');                  // the words of ONE column
  assert.equal(run('col:Subject[txt:/^kabir$/i] → K', '1b'), null);                 // (Haŋa is the subject of 1b)
  assert.equal(run('col:Verb[gls:/sleep/] and not col:Subject[txt:/kabir/i] → other', '3a'), 'other');
  assert.equal(run('col:/^Post/[marker:*]', '2c'), '✓');                            // a column by pattern: the Given marker sits in Postnuclear › Outer
  assert.equal(run('col:Subject[marker:*]', '2c'), null);                            // no marker in the Subject column
  assert.equal(run('free:/river/i → r', '2c'), 'r');                                // the free translation of the line
  assert.equal(run('label:/^2/ → two', '2b'), 'two');
  assert.throws(() => N.parseRule('txt:/(/ → x'), /Bad pattern/);
  assert.throws(() => N.parseRule('col:Subject[txt:/a/ → x'), /“]” is missing/);
  // a MERGED cell matches either column in a rule (3b: Subject merged into Verb) unless the chart says owner only
  assert.equal(run('col:Verb[txt:/kabir/i] → v', '3b'), 'v');
  assert.equal(run('col:Verb → v', '3b'), 'v');
  assert.equal(N.applyRule(N.parseRule('col:Verb → v'), N.rowCtx(c.rows.find((r) => r.label === '3b'), c, new Map(), [], { mergeOwner: true })), null);
  // a list column's value is a term too
  const vals = new Map([[N.anchorOf(c.rows[0].guid), { Status: 'new' }]]);
  const cols = [{ name: 'Status', kind: 'list', settings: 'Information status' }];
  const a = N.applyRule(N.parseRule('Status:new → fresh [row hl#fde68a b]'), N.rowCtx(c.rows[0], c, vals, cols));
  assert.deepEqual(a, { text: 'fresh', style: { scope: 'row', hl: '#fde68a', b: true }, chips: [] });
  // MARKER CHIPS AND JOINED ROWS (Seth, 2026-10-19: "show chips … for specific markers"; a ^ShdArg row
  // continues the row above — "remove the border between them and custom style a range on those rows")
  const chipsOf = (rule, label) => (N.applyRule(N.parseRule(rule), ctxOf(label)) || { chips: [] }).chips.map((m) => m.name);
  assert.deepEqual(chipsOf('marker:* → @markers', '1a'), ['New']);                       // every marker of the row
  assert.deepEqual(chipsOf('any → @markers:/^giv/i', '2c'), ['Given']);                   // by pattern
  assert.deepEqual(chipsOf('any → @markers:Reference', '2c'), ['Given']);                 // by group
  assert.deepEqual(chipsOf('any → @markers:new', '2c'), []);
  const jr = N.applyRule(N.parseRule('marker:/^(New|Given)$/ → @markers [join hl#fde68a row]'), ctxOf('2c'));
  assert.deepEqual(jr.style, { scope: 'row', join: true, hl: '#fde68a' });
  assert.equal(jr.text, '');                                                              // chips alone: no ✓
  assert.equal(N.applyRule(N.parseRule('marker:new → S [chip]'), ctxOf('1a')).style.chip, true);
  // the builder writes and reads them back
  const built = N.casesText([{ conds: [{ what: 'marker', how: 'regex', val: '^ShdArg', ci: false }], join: 'and', out: '', style: { scope: 'row', join: true, hl: '#fde68a' }, chips: 'some', chipsHow: 'regex', chipsVal: '^ShdArg' }]);
  assert.equal(built, 'marker:/^ShdArg/ → @markers:/^ShdArg/ [row join hl#fde68a]');
  assert.deepEqual(N.casesFrom(built, [])[0].chips, 'some');
  assert.equal(N.casesFrom(built, [])[0].chipsVal, '^ShdArg');
  assert.equal(N.applyRule(N.parseRule('Status:* → any'), N.rowCtx(c.rows[1], c, vals, cols)), null);
  // styles and outputs
  const cs = N.parseRule('marker:new → "two words" [cell hl u c#c0392b]; any → ·');
  assert.deepEqual(cs[0].style, { scope: 'cell', hl: '#fff2a8', u: true, c: '#c0392b' });
  assert.equal(cs[0].out, 'two words');
  assert.equal(cs[1].out, '·');
  // errors are named
  assert.throws(() => N.parseRule('marker:new and → x'), /term is missing/);
  assert.throws(() => N.parseRule('(marker:new → x'), /“\)” is missing/);
  assert.throws(() => N.parseRule('marker:new → x [blink]'), /Unknown style/);
});

test('a custom column keeps its place (left / frozen) in a 4th table column, written only when used', () => {
  const G = Object.values(FS.demoData().charts)[0].guid;
  const old = '{{flex:chart ' + G + '}}\n\n## Custom columns\n\n| Column | Kind | Settings |\n|---|---|---|\n| Comment | notes | |\n';
  const st = N.parse(old);
  assert.equal(st.columns[0].side, 'right'); assert.equal(st.columns[0].frozen, false);
  assert.equal(N.serialize(st), old);                       // an old file comes back as it was
  st.columns[0].side = 'left'; st.columns[0].frozen = true;
  st.columns.push({ name: 'Status', kind: 'notes', settings: '', side: 'right', frozen: true });
  const out = N.serialize(st);
  assert.ok(out.includes('| Column | Kind | Settings | Place |'), out);
  assert.ok(out.includes('| Comment | notes | | left frozen |') && out.includes('| Status | notes | | frozen |'), out);
  const back = N.parse(out);
  assert.deepEqual(back.columns.map((c) => [c.side, c.frozen]), [['left', true], ['right', true]]);
  assert.equal(N.serialize(back), out);
  // unfrozen on the right again: the Place column goes
  back.columns[0].side = 'right'; back.columns[0].frozen = false; back.columns[1].frozen = false;
  assert.ok(!N.serialize(back).includes('Place'));
});

test('a checkbox column: stored as x when ticked, ✓ in exports, and a rule can test it', () => {
  const body = [
    '{{flex:chart ' + G + '}}',
    '',
    '## Custom columns',
    '',
    '| Column | Kind | Settings |',
    '|---|---|---|',
    '| Checked | check | |',
    '| Flag | rule | Checked:* → done |',
    '',
    '## Values',
    '',
    '| Row | Checked |',
    '|---|---|',
    '| 1a #000000000010 | x |',
    '',
  ].join('\n');
  const st = N.parse(body);
  assert.deepEqual(st.columns.map((c) => [c.name, c.kind]), [['Checked', 'check'], ['Flag', 'rule']]);
  assert.equal(N.KINDS.check, 'Checkbox');
  assert.equal(N.serialize(st), body);
  const c = chart();
  const rule = N.parseRule('Checked:* → done; not Checked:* → todo');
  const row = (label) => c.rows.find((r) => r.label === label);
  const ticked = new Map([[N.anchorOf(row('1a').guid), { Checked: 'x' }]]);
  assert.equal(N.applyRule(rule, N.rowCtx(row('1a'), c, ticked, st.columns)).text, 'done');
  assert.equal(N.applyRule(rule, N.rowCtx(row('1b'), c, ticked, st.columns)).text, 'todo');
  // a value typed by hand (anything but blank) counts as ticked
  const typed = new Map([[N.anchorOf(row('1b').guid), { Checked: 'yes' }]]);
  assert.equal(N.applyRule(rule, N.rowCtx(row('1b'), c, typed, st.columns)).text, 'done');
});
