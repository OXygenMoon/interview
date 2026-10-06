/* Preserve CSRF headers before page scripts make any requests. */
(() => {
    'use strict';
    const originalFetch = window.fetch.bind(window);
    window.fetch = (resource, options = {}) => {
        const request = resource instanceof Request ? resource : null;
        const url = new URL(request ? request.url : resource, location.href);
        const method = String(options.method || request?.method || 'GET').toUpperCase();
        if (url.origin === location.origin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            const headers = new Headers(options.headers || request?.headers || {});
            const token = document.querySelector('meta[name="csrf-token"]')?.content;
            if (token) headers.set('X-CSRF-Token', token);
            options = { ...options, headers };
        }
        return originalFetch(resource, options);
    };
})();
