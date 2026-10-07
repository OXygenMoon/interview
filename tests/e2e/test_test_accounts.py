"""Two independent browsers share the test pool but cannot share an account."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_two_browsers_observe_exclusive_login_and_release(page, browser_instance, live_server):
    other_context = browser_instance.new_context(locale='zh-CN')
    other = other_context.new_page()
    try:
        page.goto(f'{live_server}/test-accounts')
        other.goto(f'{live_server}/test-accounts')
        expect(page.locator('[data-account-id]')).to_have_count(10)
        first = page.locator('[data-account-id]').first
        user_id = first.get_attribute('data-account-id')
        other_card = other.locator(f'[data-account-id="{user_id}"]')
        expect(other_card.locator('button')).to_be_enabled()
        first.get_by_role('button', name='使用此账号').click()
        expect(page).to_have_url(f'{live_server}/')
        expect(page.locator('[data-test-account-heartbeat]')).to_have_count(1)
        expect(other_card.locator('[data-state]')).to_have_text('使用中，无法登录该账号', timeout=10000)
        expect(other_card.locator('button')).to_be_disabled()
        page.locator('#app-account-toggle').click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        expect(page).to_have_url(f'{live_server}/login')
        expect(other_card.locator('[data-state]')).to_have_text('未登录，可以使用', timeout=10000)
        expect(other_card.locator('button')).to_be_enabled()
        other_card.get_by_role('button', name='使用此账号').click()
        expect(other).to_have_url(f'{live_server}/')
        other.locator('#app-account-toggle').click()
        other.get_by_role('button', name='退出登录', exact=True).click()
        expect(other).to_have_url(f'{live_server}/login')
    finally:
        other_context.close()


@pytest.mark.parametrize('width', [1440, 375, 320])
def test_test_pool_fits_desktop_and_mobile(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{live_server}/test-accounts')
    expect(page.get_by_role('heading', name='选一个账号，开始体验。')).to_be_visible()
    expect(page.locator('[data-account-id]')).to_have_count(10)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'test-results/test-account-pool-{width}.png', full_page=True)
