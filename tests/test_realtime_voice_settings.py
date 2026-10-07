"""Admin settings and runtime enforcement of the realtime voice switch."""

import json
import threading
from unittest.mock import patch

import pytest
import websocket
from flask import session
from werkzeug.serving import make_server

from tests.test_realtime_voice import voice_app, FakeProvider
from app import db
from app.api.realtime import authorize_browser
from app.models import ChatMessage, InterviewSession, SystemConfig, User
from app.services.realtime_voice import ASR_PREFIX


@pytest.fixture
def settings_app(voice_app):
    with voice_app.app_context():
        admin = User(username='settings_admin', role='admin')
        teacher = User(username='settings_teacher', role='teacher')
        db.session.add_all([admin, teacher])
        db.session.commit()
        voice_app.config['TEST_ADMIN_ID'] = admin.id
        voice_app.config['TEST_TEACHER_ID'] = teacher.id
    return voice_app


def authenticated_client(app, user_id):
    client = app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = str(user_id)
        state['_csrf_token'] = 'csrf'
    return client


def test_switch_persists_and_controls_room_independently_of_tts(settings_app):
    admin = authenticated_client(settings_app, settings_app.config['TEST_ADMIN_ID'])
    owner = authenticated_client(settings_app, 1)
    assert '启用实时语音交互' in admin.get('/admin/settings').get_data(as_text=True)
    assert 'id="record-btn"' in owner.get('/interview/room/1').get_data(as_text=True)
    assert admin.post('/admin/settings', data={'enable_tts': 'on'}).status_code == 302
    with settings_app.app_context():
        assert SystemConfig.get('enable_realtime_voice') == 'false'
        assert SystemConfig.get('enable_tts') == 'true'
    html = owner.get('/interview/room/1').get_data(as_text=True)
    assert 'id="record-btn"' not in html and 'id="realtime-toggle"' not in html
    assert 'id="msg-input"' in html
    assert admin.post('/admin/settings', data={'enable_realtime_voice': 'on'}).status_code == 302
    with settings_app.test_request_context('/', headers={'Origin': 'http://localhost'}):
        session['_user_id'] = '1'
        session['_csrf_token'] = 'csrf'
        assert SystemConfig.get('enable_tts') == 'false'
        assert SystemConfig.get('enable_realtime_voice') == 'true'
        assert authorize_browser(1, {'csrf_token': 'csrf'}) is None
    assert 'id="record-btn"' in owner.get('/interview/room/1').get_data(as_text=True)


@pytest.mark.parametrize('role', ['student', 'teacher'])
def test_only_admin_can_change_switch(settings_app, role):
    user_id = 1 if role == 'student' else settings_app.config['TEST_TEACHER_ID']
    client = authenticated_client(settings_app, user_id)
    assert client.post('/admin/settings', data={}).status_code == 403
    with settings_app.app_context():
        assert SystemConfig.get('enable_realtime_voice') is None


@pytest.mark.parametrize('pending_audio', [False, True])
def test_shutdown_closes_live_socket_saves_last_answer_and_blocks_reconnect(settings_app, pending_audio):
    provider = FakeProvider(deferred=True)
    server = make_server('127.0.0.1', 0, settings_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    owner = authenticated_client(settings_app, 1)
    cookie = owner.get_cookie(settings_app.config['SESSION_COOKIE_NAME'])
    admin = authenticated_client(settings_app, settings_app.config['TEST_ADMIN_ID'])
    ws = None
    try:
        with patch('app.api.realtime.connect_provider', return_value=provider) as connect:
            url = base.replace('http:', 'ws:') + '/api/interview/1/realtime'
            ws = websocket.create_connection(url, cookie=f'{cookie.key}={cookie.value}', origin=base, timeout=6)
            ws.send(json.dumps({'type': 'connect', 'csrf_token': 'csrf'}))
            while json.loads(ws.recv()).get('type') != 'ready':
                pass
            if pending_audio:
                ws.send_binary(b'\0' * 640)
                while json.loads(ws.recv()).get('type') != ASR_PREFIX + 'delta':
                    pass
            assert admin.post('/admin/settings', data={'enable_tts': 'on'}).status_code == 302
            received = []
            while True:
                event = json.loads(ws.recv())
                received.append(event)
                if event.get('type') == 'session.closed':
                    break
            kinds = [event['type'] for event in received]
            assert 'feature.disabled' in kinds
            if pending_audio:
                assert kinds.index('transcript.saved') < kinds.index('session.closed')
            with settings_app.app_context():
                if pending_audio:
                    assert ChatMessage.query.filter_by(sender='user').one().content == '我的项目使用数据库事务。'
                else:
                    assert ChatMessage.query.filter_by(sender='user').count() == 0
                assert db.session.get(InterviewSession, 1).status == 'ongoing'
            ws.close()
            ws = websocket.create_connection(url, cookie=f'{cookie.key}={cookie.value}', origin=base, timeout=5)
            ws.send(json.dumps({'type': 'connect', 'csrf_token': 'csrf'}))
            denied = json.loads(ws.recv())
            assert denied['type'] == 'error' and '管理员已关闭实时语音交互' in denied['message']
            assert connect.call_count == 1
    finally:
        if ws:
            ws.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
