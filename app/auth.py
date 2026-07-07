from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from .models import User
from . import db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # 如果已经登录，根据角色智能跳转
        if current_user.role == 'student':
            return redirect(url_for('routes.home'))
        else:
            return redirect(url_for('routes.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            # 登录后跳转首页
            # === 核心修改：登录成功后的分流逻辑 ===
            if user.role == 'student':
                # 学生 -> 去面试大厅
                return redirect(url_for('routes.home'))
            else:
                # 老师/领导 -> 去管理后台
                return redirect(url_for('routes.dashboard'))
        else:
            flash('账号或密码错误')

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # 注册接口已关闭：账号统一由管理员通过 Excel 导入或后台创建。
    # 如需恢复自助注册，把下方两行替换回原逻辑即可。
    flash('注册已关闭，请联系管理员开通账号。')
    return redirect(url_for('auth.login'))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))