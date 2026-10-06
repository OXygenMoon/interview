"""Contract tests run both deployed browser flows with isolated identities/DBs."""
import importlib.util
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from werkzeug.security import generate_password_hash

os.environ.setdefault('LLM_API_KEY', 'account-link-test-placeholder')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'account-link-test-session-secret')
from app import create_app, db
from app.config import Config
from app.models import AccountLink, AccountLinkTicket, User
from app.integrations.account_link import init_account_link

PEER_ROOT = Path(__file__).resolve().parents[2] / 'wikibook'


class PeerUser(UserMixin):
    def __init__(self, user_id, name):
        self.id, self.username = user_id, name
        self.password_hash = generate_password_hash('peer-password')
        self.session_version = 0

    def get_id(self):
        return f'{self.id}:{self.session_version}'


@pytest.fixture
def pair(monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False,
                      ACCOUNT_LINK_SECRET='contract-test-only-secret-32-characters',
                      ACCOUNT_LINK_INTERVIEW_URL='http://127.0.0.1:5101',
                      ACCOUNT_LINK_WIKIBOOK_URL='http://127.0.0.1:5102')
    with app.app_context():
        db.create_all()
        for user_id, name in [(1, 'interview-one'), (2, 'interview-two')]:
            user = User(id=user_id, username=name, role='student')
            user.set_password('local-password')
            db.session.add(user)
        db.session.commit()
    wiki = Flask('account-link-peer', template_folder=str(PEER_ROOT / 'templates'))
    wiki.config.update(app.config)
    wiki.secret_key = 'peer-test-session-secret'
    users = {10: PeerUser(10, 'wiki-ten'), 20: PeerUser(20, 'wiki-twenty')}
    manager = LoginManager(wiki)
    manager.user_loader(lambda user_id: users.get(int(user_id.split(':')[0])))
    # Prefer the actual deployed WikiBook copy, so protocol drift breaks CI here.
    protocol = PEER_ROOT / 'wikibook_app/integrations/account_link.py'
    if protocol.exists():
        spec = importlib.util.spec_from_file_location('wikibook_link_contract', protocol)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        init = module.init_account_link
    else:
        wiki.template_folder = str(Path(app.root_path) / 'templates')
        init = init_account_link
    init(wiki, 'wikibook', users.get, lambda: '/user/settings?view=connections',
         lambda: '/login?next=/account-link/authorize')
    clients = {'interview': app.test_client(), 'wikibook': wiki.test_client()}
    apps = {'interview': app, 'wikibook': wiki}

    def post(url, json, headers, **kwargs):
        site = 'interview' if urlsplit(url).port == 5101 else 'wikibook'
        # Machine requests must have no browser session/cookies attached.
        response = apps[site].test_client().post(urlsplit(url).path, json=json, headers=headers)
        return SimpleNamespace(ok=response.status_code < 400, status_code=response.status_code,
                               json=response.get_json)

    with patch('requests.post', side_effect=post):
        yield SimpleNamespace(app=app, wiki=wiki, clients=clients, users=users)
    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(pair, site, user_id):
    with pair.clients[site].session_transaction() as session:
        session['_user_id'] = str(user_id) if site == 'interview' else pair.users[user_id].get_id()
        session['_fresh'] = True


def request(pair, site, path='', method='GET'):
    client = pair.clients[site]
    status = client.get('/api/account-link')
    assert status.status_code == 200, status.data
    return client.open('/api/account-link' + path, method=method,
                       headers={'X-Account-Link-CSRF': status.json['data']['csrfToken']})


def link(pair, source='interview', source_id=1, target_id=10):
    target = 'wikibook' if source == 'interview' else 'interview'
    login(pair, source, source_id)
    login(pair, target, target_id)
    started = request(pair, source, '/start', 'POST')
    assert started.status_code == 200, started.data
    url = started.json['data']['url']
    parsed = urlsplit(url)
    page = pair.clients[target].get(parsed.path + '?' + parsed.query)
    assert page.status_code == 200, page.data
    status = pair.clients[target].get('/api/account-link').json['data']
    result = pair.clients[target].post('/account-link/authorize', data={'link_csrf': status['csrfToken']})
    assert result.status_code == 200, result.data
    return parse_qs(parsed.query)['code'][0]


