"""Mobile interview recovery in Chromium and Safari's WebKit engine."""

import json
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.e2e.test_realtime_voice import open_live_room


pytestmark = pytest.mark.e2e


@pytest.fixture(scope='module', params=['chromium', 'webkit'])
def browser_instance(request):
    with sync_playwright() as playwright:
        browser = getattr(playwright, request.param).launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(autouse=True)
def mobile_viewport(page):
    page.set_viewport_size({'width': 390, 'height': 844})


def test_timer_survives_mobile_date_parser_and_counts_past_one_hour(page, live_server):
    def room(route):
        response = route.fetch()
        body = re.sub(r'const initialElapsed = \d+;', 'const initialElapsed = 3665;', response.text())
        route.fulfill(response=response, body=body)

    page.route('**/interview/room/*', room)
    open_live_room(page, live_server)
    timer = page.locator('#interview-timer')
    expect(timer).to_have_text('61:05')
    expect(timer).not_to_have_text('61:05', timeout=3000)
    assert 'NaN' not in timer.inner_text()
    page.reload()
    expect(timer).to_have_text('61:05')


@pytest.mark.parametrize('status, content_type, body, expected', [
    (400, 'text/html', '<h1>CSRF token missing or invalid</h1>', '页面验证已失效'),
    (400, 'application/json', '{"error":"该面试已结束，无法继续对话"}', '该面试已结束'),
    (503, 'text/html', '<h1>Unavailable</h1>', 'HTTP 503'),
    (401, 'text/html', '<h1>Login</h1>', '登录已失效'),
])
def test_rejected_answer_keeps_draft_and_unlocks_retry(page, live_server, status, content_type, body, expected):
    page.route('**/api/interview/*/chat', lambda route: route.fulfill(
        status=status, content_type=content_type, body=body,
    ))
    open_live_room(page, live_server)
    answer = '您好，我想应聘技术支持岗位。'
    page.locator('#msg-input').fill(answer)
    page.locator('#send-message').click()
    expect(page.locator('#chat-container')).to_contain_text(expected)
    expect(page.locator('#text-audio-status')).to_contain_text(expected)
    expect(page.locator('#send-message')).to_be_enabled()
    expect(page.locator('#msg-input')).to_have_value(answer)
    assert not page.locator('#ai-typing-indicator').count()
    page.reload()
    expect(page.locator('#msg-input')).to_have_value(answer)
    reply = '请介绍你解决过的一次故障。'
    events = [{'type': 'token', 'content': reply}, {'type': 'done', 'message_id': 999}]
    page.unroute('**/api/interview/*/chat')
    page.route('**/api/interview/*/chat', lambda route: route.fulfill(
        status=200, content_type='text/event-stream',
        body=''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events),
    ))
    page.locator('#send-message').click()
    expect(page.locator('#chat-container')).to_contain_text(reply)
    expect(page.locator('#text-audio-status')).to_have_text('面试官已回复，可以继续回答。')
    assert page.evaluate('sessionStorage.getItem(DRAFT_KEY)') is None


@pytest.mark.parametrize('streaming', [True, False])
def test_chinese_sse_and_crlf_work_with_or_without_streaming_fetch(page, live_server, streaming):
    open_live_room(page, live_server)
    page.evaluate('''streaming => {
        const original = window.fetch;
        window.fetch = (url, options) => {
            if (!String(url).endsWith('/chat')) return original(url, options);
            const events = [{type: 'token', content: '请说明你的项目经历。'}, {type: 'done', message_id: 999}];
            const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\\r\\n\\r\\n').join(''));
            const stream = new ReadableStream({start(controller) {
                for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2));
                controller.close();
            }});
            const response = new Response(stream, {headers: {'Content-Type': 'text/event-stream'}});
            if (!streaming) Object.defineProperty(response, 'body', {value: null});
            return Promise.resolve(response);
        };
    }''', streaming)
    page.locator('#msg-input').fill('我参与了售前项目。')
    page.locator('#send-message').click()
    expect(page.locator('#chat-container')).to_contain_text('请说明你的项目经历。')
    expect(page.locator('#send-message')).to_be_enabled()
    expect(page.locator('#text-audio-status')).to_have_text('面试官已回复，可以继续回答。')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')


