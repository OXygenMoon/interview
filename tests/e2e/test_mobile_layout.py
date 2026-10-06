"""Small-phone and landscape checks, including populated management panels."""

from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_core_flows import login
from tests.e2e.test_playful_ui import ROUTES


pytestmark = pytest.mark.e2e


def layout_metrics(page):
    return page.evaluate('''() => ({
        width: innerWidth, page: document.documentElement.scrollWidth,
        overflow: [...document.querySelectorAll('main *')].filter(el => {
            const r = el.getBoundingClientRect();
            if (!r.width || r.right <= innerWidth + 1) return false;
            for (let p = el.parentElement; p && p !== document.body;
                 p = p.parentElement) {
                if (['auto', 'scroll', 'hidden'].includes(
                    getComputedStyle(p).overflowX)) return false;
            }
            return true;
        }).slice(0, 8).map(el => el.outerHTML.slice(0, 180))
    })''')


@pytest.mark.parametrize('size', [(320, 740), (390, 844), (768, 1024), (844, 390)])
@pytest.mark.parametrize('role', list(ROUTES))
def test_pages_reflow_on_phone_tablet_and_landscape(page, live_server, size, role):
    page.set_viewport_size(dict(zip(('width', 'height'), size)))
    page.emulate_media(reduced_motion='reduce')
    login(page, live_server, role)
    failures = []
    for route in ROUTES[role] + ['/account-links']:
        response = page.goto(f'{live_server}{route}')
        assert response.status == 200, route
        metrics = layout_metrics(page)
        if metrics['page'] > metrics['width'] + 1:
            failures.append((route, metrics))
    assert not failures, failures


@pytest.mark.parametrize('route,opener', [
    ('/admin/learning', '.cat-item'),
    ('/admin/company', '.company-item'),
    ('/admin/organization', '.dept-item'),
])
def test_management_panels_after_selection(page, live_server, route, opener):
    page.set_viewport_size({'width': 320, 'height': 740})
    login(page, live_server, 'admin')
    page.goto(f'{live_server}{route}')
    page.locator(opener).first.click()
    expect(page.locator('#empty-state')).not_to_be_visible()
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics


@pytest.fixture
def touch_page(browser_instance):
    context = browser_instance.new_context(
        viewport={'width': 320, 'height': 740},
        is_mobile=True, has_touch=True, locale='zh-CN',
        reduced_motion='reduce',
    )
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert not errors, errors


def assert_table_cards(page, table):
    expect(table).to_have_class(re.compile(r'responsive-table'))
    metrics = table.evaluate("""table => ({
        width: innerWidth, page: document.documentElement.scrollWidth,
        table: table.getBoundingClientRect().width,
        wrapper: table.parentElement.clientWidth,
        content: table.parentElement.scrollWidth,
        display: getComputedStyle(table).display
    })""")
    assert metrics['display'] == 'block', metrics
    assert metrics['content'] <= metrics['wrapper'] + 1, metrics
    assert metrics['page'] <= metrics['width'] + 1, metrics
    expect(page.locator('.table-scroll-hint')).to_have_count(0)
    records = table.locator('tr.mobile-record:visible')
    if records.count():
        record = records.first
        record.tap()
        expect(page.locator('.mobile-record-dialog')).to_be_visible()
        headers = table.locator('thead th').all_text_contents()
        labels = page.locator('.record-detail-fields dt').all_text_contents()
        assert [' '.join(label.split()) for label in headers] == labels
        metrics = layout_metrics(page)
        assert metrics['page'] <= metrics['width'] + 1, metrics
        page.get_by_role('button', name='关闭记录详情').tap()
        expect(page.locator('.mobile-record-dialog')).not_to_be_visible()


