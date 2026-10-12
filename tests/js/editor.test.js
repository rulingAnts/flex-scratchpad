const test = require('node:test');
const assert = require('node:assert');
const { load } = require('./load.js');

const FS = load(['util', 'flexref', 'markdown', 'editor']);
const W = FS.editor.wrapLines;

test('collapsed selection inserts an empty pair with the caret inside', () => {
  assert.deepEqual(W('abc', 1, 1, '**'), { text: 'a****bc', a: 3, z: 3 });
});

test('single line selection wraps and unwraps', () => {
  const r = W('hello world', 6, 11, '*');
  assert.equal(r.text, 'hello *world*');
  assert.equal(r.text.slice(r.a, r.z), '*world*');
  const back = W(r.text, r.a, r.z, '*');
  assert.equal(back.text, 'hello world');
  // selecting only the inner word of an already wrapped span also unwraps
  assert.equal(W('hello *world*', 7, 12, '*').text, 'hello world');
});

test('a selection across lines wraps each line, not the whole span', () => {
  const text = 'first para\nsecond para';
  const r = W(text, 0, text.length, '*');
  assert.equal(r.text, '*first para*\n*second para*');
  assert.equal(W(r.text, 0, r.text.length, '*').text, text);
});

test('list bullets, numbers, task boxes, headings and quotes stay outside the markers; spaces too', () => {
  const text = '- one\n- [ ] two\n3. three\n# head\n> quote\n\n  spaced  ';
  const r = W(text, 0, text.length, '**');
  assert.equal(r.text, '- **one**\n- [ ] **two**\n3. **three**\n# **head**\n> **quote**\n\n  **spaced**  ');
});

test('partial lines: only the selected part of the first and last line is wrapped', () => {
  const text = 'aaa bbb\nccc ddd';
  const r = W(text, 4, 11, '*');     // "bbb\nccc"
  assert.equal(r.text, 'aaa *bbb*\n*ccc* ddd');
});
