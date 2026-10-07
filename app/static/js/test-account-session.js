(() => {
    'use strict';
    const lease = document.querySelector('[data-test-account-heartbeat]');
    if (!lease) return;
    let pending = false;
    async function heartbeat() {
        if (pending) return;
        pending = true;
        try {
            const response = await fetch(lease.dataset.testAccountHeartbeat, { method: 'POST', cache: 'no-store' });
            if (response.status === 401) location.replace(lease.dataset.testAccountPool);
        } catch (_) {
            // Network outages recover on the next request; expired cookies cannot reclaim a lease.
        } finally {
            pending = false;
        }
    }
    setInterval(heartbeat, 30000);
    window.addEventListener('pageshow', heartbeat);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) heartbeat(); });
})();
