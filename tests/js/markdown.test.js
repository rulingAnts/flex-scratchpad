// node --test tests/js   — the pure logic of the UI, loaded as the classic scripts they are.
const test = require('node:test');
// legacy (loose) assert: the scripts run in their own vm context, so their arrays and objects
// have different prototypes from the test's — strict deepEqual would reject every structure.
const assert = require('node:assert');
const { load } = require('./load.js');

const FS = load(['util', 'flexref', 'markdown', 'tables', 'charts']);
const MD = FS.markdown;

test('blocks split on blank lines and keep lists, tables, fences, embeds whole', () => {
  const md = ['# Title', '', 'Para one', 'still para', '- a', '- b', '1. c', '', '| h | i |', '|---|:-:|', '| {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} | x |', '{table: striped}', '', '{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1}}', '', '```chart', 'type: bar', '```', '', '---', '> q', '![alt](file:///x.png)'].join('\n');
  const b = MD.splitBlocks(md);
  assert.deepEqual(b.map((x) => x.type), ['h', 'p', 'list', 'table', 'flex', 'chart', 'hr', 'quote', 'image']);
  assert.equal(b[1].src, 'Para one\nstill para');
  assert.equal(b[3].src.split('\n').length, 4);
  assert.equal(MD.joinBlocks(b).split('\n\n').length, 9);
});

