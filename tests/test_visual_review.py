"""Camera observations survive chat, refresh and authorized report access."""

import base64
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import ChatMessage, InterviewSession, SystemConfig, User
from app.services import ai_agent
from app.services.visual_review import MAX_FRAME_BYTES, decode_frame, normalize_visual_feedback, visual_record


FRAME = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQ1sAAAAASUVORK5CYII='
REVIEW = {'tags': ['头肩居中', '镜头偏低'], 'comment': '本帧头肩居中。建议将镜头抬至眼睛同高，保持自然姿态。'}


@pytest.fixture
def camera_app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "camera.db"}')
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            User(id=1, username='owner', role='student', department='软件系', class_name='一班'),
            User(id=2, username='other', role='student'),
            User(id=3, username='teacher', role='teacher', department='软件系', class_name='一班'),
            User(id=4, username='other-teacher', role='teacher', department='软件系', class_name='二班'),
            User(id=5, username='admin', role='admin'),
            User(id=6, username='head', role='dept_head', department='软件系'),
        ])
        db.session.add(InterviewSession(id=1, user_id=1, status='ongoing', target_role='后端工程师',
                                        start_time=datetime.now() - timedelta(seconds=90)))
        db.session.add(ChatMessage(session_id=1, sender='ai', content='请解释事务。'))
        db.session.commit()
        SystemConfig.set('enable_tts', 'false')
    yield app
    with app.app_context():
        db.session.remove()


def login(client, user_id=1):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def send_answer(app, feedback=REVIEW):
    with app.test_client() as client:
        login(client)
        with patch('app.api.interview.analyze_image', return_value=json.dumps(feedback, ensure_ascii=False)), patch(
            'app.services.ai_agent.stream_ai_response', return_value=iter(['请继续说明。']),
        ):
            result = client.post('/api/interview/1/chat', json={'message': '事务保证原子性。', 'image': FRAME})
            assert result.status_code == 200
            events = [json.loads(event[6:]) for event in result.get_data(as_text=True).strip().split('\n\n')]
    with app.app_context():
        message = ChatMessage.query.filter_by(sender='user').one()
        return message.id, events


def test_chat_persists_frame_before_analysis_and_reports_it_with_text_coaching(camera_app):
    message_id, events = send_answer(camera_app)
    observed = next(event['feedback'] for event in events if event['type'] == 'visual')
    assert observed['tags'] == REVIEW['tags']
    assert observed['comment'] == REVIEW['comment']
    assert observed['elapsed'] == '01:30'
    with camera_app.app_context():
        message = db.session.get(ChatMessage, message_id)
        assert message.visual_image == decode_frame(FRAME)
        assert message.visual_captured_at == message.timestamp
        message.suggestion = '补充事务边界和失败回滚。'
        message.reference_answer = '示例：转账应整体提交或回滚。'
        interview = db.session.get(InterviewSession, 1)
        interview.status = 'completed'
        interview.total_score = 60
        interview.summary_comment = '文字评价保留。'
        db.session.commit()
    with camera_app.test_client() as client:
        login(client)
        html = client.get('/interview/summary/1').get_data(as_text=True)
        for expected in ('01:30', '头肩居中', REVIEW['comment'], '文字评价保留。',
                         '补充事务边界和失败回滚。', '示例：转账应整体提交或回滚。',
                         f'/interview/1/frames/{message_id}', f'#answer-{message_id}'):
            assert expected in html
        assert REVIEW['comment'] in client.get('/interview/room/1').get_data(as_text=True)


@pytest.mark.parametrize('viewer,expected', [(1, 200), (2, 403), (3, 200), (4, 403), (5, 200), (6, 200)])
def test_snapshot_uses_report_permissions_and_private_cache(camera_app, viewer, expected):
    message_id, _ = send_answer(camera_app)
    with camera_app.test_client() as client:
        login(client, viewer)
        result = client.get(f'/interview/1/frames/{message_id}')
        assert result.status_code == expected
        if expected == 200:
            assert result.data == decode_frame(FRAME)
            assert result.mimetype == 'image/png'
            assert result.headers['Cache-Control'] == 'private, no-store'
        assert client.get(f'/interview/999/frames/{message_id}').status_code == 404
    with camera_app.app_context():
        db.session.get(InterviewSession, 1).status = 'deleted'
        db.session.commit()
    with camera_app.test_client() as client:
        login(client, viewer)
        assert client.get(f'/interview/1/frames/{message_id}').status_code == 404


