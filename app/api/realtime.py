"""Authenticated browser-to-Doubao bridge; provider credentials never reach JS."""

import base64
import hmac
import json
import queue
import threading
import time
import uuid
from urllib.parse import urlsplit

from flask import abort, current_app, jsonify, request, session as browser_session
from flask_login import current_user, login_required
from flask_sock import Sock
from simple_websocket import ConnectionClosed
import websocket

from .. import db
from ..models import ChatMessage, InterviewSession, SystemConfig
from ..services.realtime_voice import (
    TranscriptRecorder, connect_provider, provider_error, session_payload,
)
from ..services.websocket_transport import prepare_websocket_transport, close_websocket_transport
from ..services.realtime_turns import ReplySilenceGate


def authorize_browser(interview_id, hello):
    if not current_user.is_authenticated:
        return '请先登录后再连接实时语音。'
    origin = urlsplit(request.headers.get('Origin', ''))
    if origin.scheme not in {'http', 'https'} or origin.netloc != request.host:
        return '语音连接来源无效，请刷新面试页面。'
    expected = browser_session.get('_csrf_token', '')
    supplied = hello.get('csrf_token', '')
    if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        return '语音连接验证失效，请刷新页面。'
    interview = db.session.get(InterviewSession, interview_id)
    if not interview or interview.user_id != current_user.id:
        return '无权连接此面试。'
    if interview.status != 'ongoing':
        return '该面试已结束，无法继续对话。'
    if SystemConfig.get('enable_realtime_voice', 'true') != 'true':
        return '管理员已关闭实时语音交互，请使用文字回答。'
    if not current_app.config.get('VOLC_API_KEY'):
        return '实时语音尚未配置 API Key，请联系管理员。'
    return None


def read_upstream(upstream, events, stopped):
    audio_response_id = None
    text_response_id = None
    try:
        while not stopped.is_set():
            try:
                raw = upstream.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                break
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Provider event too large')
            event = json.loads(raw)
            kind = event.get('type')
            if kind in {'response.output_text.delta', 'response.output_text.done'}:
                text_response_id = event.get('response_id') or text_response_id
            elif kind == 'response.output_audio.started':
                audio_response_id = event.get('response_id') or text_response_id
            elif kind in {'response.output_audio.delta', 'response.output_audio.done'}:
                # Live audio chunks may omit response_id even though started
                # and done identify the response. Bind them before recording
                # or forwarding so replay and interruption use the same ID.
                audio_response_id = event.get('response_id') or audio_response_id
                if audio_response_id:
                    event['response_id'] = audio_response_id
                if kind.endswith('.done'):
                    audio_response_id = None
            while not stopped.is_set():
                try:
                    events.put(event, timeout=0.5)
                    break
                except queue.Full:
                    continue
            if event.get('type') in {'session.closed', 'error'}:
                break
    except Exception:
        # Never propagate an exception string containing provider credentials.
        try:
            events.put({'type': 'bridge.error'}, timeout=0.5)
        except queue.Full:
            pass
    finally:
        stopped.set()


