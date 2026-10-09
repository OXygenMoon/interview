"""Duplex protocol, authorization and a real browser/server WebSocket bridge."""

import base64
import json
import os
import queue
import threading
import wave
from unittest.mock import patch

import pytest
import websocket
from flask import session
from werkzeug.serving import make_server

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import ChatMessage, InterviewSession, SystemConfig, User
from app.api.realtime import authorize_browser, read_upstream
from app.services.realtime_voice import ASR_PREFIX, TranscriptRecorder, session_payload
from app.services.tts_service import _text_to_speech_v3


@pytest.fixture
def voice_app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "voice.db"}')
    app = create_app()
    app.config.update(TESTING=True, VOLC_API_KEY='server-only-test-secret', SESSION_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        db.session.add_all([User(id=1, username='owner', role='student'), User(id=2, username='other', role='student')])
        db.session.add(InterviewSession(id=1, user_id=1, status='ongoing', target_role='后端开发', difficulty='标准模式', round=2))
        db.session.add(ChatMessage(session_id=1, sender='ai', content='请介绍你的项目。'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()


def test_provider_config_restores_pairs_and_uses_pcm16(voice_app):
    with voice_app.app_context():
        interview = db.session.get(InterviewSession, 1)
        history = [ChatMessage(sender='ai', content='开场', generation_status='completed'),
                   ChatMessage(sender='user', content='使用事务', generation_status='completed'),
                   ChatMessage(sender='ai', content='解释回滚', generation_status='completed'),
                   ChatMessage(sender='user', content='未完成', generation_status='interrupted')]
        payload = session_payload(interview, history)
        assert payload['session']['model'] == '1.2.6.1'
        assert payload['session']['audio']['input']['format']['rate'] == 16000
        assert payload['session']['audio']['output']['format'] == {'type': 'pcm_s16le', 'rate': 24000}
        assert payload['extension']['dialog']['dialog_context'] == [
            {'role': 'user', 'text': '使用事务'}, {'role': 'assistant', 'text': '解释回滚'}]
        assert '专业复面' in payload['session']['instructions']
        assert voice_app.config['VOLC_API_KEY'] not in json.dumps(payload)


@pytest.mark.parametrize('difficulty', ['新手模式', '标准模式', '压力模式'])
@pytest.mark.parametrize('round_num', [1, 2, 3])
def test_realtime_interviewer_uses_the_same_student_standard(voice_app, difficulty, round_num):
    from app.services.interview_prompts import get_interaction_mode, get_round_scope
    from app.services.interview_coverage import required_questions

    with voice_app.app_context():
        interview = db.session.get(InterviewSession, 1)
        interview.difficulty = difficulty
        interview.round = round_num
        instructions = session_payload(interview, [])['session']['instructions']
        assert get_round_scope(round_num, difficulty) in instructions
        assert get_interaction_mode(difficulty) in instructions
        if difficulty != '压力模式':
            assert '中职学生' in instructions
        for question in required_questions(difficulty, round_num).values():
            assert question in instructions


@pytest.mark.parametrize('user,origin,token,status,allowed', [
    (None, 'http://localhost', 'csrf', 'ongoing', False),
    (2, 'http://localhost', 'csrf', 'ongoing', False),
    (1, 'https://evil.example', 'csrf', 'ongoing', False),
    (1, '', 'csrf', 'ongoing', False),
    (1, 'http://localhost', 'wrong', 'ongoing', False),
    (1, 'http://localhost', 'csrf', 'completed', False),
    (1, 'http://localhost', 'csrf', 'ongoing', True),
])
def test_socket_authorization(voice_app, user, origin, token, status, allowed):
    with voice_app.test_request_context('/', headers={'Origin': origin}):
        if user:
            session['_user_id'] = str(user)
        session['_csrf_token'] = 'csrf'
        db.session.get(InterviewSession, 1).status = status
        db.session.commit()
        assert (authorize_browser(1, {'csrf_token': token}) is None) is allowed


def test_transcripts_save_once_audio_replays_and_incomplete_text_is_not_scored(voice_app, tmp_path, monkeypatch):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    with voice_app.app_context():
        recorder = TranscriptRecorder(1)
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '事务'})
        completed = {'type': ASR_PREFIX + 'completed', 'item_id': 'q1', 'transcript': '事务保证原子性。', 'event_id': 'a1'}
        saved = recorder.handle(completed)
        assert saved['sender'] == 'user'
        assert recorder.handle(completed) is None
        assert recorder.handle({**completed, 'event_id': 'a2'}) is None
        recorder.handle({'type': 'response.output_text.delta', 'response_id': 'r1', 'delta': '怎么回滚？'})
        recorder.handle({'type': 'response.output_text.done', 'response_id': 'r1', 'text': '怎么回滚？'})
        recorder.handle({'type': 'response.output_audio.delta', 'response_id': 'r1', 'delta': base64.b64encode(b'\0' * 960).decode()})
        audio = recorder.handle({'type': 'response.output_audio.done', 'response_id': 'r1'})
        assert audio['type'] == 'audio.saved'
        with wave.open(str(tmp_path / audio['audio_url'].lstrip('/')), 'rb') as replay:
            assert replay.getframerate() == 24000
            assert replay.getsampwidth() == 2
            assert replay.readframes(480) == b'\0' * 960
        recorder.handle({'type': 'response.output_text.delta', 'response_id': 'r2', 'delta': '未完成的问题'})
        recorder.flush()
        assert ChatMessage.query.filter_by(sender='user').count() == 1
        assert ChatMessage.query.filter_by(content='怎么回滚？').count() == 1
        assert ChatMessage.query.filter_by(content='未完成的问题').one().generation_status == 'interrupted'


def test_audio_finishing_before_text_does_not_truncate_saved_question(voice_app, tmp_path, monkeypatch):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    with voice_app.app_context():
        recorder = TranscriptRecorder(1)
        recorder.handle({'type': 'response.output_text.delta', 'response_id': 'r1', 'delta': '如何保证'})
        recorder.handle({'type': 'response.output_audio.delta', 'response_id': 'r1', 'delta': base64.b64encode(b'\0' * 960).decode()})
        assert recorder.handle({'type': 'response.output_audio.done', 'response_id': 'r1'}) is None
        saved = recorder.handle({'type': 'response.output_text.done', 'response_id': 'r1', 'text': '如何保证事务原子性？'})
        assert saved['text'] == '如何保证事务原子性？'
        assert saved['audio_url']
        assert ChatMessage.query.filter_by(content='如何保证').count() == 0


def test_asr_snapshots_and_live_text_completion_replace_earlier_hypotheses(voice_app):
    with voice_app.app_context():
        recorder = TranscriptRecorder(1)
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '我的项目'})
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '我的项目使用事物'})
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '我的项目使用事务。'})
        saved = recorder.handle({'type': ASR_PREFIX + 'completed', 'item_id': 'q1', 'text': '我的项目使用数据库事务。'})
        assert saved['text'] == '我的项目使用数据库事务。'
        assert saved['item_id'] == 'q1'
        assert ChatMessage.query.filter_by(sender='user').one().content == saved['text']
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q2', 'delta': '下一句'})
        recorder.handle({'type': ASR_PREFIX + 'delta', 'item_id': 'q2', 'delta': '下一句修正'})
        fallback = recorder.handle({'type': ASR_PREFIX + 'completed', 'item_id': 'q2'})
        assert fallback['text'] == '下一句修正'
        assert fallback['item_id'] == 'q2'


