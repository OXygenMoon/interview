"""Verify the selected theme and the outer navbar on real Flask pages."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login


pytestmark = pytest.mark.e2e

ROUTES = {
    'student': [
        '/', '/learning', '/learning/material/1', '/learning/material/2',
        '/history', '/radar', '/leaderboard', '/resume_dashboard',
        '/profile/basic', '/interview/random', '/interview/summary/1',
        '/interview/room/1', '/change-password',
    ],
    'teacher': [
        '/dashboard', '/dashboard/compare', '/teacher/students',
        '/teacher/student/1', '/admin/interviews',
        '/admin/capability_profile',
    ],
    'admin': [
        '/dashboard', '/admin/resumes', '/admin/company',
        '/admin/learning', '/admin/organization',
        '/admin/random_questions', '/admin/settings',
    ],
}


def assert_shell(page):
    expect(page.locator('html')).to_have_attribute('data-theme', 'playful')
    expect(page.get_by_test_id('app-navbar')).to_be_visible()
    expect(page.get_by_test_id('app-navbar')).to_have_count(1)
    metrics = page.evaluate('''() => {
        const header = document.querySelector('.app-navbar');
        return {
            position: getComputedStyle(header).position,
            parent: header.parentElement.tagName,
            background: getComputedStyle(document.body).backgroundColor,
            pageWidth: document.documentElement.scrollWidth,
            viewport: innerWidth
        };
    }''')
    assert metrics['position'] == 'fixed'
    assert metrics['parent'] == 'BODY'
    assert metrics['background'] == 'rgb(255, 246, 239)'
    assert metrics['pageWidth'] <= metrics['viewport'] + 1, metrics
    header = page.get_by_test_id('app-navbar')
    initial_top = header.bounding_box()['y']
    page.evaluate('scrollTo(0, document.documentElement.scrollHeight)')
    page.wait_for_function('''() => Math.abs(
        scrollY - Math.max(0, document.documentElement.scrollHeight - innerHeight)
    ) < 2''')
    assert abs(header.bounding_box()['y'] - initial_top) < 1


@pytest.mark.parametrize('width', [1440, 768, 390])
@pytest.mark.parametrize('role', list(ROUTES))
def test_all_page_families_share_theme(page, live_server, width, role):
    page.set_viewport_size({'width': width, 'height': 1000})
    page.emulate_media(reduced_motion='reduce')
    login(page, live_server, role)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for route in ROUTES[role]:
        response = page.goto(f'{live_server}{route}')
        assert response.status == 200, route
        assert_shell(page)
    assert not errors, errors


def test_mobile_navigation_and_keyboard(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, live_server, 'student')
    toggle = page.locator('#app-menu-toggle')
    toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.get_by_role('navigation', name='主导航')).to_be_visible()
    page.get_by_role('link', name='能力成长', exact=True).click()
    expect(page).to_have_url(f'{live_server}/radar')
    toggle = page.locator('#app-menu-toggle')
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    toggle.click()
    page.keyboard.press('Escape')
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    toggle.click()
    page.get_by_role('link', name='智能简历中心', exact=True).click()
    expect(page).to_have_url(f'{live_server}/resume_dashboard')


def test_login_shell_at_small_mobile_size(page, live_server):
    page.set_viewport_size({'width': 320, 'height': 700})
    page.emulate_media(reduced_motion='reduce')
    page.goto(f'{live_server}/login')
    assert_shell(page)
    expect(page.get_by_label('账号')).to_be_visible()
    expect(page.get_by_label('密码')).to_be_visible()


def test_admin_dropdown_keeps_all_management_links(page, live_server):
    login(page, live_server, 'admin')
    page.locator('.app-nav-more summary').click()
    for label in [
        '班级对比看板', '学生简历预览', '课程内容管理',
        '组织与学生管理', '企业与岗位管理', '随机问题题库', '系统设置',
    ]:
        expect(page.get_by_role('link', name=label, exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.app-nav-more')).not_to_have_attribute('open', '')


def test_resume_editor_and_export_keep_shell_separate(page, live_server):
    login(page, live_server, 'student')
    expect(page.get_by_test_id('student-home')).to_be_visible()
    result = page.evaluate('''async () => {
        const response = await fetch('/api/resume/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: '柔彩界面回归简历'})
        });
        return {status: response.status, data: await response.json()};
    }''')
    assert result['status'] == 200
    resume_id = result['data']['id']
    page.goto(f'{live_server}/resume/edit/{resume_id}')
    expect(page.locator('#section-editor')).to_be_visible()
    assert_shell(page)
    page.emulate_media(media='print')
    expect(page.get_by_test_id('app-navbar')).not_to_be_visible()
    page.emulate_media(media='screen')
    expect(page.get_by_test_id('app-navbar')).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.emulate_media(reduced_motion='reduce')
    assert_shell(page)
    page.get_by_role('button', name='预览', exact=True).click()
    expect(page.locator('#preview-pane')).to_be_visible()


def test_management_content_and_modal_fit_mobile(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    page.emulate_media(reduced_motion='reduce')
    login(page, live_server, 'admin')
    page.goto(f'{live_server}/admin/organization')
    page.locator('.dept-item').first.click()
    expect(page.locator('#class-content')).to_be_visible()
    assert_shell(page)
    page.get_by_role('button', name='批量导入学生', exact=True).click()
    expect(page.locator('#import_modal')).to_be_visible()
    box = page.locator('#import_modal .modal-box').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    page.keyboard.press('Escape')
    page.goto(f'{live_server}/admin/company')
    page.locator('.company-item').first.click()
    expect(page.locator('#position-content')).to_be_visible()
    assert_shell(page)


def test_admin_resume_preview_uses_theme_and_clean_print(page, live_server):
    login(page, live_server, 'student')
    expect(page.get_by_test_id('student-home')).to_be_visible()
    resume_id = page.evaluate("""async () => {
        const response = await fetch('/api/resume/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: '教师预览界面回归'})
        });
        return (await response.json()).id;
    }""")
    page.locator('#app-account-toggle').click()
    page.get_by_title('退出登录').click()
    login(page, live_server, 'admin')
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.emulate_media(media='screen', reduced_motion='reduce')
        page.goto(f'{live_server}/admin/resume/{resume_id}')
        expect(page.get_by_text('只读预览', exact=True)).to_be_visible()
        assert_shell(page)
        page.emulate_media(media='print')
        expect(page.get_by_test_id('app-navbar')).not_to_be_visible()
