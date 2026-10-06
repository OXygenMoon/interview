"""Browser-level regression coverage for the platform's core workflows."""

import re

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e

PASSWORDS = {
    'student': 'StudentPass123!',
    'interview_student': 'InterviewPass123!',
    'teacher': 'TeacherPass123!',
    'admin': 'AdminPass123!',
}


def login(page, base_url, username):
    page.goto(f'{base_url}/login')
    page.get_by_label('账号').fill(username)
    page.get_by_label('密码').fill(PASSWORDS[username])
    page.get_by_test_id('login-submit').click()


def test_anonymous_login_and_student_authorization(page, live_server):
    page.goto(f'{live_server}/')
    expect(page).to_have_url(re.compile(r'/login(?:\?.*)?$'))
    expect(page.get_by_test_id('login-page')).to_be_visible()

    login(page, live_server, 'student')
    expect(page).to_have_url(f'{live_server}/')
    expect(page.get_by_test_id('student-home')).to_contain_text('端到端学生')

    response = page.goto(f'{live_server}/admin/settings')
    assert response is not None
    assert response.status == 403
    expect(page.get_by_text('Forbidden')).to_be_visible()


def test_student_quiz_retry_and_completion(page, live_server):
    login(page, live_server, 'student')
    page.goto(f'{live_server}/learning')
    expect(page.get_by_test_id('learning-index')).to_contain_text('面试基础训练')
    page.get_by_text('面试基础训练', exact=True).click()
    page.get_by_role('link', name='Quiz 基础知识测验').click()

    page.locator('input[name="q_1"][value="B"]').check()
    page.locator('input[name="q_2"][value="A"]').check()
    page.get_by_test_id('quiz-submit').click()
    expect(page.get_by_text('本次得分：0 分，尚未通过，可以立即重试。')).to_be_visible()
    expect(page.get_by_test_id('quiz-submit')).to_be_visible()

    page.locator('input[name="q_1"][value="A"]').check()
    page.locator('input[name="q_2"][value="B"]').check()
    page.get_by_test_id('quiz-submit').click()
    expect(page.get_by_text('恭喜！通过测验，得分：100 分')).to_be_visible()
    expect(page.get_by_text('测验已通过', exact=True)).to_be_visible()


def test_student_history_opens_completed_report(page, live_server):
    login(page, live_server, 'student')
    page.goto(f'{live_server}/history')
    expect(page.get_by_test_id('history-page')).to_contain_text('后端开发工程师')
    expect(page.get_by_test_id('history-page')).to_contain_text('86')
    page.get_by_title('查看报告').click()

    expect(page).to_have_url(re.compile(r'/interview/summary/\d+$'))
    expect(page.get_by_test_id('interview-summary')).to_contain_text(
        '后端开发工程师 面试报告'
    )
    expect(page.get_by_test_id('interview-summary')).to_contain_text(
        '基础扎实，回答结构清楚'
    )


def test_interview_creation_reaches_live_room(page, live_server):
    login(page, live_server, 'interview_student')
    expect(page.get_by_test_id('student-home')).to_be_visible()
    page.get_by_test_id('open-interview-setup').click()
    expect(page.get_by_test_id('interview-setup')).to_be_visible()

    page.locator('#company-select').select_option(label='未来科技')
    expect(page.locator('#position-select')).to_be_enabled()
    page.locator('#position-select').select_option(label='后端开发工程师')
    page.locator('input[name="difficulty"][value="新手模式"]').check(force=True)
    page.get_by_test_id('start-interview').click()

    expect(page).to_have_url(re.compile(r'/interview/room/\d+$'))
    expect(page.get_by_test_id('interview-room')).to_contain_text(
        '正在面试: 后端开发工程师'
    )
    expect(page.get_by_test_id('interview-room')).to_contain_text(
        '请先做一个简单的自我介绍'
    )

    dialogs = []

    def accept_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.accept()

    page.on('dialog', accept_dialog)
    page.route(
        re.compile(r'.*/api/interview/\d+/finish$'),
        lambda route: route.fulfill(
            status=503,
            content_type='application/json',
            body='{"error":"报告队列不可用"}',
        ),
    )
    finish_button = page.get_by_role('button', name='结束面试')
    finish_button.click()
    expect(finish_button).to_be_enabled()
    expect(finish_button).to_have_text('结束面试')
    expect(page).to_have_url(re.compile(r'/interview/room/\d+$'))
    assert any('提交失败：报告队列不可用' in message for message in dialogs)


def test_teacher_and_admin_role_destinations(page, live_server):
    login(page, live_server, 'teacher')
    expect(page).to_have_url(f'{live_server}/dashboard')
    expect(page.get_by_test_id('teacher-dashboard')).to_contain_text(
        '软件一班 - 班级概况'
    )
    page.goto(f'{live_server}/admin/organization')
    expect(page).to_have_url(f'{live_server}/dashboard')
    expect(page.get_by_text('只有校级管理员可以访问此页面')).to_be_visible()

    page.locator('#app-account-toggle').click()
    page.get_by_title('退出登录').click()
    expect(page).to_have_url(f'{live_server}/login')
    login(page, live_server, 'admin')
    expect(page).to_have_url(f'{live_server}/dashboard')
    page.goto(f'{live_server}/admin/organization')
    expect(page.get_by_test_id('admin-organization')).to_contain_text(
        '智能制造系'
    )
    page.goto(f'{live_server}/admin/interviews')
    expect(page.get_by_test_id('admin-interviews')).to_contain_text(
        '后端开发工程师'
    )