class FakeProvider:
    def __init__(self, deferred=False, end_marker=False):
        self.events = queue.Queue()
        self.sent = []
        self.counter = 0
        self.deferred = deferred
        self.end_marker = end_marker

    def complete_user(self):
        if self.end_marker:
            self.events.put({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '我的项目使用数据库事务。'})
            self.events.put({'type': ASR_PREFIX + 'completed', 'item_id': 'q1'})
        else:
            self.events.put({'type': ASR_PREFIX + 'completed', 'item_id': 'q1', 'transcript': '我的项目使用数据库事务。'})

    def settimeout(self, timeout):
        pass

    def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        if event['type'] == 'session.create':
            self.events.put({'type': 'session.created', 'session': {'id': 'provider-dialog'}})
        elif event['type'] == 'input_audio_buffer.append':
            if self.deferred:
                self.events.put({'type': ASR_PREFIX + 'delta', 'item_id': 'q1', 'delta': '我的项目'})
                return
            self.complete_user()
            self.events.put({'type': 'response.output_text.delta', 'response_id': 'r1', 'delta': '请解释事务回滚。'})
            self.events.put({'type': 'response.output_text.done', 'response_id': 'r1', 'text': '请解释事务回滚。'})
            self.events.put({'type': 'response.output_audio.delta', 'response_id': 'r1', 'delta': base64.b64encode(b'\0' * 960).decode()})
            self.events.put({'type': 'response.output_audio.done', 'response_id': 'r1'})
        elif event['type'] == 'input_audio_buffer.commit' and self.deferred:
            self.complete_user()
        elif event['type'] == 'session.close':
            self.events.put({'type': 'session.closed'})

    def recv(self):
        try:
            event = self.events.get(timeout=0.1)
        except queue.Empty:
            raise websocket.WebSocketTimeoutException()
        self.counter += 1
        return json.dumps({**event, 'event_id': f'fake-{self.counter}'})

    def close(self):
        pass


