# app/__init__.py
from flask import Flask, jsonify
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config.get('SECRET_KEY'):
        if app.config.get('APP_ENV') in {'development', 'testing'}:
            app.config['SECRET_KEY'] = 'development-only-secret-key'
        else:
            raise RuntimeError(
                'SECRET_KEY is required outside development/testing. '
                'Set it through the environment or the project .env file.'
            )

    db.init_app(app)

    @app.get('/healthz')
    def healthz():
        """Minimal process/database health probe for deployments."""
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({'status': 'ok', 'database': 'ok'})
        except Exception:
            app.logger.exception('health check failed')
            return jsonify({'status': 'error', 'database': 'unavailable'}), 503

    from .security import init_csrf_protection
    init_csrf_protection(app)

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
        return db.session.get(User, int(user_id))

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

    # === Phase 3：数据洞察 API ===
    from .api.insights import insights_bp
    app.register_blueprint(insights_bp, url_prefix='/api/insights')

    # 自动创建数据库表
    with app.app_context():
        db.create_all()
        from .schema_migrations import ensure_schema_compatibility
        ensure_schema_compatibility()
        from .services.question_bank import repair_question_bank
        repair_question_bank()
        from .services.storage_cleanup import cleanup_runtime_files
        cleanup_runtime_files(app)

    return app