def relay(ws, interview_id, hello):
    error = authorize_browser(interview_id, hello)
    if error:
        ws.send(json.dumps({'type': 'error', 'message': error}, ensure_ascii=False))
        return
    upstream = None
    receiver = None
    events = queue.Queue(maxsize=256)
    stopped = threading.Event()
    recorder = TranscriptRecorder(interview_id)
    reply_gate = ReplySilenceGate()
    ready = False
    closing = False
    close_sent = False
    finish_input_at = None
    sent_audio = False
    deadline = time.monotonic() + 15
    last_status_check = time.monotonic()

    def begin_close():
        nonlocal closing, close_sent, finish_input_at, deadline
        if closing:
            return
        reply_gate.discard_pending()
        # Finalize the last microphone utterance before releasing the session.
        if sent_audio:
            upstream.send(json.dumps({'type': 'input_audio_mute.commit'}))
            upstream.send(json.dumps({'type': 'input_audio_buffer.commit'}))
        else:
            upstream.send(json.dumps({'type': 'session.close'}))
            close_sent = True
        closing = True
        finish_input_at = time.monotonic() + 1.5
        deadline = time.monotonic() + 3.5

    def forward(event):
        nonlocal close_sent
        saved = recorder.handle(event)
        if saved and saved.get('sender') == 'user':
            # completed may be only an end marker; include the final snapshot.
            event = {**event, 'transcript': saved['text']}
        ws.send(json.dumps(event, ensure_ascii=False))
        if saved:
            ws.send(json.dumps(saved, ensure_ascii=False))
        if closing and not close_sent and event.get('type') == 'conversation.item.input_audio_transcription.completed':
            upstream.send(json.dumps({'type': 'session.close'}))
            close_sent = True

    try:
        interview = db.session.get(InterviewSession, interview_id)
        history = ChatMessage.query.filter_by(session_id=interview_id).order_by(ChatMessage.id).all()
        payload = session_payload(interview, history)
        greeting = history[0].content if len(history) == 1 and history[0].sender == 'ai' else None
        if greeting:
            recorder.welcome_message_id = history[0].id
        upstream = connect_provider()
        upstream.send(json.dumps(payload, ensure_ascii=False))
        upstream.settimeout(1)
        receiver = threading.Thread(target=read_upstream, args=(upstream, events, stopped), daemon=True)
        receiver.start()
        while True:
            while not events.empty():
                event = events.get_nowait()
                kind = event.get('type')
                if kind in {'error', 'bridge.error'}:
                    code = (event.get('error') or {}).get('code')
                    current_app.logger.warning('Realtime provider error code=%s', code)
                    ws.send(json.dumps({'type': 'error', 'message': provider_error(code=code)}, ensure_ascii=False))
                    return
                if kind == 'session.created' and not closing:
                    ready = True
                    interview.llm_model = 'doubao-realtime-' + current_app.config['VOLC_REALTIME_MODEL']
                    db.session.commit()
                    upstream.send(json.dumps({'type': 'input_audio_unmute.commit'}))
                    ws.send(json.dumps({'type': 'ready', 'sample_rate': 24000}))
                    if greeting:
                        upstream.send(json.dumps({'type': 'speech_text_buffer.commit', 'text': greeting}, ensure_ascii=False))
                resumed = False
                if not closing:
                    if kind == 'conversation.item.input_audio_transcription.started':
                        resumed = reply_gate.speech_started(time.monotonic())
                    elif kind == 'conversation.item.input_audio_transcription.delta':
                        resumed = reply_gate.speech_progress(event, time.monotonic())
                if resumed:
                    upstream.send(json.dumps({'type': 'response.cancel', 'event_id': str(uuid.uuid4())}))
                if reply_gate.accept(event, time.monotonic()):
                    forward(event)
                if kind == 'session.closed':
                    return
            if not closing:
                for event in reply_gate.release(time.monotonic()):
                    forward(event)
            if stopped.is_set() and events.empty():
                break
            if (not ready or closing) and time.monotonic() > deadline:
                raise TimeoutError('Session acknowledgement timeout')
            if closing and not close_sent and time.monotonic() >= finish_input_at:
                upstream.send(json.dumps({'type': 'session.close'}))
                close_sent = True
            if time.monotonic() - last_status_check > 2:
                last_status_check = time.monotonic()
                # Release the read transaction so other requests' settings
                # updates are visible throughout a long-lived connection.
                db.session.remove()
                if not closing and SystemConfig.get('enable_realtime_voice', 'true') != 'true':
                    ws.send(json.dumps({'type': 'feature.disabled',
                                        'message': '管理员已关闭实时语音交互，请使用文字回答。'}, ensure_ascii=False))
                    begin_close()
                # Keep a socket from writing after another tab finishes/deletes.
                interview = db.session.get(InterviewSession, interview_id, populate_existing=True)
                if interview.status != 'ongoing' and not closing:
                    upstream.send(json.dumps({'type': 'session.close'}))
                    closing = True
                    close_sent = True
                    deadline = time.monotonic() + 3
            incoming = ws.receive(timeout=0.02)
            if incoming is None:
                continue
            if closing:
                continue
            if not ready:
                raise ValueError('Session is not ready')
            if isinstance(incoming, bytes):
                if len(incoming) != 640:
                    raise ValueError('Expected 20 ms mono PCM16 at 16 kHz')
                if reply_gate.manual_reply:
                    # Ignore microphone frames already in flight at submission.
                    continue
                if reply_gate.audio(incoming, time.monotonic()):
                    # A short pause is not permission to play an early reply.
                    upstream.send(json.dumps({'type': 'response.cancel', 'event_id': str(uuid.uuid4())}))
                upstream.send(json.dumps({'type': 'input_audio_buffer.append',
                                          'audio': base64.b64encode(incoming).decode('ascii')}))
                sent_audio = True
                continue
            if len(incoming) > 2000:
                raise ValueError('Control message too large')
            control = json.loads(incoming)
            kind = control.get('type')
            if kind not in {'session.close', 'response.cancel', 'input_audio_buffer.commit', 'input_audio_mute.commit',
                            'input_audio_unmute.commit'}:
                raise ValueError('Unsupported browser event')
            if kind == 'session.close':
                begin_close()
            elif kind == 'input_audio_buffer.commit':
                if reply_gate.manual_reply:
                    continue
                reply_gate.finish_turn()
                # Muting protects the submitted turn from ambient noise and
                # keeps the provider alive while microphone upload is paused.
                upstream.send(json.dumps({'type': 'input_audio_mute.commit', 'event_id': str(uuid.uuid4())}))
                if not reply_gate.pending:
                    upstream.send(json.dumps({'type': kind, 'event_id': str(uuid.uuid4())}))
                sent_audio = False
                ws.send(json.dumps({'type': 'turn.committed'}))
            else:
                if kind == 'input_audio_mute.commit':
                    reply_gate.muted = True
                    reply_gate.voiced_frames = 0
                elif kind == 'input_audio_unmute.commit':
                    if reply_gate.manual_reply:
                        reply_gate.resume_input()
                    reply_gate.muted = False
                    reply_gate.last_frame = None
                elif kind == 'response.cancel':
                    reply_gate.discard_pending()
                upstream.send(json.dumps({'type': kind, 'event_id': str(uuid.uuid4())}))
    except websocket.WebSocketBadStatusException as exc:
        current_app.logger.warning('Realtime handshake rejected: HTTP %s', exc.status_code)
        ws.send(json.dumps({'type': 'error', 'message': provider_error(status=exc.status_code)}, ensure_ascii=False))
    except ConnectionClosed:
        pass
    except Exception as exc:
        current_app.logger.warning('Realtime connection failed: %s', type(exc).__name__)
        try:
            ws.send(json.dumps({'type': 'error', 'message': provider_error()}, ensure_ascii=False))
        except ConnectionClosed:
            pass
    finally:
        if upstream:
            if not close_sent:
                try:
                    upstream.send(json.dumps({'type': 'session.close'}))
                    # Receive the close acknowledgement even if the browser left.
                    until = time.monotonic() + 2
                    while time.monotonic() < until and not stopped.is_set():
                        try:
                            event = events.get(timeout=0.1)
                            if reply_gate.accept(event, time.monotonic()):
                                recorder.handle(event)
                            if event.get('type') == 'session.closed':
                                break
                        except queue.Empty:
                            continue
                except Exception:
                    pass
            stopped.set()
            upstream.close()
        if receiver:
            receiver.join(timeout=1)
        # Process any queued final transcript before report generation starts.
        try:
            while not events.empty():
                event = events.get_nowait()
                if reply_gate.accept(event, time.monotonic()):
                    recorder.handle(event)
            recorder.flush()
        except Exception:
            db.session.rollback()
            current_app.logger.error('Realtime transcript persistence failed')


