"""Seed and atomically reserve the shared test accounts across web workers."""
import secrets
from datetime import datetime, timedelta, timezone

import click
from flask import abort, session
from flask_login import logout_user, user_logged_in, user_logged_out
from sqlalchemy import or_, update

from .. import db
from ..models import Department, SchoolClass, TestAccount, User


TEST_DEPARTMENT = '测试组'
TEST_CLASS = '测试班'
TEST_ACCOUNT_COUNT = 10
LEASE_SECONDS = 180
LEASE_SESSION_KEY = '_test_account_lease'


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_test_accounts():
    """Idempotent; never convert an existing ordinary user into a test account."""
    usernames = [f'interview_test{number:02d}' for number in range(1, TEST_ACCOUNT_COUNT + 1)]
    existing = {user.username: user for user in User.query.filter(User.username.in_(usernames)).all()}
    for user in existing.values():
        if user.test_account is None:
            raise ValueError(f'账号 {user.username} 已存在且不是测试账号，请先处理名称冲突。')

    department = Department.query.filter_by(name=TEST_DEPARTMENT).first()
    if department is None:
        department = Department(name=TEST_DEPARTMENT)
        db.session.add(department)
        db.session.flush()
    if not SchoolClass.query.filter_by(department_id=department.id, name=TEST_CLASS).first():
        db.session.add(SchoolClass(department_id=department.id, name=TEST_CLASS))

    created = 0
    for number, username in enumerate(usernames, start=1):
        user = existing.get(username)
        if user is None:
            user = User(
                username=username, truename=f'测试学员 {number:02d}',
                student_id=f'INTERVIEW-TEST-{number:02d}', role='student',
                department=TEST_DEPARTMENT, class_name=TEST_CLASS,
                active=True, must_change_password=False,
            )
            # One-click access is scoped to TestAccount; no shared password is exposed.
            user.set_password(secrets.token_urlsafe(32))
            db.session.add(user)
            db.session.flush()
            db.session.add(TestAccount(user_id=user.id))
            created += 1
    db.session.commit()
    return created


def claim_account(user_id):
    """A conditional UPDATE grants only one browser the lease, including races."""
    now = utcnow()
    token = secrets.token_urlsafe(32)
    result = db.session.execute(
        update(TestAccount).where(
            TestAccount.user_id == user_id,
            or_(TestAccount.lease_token.is_(None), TestAccount.lease_expires_at.is_(None),
                TestAccount.lease_expires_at <= now),
        ).values(lease_token=token, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return token if result.rowcount == 1 else None


def validate_test_login(user):
    """Reject expired/replaced cookies; a live request renews an owned lease."""
    account = user.test_account
    if account is None:
        return True
    token = session.get(LEASE_SESSION_KEY)
    now = utcnow()
    if (not user.active or not token or account.lease_token != token
            or not account.lease_expires_at or account.lease_expires_at <= now):
        session.pop(LEASE_SESSION_KEY, None)
        return False
    if account.lease_expires_at < now + timedelta(seconds=LEASE_SECONDS - 30):
        result = db.session.execute(
            update(TestAccount).where(
                TestAccount.user_id == user.id, TestAccount.lease_token == token,
                TestAccount.lease_expires_at > now,
            ).values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
            .execution_options(synchronize_session=False)
        )
        db.session.commit()
        return result.rowcount == 1
    return True


def init_test_account_sessions(app):
    def on_login(sender, user, **kwargs):
        if user.test_account is None:
            return
        token = claim_account(user.id)
        if token is None:
            # Flask-Login has already written these keys before emitting the signal.
            session.pop(LEASE_SESSION_KEY, None)
            logout_user()
            abort(409, description='该测试账号使用中，无法登录，请选择其他账号。')
        session[LEASE_SESSION_KEY] = token

    def on_logout(sender, user, **kwargs):
        token = session.pop(LEASE_SESSION_KEY, None)
        if token and user is not None:
            db.session.execute(
                update(TestAccount).where(
                    TestAccount.user_id == user.id, TestAccount.lease_token == token,
                ).values(lease_token=None, lease_expires_at=None)
                .execution_options(synchronize_session=False)
            )
            db.session.commit()

    # Signal hooks cover password login and account-link login as well as the pool.
    user_logged_in.connect(on_login, app, weak=False)
    user_logged_out.connect(on_logout, app, weak=False)

    @app.cli.command('seed-test-accounts')
    def seed_command():
        """Create 10 shared student accounts and their test class; safe to rerun."""
        try:
            created = seed_test_accounts()
        except ValueError as error:
            db.session.rollback()
            raise click.ClickException(str(error)) from error
        click.echo(f'created={created} class={TEST_DEPARTMENT}/{TEST_CLASS} cooldown=5min')