def test_stream_error_and_timeout_clear_waiting_status(page, live_server):
    open_live_room(page, live_server)
    page.route('**/api/interview/*/chat', lambda route: route.fulfill(
        status=200, content_type='text/event-stream',
        body='data: {"type":"error","message":"AI 服务暂时不可用"}\n\n',
    ))
    page.locator('#msg-input').fill('您好。')
    page.locator('#send-message').click()
    expect(page.locator('#text-audio-status')).to_have_text('AI 服务暂时不可用')
    expect(page.locator('#send-message')).to_be_enabled()
    page.evaluate('''() => {
        const schedule = window.setTimeout;
        window.setTimeout = (callback, delay, ...args) => schedule(callback, delay === 90000 ? 20 : delay, ...args);
        window.fetch = (url, options) => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
    }''')
    page.locator('#msg-input').fill('需要保留的回答')
    page.locator('#send-message').click()
    expect(page.locator('#text-audio-status')).to_contain_text('等待超时')
    expect(page.locator('#send-message')).to_be_enabled()
    expect(page.locator('#msg-input')).to_have_value('需要保留的回答')


def test_http_voice_explains_requirement_and_keeps_text_usable(page, live_server):
    # Simulate a public HTTP origin without DNS or external network dependencies.
    page.add_init_script("Object.defineProperty(window, 'isSecureContext', {value: false});")
    open_live_room(page, live_server)
    expect(page.locator('#voice-environment-status')).to_be_visible()
    expect(page.locator('#voice-environment-status')).to_contain_text('HTTPS')
    page.locator('#realtime-toggle').click()
    expect(page.locator('#text-audio-status')).to_contain_text('HTTP 访问')
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#send-message')).to_be_enabled()
    assert page.evaluate('!realtimeVoice.active && !realtimeVoice.context && !realtimeVoice.mic')


def test_real_post_has_csrf_and_receives_server_validation(page, live_server):
    open_live_room(page, live_server)
    result = page.evaluate('''async () => {
        const response = await fetch(`/api/interview/${sessionId}/chat`, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: ''}),
        });
        return {status: response.status, body: await response.json()};
    }''')
    assert result == {'status': 400, 'body': {'error': 'Message is empty'}}


def test_mobile_voice_capture_switch_and_typed_reply_playback(page, live_server):
    from tests.e2e.test_interview_input_modes import (
        test_modes_release_mic_preserve_draft_and_play_typed_reply,
    )
    test_modes_release_mic_preserve_draft_and_play_typed_reply(page, live_server, 390)


@pytest.mark.parametrize('action', ['timeout', 'switch_to_text'])
def test_pending_microphone_can_recover_and_late_permission_releases_track(page, live_server, action):
    page.add_init_script('''
        MediaDevices.prototype.getUserMedia = options => {
            if (!options.audio) return Promise.reject(new Error('Camera disabled for this test'));
            return new Promise(resolve => { window.resolvePendingMic = resolve; });
        };
    ''')
    open_live_room(page, live_server)
    if action == 'timeout':
        page.evaluate('''() => {
            const schedule = window.setTimeout;
            window.setTimeout = (callback, delay, ...args) => schedule(callback, delay === 30000 ? 200 : delay, ...args);
        }''')
    page.locator('#realtime-toggle').click()
    page.wait_for_function('typeof resolvePendingMic === "function"')
    if action == 'switch_to_text':
        page.locator('#text-toggle').click()
    else:
        expect(page.locator('#text-audio-status')).to_contain_text('麦克风启动超时')
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#send-message')).to_be_enabled()
    page.evaluate('''() => {
        window.lateMicContext = new AudioContext();
        const stream = lateMicContext.createMediaStreamDestination().stream;
        window.lateTrack = stream.getAudioTracks()[0];
        resolvePendingMic(stream);
    }''')
    page.wait_for_function('lateTrack.readyState === "ended"')
    assert page.evaluate('!realtimeVoice.active && realtimeVoice.context === null && realtimeVoice.mic === null')
    page.evaluate('lateMicContext.close()')
