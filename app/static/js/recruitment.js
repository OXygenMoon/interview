'use strict';
document.querySelectorAll('[data-job-sync]').forEach((form) => {
    form.addEventListener('submit', () => {
        document.querySelectorAll('[data-job-sync] button').forEach((button) => { button.disabled = true; });
        form.querySelector('.jobs-sync-progress').hidden = false;
        form.setAttribute('aria-busy', 'true');
    });
});
// Back/forward navigation can restore a document with disabled refresh controls.
window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-job-sync]').forEach((form) => {
        form.querySelector('button').disabled = false;
        form.querySelector('.jobs-sync-progress').hidden = true;
        form.removeAttribute('aria-busy');
    });
});
