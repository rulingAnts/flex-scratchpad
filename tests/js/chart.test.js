const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./load.js');

// chart.js's pure helpers and the chart grammar in flexref, on the demo chart (demo-data.js is
// generated from flex/demo.py, so this is the same fixture tests/test_charts.py reads)
const FS = load(['util', 'flexref', 'interlinear', 'chart', 'flexcopy', 'demo-data']);
const R = FS.flexref;
const C = FS.chart;
const chart = () => Object.values(FS.demoData().charts)[0];
const G = chart().guid;

test('the chart grammar: rows, anchors, columns, lines, free, styles with chart targets', () => {
  const src = '{{flex:chart ' + G + ' rows=2-5 at=0000000020-0000000050 lines=txt,gls hl=r2,r3c4-c5 b=r2c3.1-2 u=gls:r4c4.1 color[red]=c4-c6 cols=Nucleus,Postnuclear/Inner free=col notes=off "lab"}}';
  const s = R.parse(src);
  assert.equal(s.kind, 'chart');
  assert.deepEqual(s.seg, [2, 5]);
  assert.deepEqual(s.at, ['0000000020', '0000000050']);
  assert.deepEqual(s.styles[0].targets, [{ line: '', row: 2 }, { line: '', row: 3, col: 4, colEnd: 5 }]);
  assert.deepEqual(s.styles[1].targets, [{ line: 'txt', row: 2, col: 3, word: 1, wordEnd: 2 }]);
  assert.deepEqual(s.styles[2].targets, [{ line: 'gls', row: 4, col: 4, word: 1 }]);
  assert.deepEqual(s.styles[3].targets, [{ line: '', col: 4, colEnd: 6 }]);
  assert.equal(s.extra.cols, 'Nucleus,Postnuclear/Inner');
  assert.equal(R.freeMode(s), 'col');
  assert.deepEqual(R.chartLines(s), ['txt', 'gls']);
  assert.equal(R.serialize(s), src);
  // a text embed never takes chart targets, a chart embed never seg=
  assert.equal(R.parse('{{flex:text ' + G + ' hl=r2}}').styles.length, 0);
  assert.equal(R.serialize(R.parse('{{flex:chart ' + G + ' seg=1-2}}')), '{{flex:chart ' + G + ' rows=1-2}}');
  // toggling a style on a chart target writes it back
  const t = R.parse('{{flex:chart ' + G + '}}');
  R.toggleStyle(t, { row: 1, col: 3, line: '' }, 'hl', '#ffd6a5');
  R.toggleStyle(t, { col: 4, line: '' }, 'b', '');
  assert.equal(R.serialize(t), '{{flex:chart ' + G + ' hl[#ffd6a5]=r1c3 b=c4}}');
  assert.ok(R.hasStyle(t, { row: 1, col: 3, line: '' }, 'hl', '#ffd6a5'));
  R.toggleStyle(t, { row: 1, col: 3, line: '' }, 'hl', '#ffd6a5');
  assert.equal(R.serialize(t), '{{flex:chart ' + G + ' b=c4}}');
});

test('chart styles resolve by row, column, cell and word', () => {
  const s = R.parse('{{flex:chart ' + G + ' hl=r2 b=r3c4-c5 u=r2c3.1 color[red]=c4 i=gls:r1c3.1}}');
  const idx = R.resolveChartStyles(s, chart());
  const names = (r, c, w, line) => R.chartStylesFor(idx, r, c, w, line).map((x) => x.style + (x.color ? '[' + x.color + ']' : '')).sort();
  assert.deepEqual(names(2, 3, 0, ''), ['hl']);                 // the row's highlight reaches every cell
  assert.deepEqual(names(2, 3, 1, 'txt'), ['hl', 'u']);         // and its first word adds its own
  assert.deepEqual(names(2, 4, 0, ''), ['color[red]', 'hl']);   // a column style on top
  assert.deepEqual(names(3, 5, 0, ''), ['b']);
  assert.deepEqual(names(1, 3, 1, 'gls'), ['i']);
  assert.deepEqual(names(1, 3, 1, 'txt'), []);
});

