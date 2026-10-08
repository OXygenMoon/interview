"""Real AudioWorklet capture with a mock provider-facing browser socket."""

import base64
import json

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def setup_mic(page):
    page.add_init_script('''
        MediaDevices.prototype.getUserMedia = async () => {
            const context = new AudioContext();
            const destination = context.createMediaStreamDestination();
            const source = context.createOscillator();
            source.connect(destination);
            source.start();
            window.testMicContext = context;
            return destination.stream;
        };
    ''')


def open_live_room(page, live_server):
    page.goto(live_server + '/login')
    page.get_by_label('账号').fill('realtime_student')
    page.get_by_label('密码', exact=True).fill('RealtimePass123!')
    page.get_by_test_id('login-submit').click()
    page.wait_for_url(live_server + '/')
    csrf = page.locator('meta[name="csrf-token"]').get_attribute('content')
    resumable = page.request.get(live_server + '/api/interview/resumable').json()
    if resumable['has_session']:
        session_id = resumable['session_id']
    else:
        response = page.request.post(live_server + '/api/interview/create',
                                     form={'target_role': '后端开发', 'difficulty': '标准模式'},
                                     headers={'X-CSRF-Token': csrf})
        assert response.ok, response.text()
        session_id = response.json()['session_id']
    page.goto(f'{live_server}/interview/room/{session_id}')


def test_continuous_pcm_capture_transcripts_mute_interrupt_and_stop(page, live_server):
    setup_mic(page)
    controls = []
    frames = []
    socket_holder = []

    def connected(socket):
        socket_holder.append(socket)

        def incoming(raw):
            if isinstance(raw, bytes):
                frames.append(raw)
                if len(frames) == 1:
                    socket.send(json.dumps({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'q1', 'delta': '我的项目'}))
                    socket.send(json.dumps({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'q1', 'delta': '我的项目使用事物'}))
                    socket.send(json.dumps({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'q1', 'text': '我的项目使用事务。'}))
                    socket.send(json.dumps({'type': 'response.output_text.delta', 'response_id': 'r1', 'delta': '怎样回滚？'}))
                    socket.send(json.dumps({'type': 'response.output_audio.delta', 'response_id': 'r1', 'delta': base64.b64encode(b'\0' * 48000).decode()}))
            else:
                event = json.loads(raw)
                controls.append(event)
                if event['type'] == 'connect':
                    socket.send(json.dumps({'type': 'ready', 'sample_rate': 24000}))
                elif event['type'] == 'session.close':
                    socket.send(json.dumps({'type': 'session.closed'}))

        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    expect(page.locator('#record-btn')).to_have_text('停止实时对话')
    expect(page.locator('#chat-container')).to_contain_text('我的项目使用事务。')
    assert '我的项目我的项目' not in page.locator('#chat-container').inner_text()
    expect(page.locator('#chat-container')).to_contain_text('怎样回滚？')
    page.wait_for_function('realtimeVoice.sources.size > 0')
    socket_holder[0].send(json.dumps({'type': 'conversation.item.input_audio_transcription.started', 'item_id': 'q2'}))
    page.wait_for_function('realtimeVoice.sources.size === 0')
    page.locator('#realtime-mute').click()
    expect(page.locator('#realtime-mute')).to_have_text('恢复麦克风')
    assert any(event['type'] == 'input_audio_mute.commit' for event in controls)
    page.locator('#realtime-mute').click()
    page.locator('#realtime-interrupt').click()
    assert any(event['type'] == 'response.cancel' for event in controls)
    page.locator('#record-btn').click()
    expect(page.locator('#realtime-status')).to_have_text('实时语音已停止')
    assert frames and all(len(frame) == 640 for frame in frames)
    assert all('api_key' not in event for event in controls)
    assert page.evaluate('realtimeVoice.context === null && realtimeVoice.mic === null')


def test_provider_auth_error_is_visible_and_releases_microphone(page, live_server):
    setup_mic(page)

    def connected(socket):
        socket.on_message(lambda raw: socket.send(json.dumps({
            'type': 'error', 'message': '语音 API Key 无效，请联系管理员更新配置。',
        })))

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    expect(page.locator('#realtime-status')).to_contain_text('API Key 无效')
    expect(page.locator('#record-btn')).to_have_text('开始实时对话')
    expect(page.locator('#msg-input')).to_be_enabled()
    assert page.evaluate('realtimeVoice.context === null && realtimeVoice.mic === null')


