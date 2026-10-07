"""Company account lifecycle, tenant isolation, submitted snapshots and ranking."""
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'company-tests-secret')
os.environ.setdefault('LLM_API_KEY', 'company-tests-key')

from app import create_app, db
from app.config import Config
from app.models import Company, CompanyAccount, InterviewSession, Position, Resume, User


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    application = create_app()
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with application.app_context():
        db.create_all()
        company_a = Company(id=1, name='合作甲公司')
        company_b = Company(id=2, name='合作乙公司')
        admin = User(id=1, username='admin', role='admin')
        employer = User(id=2, username='employer', role='company')
        student = User(id=3, username='student', role='student', truename='张同学')
        other = User(id=4, username='other', role='student', truename='李同学')
        unbound = User(id=5, username='unbound', role='company')
        for user in (admin, employer, student, other, unbound):
            user.set_password('OriginalPass123!')
        db.session.add_all([company_a, company_b, admin, employer, student, other, unbound])
        db.session.add(CompanyAccount(user=employer, company=company_a))
        db.session.add_all([Position(id=1, company=company_a, name='机械工程师', description='机械基础'),
                            Position(id=2, company=company_b, name='乙公司私有岗位')])
        db.session.add(Resume(id=1, user=student, content={'secret': '当前未递交的私人简历'}))
        db.session.add_all([
            InterviewSession(id=1, user=student, position_id=1, target_role='机械工程师',
                             status='completed', total_score=85, radar_data={'专业技能': 90},
                             resume_snapshot='<script>snapshot()</script> 面试递交快照', resume_id=1,
                             position_snapshot={'position_name': '机械工程师', 'position_description': '历史职责'},
                             evaluation_source='ai'),
            InterviewSession(id=2, user=other, position_id=2, status='completed', target_role='乙公司私有岗位',
                             total_score=99, radar_data={'专业技能': 99}, resume_snapshot='乙公司保密简历'),
            InterviewSession(id=3, user=other, position_id=1, status='ongoing', target_role='未结束面试'),
            InterviewSession(id=4, user=student, position_id=1, status='deleted', target_role='删除面试'),
            InterviewSession(id=5, user=other, position_id=1, status='processing', target_role='生成中岗位'),
        ])
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def login(app, user_id=2):
    client = app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = str(user_id)
        state['_fresh'] = True
    return client


def test_company_login_and_home_routes(app):
    client = app.test_client()
    with client.session_transaction() as state:
        state['account_link_pending'] = {'state': 'previous-account'}
    response = client.post('/login', data={'username': 'employer', 'password': 'OriginalPass123!'})
    assert response.location.endswith('/company')
    for path in ('/', '/dashboard'):
        assert client.get(path).location.endswith('/company')
    assert '企业招聘工作台' in client.get('/company').get_data(as_text=True)


@pytest.mark.parametrize('path', ['/company', '/company/positions', '/company/interviews',
                                  '/company/interviews/1', '/company/interviews/1/resume',
                                  '/company/positions/1/recommendations'])
def test_company_pages_render(app, path):
    response = login(app).get(path)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('user_id', [1, 3, 5])
def test_company_workspace_requires_bound_company_role(app, user_id):
    assert login(app, user_id).get('/company').status_code == 403


@pytest.mark.parametrize('path', ['/company/positions/2/edit', '/company/interviews/2',
                                  '/company/interviews/2/resume', '/company/positions/2/recommendations',
                                  '/company/interviews?position_id=2', '/company/interviews/3',
                                  '/company/interviews/4'])
def test_other_company_and_unfinished_or_deleted_records_are_private(app, path):
    assert login(app).get(path).status_code == 404


@pytest.mark.parametrize('path', ['/admin/organization', '/admin/company', '/admin/partnerships',
                                  '/admin/resume/1', '/teacher/student/3', '/interview/summary/2',
                                  '/api/resume/1', '/history', '/learning'])
def test_company_cannot_use_student_or_school_admin_data(app, path):
    assert login(app).get(path).status_code == 403


def test_records_only_show_owned_finished_interviews(app):
    html = login(app).get('/company/interviews').get_data(as_text=True)
    assert '张同学' in html and '生成中岗位' in html
    assert '乙公司私有岗位' not in html and '未结束面试' not in html and '删除面试' not in html


def test_company_can_manage_own_jobs_and_reject_cross_company_writes(app):
    client = login(app)
    response = client.post('/company/positions/new', data={'name': '新岗位', 'description': '新要求'})
    assert response.status_code == 302
    assert client.post('/company/positions/1/edit', data={'name': '新名称', 'description': '新要求'}).status_code == 302
    assert client.post('/company/positions/2/edit', data={'name': '侵入'}).status_code == 404
    assert client.post('/api/company/1/position', json={'name': 'API岗位'}).status_code == 200
    assert client.post('/api/company/2/position', json={'name': '侵入'}).status_code == 403
    assert client.put('/api/company/position/2', json={'name': '侵入'}).status_code == 403
    assert client.put('/api/company/position/1', json={'name': 'API新名称'}).status_code == 200
    assert client.post('/company/positions/new', data={'name': '   '}).status_code == 200
    assert client.put('/api/company/position/1', json={'name': 'x' * 101}).status_code == 400
    assert client.put('/api/company/position/1', json=['invalid']).status_code == 400
    with app.app_context():
        assert db.session.get(Position, 2).name == '乙公司私有岗位'
        assert db.session.get(InterviewSession, 1).position_snapshot['position_name'] == '机械工程师'
        assert Position.query.filter_by(company_id=1).count() == 3


