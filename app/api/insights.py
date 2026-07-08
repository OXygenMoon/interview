"""
数据洞察 API：
- /api/insights/growth       成长曲线（5维时间轴 + 移动平均预测）
- /api/insights/compare      班级/系部对比看板
- /api/insights/weak-questions 薄弱题聚合
- /api/insights/match        岗位匹配度评估
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user, login_required
from sqlalchemy import func
from collections import defaultdict
import json

from .. import db
from ..models import User, InterviewSession, ChatMessage, Company, Position, Resume

insights_bp = Blueprint('insights_api', __name__)

DIMENSIONS = ["专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度"]


@insights_bp.route('/growth', methods=['GET'])
@login_required
def growth():
    """成长曲线：每次完成面试的 5 维分数 + 总分时间轴（最近 20 次）+ 移动平均预测下次。"""
    sessions = InterviewSession.query.filter_by(
        user_id=current_user.id, status='completed'
    ).order_by(InterviewSession.start_time.asc()).limit(20).all()

    if not sessions:
        return jsonify({'has_data': False, 'points': [], 'moving_avg': [], 'predict_next': None})

    points = []
    for s in sessions:
        radar = s.radar_data or {}
        points.append({
            'date': s.start_time.strftime('%m-%d'),
            'total': s.total_score if s.total_score is not None else 0,
            'scores': {dim: radar.get(dim, 0) for dim in DIMENSIONS},
        })

    # 3 次移动平均
    totals = [p['total'] for p in points]
    moving = []
    for i in range(len(totals)):
        window = totals[max(0, i - 2):i + 1]
        moving.append(round(sum(window) / len(window), 1))

    # 预测下一次：简单线性外推（最近 3 点斜率）
    predict_next = None
    if len(totals) >= 3:
        recent = totals[-3:]
        slope = (recent[-1] - recent[0]) / 2
        predict_next = max(0, min(100, round(recent[-1] + slope)))

    return jsonify({
        'has_data': True,
        'points': points,
        'moving_avg': moving,
        'predict_next': predict_next,
        'dimensions': DIMENSIONS,
    })


@insights_bp.route('/compare', methods=['GET'])
@login_required
def compare():
    """班级/系部对比：各班各维度平均 + 总分对比。teacher/dept_head/admin 可见。"""
    if current_user.role not in ('teacher', 'dept_head', 'admin'):
        return jsonify({'error': '仅教师及以上可见'}), 403

    # 确定范围：admin 全校；dept_head 本系；teacher 本班
    scope = request.args.get('scope', 'all')
    q = db.session.query(
        User.class_name,
        User.department,
        func.avg(InterviewSession.total_score).label('avg_total'),
        func.count(InterviewSession.id).label('count'),
    ).join(InterviewSession, InterviewSession.user_id == User.id) \
     .filter(User.role == 'student', InterviewSession.status == 'completed') \
     .group_by(User.class_name, User.department)

    if current_user.role == 'teacher':
        q = q.filter(User.class_name == current_user.class_name)
    elif current_user.role == 'dept_head':
        q = q.filter(User.department == current_user.department)
    elif scope == 'dept' and current_user.department:
        q = q.filter(User.department == current_user.department)

    rows = q.all()

    # 各维度平均（需在 Python 端聚合 radar_data）
    groups = defaultdict(lambda: {'total_sum': 0, 'count': 0, 'dims': defaultdict(lambda: {'sum': 0, 'n': 0})})
    for class_name, dept, avg_total, count in rows:
        key = f"{class_name}" if class_name else '未分班'
        groups[key]['total_sum'] += (avg_total or 0) * count
        groups[key]['count'] += count

    # 精确维度需取每条 session 的 radar_data
    sess_q = InterviewSession.query.join(User, InterviewSession.user_id == User.id) \
        .filter(InterviewSession.status == 'completed')
    if current_user.role == 'teacher':
        sess_q = sess_q.filter(User.class_name == current_user.class_name)
    elif current_user.role == 'dept_head':
        sess_q = sess_q.filter(User.department == current_user.department)
    for s in sess_q.all():
        cn = s.user.class_name if s.user and s.user.class_name else '未分班'
        if s.radar_data:
            for dim in DIMENSIONS:
                groups[cn]['dims'][dim]['sum'] += s.radar_data.get(dim, 0)
                groups[cn]['dims'][dim]['n'] += 1

    result = []
    for class_name, g in groups.items():
        if g['count'] == 0:
            continue
        dims_avg = {}
        for dim in DIMENSIONS:
            n = g['dims'][dim]['n']
            dims_avg[dim] = round(g['dims'][dim]['sum'] / n, 1) if n > 0 else 0
        result.append({
            'class_name': class_name,
            'count': g['count'],
            'avg_total': round(g['total_sum'] / g['count'], 1),
            'dims': dims_avg,
        })

    result.sort(key=lambda x: x['avg_total'], reverse=True)
    return jsonify({'classes': result, 'dimensions': DIMENSIONS})


@insights_bp.route('/weak-questions', methods=['GET'])
@login_required
def weak_questions():
    """薄弱题聚合：按面试题（AI 提问）聚合，统计不合格率与平均点评。teacher+ 可见。"""
    if current_user.role not in ('teacher', 'dept_head', 'admin'):
        return jsonify({'error': '仅教师及以上可见'}), 403

    # 取所有已点评的 user 消息（is_good_response 非 None 的）
    msgs = db.session.query(
        ChatMessage.content,
        ChatMessage.is_good_response,
        ChatMessage.suggestion,
    ).join(InterviewSession, ChatMessage.session_id == InterviewSession.id) \
     .join(User, InterviewSession.user_id == User.id) \
     .filter(ChatMessage.is_good_response.isnot(None),
             InterviewSession.status == 'completed')

    if current_user.role == 'teacher':
        msgs = msgs.filter(User.class_name == current_user.class_name)
    elif current_user.role == 'dept_head':
        msgs = msgs.filter(User.department == current_user.department)

    rows = msgs.all()
    # 用对应 AI 提问作为 key（取该 user 消息前的 ai 消息）— 这里简化：按 user 回答内容前 20 字聚合
    bucket = defaultdict(lambda: {'total': 0, 'bad': 0, 'suggestions': []})
    for content, is_good, suggestion in rows:
        key = (content[:30] + '…') if len(content) > 30 else content
        bucket[key]['total'] += 1
        if not is_good:
            bucket[key]['bad'] += 1
        if suggestion:
            bucket[key]['suggestions'].append(suggestion)

    result = []
    for key, v in bucket.items():
        if v['total'] < 1:
            continue
        bad_rate = round(v['bad'] / v['total'], 2)
        result.append({
            'answer_snippet': key,
            'total': v['total'],
            'bad_rate': bad_rate,
            'sample_suggestion': v['suggestions'][0] if v['suggestions'] else '',
        })
    result.sort(key=lambda x: x['bad_rate'], reverse=True)
    return jsonify({'weak': result[:20]})


@insights_bp.route('/match', methods=['GET', 'POST'])
@login_required
def position_match():
    """岗位匹配度评估：综合简历 + 历次雷达 + 目标岗位，返回匹配度 + 差距清单。"""
    data = request.get_json(silent=True) or {} if request.method == 'POST' else {}
    position_id = data.get('position_id') or request.args.get('position_id', type=int)

    if not position_id:
        return jsonify({'error': '请选择目标岗位'}), 400

    position = Position.query.get_or_404(position_id)
    if not position.description:
        return jsonify({'error': '该岗位未填写介绍，无法评估'}), 400

    # 学生能力画像：历次雷达平均
    sessions = InterviewSession.query.filter_by(
        user_id=current_user.id, status='completed'
    ).order_by(InterviewSession.start_time.desc()).limit(10).all()
    if not sessions:
        return jsonify({'has_data': False, 'error': '尚无已完成的面试，无法评估匹配度'})

    dims_totals = defaultdict(lambda: {'sum': 0, 'n': 0})
    for s in sessions:
        if s.radar_data:
            for dim in DIMENSIONS:
                dims_totals[dim]['sum'] += s.radar_data.get(dim, 0)
                dims_totals[dim]['n'] += 1
    my_dims = {dim: round(dims_totals[dim]['sum'] / dims_totals[dim]['n'], 1)
               for dim in DIMENSIONS if dims_totals[dim]['n'] > 0}
    if not my_dims:
        return jsonify({'has_data': False, 'error': '雷达数据不足，无法评估'})

    # 简历文本
    resume = Resume.query.filter_by(user_id=current_user.id).order_by(Resume.updated_at.desc()).first()
    resume_text = ''
    if resume and resume.content:
        try:
            resume_text = json.dumps(resume.content, ensure_ascii=False)[:1500]
        except Exception:
            resume_text = str(resume.content)[:1500]
    if not resume_text and current_user.resume_text:
        resume_text = current_user.resume_text[:1500]

    # 调用 LLM 评估
    try:
        from ..services.ai_agent import client
        from ..config import Config
        system_prompt = """你是一位资深的技术招聘专家。请根据求职者的能力画像与岗位描述，评估匹配度。
严格返回 JSON：{"match_score": 0-100 整数, "strengths": ["优势1", ...], "gaps": ["待提升点1", ...], "suggestions": ["具体提升建议1", ...]}"""
        user_prompt = f"【岗位名称】{position.name}\n【岗位描述】{position.description[:1000]}\n【求职者能力画像(5维均分)】{my_dims}\n【简历摘要】{resume_text[:800]}"
        resp = client.chat.completions.create(
            model=Config.LLM_MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.5,
            response_format={"type": "json_object"},
            max_tokens=600,
        )
        import json as _json
        result = _json.loads(resp.choices[0].message.content)
        result['my_dims'] = my_dims
        return jsonify({'has_data': True, 'position': {'id': position.id, 'name': position.name}, 'result': result})
    except Exception as e:
        print(f"❌ 岗位匹配评估失败: {e}")
        return jsonify({'error': 'AI 评估失败，请稍后重试'}), 500
