"""Local waveform handling and upload endpoint contracts, without cloud calls."""

from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import shutil
import subprocess

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import User
from app.services.ai_agent import AIServiceError, transcribe_audio
from app.services import local_asr


def test_local_recognizer_decodes_mono_pcm_and_chunks_long_audio(tmp_path):
    path = tmp_path / 'answer.wav'
    Sine(440).to_audio_segment(duration=30500).set_channels(2).export(path, format='wav')
    streams = [Mock(result=SimpleNamespace(text='<|zh|><|NEUTRAL|>我用 Python。')),
               Mock(result=SimpleNamespace(text='也用 SQL。'))]
    recognizer = Mock()
    recognizer.create_stream.side_effect = streams
    with patch.object(local_asr, '_get_recognizer', return_value=recognizer):
        text = local_asr.transcribe_local_audio(str(path))
    assert text == '我用 Python。 也用 SQL。'
    assert recognizer.decode_stream.call_count == 2
    for stream, expected_length in zip(streams, (480000, 8000)):
        rate, samples = stream.accept_waveform.call_args.args
        assert rate == 16000
        assert samples.ndim == 1
        assert len(samples) == expected_length
        assert samples.dtype.name == 'float32'
        assert -1 <= samples.min() <= samples.max() <= 1


def test_silence_does_not_load_model_or_invent_transcript(tmp_path):
    path = tmp_path / 'silence.wav'
    AudioSegment.silent(duration=1000).export(path, format='wav')
    with patch.object(local_asr, '_get_recognizer') as load:
        assert local_asr.transcribe_local_audio(str(path)) == ''
    load.assert_not_called()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='browser audio decoding requires ffmpeg')
@pytest.mark.parametrize('format, codec', [('webm', 'libopus'), ('mp4', 'aac')])
def test_browser_recording_formats_are_decoded(tmp_path, format, codec):
    # The endpoint uses a .webm temp name even when the browser records MP4.
    path = tmp_path / 'recording.webm'
    Sine(440).to_audio_segment(duration=1000).export(path, format=format, codec=codec)
    stream = Mock(result=SimpleNamespace(text='你好'))
    recognizer = Mock()
    recognizer.create_stream.return_value = stream
    with patch.object(local_asr, '_get_recognizer', return_value=recognizer):
        assert transcribe_audio(str(path)) == '你好'
    rate, samples = stream.accept_waveform.call_args.args
    assert rate == 16000
    assert samples.ndim == 1
    assert 15000 < len(samples) < 18000


def test_missing_decoder_is_reported_as_service_configuration_error(tmp_path, caplog):
    path = tmp_path / 'recording.webm'
    path.write_bytes(b'webm')
    with patch.object(local_asr.subprocess, 'run', side_effect=FileNotFoundError('ffmpeg')):
        with pytest.raises(AIServiceError, match='服务尚未就绪'):
            transcribe_audio(str(path))
    assert 'ffmpeg/ffprobe' in caplog.text
    assert 'Traceback' in caplog.text


def test_decode_child_does_not_inherit_nix_libraries(tmp_path, monkeypatch):
    monkeypatch.setenv('LD_LIBRARY_PATH', '/nix/store/python-runtime/lib')
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    decoded = subprocess.CompletedProcess([], 0, stdout=b'\0\0' * 16000, stderr=b'')
    with patch.object(local_asr.subprocess, 'run', return_value=decoded) as run:
        assert local_asr.transcribe_local_audio(str(tmp_path / 'recording.webm')) == ''
    assert 'LD_LIBRARY_PATH' not in run.call_args.kwargs['env']
    assert run.call_args.kwargs['env']['PATH'] == '/usr/bin:/bin'
    assert os.environ['LD_LIBRARY_PATH'] == '/nix/store/python-runtime/lib'


