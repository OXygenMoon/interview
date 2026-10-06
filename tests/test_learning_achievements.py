import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'learning-achievements-test-session')
os.environ.setdefault('LLM_API_KEY', 'learning-achievements-test-placeholder')

from app import db
from app.integrations.account_link import init_account_link, origin, LinkError
from app.integrations.account_link_authority import operate
from app.models import (AccountLink, ChatMessage, InterviewSession,
                        LearningAttempt, LearningMaterial,
                        User, UserLearningProgress)
from app.security import init_csrf_protection
from app.services import learning_achievements as achievements


NOW = datetime(2026, 10, 6, 12)
SECRET = 'test-only-learning-secret-at-least-32-characters'


@pytest.fixture
def workspace(monkeypatch):
    app = Flask(__name__)
    app.config.update(SECRET_KEY='local-test-session', SQLALCHEMY_DATABASE_URI='sqlite://',
        SQLALCHEMY_TRACK_MODIFICATIONS=False, ACCOUNT_LINK_SECRET=SECRET,
        ACCOUNT_LINK_INTERVIEW_URL='http://127.0.0.1:5008',
        ACCOUNT_LINK_WIKIBOOK_URL='http://127.0.0.1:5180', CSRF_ENABLED=True)
    db.init_app(app)
    init_csrf_protection(app)
    init_account_link(app, 'interview', lambda uid: db.session.get(User, uid),
        lambda: '/', lambda: '/login', authority=operate)
    monkeypatch.setattr(achievements, 'now_beijing', lambda: NOW)
    with app.app_context():
        db.create_all()
        first = User(id=1, username='first', password_hash='unused', active=True)
        other = User(id=2, username='other', password_hash='unused', active=True)
        db.session.add_all([first, other, AccountLink(id='test-link', interview_user_id=1,
            wikibook_user_id=10, interview_username='first', wikibook_username='wiki')])
        db.session.commit()
        yield SimpleNamespace(app=app, user=first, other=other)
        db.session.remove()
        db.drop_all()


def stats(workspace, **params):
    payload = {'action': 'learning_achievements', 'user_id': 10,
        'actor_identity': {'id': 10, 'username': 'wiki', 'version': 'a' * 64}, **params}
    response = workspace.app.test_client().post('/internal/account-link', json=payload,
        headers={'Authorization': 'Bearer ' + SECRET})
    assert response.status_code == 200, response.json
    return response.json['data']


def session(workspace, day=1, user_id=1, answers=3, **fields):
    start = datetime(2026, 10, day, 9)
    row = InterviewSession(user_id=user_id, start_time=start, end_time=start + timedelta(minutes=10),
        status='completed', total_score=50, summary_comment='Feedback', position_id=10, **fields)
    db.session.add(row)
    db.session.flush()
    for index in range(answers):
        db.session.add(ChatMessage(session_id=row.id, sender='ai', content=f'Question {index}',
            timestamp=start + timedelta(minutes=2 * index), generation_status='completed'))
        db.session.add(ChatMessage(session_id=row.id, sender='user', content=f'Answer {index}',
            timestamp=start + timedelta(minutes=2 * index + 1), generation_status='completed'))
    db.session.commit()
    return row


def material(kind='quiz'):
    row = LearningMaterial(title='Material', material_type=kind)
    db.session.add(row)
    db.session.flush()
    return row


def attempt(material, day, score, user_id=1):
    row = LearningAttempt(user_id=user_id, material_id=material.id, score=score,
        passed=score >= 80, attempted_at=datetime(2026, 10, day, 10))
    db.session.add(row)
    db.session.commit()
    return row


