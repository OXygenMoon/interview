"""Browser flow shared with WikiBook; keep both deployed copies identical.

Only configured origins receive redirects. Browser mutations use local CSRF;
server calls use a separate shared credential and never forward cookies.
"""
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode, urlsplit

import requests
from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, session)
from flask_login import current_user, login_user, logout_user


class LinkError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def origin(config_key):
    value = str(current_app.config.get(config_key) or '').rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'https', 'http'} or not parsed.netloc
            or parsed.path or parsed.query or parsed.fragment or parsed.username
            or parsed.password):
        raise LinkError('账号关联服务地址尚未正确配置。', 503)
    allowed_interview_http = (config_key == 'ACCOUNT_LINK_INTERVIEW_URL'
                             and value == 'http://211.154.20.65:20018')
    if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'} and not allowed_interview_http:
        raise LinkError('账号关联服务必须使用 HTTPS。', 503)
    return value


def enabled():
    try:
        origin('ACCOUNT_LINK_INTERVIEW_URL')
        origin('ACCOUNT_LINK_WIKIBOOK_URL')
        return len(str(current_app.config.get('ACCOUNT_LINK_SECRET') or '')) >= 32
    except LinkError:
        return False


def server_call(site, path, payload, timeout=(3, 8)):
    if not enabled():
        raise LinkError('账号关联服务尚未配置，请联系管理员。', 503)
    try:
        response = requests.post(
            origin('ACCOUNT_LINK_' + site.upper() + '_URL') + path,
            json=payload,
            headers={'Authorization': 'Bearer ' + current_app.config['ACCOUNT_LINK_SECRET']},
            timeout=timeout, allow_redirects=False,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        raise LinkError('另一平台暂时无法连接，请稍后重试。', 503) from None
    if not isinstance(data, dict) or not response.ok or data.get('ok') is not True or 'data' not in data:
        error = data.get('error') if isinstance(data, dict) else None
        message = error.get('message') if isinstance(error, dict) else None
        raise LinkError(message or '另一平台暂时无法连接，请稍后重试。',
                        response.status_code if response.status_code >= 400 else 503)
    return data['data']


def verify_server():
    expected = str(current_app.config.get('ACCOUNT_LINK_SECRET') or '')
    supplied = request.headers.get('Authorization', '')
    if not enabled() or not hmac.compare_digest(supplied.encode(), ('Bearer ' + expected).encode()):
        raise LinkError('服务认证失败。', 401)


def user_identity(user):
    if (user is None or not user.is_active
            or getattr(user, 'must_change_password', False)):
        raise LinkError('账号不可用，请先完成密码更新或联系管理员。', 403)
    version = hashlib.sha256(
        (str(user.password_hash) + ':' + str(getattr(user, 'session_version', 0))).encode()
    ).hexdigest()
    return {'id': user.id, 'username': user.username, 'version': version}


def init_account_link(app, site, get_user, home_url, login_url, authority=None, manage_url=None):
    peer = 'wikibook' if site == 'interview' else 'interview'
    bp = Blueprint('account_link', __name__)
    manage_url = manage_url or home_url

    def call(action, **data):
        if not enabled():
            raise LinkError('账号关联服务尚未配置，请联系管理员。', 503)
        if authority:
            return authority(action, site, data)
        if data.get('user_id') is not None:
            # Assert only the locally authenticated actor, never a browser-supplied ID.
            data['actor_identity'] = user_identity(current_user)
        return server_call('interview', '/internal/account-link', {'action': action, **data})

    def actor():
        if not current_user.is_authenticated:
            raise LinkError('请先登录后关联账号。', 401)
        return user_identity(current_user)['id']

    def csrf():
        if '_account_link_csrf' not in session:
            session['_account_link_csrf'] = secrets.token_urlsafe(32)
        return session['_account_link_csrf']

    def peer_url(path, **params):
        return origin('ACCOUNT_LINK_' + peer.upper() + '_URL') + path + '?' + urlencode(params)

    @bp.before_request
    def protect():
        if request.endpoint in {'account_link.internal', 'account_link.internal_user', 'account_link.reward_scan'}:
            verify_server()
        elif request.method in {'POST', 'DELETE'}:
            supplied = request.headers.get('X-Account-Link-CSRF') or request.form.get('link_csrf', '')
            if not hmac.compare_digest(csrf().encode(), str(supplied).encode()):
                raise LinkError('页面已过期，请刷新后重试。', 400)

    @bp.after_request
    def private(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @bp.errorhandler(LinkError)
    def error(exc):
        if request.endpoint in {'account_link.authorize', 'account_link.confirm'} and exc.status != 401:
            session.pop('account_link_pending', None)
        if request.path.startswith(('/api/', '/internal/')):
            return jsonify(ok=False, error={'code': 'account_link_error', 'message': str(exc)}), exc.status
        return render_template('account_link_flow.html', error=str(exc), peer=peer,
                               home=manage_url(), csrf=csrf()), exc.status

    @bp.get('/api/account-link')
    def status():
        user_id = actor()
        data = {'enabled': enabled(), 'linked': False, 'peer': peer, 'csrfToken': csrf()}
        if data['enabled']:
            data.update(call('status', user_id=user_id))
        return jsonify(ok=True, data=data)

    @bp.post('/api/account-link/start')
    def start():
        data = call('link_start', user_id=actor())
        return jsonify(ok=True, data={'url': peer_url('/account-link/authorize', code=data['code'])})

    @bp.delete('/api/account-link')
    def unlink():
        call('unlink', user_id=actor())
        return jsonify(ok=True, data={'message': '账号关联已解除。'})

    @bp.get('/account-link/authorize')
    def authorize():
        code = request.args.get('code') or session.get('account_link_pending')
        if not isinstance(code, str) or len(code) > 100:
            raise LinkError('关联请求无效，请重新发起。')
        session['account_link_pending'] = code
        if not current_user.is_authenticated:
            return redirect(login_url())
        data = call('link_inspect', code=code, user_id=actor())
        return render_template('account_link_flow.html', source=data['username'],
                               local=current_user.username, peer=peer,
                               home=manage_url(), csrf=csrf())

    @bp.post('/account-link/authorize')
    def confirm():
        user_id = actor()
        code = session.get('account_link_pending')
        if not code:
            raise LinkError('关联请求已过期，请重新发起。')
        call('link_confirm', code=code, user_id=user_id)
        session.pop('account_link_pending', None)
        return render_template('account_link_flow.html', success=True, peer=peer,
                               home=manage_url(), csrf=csrf())

    @bp.post('/account-link/cancel')
    def cancel():
        session.pop('account_link_pending', None)
        return redirect(manage_url())

    @bp.post('/api/account-link/switch')
    def switch():
        user_id = actor()
        if not call('status', user_id=user_id)['linked']:
            raise LinkError('请先关联另一平台账号。', 409)
        nonce = secrets.token_urlsafe(32)
        session['account_link_switch'] = {'nonce': nonce, 'user_id': user_id, 'expires': time.time() + 120}
        return jsonify(ok=True, data={'url': peer_url('/account-link/prepare', nonce=nonce)})

    @bp.get('/account-link/prepare')
    def prepare():
        if not enabled():
            raise LinkError('账号关联服务尚未配置。', 503)
        nonce = request.args.get('nonce', '')
        if not 30 <= len(nonce) <= 100:
            raise LinkError('切换请求无效，请重新发起。')
        state = secrets.token_urlsafe(32)
        session['account_link_target'] = {'state': state, 'expires': time.time() + 120}
        return redirect(peer_url('/account-link/continue', nonce=nonce, state=state))

    @bp.get('/account-link/continue')
    def continue_switch():
        user_id = actor()
        pending = session.get('account_link_switch') or {}
        nonce, state = request.args.get('nonce', ''), request.args.get('state', '')
        if (pending.get('user_id') != user_id or pending.get('expires', 0) < time.time()
                or not hmac.compare_digest(str(pending.get('nonce', '')).encode(), nonce.encode())
                or not 30 <= len(state) <= 100):
            raise LinkError('切换请求已过期或来自其他浏览器，请重新发起。')
        session.pop('account_link_switch', None)
        result = call('login_issue', user_id=user_id, state=state)
        return redirect(peer_url('/account-link/callback', code=result['code'], state=state))

    @bp.get('/account-link/callback')
    def callback():
        pending = session.get('account_link_target') or {}
        state = request.args.get('state', '')
        if (not state or pending.get('expires', 0) < time.time()
                or not hmac.compare_digest(str(pending.get('state', '')).encode(), state.encode())):
            raise LinkError('切换请求已过期或来自其他浏览器，请重新发起。')
        session.pop('account_link_target', None)
        data = call('login_redeem', code=request.args.get('code', ''), state=state)
        user = get_user(data['user_id'])
        target = user_identity(user)
        if target['version'] != data['version']:
            raise LinkError('账号凭证已更新，请重新发起。', 403)
        logout_user()  # also revoke an existing remember cookie for a different account
        session.clear()
        session['_remember'] = 'clear'
        login_user(user, remember=False, fresh=True)
        return redirect(home_url())

    @bp.post('/internal/account-link/user')
    def internal_user():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or isinstance(data.get('user_id'), bool) or not isinstance(data.get('user_id'), int) or data['user_id'] <= 0:
            raise LinkError('账号标识无效。')
        return jsonify(ok=True, data=user_identity(get_user(data['user_id'])))

    if authority:
        @bp.post('/internal/account-link')
        def internal():
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise LinkError('请求格式无效。')
            return jsonify(ok=True, data=authority(data.get('action'), peer, data))

    if site == 'wikibook':
        @bp.post('/internal/account-link/reward-scan')
        def reward_scan():
            data = request.get_json(silent=True)
            if (not isinstance(data, dict) or type(data.get('user_id')) is not int
                    or data['user_id'] <= 0):
                raise LinkError('账号标识无效。')
            from wikibook_app.services.interview_badges import accept_reward_scan
            return jsonify(ok=True, data=accept_reward_scan(data['user_id']))

    app.register_blueprint(bp)
