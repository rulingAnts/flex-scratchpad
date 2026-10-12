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