def switch(pair, source):
    target = 'wikibook' if source == 'interview' else 'interview'
    result = request(pair, source, '/switch', 'POST')
    assert result.status_code == 200, result.data
    url = result.json['data']['url']
    for site in (target, source, target):
        parsed = urlsplit(url)
        response = pair.clients[site].get(parsed.path + '?' + parsed.query)
        assert response.status_code == 302, response.data
        url = response.location
    return response


@pytest.mark.parametrize('source,source_id,target_id', [('interview', 1, 10), ('wikibook', 10, 1)])
def test_link_and_switch_both_directions(pair, source, source_id, target_id):
    link(pair, source, source_id, target_id)
    assert request(pair, 'interview').json['data']['username'] == 'wiki-ten'
    assert request(pair, 'wikibook').json['data']['username'] == 'interview-one'
    # Destination may currently be logged into a different account.
    login(pair, 'wikibook', 20)
    cookie_name = pair.wiki.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    pair.clients['wikibook'].set_cookie(cookie_name, 'old-remember-cookie')
    switched = switch(pair, 'interview')
    assert any(header.startswith(cookie_name + '=;') for header in switched.headers.getlist('Set-Cookie'))
    with pair.clients['wikibook'].session_transaction() as session:
        assert session['_user_id'] == '10:0'
        assert session['_fresh']
    login(pair, 'interview', 2)
    switch(pair, 'wikibook')
    with pair.clients['interview'].session_transaction() as session:
        assert session['_user_id'] == '1'
    assert request(pair, 'wikibook', method='DELETE').status_code == 200
    assert not request(pair, 'interview').json['data']['linked']
    assert request(pair, 'interview', '/switch', 'POST').status_code == 409


def test_authentication_csrf_and_internal_secret(pair):
    assert pair.clients['interview'].get('/api/account-link').status_code == 401
    login(pair, 'interview', 1)
    assert pair.clients['interview'].post('/api/account-link/start').status_code == 400
    assert pair.clients['interview'].post('/internal/account-link', json={'action': 'status', 'user_id': 1}).status_code == 401
    assert pair.clients['wikibook'].post('/internal/account-link/user', json={'user_id': 10}).status_code == 401
    response = request(pair, 'interview')
    assert response.headers['Cache-Control'] == 'no-store'


def test_link_conflict_and_replay(pair):
    code = link(pair)
    client = pair.clients['wikibook']
    assert client.get('/account-link/authorize?code=' + code).status_code == 400
    login(pair, 'interview', 2)
    started = request(pair, 'interview', '/start', 'POST').json['data']['url']
    parsed = urlsplit(started)
    assert client.get(parsed.path + '?' + parsed.query).status_code == 200
    token = request(pair, 'wikibook').json['data']['csrfToken']
    assert client.post('/account-link/authorize', data={'link_csrf': token}).status_code == 409
    with pair.app.app_context():
        assert AccountLink.query.count() == 1


def issue_login(pair):
    link(pair)
    state = secrets.token_urlsafe(32)
    with pair.app.app_context():
        from app.integrations.account_link_authority import operate
        code = operate('login_issue', 'interview', {'user_id': 1, 'state': state})['code']
    return code, state


def redeem(pair, code, state):
    from app.integrations.account_link_authority import operate
    with pair.app.app_context():
        result = operate('login_redeem', 'wikibook', {'code': code, 'state': state})
        from app.integrations.account_link import LinkError, user_identity
        if user_identity(pair.users[result['user_id']])['version'] != result['version']:
            raise LinkError('账号凭证已更新，请重新发起。', 403)
        return result