def test_error_during_audio_upload_releases_mic_and_allows_reconnection(page, live_server):
    setup_mic(page)
    connections = []
    controls = []

    def connected(socket):
        connections.append(socket)
        first = len(connections) == 1
        failed = False

        def incoming(raw):
            nonlocal failed
            if isinstance(raw, bytes):
                if first and not failed:
                    failed = True
                    socket.send(json.dumps({'type': 'error', 'message': '服务暂时中断，请重新连接。'}))
                return
            event = json.loads(raw)
            controls.append((len(connections), event['type']))
            if event['type'] == 'connect':
                socket.send(json.dumps({'type': 'ready', 'sample_rate': 24000}))
            elif event['type'] == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))

        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    expect(page.locator('#realtime-status')).to_have_text('服务暂时中断，请重新连接。', timeout=2000)
    assert page.evaluate('realtimeVoice.context === null && realtimeVoice.mic === null')
    assert (1, 'session.close') not in controls
    page.locator('#realtime-toggle').click()
    page.wait_for_function('realtimeVoice.ready')
    assert len(connections) == 2
    page.locator('#record-btn').click()
    expect(page.locator('#realtime-status')).to_have_text('实时语音已停止')
    assert (2, 'session.close') in controls


def test_asr_final_save_corrects_preview_and_duplicate_events_do_not_add_bubbles(page, live_server):
    open_live_room(page, live_server)
    user_bubbles = page.locator('#chat-container .chat-end .chat-bubble')
    initial_count = user_bubbles.count()
    page.evaluate('''() => {
        const prefix = 'conversation.item.input_audio_transcription.';
        const final = '面试官你好，我是技师学院的毕业生，我想应聘网络工程师岗位。';
        for (let length = 1; length <= final.length; length++) {
            realtimeVoice.handle({type: prefix + 'delta', item_id: 'repeat-test', delta: final.slice(0, length)});
        }
        realtimeVoice.handle({type: prefix + 'completed', item_id: 'repeat-test'});
        realtimeVoice.handle({type: prefix + 'completed', item_id: 'repeat-test'});
        realtimeVoice.handle({type: prefix + 'delta', item_id: 'repeat-test', delta: '迟到的错误内容'});
    }''')
    final = '面试官你好，我是技师学院的毕业生，我想应聘网络工程师岗位。'
    expect(user_bubbles).to_have_count(initial_count + 1)
    expect(user_bubbles.last).to_have_text(final)
    page.evaluate('''() => {
        realtimeVoice.completedUserBubbles.get('repeat-test').textContent = '旧脚本追加的重复重复内容';
        const saved = {type: 'transcript.saved', sender: 'user', item_id: 'repeat-test', message_id: 999,
            text: '面试官你好，我是技师学院的毕业生，我想应聘网络工程师岗位。'};
        realtimeVoice.handle(saved);
        realtimeVoice.handle(saved);
    }''')
    expect(user_bubbles).to_have_count(initial_count + 1)
    expect(user_bubbles.last).to_have_text(final)
    scripts = page.locator('script[src*="realtime-voice.js"]')
    assert 'v=voice-manual-reply-20261009-1' in scripts.get_attribute('src')


