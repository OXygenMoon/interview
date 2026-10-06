"""Exercise design previews without a database or external services."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect


STATIC_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'static'
DESIGNS = [
    '01-studio', '02-editorial', '03-terminal', '04-brutal', '05-zen',
    '06-glass', '07-playful', '08-swiss', '09-board', '10-academy',
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(scope='module')
def design_server():
    handler = partial(QuietHandler, directory=str(STATIC_ROOT))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/design-lab'
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def design_page(browser_instance):
    context = browser_instance.new_context(locale='zh-CN')
    page = context.new_page()
    errors = []
    bad_responses = []
    external_requests = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: bad_responses.append(
        response.url) if response.status >= 400 else None)

    def check_request(request):
        if not request.url.startswith('http://127.0.0.1:'):
            external_requests.append(request.url)

    page.on('request', check_request)
    yield page
    context.close()
    assert not errors, errors
    assert not bad_responses, bad_responses
    assert not external_requests, external_requests


@pytest.mark.parametrize('design', DESIGNS)
@pytest.mark.parametrize('width', [1440, 768, 390, 320, 844])
def test_design_renders_at_three_sizes(
    design_page, design_server, design, width,
):
    page = design_page
    page.set_viewport_size({'width': width, 'height': 390 if width == 844 else 1050})
    page.goto(f'{design_server}/{design}.html')
    expect(page.locator('main h1')).to_be_visible()
    expect(page.locator('#records tbody tr')).to_have_count(3)
    expect(page.locator('[data-start]').first).to_be_visible()
    overflow = page.evaluate('''() => ({
        viewport: document.documentElement.clientWidth,
        page: document.documentElement.scrollWidth
    })''')
    assert overflow['page'] <= overflow['viewport'] + 1, overflow


@pytest.mark.parametrize('design', DESIGNS)
def test_interview_and_report_interactions(design_page, design_server, design):
    page = design_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(f'{design_server}/{design}.html')
    opener = page.locator('[data-start]').first
    opener.click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_label('目标岗位').select_option('Web 全栈工程师')
    page.get_by_label('面试难度').select_option('压力模式')
    page.get_by_role('button', name='进入面试预览').click()
    expect(page.locator('#dialog-title')).to_have_text('Web 全栈工程师')
    page.get_by_label('你的回答').fill('我负责校园活动平台的前端组件与性能优化，改善了列表加载时间。')
    page.get_by_role('button', name='查看示例反馈').click()
    expect(page.locator('#dialog-title')).to_have_text('让项目经历更具体')
    page.get_by_role('button', name='完成预览').click()
    expect(page.get_by_role('dialog')).not_to_be_visible()
    expect(opener).to_be_focused()
    page.locator('#records [data-report="0"]').click()
    expect(page.locator('.report-number')).to_contain_text('88.4')
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).not_to_be_visible()
    resource = page.locator('[data-resource]').first
    if resource.count():
        resource.click()
        expect(page.locator('.resource-outline')).to_be_visible()
        page.get_by_role('button', name='关闭弹窗').click()


def test_gallery_switch_favorites_comparison_and_viewports(
    design_page, design_server,
):
    page = design_page
    page.set_viewport_size({'width': 1440, 'height': 1050})
    page.goto(f'{design_server}/index.html#08')
    expect(page.locator('#selected-name')).to_have_text('瑞士国际主义')
    expect(page.locator('.concept-card')).to_have_count(10)
    for index, design in enumerate(DESIGNS):
        page.locator(f'[data-concept="{index}"]').click()
        expect(page.frame_locator('#preview').locator('h1')).to_be_visible()
        expect(page.locator('#preview')).to_have_attribute(
            'src', f'{design}.html')
    page.get_by_role('button', name='收藏方案').click()
    page.reload()
    expect(page.get_by_role('button', name='已收藏')).to_have_attribute(
        'aria-pressed', 'true')
    page.get_by_label('只看收藏').check()
    expect(page.locator('.concept-card:visible')).to_have_count(1)
    page.get_by_label('只看收藏').uncheck()
    page.get_by_role('button', name='并排比较').click()
    expect(page.locator('#second-wrap')).to_be_visible()
    page.get_by_label('对比方案').select_option('4')
    expect(page.locator('#comparison')).to_have_attribute('src', '05-zen.html')
    expect(page.frame_locator('#comparison').locator('h1')).to_be_visible()
    for viewport, expected_width in [('mobile', 390), ('tablet', 768)]:
        page.locator(f'button[data-viewport="{viewport}"]').click()
        for frame in ['#preview', '#comparison']:
            actual_width = page.locator(frame).bounding_box()['width']
            assert actual_width == expected_width
    page.get_by_role('button', name='退出比较').click()
    expect(page.locator('#second-wrap')).not_to_be_visible()
    page.locator('button[data-viewport="desktop"]').click()
    page.get_by_role('button', name='下一套设计').click()
    expect(page.locator('#selected-number')).to_have_text('01')


def test_mobile_gallery_and_review(design_page, design_server):
    page = design_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(f'{design_server}/index.html')
    page.get_by_label('只看收藏').check()
    expect(page.locator('#empty-favorites')).to_be_visible()
    page.get_by_label('只看收藏').uncheck()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role('button', name='并排比较').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.goto(f'{design_server}/review.html')
    expect(page.get_by_role('heading', name='先理清层级，再统一设计。')).to_be_visible()
    expect(page.locator('tbody tr')).to_have_count(10)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_board_add_move_and_drag(design_page, design_server):
    page = design_page
    page.set_viewport_size({'width': 1440, 'height': 1050})
    page.goto(f'{design_server}/09-board.html')
    page.get_by_role('button', name='添加任务').click()
    page.get_by_label('任务名称').fill('讲清楚一次代码重构')
    page.get_by_role('button', name='添加到待练习').click()
    column = page.locator('[data-column="0"]')
    expect(column.locator('.task-card')).to_have_count(3)
    column.locator('.task-card').last.get_by_role('button').click()
    expect(page.locator('[data-column="1"] .task-card')).to_have_count(3)
    page.locator('[data-column="0"] .task-card').first.drag_to(
        page.locator('[data-column="2"]'))
    expect(page.locator('[data-column="2"] .task-card')).to_have_count(2)
    expect(page.locator('[data-column="2"] .column-count')).to_have_text('2')


def test_keyboard_and_reduced_motion(design_page, design_server):
    page = design_page
    page.emulate_media(reduced_motion='reduce')
    page.goto(f'{design_server}/01-studio.html')
    page.keyboard.press('Tab')
    expect(page.get_by_role('link', name='跳转到主要内容')).to_be_focused()
    assert page.evaluate(
        'getComputedStyle(document.documentElement).scrollBehavior') == 'auto'
    page.locator('[data-start]').first.focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('[data-start]').first).to_be_focused()