@pytest.mark.parametrize('role', list(ROUTES))
def test_tables_use_cards_and_complete_details_on_touch(touch_page, live_server, role):
    page = touch_page
    login(page, live_server, role)
    for route in ROUTES[role]:
        page.goto(f'{live_server}{route}')
        if route == '/admin/learning':
            page.locator('.cat-item').first.click()
            expect(page.locator('#material-list tr')).to_have_count(2)
        if route == '/dashboard/compare':
            expect(page.locator('#heatHead th').first).to_have_text('班级')
        if route == '/admin/interviews':
            expect(page.locator('.table-scroll-hint')).to_have_count(0)
            Path('test-results').mkdir(exist_ok=True)
            page.screenshot(path='test-results/mobile-interview-table.png', full_page=True)
        if route == '/leaderboard':
            for tab in ['avg', 'max', 'count']:
                page.locator(f'#tab-{tab}').tap()
                assert_table_cards(page, page.locator('table:visible'))
        for table in page.locator('table:visible').all():
            # Long identifiers stay in the detail view without widening the cards.
            if table.locator('tbody td .mobile-cell-value').count():
                table.locator('tbody td .mobile-cell-value').first.evaluate('''cell => {
                    const span = document.createElement('span');
                    span.textContent = 'LongStudentOrPositionIdentifier'.repeat(8);
                    cell.append(span);
                }''')
            assert_table_cards(page, table)
        for control in page.locator('table:visible .mobile-record-open .btn:visible').all():
            box = control.bounding_box()
            assert box['height'] >= 44, (route, box)
        if route == '/admin/interviews':
            page.locator('tr.mobile-record').first.tap()
            expect(page.locator('.mobile-record-dialog').get_by_role('button', name='隐藏', exact=True)).to_be_visible()
            page.get_by_role('button', name='关闭记录详情').tap()
        if route == '/admin/learning':
            expect(page.locator('.cat-item > button').first).to_be_visible()


def create_resume(page, live_server):
    login(page, live_server, 'student')
    expect(page.get_by_test_id('student-home')).to_be_visible()
    return page.evaluate('''async () => {
        const title = '移动端完整简历预览';
        const resumes = await (await fetch('/api/resume/list')).json();
        const existing = resumes.find(resume => resume.title === title);
        if (existing) return existing.id;
        const response = await fetch('/api/resume/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title})
        });
        if (!response.ok) throw new Error(await response.text());
        return (await response.json()).id;
    }''')


@pytest.mark.parametrize('size', [(320, 740), (390, 844), (768, 1024), (844, 390)])
def test_resume_editor_preview_and_print_geometry(page, live_server, size):
    page.set_viewport_size(dict(zip(('width', 'height'), size)))
    page.emulate_media(reduced_motion='reduce')
    resume_id = create_resume(page, live_server)
    page.goto(f'{live_server}/resume/edit/{resume_id}')
    expect(page.locator('#section-editor')).to_be_visible()
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics
    page.get_by_role('button', name='预览', exact=True).click()
    for template in ['modern', 'classic', 'ats', 'campus', 'minimal', 'business', 'creative', 'tech']:
        page.locator('#preview-pane select').select_option(template)
        page.wait_for_function('''() => {
            const preview = document.getElementById('resume-preview');
            const box = preview.getBoundingClientRect();
            return box.width > 0 && box.left >= 0 && box.right <= innerWidth + 1;
        }''')
        assert page.locator('#resume-preview').evaluate('el => el.offsetWidth') == pytest.approx(794, abs=1)
        metrics = layout_metrics(page)
        assert metrics['page'] <= metrics['width'] + 1, (template, metrics)
    page.emulate_media(media='print')
    expect(page.locator('#resume-preview')).to_have_css('zoom', '1')
    expect(page.locator('.app-navbar')).not_to_be_visible()
    page.emulate_media(media='screen')
    page.get_by_role('button', name='编辑', exact=True).click()
    expect(page.locator('#section-editor')).to_be_visible()
    page.locator('#app-account-toggle').click()
    page.get_by_title('退出登录').click()
    login(page, live_server, 'admin')
    page.goto(f'{live_server}/admin/resume/{resume_id}')
    page.wait_for_function('''() => {
        const box = document.getElementById('resume-preview').getBoundingClientRect();
        return box.width > 0 && box.left >= 0 && box.right <= innerWidth + 1;
    }''')
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics
    if size[0] == 320:
        Path('test-results').mkdir(exist_ok=True)
        page.screenshot(path='test-results/mobile-resume-preview.png', full_page=True)