test('decoration keeps every character (textContent === markdown)', () => {
  const src = 'Para **bold** and *it* ~~s~~ ==hl== `c` [x](http://a.b) [[Other]] #tag {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} snake_case 2*3*4';
  const html = MD.decorate(src, 'p');
  const text = html.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  assert.equal(text, src);
  assert.match(html, /<span class="md-marker">\*\*<\/span><span class="md-b">bold<\/span>/);
  assert.match(html, /md-tag/);
  assert.match(html, /md-embed/);
  assert.doesNotMatch(html, /md-i">case/);
});

test('empty lines get a <br> so the caret has a line to sit on', () => {
  assert.equal(MD.decorate('', 'p'), '<span class="md-line "><br></span>');
  assert.equal(MD.decorate('a\n', 'p').split('\n')[1], '<span class="md-line "><br></span>');
});

test('task and heading markers', () => {
  const html = MD.decorate('- [x] done\n- [ ] todo', 'list');
  assert.match(html, /md-task md-task-on">\[x\]/);
  assert.match(html, /md-line-task md-done/);
  assert.match(MD.decorate('## Head', 'h'), /md-marker md-h md-h2">## <\/span><span class="md-h md-h2">Head/);
});

test('renderInline hides markers and emits links, tags and embed placeholders', () => {
  const html = MD.renderInline('**b** [x](http://a.b) [[N]] #t {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} a<br>b');
  assert.equal(html, '<strong>b</strong> <a class="ext-link" href="http://a.b" data-href="http://a.b">x</a> <a class="wikilink" href="note:N" data-href="note:N">N</a> <span class="inline-tag">#t</span> <span class="flex-inline" data-src="{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}"></span> a<br>b');
});

test('tables: cells split outside embeds, backticks and escaped pipes; style line round-trips', () => {
  const src = '| a | b |\n|:--|--:|\n| {{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1 u="a|b"}} | x \\| y |\n| `p|q` | l1<br>l2 |\n{table: striped; borders light; col 2: bold, center, width 30%; row 2: bg #fff2a8}';
  const t = FS.tables.parse(src);
  assert.equal(t.rows.length, 3);
  assert.equal(t.rows[1][0], '{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1 u="a|b"}}');
  assert.equal(t.rows[1][1], 'x | y');
  assert.equal(t.rows[2][0], '`p|q`');
  assert.deepEqual(t.aligns, ['left', 'right']);
  assert.ok(t.style.flags.has('striped') && t.style.flags.has('borders-light'));
  assert.deepEqual(t.style.cols[2], { bold: true, align: 'center', width: '30%' });
  assert.deepEqual(t.style.rows[2], { bg: '#fff2a8' });
  const out = FS.tables.serialize(t);
  assert.equal(out.split('\n').pop(), '{table: striped; borders light; col 2: bold, center, width 30%; row 2: bg #fff2a8}');
  assert.ok(out.includes('x \\| y') && out.includes('l1<br>l2'));
  assert.deepEqual(FS.tables.parse(out).rows, t.rows);
});

test('charts: DSL parses and serialises', () => {
  const spec = FS.charts.parse('```chart\ntype: stacked\ntitle: T\nlabels: a, b\nseries: one = 1, 2\nseries: two = 3, 4\ncolors: #111, #222\n```');
  assert.equal(spec.type, 'stacked');
  assert.deepEqual(spec.labels, ['a', 'b']);
  assert.deepEqual(spec.series.map((s) => s.values), [[1, 2], [3, 4]]);
  assert.equal(spec.errors.length, 0);
  const back = FS.charts.parse(FS.charts.serialize(spec));
  assert.deepEqual(back.series, spec.series);
  assert.ok(FS.charts.parse('```chart\nnonsense\n```').errors.length);
  assert.equal(FS.charts.parse('```chart\n{"type":"pie","labels":["x"],"series":[{"name":"s","values":[1]}]}\n```').type, 'pie');
});

test('tables: freeze panes and height round-trip through the style line', () => {
  const t = FS.tables.parse('| a | b |\n|---|---|\n| 1 | 2 |\n{table: striped; freeze rows 1; freeze cols 2; max-height 300px}');
  assert.equal(t.style.freezeRows, 1); assert.equal(t.style.freezeCols, 2); assert.equal(t.style.maxHeight, '300px');
  assert.equal(FS.tables.serialize(t).split('\n').pop(), '{table: striped; freeze rows 1; freeze cols 2; max-height 300px}');
});

test('tables: merged cells live in the style line and split/merge keep them', () => {
  const T = FS.tables;
  const t = FS.tables.parse('| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n| 7 | 8 | 9 |');
  assert.ok(T.mergeCell(t, 1, 0, 'right'));
  assert.ok(T.mergeCell(t, 1, 0, 'down'));
  assert.deepEqual(t.style.spans, { '2.1': { rows: 2, cols: 2 } });
  assert.equal(t.rows[1][0], '1<br>2<br>4<br>5');
  assert.equal(t.rows[1][1] + t.rows[2][0] + t.rows[2][1], '');
  assert.ok(!T.mergeCell(t, 0, 0, 'down'), 'header never merges into the body');
  assert.ok(!T.mergeCell(t, 2, 2, 'right'), 'cannot leave the grid');
  const out = T.serialize(t);
  assert.ok(out.endsWith('{table: span 2.1: 2x2}'), out);
  const back = T.parse(out);
  const m = T.spanMap(back);
  assert.deepEqual(m.anchors, { '1.0': { rows: 2, cols: 2 } });
  assert.deepEqual([...m.covered.keys()].sort(), ['1.1', '2.0', '2.1']);
  // split above body row 3 (0-based 3 = "7 8 9"): both halves keep the header
  const [top, bottom] = T.splitAt(back, 3);
  assert.deepEqual(top.rows.map((r) => r[0]), ['a', '1<br>2<br>4<br>5', '']);
  assert.deepEqual(bottom.rows, [['a', 'b', 'c'], ['7', '8', '9']]);
  assert.deepEqual(top.style.spans, { '2.1': { rows: 2, cols: 2 } });
  // merge back: the repeated header is dropped
  const merged = T.mergeTables(top, bottom);
  assert.equal(T.serialize(merged), out);
  // a table with a different header keeps that header as a body row
  const other = T.parse('| x | y |\n|---|---|\n| 10 | 11 |');
  const m2 = T.mergeTables(bottom, other);
  assert.deepEqual(m2.rows, [['a', 'b', 'c'], ['7', '8', '9'], ['x', 'y', ''], ['10', '11', '']]);
  // deleting the anchor row drops the span; inserting a row inside it grows it
  const t3 = T.parse(out);
  t3.rows.splice(2, 0, ['n', 'n', 'n']);
  FS.tables.shiftRowStyles && FS.tables.shiftRowStyles(t3, 3, 1);
  assert.ok(!T.unmergeCell(T.parse('| a |\n|---|\n| 1 |'), 1, 0));
  assert.ok(T.unmergeCell(T.parse(out), 2, 1), 'unmerge from a covered cell');
});

test('tables: a range of cells merges into one span and unmerges again', () => {
  const T = FS.tables;
  const t = FS.tables.parse('| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n| 7 | 8 | 9 |');
  assert.ok(T.mergeRange(t, { r1: 1, c1: 1, r2: 2, c2: 2 }));
  assert.deepEqual(t.style.spans, { '2.2': { rows: 2, cols: 2 } });
  assert.equal(t.rows[1][1], '2<br>3<br>5<br>6');
  // a range touching the merged cell grows to include it
  assert.deepEqual(T.growToSpans(t, { r1: 2, c1: 0, r2: 2, c2: 1 }), { r1: 1, c1: 0, r2: 2, c2: 2 });
  assert.ok(T.mergeRange(t, { r1: 2, c1: 0, r2: 2, c2: 1 }));
  assert.deepEqual(t.style.spans, { '2.1': { rows: 2, cols: 3 } });
  assert.equal(t.rows[1][0], '1<br>2<br>3<br>5<br>6<br>4');
  assert.ok(!T.mergeRange(t, { r1: 0, c1: 0, r2: 1, c2: 0 }), 'header never merges down');
  assert.ok(T.mergeRange(t, { r1: 0, c1: 0, r2: 0, c2: 1 }), 'header merges sideways');
  assert.ok(T.unmergeRange(t, { r1: 1, c1: 1, r2: 1, c2: 1 }));
  assert.deepEqual(t.style.spans, { '1.1': { rows: 1, cols: 2 } });
  assert.ok(!T.unmergeRange(t, { r1: 2, c1: 2, r2: 2, c2: 2 }));
});

test('tables: the frame size round-trips', () => {
  const t = FS.tables.parse('| a |\n|---|\n| 1 |\n{table: max-height 300px; frame-width 640px}');
  assert.equal(t.style.maxHeight, '300px'); assert.equal(t.style.frameWidth, '640px');
  assert.equal(FS.tables.serialize(t).split('\n').pop(), '{table: max-height 300px; frame-width 640px}');
  const [top] = FS.tables.splitAt(t, 1) || [null];
  assert.ok(top === null || top.style.frameWidth === '640px');
});

test('outline numbers are computed per level and carry across loose-list blocks', () => {
  const MD = FS.markdown;
  const ctx = { counters: [] };
  assert.deepEqual(MD.numberLines(['1. one', '  2. sub a', '  3. sub b', '9. two'], 'list', ctx), [1, 1, 2, 2]);
  // a blank line between items (a separate block) continues the count ("3." would show 3); a
  // typed jump forward goes there (Seth, 2026-10-16); a bullet resets deeper levels
  assert.deepEqual(MD.numberLines(['3. three', '  - bullet', '  1. sub'], 'list', ctx), [3, null, 1]);
  assert.deepEqual(MD.numberLines(['6. six'], 'list', ctx), [6]);
  // a paragraph resets; the next list starts at its own first number
  MD.numberLines(['prose'], 'p', ctx);
  assert.deepEqual(MD.numberLines(['7. again'], 'list', ctx), [7]);
  assert.deepEqual(MD.numberLines(['1. again'], 'list', { counters: [] }), [1]);
  // decorate shows the computed number and keeps the typed text intact
  const html = MD.decorate('1. one\n  2. sub', 'list', { counters: [] });
  assert.equal((html.match(/data-num="1\."/g) || []).length, 4);          // on the line AND on the number span
  assert.match(html, /<span class="md-marker md-num" data-num="1\.">\s*2\. <\/span>/);
  assert.match(html, /md-num" data-num="1\.">\s*2\. <\/span>/);
  assert.equal(html.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&'), '1. one\n  2. sub');
});

test('an embed inside a line of text becomes a chip span whose text is still the markdown', () => {
  const g = '6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001';
  const src = 'see {{flex:entry ' + g + '}} and {{flex:text ' + g + ' seg=2-3 "label"}} here';
  const html = MD.decorate(src, 'p');
  assert.equal(html.replace(/<[^>]+>/g, '').replace(/&quot;/g, '"'), src);
  assert.match(html, /<span class="md-embed" contenteditable="false" draggable="true" data-src="\{\{flex:entry [^"]+\}\}" data-icon="📖" data-title="entry 6a5f3a2e…">/);
  assert.match(html, /data-icon="¶" data-title="label" data-range="2–3"/);
  // a whole-line embed is not inline (it is a block of its own)
  assert.equal(MD.splitBlocks('{{flex:entry ' + g + '}}')[0].type, 'flex');
  assert.equal(MD.splitBlocks(src)[0].type, 'p');
});

test('tables: a row height round-trips through the style line', () => {
  const t = FS.tables.parse('| a | b |\n|---|---|\n| 1 | 2 |\n{table: row 2: height 48px; col 1: width 120px}');
  assert.equal(t.style.rows[2].height, '48px');
  assert.equal(t.style.cols[1].width, '120px');
  assert.match(FS.tables.serialize(t), /row 2: height 48px/);
});

test('tables: the indent level round-trips through the style line', () => {
  const t = FS.tables.parse('| a | b |\n|---|---|\n| 1 | 2 |\n{table: striped; indent 2}');
  assert.equal(t.style.indent, 2);
  assert.match(FS.tables.serialize(t), /indent 2/);
  t.style.indent = 0;
  assert.doesNotMatch(FS.tables.serialize(t), /indent/);
});

test('a list starts at its first typed number; a new block restarts when its number is not the next', () => {
  const ctx = { counters: [] };
  assert.deepEqual(MD.numberLines(['3. a', '7. b', '  1. c', '9. d'], 'list', ctx), [3, 4, 1, 5]);   // start at 3; typed digits inside the block are ignored
  assert.deepEqual(MD.numberLines(['6. e'], 'list', ctx), [6]);        // the next number continues the loose list
  assert.deepEqual(MD.numberLines(['1. f'], 'list', ctx), [1]);        // "1 again" after a blank line starts over
  assert.deepEqual(MD.numberLines(['2. g'], 'list', ctx), [2]);
  assert.deepEqual(MD.numberLines(['10. h'], 'list', ctx), [10]);      // a jump forward goes there
  assert.deepEqual(MD.numberLines(['4. i'], 'list', ctx), [11]);       // a smaller number is stale (something was added above): the count continues
  const c2 = { counters: [] };
  assert.deepEqual(MD.numberLines(['1. a', '1. b', '1. c'], 'list', c2), [1, 2, 3]);   // the "1." style still counts
});

test('collapsible headings: the fold rides in the file, not in the text; sections end at the same or a higher level', () => {
  // Seth, 2026-10-16: "headings to be collapsible (with material between that heading and the
  // NEXT heading of the same or higher level)"
  const md = ['# Chapter {collapsed}', '', 'intro', '', '## Part A', '', 'a text', '', '### Deep {collapsed}', '', 'deep text', '', '## Part B', '', 'b text', '', '# Next'].join('\n');
  const b = MD.splitBlocks(md);
  assert.deepEqual(b.map((x) => x.src), ['# Chapter', 'intro', '## Part A', 'a text', '### Deep', 'deep text', '## Part B', 'b text', '# Next']);
  assert.deepEqual(b.map((x) => !!x.folded), [true, false, false, false, true, false, false, false, false]);
  assert.equal(MD.joinBlocks(b), md);                                     // round-trips exactly
  assert.deepEqual(b.map((x) => MD.headingLevel(x)), [1, 0, 2, 0, 3, 0, 2, 0, 1]);
  // the closed chapter hides everything up to "# Next"; the closed ### inside it adds nothing
  assert.deepEqual(MD.hiddenByFolds(b), [false, true, true, true, true, true, true, true, false]);
  b[0].folded = false;
  // now only "### Deep" is closed: it hides "deep text", and "## Part B" (higher level) ends it
  assert.deepEqual(MD.hiddenByFolds(b), [false, false, false, false, false, true, false, false, false]);
  assert.equal(MD.sectionEnd(b, 0), 7);
  assert.equal(MD.sectionEnd(b, 2), 5);
  assert.equal(MD.sectionEnd(b, 4), 5);
  assert.equal(MD.sectionEnd(b, 8), 8);
  assert.equal(MD.sectionEnd(b, 1), 1);                                   // not a heading
  assert.ok(!/collapsed/.test(MD.joinBlocks(b).split('\n')[0]));
});

test('an attached file in a line is a chip too (its own icon and name), alone on a line a block', () => {
  const F = load(['util', 'flexref', 'markdown', 'files']);
  const src = 'the survey {{file attachments/Survey%20ŋa.html}} and {{file C:/x/rec.wav "Recording 3"}} here';
  const html = F.markdown.decorate(src, 'p');
  assert.equal(html.replace(/<[^>]+>/g, '').replace(/&quot;/g, '"'), src);
  assert.match(html, /data-kind="file" data-icon="🌐" data-title="Survey ŋa\.html"/);
  assert.match(html, /data-kind="file" data-icon="🔊" data-title="Recording 3"/);
  assert.equal(F.markdown.splitBlocks('{{file attachments/a.pdf}}')[0].type, 'flex');
  assert.equal(F.files.kindOf('a/b/Notes.HTM'), 'html');
  assert.equal(F.files.kindOf('setup.exe'), 'program');
  assert.equal(F.files.kindOf('README'), 'file');
  // a picture or a video shows in the note when it has a line of its own; anything else is a card
  assert.equal(F.files.embedFor({ ref: 'attachments/photo 1.jpg', kind: 'image' }), '{{file attachments/photo%201.jpg preview}}');
  assert.equal(F.files.embedFor({ ref: 'attachments/clip.mp4' }), '{{file attachments/clip.mp4 preview}}');
  assert.equal(F.files.embedFor({ ref: 'attachments/a.pdf', kind: 'pdf' }), '{{file attachments/a.pdf}}');
  assert.ok(F.files.isLinked('C:\\x\\y.pdf') && F.files.isLinked('\\\\server\\share\\y.pdf') && !F.files.isLinked('attachments/y.pdf'));
});

test('a blank FLEx line (Shift+Enter, spaces, nothing to read) is left out; punctuation or a translation is not blank', () => {
  const F = load(['util', 'flexref', 'markdown', 'interlinear']);
  const b = F.interlinear.blankSeg;
  assert.ok(b({ baseline: ' ', words: [] }));
  assert.ok(b({ baseline: '  ​﻿', words: [{ txt: ' ', punct: true }], free: ' ', notes: [''] }));
  assert.ok(!b({ baseline: '', words: [], free: 'A translation' }));
  assert.ok(!b({ baseline: '', words: [], notes: ['a note'] }));
  assert.ok(!b({ baseline: '.', words: [{ txt: '.', punct: true }] }));
  assert.ok(!b({ baseline: 'Kabir', words: [{ txt: 'Kabir' }] }));
});
