"""Missing test-account migrations must not crash authenticated requests."""

import os

import pytest
from flask_migrate import upgrade
from sqlalchemy import inspect

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'migration-guard-test-secret')
os.environ.setdefault('LLM_API_KEY', 'migration-guard-test-key')

from app import create_app, db
from app.config import Config
from app.models import User


@pytest.fixture
def pending_app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "pending.db"}')
    monkeypatch.setattr(Config, 'SECRET_KEY', 'migration-guard-test-secret')
    monkeypatch.setattr(Config, 'SESSION_COOKIE_SECURE', False)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        upgrade(revision='20261007_visual_review')
        user = User(id=51, username='existing-student', role='student')
        db.session.add(user)
        db.session.commit()
        assert not inspect(db.engine).has_table('test_accounts')
    app.config['TESTING'] = False
    # Reproduce a running process that cached success before a new revision
    # and model were added, as can happen during a development reload.
    app.extensions['database_migration_status']['is_current'] = True
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = '51'
        state['_csrf_token'] = 'csrf'
    return client


@pytest.mark.parametrize('method,path', [('GET', '/'), ('POST', '/admin/settings')])
def test_pending_migration_is_checked_before_login_and_csrf(pending_app, method, path):
    response = logged_in_client(pending_app).open(path, method=method)
    assert response.status_code == 503
    assert '数据库迁移尚未完成' in response.get_data(as_text=True)
    assert 'no such table' not in response.get_data(as_text=True)
    assert pending_app.extensions['database_migration_status']['is_current'] is False
    assert pending_app.test_client().get('/healthz').status_code == 200


def test_app_recovers_after_migration_without_recreating_users(pending_app):
    client = logged_in_client(pending_app)
    assert client.get('/').status_code == 503
    pending_app.config['TESTING'] = True
    with pending_app.app_context():
        upgrade()
        assert inspect(db.engine).has_table('test_accounts')
        assert db.session.get(User, 51).username == 'existing-student'
    pending_app.config['TESTING'] = False
    response = client.get('/')
    assert response.status_code == 200
    assert pending_app.extensions['database_migration_status']['is_current'] is True
