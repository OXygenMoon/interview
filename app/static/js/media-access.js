/* Browser exceptions are configured by the user; the page cannot install them. */
window.InterviewMediaAccess = (() => {
    const message = '当前为 HTTP 访问，浏览器默认禁止使用麦克风和摄像头。请使用 HTTPS 地址，或查看本站的浏览器设置说明；现在可输入文字继续面试。';
    const dialog = document.getElementById('mic_permission_modal');
    const origin = document.getElementById('current-origin');
    const flags = document.getElementById('media-flags-address');
    const copyStatus = document.getElementById('media-copy-status');
    if (origin) origin.value = location.origin;

    const ua = navigator.userAgent;
    const ios = /iPad|iPhone|iPod/.test(ua)
        || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    const android = /Android/.test(ua);
    const embedded = /MicroMessenger|wxwork|FBAN|FBAV|; wv\)/i.test(ua);
    const edge = /Edg\//.test(ua) && !android && !ios;
    const chrome = /Chrome\//.test(ua) && !/Edg|OPR\/|SamsungBrowser\//.test(ua);
    const supportsFlags = !ios && !embedded && (edge || chrome);
    if (dialog) {
        document.getElementById('media-flags-guide').hidden = !supportsFlags;
        document.getElementById('media-https-guide').hidden = supportsFlags;
        if (supportsFlags) {
            flags.value = `${edge ? 'edge' : 'chrome'}://flags/#unsafely-treat-insecure-origin-as-secure`;
            document.getElementById('media-browser-guide').textContent = android
                ? 'Android Chrome：可尝试以下临时设置，是否可用取决于浏览器版本。'
                : `${edge ? 'Edge' : 'Chrome'}：可为本站单独设置 HTTP 测试例外。`;
        } else {
            document.getElementById('media-https-guide').textContent = ios
                ? 'iPhone / iPad 无法照搬桌面 Chrome / Edge 的例外设置。请使用带有效证书的 HTTPS 地址，并允许麦克风与摄像头；从微信等应用打开时，可选择“在浏览器中打开”。'
                : '当前浏览器没有可由本站添加的 HTTP 例外设置。请使用 HTTPS 地址并允许麦克风与摄像头；Android 用户也可在 Chrome 中查看是否提供测试例外选项。';
        }
    }

    function showHelp() {
        if (dialog && !dialog.open) dialog.showModal();
    }

    async function copyAddress(field) {
        // HTTP pages usually have no Clipboard API. A visible input also lets
        // users long-press to copy when both programmatic methods are blocked.
        let copied = false;
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(field.value);
                copied = true;
            } catch (_) { /* Fall through to the HTTP-compatible method. */ }
        }
        if (!copied) {
            field.focus();
            field.select();
            field.setSelectionRange(0, field.value.length);
            try { copied = document.execCommand('copy'); } catch (_) { /* Manual copy. */ }
        }
        copyStatus.textContent = copied
            ? '已复制。请粘贴到浏览器设置中；复制不会自动添加策略。'
            : '无法自动复制，地址已选中，请长按或按 Ctrl+C / ⌘C 复制。';
    }

    document.getElementById('media-access-help')?.addEventListener('click', showHelp);
    document.getElementById('copy-media-origin')?.addEventListener('click', () => copyAddress(origin));
    document.getElementById('copy-media-flags')?.addEventListener('click', () => copyAddress(flags));
    const notice = document.getElementById('media-access-notice');
    if (notice && !window.isSecureContext) {
        notice.hidden = false;
        document.getElementById('voice-environment-status').textContent = message;
    }
    return {message, showHelp};
})();
