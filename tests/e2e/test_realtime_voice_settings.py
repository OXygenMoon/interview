"""Admin toggle, student entry points and microphone cleanup in Chromium."""

import json

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login
from tests.e2e.test_realtime_voice import open_live_room, setup_mic

pytestmark = pytest.mark.e2e


def test_admin_toggle_updates_room_and_disabled_event_releases_microphone(page, live_server):
    setup_mic(page)
    sockets = []

    def connected(socket):
        sockets.append(socket)

        def incoming(raw):
            if isinstance(raw, bytes):
                return
            event = json.loads(raw)
            if event['type'] == 'connect':
                socket.send(json.dumps({'type': 'ready', 'sample_rate': 24000}))
            elif event['type'] == 'session.close':
                socket.send(json.dumps({'type': 'session.closed'}))

        socket.on_message(incoming)

    page.route_web_socket('**/api/interview/*/realtime', connected)
    admin_context = page.context.browser.new_context()
    admin_page = admin_context.new_page()
    admin_page.route('https://**/*', lambda route: route.fulfill(status=204, body=''))
    try:
        login(admin_page, live_server, 'admin')
        admin_page.goto(live_server + '/admin/settings')
        toggle = admin_page.get_by_label('启用实时语音交互')
        expect(toggle).to_be_checked()
        tts_enabled = admin_page.locator('input[name="enable_tts"]').is_checked()
        open_live_room(page, live_server)
        expect(page.locator('#realtime-toggle')).to_be_visible()

        toggle.uncheck()
        admin_page.get_by_role('button', name='保存设置').click()
        expect(toggle).not_to_be_checked()
        assert admin_page.locator('input[name="enable_tts"]').is_checked() == tts_enabled
        page.reload()
        expect(page.locator('#record-btn')).to_have_count(0)
        expect(page.locator('#realtime-toggle')).to_have_count(0)
        expect(page.get_by_text('实时语音交互已由管理员关闭，可使用文字回答。')).to_be_visible()
        expect(page.locator('#msg-input')).to_be_enabled()

        toggle.check()
        admin_page.get_by_role('button', name='保存设置').click()
        expect(toggle).to_be_checked()
        page.reload()
        page.locator('#realtime-toggle').click()
        expect(page.locator('#record-btn')).to_have_text('停止实时对话')
        page.wait_for_function('realtimeVoice.ready')
        page.evaluate('window.voiceTestTrack = realtimeVoice.mic.getAudioTracks()[0]')

        toggle.uncheck()
        admin_page.get_by_role('button', name='保存设置').click()
        expect(toggle).not_to_be_checked()
        # Server-side polling and final transcript persistence are covered by
        # a real WebSocket integration test; exercise its browser event here.
        sockets[0].send(json.dumps({'type': 'feature.disabled',
                                   'message': '管理员已关闭实时语音交互，请使用文字回答。'}))
        expect(page.locator('#realtime-status')).to_have_text('管理员已关闭实时语音交互，请使用文字回答。')
        expect(page.locator('#record-btn')).to_be_disabled()
        expect(page.locator('#realtime-toggle')).to_be_disabled()
        expect(page.locator('#msg-input')).to_be_enabled()
        assert page.evaluate('realtimeVoice.context === null && realtimeVoice.mic === null && window.voiceTestTrack.readyState === "ended"')
    finally:
        if not admin_page.is_closed():
            admin_page.goto(live_server + '/admin/settings')
            admin_page.locator('input[name="enable_realtime_voice"]').check()
            admin_page.get_by_role('button', name='保存设置').click()
        admin_context.close()