def test_register_and_small_phone_management_modals(touch_page, live_server):
    page = touch_page
    page.goto(f'{live_server}/register')
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics
    login(page, live_server, 'admin')
    for route,button,dialog in [
        ('/admin/company', '+ 新增公司', '#company_modal'),
        ('/admin/organization', '批量导入学生', '#import_modal'),
    ]:
        page.goto(f'{live_server}{route}')
        page.get_by_role('button', name=button, exact=True).tap()
        expect(page.locator(dialog)).to_be_visible()
        box = page.locator(f'{dialog} .modal-box').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 320, box
        assert box['y'] >= 0 and box['y'] + box['height'] <= 740, box
        page.keyboard.press('Escape')


def test_mobile_student_filter_and_table_pagination(touch_page, live_server):
    page = touch_page
    login(page, live_server, 'teacher')
    page.goto(f'{live_server}/teacher/students')
    page.locator('#search-input').fill('没有这名学生')
    page.locator('#search-input').press('Enter')
    expect(page.locator('#no-result-msg')).to_be_visible()
    page.locator('#search-input').fill('端到端学生')
    page.locator('#search-input').press('Enter')
    expect(page.locator('#visible-count')).to_have_text('1')
    assert_table_cards(page, page.locator('#student-table'))

    # Repeat the real server-rendered row to exercise a second client-side page.
    def many_rows(route):
        response = route.fetch()
        html = response.text()
        row = re.search(r'<tbody>\s*(<tr[\s\S]*?</tr>)', html).group(1)
        html = html.replace('<tbody>', '<tbody>' + row * 17, 1)
        route.fulfill(response=response, body=html)

    page.route('**/admin/interviews', many_rows)
    page.goto(f'{live_server}/admin/interviews')
    expect(page.locator('#log-table tbody tr:visible')).to_have_count(15)
    page.get_by_role('button', name='下一页', exact=True).tap()
    expect(page.locator('#log-table tbody tr:visible')).to_have_count(3)
    assert_table_cards(page, page.locator('#log-table'))
    page.get_by_role('button', name='上一页', exact=True).tap()
    expect(page.locator('#log-table tbody tr:visible')).to_have_count(15)


def test_dynamic_article_table_and_long_code_stay_inside_content(touch_page, live_server):
    page = touch_page
    login(page, live_server, 'student')
    page.goto(f'{live_server}/learning/material/1')
    page.locator('article').evaluate('''article => {
        article.innerHTML += `<table><thead><tr><th>项目</th><th>说明</th><th>结果</th></tr></thead>
            <tbody><tr><td>课程内容</td><td>${'LongContent'.repeat(50)}</td><td>完成</td></tr></tbody></table>
            <pre><code>${'long_code_without_spaces'.repeat(50)}</code></pre>`;
    }''')
    assert_table_cards(page, page.locator('article table'))
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics


def test_live_interview_input_and_navigation_fit_touch_landscape(touch_page, live_server):
    page = touch_page
    with page.expect_response('**/api/interview/resumable') as resumable:
        page.goto(f'{live_server}/login')
        page.get_by_label('账号').fill('mobile_interview_student')
        page.get_by_label('密码').fill('MobileInterviewPass123!')
        page.get_by_test_id('login-submit').tap()
    expect(page.get_by_test_id('student-home')).to_be_visible()
    if resumable.value.json()['has_session']:
        page.locator('#resumable_continue_btn').tap()
    else:
        page.get_by_test_id('open-interview-setup').tap()
        expect(page.get_by_test_id('interview-setup')).to_be_visible()
        page.locator('#company-select').select_option(label='未来科技')
        page.locator('#position-select').select_option(label='后端开发工程师')
        page.get_by_test_id('start-interview').tap()
    expect(page.locator('#msg-input')).to_be_visible()
    for width, height in [(320, 740), (844, 390)]:
        page.set_viewport_size({'width': width, 'height': height})
        metrics = layout_metrics(page)
        assert metrics['page'] <= metrics['width'] + 1, metrics
        page.locator('#msg-input').fill('移动端回答输入验证')
        expect(page.locator('#msg-input')).to_have_value('移动端回答输入验证')
        page.locator('#app-nav-reveal').tap()
        expect(page.locator('.app-navbar')).to_be_visible()
        page.locator('#app-menu-toggle').tap()
        expect(page.locator('#app-navigation')).to_be_visible()
        page.keyboard.press('Escape')
        page.locator('#msg-input').tap()
        expect(page.locator('#msg-input')).to_be_focused()


