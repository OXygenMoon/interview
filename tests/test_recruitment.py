"""Recruitment normalization, independent sync failures, search and source links."""
import json
import os
from datetime import timedelta
from unittest.mock import patch

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'jobs-test-secret')
os.environ.setdefault('LLM_API_KEY', 'jobs-test-placeholder')

from app import create_app, db
from app.config import Config
from app.models import RecruitmentJob, RecruitmentSync, User
from app.services.recruitment import (
    canonical_url, normalize_job, parse_local_detail, parse_local_list,
    parse_structured_jobs, save_jobs, sync_source, utcnow,
)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite://')
    monkeypatch.setattr(Config, 'SECRET_KEY', 'jobs-test-secret')
    monkeypatch.setattr(Config, 'SESSION_COOKIE_SECURE', False)
    application = create_app()
    application.config.update(TESTING=True, RECRUITMENT_REQUEST_DELAY=0)
    with application.app_context():
        db.create_all()
        db.session.add_all([User(id=1, username='admin', role='admin'),
                            User(id=2, username='student', role='student')])
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def client_as(app, user=2):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user)
        session['_fresh'] = True
    return client


def job(**overrides):
    value = dict(title='机械设计', company='嘉善测试制造有限公司', district='嘉兴嘉善县姚庄',
        salary='8-13K', experience='经验不限', education='大专', description='岗位要求：机械设计。',
        url='https://www.zhipin.com/job_detail/abc123.html?ka=search')
    value.update(overrides)
    return value


def test_normalization_merges_exact_local_identity_and_preserves_companies():
    one = normalize_job('boss', job())
    two = normalize_job('lagou', job(url='https://www.lagou.com/jobs/123.html', district='嘉善'))
    assert one['group_key'] == two['group_key']
    assert normalize_job('boss', job(company='另一家企业'))['group_key'] != one['group_key']
    assert normalize_job('boss', job(district='嘉兴南湖区'))['group_key'] != one['group_key']
    assert one['source_url'] == 'https://www.zhipin.com/job_detail/abc123.html'
    with pytest.raises(ValueError):
        normalize_job('boss', job(district='上海', description='嘉善公司在上海的岗位'))


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'http://www.zhipin.com/job_detail/a.html',
    'https://www.zhipin.com.evil.com/job_detail/a.html',
    'https://www.zhipin.com@evil.com/job_detail/a.html',
    'https://www.zhipin.com:444/job_detail/a.html',
    'https://www.zhipin.com/', 'https://www.lagou.com/jobs/123.html',
])
def test_origin_link_validation(url):
    with pytest.raises(ValueError):
        canonical_url('boss', url)


def test_public_page_parsers_and_plain_text():
    body = '''<li><a class="job" title="机械设计" href="/Q/StationInfo.aspx?StationID=C123">
      <p><b>机械设计</b><b>8k-13k</b></p><p><span>嘉善</span><span>一年以上</span><span>本科</span></p>
      </a><a class="firm" title="测试企业"></a></li>'''
    rows = parse_local_list(body, 'https://www.573job.com/')
    assert rows[0]['url'] == 'https://www.573job.com/Q/StationInfo.aspx?StationID=C123'
    assert rows[0]['salary'] == '8k-13k'
    detail = parse_local_detail('<div><div><h3>职位描述</h3></div><div>职责一<br>职责二</div></div>')
    assert detail['description'] == '职责一\n职责二'
    posting = {'@type': 'JobPosting', 'title': '设计师', 'url': '/jobs/123.html',
        'hiringOrganization': {'name': '测试企业'}, 'description': '<p>要求</p><script>evil()</script>',
        'jobLocation': {'address': {'addressLocality': '嘉兴', 'streetAddress': '嘉善县姚庄'}},
        'baseSalary': {'currency': 'CNY', 'value': {'minValue': 8000, 'maxValue': 13000, 'unitText': 'MONTH'}}}
    rows = parse_structured_jobs('<script type="application/ld+json">'+json.dumps(posting).replace('</', '<\\/')+'</script>', 'https://www.lagou.com/')
    normalized = normalize_job('lagou', rows[0])
    assert normalized['district'] == '嘉善'
    assert normalized['description'] == '要求'
    assert normalized['salary'] == '8000-13000 CNY/MONTH'
    assert parse_structured_jobs('<html>需要验证</html>', 'https://www.zhipin.com/') == []


