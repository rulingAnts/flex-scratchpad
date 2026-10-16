// Loads the classic UI scripts into a bare context for node:test (no DOM needed for the logic modules).
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const UI = path.join(__dirname, '..', '..', 'flex_scratchpad', 'ui', 'js');
function load(names) {
  const ctx = { console, Intl, setTimeout, clearTimeout };
  ctx.window = ctx; ctx.globalThis = ctx;
  ctx.document = { createElement: () => ({ style: {}, appendChild() {}, addEventListener() {}, classList: { add() {} } }), addEventListener() {}, removeEventListener() {}, readyState: 'loading', body: { appendChild() {} }, getElementById: () => null, querySelectorAll: () => [] };
  vm.createContext(ctx);
  for (const n of names) vm.runInContext(fs.readFileSync(path.join(UI, n + '.js'), 'utf8'), ctx, { filename: n + '.js' });
  return ctx.FS;
}
module.exports = { load };
