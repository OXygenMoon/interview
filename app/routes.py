import json

import pandas as pd
from io import BytesIO
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from collections import Counter
from sqlalchemy import func
from datetime import datetime
from . import db  # 确保导入 db 实例，用于 db.session.add/commit
from .models import InterviewSession, ChatMessage, User, Department, SchoolClass, LearningCategory, LearningMaterial, UserLearningProgress, Company, Position, Resume, SystemConfig
from .config import Config
from .decorators import teacher_required, dept_head_required, admin_required

bp = Blueprint('routes', __name__)

DEFAULT_RANDOM_INTERVIEW_QUESTIONS = [
    "请你做一个 1 分钟的自我介绍，并突出与岗位相关的优势。",
    "请分享一个你遇到困难并最终解决的问题，重点说说你的思考过程。",
    "如果你和同事在方案上意见不一致，你会如何推进沟通并达成结果？",
    "请举例说明你如何在压力下保证任务质量和交付时间。",
    "你为什么想加入我们公司？你最看重的是什么？"
]


def get_random_interview_questions():
    """读取随机问题题库，若未配置则返回默认题库"""
    raw_value = SystemConfig.get('random_interview_questions', '[]')
    questions = []

    try:
        parsed = json.loads(raw_value) if raw_value else []
        if isinstance(parsed, list):
            questions = [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        questions = []

    return questions if questions else DEFAULT_RANDOM_INTERVIEW_QUESTIONS


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
        enable_video = request.form.get('enable_video') == 'on'
        
        # 保存设置
        SystemConfig.set('enable_tts', 'true' if enable_tts else 'false', '是否启用面试官语音输出 (TTS)')
        SystemConfig.set('enable_video', 'true' if enable_video else 'false', '是否启用视频面试 (摄像头与视觉分析)')
        
        flash('系统设置已更新', 'success')
        return redirect(url_for('routes.admin_settings'))
    
    # 读取设置
    enable_tts = SystemConfig.get('enable_tts', 'true') == 'true'
    enable_video = SystemConfig.get('enable_video', 'true') == 'true'
    
    return render_template('admin_settings.html', enable_tts=enable_tts, enable_video=enable_video)


@bp.route('/admin/random_questions', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_random_questions():
    """管理员：随机问题题库配置"""
    if request.method == 'POST':
        raw_text = request.form.get('questions_text', '')
        lines = [line.strip() for line in raw_text.splitlines()]
        questions = [line for line in lines if line]

        if not questions:
            questions = DEFAULT_RANDOM_INTERVIEW_QUESTIONS

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
    student = User.query.get(resume.user_id)
    return render_template('admin_resume_preview.html', resume=resume, student=student)


@bp.route('/')
@login_required
def home():
    """首页/仪表盘"""

    # 1. 角色检查
    if current_user.role != 'student':
        return redirect(url_for('routes.dashboard'))

    # 2. 查询历史记录 (修改点：包含 completed 和 processing)
    # 使用 .in_(['completed', 'processing']) 来同时获取两种状态
    history_sessions = InterviewSession.query \
        .filter(
        InterviewSession.user_id == current_user.id,
        InterviewSession.status.in_(['completed', 'processing'])
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
    classmates = User.query.filter_by(class_name=current_user.class_name, role='student').all()
    
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
    
    return render_template('leaderboard.html',
                           current_user=current_user,
                           avg_rank=avg_rank_list,
                           max_rank=max_rank_list,
                           count_rank=count_rank_list)


@bp.route('/history')
@login_required
def history():
    """历史记录与统计分析页面"""

    # 1. 查询记录 (修改点：同样包含 completed 和 processing)
    # 注意这里原代码是 .asc() 正序，为了统计图表方便
    sessions = InterviewSession.query \
        .filter(
        InterviewSession.user_id == current_user.id,
        InterviewSession.status.in_(['completed', 'processing'])
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
        scores = [s.total_score if s.total_score else 0 for s in finished_sessions]
        avg_score = round(sum(scores) / total_count, 1)
        max_score = max(scores)
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
    student = User.query.get(session.user_id)

    # === 1. 权限检查 ===
    is_owner = (current_user.id == student.id)
    is_teacher_allowed = False

    if current_user.role in ['teacher', 'dept_head', 'admin']:
        if current_user.role == 'admin':
            is_teacher_allowed = True
        elif current_user.role == 'dept_head' and current_user.department == student.department:
            is_teacher_allowed = True
        elif current_user.role == 'teacher' and current_user.class_name == student.class_name:
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

    return render_template('chat.html',
                           session=session,
                           messages=messages,
                           current_user=current_user,
                           base_template=base_template,
                           is_read_only=is_read_only,
                           enable_video=enable_video)


# === 面试报告页 ===
@bp.route('/interview/summary/<int:session_id>')
@login_required
def interview_summary(session_id):
    """面试结果总结页"""
    session = InterviewSession.query.get_or_404(session_id)
    student = User.query.get(session.user_id)

    # === 1. 权限检查 ===
    is_owner = (current_user.id == student.id)
    is_teacher_allowed = False

    if current_user.role in ['teacher', 'dept_head', 'admin']:
        if current_user.role == 'admin':
            is_teacher_allowed = True
        elif current_user.role == 'dept_head' and current_user.department == student.department:
            is_teacher_allowed = True
        elif current_user.role == 'teacher' and current_user.class_name == student.class_name:
            is_teacher_allowed = True

    if not (is_owner or is_teacher_allowed):
        flash("您无权访问该报告", "error")
        return redirect(url_for('routes.home'))

    messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()

    # === 2. 动态决定继承哪个模板 ===
    base_template = 'teacher_base.html' if current_user.role != 'student' else 'base.html'

    return render_template('summary.html',
                           session=session,
                           current_user=current_user,
                           messages=messages,
                           base_template=base_template)


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
    query = InterviewSession.query.join(User).filter(InterviewSession.status == 'completed')
    title = "管理后台"

    if current_user.role == 'teacher':
        query = query.filter(User.class_name == current_user.class_name)
        title = f"{current_user.class_name} - 班级概况"
    elif current_user.role == 'dept_head':
        query = query.filter(User.department == current_user.department)
        title = f"{current_user.department} - 系部概况"
    elif current_user.role == 'admin':
        title = "全校数据大盘"

    sessions = query.order_by(InterviewSession.start_time.desc()).all()

    total_interviews = len(sessions)
    if total_interviews > 0:
        avg_score = round(sum([s.total_score for s in sessions if s.total_score]) / total_interviews, 1)
    else:
        avg_score = 0

    top_students = query.order_by(InterviewSession.total_score.desc()).limit(5).all()

    return render_template('dashboard.html',
                           title=title,
                           sessions=sessions,
                           total_interviews=total_interviews,
                           avg_score=avg_score,
                           top_students=top_students)


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
        # 此时 selected_dept 和 selected_class 应忽略或置空
        pass
        
    elif scope == 'department':
        if selected_dept:
            query = query.filter_by(department=selected_dept)
            display_title = f"{selected_dept} - 能力画像"
        else:
            # 如果没选系，不显示任何数据，等待用户选择
            query = query.filter(False)
            
    elif scope == 'class':
        if selected_class:
            query = query.filter_by(class_name=selected_class)
            display_title = f"{selected_class} - 能力画像"
            # 如果同时选了系，也可以加校验，但 class_name 理论上唯一或足以定位
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
        query = query.filter_by(class_name=current_user.class_name)
    elif current_user.role == 'dept_head':
        query = query.filter_by(department=current_user.department)

    students_db = query.all()
    student_list = []

    for s in students_db:
        finished_sessions = [sess for sess in s.sessions if sess.status == 'completed']
        count = len(finished_sessions)
        avg_score = 0
        last_active = None

        if count > 0:
            total = sum(sess.total_score for sess in finished_sessions if sess.total_score)
            avg_score = round(total / count, 1)
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

    if current_user.role == 'teacher' and student.class_name != current_user.class_name:
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
        scores = [s.total_score if s.total_score else 0 for s in sessions]
        avg_score = round(sum(scores) / total_count, 1)
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
def add_department():
    """API: 新增系部"""
    name = request.json.get('name', '').strip()
    if not name: return jsonify({'error': '名称不能为空'}), 400

    if Department.query.filter_by(name=name).first():
        return jsonify({'error': '该系部已存在'}), 400

    db.session.add(Department(name=name))
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/department/delete/<int:dept_id>', methods=['POST'])
@login_required
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
def add_class():
    """API: 新增班级 (支持逗号分隔批量创建)"""
    data = request.json
    dept_id = data.get('dept_id')
    class_names_str = data.get('class_names', '').strip()

    if not dept_id or not class_names_str:
        return jsonify({'error': '参数不完整'}), 400

    dept = Department.query.get(dept_id)
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
def delete_class(class_id):
    """API: 删除班级 (级联删除学生和面试记录)"""
    cls = SchoolClass.query.get_or_404(class_id)
    dept = Department.query.get(cls.department_id)
    
    # 1. 查找该班级下的所有学生
    # 注意：User 表中 department 和 class_name 是字符串字段
    students = User.query.filter_by(
        department=dept.name, 
        class_name=cls.name, 
        role='student'
    ).all()

    for student in students:
        # 2. 删除学生的所有面试记录
        sessions = InterviewSession.query.filter_by(user_id=student.id).all()
        for session in sessions:
            # 删除聊天记录
            ChatMessage.query.filter_by(session_id=session.id).delete()
            # 删除 Session
            db.session.delete(session)
        
        # 3. 删除学生账号
        db.session.delete(student)

    # 4. 删除班级
    db.session.delete(cls)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/student/template')
@login_required
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
def import_students():
    """API: 批量导入学生 (Excel)"""
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400

    file = request.files['file']
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': '请上传 Excel 文件'}), 400

    try:
        df = pd.read_excel(file)

        # 简单校验表头
        required_cols = ['姓名', '学号', '系部', '班级']
        for col in required_cols:
            if col not in df.columns:
                return jsonify({'error': f'模板缺少列: {col}'}), 400

        success_count = 0

        for _, row in df.iterrows():
            truename = str(row['姓名']).strip()
            student_id = str(row['学号']).strip()
            dept_name = str(row['系部']).strip()
            class_name = str(row['班级']).strip()

            # 默认密码
            password = '123456'
            if '初始密码(选填)' in df.columns and pd.notna(row['初始密码(选填)']):
                password = str(row['初始密码(选填)']).strip()

            if not student_id or not truename:
                continue

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
                user.set_password(password)
                db.session.add(user)

            # 更新用户信息
            user.truename = truename
            user.department = dept_name
            user.class_name = class_name

            success_count += 1

        db.session.commit()
        return jsonify({'status': 'success', 'count': success_count})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/student/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_student_api(user_id):
    """API: 删除单个学生 (级联删除面试记录)"""
    student = User.query.get_or_404(user_id)
    
    if student.role != 'student':
        return jsonify({'error': '只能删除学生账号'}), 400

    try:
        # 1. 删除学生的所有面试记录
        sessions = InterviewSession.query.filter_by(user_id=student.id).all()
        for session in sessions:
            # 删除聊天记录
            ChatMessage.query.filter_by(session_id=session.id).delete()
            # 删除 Session
            db.session.delete(session)
        
        # 2. 删除学习进度
        UserLearningProgress.query.filter_by(user_id=student.id).delete()

        # 3. 删除学生账号
        db.session.delete(student)
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


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
    valid_radar_count = 0

    # 趋势图数据
    trend_labels = []
    trend_data = []

    for s in my_sessions:
        # 趋势图：最近 10 次
        trend_labels.append(s.start_time.strftime('%m-%d'))
        trend_data.append(s.total_score)

        # 雷达图聚合
        if s.radar_data:
            valid_radar_count += 1
            for dim in dimensions:
                # 累加分数 (兼容 JSON 里的 key)
                my_totals[dim] += s.radar_data.get(dim, 0)

    # 计算我的平均分
    my_avg_data = []
    if valid_radar_count > 0:
        my_avg_data = [round(my_totals[dim] / valid_radar_count, 1) for dim in dimensions]
    else:
        my_avg_data = [0] * 5

    # 3. 数据聚合：班级平均水平 (Benchmark)
    # 找到同班同学的所有 Session
    class_avg_data = [0] * 5
    try:
        class_users = User.query.filter_by(class_name=current_user.class_name).with_entities(User.id).all()
        class_user_ids = [u.id for u in class_users]

        if class_user_ids:
            class_sessions = InterviewSession.query \
                .filter(InterviewSession.user_id.in_(class_user_ids), InterviewSession.status == 'completed') \
                .all()

            if class_sessions:
                class_totals = {dim: 0 for dim in dimensions}
                class_count = 0
                for cs in class_sessions:
                    if cs.radar_data:
                        class_count += 1
                        for dim in dimensions:
                            class_totals[dim] += cs.radar_data.get(dim, 0)

                if class_count > 0:
                    class_avg_data = [round(class_totals[dim] / class_count, 1) for dim in dimensions]
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
    data = request.json
    my_scores = data.get('my_scores', [])  # [70, 80, ...]
    dimensions = data.get('dimensions', [])  # ["专业技能", ...]

    if not my_scores or not dimensions:
        return jsonify({'error': '无数据'}), 400

    # 构造 Prompt
    score_map = dict(zip(dimensions, my_scores))

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
        from .services.ai_agent import client, Config  # 临时导入，或复用 helper
        response = client.chat.completions.create(
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


from datetime import datetime, timedelta

@bp.route('/admin/interviews')
@login_required
@teacher_required
def admin_interviews():
    """面试记录流水页面"""
    
    # 1. 清理过期的 ongoing 记录 (超过24小时未结束)
    try:
        cutoff_time = datetime.now() - timedelta(hours=24)
        stale_sessions = InterviewSession.query.filter(
            InterviewSession.status == 'ongoing',
            InterviewSession.start_time < cutoff_time
        ).all()
        
        if stale_sessions:
            for s in stale_sessions:
                # 删除关联的聊天记录
                ChatMessage.query.filter_by(session_id=s.id).delete()
                # 删除 Session
                db.session.delete(s)
            db.session.commit()
    except Exception as e:
        print(f"Cleanup failed: {e}")
        db.session.rollback()

    # 2. 获取所有有效面试记录 (只获取已完成)
    # 按时间倒序
    query = InterviewSession.query.join(User).filter(InterviewSession.status == 'completed').order_by(InterviewSession.start_time.desc())
    
    # 根据权限过滤
    if current_user.role == 'teacher':
        query = query.filter(User.class_name == current_user.class_name)
    elif current_user.role == 'dept_head':
        query = query.filter(User.department == current_user.department)
        
    sessions = query.all()
    
    # 3. 统计数据
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

    return render_template('admin_interviews.html', sessions=sessions, stats=stats)


@bp.route('/api/admin/interview/delete/<int:session_id>', methods=['POST'])
@login_required
@teacher_required
def delete_interview_session(session_id):
    """API: 删除单条面试记录"""
    session = InterviewSession.query.get_or_404(session_id)
    student = User.query.get(session.user_id)
    
    # 权限检查
    has_permission = False
    if current_user.role == 'admin':
        has_permission = True
    elif current_user.role == 'dept_head' and current_user.department == student.department:
        has_permission = True
    elif current_user.role == 'teacher' and current_user.class_name == student.class_name:
        has_permission = True
        
    if not has_permission:
        return jsonify({'error': '无权删除此记录'}), 403

    try:
        # 删除关联的聊天记录
        ChatMessage.query.filter_by(session_id=session.id).delete()
        # 删除 Session
        db.session.delete(session)
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ===============================================================
#  学习模块 (Learning Hub) - 管理端
# ===============================================================

@bp.route('/admin/learning')
@login_required
@teacher_required
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
@teacher_required
def add_learning_category():
    name = request.json.get('name')
    if not name: return jsonify({'error': '名称不能为空'}), 400

    # 简单的自动排序逻辑
    count = LearningCategory.query.count()
    cat = LearningCategory(name=name, sort_order=count + 1)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/learning/category/delete/<int:cat_id>', methods=['POST'])
@login_required
@teacher_required
def delete_learning_category(cat_id):
    cat = LearningCategory.query.get_or_404(cat_id)
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/admin/learning/material/add', methods=['POST'])
@login_required
@teacher_required
def add_learning_material():
    data = request.json
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
@teacher_required
def delete_learning_material(m_id):
    mat = LearningMaterial.query.get_or_404(m_id)
    db.session.delete(mat)
    db.session.commit()
    return jsonify({'status': 'success'})


# ===============================================================
#  学习模块 (Learning Hub) - 学生端
# ===============================================================

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
                           my_done_ids=my_done_ids)


@bp.route('/api/learning/complete/<int:material_id>', methods=['POST'])
@login_required
def complete_learning_material(material_id):
    """API: 标记完成 (文章) 或 提交答案 (测验)"""
    material = LearningMaterial.query.get_or_404(material_id)

    # 检查是否已完成
    existing = UserLearningProgress.query.filter_by(user_id=current_user.id, material_id=material.id).first()
    if existing:
        return jsonify({'status': 'already_completed'})

    # 1. 文章类型：直接完成
    if material.material_type == 'article':
        prog = UserLearningProgress(user_id=current_user.id, material_id=material.id, score=100)
        db.session.add(prog)
        db.session.commit()
        return jsonify({'status': 'success', 'score': 100})

    # 2. 测验类型：需要判分
    elif material.material_type == 'quiz':
        user_answers = request.json.get('answers', {})  # {'0': 'A', '1': 'B'}
        questions = json.loads(material.content)

        correct_count = 0
        total_count = len(questions)

        for idx, q in enumerate(questions):
            # 比对答案 (注意 index 转字符串)
            user_ans = user_answers.get(str(idx))
            if user_ans and user_ans == q.get('answer'):
                correct_count += 1

        # 计算得分
        score = int((correct_count / total_count) * 100) if total_count > 0 else 0

        # 达标线：80分
        passed = score >= 80

        if passed:
            prog = UserLearningProgress(user_id=current_user.id, material_id=material.id, score=score)
            db.session.add(prog)
            db.session.commit()
            return jsonify({'status': 'success', 'score': score, 'passed': True})
        else:
            return jsonify({'status': 'failed', 'score': score, 'passed': False})

    return jsonify({'error': 'unknown type'}), 400


@bp.route('/learning/submit_quiz/<int:material_id>', methods=['POST'])
@login_required
def submit_quiz(material_id):
    # 1. 获取课程内容
    material = LearningMaterial.query.get_or_404(material_id)

    # 2. 解析正确答案 (JSON)
    # 假设 content 存的是 [{"key":"A", "val":"...", "answer":"A"}, ...]
    try:
        questions = json.loads(material.content)
    except:
        flash("题库数据错误", "error")
        return redirect(url_for('routes.learning_detail', material_id=material_id))

    # 3. 计算分数
    correct_count = 0
    total_count = len(questions)

    for q in questions:
        # 我们在模板里定义的 name 是 "q_{{ q.id }}"
        # 比如 q.id 是 501，那么表单项就是 "q_501"
        qid = str(q.get('id'))
        user_choice = request.form.get(f"q_{qid}")  # 获取用户选了什么

        # 获取正确答案字段 (假设JSON里叫 'answer'，或者是题目里定义的正确项)
        # 这里假设你的JSON结构里直接有 "answer": "A"
        # 如果没有，你需要根据你的数据结构调整
        correct_answer = q.get('answer')

        if user_choice and user_choice == correct_answer:
            correct_count += 1

    # 计算百分制得分
    score = int((correct_count / total_count) * 100) if total_count > 0 else 0

    # 4. 保存或更新进度
    progress = UserLearningProgress.query.filter_by(
        user_id=current_user.id,
        material_id=material_id
    ).first()

    if not progress:
        progress = UserLearningProgress(user_id=current_user.id, material_id=material_id)
        db.session.add(progress)

    progress.score = score
    progress.status = 'completed'
    progress.completed_at = datetime.now()

    db.session.commit()

    # 5. 反馈并跳转回去
    if score >= 80:
        flash(f"恭喜！通过测验，得分：{score} 分", "success")
    else:
        flash(f"很遗憾，得分：{score} 分，请再接再厉", "warning")

    return redirect(url_for('routes.learning_detail', material_id=material_id))
