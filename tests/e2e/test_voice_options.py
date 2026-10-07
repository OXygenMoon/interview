"""Voice selection and submission on desktop and mobile."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1440, 390])
def test_voice_options_are_selectable_and_submitted(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
    # Keep this test independent of interviews created by other browser tests.
    page.route('**/api/interview/resumable', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{"has_session":false}',
    ))
    page.route('**/api/interview/cooldown-status', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{"can_start":true}',
    ))
    login(page, live_server, 'interview_student')
    page.get_by_test_id('open-interview-setup').click()
    options = page.get_by_role('radiogroup', name='选择面试官音色')
    expect(options.get_by_role('radio')).to_have_count(8)
    for name in ['云舟老师', '小天老师', '小何老师', '知性灿灿老师', '儒雅逸辰老师']:
        radio = options.get_by_role('radio', name=name)
        radio.check()
        expect(radio).to_be_checked()
    selected_voice = 'zh_male_ruyayichen_uranus_bigtts'
    page.locator('#company-select').select_option(label='未来科技')
    page.locator('#position-select').select_option(label='后端开发工程师')
    # Inspect FormData without changing the shared browser-test database.
    page.route('**/api/interview/create', lambda route: route.fulfill(
        status=503, content_type='application/json', body='{"error":"测试暂停创建"}',
    ))
    with page.expect_request('**/api/interview/create') as request:
        page.get_by_test_id('start-interview').click()
    assert f'name="voice_type"\r\n\r\n{selected_voice}' in request.value.post_data
    expect(options.get_by_role('radio', name='儒雅逸辰老师')).to_be_checked()
    expect(page.locator('#setup-feedback')).to_contain_text('测试暂停创建')