def init_realtime(app):
    app.config.setdefault('SOCK_SERVER_OPTIONS', {'ping_interval': 20, 'max_message_size': 8192})
    sock = Sock(app)

    @app.before_request
    def prepare_realtime_socket():
        if request.endpoint == 'realtime':
            prepare_websocket_transport(request.environ)

    @sock.route('/api/interview/<int:interview_id>/realtime')
    def realtime(ws, interview_id):
        try:
            raw = ws.receive(timeout=5)
            if not isinstance(raw, str) or len(raw) > 2000:
                return
            hello = json.loads(raw)
            if not isinstance(hello, dict) or hello.get('type') != 'connect':
                return
            relay(ws, interview_id, hello)
        except (ConnectionClosed, ValueError):
            return
        except Exception as exc:
            # A request has already upgraded: HTTP error/debug pages are no
            # longer valid here, including failures during authorization.
            current_app.logger.warning('Realtime socket failed: %s', type(exc).__name__)
            try:
                ws.send(json.dumps({'type': 'error', 'message': provider_error()}, ensure_ascii=False))
            except (ConnectionClosed, OSError):
                pass
        finally:
            close_websocket_transport(ws)

    @app.post('/api/interview/<int:interview_id>/realtime/frame/<int:message_id>')
    @login_required
    def realtime_frame(interview_id, message_id):
        from ..services.ai_agent import analyze_image
        from ..services.visual_review import decode_frame, normalize_visual_feedback, visual_record, UNAVAILABLE_COMMENT
        interview = db.session.get(InterviewSession, interview_id)
        if not interview or interview.user_id != current_user.id:
            abort(403)
        if interview.status != 'ongoing' or SystemConfig.get('enable_video', 'true') != 'true':
            abort(400)
        message = ChatMessage.query.filter_by(id=message_id, session_id=interview_id, sender='user').first_or_404()
        image = (request.get_json(silent=True) or {}).get('image')
        try:
            frame = decode_frame(image)
        except (ValueError, TypeError):
            abort(400)
        message.visual_image = frame
        message.visual_captured_at = message.timestamp
        db.session.commit()
        feedback = {'tags': [], 'comment': UNAVAILABLE_COMMENT}
        try:
            feedback = normalize_visual_feedback(analyze_image(image, detailed=True))
        except Exception:
            current_app.logger.warning('Realtime visual observation unavailable')
        message.visual_context = json.dumps(feedback, ensure_ascii=False)
        db.session.commit()
        return jsonify({'feedback': visual_record(message, interview)})