def test_authenticated_read_only_scope_and_csrf_exemption(workspace):
    session(workspace)
    session(workspace, user_id=2)
    client = workspace.app.test_client()
    assert client.post('/internal/account-link', json={}).status_code == 401
    assert client.post('/internal/account-link', json={}, headers={
        'Authorization': 'Bearer wrong'}).status_code == 401
    # A real signed machine request works with TESTING=False and CSRF enabled.
    data = stats(workspace)
    assert data['metrics']['interview_valid_session_count'] == 1
    assert data['wikibook_user_id'] == 10 and data['link_id'] == 'test-link'
    assert set(data) == {'schema_version', 'wikibook_user_id', 'linked', 'link_id',
                         'generated_at', 'metrics', 'valid_days'}
    assert not db.session.new and not db.session.dirty and not db.session.deleted
    with patch.object(achievements, 'linked_learning_achievements') as calculation:
        bad = client.post('/internal/account-link', json={
            'action': 'learning_achievements', 'user_id': 10,
            'actor_identity': {'id': 20, 'username': 'wiki', 'version': 'a' * 64}},
            headers={'Authorization': 'Bearer ' + SECRET})
        assert bad.status_code == 400
        calculation.assert_not_called()


def test_effective_sessions_exclude_empty_duplicate_failed_deleted_and_future(workspace):
    session(workspace, reviewed=True)
    session(workspace, answers=0)
    session(workspace, answers=2)
    session(workspace, abandoned=True)
    session(workspace, deleted_at=NOW)
    session(workspace, evaluation_source='rule')
    session(workspace, day=7)
    invalid = session(workspace)
    invalid.status = 'failed'
    # Three duplicate user messages against a single question do not count as
    # three questions; failed AI generations also cannot anchor valid answers.
    duplicate = session(workspace, answers=1)
    for _ in range(4):
        db.session.add(ChatMessage(session_id=duplicate.id, sender='user', content='Again',
            timestamp=duplicate.start_time + timedelta(minutes=2)))
    broken = session(workspace)
    ChatMessage.query.filter_by(session_id=broken.id, sender='ai').update({'generation_status': 'failed'})
    db.session.commit()
    data = stats(workspace)
    assert data['metrics']['interview_valid_session_count'] == 1
    assert data['metrics']['interview_report_viewed_count'] == 1
    assert data['valid_days'] == ['2026-10-01']


def test_days_positions_and_exclusive_window(workspace):
    session(workspace, day=1)
    session(workspace, day=2)
    row = session(workspace, day=2)
    row.position_id = 20
    session(workspace, day=3)
    db.session.commit()
    data = stats(workspace, start_date='2026-10-02', end_date_exclusive='2026-10-03')
    assert data['metrics']['interview_valid_session_count'] == 2
    assert data['metrics']['interview_active_day_count'] == 1
    assert data['metrics']['interview_position_variety_count'] == 2
    assert data['valid_days'] == ['2026-10-02']


def test_chain_antecedents_outside_window_and_invalid_parent(workspace):
    first = session(workspace, day=1, round=1)
    second = session(workspace, day=2, round=2, parent_session_id=first.id)
    third = session(workspace, day=3, round=3, parent_session_id=second.id)
    data = stats(workspace, start_date='2026-10-03', end_date_exclusive='2026-10-04')
    assert data['metrics']['interview_round_chain_complete_count'] == 1
    assert data['metrics']['interview_valid_session_count'] == 1
    second.position_id = 99
    db.session.commit()
    assert stats(workspace)['metrics']['interview_round_chain_complete_count'] == 0
    second.position_id = 10
    first.user_id = 2
    db.session.commit()
    assert stats(workspace)['metrics']['interview_round_chain_complete_count'] == 0


def test_quiz_pass_recovery_and_article_exclusion(workspace):
    quiz = material()
    old_quiz = material()
    article = material('article')
    attempt(quiz, 1, 20)
    attempt(quiz, 2, 80)
    attempt(quiz, 3, 100)
    attempt(article, 2, 100)
    attempt(old_quiz, 1, 100)
    db.session.add(UserLearningProgress(user_id=1, material_id=old_quiz.id,
        status='completed', score=100, completed_at=datetime(2026, 10, 2)))
    db.session.commit()
    data = stats(workspace, start_date='2026-10-02', end_date_exclusive='2026-10-03')
    assert data['metrics']['interview_quiz_passed_count'] == 1
    assert data['metrics']['interview_quiz_recovery_count'] == 1


