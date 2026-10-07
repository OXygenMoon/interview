"""Selected frontend voices survive creation and reach the speech providers."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import db
from app.config import Config
from app.models import InterviewSession
from app.services.realtime_voice import session_payload
from app.services.tts_service import _text_to_speech_v3
from tests.test_realtime_voice import voice_app


@pytest.mark.parametrize('voice,expected_realtime', [
    ('zh_male_dayi_saturn_bigtts', 'zh_male_yunzhou_jupiter_bigtts'),
    ('zh_female_mizai_saturn_bigtts', 'zh_female_xiaohe_jupiter_bigtts'),
    ('zh_female_vv_uranus_bigtts', 'zh_female_vv_jupiter_bigtts'),
    ('zh_male_m191_uranus_bigtts', 'zh_male_m191_uranus_bigtts'),
    ('zh_male_taocheng_uranus_bigtts', 'zh_male_taocheng_uranus_bigtts'),
    ('zh_female_xiaohe_uranus_bigtts', 'zh_female_xiaohe_uranus_bigtts'),
    ('zh_female_cancan_uranus_bigtts', 'zh_female_cancan_uranus_bigtts'),
    ('zh_male_ruyayichen_uranus_bigtts', 'zh_male_ruyayichen_uranus_bigtts'),
    ('unlisted-voice', 'zh_male_yunzhou_jupiter_bigtts'),
])
def test_selected_voice_reaches_realtime_and_tts(voice_app, tmp_path, monkeypatch, voice, expected_realtime):
    voice_app.config['VOLC_REALTIME_VOICE'] = 'zh_male_yunzhou_jupiter_bigtts'
    client = voice_app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = '2'
    result = client.post('/api/interview/create', data={
        'target_role': '后端工程师', 'voice_type': voice,
    })
    assert result.status_code == 200
    with voice_app.app_context():
        interview = db.session.get(InterviewSession, result.json['session_id'])
        saved_voice = interview.voice_type
        assert saved_voice == (voice if voice != 'unlisted-voice' else Config.VOLC_DEFAULT_VOICE)
        payload = session_payload(interview, [])
        assert payload['session']['audio']['output']['voice'] == expected_realtime

    monkeypatch.setattr(Config, 'VOLC_API_KEY', 'test-key')
    monkeypatch.setattr(Config, 'VOLC_TTS_RESOURCE_ID', '')
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [
        json.dumps({'code': 0, 'data': 'YWJj'}).encode(), b'{"code":20000000}',
    ]
    with patch('app.services.tts_service.requests.post', return_value=response) as post:
        filename = _text_to_speech_v3('请介绍你的项目。', str(tmp_path), saved_voice)
    assert (tmp_path / filename).read_bytes() == b'abc'
    assert post.call_args.kwargs['json']['req_params']['speaker'] == saved_voice
    expected_resource = 'seed-tts-2.0' if '_uranus_' in saved_voice else 'seed-tts-1.0'
    assert post.call_args.kwargs['headers']['X-Api-Resource-Id'] == expected_resource
