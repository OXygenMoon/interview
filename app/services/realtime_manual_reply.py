"""Recover a submitted voice turn when duplex EndASR produces no reply."""

import base64
import json
import queue
import tempfile
from pathlib import Path
import wave

from .. import db
from ..models import ChatMessage, InterviewSession
from .ai_agent import stream_ai_response
from .realtime_voice import MAX_AUDIO_BYTES, MAX_TEXT_CHARS
from .tts_service import _text_to_speech_realtime


def generate_manual_reply(app, interview_id, job_id, response_id, events, canceled, existing_text=''):
    def emit(kind, **fields):
        event = {'type': kind, 'response_id': response_id, '_manual_job': job_id, **fields}
        while not canceled.is_set():
            try:
                events.put(event, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    with app.app_context():
        try:
            interview = db.session.get(InterviewSession, interview_id)
            if not interview or interview.status != 'ongoing' or canceled.is_set():
                return
            text = existing_text
            if text:
                if not emit('response.output_text.done', text=text):
                    return
            if not text:
                history = ChatMessage.query.filter_by(session_id=interview_id, generation_status='completed').order_by(ChatMessage.id).all()
                context = json.dumps({
                    'position': interview.position_snapshot or {},
                    'resume': (interview.resume_snapshot or interview.user.resume_text or '')[:1500] if interview.use_resume else '',
                    'prior_round': interview.prior_round_summary or {},
                }, ensure_ascii=False)[:6000]
                for token in stream_ai_response(
                    history, target_role=interview.target_role, difficulty=interview.difficulty,
                    context_info=context, round_num=interview.round or 1,
                ):
                    if canceled.is_set():
                        return
                    text += token
                    if len(text) > MAX_TEXT_CHARS:
                        raise ValueError('Manual response exceeds limit')
                    if not emit('response.output_text.delta', delta=token):
                        return
                if not text.strip():
                    raise ValueError('Empty manual response')
                if not emit('response.output_text.done', text=text, model_name=app.config['LLM_MODEL_NAME']):
                    return
            # Use the activated Doubao voice resource and the selected speaker.
            # Temporary synthesis output is recorded through the normal relay.
            with tempfile.TemporaryDirectory(prefix='interview-manual-speech-') as directory:
                if canceled.is_set():
                    return
                filename = _text_to_speech_realtime(text, directory, interview.voice_type)
                if canceled.is_set():
                    return
                if filename:
                    with wave.open(str(Path(directory) / filename), 'rb') as audio:
                        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (24000, 1, 2):
                            raise ValueError('Invalid manual speech format')
                        if audio.getnframes() * 2 > MAX_AUDIO_BYTES:
                            raise ValueError('Manual speech exceeds limit')
                        while chunk := audio.readframes(12000):
                            if not emit('response.output_audio.delta', delta=base64.b64encode(chunk).decode('ascii')):
                                return
                else:
                    emit('manual.audio_unavailable', message='语音播报暂不可用，面试官回复已显示为文字。')
            emit('response.output_audio.done')
        except Exception as error:
            app.logger.warning('Manual voice reply failed: %s', type(error).__name__)
            emit('manual.reply_failed', message='面试官回复生成失败，请再次点击“我说完了”重试。')