def test_legacy_quiz_progress_never_proves_recovery(workspace):
    quiz = material()
    db.session.add(UserLearningProgress(user_id=1, material_id=quiz.id,
        status='completed', score=100, completed_at=datetime(2026, 10, 2)))
    attempt(quiz, 3, 30)
    db.session.commit()
    data = stats(workspace)
    assert data['metrics']['interview_quiz_passed_count'] == 1
    assert data['metrics']['interview_quiz_recovery_count'] == 0


def test_prior_legacy_pass_prevents_false_first_recovery(workspace):
    quiz = material()
    db.session.add(UserLearningProgress(user_id=1, material_id=quiz.id,
        status='completed', score=100, completed_at=datetime(2026, 10, 1)))
    attempt(quiz, 2, 20)
    attempt(quiz, 3, 100)
    data = stats(workspace, start_date='2026-10-02', end_date_exclusive='2026-10-04')
    assert data['metrics']['interview_quiz_passed_count'] == 0
    assert data['metrics']['interview_quiz_recovery_count'] == 0


@pytest.mark.parametrize('fields', [{'start_date': 'bad'}, {'start_date': 10},
    {'start_date': '2026-10-04', 'end_date_exclusive': '2026-10-03'}])
def test_bad_windows(workspace, fields):
    client = workspace.app.test_client()
    payload = {'action': 'learning_achievements', 'user_id': 10,
        'actor_identity': {'id': 10, 'username': 'wiki', 'version': 'a' * 64}, **fields}
    assert client.post('/internal/account-link', json=payload, headers={
        'Authorization': 'Bearer ' + SECRET}).status_code == 400


def test_unlinked_and_inactive_accounts(workspace):
    assert stats(workspace, user_id=20, actor_identity={
        'id': 20, 'username': 'other', 'version': 'a' * 64})['linked'] is False
    workspace.user.active = False
    db.session.commit()
    payload = {'action': 'learning_achievements', 'user_id': 10,
        'actor_identity': {'id': 10, 'username': 'wiki', 'version': 'a' * 64}}
    response = workspace.app.test_client().post('/internal/account-link', json=payload,
        headers={'Authorization': 'Bearer ' + SECRET})
    assert response.status_code == 403


def test_record_timezone_conversion(workspace):
    workspace.app.config['INTERVIEW_RECORD_TIMEZONE'] = 'UTC'
    row = session(workspace)
    shift = timedelta(hours=10)
    row.start_time += shift
    row.end_time += shift
    for message in ChatMessage.query.filter_by(session_id=row.id):
        message.timestamp += shift
    db.session.commit()
    assert stats(workspace)['valid_days'] == ['2026-10-02']


def test_production_origin_exact_exception(workspace):
    workspace.app.config['ACCOUNT_LINK_INTERVIEW_URL'] = 'http://211.154.20.65:20018'
    assert origin('ACCOUNT_LINK_INTERVIEW_URL') == 'http://211.154.20.65:20018'
    for url in ('http://211.154.20.65:20019', 'http://211.154.20.66:20018',
                'http://211.154.20.65:20018.evil.test', 'http://example.com'):
        workspace.app.config['ACCOUNT_LINK_INTERVIEW_URL'] = url
        with pytest.raises(LinkError):
            origin('ACCOUNT_LINK_INTERVIEW_URL')


def test_notification_failure_preserves_committed_learning(workspace):
    first = session(workspace)
    with patch('app.integrations.account_link.server_call', side_effect=LinkError('unavailable')):
        achievements.notify_wikibook_learning_change(1)
    assert db.session.get(InterviewSession, first.id).status == 'completed'


def test_first_report_view_notifies_actual_author_once(workspace):
    from app.utils.session_state import mark_reviewed

    row = session(workspace, user_id=2)
    with patch.object(achievements, 'notify_wikibook_learning_change') as notification:
        mark_reviewed(row)
        mark_reviewed(row)
        notification.assert_called_once_with(2)