def test_login_ticket_once_and_browser_binding(pair):
    from app.integrations.account_link import LinkError
    code, state = issue_login(pair)
    victim = pair.wiki.test_client()
    assert victim.get('/account-link/callback', query_string={'code': code, 'state': state}).status_code == 400
    with pytest.raises(LinkError, match='不匹配'):
        redeem(pair, code, secrets.token_urlsafe(32))
    assert redeem(pair, code, state)['user_id'] == 10
    with pytest.raises(LinkError, match='已使用'):
        redeem(pair, code, state)


@pytest.mark.parametrize('change', ['unlink', 'expired', 'source_password', 'target_password', 'disabled', 'must_change', 'wiki_session'])
def test_issued_ticket_invalidated(pair, change):
    from app.integrations.account_link import LinkError
    code, state = issue_login(pair)
    if change == 'unlink':
        request(pair, 'interview', method='DELETE')
    elif change in {'target_password', 'wiki_session'}:
        if change == 'target_password':
            pair.users[10].password_hash = generate_password_hash('new-password')
        else:
            pair.users[10].session_version += 1
    else:
        with pair.app.app_context():
            if change == 'expired':
                AccountLinkTicket.query.filter_by(purpose='login').first().expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            else:
                user = db.session.get(User, 1)
                if change == 'source_password': user.set_password('new-password')
                elif change == 'disabled': user.active = False
                else: user.must_change_password = True
            db.session.commit()
    with pytest.raises(LinkError):
        redeem(pair, code, state)


def test_unlogged_target_resumes_after_local_login(pair):
    login(pair, 'interview', 1)
    started = request(pair, 'interview', '/start', 'POST').json['data']['url']
    parsed = urlsplit(started)
    client = pair.clients['wikibook']
    assert client.get(parsed.path + '?' + parsed.query).location == '/login?next=/account-link/authorize'
    login(pair, 'wikibook', 10)
    response = client.get('/account-link/authorize')
    assert response.status_code == 200
    assert b'interview-one' in response.data and b'wiki-ten' in response.data


def test_continue_requires_issuing_browser_and_account(pair):
    link(pair)
    prepare_url = request(pair, 'interview', '/switch', 'POST').json['data']['url']
    parsed = urlsplit(prepare_url)
    continued = pair.clients['wikibook'].get(parsed.path + '?' + parsed.query).location
    parsed = urlsplit(continued)
    other = pair.app.test_client()
    with other.session_transaction() as session:
        session['_user_id'] = '1'
    assert other.get(parsed.path + '?' + parsed.query).status_code == 400
    login(pair, 'interview', 2)
    assert pair.clients['interview'].get(parsed.path + '?' + parsed.query).status_code == 400


def test_disabled_and_unavailable_fail_closed(pair):
    login(pair, 'interview', 1)
    pair.app.config['ACCOUNT_LINK_SECRET'] = ''
    assert not request(pair, 'interview').json['data']['enabled']
    assert request(pair, 'interview', '/start', 'POST').status_code == 503
    pair.app.config['ACCOUNT_LINK_SECRET'] = 'contract-test-only-secret-32-characters'
    login(pair, 'wikibook', 10)
    import requests
    with patch('requests.post', side_effect=requests.ConnectionError):
        assert pair.clients['wikibook'].get('/api/account-link').status_code == 503


def test_peer_protocol_and_templates_remain_identical():
    if not (PEER_ROOT / 'wikibook_app/integrations/account_link.py').exists():
        pytest.skip('WikiBook checkout is not available')
    root = Path(__file__).resolve().parents[1]
    assert (root / 'app/integrations/account_link.py').read_bytes() == (PEER_ROOT / 'wikibook_app/integrations/account_link.py').read_bytes()
    assert (root / 'app/templates/account_link_flow.html').read_bytes() == (PEER_ROOT / 'templates/account_link_flow.html').read_bytes()
