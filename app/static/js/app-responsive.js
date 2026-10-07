/* Mobile records share their source data and actions with the desktop table. */
(() => {
    'use strict';
    const main = document.getElementById('main-content');
    if (!main) return;
    const compact = matchMedia('screen and (max-width: 1023px)');
    const tables = new Set();
    const sizes = new ResizeObserver(() => scheduleRefresh());
    let pending = false;
    let returnFocus;
    const text = node => node?.textContent.replace(/\s+/g, ' ').trim() || '';
    const dialog = document.createElement('dialog');
    dialog.className = 'modal mobile-record-dialog';
    dialog.setAttribute('aria-labelledby', 'mobile-record-title');
    const box = document.createElement('div');
    box.className = 'modal-box';
    const title = document.createElement('h2');
    title.id = 'mobile-record-title';
    title.className = 'text-lg font-bold';
    const fields = document.createElement('dl');
    fields.className = 'record-detail-fields';
    const footer = document.createElement('div');
    footer.className = 'modal-action';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn';
    close.textContent = '关闭';
    close.setAttribute('aria-label', '关闭记录详情');
    close.addEventListener('click', () => dialog.close());
    footer.append(close);
    box.append(title, fields, footer);
    dialog.append(box);
    main.append(dialog);
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => {
        if (returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
        fields.replaceChildren();
    });

    function scheduleRefresh() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; refresh(); });
    }
    function openRecord(row, trigger) {
        const table = row.closest('table');
        const headers = [...(table.tHead?.rows[0]?.cells || [])].map(text);
        title.textContent = text(row.querySelector('.mobile-record-heading')) || '记录详情';
        fields.replaceChildren();
        [...row.cells].filter(cell => !cell.hasAttribute('data-mobile-generated')).forEach((cell, index) => {
            const group = document.createElement('div');
            const label = document.createElement('dt');
            label.textContent = headers[index] || `信息 ${index + 1}`;
            const value = document.createElement('dd');
            const source = cell.querySelector('.mobile-cell-value');
            const clone = source.cloneNode(true);
            // Preserve event listeners on the original actions, including async buttons.
            const originalControls = [...source.querySelectorAll('button')];
            const clonedControls = [...clone.querySelectorAll('button')];
            clone.querySelectorAll('*').forEach(element => {
                element.removeAttribute('id');
                for (const attr of [...element.attributes]) {
                    if (attr.name.startsWith('on')) element.removeAttribute(attr.name);
                }
            });
            clonedControls.forEach((button, controlIndex) => button.addEventListener('click', event => {
                event.preventDefault();
                const original = originalControls[controlIndex];
                dialog.close();
                original.click();
            }));
            value.append(clone);
            group.append(label, value);
            fields.append(group);
        });
        returnFocus = trigger || row;
        dialog.showModal();
        close.focus();
    }

    function adaptRow(table, row, headers) {
        const cells = [...row.cells].filter(cell => !cell.hasAttribute('data-mobile-generated'));
        if (!cells.length) return;
        if (cells.length === 1 && cells[0].colSpan > 1) {
            row.classList.add('mobile-empty-row');
            return;
        }
        const primary = Math.min(Number(table.dataset.mobilePrimary || 0), cells.length - 1);
        const fallbackMetric = headers.reduce((found, label, index) => /分|得分|结果|类型|累计/.test(label) ? index : found, -1);
        const metric = Math.min(Number(table.dataset.mobileMetric ?? (fallbackMetric > 0 ? fallbackMetric : 1)), cells.length - 1);
        cells.forEach((cell, index) => {
            if (!cell.querySelector(':scope > .mobile-cell-value')) {
                const value = document.createElement('div');
                value.className = 'mobile-cell-value';
                value.append(...cell.childNodes);
                cell.append(value);
            }
            cell.classList.toggle('mobile-record-primary', index === primary);
            cell.classList.toggle('mobile-record-metric', index === metric && index !== primary);
            cell.dataset.mobileLabel = headers[index] || '';
        });
        const source = cells[primary].querySelector('.mobile-cell-value');
        const name = [...source.querySelectorAll('.js-name, .font-bold, .font-semibold, .font-black, .font-extrabold')]
            .find(element => !element.closest('.avatar'));
        const headingText = text(name || source);
        let heading = cells[primary].querySelector(':scope > .mobile-record-heading');
        if (!heading) {
            heading = document.createElement('div');
            heading.className = 'mobile-record-heading';
            cells[primary].append(heading);
        }
        if (heading.textContent !== headingText) heading.textContent = headingText;
        let meta = row.querySelector(':scope > .mobile-record-meta');
        if (!meta) {
            meta = document.createElement('td');
            meta.className = 'mobile-record-meta';
            meta.setAttribute('data-mobile-generated', '');
            row.append(meta);
        }
        const secondary = table.dataset.mobileSecondary;
        const metaText = secondary !== undefined ? text(cells[Number(secondary)]?.querySelector('.mobile-cell-value')) :
            text(source.querySelector('.js-id, .font-mono, .text-xs'));
        if (meta.textContent !== metaText) meta.textContent = metaText;
        if (!row.querySelector(':scope > .mobile-record-open')) {
            const action = document.createElement('td');
            action.className = 'mobile-record-open';
            action.setAttribute('data-mobile-generated', '');
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-ghost text-primary';
            button.textContent = '查看详情';
            action.append(button);
            row.append(action);
        }
        row.classList.add('mobile-record');
        if (compact.matches) {
            row.tabIndex = 0;
            row.setAttribute('role', 'listitem');
            row.setAttribute('aria-label', `${headingText}，查看记录详情`);
        } else {
            row.removeAttribute('tabindex');
            row.removeAttribute('role');
            row.removeAttribute('aria-label');
        }
    }
    function refresh() {
        main.querySelectorAll('table').forEach(table => {
            if (table.closest('#resume-preview, .mobile-record-dialog, .setup-description')) return;
            if (!tables.has(table)) {
                let wrapper = table.parentElement;
                if (!wrapper.classList.contains('overflow-x-auto')) {
                    wrapper = document.createElement('div');
                    table.before(wrapper);
                    wrapper.append(table);
                }
                wrapper.classList.add('table-scroll');
                table.classList.add('responsive-table');
                tables.add(table);
            }
            const headers = [...(table.tHead?.rows[0]?.cells || [])].map(text);
            table.setAttribute('role', compact.matches ? 'list' : 'table');
            if (table.tHead) table.tHead.setAttribute('aria-hidden', String(compact.matches));
            [...table.tBodies].forEach(body => {
                if (compact.matches) body.setAttribute('role', 'presentation');
                else body.removeAttribute('role');
                [...body.rows].forEach(row => adaptRow(table, row, headers));
            });
        });
        const preview = main.querySelector('.resume-preview-canvas > #resume-preview');
        if (preview && preview.parentElement.clientWidth) {
            const canvas = preview.parentElement;
            const style = getComputedStyle(canvas);
            const available = canvas.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
            const zoom = String(Math.min(1, available / preview.offsetWidth));
            if (preview.style.zoom !== zoom) preview.style.zoom = zoom;
        }
    }
    main.addEventListener('click', event => {
        if (!compact.matches) return;
        const row = event.target.closest('tr.mobile-record');
        if (!row || (event.target.closest('a, button, input, select, textarea') &&
            !event.target.closest('.mobile-record-open'))) return;
        openRecord(row, event.target.closest('button') || row);
    });
    main.addEventListener('keydown', event => {
        if (!compact.matches || !event.target.matches('tr.mobile-record') || !['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        openRecord(event.target, event.target);
    });
    new MutationObserver(scheduleRefresh).observe(main, {childList: true, subtree: true});
    main.querySelectorAll('.resume-preview-canvas').forEach(canvas => sizes.observe(canvas));
    compact.addEventListener('change', scheduleRefresh);
    window.addEventListener('resize', scheduleRefresh);
    refresh();
})();
