// Keep the existing utility vocabulary while giving every template one palette.
const shades = values => Object.fromEntries(
  [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((key, i) => [key, values[i]]),
);
const plum = shades(['#f7eff7', '#eee1f0', '#dac5df', '#c4a6ca', '#a27ca6', '#8d587a', '#7b476b', '#693958', '#563148', '#432839', '#30202a']);
const peach = shades(['#fff1e8', '#f7decc', '#edc4a9', '#dba98f', '#c98b6c', '#a46748', '#92553b', '#75432f', '#633b2c', '#4e3026', '#38241d']);
const sage = shades(['#f1f5ed', '#e4ecd9', '#cadbb9', '#acc599', '#89a574', '#6c8a58', '#557143', '#425a34', '#364b2c', '#2c3d25', '#202d1b']);
const blue = shades(['#f1f0f8', '#e7e5f3', '#d1d0e5', '#b4b2d0', '#8e8cac', '#757498', '#625f81', '#4f4d6a', '#403e56', '#353445', '#252434']);
const warm = shades(['#faf7f7', '#f2edef', '#e8dfe6', '#d4c8d2', '#8d7c89', '#7b6d7a', '#665865', '#534652', '#453d48', '#342d36', '#27212a']);
const rose = shades(['#fff2f0', '#f8dfda', '#edc6bc', '#dfa498', '#c98477', '#b76c61', '#9b5148', '#823e37', '#6a332e', '#552b27', '#3c201d']);
const lightPalettes = require('./scripts/theme-palettes.cjs');
const lightThemes = Object.fromEntries(Object.entries(lightPalettes).map(([name, palette]) => [
  `playful-${name}`, {
    primary: palette.accent, 'primary-content': palette.surface,
    secondary: palette.secondary, 'secondary-content': palette.ink,
    accent: palette.hero, 'accent-content': palette.ink,
    neutral: palette.ink, 'neutral-content': palette.surface,
    'base-100': palette.surface, 'base-200': palette.soft, 'base-300': palette.line,
    'base-content': palette.ink,
    info: '#e7e5f3', 'info-content': '#504e6c',
    success: '#e4ecd9', 'success-content': '#425a34',
    warning: '#f6e5bd', 'warning-content': '#765126',
    error: '#f8dfda', 'error-content': '#823e37',
    '--rounded-box': '1.5rem', '--rounded-btn': '2rem', '--rounded-badge': '.65rem',
    '--animation-btn': '.18s', '--animation-input': '.18s',
    'color-scheme': 'light',
  },
]));

module.exports = {
  content: ['./app/templates/**/*.html', './app/static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        slate: warm, gray: warm, zinc: warm, neutral: warm, stone: warm,
        orange: peach, amber: peach, yellow: peach,
        indigo: plum, purple: plum, violet: plum, fuchsia: plum,
        emerald: sage, green: sage, teal: sage, lime: sage,
        blue, sky: blue, cyan: blue,
        red: rose, rose, pink: rose,
      },
      fontFamily: {
        sans: ['Avenir Next', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
    },
  },
  plugins: [require('daisyui')],
  daisyui: {
    logs: false,
    themes: [{
      ...lightThemes,
      playful: {
        primary: '#83556f', 'primary-content': '#fffdf9',
        secondary: '#e7b498', 'secondary-content': '#543b32',
        accent: '#d1e0be', 'accent-content': '#405332',
        neutral: '#453d48', 'neutral-content': '#fffdf9',
        'base-100': '#fffdf9', 'base-200': '#f5edeb', 'base-300': '#e8dfe6',
        'base-content': '#453d48',
        info: '#e7e5f3', 'info-content': '#504e6c',
        success: '#e4ecd9', 'success-content': '#425a34',
        warning: '#f6e5bd', 'warning-content': '#765126',
        error: '#f8dfda', 'error-content': '#823e37',
        '--rounded-box': '1.5rem', '--rounded-btn': '2rem', '--rounded-badge': '.65rem',
        '--animation-btn': '.18s', '--animation-input': '.18s',
      },
      'playful-dark': {
        primary: '#d9a3c1', 'primary-content': '#2b1c27',
        secondary: '#d9ab8f', 'secondary-content': '#2c211c',
        accent: '#b4cca2', 'accent-content': '#1f2c1c',
        neutral: '#332b39', 'neutral-content': '#efe5ed',
        'base-100': '#26212c', 'base-200': '#302936', 'base-300': '#413747',
        'base-content': '#f3eaf0',
        info: '#343148', 'info-content': '#c5c2e3',
        success: '#303c2d', 'success-content': '#bbd3aa',
        warning: '#443927', 'warning-content': '#edd19b',
        error: '#472f32', 'error-content': '#efb5ad',
        '--rounded-box': '1.5rem', '--rounded-btn': '2rem', '--rounded-badge': '.65rem',
        '--animation-btn': '.18s', '--animation-input': '.18s',
      },
    }],
  },
};