def test_sync_idempotency_failure_retains_cache_and_atomic_import(app):
    with app.app_context():
        assert sync_source('boss', [job()])['status'] == 'success'
        assert sync_source('boss', [job(salary='9-14K')])['status'] == 'success'
        assert RecruitmentJob.query.count() == 1
        assert RecruitmentJob.query.first().salary == '9-14K'
        success_time = db.session.get(RecruitmentSync, 'boss').succeeded_at
        with patch('app.services.recruitment.collect_source', side_effect=ValueError('需要验证')):
            assert sync_source('boss')['status'] == 'failed'
        assert RecruitmentJob.query.count() == 1
        assert db.session.get(RecruitmentSync, 'boss').succeeded_at == success_time
        result = sync_source('boss', [job(title='不应保存', url='https://www.zhipin.com/job_detail/new.html'), job(url='https://evil.com/')])
        assert result['status'] == 'failed' and RecruitmentJob.query.count() == 1
        state = db.session.get(RecruitmentSync, 'boss')
        state.lease_token = 'another-task'
        state.started_at = utcnow()
        state.status = 'running'
        db.session.commit()
        assert sync_source('boss', [job()])['status'] == 'running'
        assert state.lease_token == 'another-task'


def test_search_group_details_filters_expiry_and_authorization(app):
    with app.app_context():
        save_jobs('boss', [job(), job(title='50% 技术员', url='https://www.zhipin.com/job_detail/b.html'),
                          job(title='过期岗位', expires_at='2020-01-01', url='https://www.zhipin.com/job_detail/old.html')])
        save_jobs('lagou', [job(salary='10-15K', url='https://www.lagou.com/jobs/123.html')])
        old = normalize_job('boss', job(title='旧记录', url='https://www.zhipin.com/job_detail/stale.html'))
        db.session.add(RecruitmentJob(**old, last_seen_at=utcnow()-timedelta(days=31)))
        db.session.commit()
        key = RecruitmentJob.query.filter_by(title='机械设计').first().group_key
    client = client_as(app)
    assert app.test_client().get('/jobs').status_code == 302
    assert client.post('/jobs/sync', data={'source': 'boss'}).status_code == 403
    assert client.get('/jobs/unknown').status_code == 404
    body = client.get('/jobs').get_data(as_text=True)
    assert body.count('<li class="jobs-row">') == 2
    assert '2 条来源记录已合并' in body and '过期岗位' not in body and '旧记录' not in body
    body = client.get('/jobs?source=lagou&district=嘉善&q=机械').get_data(as_text=True)
    assert body.count('<li class="jobs-row">') == 1 and 'BOSS直聘' in body
    assert client.get('/jobs?q=%25').get_data(as_text=True).count('<li class="jobs-row">') == 1
    body = client.get('/jobs?include_old=1').get_data(as_text=True)
    assert '过期岗位' in body and '旧记录' in body
    body = client.get(f'/jobs/{key}?q=机械&district=嘉善').get_data(as_text=True)
    assert 'https://www.lagou.com/jobs/123.html' in body and 'https://www.zhipin.com/job_detail/abc123.html' in body
    assert 'rel="noopener noreferrer"' in body and '10-15K' in body and '8-13K' in body
    assert 'q=' in body and 'district=' in body
    assert client.get('/jobs?q=不存在&page=oops').status_code == 200
    assert '没有找到符合条件的岗位' in client.get('/jobs?q=不存在').get_data(as_text=True)


