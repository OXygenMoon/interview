/* Build light palettes and utility overrides, including hover and alpha. */
const { readFileSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const postcss = require('postcss');
const lightPalettes = require('./theme-palettes.cjs');
const source = resolve(__dirname, '../app/static/css', process.argv[2] || 'ui.css');
const output = resolve(__dirname, '../app/static/css', process.argv[3] || 'theme-utilities.css');
const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const neutral = ['#26212c', '#302936', '#413747', '#52445a', '#6a5972', '#816d88', '#67556e', '#4a3d52', '#2c2433', '#19161e', '#141119'];
const tinted = {
  plum: ['#302434', '#3a2c40', '#503951', '#76516c', '#956b88', '#a47794', '#825d78', '#63445d', '#452f42', '#30222e', '#211720'],
  peach: ['#332823', '#443129', '#594034', '#74523e', '#9f7156', '#aa795b', '#895b44', '#6b4534', '#4b3027', '#34231e', '#241815'],
  sage: ['#283026', '#333e2e', '#45543d', '#5a6c4e', '#748b64', '#839b71', '#61774f', '#4c5c40', '#36442d', '#252f20', '#192117'],
  blue: ['#292735', '#353144', '#454057', '#625b7b', '#80789e', '#9187ad', '#70688c', '#524b67', '#39344b', '#282536', '#1b1925'],
  rose: ['#352527', '#452f32', '#5c3b3e', '#805153', '#a16d6c', '#b87d78', '#965e5a', '#734442', '#512f31', '#382224', '#261719'],
};
const families = {
  slate: 'neutral', gray: 'neutral', zinc: 'neutral', neutral: 'neutral', stone: 'neutral',
  indigo: 'plum', purple: 'plum', violet: 'plum', fuchsia: 'plum',
  orange: 'peach', amber: 'peach', yellow: 'peach',
  emerald: 'sage', green: 'sage', teal: 'sage', lime: 'sage',
  blue: 'blue', sky: 'blue', cyan: 'blue', red: 'rose', rose: 'rose', pink: 'rose',
};
const ink = { neutral: '#eee2ed', plum: '#ddb6d5', peach: '#e8bea3', sage: '#bdd5ad', blue: '#c3bfdf', rose: '#efb8b0' };
function rgb(hex) { return hex.startsWith('var(') ? hex : [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)).join(' '); }
function replaceColor(value, hex) {
  return value.replace(/#[\da-f]{3,8}|rgba?\((?:[^()]|\([^()]*\))*\)/gi, original => {
    let alpha = original.match(/\/(.+)\)$/)?.[1].trim();
    if (original.startsWith('#') && [5, 9].includes(original.length)) {
      const digits = original.length === 5 ? original.at(-1).repeat(2) : original.slice(-2);
      alpha = String(Number((parseInt(digits, 16) / 255).toFixed(4)));
    }
    if (!alpha && original.startsWith('rgba')) alpha = original.match(/,\s*([\d.]+)\)$/)?.[1];
    return `rgb(${rgb(hex)}${alpha === undefined ? '' : ' / ' + alpha})`;
  });
}
const target = postcss.root();
const lightTarget = postcss.root();
postcss.parse(readFileSync(source, 'utf8')).walkRules(rule => {
  const plain = rule.selector.replace(/\\/g, '');
  const match = plain.match(/(?:^|[ .:>~+])(bg|text|border|ring|divide|from|via|to|placeholder|shadow)-(white|black|slate|gray|zinc|neutral|stone|indigo|purple|violet|fuchsia|orange|amber|yellow|emerald|green|teal|lime|blue|sky|cyan|red|rose|pink)(?:-(50|100|200|300|400|500|600|700|800|900|950))?(?=[\s:/.>,)]|$)/);
  if (!match) return;
  const [, kind, family, shade] = match;
  const group = families[family] || 'neutral';
  // Recolor accent utilities and white surfaces without changing status colors.
  if (group === 'plum' || (family === 'white' && kind === 'bg')) {
    const lightClone = rule.clone({ nodes: [] });
    lightClone.selector = rule.selectors.map(selector => {
      const position = selector.indexOf('::');
      const exclude = ':not(:where(#resume-preview, #resume-preview *))';
      const scoped = position < 0 ? selector + exclude : selector.slice(0, position) + exclude + selector.slice(position);
      return `:where(html[data-theme^="playful-"]:not([data-theme="playful-dark"])) .app-main ${scoped}`;
    }).join(',');
    const token = family === 'white' ? 'var(--tone-surface)' : `var(--tone-${shade || 500})`;
    rule.walkDecls(decl => {
      if (/color|background|shadow|gradient|fill|stroke/.test(decl.prop)) {
        const changed = replaceColor(decl.value, token);
        if (changed !== decl.value) lightClone.append(decl.clone({ value: changed }));
      }
    });
    if (lightClone.nodes.length) {
      let block = lightClone;
      for (let parent = rule.parent; parent.type !== 'root'; parent = parent.parent) {
        if (parent.type === 'atrule') { const wrapper = parent.clone({ nodes: [] }); wrapper.append(block); block = wrapper; }
      }
      lightTarget.append(block);
    }
  }
  const index = Math.max(0, shades.indexOf(Number(shade)));
  let hex;
  if (['text', 'placeholder'].includes(kind)) {
    hex = family === 'white' ? '#fffdf9' : family === 'black' ? '#f3eaf0' : group === 'neutral' && Number(shade) <= 500 ? ['#fff5fd', '#eee2ed', '#ded1df', '#cfc0ce', '#b9abba', '#b9abba'][index] : ink[group];
  } else if (['border', 'divide', 'ring'].includes(kind)) {
    hex = family === 'white' ? '#68576e' : family === 'black' ? '#413747' : (tinted[group] || neutral)[Math.min(6, Math.max(2, index))];
  } else if (kind === 'shadow') hex = '#100c16';
  else hex = family === 'white' ? '#26212c' : family === 'black' ? '#100d16' : (tinted[group] || neutral)[index];
  const clone = rule.clone({ nodes: [] });
  clone.selector = rule.selectors.map(selector => {
    const position = selector.indexOf('::');
    const exclude = ':not(:where(#resume-preview, #resume-preview *))';
    const scoped = position < 0 ? selector + exclude : selector.slice(0, position) + exclude + selector.slice(position);
    return `:where(html[data-theme="playful-dark"]) .app-main ${scoped}`;
  }).join(',');
  rule.walkDecls(decl => {
    if (/color|background|shadow|gradient|fill|stroke/.test(decl.prop)) {
      const changed = replaceColor(decl.value, hex);
      if (changed !== decl.value) clone.append(decl.clone({ value: changed }));
    }
  });
  if (!clone.nodes.length) return;
  let block = clone;
  for (let parent = rule.parent; parent.type !== 'root'; parent = parent.parent) {
    if (parent.type === 'atrule') { const wrapper = parent.clone({ nodes: [] }); wrapper.append(block); block = wrapper; }
  }
  target.append(block);
});
writeFileSync(output, '/* Generated by scripts/build-theme-utilities.cjs; do not edit. */\n' + lightTarget.toString() + '\n' + target.toString());
const lightCSS = Object.entries(lightPalettes).map(([name, palette]) => {
  const variables = {
    '--ui-canvas': palette.canvas, '--ui-surface': palette.surface,
    '--ui-ink': palette.ink, '--ui-muted': palette.muted, '--ui-line': palette.line,
    '--ui-accent': palette.accent, '--ui-peach': palette.hero, '--ui-lilac': palette.soft,
    '--theme-primary-hover': palette.hover, '--theme-soft': palette.shades[0], '--theme-border': palette.shades[2],
    '--tone-surface': rgb(palette.surface),
    ...Object.fromEntries(shades.map((shade, index) => [`--tone-${shade}`, rgb(palette.shades[index])])),
  };
  return `html[data-theme="playful-${name}"] {\n    color-scheme: light;\n${Object.entries(variables).map(([key, value]) => `    ${key}: ${value};`).join('\n')}\n}`;
}).join('\n');
writeFileSync(resolve(__dirname, '../app/static/css/light-themes.css'),
  '/* Generated from scripts/theme-palettes.cjs; do not edit. */\n' + lightCSS + '\n');
