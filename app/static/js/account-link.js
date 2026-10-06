(() => {
    'use strict';
    const panel = document.querySelector('[data-account-link-panel]');
    const switchButtons = [...document.querySelectorAll('[data-account-switch]')];
    if (!panel && !switchButtons.length) return;
    let token = '', busy = false;
    const statuses = [...document.querySelectorAll('[data-link-status]')];
    const startButtons = [...document.querySelectorAll('[data-link-start]')];
    const unlink = panel?.querySelector('[data-link-unlink]');
    const retry = panel?.querySelector('[data-link-retry]');
    const confirmation = panel?.querySelector('[data-link-unlink-confirm]');
    async function request(path = '', method = 'GET') {
        const response = await fetch('/api/account-link' + path, {
            method, headers: { 'Accept': 'application/json', 'X-Account-Link-CSRF': token },
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error?.message || '账号关联服务暂时不可用。');
        return data.data;
    }
    function message(text, failed = false) {
        statuses.forEach(status => { status.textContent = text; status.setAttribute('role', failed ? 'alert' : 'status'); });
        if (!statuses.length && failed) window.alert(text);
    }
    async function load() {
        try {
            const data = await request(); token = data.csrfToken;
            message(!data.enabled ? '账号关联服务尚未配置，请联系管理员。' : data.linked ? `已关联 WikiBook 账号：${data.username}` : '尚未关联 WikiBook 账号。');
            startButtons.forEach(button => { button.hidden = data.linked; button.disabled = !data.enabled; });
            if (unlink) unlink.hidden = !data.linked;
            switchButtons.forEach(button => { button.hidden = !data.linked; });
            if (retry) retry.hidden = true;
        } catch (error) { message(error.message, Boolean(panel)); if (retry) retry.hidden = false; }
    }
    async function act(path, method = 'POST') {
        if (busy) return;
        busy = true;
        const buttons = [...new Set([...(panel?.querySelectorAll('button') || []), ...startButtons, ...switchButtons])];
        const previous = buttons.map(button => button.disabled);
        buttons.forEach(button => { button.disabled = true; });
        try {
            const data = await request(path, method);
            if (data.url) window.location.assign(data.url);
            else { if (confirmation) confirmation.hidden = true; await load(); message(data.message); }
        } catch (error) { message(error.message, true); }
        finally { busy = false; buttons.forEach((button, index) => { button.disabled = previous[index]; }); }
    }
    startButtons.forEach(button => button.addEventListener('click', () => act('/start')));
    switchButtons.forEach(button => button.addEventListener('click', () => act('/switch')));
    unlink?.addEventListener('click', () => { confirmation.hidden = false; });
    panel?.querySelector('[data-link-unlink-yes]')?.addEventListener('click', () => act('', 'DELETE'));
    panel?.querySelector('[data-link-unlink-no]')?.addEventListener('click', () => { confirmation.hidden = true; });
    retry?.addEventListener('click', load);
    load();
})();