def test_pagination_preserves_filters_and_escapes_content(app):
    with app.app_context():
        save_jobs('boss', [job(title=f'设计师 {i}', url=f'https://www.zhipin.com/job_detail/{i}.html') for i in range(17)])
        save_jobs('boss', [job(title='<img src=x onerror=alert(1)>设计师', url='https://www.zhipin.com/job_detail/xss.html')])
        db.session.commit()
    client = client_as(app)
    body = client.get('/jobs?q=设计师&district=嘉善').get_data(as_text=True)
    assert body.count('<li class="jobs-row">') == 15
    assert 'onerror=' not in body and 'page=2' in body
    body = client.get('/jobs?q=设计师&district=嘉善&page=2').get_data(as_text=True)
    assert body.count('<li class="jobs-row">') == 3


def test_admin_refresh_and_cli_import(app, tmp_path):
    admin = client_as(app, 1)
    with patch('app.services.recruitment.collect_source', return_value=([job()], False)):
        response = admin.post('/jobs/sync', data={'source': 'boss'}, follow_redirects=True)
        assert response.status_code == 200 and '已更新 1 条来源记录' in response.get_data(as_text=True)
    assert admin.post('/jobs/sync', data={'source': 'invalid'}).status_code == 400
    path = tmp_path/'jobs.json'
    path.write_text(json.dumps([job(url='https://www.lagou.com/jobs/123.html')]), encoding='utf-8')
    result = app.test_cli_runner().invoke(args=['sync-jobs', '--source', 'lagou', '--file', str(path)])
    assert result.exit_code == 0, result.output
    assert 'success' in result.output
    path.write_text('{}', encoding='utf-8')
    assert app.test_cli_runner().invoke(args=['sync-jobs', '--source', 'lagou', '--file', str(path)]).exit_code != 0


def test_new_schema_bootstrap_upgrade_legacy_adoption_and_downgrade(tmp_path, monkeypatch):
    from flask_migrate import downgrade, upgrade
    from sqlalchemy import inspect
    from app.database_migrations import bootstrap_database
    for legacy in (False, True):
        monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / ("legacy.db" if legacy else "fresh.db")}')
        application = create_app()
        application.config['TESTING'] = True
        with application.app_context():
            if legacy:
                db.create_all()
                db.session.add(User(id=3, username='preserved', role='student'))
                db.session.commit()
            result = bootstrap_database()
            assert result['revision'] == '20261025_local_recruitment'
            assert inspect(db.engine).has_table('recruitment_jobs')
            if legacy:
                assert db.session.get(User, 3).username == 'preserved'
            downgrade(revision='20261022_learning_video')
            assert not inspect(db.engine).has_table('recruitment_jobs')
            upgrade()
            assert inspect(db.engine).has_table('recruitment_syncs')
            db.session.remove()
            db.engine.dispose()


def test_sync_failure_is_independent_and_preserves_success_timestamp(app):
    with app.app_context():
        with patch('app.services.recruitment.collect_source', side_effect=[
            ValueError('验证码'), ([job(url='https://www.lagou.com/jobs/123.html')], False),
            ([job(url='https://www.573job.com/Q/StationInfo.aspx?StationID=C1')], True),
        ]):
            result = app.test_cli_runner().invoke(args=['sync-jobs', '--limit', '3'])
        assert result.exit_code != 0
        assert 'boss: failed' in result.output and 'lagou: success' in result.output and 'jiaxing: partial' in result.output
        assert RecruitmentJob.query.count() == 2


def test_csrf_is_enforced_for_refresh(app):
    from app.database_migrations import bootstrap_database
    with app.app_context():
        bootstrap_database()
    admin = client_as(app, 1)
    app.config['TESTING'] = False
    try:
        assert admin.post('/jobs/sync', data={'source': 'boss'}).status_code == 400
    finally:
        app.config['TESTING'] = True
