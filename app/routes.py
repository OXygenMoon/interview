import json
import secrets

import pandas as pd
from io import BytesIO
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file, abort
from flask_login import login_required, current_user
from collections import Counter
from datetime import datetime
from . import db  # 确保导入 db 实例，用于 db.session.add/commit
from .models import InterviewSession, ChatMessage, User, Department, SchoolClass, LearningCategory, LearningMaterial, UserLearningProgress, LearningAttempt, Company, Resume, SystemConfig
from .config import Config
from .decorators import teacher_required, admin_required
from .services.question_bank import get_random_interview_questions, sanitize_questions
from .services.visual_review import visual_record
from .utils.session_state import (
    mark_reviewed,
    expire_stale_sessions,
    reap_stuck_reports,
    soft_delete_session,
    restore_soft_deleted_session,
)

bp = Blueprint('routes', __name__)


def _can_view_interview(session):
    student = db.session.get(User, session.user_id)
    return bool(student) and (
        current_user.id == student.id
        or current_user.role == 'admin'
        or (current_user.role == 'dept_head' and current_user.department == student.department)
        or (current_user.role == 'teacher' and current_user.department == student.department
            and current_user.class_name == student.class_name)
    )


@bp.route('/interview/<int:session_id>/frames/<int:message_id>')
@login_required
def interview_frame(session_id, message_id):
    session = InterviewSession.query.get_or_404(session_id)
    if session.status == 'deleted':
        abort(404)
    if not _can_view_interview(session):
        abort(403)
    message = ChatMessage.query.filter_by(id=message_id, session_id=session_id, sender='user').first_or_404()
    if not message.visual_image:
        abort(404)
    mimetype = 'image/png' if message.visual_image.startswith(b'\x89PNG') else 'image/jpeg'
    response = send_file(BytesIO(message.visual_image), mimetype=mimetype)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# ===============================================================
#  学生端核心功能 (首页、历史、聊天、报告)
# ===============================================================

@bp.app_template_filter('time_ago')
def time_ago(value):
    """
    将 datetime 转换为 'x 分钟前' 的格式
    """
    if not value: return ""
    now = datetime.now()
    diff = now - value
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    elif seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    elif seconds < 604800:
        return f"{int(seconds // 86400)} 天前"
    elif seconds < 2592000:
        return f"{int(seconds // 604800)} 周前"
    else:
        return value.strftime('%Y-%m-%d')


@bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    """系统全局设置"""
    if request.method == 'POST':
        # 处理开关设置
        enable_tts = request.form.get('enable_tts') == 'on'
        enable_realtime_voice = request.form.get('enable_realtime_voice') == 'on'
        enable_video = request.form.get('enable_video') == 'on'

        # 保存设置
        SystemConfig.set('enable_tts', 'true' if enable_tts else 'false', '是否启用面试官语音输出 (TTS)')
        SystemConfig.set('enable_realtime_voice', 'true' if enable_realtime_voice else 'false', '是否启用实时语音交互')
        SystemConfig.set('enable_video', 'true' if enable_video else 'false', '是否启用视频面试 (摄像头与视觉分析)')

        # 冷却系统配置
        try:
            ttl = int(request.form.get('session_ttl_minutes', 10))
            abandon_cd = int(request.form.get('cooldown_abandon_minutes', 10))
            complete_cd = int(request.form.get('cooldown_complete_minutes', 30))
            audio_retention_days = int(request.form.get('audio_retention_days', 30))
            temp_retention_hours = int(request.form.get('temp_retention_hours', 24))
        except ValueError:
            ttl, abandon_cd, complete_cd = 10, 10, 30
            audio_retention_days, temp_retention_hours = 30, 24
        requires_review = request.form.get('cooldown_requires_review') == 'on'

        SystemConfig.set('session_ttl_minutes', str(max(1, ttl)), 'ongoing 面试无活动多久后判为 expired（分钟）')
        SystemConfig.set('cooldown_abandon_minutes', str(max(0, abandon_cd)), '中途放弃后再次开始面试的冷却罚时（分钟）')
        SystemConfig.set('cooldown_complete_minutes', str(max(0, complete_cd)), '完成一次面试后再次开始的冷却时长（分钟）')
        SystemConfig.set('cooldown_requires_review', 'true' if requires_review else 'false', '完成后是否强制复盘上次报告才能开始下一次')
        SystemConfig.set('audio_retention_days', str(max(0, audio_retention_days)), 'TTS 音频保留天数')
        SystemConfig.set('temp_retention_hours', str(max(1, temp_retention_hours)), '临时文件保留小时数')

        flash('系统设置已更新', 'success')
        return redirect(url_for('routes.admin_settings'))

    # 读取设置
    enable_tts = SystemConfig.get('enable_tts', 'true') == 'true'
    enable_realtime_voice = SystemConfig.get('enable_realtime_voice', 'true') == 'true'
    enable_video = SystemConfig.get('enable_video', 'true') == 'true'
    cooldown = {
        'session_ttl_minutes': SystemConfig.get('session_ttl_minutes', '10'),
        'cooldown_abandon_minutes': SystemConfig.get('cooldown_abandon_minutes', '10'),
        'cooldown_complete_minutes': SystemConfig.get('cooldown_complete_minutes', '30'),
        'cooldown_requires_review': SystemConfig.get('cooldown_requires_review', 'true') == 'true',
        'audio_retention_days': SystemConfig.get('audio_retention_days', '30'),
        'temp_retention_hours': SystemConfig.get('temp_retention_hours', '24'),
    }

    return render_template('admin_settings.html', enable_tts=enable_tts, enable_realtime_voice=enable_realtime_voice,
                           enable_video=enable_video, cooldown=cooldown)


