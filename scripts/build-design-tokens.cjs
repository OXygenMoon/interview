/* tokens.css is the source; Flask serves the generated local copy. */
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
fs.copyFileSync(path.join(root, 'tokens.css'), path.join(root, 'app/static/css/tokens.css'));
