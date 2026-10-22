"""Admin upload and Bilibili editing through the real student learning flow."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_company_portal import sign_in

pytestmark = pytest.mark.e2e


def test_admin_video_upload_student_playback_and_bilibili_edit(page, browser_instance, live_server, tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('ffmpeg is needed to create a real playback fixture')
    clip = tmp_path / 'lesson.mp4'
    subprocess.run([ffmpeg, '-loglevel', 'error', '-f', 'lavfi', '-i',
        'color=c=0x4338ca:s=640x360:d=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(clip)], check=True, timeout=20)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    sign_in(page, live_server, 'admin', 'AdminPass123!')
    page.goto(live_server + '/admin/learning')
    page.get_by_role('button', name='+ 添加内容').click()
    page.get_by_label('课程标题', exact=True).fill('视频上传与播放测试')
    page.get_by_label('内容类型').select_option('video')
    expect(page.get_by_text('视频来源', exact=True)).to_be_visible()
    page.get_by_label('选择视频', exact=True).set_input_files(clip)
    page.locator('#m-content').fill('这是一节视频课程的说明。')
    page.get_by_role('button', name='保存', exact=True).click()
    row = page.get_by_role('row').filter(has_text='视频上传与播放测试')
    expect(row).to_be_visible()
    lesson_url = row.get_by_role('link', name='预览').get_attribute('href')
    lesson_id = re.search(r'/([0-9]+)$', lesson_url).group(1)

    student_context = browser_instance.new_context(viewport={'width': 1440, 'height': 1000})
    student = student_context.new_page()
    student.on('pageerror', lambda error: errors.append(str(error)))
    try:
        sign_in(student, live_server, 'student', 'StudentPass123!')
        student.goto(live_server + lesson_url)
        video = student.locator('video')
        expect(video).to_be_visible()
        student.wait_for_function('document.querySelector("video").readyState >= 2')
        video.evaluate('(element) => element.play()')
        student.wait_for_function('document.querySelector("video").currentTime > 0.1')
        video.evaluate('(element) => element.pause()')
        student.get_by_role('button', name='标记本节已学完', exact=True).click()
        expect(student.get_by_text('本节已完成', exact=True)).to_be_visible()

        row.get_by_role('button', name='编辑', exact=True).click()
        expect(page.get_by_text('已上传视频；不选择新文件会保留当前视频。')).to_be_visible()
        page.get_by_label('视频来源').select_option('bilibili')
        page.get_by_label('B 站链接或 iframe 嵌入代码').fill(
            '<iframe src="//player.bilibili.com/player.html?bvid=BV1B7411m7LV&p=2" onload="alert(1)"></iframe>')
        artifacts = Path(__file__).resolve().parents[2] / 'test-results'
        page.wait_for_function('getComputedStyle(document.querySelector("#add_material_modal")).opacity === "1"')
        page.screenshot(path=str(artifacts / 'learning-video-admin.png'), full_page=True)
        page.get_by_role('button', name='保存', exact=True).click()
        expect(page.locator('#add_material_modal[open]')).to_have_count(0)
        student.route('https://player.bilibili.com/**', lambda route: route.fulfill(
            status=200, content_type='text/html', body='<p>Bilibili player fixture</p>'))
        student.reload()
        expect(student.locator('iframe')).to_have_attribute('src',
            'https://player.bilibili.com/player.html?bvid=BV1B7411m7LV&p=2&autoplay=0')
        expect(student.get_by_text('本节已完成', exact=True)).to_be_visible()
        assert student.request.get(f'{live_server}/learning/material/{lesson_id}/video').status == 404
        student.set_viewport_size({'width': 390, 'height': 844})
        expect(student.locator('iframe')).to_be_visible()
        assert student.evaluate('document.documentElement.scrollWidth <= innerWidth')
        student.screenshot(path=str(artifacts / 'learning-video-student-mobile.png'), full_page=True)
        assert not errors
    finally:
        student_context.close()
