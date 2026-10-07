(() => {
    'use strict';
    const pool = document.querySelector('[data-testid="test-account-pool"]');
    if (!pool) return;
    const sync = pool.querySelector('[data-pool-sync]');
    let refreshing = false;
    async function refresh() {
        if (refreshing) return;
        refreshing = true;
        try {
            const response = await fetch(pool.dataset.statusUrl, { cache: 'no-store' });
            if (!response.ok) throw new Error('status');
            const data = await response.json();
            const states = new Map(data.accounts.map(account => [String(account.id), account]));
            pool.querySelectorAll('[data-account-id]').forEach(card => {
                const account = states.get(card.dataset.accountId);
                const button = card.querySelector('[data-login-button]');
                const state = card.querySelector('[data-state]');
                if (!account) {
                    state.textContent = '账号已移除，无法登录';
                    button.disabled = true;
                    return;
                }
                state.textContent = !account.active ? '已停用，无法登录' : account.busy ? '使用中，无法登录该账号' : '未登录，可以使用';
                state.dataset.busy = String(account.busy);
                button.textContent = account.owned ? '进入面试大厅 →' : !account.active ? '已停用' : account.busy ? '使用中' : '使用此账号 →';
                button.disabled = !account.owned && (!account.active || account.busy || data.signed_in);
                button.classList.toggle('btn-primary', !button.disabled);
                button.classList.toggle('btn-outline', button.disabled);
            });
            pool.querySelector('[data-pool-available]').textContent = data.accounts.filter(account => account.active && !account.busy).length;
            const sessionNote = pool.querySelector('[data-pool-session]');
            sessionNote.hidden = !data.signed_in;
            if (data.signed_in && !sessionNote.textContent.trim()) {
                sessionNote.textContent = '当前浏览器已有账号登录，切换账号前请先退出登录。';
            }
            sync.textContent = '账号状态已更新';
        } catch (_) {
            sync.textContent = '状态更新失败，暂时无法确认账号是否可用。请刷新页面重试。';
            pool.querySelectorAll('[data-login-button]').forEach(button => { button.disabled = true; });
        } finally {
            refreshing = false;
        }
    }
    pool.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', () => {
            const button = form.querySelector('button');
            button.disabled = true;
            button.textContent = '正在登录…';
        });
    });
    setInterval(refresh, 5000);
    window.addEventListener('pageshow', refresh);
})();
