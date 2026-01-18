import json

import pandas as pd
from io import BytesIO
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from collections import Counter
from sqlalchemy import func
from datetime import datetime
from . import db  # 确保导入 db 实例，用于 db.session.add/commit
from .models import InterviewSession, ChatMessage, User, Department, SchoolClass, LearningCategory, LearningMaterial, UserLearningProgress
from .config import Config
from .decorators import teacher_required, dept_head_required, admin_required

bp = Blueprint('routes', __name__)


# ===============================================================
#  学生端核心功能 (首页、历史、聊天、报告)
# ===============================================================

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

    return render_template(
        'index.html',
        current_user=current_user,
        sessions=history_sessions,  # 传给模板的是包含"生成中"的全量列表
        stats=stats,
        voice_options=Config.VOLC_AVAILABLE_VOICES
    )


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

    return render_template('chat.html',
                           session=session,
                           messages=messages,
                           current_user=current_user,
                           base_template=base_template,
                           is_read_only=is_read_only)


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


@bp.route('/profile/resume')
@login_required
def profile_resume():
    """我的简历页面"""
    return render_template('profile_resume.html', current_user=current_user)


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
    """API: 删除班级"""
    cls = SchoolClass.query.get_or_404(class_id)
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
        return render_template('radar.html', has_data=False)

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