@pytest.mark.parametrize('width', [1440, 390])
def test_finish_one_turn_pauses_noise_upload_and_resumes_after_playback(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 844})
    setup_mic(page)  # A continuous oscillator simulates never-ending background sound.
    controls, frames, sockets = [], [], []

    def connected(socket):
        sockets.append(socket)

        def incoming(raw):
            if isinstance(raw, bytes):
                frames.append(raw)
                return
            kind = json.loads(raw)['type']
            controls.append(kind)
            if kind == 'connect':
                socket.send(json.dumps({'type': 'ready'}))
            elif kind == 'input_audio_buffer.commit':
                socket.send(json.dumps({'type': 'turn.committed'}))
            elif kind == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))

        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    finish = page.locator('#realtime-finish-turn')
    expect(finish).to_be_enabled()
    page.wait_for_function('realtimeVoice.ready && realtimeVoice.mic !== null')
    page.evaluate('window.originalMic = realtimeVoice.mic; window.originalSocket = realtimeVoice.socket')
    for turn in [1, 2]:
        expect(finish).to_be_enabled()
        finish.click()
        expect(finish).to_be_disabled()
        expect(finish).to_have_text('等待面试官')
        assert controls.count('input_audio_buffer.commit') == turn
        page.wait_for_timeout(80)  # Let frames in flight drain.
        paused_count = len(frames)
        page.wait_for_timeout(120)
        assert len(frames) == paused_count
        assert page.evaluate('realtimeVoice.active && realtimeVoice.ready && originalMic.getTracks()[0].readyState === "live"')
        sockets[0].send(json.dumps({'type': 'conversation.item.input_audio_transcription.started', 'item_id': f'manual-{turn}'}))
        sockets[0].send(json.dumps({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': f'manual-{turn}', 'text': '我已回答完。'}))
        sockets[0].send(json.dumps({'type': 'response.output_text.done', 'response_id': f'manual-r{turn}', 'text': '请解释事务回滚。'}))
        sockets[0].send(json.dumps({'type': 'response.output_audio.delta', 'response_id': f'manual-r{turn}', 'delta': base64.b64encode(bytes(48000)).decode()}))
        sockets[0].send(json.dumps({'type': 'response.output_audio.done', 'response_id': f'manual-r{turn}'}))
        page.wait_for_function('realtimeVoice.sources.size > 0')
        expect(finish).to_be_disabled()
        page.wait_for_timeout(120)
        assert len(frames) == paused_count  # Audio.done is not yet audible playback completion.
        expect(finish).to_be_enabled(timeout=3000)
        assert controls.count('input_audio_unmute.commit') == turn
        page.wait_for_timeout(120)
        assert len(frames) > paused_count
        assert page.evaluate('realtimeVoice.socket === originalSocket && realtimeVoice.mic === originalMic')
    assert len(sockets) == 1
    assert 'session.close' not in controls
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.locator('#record-btn').click()
    assert 'session.close' in controls


def test_manual_wait_can_be_interrupted_or_switched_back_to_text(page, live_server):
    setup_mic(page)
    controls = []

    def connected(socket):
        def incoming(raw):
            if isinstance(raw, bytes):
                return
            kind = json.loads(raw)['type']
            controls.append(kind)
            if kind == 'connect':
                socket.send(json.dumps({'type': 'ready'}))
            elif kind == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))
        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    finish = page.locator('#realtime-finish-turn')
    expect(finish).to_be_enabled()
    finish.click()
    expect(finish).to_be_disabled()
    page.locator('#realtime-interrupt').click()
    expect(finish).to_be_enabled()
    assert not page.evaluate('realtimeVoice.turnCommitted')
    assert 'response.cancel' in controls and 'input_audio_unmute.commit' in controls
    finish.click()
    expect(finish).to_be_disabled()
    page.evaluate('window.manualMic = realtimeVoice.mic')
    page.locator('#text-toggle').click()
    expect(page.locator('#msg-input')).to_be_visible()
    assert page.evaluate('!realtimeVoice.active && !realtimeVoice.turnCommitted && manualMic.getTracks()[0].readyState === "ended"')
    assert controls.count('session.close') == 1


def test_manual_recovery_errors_and_text_only_reply_restore_controls(page, live_server):
    setup_mic(page)
    controls = []

    def connected(socket):
        def incoming(raw):
            if isinstance(raw, bytes):
                return
            kind = json.loads(raw)['type']
            controls.append(kind)
            if kind == 'connect':
                socket.send(json.dumps({'type': 'ready'}))
            elif kind == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))
        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    open_live_room(page, live_server)
    page.locator('#realtime-toggle').click()
    finish = page.locator('#realtime-finish-turn')
    expect(finish).to_be_enabled()
    finish.click()
    page.evaluate("realtimeVoice.handle({type:'manual.reply_failed',message:'回复生成失败，请重试。'})")
    expect(finish).to_be_enabled()
    expect(page.locator('#realtime-status')).to_have_text('回复生成失败，请重试。')
    finish.click()
    page.evaluate('''() => {
        realtimeVoice.handle({type:'response.output_text.done',response_id:'text-only',text:'请解释回滚机制。'});
        realtimeVoice.handle({type:'manual.audio_unavailable',message:'语音播报暂不可用，面试官回复已显示为文字。'});
        realtimeVoice.handle({type:'response.output_audio.done',response_id:'text-only'});
    }''')
    expect(finish).to_be_enabled()
    expect(page.locator('#realtime-status')).to_have_text('语音播报暂不可用，面试官回复已显示为文字。')
    expect(page.locator('#chat-container')).to_contain_text('请解释回滚机制。')
    assert page.evaluate('realtimeVoice.active && realtimeVoice.ready && !realtimeVoice.turnCommitted')
    assert controls.count('input_audio_unmute.commit') == 2
    page.locator('#record-btn').click()
