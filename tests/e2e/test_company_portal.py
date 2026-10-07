"""Real browser coverage for admin onboarding and the company recruitment workspace."""
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def sign_in(page, base_url, username, password):
    page.goto(f'{base_url}/login')
    page.get_by_label('账号', exact=True).fill(username)
    page.get_by_label('密码', exact=True).fill(password)
    page.get_by_test_id('login-submit').click()


def sign_out(page):
    page.get_by_label('打开个人账号菜单').click()
    page.get_by_role('button', name='退出登录', exact=True).click()


def test_company_account_positions_records_recommendations_and_mobile(page, live_server):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    sign_in(page, live_server, 'admin', 'AdminPass123!')
    page.goto(f'{live_server}/admin/partnerships')
    expect(page.get_by_role('heading', name='校企合作管理')).to_be_visible()
    page.get_by_label('所属公司').select_option(label='未来科技')
    page.get_by_label('登录账号', exact=True).fill('company-e2e')
    page.locator('#truename').fill('企业联系人')
    page.get_by_label('初始密码').fill('TemporaryCompany123!')
    page.get_by_role('button', name='开通公司账号').click()
    expect(page.get_by_text('@company-e2e · 企业联系人')).to_be_visible()
    sign_out(page)

    sign_in(page, live_server, 'company-e2e', 'TemporaryCompany123!')
    expect(page).to_have_url(f'{live_server}/change-password')
    page.get_by_label('当前密码').fill('TemporaryCompany123!')
    page.get_by_label('新密码（至少 10 个字符）', exact=True).fill('PermanentCompany123!')
    page.get_by_label('确认新密码').fill('PermanentCompany123!')
    page.get_by_role('button', name='保存新密码').click()
    expect(page).to_have_url(f'{live_server}/company')
    expect(page.get_by_role('heading', name='未来科技', exact=True)).to_be_visible()

    page.get_by_role('link', name='+ 新增面试岗位').click()
    page.get_by_label('岗位名称').fill('企业新增设备维护岗位')
    page.get_by_label('岗位职责与要求').fill('负责基础设备维护与安全检查。')
    page.get_by_role('button', name='保存岗位').click()
    position = page.locator('article').filter(has=page.get_by_role('heading', name='企业新增设备维护岗位'))
    position.get_by_role('link', name='编辑岗位').click()
    page.get_by_label('岗位名称').fill('企业更新设备维护岗位')
    page.get_by_role('button', name='保存岗位').click()
    expect(page.get_by_role('heading', name='企业更新设备维护岗位')).to_be_visible()

    backend = page.locator('article').filter(has=page.get_by_role('heading', name='后端开发工程师', exact=True))
    backend.get_by_role('link', name='一键推荐学生 →').click()
    expect(page.get_by_role('heading', name='1. 端到端学生')).to_be_visible()
    expect(page.get_by_text('87.2', exact=True)).to_be_visible()
    page.get_by_role('link', name='查看递交简历').click()
    expect(page.get_by_test_id('resume-preview')).to_contain_text('熟悉 Python')
    expect(page.locator('.resume-campus')).to_be_visible()
    company_preview = page.locator('#resume-preview').inner_html()
    page.get_by_label('简历模板').select_option('classic')
    expect(page.locator('.resume-classic')).to_be_visible()
    page.get_by_label('简历模板').select_option('campus')
    page.get_by_role('button', name='智能一页纸').click()
    expect(page.get_by_role('button', name='智能一页纸')).to_be_enabled()
    page.emulate_media(media='print')
    expect(page.locator('#resume-preview')).to_have_css('zoom', '1')
    page.emulate_media(media='screen')
    artifact = Path('test-results/company-portal')
    artifact.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifact / 'resume-desktop.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(artifact / 'resume-mobile.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('link', name='返回面试详情').click()
    expect(page.get_by_test_id('interview-summary')).to_be_visible()
    expect(page.get_by_text('我通过指标、告警和压测闭环改进稳定性。')).to_be_visible()
    assert page.locator('#radarChart').evaluate('el => !!window.Chart.getChart(el)')
    expect(page.get_by_role('button', name='进入下一轮 →')).to_have_count(0)
    frame = page.get_by_test_id('visual-record').locator('img')
    expect(frame).to_be_visible()
    assert frame.evaluate('el => el.complete && el.naturalWidth > 0')
    page.get_by_role('link', name='查看对话记录', exact=True).click()
    expect(page.get_by_text('仅供查阅模式，无法发送消息')).to_be_visible()
    expect(page.get_by_label('文字回答')).to_have_count(0)
    page.get_by_role('link', name='查看报告', exact=True).click()

    artifact = Path('test-results/company-portal')
    artifact.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifact / 'interview-desktop.png'), full_page=True)
    for url in ('/company', '/company/positions', '/company/interviews', '/admin/partnerships'):
        page.set_viewport_size({'width': 390, 'height': 844})
        if url == '/admin/partnerships':
            sign_out(page)
            sign_in(page, live_server, 'admin', 'AdminPass123!')
        response = page.goto(f'{live_server}{url}')
        assert response.status == 200
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(artifact / (url.replace('/', '-') + '-mobile.png')), full_page=True)

    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto(f'{live_server}/admin/resumes')
    preview = page.locator('tr').filter(has_text='递交简历排版测试').get_by_role('link', name='预览', exact=True)
    page.goto(live_server + preview.get_attribute('href'))
    expect(page.locator('.resume-campus')).to_be_visible()
    assert page.locator('#resume-preview').inner_html() == company_preview
    assert errors == []

    sign_out(page)
    sign_in(page, live_server, 'student', 'StudentPass123!')
    page.goto(f'{live_server}/resume_dashboard')
    editor = page.locator('a[href^="/resume/edit/"]').first
    page.goto(live_server + editor.get_attribute('href'))
    page.get_by_role('button', name='预览', exact=True).click()
    expect(page.locator('.resume-campus')).to_be_visible()
    assert page.locator('#resume-preview').inner_html() == company_preview
    assert errors == []
