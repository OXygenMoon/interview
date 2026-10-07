/* One document-level navbar; it never lives inside a scrolling page panel. */
(() => {
    'use strict';
    const button = document.getElementById('app-menu-toggle');
    const nav = document.getElementById('app-navigation');
    const header = document.querySelector('.app-navbar');
    const menus = [...document.querySelectorAll('.app-nav-more, .app-profile-menu')];
    const reveal = document.getElementById('app-nav-reveal');
    const passwordToggle = document.querySelector('[data-password-toggle]');
    passwordToggle?.addEventListener('click', () => {
        const input = document.getElementById(passwordToggle.getAttribute('aria-controls'));
        if (!input) return;
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        passwordToggle.textContent = show ? '隐藏' : '显示';
        passwordToggle.setAttribute('aria-pressed', String(show));
        passwordToggle.setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
    });
    const loginForm = document.querySelector('[data-testid="login-page"] form');
    loginForm?.addEventListener('submit', () => {
        const submit = loginForm.querySelector('[type="submit"]');
        loginForm.setAttribute('aria-busy', 'true');
        submit.disabled = true;
        submit.textContent = '正在登录…';
    });
    // Restore the native form when returning through the browser's page cache.
    window.addEventListener('pageshow', () => {
        if (!loginForm) return;
        const submit = loginForm.querySelector('[type="submit"]');
        loginForm.removeAttribute('aria-busy');
        submit.disabled = false;
        submit.textContent = '登录并继续 →';
    });
    function closeMenu(restoreFocus = false) {
        nav?.classList.remove('is-open');
        button?.setAttribute('aria-expanded', 'false');
        button?.setAttribute('aria-label', '打开导航菜单');
        if (restoreFocus) button?.focus();
    }
    button?.addEventListener('click', () => {
        const open = nav.classList.toggle('is-open');
        button.setAttribute('aria-expanded', String(open));
        button.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
    });
    document.addEventListener('click', event => {
        if (!header?.contains(event.target)) closeMenu();
        menus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
        if (event.target.closest('#app-navigation a')) closeMenu();
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const openMenu = menus.find(menu => menu.open);
        if (openMenu) { openMenu.open = false; openMenu.querySelector('summary').focus(); }
        else if (nav?.classList.contains('is-open')) closeMenu(true);
    });
    menus.forEach(menu => menu.addEventListener('toggle', () => {
        if (menu.open) menus.forEach(other => { if (other !== menu) other.open = false; });
        if (menu.classList.contains('app-profile-menu')) {
            menu.querySelector('summary').setAttribute('aria-expanded', String(menu.open));
            if (menu.open) closeMenu();
        }
    }));
    matchMedia('(min-width: 1280px)').addEventListener('change', event => {
        if (event.matches) closeMenu();
    });

    if (reveal && header) {
        let pointerInside = false;
        let hideTimer;
        const keyboardInside = () => reveal.matches(':focus-visible') || !!header.querySelector(':focus-visible');
        function showNavbar() {
            clearTimeout(hideTimer);
            hideTimer = undefined;
            header.classList.add('is-revealed');
            reveal.setAttribute('aria-expanded', 'true');
        }
        function hideNavbar() {
            if (hideTimer !== undefined) return;
            hideTimer = setTimeout(() => {
                hideTimer = undefined;
                if (pointerInside || keyboardInside()) return;
                closeMenu();
                menus.forEach(menu => { menu.open = false; });
                if (header.contains(document.activeElement)) document.activeElement.blur();
                header.classList.remove('is-revealed');
                reveal.setAttribute('aria-expanded', 'false');
            }, 180);
        }
        document.addEventListener('pointermove', event => {
            if (event.pointerType === 'touch') return;
            const bounds = header.getBoundingClientRect();
            const inTopGap = header.classList.contains('is-revealed') &&
                event.clientY <= bounds.top && event.clientX >= bounds.left && event.clientX <= bounds.right;
            pointerInside = event.clientY <= 20 || inTopGap || header.contains(event.target);
            if (pointerInside) showNavbar();
            else hideNavbar();
        });
        document.documentElement.addEventListener('pointerleave', () => {
            pointerInside = false;
            hideNavbar();
        });
        reveal.addEventListener('click', showNavbar);
        reveal.addEventListener('focus', showNavbar);
        header.addEventListener('focusin', showNavbar);
        [reveal, header].forEach(element => element.addEventListener('focusout', () => {
            queueMicrotask(hideNavbar);
        }));
        document.addEventListener('click', event => {
            if (header.contains(event.target) || reveal.contains(event.target)) return;
            pointerInside = false;
            hideNavbar();
        });
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || !header.classList.contains('is-revealed')) return;
            // Closing a submenu first preserves the existing keyboard navigation.
            if (header.querySelector(':focus-visible')) return;
            pointerInside = false;
            if (document.activeElement === reveal) document.getElementById('main-content')?.focus();
            hideNavbar();
        });
    }
})();
