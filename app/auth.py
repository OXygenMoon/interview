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
    if current_user.is_authenticated:
        return redirect(url_for('routes.home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        truename = request.form.get('truename')

        # === 新增字段 ===
        role = request.form.get('role')
        department = request.form.get('department')
        class_name = request.form.get('class_name')
        # ===============

        if User.query.filter_by(username=username).first():
            flash('账号已存在')
            return redirect(url_for('auth.register'))

        new_user = User(
            username=username,
            truename=truename,
            role=role,
            department=department,
            class_name=class_name
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash('注册成功！请登录。')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))