def test_submitted_resume_remains_snapshot_after_edit_or_delete(app):
    with app.app_context():
        db.session.delete(db.session.get(Resume, 1))
        db.session.commit()
    html = login(app).get('/company/interviews/1/resume').get_data(as_text=True)
    assert '面试递交快照' in html and '&lt;script&gt;' in html
    assert '<script>snapshot()' not in html and '当前未递交的私人简历' not in html
    assert '未保存递交简历' in login(app).get('/company/interviews/5/resume').get_data(as_text=True)


def test_recommendations_rank_latest_completed_per_student_and_explain(app):
    client = login(app)
    html = client.get('/company/positions/1/recommendations').get_data(as_text=True)
    assert '88.0' in html and '张同学' in html and '乙公司保密简历' not in html
    with app.app_context():
        db.session.add(InterviewSession(user_id=3, position_id=1, status='completed', total_score=55,
                                       radar_data={'专业技能': 50}, start_time=datetime.now() + timedelta(seconds=2)))
        db.session.commit()
    html = client.get('/company/positions/1/recommendations').get_data(as_text=True)
    assert '暂时没有达到推荐标准' in html


@pytest.mark.parametrize('values', [
    {'total_score': None}, {'radar_data': None}, {'radar_data': {'专业技能': 59}},
    {'radar_data': {'专业技能': '90'}}, {'radar_data': {'专业技能': 110}},
    {'radar_data': ['invalid']}, {'evaluation_source': 'rule'},
])
def test_recommendations_exclude_unusable_scores(app, values):
    with app.app_context():
        record = db.session.get(InterviewSession, 1)
        for field, value in values.items():
            setattr(record, field, value)
        db.session.commit()
    assert '暂时没有达到推荐标准' in login(app).get('/company/positions/1/recommendations').get_data(as_text=True)


def test_recommendations_exclude_inactive_students(app):
    with app.app_context():
        db.session.get(User, 3).active = False
        db.session.commit()
    assert '暂时没有达到推荐标准' in login(app).get('/company/positions/1/recommendations').get_data(as_text=True)


def test_admin_opens_account_then_company_changes_password(app):
    admin = login(app, 1)
    assert admin.get('/admin/partnerships').status_code == 200
    response = admin.post('/admin/partnerships', data={
        'company_name': '新合作公司', 'username': 'new-company', 'truename': '王经理',
        'password': 'TemporaryPass123!',
    })
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='new-company').one()
        assert user.role == 'company' and user.must_change_password
        assert user.company_account.company.name == '新合作公司'
    client = app.test_client()
    assert client.post('/login', data={'username': 'new-company', 'password': 'TemporaryPass123!'}).location.endswith('/change-password')
    assert client.get('/company').location.endswith('/change-password')
    response = client.post('/change-password', data={
        'current_password': 'TemporaryPass123!', 'new_password': 'NewCompanyPass123!',
        'confirm_password': 'NewCompanyPass123!',
    })
    assert response.location.endswith('/company')
    assert client.get('/company').status_code == 200


def test_admin_lifecycle_and_duplicate_account_rolls_back_company(app):
    client = login(app, 1)
    response = client.post('/admin/partnerships', data={
        'company_name': '应回滚公司', 'username': 'student', 'truename': '联系人', 'password': 'TemporaryPass123!',
    })
    assert '该账号已存在' in response.get_data(as_text=True)
    with app.app_context():
        assert Company.query.filter_by(name='应回滚公司').count() == 0
    response = client.post('/admin/partnerships', data={
        'company_id': '1', 'username': 'second-contact', 'truename': '第二联系人', 'password': 'TemporaryPass123!',
    })
    assert response.status_code == 302
    client.post('/admin/partnerships/2', data={'action': 'contact', 'truename': '新联系人'})
    client.post('/admin/partnerships/2', data={'action': 'reset', 'password': 'ResetPass123!'})
    company_client = app.test_client()
    assert company_client.post('/login', data={'username': 'employer', 'password': 'OriginalPass123!'}).status_code == 200
    assert company_client.post('/login', data={'username': 'employer', 'password': 'ResetPass123!'}).location.endswith('/change-password')
    client.post('/admin/partnerships/2', data={'action': 'toggle'})
    response = company_client.get('/company')
    assert response.location.split('?')[0].endswith('/login')
    with app.app_context():
        assert not db.session.get(User, 2).active
        assert db.session.get(User, 2).truename == '新联系人'
    client.post('/admin/partnerships/2', data={'action': 'toggle'})
    with app.app_context():
        assert db.session.get(User, 2).active


def test_existing_interviews_and_accounts_prevent_destructive_library_deletion(app):
    admin = login(app, 1)
    assert admin.delete('/api/company/1').status_code == 409
    assert admin.delete('/api/company/position/1').status_code == 409
    assert admin.delete('/api/company/position/2').status_code == 409


def test_company_and_student_cannot_create_company_accounts_or_start_company_interviews(app):
    assert login(app).post('/admin/partnerships', data={}).status_code == 403
    assert login(app, 3).post('/admin/partnerships', data={}).status_code == 403
    assert login(app).post('/api/interview/create', data={}).status_code == 403


def test_company_forms_require_csrf_when_enabled(app):
    client = login(app)
    client.get('/company/positions/new')
    app.config['TESTING'] = False
    # Test database intentionally lacks Alembic revision; keep schema guard independent.
    from unittest.mock import patch
    with patch('app.database_migrations.get_migration_status', return_value={'is_current': True}):
        assert client.post('/company/positions/new', data={'name': 'CSRF岗位'}).status_code == 400
        with client.session_transaction() as state:
            token = state['_csrf_token']
        assert client.post('/company/positions/new', data={'name': 'CSRF岗位', 'csrf_token': token}).status_code == 302
    app.config['TESTING'] = True
