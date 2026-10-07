"""Browser upload metadata and transcription failure recovery."""

import pytest
from playwright.sync_api import expect

from .test_core_flows import login

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('mime_type, filename', [
    ('audio/webm;codecs=opus', 'recording.webm'),
    ('audio/mp4', 'recording.mp4'),
])
def test_upload_preserves_recorder_format(page, live_server, mime_type, filename):
    login(page, live_server, 'student')
    page.goto(f'{live_server}/interview/room/1')
    page.route('**/api/interview/transcribe', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{"status":"empty"}',
    ))
    with page.expect_request('**/api/interview/transcribe') as pending:
        page.evaluate('''async mimeType => {
            mediaRecorder = { mimeType };
            audioChunks = [new Blob([new Uint8Array(2000)], { type: mimeType })];
            await sendAudioMessage();
        }''', mime_type)
    body = pending.value.post_data_buffer
    assert f'filename="{filename}"'.encode() in body
    assert f'Content-Type: {mime_type}'.encode() in body
    assert page.evaluate('isProcessing') is False


@pytest.mark.parametrize('content_type, body, expected', [
    ('application/json', '{"status":"error","error":"语音识别服务尚未就绪"}', '语音识别服务尚未就绪'),
    ('text/html', '<h1>Service Unavailable</h1>', 'HTTP 503'),
])
def test_transcription_error_is_visible_and_unlocks_input(page, live_server, content_type, body, expected):
    login(page, live_server, 'student')
    page.goto(f'{live_server}/interview/room/1')
    page.route('**/api/interview/transcribe', lambda route: route.fulfill(
        status=503, content_type=content_type, body=body,
    ))
    page.evaluate('''async () => {
        mediaRecorder = { mimeType: 'audio/webm' };
        audioChunks = [new Blob([new Uint8Array(2000)], { type: 'audio/webm' })];
        await sendAudioMessage();
    }''')
    expect(page.locator('#chat-container')).to_contain_text(expected)
    assert page.evaluate('isProcessing') is False
