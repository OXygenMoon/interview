"""
数据洞察 API：
- /api/insights/growth       成长曲线（5维时间轴 + 移动平均预测）
- /api/insights/compare      班级/系部对比看板
- /api/insights/weak-questions 薄弱题聚合
- /api/insights/match        岗位匹配度评估
"""
from flask import Blueprint, request, jsonify
from flask_login import current_user, login_required
from sqlalchemy import func
from collections import defaultdict
import re

from .. import db
from ..models import User, InterviewSession, ChatMessage, Position

insights_bp = Blueprint('insights_api', __name__)

DIMENSIONS = ["专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度"]


@insights_bp.route('/growth', methods=['GET'])
@login_required
def growth():
    """成长曲线：每次完成面试的 5 维分数 + 总分时间轴（最近 20 次）+ 移动平均预测下次。"""
    sessions = InterviewSession.query.filter_by(
        user_id=current_user.id, status='completed'
    ).filter(
        InterviewSession.total_score.isnot(None)
    ).order_by(InterviewSession.start_time.desc()).limit(20).all()
    sessions.reverse()

    if not sessions:
        return jsonify({'has_data': False, 'points': [], 'moving_avg': [], 'trend_estimate': None})

    points = []
    for s in sessions:
        radar = s.radar_data or {}
        points.append({
            'date': s.start_time.strftime('%m-%d'),
            'total': s.total_score,
            'scores': {
                dim: radar.get(dim)
                if isinstance(radar.get(dim), (int, float)) else None
                for dim in DIMENSIONS
            },
        })

    # 3 次移动平均
    totals = [p['total'] for p in points]
    moving = []
    for i in range(len(totals)):
        window = totals[max(0, i - 2):i + 1]
        moving.append(round(sum(window) / len(window), 1))

    # 仅给出近期趋势估计，不声称预测个人未来表现。
    trend_estimate = None
    if len(totals) >= 3:
        recent = totals[-3:]
        trend_estimate = round(
            (recent[0] + recent[1] * 2 + recent[2] * 3) / 6,
            1,
        )

    return jsonify({
        'has_data': True,
        'points': points,
        'moving_avg': moving,
        'trend_estimate': trend_estimate,
        'estimate_note': '近期三次成绩的加权均值，仅描述趋势，不代表下次成绩预测。',
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
        q = q.filter(
            User.department == current_user.department,
            User.class_name == current_user.class_name,
        )
    elif current_user.role == 'dept_head':
        q = q.filter(User.department == current_user.department)
    elif scope == 'dept' and current_user.department:
        q = q.filter(User.department == current_user.department)

    rows = q.all()

    # 各维度平均（需在 Python 端聚合 radar_data）
    groups = defaultdict(lambda: {
        'total_sum': 0,
        'count': 0,
        'dims': defaultdict(lambda: {'sum': 0, 'n': 0}),
    })
    for class_name, dept, avg_total, count in rows:
        key = (dept or '未设置系部', class_name or '未分班')
        groups[key]['total_sum'] += (avg_total or 0) * count
        groups[key]['count'] += count

    # 精确维度需取每条 session 的 radar_data
    sess_q = InterviewSession.query.join(User, InterviewSession.user_id == User.id) \
        .filter(InterviewSession.status == 'completed')
    if current_user.role == 'teacher':
        sess_q = sess_q.filter(
            User.department == current_user.department,
            User.class_name == current_user.class_name,
        )
    elif current_user.role == 'dept_head':
        sess_q = sess_q.filter(User.department == current_user.department)
    elif scope == 'dept' and current_user.department:
        sess_q = sess_q.filter(User.department == current_user.department)
    for s in sess_q.all():
        key = (
            s.user.department if s.user and s.user.department else '未设置系部',
            s.user.class_name if s.user and s.user.class_name else '未分班',
        )
        if s.radar_data:
            for dim in DIMENSIONS:
                value = s.radar_data.get(dim)
                if isinstance(value, (int, float)):
                    groups[key]['dims'][dim]['sum'] += value
                    groups[key]['dims'][dim]['n'] += 1

    result = []
    for (department, class_name), g in groups.items():
        if g['count'] == 0:
            continue
        dims_avg = {}
        for dim in DIMENSIONS:
            n = g['dims'][dim]['n']
            dims_avg[dim] = round(g['dims'][dim]['sum'] / n, 1) if n > 0 else 0
        result.append({
            'class_name': class_name,
            'department': department,
            'label': f'{department} / {class_name}',
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

    # 同时取问题和已点评回答，在 Python 端按 session 顺序配对。
    # suggestion 非 NULL 表示该 user 消息确实经过报告点评，避免把默认 False
    # 的未点评消息或 AI 消息误判为不合格回答。
    msgs = ChatMessage.query \
        .join(InterviewSession, ChatMessage.session_id == InterviewSession.id) \
        .join(User, InterviewSession.user_id == User.id) \
        .filter(InterviewSession.status == 'completed')

    if current_user.role == 'teacher':
        msgs = msgs.filter(
            User.department == current_user.department,
            User.class_name == current_user.class_name,
        )
    elif current_user.role == 'dept_head':
        msgs = msgs.filter(User.department == current_user.department)

    rows = msgs.order_by(
        ChatMessage.session_id,
        ChatMessage.timestamp,
        ChatMessage.id,
    ).all()

    def canonical_question(question):
        normalized = re.sub(r'[\s，。！？、,.!?：:；;“”"\'（）()【】\[\]]+', '', question).lower()
        category_rules = [
            (('自我介绍', '介绍自己'), '自我介绍与岗位优势'),
            (('线上故障', '生产故障', '事故处理', '系统故障'), '故障处理与复盘'),
            (('意见不一致', '团队冲突', '同事冲突', '方案分歧'), '团队分歧与沟通'),
            (('压力', '截止时间', '紧急任务'), '压力与时间管理'),
            (('为什么加入', '求职动机', '选择我们'), '求职动机'),
            (('项目', '经历'), '项目经历与个人贡献'),
            (('职业规划', '未来规划'), '职业规划'),
        ]
        for keywords, label in category_rules:
            if any(keyword in normalized for keyword in keywords):
                return label
        normalized = re.sub(r'^(请你|请|能否|可以|谈谈|说说|介绍一下)', '', normalized)
        return normalized[:80]

    bucket = defaultdict(lambda: {
        'total': 0,
        'bad': 0,
        'suggestions': [],
        'samples': [],
    })
    current_question = {}
    for msg in rows:
        content = (msg.content or '').strip()
        if msg.sender == 'ai':
            current_question[msg.session_id] = content
            continue
        if msg.sender != 'user' or msg.suggestion is None:
            continue

        question = current_question.get(msg.session_id, '').strip()
        if not question:
            continue
        key = canonical_question(question)
        if not key:
            continue
        bucket[key]['total'] += 1
        if not msg.is_good_response:
            bucket[key]['bad'] += 1
        if msg.suggestion:
            bucket[key]['suggestions'].append(msg.suggestion)
        bucket[key]['samples'].append(question)

    result = []
    for question_key, v in bucket.items():
        if v['total'] < 1:
            continue
        bad_rate = round(v['bad'] / v['total'], 2)
        display_question = v['samples'][0]
        snippet = (display_question[:60] + '…') if len(display_question) > 60 else display_question
        result.append({
            'question': snippet,
            'topic': question_key,
            'answer_snippet': snippet,
            'total': v['total'],
            'bad_rate': bad_rate,
            'sample_suggestion': v['suggestions'][0] if v['suggestions'] else '',
            'sample_question': v['samples'][0],
        })
    result.sort(key=lambda x: (x['bad_rate'], x['total']), reverse=True)
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
        user_id=current_user.id,
        status='completed',
        position_id=position.id,
    ).order_by(InterviewSession.start_time.desc()).limit(10).all()
    if not sessions:
        return jsonify({
            'has_data': False,
            'error': '尚无该岗位的已完成面试，不能用其他岗位历史推断匹配度',
        })

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

    # 使用目标岗位最近一次面试时冻结的简历，避免当前简历反向改写历史结论。
    resume_text = next(
        (session.resume_snapshot for session in sessions if session.resume_snapshot),
        '',
    )

    # 调用 LLM 评估
    try:
        from ..services.ai_agent import client, chat_request_options
        from ..config import Config
        system_prompt = """你是一位资深的技术招聘专家。请根据求职者的能力画像与岗位描述，评估匹配度。
严格返回 JSON：{"match_score": 0-100 整数, "strengths": ["优势1", ...], "gaps": ["待提升点1", ...], "suggestions": ["具体提升建议1", ...]}"""
        user_prompt = f"【岗位名称】{position.name}\n【岗位描述】{position.description[:1000]}\n【求职者能力画像(5维均分)】{my_dims}\n【简历摘要】{resume_text[:800]}"
        resp = client.chat.completions.create(
            **chat_request_options(),
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
