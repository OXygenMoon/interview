"""Real Chromium sockets catch HTTP leakage and frame corruption at shutdown."""

import base64
import json
import os
import threading
import time
from unittest.mock import patch

import pytest
from werkzeug.serving import make_server

from tests.test_realtime_voice import voice_app, FakeProvider
from app import db
from app.api.realtime import authorize_browser
from app.models import ChatMessage
from app.services.websocket_transport import WebSocketTransport


pytestmark = pytest.mark.e2e


class ShortWrites:
    def __init__(self, sock):
        self.sock = sock

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def send(self, data, *args):
        written = self.sock.send(data[:997], *args)
        time.sleep(0.0001)
        return written

    def sendall(self, data, *args):
        while data:
            data = data[self.send(data, *args):]


@pytest.fixture
def transport_page(voice_app, browser_instance, tmp_path, monkeypatch):
    monkeypatch.setattr(voice_app, 'root_path', str(tmp_path))
    # Exercise heartbeat/data contention without a 20-second test wait.
    voice_app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 0.05, 'max_message_size': 8192}

    @voice_app.before_request
    def force_short_writes():
        from flask import request
        if request.endpoint == 'realtime':
            transport = request.environ['werkzeug.socket']
            if isinstance(transport, WebSocketTransport):
                transport.sock = ShortWrites(transport.sock)
            else:
                request.environ['werkzeug.socket'] = ShortWrites(transport)

    server = make_server('127.0.0.1', 0, voice_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    client = voice_app.test_client()
    with client.session_transaction() as state:
        state['_user_id'] = '1'
        state['_csrf_token'] = 'csrf'
    cookie = client.get_cookie(voice_app.config['SESSION_COOKIE_NAME'])
    context = browser_instance.new_context()
    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': base}])
    page = context.new_page()
    page.route('https://**/*', lambda route: route.fulfill(status=204, body=''))
    page.goto(base + '/healthz')
    cdp = context.new_cdp_session(page)
    cdp.send('Network.enable')
    frame_errors = []
    cdp.on('Network.webSocketFrameError', lambda event: frame_errors.append(event['errorMessage']))
    yield page, frame_errors
    context.close()
    server.shutdown()
    thread.join(timeout=3)


@pytest.mark.parametrize('failure', ['provider', 'authorization', 'exception'])
def test_failed_sessions_close_without_http_frames(transport_page, failure):
    page, frame_errors = transport_page
    # Trigger a provider error after the ready frame, matching a conversation
    # interrupted from the server while the microphone is still uploading.
    def failed_provider():
        provider = FakeProvider()
        original_send = provider.send

        def send(raw):
            if json.loads(raw)['type'] == 'input_audio_buffer.append':
                provider.events.put({'type': 'error', 'error': {'code': 'test-failure'}})
            else:
                original_send(raw)

        provider.send = send
        return provider

    with patch('app.api.realtime.connect_provider', side_effect=failed_provider), patch(
        'app.api.realtime.authorize_browser',
        side_effect=RuntimeError('test failure') if failure == 'exception' else None,
        wraps=None if failure == 'exception' else authorize_browser,
    ):
        for _ in range(3):
            result = page.evaluate('''token => new Promise(resolve => {
                const result = {errors: 0, events: []};
                const ws = new WebSocket(location.origin.replace('http', 'ws') + '/api/interview/1/realtime');
                const timer = setTimeout(() => { ws.close(); resolve({...result, timeout:true}); }, 6000);
                ws.onopen = () => ws.send(JSON.stringify({type:'connect', csrf_token:token}));
                ws.onmessage = ({data}) => {
                    const event = JSON.parse(data);
                    result.events.push(event.type);
                    if (event.type === 'ready') ws.send(new Uint8Array(640));
                    // Old clients send session.close in response to an error.
                    if (event.type === 'error' && ws.readyState === WebSocket.OPEN)
                        ws.send(JSON.stringify({type:'session.close'}));
                };
                ws.onerror = () => result.errors++;
                ws.onclose = event => { clearTimeout(timer); resolve({...result, code:event.code}); };
            })''', 'invalid' if failure == 'authorization' else 'csrf')
            assert result.get('timeout') is None
            assert 'error' in result['events']
            assert result['errors'] == 0
            assert result['code'] == 1000
    assert frame_errors == []


def test_audio_and_heartbeats_survive_short_socket_writes(voice_app, transport_page):
    page, frame_errors = transport_page
    provider = FakeProvider(deferred=True)
    original_send = provider.send
    audio = base64.b64encode(os.urandom(24000)).decode()

    def send(raw):
        if json.loads(raw)['type'] == 'input_audio_buffer.append':
            provider.events.put({'type': 'response.output_audio.delta', 'response_id': 'stress', 'delta': audio})
        else:
            original_send(raw)

    provider.send = send
    with patch('app.api.realtime.connect_provider', return_value=provider):
        result = page.evaluate('''() => new Promise(resolve => {
            const result = {errors:0, chunks:0, bytes:0, saved:false};
            const ws = new WebSocket(location.origin.replace('http','ws') + '/api/interview/1/realtime');
            let upload;
            const timer = setTimeout(() => {clearInterval(upload);ws.close();resolve({...result,timeout:true});},12000);
            ws.onopen = () => ws.send(JSON.stringify({type:'connect',csrf_token:'csrf'}));
            ws.onmessage = ({data}) => {
                const event = JSON.parse(data);
                if (event.type === 'ready') upload = setInterval(() => ws.send(new Uint8Array(640)),20);
                if (event.type === 'response.output_audio.delta') {
                    result.chunks++; result.bytes += atob(event.delta).length;
                    if (result.chunks === 60) {
                        clearInterval(upload); ws.send(JSON.stringify({type:'session.close'}));
                    }
                }
                if (event.type === 'transcript.saved') result.saved = true;
            };
            ws.onerror = () => result.errors++;
            ws.onclose = event => {clearTimeout(timer);clearInterval(upload);resolve({...result,code:event.code});};
        })''')
    assert result.get('timeout') is None
    assert result['errors'] == 0 and result['code'] == 1000
    assert result['chunks'] >= 60 and result['bytes'] == result['chunks'] * 24000
    assert result['saved'] is True
    assert frame_errors == []
    with voice_app.app_context():
        assert ChatMessage.query.filter_by(sender='user').one().content == '我的项目使用数据库事务。'


def test_replies_wait_for_three_seconds_and_short_pause_cancels_unheard_reply(voice_app, transport_page):
    page, frame_errors = transport_page
    provider = FakeProvider(deferred=True)
    original_send = provider.send
    turn = 0
    talking = False

    def send(raw):
        nonlocal turn, talking
        event = json.loads(raw)
        if event['type'] != 'input_audio_buffer.append':
            original_send(raw)
            return
        provider.sent.append(event)
        voiced = base64.b64decode(event['audio'])[:2] != b'\0\0'
        if voiced and not talking:
            turn += 1
            talking = True
            provider.events.put({'type': 'conversation.item.input_audio_transcription.started', 'item_id': f'q{turn}'})
            provider.events.put({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': f'q{turn}', 'delta': f'回答{turn}'})
        elif talking and not voiced:
            talking = False
            provider.events.put({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': f'q{turn}', 'text': f'回答{turn}'})
            for kind, data in [
                ('response.output_text.delta', {'delta': f'追问{turn}'}),
                ('response.output_text.done', {'text': f'追问{turn}'}),
                ('response.output_audio.delta', {'delta': base64.b64encode(bytes(960)).decode()}),
                ('response.output_audio.done', {}),
            ]:
                provider.events.put({'type': kind, 'response_id': f'r{turn}', **data})

    provider.send = send
    with patch('app.api.realtime.connect_provider', return_value=provider):
        result = page.evaluate('''() => new Promise(resolve => {
            const result = {output:[], errors:[]};
            const ws = new WebSocket(location.origin.replace('http','ws')+'/api/interview/1/realtime');
            let upload, started, lastVoice=0;
            const timeout=setTimeout(()=>{clearInterval(upload);ws.close();resolve({...result,timeout:true});},12000);
            ws.onopen=()=>ws.send(JSON.stringify({type:'connect',csrf_token:'csrf'}));
            ws.onmessage=({data})=>{
                const e=JSON.parse(data);
                if(e.type==='ready') {
                    started=performance.now();
                    upload=setInterval(()=>{
                        const t=performance.now()-started;
                        if(t>6500){clearInterval(upload);ws.send(JSON.stringify({type:'session.close'}));return;}
                        const frame=new Int16Array(320);
                        if(t<400 || (t>=2400 && t<2800)){frame.fill(4000);lastVoice=t;}
                        ws.send(frame.buffer);
                    },20);
                }
                if(e.type.startsWith('response.output_'))result.output.push({type:e.type,id:e.response_id,after:performance.now()-started-lastVoice});
                if(e.type==='error')result.errors.push(e.message);
            };
            ws.onclose=e=>{clearInterval(upload);clearTimeout(timeout);resolve({...result,code:e.code});};
        })''')
    assert result.get('timeout') is None
    assert result['errors'] == []
    assert result['code'] == 1000
    assert result['output']
    assert {event['id'] for event in result['output']} == {'r2'}
    assert min(event['after'] for event in result['output']) >= 2980
    assert any(event['type'] == 'response.cancel' for event in provider.sent)
    with voice_app.app_context():
        assert ChatMessage.query.filter_by(content='追问1').count() == 0
        assert ChatMessage.query.filter_by(content='追问2').one().audio_url
    assert frame_errors == []


def test_manual_turn_commit_keeps_socket_open_and_ignores_duplicate_and_inflight_audio(voice_app, transport_page):
    page, frame_errors = transport_page
    provider = FakeProvider(deferred=True)
    original_send = provider.send
    turn, started = 0, False

    def send(raw):
        nonlocal turn, started
        event = json.loads(raw)
        kind = event['type']
        if kind == 'input_audio_unmute.commit':
            turn += 1
            started = False
        if kind == 'input_audio_buffer.append':
            provider.sent.append(event)
            if not started:
                started = True
                provider.events.put({'type': 'conversation.item.input_audio_transcription.started', 'item_id': f'q{turn}'})
                provider.events.put({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': f'q{turn}', 'delta': f'手动回答{turn}'})
        elif kind == 'input_audio_buffer.commit':
            provider.sent.append(event)
            provider.events.put({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': f'q{turn}', 'text': f'手动回答{turn}'})
            provider.events.put({'type': 'response.output_text.done', 'response_id': f'r{turn}', 'text': f'手动追问{turn}'})
            provider.events.put({'type': 'response.output_audio.delta', 'response_id': f'r{turn}', 'delta': base64.b64encode(bytes(960)).decode()})
            provider.events.put({'type': 'response.output_audio.done', 'response_id': f'r{turn}'})
        else:
            original_send(raw)

    provider.send = send
    with patch('app.api.realtime.connect_provider', return_value=provider):
        result = page.evaluate('''() => new Promise(resolve => {
            const result={delays:[],errors:[],acks:0};
            const ws=new WebSocket(location.origin.replace('http','ws')+'/api/interview/1/realtime');
            let upload, submittedAt, round=0;
            const timeout=setTimeout(()=>{clearInterval(upload);ws.close();resolve({...result,timeout:true});},7000);
            const frame=new Int16Array(320);frame.fill(4000);
            function answer(){
                round++;
                const began=performance.now();
                upload=setInterval(()=>{
                    ws.send(frame.buffer);
                    if(performance.now()-began>=500){
                        clearInterval(upload);submittedAt=performance.now();
                        ws.send(JSON.stringify({type:'input_audio_buffer.commit'}));
                        ws.send(JSON.stringify({type:'input_audio_buffer.commit'}));
                        ws.send(frame.buffer); // A frame that was already in flight.
                    }
                },20);
            }
            ws.onopen=()=>ws.send(JSON.stringify({type:'connect',csrf_token:'csrf'}));
            ws.onmessage=({data})=>{
                const e=JSON.parse(data);
                if(e.type==='ready')answer();
                if(e.type==='turn.committed')result.acks++;
                if(e.type==='error')result.errors.push(e.message);
                if(e.type==='response.output_audio.delta')result.delays.push(performance.now()-submittedAt);
                if(e.type==='response.output_audio.done'){
                    if(round<2){ws.send(JSON.stringify({type:'input_audio_unmute.commit'}));answer();}
                    else ws.send(JSON.stringify({type:'session.close'}));
                }
            };
            ws.onclose=e=>{clearInterval(upload);clearTimeout(timeout);resolve({...result,code:e.code});};
        })''')
    assert result.get('timeout') is None
    assert result['code'] == 1000
    assert result['errors'] == []
    assert result['acks'] == 2
    assert len(result['delays']) == 2 and max(result['delays']) < 1200
    assert sum(event['type'] == 'input_audio_buffer.commit' for event in provider.sent) == 2
    assert sum(event['type'] == 'input_audio_mute.commit' for event in provider.sent) == 2
    assert not any(event['type'] == 'response.cancel' for event in provider.sent)
    with voice_app.app_context():
        assert ChatMessage.query.filter(ChatMessage.content.like('手动回答%')).count() == 2
        assert ChatMessage.query.filter(ChatMessage.content.like('手动追问%')).count() == 2
    assert frame_errors == []
