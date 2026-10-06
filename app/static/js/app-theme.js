/* Apply preferences before styles paint and share them across pages and tabs. */
(() => {
    'use strict';
    const key = 'interview-ui-theme';
    const lightKey = 'interview-ui-light-theme';
    const root = document.documentElement;
    const system = matchMedia('(prefers-color-scheme: dark)');
    const themes = {
        playful: { label: '奶油', canvas: '#fff6ef' },
        'playful-sage': { label: '鼠尾草', canvas: '#f3f6ef' },
        'playful-blue': { label: '雾蓝', canvas: '#f1f5f9' },
        'playful-lavender': { label: '薰衣草', canvas: '#f6f3fa' },
        'playful-rose': { label: '玫瑰', canvas: '#fff3f4' },
        'playful-dark': { label: '暗色', canvas: '#1b1721' },
    };
    const valid = value => Object.hasOwn(themes, value);
    const validLight = value => valid(value) && value !== 'playful-dark';
    let preference = null;
    let lightPreference = 'playful';
    let storageAvailable = true;
    function readPreferences() {
        try {
            const saved = localStorage.getItem(key);
            const savedLight = localStorage.getItem(lightKey);
            preference = valid(saved) ? saved : null;
            lightPreference = validLight(saved) ? saved : validLight(savedLight) ? savedLight : 'playful';
        } catch (_) { storageAvailable = false; }
    }
    function apply(theme) {
        root.dataset.theme = theme;
        const dark = theme === 'playful-dark';
        document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themes[theme].canvas);
        const button = document.getElementById('app-theme-toggle');
        button?.setAttribute('aria-label', `选择主题，当前为${dark ? '暗色' : '亮色 · ' + themes[theme].label}`);
        document.querySelectorAll('input[name="app-theme-mode"]').forEach(input => {
            input.checked = input.value === (dark ? 'dark' : 'light');
        });
        document.querySelectorAll('input[name="app-theme-tone"]').forEach(input => {
            input.checked = input.value === lightPreference;
        });
        const tones = document.getElementById('app-theme-tones');
        if (tones) tones.hidden = dark;
        const hint = document.getElementById('app-theme-hint');
        if (hint) hint.textContent = dark ? `切回亮色将恢复${themes[lightPreference].label}色调` :
            storageAvailable ? '偏好会自动保存' : '当前浏览器无法保存偏好，本页仍可切换';
        window.dispatchEvent(new CustomEvent('app:theme-change', { detail: { theme, dark } }));
    }
    function choose(theme) {
        preference = theme;
        if (validLight(theme)) lightPreference = theme;
        try {
            localStorage.setItem(lightKey, lightPreference);
            localStorage.setItem(key, preference);
        } catch (_) { storageAvailable = false; }
        apply(theme);
    }
    const fallback = () => system.matches ? 'playful-dark' : lightPreference;
    readPreferences();
    apply(preference || fallback());
    document.addEventListener('DOMContentLoaded', () => {
        apply(root.dataset.theme);
        const control = document.getElementById('app-theme-control');
        const button = document.getElementById('app-theme-toggle');
        const panel = document.getElementById('app-theme-panel');
        if (!control || !button || !panel) return;
        function close(restoreFocus = false) {
            panel.hidden = true;
            button.setAttribute('aria-expanded', 'false');
            if (restoreFocus) button.focus();
        }
        function open() {
            document.querySelectorAll('.app-nav-more').forEach(menu => { menu.open = false; });
            document.getElementById('app-navigation')?.classList.remove('is-open');
            const menuButton = document.getElementById('app-menu-toggle');
            menuButton?.setAttribute('aria-expanded', 'false');
            menuButton?.setAttribute('aria-label', '打开导航菜单');
            panel.hidden = false;
            button.setAttribute('aria-expanded', 'true');
            panel.querySelector('input[name="app-theme-mode"]:checked')?.focus();
        }
        button.addEventListener('click', () => panel.hidden ? open() : close());
        button.addEventListener('keydown', event => {
            if (event.key === 'ArrowDown') { event.preventDefault(); open(); }
        });
        function chooseFromInput(input) {
            if (input.name === 'app-theme-mode') {
                choose(input.value === 'dark' ? 'playful-dark' : lightPreference);
            } else if (input.name === 'app-theme-tone' && validLight(input.value)) {
                choose(input.value);
            }
        }
        panel.addEventListener('change', event => chooseFromInput(event.target));
        panel.addEventListener('click', event => {
            // Explicitly choosing the already selected system default saves it too.
            if (!preference && event.target.checked) chooseFromInput(event.target);
        });
        document.addEventListener('click', event => { if (!control.contains(event.target)) close(); });
        control.addEventListener('focusout', event => {
            // Pointer-down on a label temporarily blurs the radio to the body.
            // Keep the panel mounted until pointer-up can activate that label.
            // Tab navigation has a real destination; outside clicks close above.
            if (event.relatedTarget && !control.contains(event.relatedTarget)) close();
        });
        control.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !panel.hidden) {
                event.preventDefault();
                event.stopPropagation();
                close(true);
            }
        });
    });
    system.addEventListener('change', () => { if (!preference) apply(fallback()); });
    window.addEventListener('storage', event => {
        if (event.key !== key && event.key !== lightKey && event.key !== null) return;
        readPreferences();
        apply(preference || fallback());
    });
})();