@bp.route('/admin/random_questions', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_random_questions():
    """管理员：随机问题题库配置"""
    if request.method == 'POST':
        raw_text = request.form.get('questions_text', '')
        lines = [line.strip() for line in raw_text.splitlines()]
        questions = sanitize_questions(lines)
        if len(questions) < 3:
            flash('请至少提供 3 道有效且不重复的问题（每题至少 8 个字符）。', 'error')
            return render_template('admin_random_questions.html', questions=lines), 400

        SystemConfig.set(
            'random_interview_questions',
            json.dumps(questions, ensure_ascii=False),
            '随机问题面试题库（JSON数组）'
        )
        flash(f'随机问题题库已更新，共 {len(questions)} 题', 'success')
        return redirect(url_for('routes.admin_random_questions'))

    questions = get_random_interview_questions()
    return render_template('admin_random_questions.html', questions=questions)


@bp.route('/admin/company')
@login_required
@admin_required
def admin_company():
    """公司/岗位管理页面"""
    companies = Company.query.order_by(Company.created_at.desc()).all()
    return render_template('admin_company.html', companies=companies)


@bp.route('/admin/resumes')
@login_required
@admin_required
def admin_resumes():
    """管理员：查看全校学生简历（只读预览）"""
    # 取出所有简历，并 join 用户信息用于展示
    resumes = Resume.query.join(User).order_by(Resume.updated_at.desc()).all()
    return render_template('admin_resumes.html', resumes=resumes)


@bp.route('/admin/resume/<int:resume_id>')
@login_required
@admin_required
def admin_resume_preview(resume_id):
    """管理员：只读预览指定简历"""
    resume = Resume.query.get_or_404(resume_id)
    student = db.session.get(User, resume.user_id)
    return render_template('admin_resume_preview.html', resume=resume, student=student)


@bp.route('/')
@login_required
def home():
    """首页/仪表盘"""

    # 1. 角色检查
    if current_user.role != 'student':
        return redirect(url_for('routes.dashboard'))

    # 1.5 懒清理：过期 ongoing、卡死的 processing
    expire_stale_sessions(current_user.id)
    reap_stuck_reports(current_user.id)

    # 2. 查询历史记录 (修改点：包含 completed 和 processing)
    # 使用 .in_(['completed', 'processing']) 来同时获取两种状态
    history_sessions = InterviewSession.query \
        .filter(
        InterviewSession.user_id == current_user.id,
        InterviewSession.status.in_(['completed', 'processing', 'failed'])
    ) \
        .order_by(InterviewSession.start_time.desc()) \
        .all()

    # 3. 计算仪表盘统计数据 (修改点：只统计已完成的，避免"生成中"的0分拉低平均分)
    # 筛选出真正完成的 session 用于计算
    finished_sessions = [s for s in history_sessions if s.status == 'completed']

    stats = {
        'total_count': len(finished_sessions),  # 或者用 len(history_sessions) 看你想不想把生成中的算进总场次
        'avg_score': 0,
        'max_score': 0,
        'latest_trend': 0
    }

    if stats['total_count'] > 0:
        scores = [s.total_score for s in finished_sessions if s.total_score is not None]
        if scores:
            stats['avg_score'] = round(sum(scores) / len(scores), 1)
            stats['max_score'] = max(scores)

            # 计算最近一次得分与平均分的差距
            # 注意：finished_sessions 已经是按时间倒序过滤出来的了
            latest_score = scores[0]
            stats['latest_trend'] = round(latest_score - stats['avg_score'], 1)

    # 获取用户的所有简历 (用于发起面试时选择)
    my_resumes = Resume.query.filter_by(user_id=current_user.id).order_by(Resume.updated_at.desc()).all()

    return render_template(
        'index.html',
        current_user=current_user,
        sessions=history_sessions,  # 传给模板的是包含"生成中"的全量列表
        stats=stats,
        voice_options=Config.VOLC_AVAILABLE_VOICES,
        my_resumes=my_resumes
    )


@bp.route('/interview/random')
@login_required
def random_interview_page():
    """随机问题面试页面（学生端）"""
    if current_user.role != 'student':
        flash("只有学生可以使用随机问题面试", "warning")
        return redirect(url_for('routes.dashboard'))

    return render_template('random_interview.html')


@bp.route('/leaderboard')
@login_required
def leaderboard():
    """
    学生端：班级排行榜
    可以看到班级排名，包括：平均得分排名、最高分排名、面试次数排名
    """
    if current_user.role != 'student':
        flash("只有学生可以查看班级排行榜", "warning")
        return redirect(url_for('routes.dashboard'))
    
    # 1. 获取同班同学
    classmates = User.query.filter_by(
        department=current_user.department,
        class_name=current_user.class_name,
        role='student',
        active=True,
    ).all()
    
    # 2. 准备数据容器
    rank_data = []
    
    for student in classmates:
        # 获取该生已完成的面试
        sessions = InterviewSession.query.filter_by(user_id=student.id, status='completed').all()
        count = len(sessions)
        
        avg_score = 0
        max_score = 0
        last_active = None
        
        if count > 0:
            scores = [s.total_score for s in sessions if s.total_score is not None]
            if scores:
                avg_score = round(sum(scores) / len(scores), 1)
                max_score = max(scores)
            
            # 计算最近活跃时间
            last_active = max(s.start_time for s in sessions)
        
        rank_data.append({
            'user': student,
            'count': count,
            'avg_score': avg_score,
            'max_score': max_score,
            'last_active': last_active
        })
    
    # 3. 生成三个维度的排名列表
    # A. 平均分排名 (降序)
    avg_rank_list = sorted(rank_data, key=lambda x: x['avg_score'], reverse=True)
    # 只取前 20 名展示，避免太长
    avg_rank_list = avg_rank_list[:20]
    
    # B. 最高分排名 (降序)
    max_rank_list = sorted(rank_data, key=lambda x: x['max_score'], reverse=True)
    max_rank_list = max_rank_list[:20]
    
    # C. 勤奋度排名 (次数降序)
    count_rank_list = sorted(rank_data, key=lambda x: x['count'], reverse=True)
    count_rank_list = count_rank_list[:20]

    # D. 计算当前用户在完整列表中的排名位置
    avg_rank_full = sorted(rank_data, key=lambda x: x['avg_score'], reverse=True)
    max_rank_full = sorted(rank_data, key=lambda x: x['max_score'], reverse=True)
    count_rank_full = sorted(rank_data, key=lambda x: x['count'], reverse=True)

    def find_rank(sorted_list, user_id):
        for i, item in enumerate(sorted_list):
            if item['user'].id == user_id:
                return i + 1
        return None

    my_avg_rank = find_rank(avg_rank_full, current_user.id)
    my_max_rank = find_rank(max_rank_full, current_user.id)
    my_count_rank = find_rank(count_rank_full, current_user.id)

    return render_template('leaderboard.html',
                           current_user=current_user,
                           avg_rank=avg_rank_list,
                           max_rank=max_rank_list,
                           count_rank=count_rank_list,
                           my_avg_rank=my_avg_rank,
                           my_max_rank=my_max_rank,
                           my_count_rank=my_count_rank)


@bp.route('/history')
@login_required
def history():
    """历史记录与统计分析页面"""

    # 1. 查询记录 (修改点：同样包含 completed 和 processing)
    # 注意这里原代码是 .asc() 正序，为了统计图表方便
    sessions = InterviewSession.query \
        .filter(
        InterviewSession.user_id == current_user.id,
        InterviewSession.status.in_(['completed', 'processing', 'failed'])
    ) \
        .order_by(InterviewSession.start_time.asc()) \
        .all()

    # 2. 统计逻辑 (修改点：只用已完成的数据画图)
    finished_sessions = [s for s in sessions if s.status == 'completed']

    total_count = len(finished_sessions)
    avg_score = 0
    max_score = 0
    recent_trend = []
    date_labels = []
    role_dist = {}

    if total_count > 0:
        scores = [s.total_score for s in finished_sessions if s.total_score is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        max_score = max(scores) if scores else 0
        recent_trend = scores
        date_labels = [s.start_time.strftime('%m-%d') for s in finished_sessions]
        roles = [s.target_role for s in finished_sessions]
        role_dist = dict(Counter(roles))

    # 列表显示时通常习惯倒序 (最近的在上面)，这里反转一下传给表格
    # 注意：这里传的是 sessions (全量)，所以列表里会显示"生成中"
    sessions_reversed = sessions[::-1]

    return render_template(
        'history.html',
        current_user=current_user,
        sessions=sessions_reversed,
        stats={
            'total_count': total_count,
            'avg_score': avg_score,
            'max_score': max_score,
            'recent_trend': recent_trend,
            'date_labels': date_labels,
            'role_dist_keys': list(role_dist.keys()),
            'role_dist_values': list(role_dist.values())
        }
    )


# === 面试聊天室 ===
@bp.route('/interview/room/<int:session_id>')
@login_required
def interview_room(session_id):
    """面试聊天室 / 历史回顾"""
    session = InterviewSession.query.get_or_404(session_id)
    if session.status == 'deleted':
        abort(404)
    student = db.session.get(User, session.user_id)

    # === 1. 权限检查 ===
    is_owner = (current_user.id == student.id)
    is_teacher_allowed = False

    if current_user.role in ['teacher', 'dept_head', 'admin']:
        if current_user.role == 'admin':
            is_teacher_allowed = True
        elif current_user.role == 'dept_head' and current_user.department == student.department:
            is_teacher_allowed = True
        elif (
            current_user.role == 'teacher'
            and current_user.department == student.department
            and current_user.class_name == student.class_name
        ):
            is_teacher_allowed = True

    if not (is_owner or is_teacher_allowed):
        flash("您无权访问该面试房间", "error")
        return redirect(url_for('routes.home'))

    # === 2. 动态模板与只读模式 ===
    base_template = 'base.html'
    is_read_only = False

    if current_user.role != 'student':
        base_template = 'teacher_base.html'
        is_read_only = True
    elif session.status == 'completed':
        is_read_only = True

    messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
    
    # 获取全局配置
    enable_video = SystemConfig.get('enable_video', 'true') == 'true'
    enable_realtime_voice = SystemConfig.get('enable_realtime_voice', 'true') == 'true'

    return render_template('chat.html',
                           session=session,
                           messages=messages,
                           current_user=current_user,
                           base_template=base_template,
                           is_read_only=is_read_only,
                           enable_video=enable_video,
                           enable_realtime_voice=enable_realtime_voice,
                           enable_tts=SystemConfig.get('enable_tts', 'true') == 'true',
                           visual_records={msg.id: record for msg in messages
                                           if (record := visual_record(msg, session))})


# === 面试报告页 ===
@bp.route('/interview/summary/<int:session_id>')
@login_required
def interview_summary(session_id):
    """面试结果总结页"""
    session = InterviewSession.query.get_or_404(session_id)
    if session.status == 'deleted':
        abort(404)
    student = db.session.get(User, session.user_id)

    # === 1. 权限检查 ===
    is_owner = (current_user.id == student.id)
    is_teacher_allowed = False

    if current_user.role in ['teacher', 'dept_head', 'admin']:
        if current_user.role == 'admin':
            is_teacher_allowed = True
        elif current_user.role == 'dept_head' and current_user.department == student.department:
            is_teacher_allowed = True
        elif (
            current_user.role == 'teacher'
            and current_user.department == student.department
            and current_user.class_name == student.class_name
        ):
            is_teacher_allowed = True

    if not (is_owner or is_teacher_allowed):
        flash("您无权访问该报告", "error")
        return redirect(url_for('routes.home'))

    # 学生本人查看已完成的报告 → 标记已复盘（满足冷却系统的复盘门槛）
    if is_owner and session.status == 'completed':
        mark_reviewed(session)

    messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()

    # === 2. 动态决定继承哪个模板 ===
    base_template = 'teacher_base.html' if current_user.role != 'student' else 'base.html'

    return render_template('summary.html',
                           session=session,
                           current_user=current_user,
                           messages=messages,
                           base_template=base_template,
                           visual_records={msg.id: record for msg in messages
                                           if (record := visual_record(msg, session))})


# === 个人与杂项 ===
@bp.route('/profile')
@login_required
def profile():
    return redirect(url_for('routes.home'))


@bp.route('/avatar/<name>')
def avatar_generator(name):
    return "https://api.dicebear.com/7.x/avataaars/svg?seed=" + name


@bp.route('/profile/basic', methods=['GET', 'POST'])
@login_required
def profile_basic():
    """个人基础信息维护页面"""
    if request.method == 'POST':
        # 保存基础信息
        info = {
            'name': request.form.get('name'),
            'job_target': request.form.get('job_target'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'location': request.form.get('location'),
            'self_evaluation': request.form.get('self_evaluation')
        }
        current_user.profile_info = info
        db.session.commit()
        flash('基础信息已保存', 'success')
        return redirect(url_for('routes.profile_basic'))
        
    return render_template('profile_basic.html', user=current_user)


@bp.route('/resume_dashboard', methods=['GET', 'POST'])
@login_required
def resume_dashboard():
    """简历管理看板 (含个人基础信息)"""
    
    # 如果是 POST 请求，说明是在保存基础信息
    if request.method == 'POST':
        info = {
            'name': request.form.get('name'),
            'job_target': request.form.get('job_target'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'location': request.form.get('location'),
            'self_evaluation': request.form.get('self_evaluation')
        }
        current_user.profile_info = info
        db.session.commit()
        flash('基础信息已保存', 'success')
        return redirect(url_for('routes.resume_dashboard'))

    resumes = Resume.query.filter_by(user_id=current_user.id).order_by(Resume.updated_at.desc()).all()
    return render_template('resume_dashboard.html', resumes=resumes, user=current_user)


@bp.route('/resume/edit/<int:resume_id>')
@login_required
def resume_edit(resume_id):
    """简历编辑器 (指定ID)"""
    resume = Resume.query.get_or_404(resume_id)
    if resume.user_id != current_user.id:
        flash('无权访问此简历', 'error')
        return redirect(url_for('routes.resume_dashboard'))
    return render_template('resume_editor.html', resume=resume)


@bp.route('/resume_builder')
@login_required
def resume_builder():
    """
    旧版入口重定向到仪表盘
    """
    return redirect(url_for('routes.resume_dashboard'))



# ===============================================================
#  教师端 / 管理端核心功能
# ===============================================================

@bp.route('/dashboard')
@login_required
@teacher_required
def dashboard():
    """根据角色自动展示不同的管理数据"""
    query = InterviewSession.query.join(
        User,
        InterviewSession.user_id == User.id,
    ).filter(InterviewSession.status == 'completed')
    title = "管理后台"

    if current_user.role == 'teacher':
        query = query.filter(
            User.department == current_user.department,
            User.class_name == current_user.class_name,
        )
        title = f"{current_user.class_name} - 班级概况"
    elif current_user.role == 'dept_head':
        query = query.filter(User.department == current_user.department)
        title = f"{current_user.department} - 系部概况"
    elif current_user.role == 'admin':
        title = "全校数据大盘"

    sessions = query.order_by(InterviewSession.start_time.desc()).all()

    total_interviews = len(sessions)
    scores = [s.total_score for s in sessions if s.total_score is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    student_stats = {}
    for interview in sessions:
        if interview.total_score is None or not interview.user:
            continue
        row = student_stats.setdefault(interview.user_id, {
            'user': interview.user,
            'scores': [],
            'latest_session_id': interview.id,
        })
        row['scores'].append(interview.total_score)
    top_students = []
    for row in student_stats.values():
        top_students.append({
            'user': row['user'],
            'avg_score': round(sum(row['scores']) / len(row['scores']), 1),
            'count': len(row['scores']),
            'latest_session_id': row['latest_session_id'],
        })
    top_students.sort(key=lambda row: (row['avg_score'], row['count']), reverse=True)
    top_students = top_students[:5]

    return render_template('dashboard.html',
                           title=title,
                           sessions=sessions,
                           total_interviews=total_interviews,
                           avg_score=avg_score,
                           top_students=top_students)


@bp.route('/dashboard/compare')
@login_required
@teacher_required
def dashboard_compare():
    """班级/系部对比看板页（图表由 /api/insights/compare 填充）。"""
    return render_template('compare.html')


@bp.route('/admin/capability_profile')
@login_required
@teacher_required
def admin_capability_profile():
    """能力画像分析 (支持全校/系部/班级三级视图)"""
    
    # === 1. 参数获取与权限控制 ===
    scope = request.args.get('scope') # 'school', 'department', 'class'
    selected_dept = request.args.get('dept_name')
    selected_class = request.args.get('class_name')
    
    # 默认逻辑
    if not scope:
        if current_user.role == 'admin': 
            scope = 'school'
        elif current_user.role == 'dept_head': 
            scope = 'department'
            selected_dept = current_user.department
        elif current_user.role == 'teacher': 
            scope = 'class'
            selected_class = current_user.class_name

    # 强制权限收敛
    if current_user.role == 'teacher':
        scope = 'class'
        selected_class = current_user.class_name
        selected_dept = current_user.department
    elif current_user.role == 'dept_head':
        # 系主任只能看本系，不能看全校
        if scope == 'school': 
            scope = 'department'
        selected_dept = current_user.department

    # === 2. 构建学生查询 ===
    query = User.query.filter_by(role='student')
    display_title = "全校能力画像"
    
    if scope == 'school':
        display_title = "全校能力画像"
        selected_dept = None
        selected_class = None
        
    elif scope == 'department':
        if selected_dept:
            query = query.filter_by(department=selected_dept)
            display_title = f"{selected_dept} - 能力画像"
        else:
            # 如果没选系，不显示任何数据，等待用户选择
            query = query.filter(False)
            
    elif scope == 'class':
        if selected_class:
            if current_user.role == 'admin' and not selected_dept:
                query = query.filter(False)
                display_title = "请先选择系部，再选择班级"
            else:
                query = query.filter_by(class_name=selected_class)
                display_title = f"{selected_class} - 能力画像"
                if selected_dept:
                    query = query.filter_by(department=selected_dept)
        else:
            # 如果没选班级，不显示数据
            query = query.filter(False)

    students = query.all()
    student_ids = [s.id for s in students]
    
    # === 3. 获取下拉菜单数据 (用于前端筛选) ===
    departments_list = []
    classes_list = []
    
    if current_user.role == 'admin':
        # 管理员可以看到所有系
        departments_list = [d.name for d in Department.query.all()]
        
        # 如果当前选了系，则加载该系的班级
        if selected_dept:
            dept_obj = Department.query.filter_by(name=selected_dept).first()
            if dept_obj:
                classes_list = [c.name for c in dept_obj.classes]
        
    elif current_user.role == 'dept_head':
        # 系主任只能看本系的班级
        dept_obj = Department.query.filter_by(name=current_user.department).first()
        if dept_obj:
            classes_list = [c.name for c in dept_obj.classes]

    # === 4. 核心数据计算 (复用原有逻辑，但基于动态 query) ===
    if not student_ids:
         return render_template('admin_class_profile.html', 
                                has_data=False, 
                                display_title=display_title,
                                scope=scope,
                                selected_dept=selected_dept,
                                selected_class=selected_class,
                                departments_list=departments_list,
                                classes_list=classes_list)

    # 获取有效面试
    sessions = InterviewSession.query.filter(
        InterviewSession.user_id.in_(student_ids),
        InterviewSession.status == 'completed'
    ).all()
    
    if not sessions:
         return render_template('admin_class_profile.html', 
                                has_data=False, 
                                display_title=display_title,
                                scope=scope,
                                selected_dept=selected_dept,
                                selected_class=selected_class,
                                departments_list=departments_list,
                                classes_list=classes_list)

    # --- A. 整体五维雷达 ---
    dimensions = ["专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度"]
    dim_totals = {d: 0 for d in dimensions}
    dim_counts = {d: 0 for d in dimensions}
    
    # --- B. 能力偏差 ---
    weakness_alerts = [] 
    
    student_radars = {} 
    
    for s in sessions:
        if not s.radar_data: continue
        uid = s.user_id
        if uid not in student_radars:
            student_radars[uid] = {d: [] for d in dimensions}
        for dim in dimensions:
            score = s.radar_data.get(dim, 0)
            dim_totals[dim] += score
            dim_counts[dim] += 1
            student_radars[uid][dim].append(score)
            
    # 计算整体平均 (Group Average)
    group_avg_radar = {}
    for dim in dimensions:
        count = dim_counts[dim]
        group_avg_radar[dim] = round(dim_totals[dim] / count, 1) if count > 0 else 0

    # 计算学生偏差
    student_info_map = {s.id: s for s in students}
    for uid, radar_lists in student_radars.items():
        user = student_info_map.get(uid)
        if not user: continue
        
        user_avgs = {}
        for dim in dimensions:
            scores = radar_lists[dim]
            if not scores: continue
            u_avg = sum(scores) / len(scores)
            user_avgs[dim] = u_avg
            
            # 偏差检测：低于平均分 15 分
            g_avg = group_avg_radar.get(dim, 0)
            if u_avg < (g_avg - 15):
                weakness_alerts.append({
                    'student': user.truename,
                    'student_id': user.student_id,
                    'class_name': user.class_name, # 多加一个班级显示，因为可能是全校视图
                    'dim': dim,
                    'score': round(u_avg, 1),
                    'group_avg': g_avg,
                    'diff': round(u_avg - g_avg, 1)
                })

    # --- C. 薄弱点 ---
    sorted_dims = sorted(group_avg_radar.items(), key=lambda x: x[1])
    weak_dims = sorted_dims[:2]

    # --- D. 分布 ---
    grade_dist = {'S': 0, 'A': 0, 'B': 0, 'C': 0, 'D': 0}
    for uid, radar_lists in student_radars.items():
        all_scores = []
        for d in dimensions:
            all_scores.extend(radar_lists[d])
        if not all_scores: continue
        final_avg = sum(all_scores) / len(all_scores)
        
        if final_avg >= 90: grade_dist['S'] += 1
        elif final_avg >= 80: grade_dist['A'] += 1
        elif final_avg >= 70: grade_dist['B'] += 1
        elif final_avg >= 60: grade_dist['C'] += 1
        else: grade_dist['D'] += 1

    return render_template(
        'admin_class_profile.html',
        has_data=True,
        display_title=display_title,
        scope=scope,
        selected_dept=selected_dept,
        selected_class=selected_class,
        departments_list=departments_list,
        classes_list=classes_list,
        
        dimensions=dimensions,
        class_avg_data=[group_avg_radar[d] for d in dimensions], # 变量名保持兼容，实际是 group avg
        weak_dims=weak_dims,
        weakness_alerts=weakness_alerts,
        grade_dist=grade_dist,
        total_students=len(students),
        active_students=len(student_radars)
    )


@bp.route('/teacher/students')
@login_required
@teacher_required
def teacher_students():
    """教师端：学生花名册与学情统计"""
    query = User.query.filter_by(role='student')

    if current_user.role == 'teacher':
        query = query.filter_by(
            department=current_user.department,
            class_name=current_user.class_name,
            active=True,
        )
    elif current_user.role == 'dept_head':
        query = query.filter_by(department=current_user.department, active=True)

    students_db = query.all()
    student_list = []

    for s in students_db:
        finished_sessions = [sess for sess in s.sessions if sess.status == 'completed']
        valid_scores = [
            sess.total_score for sess in finished_sessions
            if sess.total_score is not None
        ]
        count = len(finished_sessions)
        avg_score = 0
        last_active = None

        if count > 0:
            avg_score = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0
            last_active = max(sess.start_time for sess in finished_sessions)

        student_list.append({
            'info': s,
            'count': count,
            'avg_score': avg_score,
            'last_active': last_active
        })

    student_list.sort(key=lambda x: x['avg_score'] if x['count'] > 0 else -1)
    return render_template('teacher_students.html', students=student_list)


@bp.route('/teacher/student/<int:user_id>')
@login_required
@teacher_required
def teacher_student_detail(user_id):
    """教师查看单个学生的详细档案"""
    student = User.query.get_or_404(user_id)

    if (
        current_user.role == 'teacher'
        and (
            student.department != current_user.department
            or student.class_name != current_user.class_name
        )
    ):
        flash('您只能查看本班学生', 'error')
        return redirect(url_for('routes.teacher_students'))

    if current_user.role == 'dept_head' and student.department != current_user.department:
        flash('您只能查看本系学生', 'error')
        return redirect(url_for('routes.teacher_students'))

    sessions = InterviewSession.query \
        .filter_by(user_id=student.id, status='completed') \
        .order_by(InterviewSession.start_time.desc()) \
        .all()

    total_count = len(sessions)
    avg_score = 0
    recent_trend = []
    date_labels = []

    if total_count > 0:
        scores = [s.total_score for s in sessions if s.total_score is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        recent_trend = scores[::-1]
        date_labels = [s.start_time.strftime('%m-%d') for s in sessions[::-1]]

    return render_template('teacher_student_detail.html',
                           student=student,
                           sessions=sessions,
                           stats={
                               'avg_score': avg_score,
                               'total_count': total_count,
                               'trend': recent_trend,
                               'labels': date_labels
                           })


# ===============================================================
#  (新增) 校级管理员功能：组织架构管理与批量导入
# ===============================================================

@bp.route('/admin/organization')
@login_required
@teacher_required
def admin_organization():
    """校级管理员：组织架构管理页面"""
    if current_user.role != 'admin':
        flash("只有校级管理员可以访问此页面", "error")
        return redirect(url_for('routes.dashboard'))

    departments_db = Department.query.order_by(Department.id).all()

    # === 关键修正：在后端将 SQLAlchemy 对象转换为纯字典 ===
    # 这样前端模板直接用 | tojson 就不会报错了
    departments_data = []
    for d in departments_db:
        departments_data.append({
            'id': d.id,
            'name': d.name,
            # 将班级对象列表也转换为字典列表
            'classes': [{'id': c.id, 'name': c.name} for c in d.classes]
        })

    return render_template('admin_organization.html', departments=departments_data)

@bp.route('/api/admin/department/add', methods=['POST'])
@login_required
@admin_required
def add_department():
    """API: 新增系部"""
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name: return jsonify({'error': '名称不能为空'}), 400

    if Department.query.filter_by(name=name).first():
        return jsonify({'error': '该系部已存在'}), 400

    db.session.add(Department(name=name))
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/department/delete/<int:dept_id>', methods=['POST'])
@login_required
@admin_required
def delete_department(dept_id):
    """API: 删除系部"""
    dept = Department.query.get_or_404(dept_id)

    # 1. 检查该系部下是否有学生
    student_count = User.query.filter_by(department=dept.name, role='student').count()
    if student_count > 0:
        return jsonify({'error': f'无法删除：该系部下仍有 {student_count} 名学生，请先移除学生'}), 400

    db.session.delete(dept)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/class/add', methods=['POST'])
@login_required
@admin_required
def add_class():
    """API: 新增班级 (支持逗号分隔批量创建)"""
    data = request.get_json(silent=True) or {}
    dept_id = data.get('dept_id')
    class_names_str = data.get('class_names', '').strip()

    if not dept_id or not class_names_str:
        return jsonify({'error': '参数不完整'}), 400

    dept = db.session.get(Department, dept_id)
    if not dept: return jsonify({'error': '系部不存在'}), 404

    # 兼容中文逗号和英文逗号
    class_names = class_names_str.replace('，', ',').split(',')

    added_count = 0
    for name in class_names:
        name = name.strip()
        if name:
            exists = SchoolClass.query.filter_by(department_id=dept.id, name=name).first()
            if not exists:
                db.session.add(SchoolClass(name=name, department_id=dept.id))
                added_count += 1

    db.session.commit()
    return jsonify({'status': 'success', 'count': added_count})


@bp.route('/api/admin/class/delete/<int:class_id>', methods=['POST'])
@login_required
@admin_required
def delete_class(class_id):
    """API: 仅删除空班级，绝不级联删除学生或业务记录。"""
    cls = SchoolClass.query.get_or_404(class_id)
    dept = db.session.get(Department, cls.department_id)

    student_count = User.query.filter_by(
        department=dept.name,
        class_name=cls.name,
        role='student',
    ).count()
    if student_count:
        return jsonify({
            'error': f'无法删除：该班级仍有 {student_count} 名学生，请先调整其班级归属'
        }), 400

    db.session.delete(cls)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/student/template')
@login_required
@admin_required
def download_student_template():
    """API: 下载学生导入模板 (Excel)"""
    # 创建一个空的 DataFrame 并包含表头
    df = pd.DataFrame(columns=['姓名', '学号', '系部', '班级', '初始密码(选填)'])

    # 写入内存 Buffer
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='学生导入模板')

    output.seek(0)
    return send_file(output, as_attachment=True, download_name='学生导入模板.xlsx')


@bp.route('/api/admin/student/import', methods=['POST'])
@login_required
@admin_required
def import_students():
    """API: 批量导入学生 (Excel)"""
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400

    file = request.files['file']
    if not (file.filename or '').lower().endswith('.xlsx'):
        return jsonify({'error': '请上传 .xlsx 格式的 Excel 文件'}), 400

    try:
        df = pd.read_excel(file)

        # 简单校验表头
        required_cols = ['姓名', '学号', '系部', '班级']
        for col in required_cols:
            if col not in df.columns:
                return jsonify({'error': f'模板缺少列: {col}'}), 400

        def cell_text(value):
            """Normalize pandas/Excel scalars without turning blanks into 'nan'."""
            if pd.isna(value):
                return ''
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value).strip()

        normalized_rows = []
        for row_index, row in df.iterrows():
            values = {
                'truename': cell_text(row['姓名']),
                'student_id': cell_text(row['学号']),
                'department': cell_text(row['系部']),
                'class_name': cell_text(row['班级']),
            }
            missing = [
                label
                for label, key in (
                    ('姓名', 'truename'),
                    ('学号', 'student_id'),
                    ('系部', 'department'),
                    ('班级', 'class_name'),
                )
                if not values[key]
            ]
            if missing:
                return jsonify({
                    'error': (
                        f'第 {row_index + 2} 行缺少必填项: '
                        f'{", ".join(missing)}'
                    )
                }), 400

            supplied_password = None
            if '初始密码(选填)' in df.columns:
                supplied_password = cell_text(row['初始密码(选填)']) or None
                if supplied_password and len(supplied_password) < 10:
                    return jsonify({
                        'error': (
                            f'第 {row_index + 2} 行学号 '
                            f'{values["student_id"]} 的初始密码少于 10 个字符'
                        )
                    }), 400

            values['password'] = supplied_password
            normalized_rows.append(values)

        success_count = 0
        credentials = []

        for row in normalized_rows:
            truename = row['truename']
            student_id = row['student_id']
            dept_name = row['department']
            class_name = row['class_name']
            supplied_password = row['password']

            # 1. 自动处理系部 (如果不存在则创建)
            dept = Department.query.filter_by(name=dept_name).first()
            if not dept:
                dept = Department(name=dept_name)
                db.session.add(dept)
                db.session.flush()  # 刷新以获取 ID

            # 2. 自动处理班级 (如果不存在则创建)
            school_class = SchoolClass.query.filter_by(department_id=dept.id, name=class_name).first()
            if not school_class:
                school_class = SchoolClass(name=class_name, department_id=dept.id)
                db.session.add(school_class)

            # 3. 创建或更新学生用户
            user = User.query.filter_by(student_id=student_id).first()
            if not user:
                # 新建用户 (username 默认为学号)
                user = User(username=student_id, student_id=student_id, role='student')
                initial_password = supplied_password or secrets.token_urlsafe(12)
                user.set_password(initial_password)
                user.must_change_password = True
                db.session.add(user)
                credentials.append({
                    'name': truename,
                    'student_id': student_id,
                    'password': initial_password,
                })
            elif supplied_password:
                user.set_password(supplied_password)
                user.must_change_password = True
                credentials.append({
                    'name': truename,
                    'student_id': student_id,
                    'password': supplied_password,
                })

            # 更新用户信息
            user.truename = truename
            user.department = dept_name
            user.class_name = class_name

            success_count += 1

        db.session.commit()
        return jsonify({
            'status': 'success',
            'count': success_count,
            'credentials': credentials,
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/student/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_student_api(user_id):
    """API: 停用学生账号，保留其面试、简历和学习记录。"""
    student = User.query.get_or_404(user_id)
    
    if student.role != 'student':
        return jsonify({'error': '只能删除学生账号'}), 400

    try:
        student.active = False
        student.deactivated_at = datetime.now()
        db.session.commit()
        return jsonify({'status': 'deactivated'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/student/reactivate/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reactivate_student_api(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != 'student':
        return jsonify({'error': '只能重新启用学生账号'}), 400
    student.active = True
    student.deactivated_at = None
    db.session.commit()
    return jsonify({'status': 'active'})


@bp.route('/api/admin/student/reset-password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_student_password_api(user_id):
    student = User.query.get_or_404(user_id)
    if student.role != 'student':
        return jsonify({'error': '只能重置学生账号密码'}), 400
    temporary_password = secrets.token_urlsafe(12)
    student.set_password(temporary_password)
    student.must_change_password = True
    db.session.commit()
    return jsonify({
        'status': 'success',
        'username': student.username,
        'temporary_password': temporary_password,
    })


@bp.route('/radar')
@login_required
def ability_radar():
    """
    能力雷达页面：展示五维能力图谱、成长趋势、班级对比
    """
    if current_user.role != 'student':
        flash("只有学生用户拥有能力雷达档案", "warning")
        return redirect(url_for('routes.dashboard'))

    # 1. 获取我的所有已完成面试
    my_sessions = InterviewSession.query \
        .filter_by(user_id=current_user.id, status='completed') \
        .order_by(InterviewSession.start_time.asc()) \
        .all()

    if not my_sessions:
        return render_template('radar.html', has_data=False, stats={'total': 0, 'max': 0, 'avg': 0})

    # 2. 数据聚合：我的各项能力总分
    # 维度顺序固定，方便前端绘图
    dimensions = ["专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度"]
    my_totals = {dim: 0 for dim in dimensions}
    my_counts = {dim: 0 for dim in dimensions}

    # 趋势图数据
    trend_labels = []
    trend_data = []

    for s in my_sessions:
        # 趋势图：最近 10 次
        if s.total_score is not None:
            trend_labels.append(s.start_time.strftime('%m-%d'))
            trend_data.append(s.total_score)

        # 雷达图聚合
        if s.radar_data:
            for dim in dimensions:
                value = s.radar_data.get(dim)
                if isinstance(value, (int, float)):
                    my_totals[dim] += value
                    my_counts[dim] += 1

    # 计算我的平均分
    my_avg_data = []
    my_avg_data = [
        round(my_totals[dim] / my_counts[dim], 1) if my_counts[dim] else 0
        for dim in dimensions
    ]

    # 3. 数据聚合：班级平均水平 (Benchmark)
    # 找到同班同学的所有 Session
    class_avg_data = [0] * 5
    try:
        class_users = User.query.filter_by(
            department=current_user.department,
            class_name=current_user.class_name,
            role='student',
        ).with_entities(User.id).all()
        class_user_ids = [u.id for u in class_users]

        if class_user_ids:
            class_sessions = InterviewSession.query \
                .filter(InterviewSession.user_id.in_(class_user_ids), InterviewSession.status == 'completed') \
                .all()

            if class_sessions:
                class_totals = {dim: 0 for dim in dimensions}
                class_counts = {dim: 0 for dim in dimensions}
                for cs in class_sessions:
                    if cs.radar_data:
                        for dim in dimensions:
                            value = cs.radar_data.get(dim)
                            if isinstance(value, (int, float)):
                                class_totals[dim] += value
                                class_counts[dim] += 1

                class_avg_data = [
                    round(class_totals[dim] / class_counts[dim], 1)
                    if class_counts[dim] else 0
                    for dim in dimensions
                ]
    except Exception as e:
        print(f"Error calculating class stats: {e}")
        # 出错则默认为 0，不影响页面崩溃

    # 4. 核心指标
    total_interviews = len(my_sessions)
    max_score = max(trend_data) if trend_data else 0
    avg_score = round(sum(trend_data) / len(trend_data), 1) if trend_data else 0

    return render_template(
        'radar.html',
        has_data=True,
        dimensions=dimensions,
        my_avg_data=my_avg_data,
        class_avg_data=class_avg_data,
        trend_labels=trend_labels[-10:],  # 只取最近 10 次
        trend_data=trend_data[-10:],
        stats={
            'total': total_interviews,
            'max': max_score,
            'avg': avg_score
        }
    )


@bp.route('/api/radar/analyze', methods=['POST'])
@login_required
def analyze_radar_ai():
    """
    API: 调用 AI 对雷达图数据进行深度诊断
    """
    dimensions = ["专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度"]
    sessions = InterviewSession.query.filter_by(
        user_id=current_user.id,
        status='completed',
    ).all()
    totals = {dimension: 0 for dimension in dimensions}
    counts = {dimension: 0 for dimension in dimensions}
    for interview in sessions:
        for dimension in dimensions:
            value = (interview.radar_data or {}).get(dimension)
            if isinstance(value, (int, float)):
                totals[dimension] += value
                counts[dimension] += 1
    score_map = {
        dimension: round(totals[dimension] / counts[dimension], 1)
        for dimension in dimensions
        if counts[dimension]
    }
    if len(score_map) != len(dimensions):
        return jsonify({'error': '无数据'}), 400

    system_prompt = """
    你是一位资深的职业生涯规划导师。
    请根据学生的【五维能力雷达图】数据，生成一份简短犀利的【能力诊断报告】。

    要求：
    1. 风格：专业、鼓励、一针见血。
    2. 结构：
       - 🌟 核心优势：（找出最高分的1-2项进行表扬）
       - ⚠️ 提升短板：（找出最低分的1项提出警告）
       - 🚀 训练建议：（针对短板给出具体的训练方向，例如"多练Python基础"或"多用STAR法则"）
    3. 字数：200字以内，不要废话。
    """

    user_prompt = f"学生各维度平均分如下（满分100）：\n{json.dumps(score_map, ensure_ascii=False)}"

    try:
        from .services.ai_agent import client, Config, chat_request_options
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        content = response.choices[0].message.content
        return jsonify({'status': 'success', 'analysis': content})

    except Exception as e:
        print(f"AI Analysis Failed: {e}")
        return jsonify({'error': str(e)}), 500


from datetime import timedelta

@bp.route('/admin/interviews')
@login_required
@teacher_required
def admin_interviews():
    """面试记录流水页面"""
    # 读取页面不得触发数据删除。过期状态由会话状态服务负责转换。
    # 获取所有有效面试记录（只获取已完成）
    # 按时间倒序
    include_deleted = (
        current_user.role == 'admin'
        and request.args.get('include_deleted') == '1'
    )
    visible_statuses = ['completed', 'deleted'] if include_deleted else ['completed']
    query = InterviewSession.query.join(
        User,
        InterviewSession.user_id == User.id,
    ).filter(
        InterviewSession.status.in_(visible_statuses)
    ).order_by(InterviewSession.start_time.desc())
    
    # 根据权限过滤
    if current_user.role == 'teacher':
        query = query.filter(
            User.department == current_user.department,
            User.class_name == current_user.class_name,
        )
    elif current_user.role == 'dept_head':
        query = query.filter(User.department == current_user.department)
        
    sessions = query.all()
    
    # 统计数据
    now = datetime.now()
    stats = {
        '1h': 0,
        '24h': 0,
        '1week': 0,
        '1month': 0,
        '1year': 0,
        'all': len(sessions)
    }
    
    for s in sessions:
        delta = now - s.start_time
        if delta <= timedelta(hours=1):
            stats['1h'] += 1
        if delta <= timedelta(hours=24):
            stats['24h'] += 1
        if delta <= timedelta(days=7):
            stats['1week'] += 1
        if delta <= timedelta(days=30):
            stats['1month'] += 1
        if delta <= timedelta(days=365):
            stats['1year'] += 1

    return render_template(
        'admin_interviews.html',
        sessions=sessions,
        stats=stats,
        include_deleted=include_deleted,
    )


@bp.route('/api/admin/interview/delete/<int:session_id>', methods=['POST'])
@login_required
@teacher_required
def delete_interview_session(session_id):
    """API: 删除单条面试记录"""
    session = InterviewSession.query.get_or_404(session_id)
    student = db.session.get(User, session.user_id)
    
    # 权限检查
    has_permission = False
    if current_user.role == 'admin':
        has_permission = True
    elif current_user.role == 'dept_head' and current_user.department == student.department:
        has_permission = True
    elif (
        current_user.role == 'teacher'
        and current_user.department == student.department
        and current_user.class_name == student.class_name
    ):
        has_permission = True
        
    if not has_permission:
        return jsonify({'error': '无权删除此记录'}), 403

    try:
        soft_delete_session(
            session,
            current_user.id,
            reason='admin_requested',
        )
        return jsonify({'status': 'success'})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/interview/restore/<int:session_id>', methods=['POST'])
@login_required
@admin_required
def restore_interview_session(session_id):
    session = InterviewSession.query.get_or_404(session_id)
    if session.status != 'deleted':
        return jsonify({'error': '该记录未被隐藏'}), 400
    restore_soft_deleted_session(session)
    return jsonify({'status': 'restored'})


# ===============================================================
#  学习模块 (Learning Hub) - 管理端
# ===============================================================

@bp.route('/admin/learning')
@login_required
@admin_required
def admin_learning():
    """管理端：课程内容管理"""
    categories_db = LearningCategory.query.order_by(LearningCategory.sort_order).all()

    # === 修复：将数据库对象转换为字典列表，以便前端能够直接转 JSON ===
    categories_data = []
    for cat in categories_db:
        categories_data.append({
            'id': cat.id,
            'name': cat.name,
            'icon': cat.icon,
            # 在这里预先处理好 materials 列表
            'materials': [{'id': m.id, 'title': m.title, 'type': m.material_type} for m in cat.materials]
        })

    return render_template('admin_learning.html', categories=categories_data)

@bp.route('/api/admin/learning/category/add', methods=['POST'])
@login_required
@admin_required
def add_learning_category():
    name = (request.get_json(silent=True) or {}).get('name')
    if not name: return jsonify({'error': '名称不能为空'}), 400

    # 简单的自动排序逻辑
    count = LearningCategory.query.count()
    cat = LearningCategory(name=name, sort_order=count + 1)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/learning/category/delete/<int:cat_id>', methods=['POST'])
@login_required
@admin_required
def delete_learning_category(cat_id):
    cat = LearningCategory.query.get_or_404(cat_id)
    material_ids = [m.id for m in cat.materials]
    if material_ids:
        record_count = (
            UserLearningProgress.query.filter(
                UserLearningProgress.material_id.in_(material_ids)
            ).count()
            + LearningAttempt.query.filter(
                LearningAttempt.material_id.in_(material_ids)
            ).count()
        )
        if record_count:
            return jsonify({
                'error': f'该分类已有 {record_count} 条学习记录，不能删除'
            }), 400
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/learning/material/add', methods=['POST'])
@login_required
@admin_required
def add_learning_material():
    data = request.get_json(silent=True) or {}
    category_id = data.get('category_id')
    title = data.get('title')
    m_type = data.get('type')  # article 或 quiz
    content = data.get('content')

    if not all([category_id, title, m_type, content]):
        return jsonify({'error': '参数不完整'}), 400

    # 如果是 quiz，校验一下 JSON 格式
    if m_type == 'quiz':
        try:
            json.loads(content)
        except:
            return jsonify({'error': '题目内容必须是合法的 JSON 格式'}), 400

    mat = LearningMaterial(
        category_id=category_id,
        title=title,
        material_type=m_type,
        content=content
    )
    db.session.add(mat)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/learning/material/delete/<int:m_id>', methods=['POST'])
@login_required
@admin_required
def delete_learning_material(m_id):
    mat = LearningMaterial.query.get_or_404(m_id)
    record_count = (
        UserLearningProgress.query.filter_by(material_id=mat.id).count()
        + LearningAttempt.query.filter_by(material_id=mat.id).count()
    )
    if record_count:
        return jsonify({'error': f'已有 {record_count} 条学习记录，不能删除该材料'}), 400
    db.session.delete(mat)
    db.session.commit()
    return jsonify({'status': 'success'})


# ===============================================================
#  学习模块 (Learning Hub) - 学生端
# ===============================================================

def _load_quiz_questions(material):
    if material.material_type != 'quiz':
        raise ValueError('该材料不是测验')
    questions = json.loads(material.content)
    if not isinstance(questions, list) or not questions:
        raise ValueError('题库为空或格式错误')
    return questions


def _grade_quiz(material, answers):
    """Grade both HTML and JSON submissions through one canonical path."""
    questions = _load_quiz_questions(material)
    normalized_answers = {}
    correct_count = 0
    for index, question in enumerate(questions):
        question_id = str(question.get('id', index))
        answer = answers.get(question_id)
        if answer is None:
            answer = answers.get(str(index))
        normalized_answers[question_id] = answer
        if answer is not None and str(answer) == str(question.get('answer')):
            correct_count += 1
    score = int((correct_count / len(questions)) * 100)
    return score, score >= 80, normalized_answers


def _record_quiz_attempt(material, answers):
    score, passed, normalized_answers = _grade_quiz(material, answers)
    db.session.add(LearningAttempt(
        user_id=current_user.id,
        material_id=material.id,
        score=score,
        passed=passed,
        answers=normalized_answers,
    ))
    if passed:
        progress = UserLearningProgress.query.filter_by(
            user_id=current_user.id,
            material_id=material.id,
        ).first()
        if progress is None:
            progress = UserLearningProgress(
                user_id=current_user.id,
                material_id=material.id,
            )
            db.session.add(progress)
        progress.score = max(progress.score or 0, score)
        progress.status = 'completed'
        progress.completed_at = datetime.now()
    db.session.commit()
    from .services.learning_achievements import notify_wikibook_learning_change
    notify_wikibook_learning_change(current_user.id)
    return score, passed

@bp.route('/learning')
@login_required
def learning_index():
    """学生端：学习中心首页"""
    categories = LearningCategory.query.order_by(LearningCategory.sort_order).all()

    # 计算每个分类的进度
    # 这部分逻辑稍微复杂一点，我们在 python 里算
    progress_map = {}  # {cat_id: percent}

    # 获取我已完成的所有 material_id
    my_done_ids = [p.material_id for p in UserLearningProgress.query.filter_by(user_id=current_user.id).all()]

    for cat in categories:
        total_m = len(cat.materials)
        if total_m == 0:
            progress_map[cat.id] = 0
        else:
            done_count = sum(1 for m in cat.materials if m.id in my_done_ids)
            progress_map[cat.id] = int((done_count / total_m) * 100)

    return render_template('learning_index.html', categories=categories, progress_map=progress_map)


@bp.route('/learning/material/<int:material_id>')
@login_required
def learning_detail(material_id):
    """学生端：具体的学习页面 (阅读/答题)"""
    material = LearningMaterial.query.get_or_404(material_id)
    category = material.category

    # 获取同分类下的所有课程，用于生成侧边栏目录
    siblings = LearningMaterial.query.filter_by(category_id=category.id).order_by(LearningMaterial.sort_order).all()

    # 计算上一节/下一节
    prev_id = None
    next_id = None
    for idx, m in enumerate(siblings):
        if m.id == material.id:
            if idx > 0:
                prev_id = siblings[idx - 1].id
            if idx < len(siblings) - 1:
                next_id = siblings[idx + 1].id
            break

    # 获取我的完成状态
    progress = UserLearningProgress.query.filter_by(user_id=current_user.id, material_id=material.id).first()
    is_completed = (progress is not None)

    # 获取我已完成的所有ID，用于目录打钩
    my_done_ids = [p.material_id for p in UserLearningProgress.query.filter_by(user_id=current_user.id).all()]

    # 如果是测验，解析 JSON 内容传给前端
    quiz_data = []
    if material.material_type == 'quiz':
        try:
            quiz_data = json.loads(material.content)
        except:
            quiz_data = []

    return render_template('learning_detail.html',
                           lesson=material,  # ✅ 修正1：对应 {{ lesson.title }}
                           questions=quiz_data,  # ✅ 修正2：对应 {% for q in questions %}
                           category=category,
                           siblings=siblings,
                           is_completed=is_completed,
                           my_done_ids=my_done_ids,
                           prev_id=prev_id,
                           next_id=next_id)


@bp.route('/api/learning/complete/<int:material_id>', methods=['POST'])
@login_required
def complete_learning_material(material_id):
    """API: 标记完成 (文章) 或 提交答案 (测验)"""
    material = LearningMaterial.query.get_or_404(material_id)

    existing = UserLearningProgress.query.filter_by(user_id=current_user.id, material_id=material.id).first()

    # 1. 文章类型：直接完成
    if material.material_type == 'article':
        if existing:
            return jsonify({'status': 'already_completed', 'score': existing.score})
        prog = UserLearningProgress(user_id=current_user.id, material_id=material.id, score=100)
        db.session.add(prog)
        db.session.commit()
        return jsonify({'status': 'success', 'score': 100})

    # 2. 测验类型：需要判分
    elif material.material_type == 'quiz':
        if existing:
            return jsonify({'status': 'already_completed', 'score': existing.score, 'passed': True})
        try:
            answers = (request.get_json(silent=True) or {}).get('answers', {})
            score, passed = _record_quiz_attempt(material, answers)
        except (TypeError, ValueError, json.JSONDecodeError):
            return jsonify({'error': '题库数据错误'}), 400
        return jsonify({
            'status': 'success' if passed else 'failed',
            'score': score,
            'passed': passed,
        })

    return jsonify({'error': 'unknown type'}), 400


@bp.route('/learning/submit_quiz/<int:material_id>', methods=['POST'])
@login_required
def submit_quiz(material_id):
    material = LearningMaterial.query.get_or_404(material_id)
    existing = UserLearningProgress.query.filter_by(
        user_id=current_user.id,
        material_id=material_id,
    ).first()
    if existing:
        flash(f"该测验已经通过，最高得分：{existing.score} 分", "info")
        return redirect(url_for('routes.learning_detail', material_id=material_id))

    try:
        questions = _load_quiz_questions(material)
        answers = {
            str(question.get('id', index)): request.form.get(
                f"q_{question.get('id', index)}"
            )
            for index, question in enumerate(questions)
        }
        score, passed = _record_quiz_attempt(material, answers)
    except (TypeError, ValueError, json.JSONDecodeError):
        flash("题库数据错误", "error")
        return redirect(url_for('routes.learning_detail', material_id=material_id))
    if passed:
        flash(f"恭喜！通过测验，得分：{score} 分", "success")
    else:
        flash(f"本次得分：{score} 分，尚未通过，可以立即重试。", "warning")

    return redirect(url_for('routes.learning_detail', material_id=material_id))


@bp.get('/account-links')
@login_required
def account_links():
    return render_template('account_links.html')
