"""Text replies use the activated speech model without microphone input."""

import base64
import json
import wave
from unittest.mock import patch

import pytest

from tests.test_realtime_voice import voice_app
from app import db
from app.config import Config
from app.models import ChatMessage, InterviewSession, SystemConfig
from app.services.tts_service import text_to_speech, text_to_speech_chunks


class SpeechProvider:
    def __init__(self, fail=False):
        self.sent = []
        self.events = []
        self.fail = fail
        self.closed = False

    def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        if event['type'] == 'session.create':
            self.events.append({'type': 'session.created'})
        elif event['type'] == 'speech_text_buffer.commit':
            self.events.extend([
                {'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'\0' * 4800).decode()},
                {'type': 'error' if self.fail else 'response.output_audio.done'},
            ])
        elif event['type'] == 'session.close':
            self.events.append({'type': 'session.closed'})

    def recv(self):
        return json.dumps(self.events.pop(0))

    def settimeout(self, timeout):
        pass

    def close(self):
        self.closed = True


@pytest.mark.parametrize('voice,expected', [
    ('zh_male_dayi_saturn_bigtts', 'zh_male_yunzhou_jupiter_bigtts'),
    ('zh_female_mizai_saturn_bigtts', 'zh_female_xiaohe_jupiter_bigtts'),
    ('zh_female_vv_uranus_bigtts', 'zh_female_vv_jupiter_bigtts'),
    ('zh_male_m191_uranus_bigtts', 'zh_male_m191_uranus_bigtts'),
    ('zh_male_taocheng_uranus_bigtts', 'zh_male_taocheng_uranus_bigtts'),
    ('zh_female_xiaohe_uranus_bigtts', 'zh_female_xiaohe_uranus_bigtts'),
    ('zh_female_cancan_uranus_bigtts', 'zh_female_cancan_uranus_bigtts'),
    ('zh_male_ruyayichen_uranus_bigtts', 'zh_male_ruyayichen_uranus_bigtts'),
])
def test_selected_voice_reads_entire_reply_once_without_mic(tmp_path, monkeypatch, voice, expected):
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-secret')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', '')
    monkeypatch.setattr(Config, 'VOLC_REALTIME_VOICE', 'zh_male_yunzhou_jupiter_bigtts')
    provider = SpeechProvider()
    reply = '请介绍一下你的项目。你如何保证数据库事务的一致性？'
    with patch('app.services.tts_service.connect_provider', return_value=provider):
        chunks = list(text_to_speech_chunks(reply, str(tmp_path), voice))
    assert len(chunks) == 1
    with wave.open(str(tmp_path / chunks[0][1]), 'rb') as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        assert audio.readframes(2400) == b'\0' * 4800
    types = [event['type'] for event in provider.sent]
    assert types == ['session.create', 'input_audio_mute.commit', 'speech_text_buffer.commit', 'session.close']
    assert provider.sent[0]['session']['audio']['output']['voice'] == expected
    assert provider.sent[2]['text'] == reply
    assert 'test-secret' not in json.dumps(provider.sent)
    assert provider.closed


def test_failed_speech_does_not_publish_partial_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-secret')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', '')
    provider = SpeechProvider(fail=True)
    with patch('app.services.tts_service.connect_provider', return_value=provider):
        assert text_to_speech('你好。', str(tmp_path)) is None
    assert list(tmp_path.iterdir()) == []
    assert provider.closed


@pytest.mark.parametrize('tts_enabled', [True, False])
def test_typed_chat_speech_is_independent_of_live_call_switch(voice_app, tmp_path, monkeypatch, tts_enabled):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-secret')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', '')
    with voice_app.app_context():
        SystemConfig.set('enable_realtime_voice', 'false')
        SystemConfig.set('enable_tts', 'true' if tts_enabled else 'false')
        db.session.get(InterviewSession, 1).voice_type = 'zh_female_cancan_uranus_bigtts'
        db.session.commit()
    client = voice_app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = '1'
    provider = SpeechProvider()
    with patch('app.services.ai_agent.stream_ai_response', return_value=iter(['请解释', '事务回滚。'])), patch(
        'app.services.tts_service.connect_provider', return_value=provider,
    ) as connect:
        response = client.post('/api/interview/1/chat', json={'message': '我使用数据库事务。'})
        events = [json.loads(part.removeprefix('data: ')) for part in response.get_data(as_text=True).split('\n\n') if part]
    assert response.status_code == 200
    assert ''.join(event['content'] for event in events if event['type'] == 'token') == '请解释事务回滚。'
    assert events[-1]['type'] == 'done'
    audio = [event for event in events if event['type'] == 'audio']
    assert bool(audio) is tts_enabled
    assert connect.call_count == int(tts_enabled)
    with voice_app.app_context():
        message = ChatMessage.query.filter_by(sender='ai', content='请解释事务回滚。').one()
        assert bool(message.audio_url) is tts_enabled
    if tts_enabled:
        assert audio[0]['url'].endswith('.wav')
        assert provider.sent[0]['session']['audio']['output']['voice'] == 'zh_female_cancan_uranus_bigtts'


def test_explicit_tts_resource_keeps_http_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-secret')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', 'seed-tts-2.0')
    with patch('app.services.tts_service._text_to_speech_v3', return_value='speech.mp3') as http, patch(
        'app.services.tts_service.connect_provider',
    ) as realtime:
        assert text_to_speech('你好。', str(tmp_path), 'zh_female_cancan_uranus_bigtts') == 'speech.mp3'
    http.assert_called_once()
    realtime.assert_not_called()
