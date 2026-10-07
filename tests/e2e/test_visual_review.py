"""Timestamped images and text remain usable on desktop and small phones."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from .test_core_flows import login

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1440, 375])
def test_visual_report_has_image_coaching_and_answer_navigation(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    login(page, live_server, 'student')
    page.goto(f'{live_server}/interview/summary/1')
    record = page.get_by_test_id('visual-record')
    expect(record).to_contain_text('01:30')
    expect(record).to_contain_text('头肩居中')
    expect(record).to_contain_text('仪态点评')
    expect(record).to_contain_text('建议将镜头抬至眼睛同高')
    image = record.locator('img')
    image.scroll_into_view_if_needed()
    expect(image).to_be_visible()
    assert image.evaluate('image => image.complete && image.naturalWidth > 0')
    record.get_by_role('link', name='查看对应回答').click()
    answer = page.locator('[id^="answer-"]').first
    expect(answer).to_be_visible()
    expect(answer).to_contain_text('可以补充量化结果。')
    answer.locator('.collapse input[type="checkbox"]').check()
    expect(answer).to_contain_text('说明改进前后的故障率和具体行动。')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    Path('test-results').mkdir(exist_ok=True)
    page.screenshot(path=f'test-results/visual-review-{width}.png', full_page=True)
    page.goto(f'{live_server}/interview/room/1')
    expect(page.get_by_test_id('visual-record')).to_contain_text('01:30')


def test_live_visual_feedback_escapes_keywords_and_shows_timestamp(page, live_server):
    # The shared renderer is also loaded in read-only rooms. Add its target
    # panel to exercise safe text rendering without an external model call.
    login(page, live_server, 'student')
    page.goto(f'{live_server}/interview/room/1')
    page.evaluate('''() => {
        const card = document.createElement('div');
        card.id = 'visual-feedback-card';
        card.innerHTML = '<div id="visual-feedback-content"></div>';
        document.body.appendChild(card);
        updateVisualFeedbackUI({
            elapsed: '02:05', tags: ['<img src=x onerror=window.injected=true>', '头肩居中'],
            comment: '本帧肩部可见，请调整镜头高度。'
        });
    }''')
    card = page.locator('#visual-feedback-card')
    expect(card).to_contain_text('02:05')
    expect(card).to_contain_text('仪态点评：本帧肩部可见')
    expect(card.locator('img')).to_have_count(0)
    assert page.evaluate('window.injected !== true')


@pytest.mark.parametrize('width', [1440, 375])
def test_visual_pager_switches_one_record_and_reveals_answer_links(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    login(page, live_server, 'admin')
    page.goto(f'{live_server}/interview/summary/2')
    review = page.get_by_test_id('visual-review')
    pages = review.locator('[data-visual-page]')
    visible_record = review.locator('[data-testid="visual-record"]:visible')
    expect(pages).to_have_count(9)
    expect(visible_record).to_have_count(1)
    expect(visible_record).to_contain_text('第 1 帧仪态点评')
    expect(pages.first).to_have_attribute('aria-current', 'page')

    pages.nth(1).click()
    expect(visible_record).to_have_count(1)
    expect(visible_record).to_contain_text('02:00')
    expect(visible_record).to_contain_text('画面标签 2')
    expect(visible_record).to_contain_text('第 2 帧仪态点评')
    expect(review.locator('[data-visual-page-status]')).to_have_text('第 2 / 9 条 · 时间戳 02:00')
    assert pages.first.get_attribute('aria-current') is None

    # Native buttons also support keyboard selection, including historical records.
    pages.last.focus()
    pages.last.press('Enter')
    expect(visible_record).to_contain_text('05:30')
    expect(visible_record).to_contain_text('历史记录未保存截图')
    expect(visible_record).to_contain_text('第 9 帧仪态点评')

    answer = page.locator('[id^="answer-"]').nth(5)
    link = answer.get_by_role('link', name='查看画面与仪态点评')
    target = link.get_attribute('href')
    link.click()
    expect(pages.nth(5)).to_have_attribute('aria-current', 'page')
    expect(visible_record).to_contain_text('第 6 帧仪态点评')
    expect(visible_record).to_be_in_viewport()
    visible_record.get_by_role('link', name='查看对应回答').click()
    expect(answer).to_be_in_viewport()

    # A report opened with a record hash selects that page before scrolling.
    page.goto(f'{live_server}/interview/summary/2{target}')
    expect(visible_record).to_have_count(1)
    expect(visible_record).to_contain_text('第 6 帧仪态点评')
    expect(visible_record).to_be_in_viewport()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    page.screenshot(path=f'test-results/visual-pager-{width}.png', full_page=True)
