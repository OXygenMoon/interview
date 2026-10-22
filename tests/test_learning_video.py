"""Video lesson management, private playback and migration contracts."""
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from flask_migrate import upgrade
from sqlalchemy import text

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'video-test-secret')
os.environ.setdefault('LLM_API_KEY', 'video-test-placeholder')

from app import create_app, db
from app.config import Config
from app.models import LearningCategory, LearningMaterial, User, UserLearningProgress
from app.services.learning_media import normalize_bilibili_url


# Container header sufficient for upload contract tests. Browser tests use a real clip.
MP4 = b'\x00\x00\x00\x20ftypisom' + b'\x00' * 60
BVID = 'BV1B7411m7LV'


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', 'sqlite://')
    monkeypatch.setattr(Config, 'SECRET_KEY', 'video-test-secret')
    monkeypatch.setattr(Config, 'SESSION_COOKIE_SECURE', False)
    monkeypatch.setattr(Config, 'LEARNING_VIDEO_UPLOAD_DIR', str(tmp_path / 'videos'))
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([User(id=1, username='admin', role='admin'),
            User(id=2, username='student', role='student'),
            User(id=3, username='teacher', role='teacher'),
            LearningCategory(id=1, name='课程')])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def client_as(app, user_id=1):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['_csrf_token'] = 'video-csrf'
    return client


def payload(**values):
    return dict(category_id=1, title='视频课程', type='video', content='',
                video_source='bilibili', video_url=f'https://www.bilibili.com/video/{BVID}', **values)


def upload(client, url='/api/admin/learning/material/add', video=MP4, filename='课程.mp4', **values):
    data = payload()
    data.update(video_source='upload', **values)
    data['video'] = (BytesIO(video), filename)
    return client.post(url, data=data, content_type='multipart/form-data')


def test_bilibili_create_edit_student_playback_and_completion(app):
    admin = client_as(app)
    data = payload()
    data['video_url'] = f'<iframe src="//player.bilibili.com/player.html?bvid={BVID}&amp;p=2" onload="evil()"></iframe>'
    result = admin.post('/api/admin/learning/material/add', json=data)
    assert result.status_code == 200
    material_id = result.json['id']
    student = client_as(app, 2)
    page = student.get(f'/learning/material/{material_id}').get_data(as_text=True)
    assert '<iframe src="https://player.bilibili.com/player.html?' in page
    assert 'p=2&amp;autoplay=0' in page and 'onload="evil()"' not in page
    assert '标记本节已学完' in page
    for expected in ('success', 'already_completed'):
        assert student.post(f'/api/learning/complete/{material_id}').json['status'] == expected
    with app.app_context():
        assert UserLearningProgress.query.count() == 1
    # Editing a URL/title preserves existing progress, but type changes are blocked.
    data['title'] = '已更新标题'
    assert admin.post(f'/api/admin/learning/material/update/{material_id}', json=data).status_code == 200
    data.update(type='article', content='正文')
    assert admin.post(f'/api/admin/learning/material/update/{material_id}', json=data).status_code == 400
    assert admin.post(f'/api/admin/learning/material/delete/{material_id}').status_code == 400


def test_upload_private_range_playback_keep_replace_and_delete(app):
    admin = client_as(app)
    result = upload(admin)
    assert result.status_code == 200, result.json
    material_id = result.json['id']
    directory = Path(app.config['LEARNING_VIDEO_UPLOAD_DIR'])
    with app.app_context():
        original = directory / db.session.get(LearningMaterial, material_id).video_url
    assert original.read_bytes() == MP4 and '课程' not in original.name
    endpoint = f'/learning/material/{material_id}/video'
    assert app.test_client().get(endpoint).status_code == 302
    student = client_as(app, 2)
    response = student.get(endpoint, headers={'Range': 'bytes=0-15'})
    assert response.status_code == 206
    assert response.data == MP4[:16] and response.mimetype == 'video/mp4'
    assert response.headers['Content-Range'] == f'bytes 0-15/{len(MP4)}'
    page = student.get(f'/learning/material/{material_id}').get_data(as_text=True)
    assert f'src="{endpoint}"' in page and '<video controls playsinline' in page
    data = payload()
    data.update(video_source='upload', video_url='../../untrusted.mp4')
    assert admin.post(f'/api/admin/learning/material/update/{material_id}', json=data).status_code == 200
    assert original.exists()  # The server keeps its own filename, never a client path.
    assert upload(admin, f'/api/admin/learning/material/update/{material_id}').status_code == 200
    assert not original.exists() and len(list(directory.iterdir())) == 1
    assert admin.post(f'/api/admin/learning/material/delete/{material_id}').status_code == 200
    assert not list(directory.iterdir())
    assert student.get(endpoint).status_code == 404