def test_model_is_loaded_once_from_local_files(tmp_path):
    (tmp_path / 'model.int8.onnx').touch()
    (tmp_path / 'tokens.txt').touch()
    with patch.object(local_asr, '_recognizer', None), patch.object(
        Config, 'ASR_MODEL_DIR', str(tmp_path),
    ), patch('sherpa_onnx.OfflineRecognizer.from_sense_voice') as load:
        first = local_asr._get_recognizer()
        assert local_asr._get_recognizer() is first
        load.assert_called_once()
        assert load.call_args.kwargs['provider'] == 'cpu'
        assert load.call_args.kwargs['model'] == str(tmp_path / 'model.int8.onnx')


def test_missing_model_is_reported_without_network_download(tmp_path):
    with patch.object(local_asr, '_recognizer', None), patch.object(
        Config, 'ASR_MODEL_DIR', str(tmp_path),
    ):
        with pytest.raises(RuntimeError, match='prepare_local_asr'):
            local_asr._get_recognizer()


@pytest.fixture
def transcribe_client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "test.db"}')
    monkeypatch.setattr(Config, 'CSRF_ENABLED', False)
    monkeypatch.setattr(Config, 'SESSION_COOKIE_SECURE', False)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        user = User(username='local-asr-test', role='student')
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    with app.test_client() as client:
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True
        yield client


@pytest.mark.parametrize('text, expected', [
    ('我用 Python。', {'status': 'success', 'text': '我用 Python。'}),
    ('', {'status': 'empty'}),
])
def test_transcribe_upload_returns_text_and_deletes_recording(transcribe_client, text, expected):
    uploaded = []

    def recognize(path):
        assert Path(path).read_bytes() == b'browser-webm'
        uploaded.append(path)
        return text

    with patch('app.api.interview.transcribe_audio', side_effect=recognize):
        response = transcribe_client.post('/api/interview/transcribe', data={
            'audio': (BytesIO(b'browser-webm'), 'recording.webm'),
        })
    assert response.status_code == 200
    assert response.get_json() == expected
    assert uploaded and all(not Path(path).exists() for path in uploaded)


def test_unavailable_local_asr_returns_error_and_cleans_upload(transcribe_client):
    uploaded = []

    def unavailable(path):
        uploaded.append(path)
        raise AIServiceError('语音识别暂时不可用')

    with patch('app.api.interview.transcribe_audio', side_effect=unavailable):
        response = transcribe_client.post('/api/interview/transcribe', data={
            'audio': (BytesIO(b'browser-webm'), 'recording.webm'),
        })
    assert response.status_code == 503
    assert response.get_json()['status'] == 'error'
    assert response.get_json()['code'] == 'asr_unavailable'
    assert all(not Path(path).exists() for path in uploaded)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='browser audio decoding requires ffmpeg')
def test_corrupt_recording_returns_400_instead_of_service_unavailable(transcribe_client, caplog):
    with patch.object(local_asr, '_get_recognizer') as load:
        response = transcribe_client.post('/api/interview/transcribe', data={
            'audio': (BytesIO(b'incomplete-browser-recording'), 'recording.webm'),
        })
    assert response.status_code == 400
    assert response.get_json()['code'] == 'invalid_audio'
    assert '重新' in response.get_json()['error']
    assert '录音解码失败' in caplog.text
    load.assert_not_called()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='browser audio decoding requires ffmpeg')
def test_missing_model_returns_actionable_error_and_logs_cause(transcribe_client, tmp_path, caplog):
    audio = BytesIO()
    Sine(440).to_audio_segment(duration=1000).export(audio, format='wav')
    with patch.object(local_asr, '_recognizer', None), patch.object(Config, 'ASR_MODEL_DIR', str(tmp_path)):
        response = transcribe_client.post('/api/interview/transcribe', data={
            'audio': (BytesIO(audio.getvalue()), 'recording.wav'),
        })
    assert response.status_code == 503
    assert response.get_json()['code'] == 'asr_unavailable'
    assert '管理员' in response.get_json()['error']
    assert 'prepare_local_asr.py' in caplog.text
    assert 'Traceback' in caplog.text
