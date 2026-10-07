/* Same design system, only the classes used by anonymous entry surfaces. */
const config = require('./tailwind.config.cjs');
module.exports = {
  ...config,
  content: [
    './app/templates/base.html', './app/templates/login.html',
    './app/templates/register.html', './app/templates/_navbar.html',
    './app/templates/_theme_switcher.html', './app/templates/_flash_messages.html',
  ],
};
