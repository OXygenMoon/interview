# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    from .filters import register_filters
    register_filters(app)

    # === 初始化登录管理 ===
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # 未登录时自动跳到这里
    login_manager.login_message = "请先登录以访问此页面"

    # 用户加载回调 (Flask-Login 需要用 ID 查用户)
    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # =========================================================
    # 注册蓝图
    # =========================================================
    from .api.interview import api_bp as interview_bp
    app.register_blueprint(interview_bp, url_prefix='/api/interview')

    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    # === 注册认证蓝图 ===
    from .auth import auth_bp
    app.register_blueprint(auth_bp)

    # === 新增：注册用户 API ===
    from .api.user import user_bp
    app.register_blueprint(user_bp, url_prefix='/api/user')

    # === 新增：公司/岗位 API ===
    from .api.company import company_bp
    app.register_blueprint(company_bp, url_prefix='/api/company')

    # === 新增：简历 API ===
    from .api.resume import resume_bp
    app.register_blueprint(resume_bp, url_prefix='/api/resume')

    # 自动创建数据库表
    with app.app_context():
        db.create_all()

    return app