def test_record_details_keep_native_and_inline_management_actions(touch_page, live_server):
    page = touch_page
    login(page, live_server, 'admin')
    prompts = []

    def cancel_action(dialog):
        prompts.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', cancel_action)
    page.goto(f'{live_server}/admin/learning')
    page.locator('.cat-item').first.tap()
    page.locator('tr.mobile-record').first.tap()
    expect(page.locator('.mobile-record-dialog')).to_be_visible()
    page.locator('.mobile-record-dialog').get_by_role('button', name='删除', exact=True).tap()
    assert prompts == ['确定删除吗？']
    expect(page.locator('.mobile-record-dialog')).not_to_be_visible()
    expect(page.locator('#material-list tr')).to_have_count(2)

    page.goto(f'{live_server}/admin/interviews')
    page.locator('tr.mobile-record').first.tap()
    page.locator('.mobile-record-dialog').get_by_role('button', name='隐藏', exact=True).tap()
    assert '确定隐藏这条面试记录吗' in prompts[-1]
    expect(page.locator('.mobile-record-dialog')).not_to_be_visible()


def test_record_keyboard_details_navigation_and_desktop_restore(page, live_server):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, live_server, 'student')
    page.goto(f'{live_server}/')
    record = page.locator('#recent-records-table tr.mobile-record').first
    record.focus()
    page.keyboard.press('Enter')
    expect(page.locator('.mobile-record-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(record).to_be_focused()
    record.get_by_role('button', name='查看详情', exact=True).click()
    page.locator('.mobile-record-dialog').get_by_role('link', name='查看报告').click()
    expect(page).to_have_url(re.compile(r'/interview/summary/\d+$'))
    page.goto(f'{live_server}/')
    Path('test-results').mkdir(exist_ok=True)
    page.screenshot(path='test-results/mobile-recent-record-cards.png', full_page=True)
    page.locator('#recent-records-table').locator('..').locator('..').screenshot(
        path='test-results/mobile-record-card-component.png',
    )
    page.set_viewport_size({'width': 1440, 'height': 1000})
    expect(page.locator('#recent-records-table')).to_have_css('display', 'table')
    expect(page.locator('#recent-records-table')).to_have_attribute('role', 'table')
    expect(page.locator('#recent-records-table thead')).to_be_visible()
    expect(page.locator('#recent-records-table .mobile-record-open').first).not_to_be_visible()
    expect(page.get_by_role('link', name='查看报告')).to_be_visible()


@pytest.mark.parametrize('width', [320, 390, 768, 844])
def test_long_record_titles_wrap_to_two_lines_and_open_complete_details(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 844})
    login(page, live_server, 'student')
    page.goto(f'{live_server}/')
    name = '网络安全项目助理／商务技术支持与企业系统维护' * 4
    page.locator('#recent-records-table .mobile-cell-value .font-bold').first.evaluate(
        '(element, name) => element.textContent = name', name,
    )
    heading = page.locator('#recent-records-table .mobile-record-heading').first
    expect(heading).to_have_text(name)
    assert heading.bounding_box()['height'] <= 49
    metrics = layout_metrics(page)
    assert metrics['page'] <= metrics['width'] + 1, metrics
    page.locator('#recent-records-table .mobile-record-open button').first.click()
    expect(page.locator('#mobile-record-title')).to_have_text(name)
    expect(page.locator('.record-detail-fields')).to_contain_text(name)
    expect(page.locator('.mobile-record-dialog').get_by_role('link', name='查看报告')).to_be_visible()
    page.keyboard.press('Escape')
