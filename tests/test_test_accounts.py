"""Test the pool's exclusivity, recovery, permissions and isolated cooldown."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import Department, InterviewSession, SchoolClass, SystemConfig, TestAccount as PoolAccount, User
from app.services.test_accounts import LEASE_SESSION_KEY, seed_test_accounts, utcnow
from app.utils.session_state import get_cooldown_status


@pytest.fixture
def pool_app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "pool.db"}')
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        seed_test_accounts()
        user = User(username='ordinary', role='student', active=True)
        user.set_password('OrdinaryPass123!')
        db.session.add(user)
        db.session.commit()
        app.config['TEST_POOL_IDS'] = [row.user_id for row in PoolAccount.query.order_by(PoolAccount.user_id)]
        app.config['ORDINARY_ID'] = user.id
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def claim(client, user_id):
    return client.post(f'/test-accounts/{user_id}/login')


def test_seed_is_idempotent_and_creates_one_class(pool_app):
    with pool_app.app_context():
        assert seed_test_accounts() == 0
        assert PoolAccount.query.count() == 10
        assert User.query.filter_by(department='测试组', class_name='测试班', role='student').count() == 10
        assert Department.query.filter_by(name='测试组').count() == 1
        assert SchoolClass.query.filter_by(name='测试班').count() == 1


def test_seed_refuses_existing_ordinary_username(pool_app):
    with pool_app.app_context():
        account = PoolAccount.query.first()
        user_id = account.user_id
        db.session.delete(account)
        db.session.commit()
        with pytest.raises(ValueError, match='不是测试账号'):
            seed_test_accounts()
        assert db.session.get(PoolAccount, user_id) is None


def test_public_states_login_busy_logout_and_reuse(pool_app):
    owner, visitor = pool_app.test_client(), pool_app.test_client()
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    page = visitor.get('/test-accounts')
    assert page.status_code == 200
    assert page.data.count(b'data-account-id=') == 10
    assert page.headers['Cache-Control'] == 'no-store'
    assert claim(owner, user_id).status_code == 302
    states = visitor.get('/api/test-accounts').get_json()['accounts']
    assert states[0]['busy'] and not states[0]['owned']
    assert not any('token' in key for account in states for key in account)
    assert claim(visitor, user_id).status_code == 409
    assert visitor.get('/api/test-accounts').get_json()['signed_in'] is False
    assert owner.get('/api/test-accounts').get_json()['accounts'][0]['owned']
    assert owner.post('/logout').status_code == 302
    assert visitor.get('/api/test-accounts').get_json()['accounts'][0]['busy'] is False
    assert claim(visitor, user_id).status_code == 302


def test_expiry_revokes_old_cookie_without_releasing_new_owner(pool_app):
    old, new = pool_app.test_client(), pool_app.test_client()
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    claim(old, user_id)
    with old.session_transaction() as cookie:
        old_token = cookie[LEASE_SESSION_KEY]
    with pool_app.app_context():
        db.session.get(PoolAccount, user_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert new.get('/api/test-accounts').get_json()['accounts'][0]['busy'] is False
    assert claim(new, user_id).status_code == 302
    assert old.post('/api/test-accounts/heartbeat').status_code == 401
    assert old.post('/logout').status_code == 302  # redirects unauthenticated browser
    assert new.post('/api/test-accounts/heartbeat').status_code == 200
    with pool_app.app_context():
        assert db.session.get(PoolAccount, user_id).lease_token != old_token


def test_heartbeat_renews_but_cannot_resurrect_expired_lease(pool_app):
    owner = pool_app.test_client()
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    claim(owner, user_id)
    with pool_app.app_context():
        db.session.get(PoolAccount, user_id).lease_expires_at = utcnow() + timedelta(seconds=40)
        db.session.commit()
    assert owner.post('/api/test-accounts/heartbeat').status_code == 200
    with pool_app.app_context():
        account = db.session.get(PoolAccount, user_id)
        assert account.lease_expires_at > utcnow() + timedelta(seconds=150)
        account.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert owner.post('/api/test-accounts/heartbeat').status_code == 401


def test_simultaneous_claim_has_exactly_one_winner(pool_app):
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    gate = Barrier(2)

    def concurrent_login():
        client = pool_app.test_client()
        gate.wait(timeout=5)
        return claim(client, user_id).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = list(executor.map(lambda _: concurrent_login(), range(2)))
    assert sorted(codes) == [302, 409]


def test_password_login_also_obeys_exclusive_lease(pool_app):
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    with pool_app.app_context():
        user = db.session.get(User, user_id)
        username = user.username
        user.set_password('TestPass123!')
        db.session.commit()
    owner, visitor = pool_app.test_client(), pool_app.test_client()
    assert owner.post('/login', data={'username': username, 'password': 'TestPass123!'}).status_code == 302
    assert claim(visitor, user_id).status_code == 409
    assert visitor.post('/login', data={'username': username, 'password': 'TestPass123!'}).status_code == 409


def test_pool_cannot_login_ordinary_disabled_or_switch_authenticated_user(pool_app):
    client = pool_app.test_client()
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    ordinary_id = pool_app.config['ORDINARY_ID']
    assert claim(client, ordinary_id).status_code == 404
    with pool_app.app_context():
        db.session.get(User, user_id).active = False
        db.session.commit()
    assert claim(client, user_id).status_code == 403
    assert client.post('/login', data={'username': 'ordinary', 'password': 'OrdinaryPass123!'}).status_code == 302
    assert claim(client, pool_app.config['TEST_POOL_IDS'][1]).status_code == 409
    with client.session_transaction() as cookie:
        assert cookie['_user_id'] == str(ordinary_id)


def test_claim_requires_csrf_in_runtime(pool_app):
    pool_app.config.update(TESTING=False)
    pool_app.extensions['database_migration_status'] = {'is_current': True}
    client = pool_app.test_client()
    user_id = pool_app.config['TEST_POOL_IDS'][0]
    assert claim(client, user_id).status_code == 400
    assert client.get('/test-accounts').status_code == 200
    with client.session_transaction() as cookie:
        token = cookie['_csrf_token']
    assert client.post(f'/test-accounts/{user_id}/login', data={'csrf_token': token}).status_code == 302
    assert client.post('/api/test-accounts/heartbeat').status_code == 400
    assert client.post('/api/test-accounts/heartbeat', headers={'X-CSRF-Token': token}).status_code == 200


@pytest.mark.parametrize('status,abandoned', [('completed', False), ('expired', True), ('processing', False)])
def test_test_students_have_five_minute_cooldown_without_review_gate(pool_app, status, abandoned):
    with pool_app.app_context():
        SystemConfig.set('cooldown_complete_minutes', '30')
        SystemConfig.set('cooldown_abandon_minutes', '10')
        SystemConfig.set('cooldown_requires_review', 'true')
        user_id = pool_app.config['TEST_POOL_IDS'][0]
        ended = datetime.now() - timedelta(minutes=4)
        interview = InterviewSession(user_id=user_id, status=status, abandoned=abandoned,
                                     reviewed=False, start_time=ended, last_activity=ended, end_time=ended)
        db.session.add(interview)
        db.session.commit()
        cooldown = get_cooldown_status(user_id)
        assert cooldown['can_start'] is False
        assert 55 <= cooldown['wait_seconds'] <= 60
        assert cooldown['reason'] != 'review_required'
        interview.end_time = datetime.now() - timedelta(minutes=5, seconds=1)
        db.session.commit()
        assert get_cooldown_status(user_id)['can_start'] is True
        ordinary = InterviewSession(user_id=pool_app.config['ORDINARY_ID'], status=status,
                                    abandoned=abandoned, reviewed=True, start_time=ended,
                                    last_activity=ended, end_time=interview.end_time)
        db.session.add(ordinary)
        db.session.commit()
        assert get_cooldown_status(ordinary.user_id)['can_start'] is False


def test_test_student_cannot_start_second_ongoing_interview(pool_app):
    with pool_app.app_context():
        user_id = pool_app.config['TEST_POOL_IDS'][0]
        db.session.add(InterviewSession(user_id=user_id, status='ongoing', last_activity=datetime.now()))
        db.session.commit()
        assert get_cooldown_status(user_id)['reason'] == 'has_ongoing'
