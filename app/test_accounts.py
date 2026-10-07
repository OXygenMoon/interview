"""Public, password-free access to designated demo students only."""
from flask import Blueprint, jsonify, redirect, render_template, session, url_for
from flask_login import current_user, login_user

from . import db
from .models import TestAccount
from .services.test_accounts import LEASE_SESSION_KEY, TEST_CLASS, TEST_DEPARTMENT, utcnow


test_accounts_bp = Blueprint('test_accounts', __name__)


@test_accounts_bp.errorhandler(409)
def account_busy(error):
    return render_template('test_accounts.html', accounts=account_states(),
                           test_class=TEST_CLASS, test_department=TEST_DEPARTMENT,
                           pool_error=error.description), 409


def account_states():
    now = utcnow()
    states = []
    for account in TestAccount.query.order_by(TestAccount.user_id).all():
        user = account.user
        busy = bool(account.lease_token and account.lease_expires_at and account.lease_expires_at > now)
        owned = bool(current_user.is_authenticated and current_user.id == user.id
                     and session.get(LEASE_SESSION_KEY) == account.lease_token and busy)
        states.append({
            'id': user.id, 'username': user.username, 'name': user.truename,
            'busy': busy, 'owned': owned, 'active': user.active and not user.must_change_password,
        })
    return states


@test_accounts_bp.after_request
def prevent_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@test_accounts_bp.get('/test-accounts')
def index():
    return render_template('test_accounts.html', accounts=account_states(),
                           test_class=TEST_CLASS, test_department=TEST_DEPARTMENT)


@test_accounts_bp.get('/api/test-accounts')
def status():
    return jsonify(accounts=account_states(), signed_in=current_user.is_authenticated)


@test_accounts_bp.post('/test-accounts/<int:user_id>/login')
def login(user_id):
    account = db.get_or_404(TestAccount, user_id)
    if current_user.is_authenticated:
        if current_user.id == user_id:
            return redirect(url_for('routes.home'))
        return render_template('test_accounts.html', accounts=account_states(),
                               test_class=TEST_CLASS, test_department=TEST_DEPARTMENT,
                               pool_error='请先退出当前账号，再选择测试账号。'), 409
    if not account.user.active or account.user.must_change_password:
        return render_template('test_accounts.html', accounts=account_states(),
                               test_class=TEST_CLASS, test_department=TEST_DEPARTMENT,
                               pool_error='该测试账号已停用或需要管理员处理，请选择其他账号。'), 403
    login_user(account.user, remember=False)
    return redirect(url_for('routes.home'))


@test_accounts_bp.post('/api/test-accounts/heartbeat')
def heartbeat():
    if not current_user.is_authenticated or current_user.test_account is None:
        return jsonify(error='测试账号登录已失效，请重新选择账号。'), 401
    return jsonify(ok=True)
