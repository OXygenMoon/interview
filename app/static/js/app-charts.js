/* Keep existing chart data and colors; adapt readability without a reload. */
(() => {
    'use strict';
    const originals = new WeakMap();
    const darkColors = {
        '#8d587a': '#d9a3c1', '#7b476b': '#d9a3c1', '#a27ca6': '#c8b2dd',
        '#c98b6c': '#e2b292', '#a46748': '#e2b292', '#6c8a58': '#b4cca2',
        '#89a574': '#c4d7b5', '#b76c61': '#e9aaa3', '#9b5148': '#e9aaa3',
        '#757498': '#b6b4dc', '#342d36': '#ded1df', '#453d48': '#ded1df',
        '#d4c8d2': '#9b91a4', '#6366f1': '#d9a3c1', '#10b981': '#b4cca2',
    };
    function color(value, surface, replacements = darkColors) {
        if (Array.isArray(value)) return value.map(item => color(item, surface, replacements));
        if (typeof value !== 'string') return value; // Keep CanvasGradient fills.
        let rgb;
        let alpha = 1;
        if (/^#[\da-f]{3}$/i.test(value)) value = '#' + [...value.slice(1)].map(c => c + c).join('');
        const match = value.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/);
        if (match) {
            rgb = '#' + match.slice(1, 4).map(c => Number(c).toString(16).padStart(2, '0')).join('');
            alpha = match[4] === undefined ? 1 : Number(match[4]);
        } else rgb = value.toLowerCase();
        const result = rgb === '#ffffff' ? surface : replacements[rgb];
        if (!result) return value;
        return alpha === 1 ? result : `rgba(${[1, 3, 5].map(i => parseInt(result.slice(i, i + 2), 16)).join(',')},${alpha})`;
    }
    function adapt(chart) {
        const style = getComputedStyle(document.documentElement);
        const dark = document.documentElement.dataset.theme === 'playful-dark';
        const ink = style.getPropertyValue('--ui-ink').trim();
        const muted = style.getPropertyValue('--ui-muted').trim();
        const line = style.getPropertyValue('--ui-line').trim();
        const surface = style.getPropertyValue('--ui-surface').trim();
        const accent = style.getPropertyValue('--ui-accent').trim();
        const lightColors = { '#8d587a': accent, '#7b476b': accent, '#a27ca6': accent, '#6366f1': accent };
        const tinted = document.documentElement.dataset.theme !== 'playful';
        const options = chart.options;
        options.color = muted;
        for (const scale of Object.values(options.scales || {})) {
            if (scale.ticks) { scale.ticks.color = muted; scale.ticks.backdropColor = surface; }
            if (scale.grid) scale.grid.color = line;
            if (scale.border) scale.border.color = line;
            if (scale.angleLines) scale.angleLines.color = line;
            if (scale.pointLabels) scale.pointLabels.color = ink;
            if (scale.title) scale.title.color = ink;
        }
        if (options.plugins.legend?.labels) options.plugins.legend.labels.color = ink;
        if (options.plugins.title) options.plugins.title.color = ink;
        if (options.plugins.tooltip) {
            Object.assign(options.plugins.tooltip, {
                backgroundColor: dark ? '#f3eaf0' : '#453d48',
                titleColor: dark ? '#26212c' : '#fffdf9',
                bodyColor: dark ? '#26212c' : '#fffdf9',
            });
        }
        for (const dataset of chart.data.datasets) {
            if (!originals.has(dataset)) {
                const saved = {};
                for (const property of ['borderColor', 'backgroundColor', 'pointBorderColor', 'pointBackgroundColor', 'pointHoverBorderColor', 'pointHoverBackgroundColor']) {
                    if (dataset[property] !== undefined) saved[property] = dataset[property];
                }
                originals.set(dataset, saved);
            }
            for (const [property, value] of Object.entries(originals.get(dataset))) {
                dataset[property] = dark ? color(value, surface) : tinted ? color(value, surface, lightColors) : value;
            }
        }
    }
    Chart.register({ id: 'appTheme', beforeUpdate: adapt });
    window.addEventListener('app:theme-change', () => {
        for (const chart of Object.values(Chart.instances)) chart.update('none');
    });
})();
