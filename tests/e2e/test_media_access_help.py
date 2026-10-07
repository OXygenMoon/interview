"""Browser-specific HTTP guidance and copying when Clipboard API is unavailable."""

import json

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


def insecure_page(page, user_agent='Mozilla/5.0 Windows NT 10.0 Chrome/140.0.0.0'):
    page.add_init_script('''(() => {
        Object.defineProperty(window, 'isSecureContext', {value: false});
        Object.defineProperty(navigator, 'userAgent', {value: USER_AGENT});
        window.mediaRequestCount = 0;
        MediaDevices.prototype.getUserMedia = () => {
            window.mediaRequestCount++;
            return Promise.reject(new Error('No device capture expected'));
        };
    })();'''.replace('USER_AGENT', json.dumps(user_agent)))


@pytest.mark.parametrize('ua, flags, explanation', [
    ('Mozilla/5.0 Windows NT 10.0 Chrome/140.0.0.0', 'chrome', 'Chrome：'),
    ('Mozilla/5.0 Windows NT 10.0 Chrome/140.0.0.0 Edg/140.0.0.0', 'edge', 'Edge：'),
    ('Mozilla/5.0 Linux Android 15 Chrome/140.0.0.0 Mobile', 'chrome', 'Android Chrome'),
    ('Mozilla/5.0 iPhone CPU iPhone OS 18_0 CriOS/140.0.0.0 Mobile', None, 'iPhone / iPad'),
    ('Mozilla/5.0 Linux Android 15 Chrome/140.0.0.0 MicroMessenger/8.0', None, 'HTTPS'),
    ('Mozilla/5.0 Linux Android 15 Chrome/140.0.0.0 EdgA/140.0.0.0', None, 'HTTPS'),
])
def test_device_guidance_preserves_text_and_does_not_capture(page, live_server, ua, flags, explanation):
    page.set_viewport_size({'width': 390, 'height': 844})
    insecure_page(page, ua)
    open_live_room(page, live_server)
    expect(page.locator('#voice-environment-status')).to_contain_text('麦克风和摄像头')
    page.locator('#media-access-help').click()
    expect(page.locator('#mic_permission_modal')).to_be_visible()
    expect(page.locator('#current-origin')).to_have_value(live_server)
    if flags:
        expect(page.locator('#media-browser-guide')).to_contain_text(explanation)
        expect(page.locator('#media-flags-address')).to_have_value(
            f'{flags}://flags/#unsafely-treat-insecure-origin-as-secure')
        expect(page.locator('#media-https-guide')).to_be_hidden()
    else:
        expect(page.locator('#media-flags-guide')).to_be_hidden()
        expect(page.locator('#media-https-guide')).to_contain_text(explanation)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role('button', name='返回面试', exact=True).click()
    page.locator('#realtime-toggle').click()
    expect(page.locator('#msg-input')).to_be_visible()
    expect(page.locator('#send-message')).to_be_enabled()
    assert page.evaluate('mediaRequestCount') == 0
    assert not page.evaluate('realtimeVoice.active')


@pytest.mark.parametrize('clipboard, fallback, expected', [
    ('missing', True, '已复制'),
    ('reject', True, '已复制'),
    ('missing', False, '地址已选中'),
    ('success', False, '已复制'),
])
def test_copy_works_or_selects_address_on_http(page, live_server, clipboard, fallback, expected):
    insecure_page(page)
    open_live_room(page, live_server)
    page.locator('#media-access-help').click()
    page.evaluate('''({clipboard, fallback}) => {
        window.copiedAddress = null;
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value:
            clipboard === 'missing' ? undefined : {writeText: async value => {
                if (clipboard === 'reject') throw new Error('Clipboard blocked');
                window.copiedAddress = value;
            }}
        });
        document.execCommand = () => {
            window.copiedAddress = document.activeElement.value;
            return fallback;
        };
    }''', {'clipboard': clipboard, 'fallback': fallback})
    for button, field in [('copy-media-origin', 'current-origin'), ('copy-media-flags', 'media-flags-address')]:
        page.locator('#' + button).click()
        expect(page.locator('#media-copy-status')).to_contain_text(expected)
        value = page.locator('#' + field).input_value()
        assert page.evaluate('copiedAddress') == value
        if expected == '地址已选中':
            assert page.locator('#' + field).evaluate('(input) => input.selectionEnd - input.selectionStart') == len(value)


def test_secure_context_on_http_does_not_show_exception_warning(page, live_server):
    # Localhost and effective browser exceptions are secure even with http URLs.
    page.add_init_script("Object.defineProperty(window, 'isSecureContext', {value: true});")
    open_live_room(page, live_server)
    assert page.url.startswith('http:')
    expect(page.locator('#media-access-notice')).to_be_hidden()


def test_random_room_explains_http_before_capture(page, live_server):
    insecure_page(page)
    open_live_room(page, live_server)
    page.goto(live_server + '/interview/random')
    expect(page.locator('#media-access-notice')).to_be_visible()
    for button in ['#record-btn', '#camera-toggle-btn']:
        page.locator(button).click()
        expect(page.locator('#mic_permission_modal')).to_be_visible()
        page.get_by_role('button', name='返回面试', exact=True).click()
    expect(page.locator('#answer-text')).to_be_enabled()
    assert page.evaluate('mediaRequestCount') == 0
