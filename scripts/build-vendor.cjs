const { copyFileSync, mkdirSync } = require('node:fs');
const { resolve } = require('node:path');
const root = resolve(__dirname, '..');
const destination = resolve(root, 'app/static/vendor');
mkdirSync(destination, { recursive: true });
for (const [source, target] of [
  ['chart.js/dist/chart.umd.js', 'chart.umd.js'],
  ['marked/marked.min.js', 'marked.min.js'],
  ['chart.js/LICENSE.md', 'chart-LICENSE.md'],
  ['marked/LICENSE.md', 'marked-LICENSE.md'],
]) copyFileSync(resolve(root, 'node_modules', source), resolve(destination, target));
