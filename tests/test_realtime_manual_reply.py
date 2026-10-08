"""Manual recovery reuses interview context, selected Doubao voice and cancellation."""
import queue
import threading
import wave
from pathlib import Path

from tests.test_realtime_voice import voice_app
from app import db
from app.models import ChatMessage
from app.services.realtime_manual_reply import generate_manual_reply


def test_worker_synthesizes_existing_provider_reply_without_asking_another_question(voice_app, monkeypatch):
    calls = []

    def speech(text, directory, voice):
        calls.append(text)
        with wave.open(str(Path(directory) / 'test.wav'), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(bytes(4800))
        return 'test.wav'

    monkeypatch.setattr('app.services.realtime_manual_reply._text_to_speech_realtime', speech)
    monkeypatch.setattr('app.services.realtime_manual_reply.stream_ai_response', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not regenerate')))
    events = queue.Queue()
    generate_manual_reply(voice_app, 1, 'job', 'r1', events, threading.Event(), '为什么使用数据库事务？')
    received = list(events.queue)
    assert calls == ['为什么使用数据库事务？']
    assert [event['type'] for event in received] == ['response.output_text.done', 'response.output_audio.delta', 'response.output_audio.done']
    assert all(event['response_id'] == 'r1' and event['_manual_job'] == 'job' for event in received)


def test_failed_or_canceled_generation_does_not_publish_a_complete_reply(voice_app, monkeypatch):
    with voice_app.app_context():
        db.session.add(ChatMessage(session_id=1, sender='user', content='我使用数据库事务。'))
        db.session.commit()
    monkeypatch.setattr('app.services.realtime_manual_reply._text_to_speech_realtime', lambda *args: (_ for _ in ()).throw(AssertionError('must not synthesize')))
    events = queue.Queue()

    def failed(*args, **kwargs):
        yield '请解释'
        raise RuntimeError('model failed')

    monkeypatch.setattr('app.services.realtime_manual_reply.stream_ai_response', failed)
    generate_manual_reply(voice_app, 1, 'failed', 'r1', events, threading.Event())
    assert [event['type'] for event in events.queue] == ['response.output_text.delta', 'manual.reply_failed']
    canceled = threading.Event()
    events = queue.Queue()

    def interrupted(*args, **kwargs):
        yield '请解释'
        canceled.set()
        yield '回滚'

    monkeypatch.setattr('app.services.realtime_manual_reply.stream_ai_response', interrupted)
    generate_manual_reply(voice_app, 1, 'canceled', 'r2', events, canceled)
    assert [event['type'] for event in events.queue] == ['response.output_text.delta']
