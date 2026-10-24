"""Local recruitment navigation, grouping, detail links and mobile layouts."""
import pytest
from playwright.sync_api import expect
from .test_core_flows import login

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize('width', [1440, 390])
def test_local_jobs_search_details_and_return(page, live_server, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    login(page, live_server, 'student')
    page.goto(f'{live_server}/jobs')
    expect(page.get_by_role('heading', name='嘉善 · 嘉兴本地招聘')).to_be_visible()
    expect(page.locator('.jobs-row')).to_have_count(1)
    expect(page.get_by_text('2 条来源记录已合并')).to_be_visible()
    page.get_by_label('岗位、企业或关键词').fill('机械')
    page.get_by_label('工作地区').select_option('嘉善')
    page.get_by_label('信息来源').select_option('lagou')
    page.get_by_role('button', name='查询岗位').click()
    expect(page.locator('.jobs-row')).to_have_count(1)
    page.get_by_role('link', name='测试机械设计师', exact=True).click()
    expect(page.get_by_test_id('job-detail')).to_be_visible()
    expect(page.get_by_text('测试职责一', exact=False).first).to_be_visible()
    boss = page.get_by_role('link', name='前往BOSS直聘查看')
    expect(boss).to_have_attribute('href', 'https://www.zhipin.com/job_detail/e2e-only.html')
    expect(boss).to_have_attribute('target', '_blank')
    expect(page.get_by_role('link', name='前往拉勾网查看')).to_have_attribute('href', 'https://www.lagou.com/jobs/999999999.html')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.get_by_role('link', name='返回岗位列表').click()
    expect(page.get_by_label('岗位、企业或关键词')).to_have_value('机械')
    expect(page.get_by_label('工作地区')).to_have_value('嘉善')
    expect(page.get_by_label('信息来源')).to_have_value('lagou')
    page.get_by_label('岗位、企业或关键词').fill('没有这样的岗位')
    page.get_by_role('button', name='查询岗位').click()
    expect(page.get_by_text('没有找到符合条件的岗位')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
