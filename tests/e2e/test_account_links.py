"""Two real HTTP servers, real WikiBook users, and the actual Vue link panel.

Requires the sibling WikiBook checkout. All database writes use temporary files.
"""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import pytest
from flask import redirect, render_template_string, request, url_for
from flask_login import current_user, login_user
from werkzeug.serving import make_server

from app import create_app, db
from app.config import Config
from app.models import User

PEER_ROOT = Path(__file__).resolve().parents[3] / 'wikibook'
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not PEER_ROOT.exists(), reason='WikiBook checkout required')]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture
def linked_servers(tmp_path, monkeypatch):
    interview_port, wiki_port, vite_port = free_port(), free_port(), free_port()
    interview_url = f'http://127.0.0.1:{interview_port}'
    wiki_url = f'http://127.0.0.1:{wiki_port}'
    vite_url = f'http://127.0.0.1:{vite_port}'
    shared = dict(ACCOUNT_LINK_SECRET='isolated-browser-test-shared-secret-32-characters',
                  ACCOUNT_LINK_INTERVIEW_URL=interview_url, ACCOUNT_LINK_WIKIBOOK_URL=wiki_url,
                  SESSION_COOKIE_SECURE=False)
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "interview.db"}')
    monkeypatch.setattr(Config, 'APP_ENV', 'testing')
    monkeypatch.setattr(Config, 'SECRET_KEY', 'isolated-interview-browser-session-key')
    monkeypatch.setattr(Config, 'LLM_API_KEY', 'isolated-browser-llm-placeholder')
    interview = create_app()
    interview.config.update(shared, TESTING=False, SESSION_COOKIE_NAME='interview_session',
                            REMEMBER_COOKIE_NAME='interview_remember', REPORT_QUEUE_MODE='thread')
    with interview.app_context():
        from app.database_migrations import bootstrap_database
        bootstrap_database()
        user = User(username='interview-browser', role='student')
        user.set_password('browser-password')
        db.session.add(user); db.session.commit()

    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "wiki.db"}')
    sys.path.append(str(PEER_ROOT))
    from wikibook_app.factory import create_app as create_wiki
    from wikibook_app.extensions import db as wiki_db, login_manager
    from wikibook_app.models import User as WikiUser
    wiki = create_wiki()
    wiki.config.update(shared, TESTING=False, SESSION_COOKIE_NAME='wikibook_session',
                       REMEMBER_COOKIE_NAME='wikibook_remember')

    previous_loader = login_manager._user_callback

    @login_manager.user_loader
    def load(value):
        user = wiki_db.session.get(WikiUser, int(value.split(':')[0]))
        return user if user and user.get_id() == value else None

    with wiki.app_context():
        wiki_db.create_all()
        user = WikiUser(username='wiki-browser', email='browser@example.test')
        user.set_password('browser-password')
        wiki_db.session.add(user); wiki_db.session.commit()

    @wiki.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = WikiUser.query.filter_by(username=request.form['username']).first()
            assert user and user.check_password(request.form['password'])
            login_user(user)
            return redirect('/account-link/authorize' if request.args.get('next') else '/user/settings')
        return render_template_string('''<form method="post"><label>WikiBook 账号<input name="username"></label>
        <label>密码<input name="password" type="password"></label><button>登录 WikiBook</button></form>''')

    @wiki.get('/')
    def home():
        return redirect('/user/settings?view=connections')

    @wiki.get('/user/settings')
    def settings():
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return render_template_string('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><h1>WikiBook 账号设置</h1>
        <p id="signed-in-user">{{ username }}</p><main id="account-link"></main><script type="module">
        import { createApp } from '{{ vite }}/node_modules/.vite/deps/vue.js';
        import AccountLinkPanel from '{{ vite }}/src/components/users/AccountLinkPanel.vue';
        createApp(AccountLinkPanel).mount('#account-link');</script></html>''',
                                      username=current_user.username, vite=vite_url)

    log_file = (tmp_path / 'vite.log').open('w')
    env = dict(os.environ, VITE_BACKEND_ORIGIN=wiki_url)
    vite = subprocess.Popen(['npm', 'exec', 'vite', '--', '--host', '127.0.0.1', '--port', str(vite_port), '--strictPort'],
                            cwd=PEER_ROOT / 'frontend', env=env, stdout=log_file, stderr=subprocess.STDOUT)
    servers = [make_server('127.0.0.1', interview_port, interview, threaded=True),
               make_server('127.0.0.1', wiki_port, wiki, threaded=True)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads: thread.start()
    try:
        for _ in range(100):
            try:
                with urlopen(vite_url, timeout=1): break
            except OSError: time.sleep(.1)
        else: pytest.fail((tmp_path / 'vite.log').read_text())
        yield interview_url, wiki_url
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=5)
        vite.terminate(); vite.wait(timeout=10); log_file.close()
        login_manager.user_loader(previous_loader)
        with interview.app_context(): db.session.remove()
        with wiki.app_context(): wiki_db.session.remove()


@pytest.mark.parametrize('width', [1280, 390])
def test_frontend_link_switch_and_unlink(browser_instance, linked_servers, width):
    from playwright.sync_api import expect
    interview_url, wiki_url = linked_servers
    context = browser_instance.new_context(viewport={'width': width, 'height': 900})
    page = context.new_page()
    try:
        page.goto(interview_url + '/login')
        page.locator('[name=username]').fill('interview-browser')
        page.locator('[name=password]').fill('browser-password')
        page.locator('form button[type=submit]').click()
        page.goto(interview_url + '/account-links')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        avatar = page.locator('#app-account-toggle')
        avatar.click()
        expect(avatar).to_have_attribute('aria-expanded', 'true')
        menu = page.get_by_role('group', name='个人账号菜单', exact=True)
        expect(menu.get_by_role('link', name='账号关联设置', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        expect(avatar).to_be_focused()
        expect(avatar).to_have_attribute('aria-expanded', 'false')
        avatar.click()
        menu.get_by_role('button', name='关联 WikiBook 账号', exact=True).click()
        page.wait_for_url(wiki_url + '/login?next=/account-link/authorize')
        page.get_by_label('WikiBook 账号').fill('wiki-browser')
        page.get_by_label('密码', exact=True).fill('browser-password')
        page.get_by_role('button', name='登录 WikiBook').click()
        expect(page.get_by_text('interview-browser', exact=True)).to_be_visible()
        expect(page.get_by_text('wiki-browser', exact=True)).to_be_visible()
        page.get_by_role('button', name='确认关联这两个账号').click()
        expect(page.get_by_role('heading', name='账号已关联')).to_be_visible()
        page.get_by_role('link', name='返回账号设置').click()
        expect(page.get_by_role('button', name='切换 Interview', exact=True)).to_be_visible(timeout=15000)
        # One click must also work when the destination has no existing login.
        context.clear_cookies(name='interview_session')
        context.clear_cookies(name='interview_remember')
        page.get_by_role('button', name='切换 Interview', exact=True).click()
        page.wait_for_url(interview_url + '/')
        expect(page.locator('.app-account-name')).to_have_text('interview-browser')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.locator('#app-account-toggle').click()
        expect(page.get_by_role('group', name='个人账号菜单')).to_be_visible()
        page.screenshot(path=str(Path(__file__).resolve().parents[2] / f'test-results/account-links-interview-{width}.png'))
        context.clear_cookies(name='wikibook_session')
        context.clear_cookies(name='wikibook_remember')
        switch_button = page.get_by_role('button', name='切换 WikiBook', exact=True)
        expect(switch_button).to_be_visible()
        switch_button.click()
        page.wait_for_url(wiki_url + '/user/settings?view=connections')
        expect(page.locator('#signed-in-user')).to_have_text('wiki-browser')
        page.screenshot(path=str(Path(__file__).resolve().parents[2] / f'test-results/account-links-wikibook-{width}.png'))
        page.get_by_role('button', name='解除关联', exact=True).click()
        page.get_by_role('button', name='确认解除关联', exact=True).click()
        expect(page.get_by_text('账号关联已解除。', exact=True)).to_be_visible()
        page.goto(interview_url + '/account-links')
        expect(page.locator('[data-account-link-panel]').get_by_text('尚未关联 WikiBook 账号。', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='切换 WikiBook', exact=True)).to_have_count(0)
    except Exception:
        output = Path(__file__).resolve().parents[2] / f'test-results/account-links-failure-{width}.png'
        page.screenshot(path=str(output), full_page=True)
        raise
    finally:
        context.close()