def test_failed_visual_analysis_keeps_image_and_does_not_interrupt_chat(camera_app):
    message_id, events = send_answer(camera_app, '')
    visual = next(event['feedback'] for event in events if event['type'] == 'visual')
    assert '无法给出仪态点评' in visual['comment']
    assert visual['has_image'] is True
    assert any(event['type'] == 'token' for event in events)
    with camera_app.app_context():
        assert db.session.get(ChatMessage, message_id).visual_image


def test_camera_disabled_or_invalid_frame_does_not_store_an_observation(camera_app):
    with camera_app.test_client() as client:
        login(client)
        result = client.post('/api/interview/1/chat', json={'message': '回答', 'image': 'https://private/frame.png'})
        assert result.status_code == 400
    with camera_app.app_context():
        assert ChatMessage.query.filter_by(sender='user').count() == 0
        SystemConfig.set('enable_video', 'false')
    with camera_app.test_client() as client:
        login(client)
        with patch('app.api.interview.analyze_image') as analyze, patch(
            'app.services.ai_agent.stream_ai_response', return_value=iter(['下一个问题。']),
        ):
            result = client.post('/api/interview/1/chat', json={'message': '回答', 'image': FRAME})
            assert result.status_code == 200
            assert '"type": "visual"' not in result.get_data(as_text=True)
            analyze.assert_not_called()
        assert 'id="local-video"' not in client.get('/interview/room/1').get_data(as_text=True)
    with camera_app.app_context():
        assert ChatMessage.query.filter_by(sender='user').one().visual_captured_at is None


def test_legacy_tags_have_answer_timestamps_without_inventing_image_or_posture():
    start = datetime(2026, 10, 7, 9)
    message = SimpleNamespace(id=5, sender='user', visual_context='["画面清晰", "光线偏暗"]',
                              visual_captured_at=None, timestamp=start + timedelta(seconds=125))
    record = visual_record(message, SimpleNamespace(start_time=start))
    assert record['elapsed'] == '02:05'
    assert record['has_image'] is False
    assert record['estimated_time'] is True
    assert record['tags'] == ['画面清晰', '光线偏暗']
    assert '未生成仪态点评' in record['comment']
    assert normalize_visual_feedback('画面清晰，头肩居中')['tags'] == ['画面清晰', '头肩居中']


def test_frame_input_bounds_and_format():
    assert decode_frame(FRAME).startswith(b'\x89PNG')
    for invalid in ('data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,YWJj',
                    'data:image/png;base64,!!', 'https://example.com/image.png',
                    'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'x' * MAX_FRAME_BYTES).decode()):
        with pytest.raises(ValueError):
            decode_frame(invalid)


def test_detailed_visual_model_returns_posture_coaching_and_keeps_default_array_contract():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(REVIEW)))])
    with patch.object(ai_agent.client.chat.completions, 'create', return_value=response) as create:
        assert normalize_visual_feedback(ai_agent.analyze_image(FRAME, detailed=True)) == REVIEW
    options = create.call_args.kwargs
    prompt = options['messages'][0]['content'][0]['text']
    assert '头肩姿态' in prompt
    assert '不从姿态' in prompt
    assert options['max_tokens'] >= 300


def test_invalid_detailed_model_output_is_unavailable_instead_of_becoming_a_tag():
    for invalid in ('模型错误', '{"tags": ["画面清晰"]}', '[]'):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=invalid))])
        with patch.object(ai_agent.client.chat.completions, 'create', return_value=response):
            assert ai_agent.analyze_image(FRAME, detailed=True) == ''


def test_previous_database_revision_upgrades_without_losing_answer_or_visual_tags(camera_app):
    from sqlalchemy import text

    with camera_app.app_context():
        message = ChatMessage.query.first()
        message.visual_context = '["光线偏暗"]'
        db.session.commit()
        db.session.execute(text('ALTER TABLE chat_messages DROP COLUMN visual_image'))
        db.session.execute(text('ALTER TABLE chat_messages DROP COLUMN visual_captured_at'))
        db.session.commit()
        db.session.remove()
    runner = camera_app.test_cli_runner()
    stamped = runner.invoke(args=['db', 'stamp', '20261006_account_links'])
    assert stamped.exit_code == 0, stamped.output
    upgraded = runner.invoke(args=['bootstrap-db'])
    assert upgraded.exit_code == 0, upgraded.output
    checked = runner.invoke(args=['db', 'check'])
    assert checked.exit_code == 0, checked.output
    with camera_app.app_context():
        message = ChatMessage.query.first()
        assert message.content == '请解释事务。'
        assert message.visual_context == '["光线偏暗"]'
        assert message.visual_image is None
        assert message.visual_captured_at is None