test('headers, visible columns, merged cells, free-translation runs', () => {
  const c = chart();
  const cols = c.template.columns;
  const hr = C.headerRows(cols);
  assert.equal(hr.length, 2);
  assert.deepEqual(hr[0].map((h) => [h.text, h.span]), [['Prenuclear', 2], ['Nucleus', 3], ['Postnuclear', 2]]);
  assert.deepEqual(hr[1].map((h) => h.text), ['Outer', 'Inner', 'Subject', 'Verb', 'Object', 'Inner', 'Outer']);
  // cols= by group, by path, by position, by abbreviation; an unknown selection shows everything
  assert.deepEqual(C.visibleColumns({ extra: { cols: 'Nucleus' } }, c).map((x) => x.n), [3, 4, 5]);
  assert.deepEqual(C.visibleColumns({ extra: { cols: 'Postnuclear/Inner,c1' } }, c).map((x) => x.n), [1, 6]);
  assert.deepEqual(C.visibleColumns({ extra: { cols: 'c3-c5,Pre-O' } }, c).map((x) => x.n), [1, 3, 4, 5]);
  assert.deepEqual(C.visibleColumns({ extra: { cols: 'Inner' } }, c).map((x) => x.n), [2, 6]);     // the same name in two groups: both
  assert.equal(C.visibleColumns({ extra: { cols: 'nothing' } }, c).length, 7);
  // 3b: one group in Subject merging into Verb (and the empty Object stays its own cell)
  const lay = C.layoutRow(c.rows[6], cols);
  assert.deepEqual(lay.map((s) => [s.col.n, s.span, s.parts.length]), [[1, 1, 0], [2, 1, 0], [3, 2, 1], [5, 1, 0], [6, 1, 0], [7, 1, 0]]);
  // 2a and 2b both come from segment 3: one Free cell for the two of them
  const runs = C.freeRuns(c.rows);
  assert.deepEqual(runs.map((r) => [r.from, r.to, r.segs]), [[0, 0, [1]], [1, 1, [2]], [2, 3, [3]], [4, 4, [4]], [5, 5, [5]], [6, 6, [6]]]);
  assert.deepEqual(C.freeText(c, [3], true), ['‘“Mother!” he sees.’']);
  // a row holding the end of one segment and the start of the next (Siakai row 1 = 1.1 + 2.1,
  // 2a–2b = 2.1): each translation once, after the last row of its segment, runs never overlap
  const seg = (n, w) => ({ kind: 'words', seg: n, segTo: n, words: [{ txt: 'w' + w }] });
  const rows = [{ cells: [seg(1, 0), seg(2, 0)] }, { cells: [seg(2, 1)] }, { cells: [seg(2, 2)] }, { cells: [{ kind: 'tag', tag: {} }] }];
  assert.deepEqual(C.freeRuns(rows).map((r) => [r.from, r.to, r.segs]), [[0, 0, [1]], [1, 3, [2]]]);
  assert.deepEqual(C.freeRuns([]), []);
  assert.deepEqual(C.freeText(c, [1, 2], true), ['‘The dog slept.’ (1.1)', '‘Yesterday the child saw the river.’ (1.2)']);
});

test('the TSV grid and the readable copy carry headers, words, markers, translations and notes', () => {
  const c = chart();
  const spec = R.parse('{{flex:chart ' + G + ' rows=1-4}}');
  c.rows = c.rows.slice(0, 4);
  const grid = C.chartGrid(spec, c);
  assert.deepEqual(grid[0], ['', 'Prenuclear', '', 'Nucleus', '', '', 'Postnuclear', '', 'Free', 'Notes'].slice(0, 9));   // no row of 1–4 has a note
  assert.deepEqual(grid[2].slice(0, 5), ['1a', '', '', 'Kabir/dog', 'ka-nuwa-mo/slept lo/DECL']);
  assert.equal(grid[2][6], '⟨new⟩');
  assert.equal(grid[3][7], '‹‹1b');
  assert.equal(grid[5][1], '[2a]');
  assert.equal(grid[3][8], '‘Yesterday the child saw the river.’');
  assert.equal(grid[4][8], '‘“Mother!” he sees.’');       // the run's first row carries it
  assert.equal(grid[5][8], '');
  const tsv = C.chartTsv(spec, c);
  assert.ok(tsv.split('\n')[2].startsWith('1a\t\t\tKabir/dog\tka-nuwa-mo/slept lo/DECL'));
  const copy = FS.flexcopy.build(spec, c);
  assert.equal(copy.ref, 'Story chart — The dog and the river, rows 1a–2b');
  assert.ok(copy.body.split('\n')[0].startsWith('    Prenuclear'), copy.body.split('\n')[0]);
  assert.ok(copy.body.includes('1b  Haŋa/yesterday'), copy.body);
  assert.ok(copy.inline.startsWith('Story chart — The dog and the river, rows 1a–2b: Kabir ka-nuwa-mo lo Haŋa'));
  // with notes shown (row 2c has one) the Notes column appears
  const full = chart();
  const g2 = C.chartGrid(R.parse('{{flex:chart ' + G + ' free=off}}'), full);
  assert.equal(g2[0][g2[0].length - 1], 'Notes');
  assert.equal(g2[6][g2[6].length - 1], 'Locative after the verb in the chart.');
});