def test_live_audio_chunks_without_response_id_attach_to_greeting_and_reply(voice_app, tmp_path, monkeypatch):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    provider = FakeProvider()
    audio = base64.b64encode(b'\0' * 960).decode()
    for event in [
        {'type': 'response.output_audio.started', 'response_id': 'g1'},
        {'type': 'response.output_audio.delta', 'delta': audio},
        {'type': 'response.output_audio.done', 'response_id': 'g1'},
        {'type': 'response.output_text.delta', 'response_id': 'r1', 'delta': '怎样回滚？'},
        {'type': 'response.output_audio.started', 'response_id': ''},
        {'type': 'response.output_audio.delta', 'delta': audio},
        {'type': 'response.output_text.done', 'response_id': 'r1', 'text': '怎样回滚？'},
        {'type': 'response.output_audio.done', 'response_id': 'r1'},
        {'type': 'session.closed'},
    ]:
        provider.events.put(event)
    events = queue.Queue()
    read_upstream(provider, events, threading.Event())
    with voice_app.app_context():
        recorder = TranscriptRecorder(1)
        greeting = ChatMessage.query.filter_by(session_id=1, sender='ai').one()
        recorder.welcome_message_id = greeting.id
        saved = []
        while not events.empty():
            result = recorder.handle(events.get_nowait())
            if result:
                saved.append(result)
        assert [event['response_id'] for event in saved if event['type'] == 'audio.saved'] == ['g1', 'r1']
        messages = ChatMessage.query.order_by(ChatMessage.id).all()
        assert len(messages) == 2
        assert all(message.audio_url for message in messages)
        for message in messages:
            with wave.open(str(tmp_path / message.audio_url.lstrip('/')), 'rb') as replay:
                assert replay.readframes(480) == b'\0' * 960


@pytest.mark.parametrize('deferred', [False, True])
@pytest.mark.parametrize('end_marker', [False, True])
def test_real_websocket_bridge_saves_before_close_and_never_leaks_key(voice_app, tmp_path, monkeypatch, deferred, end_marker):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    provider = FakeProvider(deferred=deferred, end_marker=end_marker)
    server = make_server('127.0.0.1', 0, voice_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    with voice_app.test_client() as client:
        with client.session_transaction() as state:
            state['_user_id'] = '1'
            state['_csrf_token'] = 'csrf'
        cookie = client.get_cookie(voice_app.config['SESSION_COOKIE_NAME'])
    ws = None
    try:
        with patch('app.api.realtime.connect_provider', return_value=provider):
            ws = websocket.create_connection(base.replace('http:', 'ws:') + '/api/interview/1/realtime',
                                               cookie=f'{cookie.key}={cookie.value}', origin=base, timeout=5)
            ws.send(json.dumps({'type': 'connect', 'csrf_token': 'csrf'}))
            while json.loads(ws.recv()).get('type') != 'ready':
                pass
            ws.send_binary(b'\0' * 640)
            # This fixture uploads one frame rather than a continuous mic.
            # Muting makes the absence of subsequent frames explicit.
            ws.send(json.dumps({'type': 'input_audio_mute.commit'}))
            received = []
            while True:
                event = json.loads(ws.recv())
                received.append(event)
                if event.get('type') == ('audio.saved' if not deferred else ASR_PREFIX + 'delta'):
                    break
            ws.send(json.dumps({'type': 'input_audio_mute.commit', 'secret': 'client-config-is-ignored'}))
            ws.send(json.dumps({'type': 'session.close'}))
            while True:
                event = json.loads(ws.recv())
                received.append(event)
                if event.get('type') == 'session.closed':
                    break
            assert 'server-only-test-secret' not in json.dumps(received)
            assert 'client-config-is-ignored' not in json.dumps(provider.sent)
            completed = next(e for e in received if e['type'] == ASR_PREFIX + 'completed')
            assert completed['transcript'] == '我的项目使用数据库事务。'
            saved = next(e for e in received if e['type'] == 'transcript.saved' and e['sender'] == 'user')
            assert saved['item_id'] == 'q1'
            assert base64.b64decode(next(e['audio'] for e in provider.sent if e['type'] == 'input_audio_buffer.append')) == b'\0' * 640
            with voice_app.app_context():
                assert ChatMessage.query.filter_by(sender='user').one().content == '我的项目使用数据库事务。'
                if not deferred:
                    assert ChatMessage.query.filter_by(content='请解释事务回滚。').one().audio_url
    finally:
        if ws:
            ws.close()
        server.shutdown()
        thread.join(timeout=3)


@pytest.mark.parametrize('voice,resource', [
    ('zh_male_dayi_saturn_bigtts', 'seed-tts-1.0'),
    ('zh_female_vv_uranus_bigtts', 'seed-tts-2.0'),
])
def test_new_key_tts_joins_streamed_audio_chunks(tmp_path, monkeypatch, voice, resource):
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-key')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', '')
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [
        json.dumps({'code': 0, 'data': base64.b64encode(part).decode()}).encode()
        for part in (b'first-', b'second')
    ] + [b'{"code":20000000}']
    with patch('app.services.tts_service.requests.post', return_value=response) as post:
        name = _text_to_speech_v3('请介绍项目。', str(tmp_path), voice)
    assert (tmp_path / name).read_bytes() == b'first-second'
    assert post.call_args.kwargs['headers']['X-Api-Key'] == 'test-key'
    assert post.call_args.kwargs['headers']['X-Api-Resource-Id'] == resource
    assert post.call_args.args[0].endswith('/api/v3/tts/unidirectional')


def test_failed_tts_stream_removes_partial_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-key')
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [b'{"code":0,"data":"YWJj"}', b'{"code":45000010}']
    with patch('app.services.tts_service.requests.post', return_value=response):
        assert _text_to_speech_v3('请介绍项目。', str(tmp_path)) is None
    assert list(tmp_path.iterdir()) == []
