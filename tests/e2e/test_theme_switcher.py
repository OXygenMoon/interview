"""Theme choices, persistence and keyboard behavior on the real application."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login
from tests.e2e.test_playful_ui import ROUTES

pytestmark = pytest.mark.e2e

PALETTES = [
    ('奶油', 'playful', 'rgb(255, 246, 239)', 'rgb(131, 85, 111)'),
    ('鼠尾草', 'playful-sage', 'rgb(243, 246, 239)', 'rgb(72, 102, 83)'),
    ('雾蓝', 'playful-blue', 'rgb(241, 245, 249)', 'rgb(70, 107, 145)'),
    ('薰衣草', 'playful-lavender', 'rgb(246, 243, 250)', 'rgb(114, 86, 142)'),
    ('玫瑰', 'playful-rose', 'rgb(255, 243, 244)', 'rgb(150, 86, 111)'),
]


def open_picker(page):
    page.locator('#app-theme-toggle').click()
    expect(page.locator('#app-theme-panel')).to_be_visible()


def choose(page, label):
    page.locator('#app-theme-panel label').filter(has_text=label).click()


@pytest.mark.parametrize('target', ['.app-theme-swatch', '.app-theme-tone-content > span:last-child', '.app-theme-mode > span'])
def test_real_pointer_press_keeps_picker_open_and_switches(page, live_server, target):
    login(page, live_server, 'student')
    open_picker(page)
    label = page.locator('#app-theme-panel label').filter(has_text='暗色主题' if 'mode' in target else '雾蓝')
    label.locator(':scope > span' if 'mode' in target else target).click(delay=150)
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-dark' if 'mode' in target else 'playful-blue')
    expect(page.locator('#app-theme-panel')).to_be_visible()


@pytest.mark.parametrize('width', [1440, 320])
@pytest.mark.parametrize('label,theme,canvas,accent', PALETTES)
def test_palette_updates_page_and_survives_reload(page, live_server, width, label, theme, canvas, accent):
    page.set_viewport_size({'width': width, 'height': 700})
    page.goto(f'{live_server}/login')
    open_picker(page)
    box = page.locator('#app-theme-panel').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    choose(page, label)
    expect(page.locator('html')).to_have_attribute('data-theme', theme)
    expect(page.get_by_role('radio', name=label, exact=True)).to_be_checked()
    assert page.evaluate('getComputedStyle(document.body).backgroundColor') == canvas
    button = page.locator('button.btn-primary').first
    expect(button).to_have_css('background-color', accent)
    assert page.evaluate("localStorage.getItem('interview-ui-theme')") == theme
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', theme)
    expect(page.locator('#app-theme-panel')).not_to_be_visible()


def test_dark_mode_remembers_last_light_tone(page, live_server):
    page.goto(f'{live_server}/login')
    open_picker(page)
    choose(page, '雾蓝')
    choose(page, '暗色主题')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-dark')
    expect(page.locator('#app-theme-tones')).not_to_be_visible()
    assert page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(27, 23, 33)'
    page.reload()
    open_picker(page)
    expect(page.get_by_role('radio', name='暗色主题')).to_be_checked()
    choose(page, '亮色主题')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-blue')
    expect(page.get_by_role('radio', name='雾蓝', exact=True)).to_be_checked()


def test_keyboard_and_outside_dismissal(page, live_server):
    page.goto(f'{live_server}/login')
    toggle = page.locator('#app-theme-toggle')
    toggle.focus()
    page.keyboard.press('Enter')
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.get_by_role('radio', name='亮色主题')).to_be_focused()
    page.keyboard.press('ArrowRight')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-dark')
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('Tab')
    expect(page.get_by_role('radio', name='奶油', exact=True)).to_be_focused()
    page.keyboard.press('ArrowRight')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-sage')
    page.keyboard.press('Escape')
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    open_picker(page)
    page.get_by_label('账号', exact=True).click()
    expect(page.locator('#app-theme-panel')).not_to_be_visible()
    toggle.focus()
    page.keyboard.press('ArrowDown')
    expect(page.locator('#app-theme-panel')).to_be_visible()
    page.keyboard.press('Tab')
    page.keyboard.press('Tab')
    expect(page.locator('#app-theme-panel')).not_to_be_visible()


def test_preferences_sync_between_tabs_and_system_fallback(page, live_server):
    page.emulate_media(color_scheme='light')
    page.goto(f'{live_server}/login')
    other = page.context.new_page()
    other.emulate_media(color_scheme='light')
    other.goto(f'{live_server}/login')
    open_picker(page)
    choose(page, '玫瑰')
    expect(other.locator('html')).to_have_attribute('data-theme', 'playful-rose')
    choose(page, '暗色主题')
    expect(other.locator('html')).to_have_attribute('data-theme', 'playful-dark')
    other.evaluate('localStorage.clear()')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-dark')
    choose(page, '亮色主题')
    page.emulate_media(color_scheme='light')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful')
    other.close()


def test_invalid_or_unavailable_storage_still_allows_switching(page, live_server):
    page.emulate_media(color_scheme='light')
    page.goto(f'{live_server}/login')
    page.evaluate("localStorage.setItem('interview-ui-theme', 'unknown')")
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful')
    page.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});")
    page.reload()
    open_picker(page)
    choose(page, '薰衣草')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-lavender')
    choose(page, '暗色主题')
    choose(page, '亮色主题')
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful-lavender')


@pytest.mark.parametrize('role', list(ROUTES))
@pytest.mark.parametrize('theme', ['playful-blue', 'playful-dark'])
def test_selected_theme_is_shared_by_all_roles_and_pages(page, live_server, role, theme):
    page.set_viewport_size({'width': 390, 'height': 844})
    page.emulate_media(reduced_motion='reduce')
    login(page, live_server, role)
    page.evaluate('(theme) => localStorage.setItem("interview-ui-theme", theme)', theme)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for route in ROUTES[role]:
        page.goto(f'{live_server}{route}')
        expect(page.locator('html')).to_have_attribute('data-theme', theme)
        # Reveal the same control on the immersive interview page.
        if route == '/interview/room/1' and page.locator('#app-nav-reveal').count():
            page.locator('#app-nav-reveal').click()
        open_picker(page)
        expect(page.get_by_role('radio', name='暗色主题' if theme == 'playful-dark' else '亮色主题')).to_be_checked()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        box = page.locator('#app-theme-panel').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 390
        page.keyboard.press('Escape')
    assert not errors, errors
