"""Exclusive controls, draft preservation and typed-reply speech playback."""

import json

import pytest
from playwright.sync_api import expect

from tests.e2e.test_realtime_voice import open_live_room, setup_mic


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1440, 390])
def test_modes_release_mic_preserve_draft_and_play_typed_reply(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
    setup_mic(page)
    page.add_init_script('''
        window.testSpeechPlayers = [];
        window.Audio = class {
            constructor(url) { this.url = url; this.paused = true; window.testSpeechPlayers.push(this); }
            play() { this.paused = false; return Promise.resolve(); }
            pause() { this.paused = true; }
        };
    ''')
    controls = []

    def connected(socket):
        def incoming(raw):
            if isinstance(raw, bytes):
                return
            event = json.loads(raw)
            controls.append(event['type'])
            if event['type'] == 'connect':
                socket.send(json.dumps({'type': 'ready', 'sample_rate': 24000}))
            elif event['type'] == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))

        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    reply = '请解释一下数据库事务。'
    audio_url = '/static/uploads/audio/test-typed-reply.wav'
    body = ''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in [
        {'type': 'token', 'content': reply}, {'type': 'audio', 'url': audio_url, 'index': 0},
        {'type': 'done', 'message_id': 999},
    ])
    page.route('**/api/interview/*/chat', lambda route: route.fulfill(
        status=200, content_type='text/event-stream', body=body,
    ))
    open_live_room(page, live_server)
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#realtime-controls')).not_to_be_visible()
    page.locator('#msg-input').fill('还没有发送的草稿')
    page.locator('#realtime-toggle').click()
    page.wait_for_function('realtimeVoice.ready')
    expect(page.locator('#msg-input')).not_to_be_visible()
    expect(page.locator('#send-message')).not_to_be_visible()
    expect(page.locator('#realtime-controls')).to_be_visible()
    expect(page.locator('#realtime-toggle')).to_have_attribute('aria-pressed', 'true')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.evaluate('window.inputModeTrack = realtimeVoice.mic.getAudioTracks()[0]')
    page.locator('#text-toggle').click()
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#msg-input')).to_have_value('还没有发送的草稿')
    expect(page.locator('#realtime-controls')).not_to_be_visible()
    assert page.evaluate('inputModeTrack.readyState === "ended" && realtimeVoice.context === null')
    assert 'session.close' in controls
    page.locator('#msg-input').fill('我使用数据库事务。')
    page.locator('#send-message').click()
    expect(page.locator('#chat-container')).to_contain_text(reply)
    page.wait_for_function('window.testSpeechPlayers.length === 1')
    assert page.evaluate('testSpeechPlayers[0].url') == audio_url
    expect(page.locator('#text-audio-status')).to_have_text('面试官正在播报…')
    # Clicking a reply replays it and stops the current playback first.
    page.locator('#chat-container .chat-start .chat-bubble').last.click()
    assert page.evaluate('testSpeechPlayers.length === 2 && testSpeechPlayers[0].paused')
    page.locator('#realtime-toggle').click()
    page.wait_for_function('realtimeVoice.ready')
    assert page.evaluate('testSpeechPlayers.every(player => player.paused)')
    expect(page.locator('#msg-input')).not_to_be_visible()
    page.locator('#text-toggle').click()
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#text-toggle')).to_have_attribute('aria-pressed', 'true')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