def test_switching_source_and_deleting_category_clean_files(app):
    admin = client_as(app)
    material_id = upload(admin).json['id']
    directory = Path(app.config['LEARNING_VIDEO_UPLOAD_DIR'])
    assert admin.post(f'/api/admin/learning/material/update/{material_id}', json=payload()).status_code == 200
    assert not list(directory.iterdir())
    upload(admin)
    assert admin.post('/api/admin/learning/category/delete/1').status_code == 200
    assert not list(directory.iterdir())


@pytest.mark.parametrize('user_id', [2, 3])
def test_only_admin_can_manage_courses(app, user_id):
    client = client_as(app, user_id)
    assert client.get('/admin/learning').status_code == 403
    assert upload(client).status_code == 403
    assert client.post('/api/admin/learning/material/update/1', json=payload()).status_code == 403
    with app.app_context():
        assert LearningMaterial.query.count() == 0


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'https://evil.test/player.html?bvid=' + BVID,
    'https://player.bilibili.com.evil.test/player.html?bvid=' + BVID,
    'https://player.bilibili.com@evil.test/player.html?bvid=' + BVID,
    '<iframe src="https://evil.test"></iframe>',
    'https://player.bilibili.com/player.html?bvid=bad',
    'https://player.bilibili.com/player.html?bvid=' + BVID + '&p=-1',
    'https://www.bilibili.com/',
])
def test_invalid_embeds_are_rejected(app, url):
    data = payload()
    data['video_url'] = url
    assert client_as(app).post('/api/admin/learning/material/add', json=data).status_code == 400
    with app.app_context():
        assert LearningMaterial.query.count() == 0


def test_legacy_aid_and_protocol_relative_embeds():
    result = normalize_bilibili_url('//player.bilibili.com/player.html?aid=123&cid=456&p=2&autoplay=1')
    assert result == 'https://player.bilibili.com/player.html?aid=123&cid=456&p=2&autoplay=0'


def test_invalid_files_missing_category_and_size_limits(app):
    admin = client_as(app)
    assert upload(admin, video=b'<script>bad</script>').status_code == 400
    assert upload(admin, filename='movie.html').status_code == 400
    data = payload()
    data.update(category_id=999)
    assert admin.post('/api/admin/learning/material/add', json=data).status_code == 400
    data.update(category_id=1, video_source='upload')
    assert admin.post('/api/admin/learning/material/add', json=data).status_code == 400
    app.config['LEARNING_VIDEO_MAX_BYTES'] = 32
    assert upload(admin).status_code == 413
    assert upload(admin, video=MP4 + b'x' * (1024 * 1024)).status_code == 413
    directory = Path(app.config['LEARNING_VIDEO_UPLOAD_DIR'])
    assert not directory.exists() or not list(directory.iterdir())
    with app.app_context():
        assert LearningMaterial.query.count() == 0


def test_learning_upload_limit_does_not_raise_other_api_limits(app):
    app.config.update(MAX_CONTENT_LENGTH=32, LEARNING_VIDEO_MAX_BYTES=1024)
    admin = client_as(app)
    assert upload(admin).status_code == 200
    assert admin.post('/api/admin/learning/category/add', json={'name': 'x' * 128}).status_code == 413


def test_failed_database_save_removes_new_upload(app):
    with patch.object(db.session, 'commit', side_effect=RuntimeError('write failed')):
        with pytest.raises(RuntimeError, match='write failed'):
            upload(client_as(app))
    assert not list(Path(app.config['LEARNING_VIDEO_UPLOAD_DIR']).iterdir())


def test_versioned_migration_preserves_existing_course(app):
    with app.app_context():
        db.drop_all()
        upgrade(revision='20261008_resume_document')
        db.session.execute(text("INSERT INTO learning_categories (id, name) VALUES (5, '已有分类')"))
        db.session.execute(text("INSERT INTO learning_materials (id, category_id, title, material_type, content) VALUES (7, 5, '旧文章', 'article', '保留正文')"))
        db.session.commit()
        upgrade()
        material = db.session.get(LearningMaterial, 7)
        assert material.title == '旧文章' and material.content == '保留正文'
        assert material.video_source is None and material.video_url is None
