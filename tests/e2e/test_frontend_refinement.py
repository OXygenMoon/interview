"""Functional coverage for the refined entry and interview setup states."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login


pytestmark = pytest.mark.e2e


def select_position(page):
    page.locator('#company-select').select_option(label='未来科技')
    page.locator('#position-select').select_option(label='后端开发工程师')


def test_login_password_visibility_and_local_visual(page, live_server):
    page.goto(f'{live_server}/login')
    visual = page.locator('.auth-visual img')
    expect(visual).to_be_visible()
    assert visual.evaluate('(image) => image.complete && image.naturalWidth > 0')
    assert page.locator('script[src*="marked"]').count() == 0
    password = page.get_by_label('密码', exact=True)
    password.fill('draft-password')
    page.get_by_role('button', name='显示密码').click()
    expect(password).to_have_attribute('type', 'text')
    expect(password).to_have_value('draft-password')
    page.get_by_role('button', name='隐藏密码').click()
    expect(password).to_have_attribute('type', 'password')
    expect(password).to_have_value('draft-password')


def test_setup_validation_failure_and_retry_preserve_input(page, live_server):
    login(page, live_server, 'interview_student')
    page.get_by_test_id('open-interview-setup').click()
    page.get_by_test_id('start-interview').click()
    feedback = page.locator('#setup-feedback')
    expect(feedback).to_contain_text('请先选择公司和岗位')
    expect(feedback).to_be_focused()
    expect(page.locator('#position-select')).to_have_attribute('aria-invalid', 'true')
    select_position(page)
    expect(feedback).not_to_be_visible()
    page.route('**/api/interview/create', lambda route: route.abort('failed'))
    page.get_by_test_id('start-interview').click()
    expect(feedback).to_contain_text('暂时无法连接服务器')
    expect(page.locator('#position-select option:checked')).to_have_text('后端开发工程师')
    expect(page.get_by_test_id('start-interview')).to_be_enabled()
    page.unroute('**/api/interview/create')
    page.route('**/api/interview/create', lambda route: route.fulfill(
        status=423, content_type='application/json',
        body='{"cooldown":{"reason":"review_required","last_session_id":1}}',
    ))
    page.get_by_test_id('start-interview').click()
    expect(feedback).to_contain_text('请先查看上一次面试报告')
    expect(feedback.get_by_role('link', name='去复盘')).to_have_attribute(
        'href', '/interview/summary/1',
    )
    expect(page.get_by_test_id('start-interview')).to_be_enabled()


def test_setup_inflight_disallows_duplicate_requests(page, live_server):
    login(page, live_server, 'interview_student')
    page.get_by_test_id('open-interview-setup').click()
    select_position(page)
    pending = []
    page.route('**/api/interview/create', lambda route: pending.append(route))
    button = page.get_by_test_id('start-interview')
    button.click()
    expect(button).to_be_disabled()
    expect(button).to_have_attribute('aria-busy', 'true')
    page.evaluate('submitSetup()')
    assert len(pending) == 1
    pending[0].fulfill(status=503, content_type='application/json',
                       body='{"error":"服务暂不可用"}')
    expect(button).to_be_enabled()
    expect(page.locator('#setup-feedback')).to_contain_text('服务暂不可用')


@pytest.mark.parametrize('theme', [
    'playful', 'playful-sage', 'playful-blue',
    'playful-lavender', 'playful-rose', 'playful-dark',
])
def test_home_original_layout_and_single_line_controls(page, live_server, theme):
    login(page, live_server, 'student')
    page.evaluate('(theme) => localStorage.setItem("interview-ui-theme", theme)', theme)
    page.reload()
    expect(page.locator('.club-art')).to_be_visible()
    expect(page.locator('#recent-records-table')).to_contain_text('后端开发工程师')
    expect(page.locator('.club-metric').nth(2)).to_contain_text('86')
    for width in [320, 375, 414, 768, 1440]:
        page.set_viewport_size({'width': width, 'height': 1000})
        metrics = page.evaluate('''() => ({
            width: document.documentElement.scrollWidth,
            viewport: innerWidth,
            rootClip: getComputedStyle(document.documentElement).overflowX,
            bodyClip: getComputedStyle(document.body).overflowX,
            primary: document.querySelector('[data-testid="open-interview-setup"]')
                .getBoundingClientRect().bottom,
            intro: document.querySelector('.club-intro').getBoundingClientRect().toJSON(),
            illustration: document.querySelector('.club-art').getBoundingClientRect().toJSON(),
            cards: [...document.querySelectorAll('.club-metric')].map(card => ({
                rect: card.getBoundingClientRect().toJSON(),
                background: getComputedStyle(card).backgroundColor,
                noteVisible: getComputedStyle(card.querySelector('.club-metric-note')).display !== 'none'
            })),
            wrap: [...document.querySelectorAll('.club-actions .btn')].some(button => {
                const range = document.createRange(); range.selectNodeContents(button);
                return range.getBoundingClientRect().height > 24;
            })
        })''')
        assert metrics['width'] <= metrics['viewport'] + 1
        assert metrics['rootClip'] == metrics['bodyClip'] == 'clip'
        assert metrics['primary'] < 1000
        assert not metrics['wrap']
        cards = metrics['cards']
        assert len({card['background'] for card in cards}) == 3
        assert all(card['noteVisible'] for card in cards)
        if width < 768:
            assert metrics['illustration']['top'] >= metrics['intro']['bottom'] - 1
            assert abs(cards[0]['rect']['top'] - cards[1]['rect']['top']) < 1
            assert cards[2]['rect']['top'] >= cards[0]['rect']['bottom']
            assert cards[2]['rect']['width'] > cards[0]['rect']['width'] * 1.9
        else:
            assert metrics['illustration']['left'] >= metrics['intro']['right'] - 1
            assert max(card['rect']['top'] for card in cards) - min(
                card['rect']['top'] for card in cards
            ) < 1