test('a text’s chart spans become column tags on an example when the cols line is on', () => {
  const I = FS.interlinear;
  const text = { guid: 't', segments: [{ n: 1, words: [{ txt: 'Kabir', ai: 0 }, { txt: 'ka-nuwa-mo', ai: 1 }, { txt: 'lo', ai: 2 }, { txt: '.', punct: true, ai: 3 }] }], tags: [],
    chartSpans: [{ chart: 'c', chartName: 'Story chart', template: 'Default', row: '1a', column: { guid: 'g3', name: 'Subject', abbr: 'S', path: ['Nucleus'] }, from: { seg: 1, w: 0 }, to: { seg: 1, w: 0 } },
      { chart: 'c', chartName: 'Story chart', template: 'Default', row: '1a', column: { guid: 'g4', name: 'Verb', abbr: 'V', path: ['Nucleus'] }, from: { seg: 1, w: 1 }, to: { seg: 1, w: 2 } }] };
  const specOff = R.parse('{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1}}');
  const specOn = R.parse('{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1 lines=txt,gls,cols}}');
  assert.equal(R.showsCols(specOff), false);
  assert.equal(R.showsCols(specOn), true);
  assert.equal(I.withChartTags(text, specOff).tags.length, 0);
  const on = I.withChartTags(text, specOn);
  assert.equal(on.tags.length, 2);
  assert.equal(on.tags[0].tag.name, 'Nucleus/Subject');
  assert.equal(on.tags[0].tag.column, true);
  assert.equal(on.tags[1].tag.abbr, 'V');
  assert.deepEqual(on.tags[1].to, { seg: 1, w: 2 });
  const lanes = I.segTags(text, specOn, text.segments[0]);
  assert.equal(lanes.length, 2);
  assert.deepEqual(lanes.map((o) => [o.firstAi, o.lastAi]), [[0, 0], [1, 2]]);
  assert.equal(I.segTags(text, specOff, text.segments[0]).length, 0);
});

test('the pivot counts rows by marker and column', () => {
  const c = chart();
  const p = C.pivot(c, R.parse('{{flex:chart ' + G + '}}'));
  assert.deepEqual(p.columns, ['Prenuclear › Outer', 'Prenuclear › Inner', 'Nucleus › Subject', 'Nucleus › Verb', 'Nucleus › Object', 'Postnuclear › Inner', 'Postnuclear › Outer']);
  const by = Object.fromEntries(p.lines.map((l) => [l.key, l]));
  assert.deepEqual(by['m:New'].counts, [0, 0, 1, 1, 0, 0, 0]);
  assert.equal(by['m:New'].total, 1);
  assert.deepEqual(by['m:Given'].counts, [0, 0, 1, 1, 0, 1, 0]);
  assert.equal(by['clause:speech'].total, 1);
  assert.equal(by['moved:preposed'].counts[0], 1);
  assert.equal(by['clauseref'].total, 1);
  assert.deepEqual(p.totals, [1, 1, 5, 5, 1, 1, 0]);   // 3b's words sit in Subject (merged into Verb)
  assert.equal(p.rowCount, 7);
  const narrow = C.pivot(c, R.parse('{{flex:chart ' + G + ' cols=Nucleus}}'));
  assert.equal(narrow.columns.length, 3);
});
