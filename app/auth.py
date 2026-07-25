from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from .models import User
from . import db

auth_bp = Blueprint('auth', __name__)


def _redirect_for_role(user):
    if user.must_change_password:
        return redirect(url_for('auth.change_password'))
    if user.role == 'student':
        return redirect(url_for('routes.home'))
    return redirect(url_for('routes.dashboard'))


@auth_bp.before_app_request
def require_password_change():
    """Imported/reset accounts may only visit the password-change flow."""
    if not current_user.is_authenticated:
        return None
    if not current_user.active:
        logout_user()
        flash('该账号已停用，请联系管理员。', 'error')
        return redirect(url_for('auth.login'))
    if not current_user.must_change_password:
        return None
    allowed_endpoints = {'auth.change_password', 'auth.logout', 'static'}
    if request.endpoint not in allowed_endpoints:
        return redirect(url_for('auth.change_password'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.active:
                flash('该账号已停用，请联系管理员。', 'error')
                return render_template('login.html')
            login_user(user)
            return _redirect_for_role(user)
        else:
            flash('账号或密码错误')

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # 注册接口已关闭：账号统一由管理员通过 Excel 导入或后台创建。
    # 如需恢复自助注册，把下方两行替换回原逻辑即可。
    flash('注册已关闭，请联系管理员开通账号。')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('当前密码不正确。', 'error')
        elif len(new_password) < 10:
            flash('新密码至少需要 10 个字符。', 'error')
        elif new_password != confirm_password:
            flash('两次输入的新密码不一致。', 'error')
        elif new_password == current_password:
            flash('新密码不能与当前密码相同。', 'error')
        else:
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.commit()
            flash('密码已更新。', 'success')
            return _redirect_for_role(current_user)

    return render_template('change_password.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
