(() => {
    const pager = document.querySelector('[data-visual-pager]');
    if (!pager) return;

    const buttons = Array.from(pager.querySelectorAll('[data-visual-page]'));
    const panels = Array.from(pager.querySelectorAll('[data-visual-panel]'));
    const status = pager.querySelector('[data-visual-page-status]');

    function selectPage(index) {
        panels.forEach((panel, pageIndex) => {
            panel.hidden = pageIndex !== index;
        });
        buttons.forEach((button, pageIndex) => {
            if (pageIndex === index) button.setAttribute('aria-current', 'page');
            else button.removeAttribute('aria-current');
        });
        status.textContent = `第 ${index + 1} / ${panels.length} 条 · 时间戳 ${buttons[index].dataset.elapsed}`;
    }

    buttons.forEach((button, index) => {
        button.addEventListener('click', () => selectPage(index));
    });

    function showLinkedRecord(hash, scroll) {
        // Reveal a hidden record before the browser follows an answer's anchor.
        const index = panels.findIndex(panel => {
            const record = panel.querySelector('[data-testid="visual-record"]');
            return record && hash === `#${record.id}`;
        });
        if (index < 0) return;
        selectPage(index);
        if (scroll) panels[index].querySelector('[data-testid="visual-record"]').scrollIntoView({ block: 'start' });
    }

    document.querySelectorAll('a[href^="#visual-"]').forEach(link => {
        link.addEventListener('click', () => showLinkedRecord(link.hash, false));
    });
    window.addEventListener('hashchange', () => showLinkedRecord(window.location.hash, true));
    showLinkedRecord(window.location.hash, true);
})();
