from flask_login import current_user, login_required
from flask import Blueprint, request, jsonify, url_for, current_app
from datetime import datetime
import json
import os
import random
import tempfile
import uuid


# 使用相对导入，引用上一级 app 目录下的 db 和 models
from .. import db
from ..models import InterviewSession, ChatMessage, SystemConfig, RandomPracticeAttempt
from ..config import Config

# 引入 AI 服务
from ..services.ai_agent import AIServiceError, CHAT_PROMPT_VERSION, REPORT_PROMPT_VERSION, generate_interview_report, transcribe_audio, analyze_image, evaluate_random_answer
from ..services.question_bank import get_random_interview_questions
# 引入 TTS 服务
from ..services.tts_service import text_to_speech
# 引入文件解析服务 (解析简历用)
from ..utils.file_parser import extract_text_from_file
# 面试会话状态：10min TTL 续接 / 冷却系统 / 复盘门槛
from ..utils.session_state import (
    get_resumable_session,
    mark_abandoned,
    get_cooldown_status,
    soft_delete_session,
)

def resume_json_to_text(data):
    """将结构化简历转换为文本"""
    if not data:
        return ""
    
    lines = []
    hidden = data.get('hiddenSections') or {}
    if not isinstance(hidden, dict):
        hidden = {}

    def section_visible(section):
        return not hidden.get(section)

    def has_text(value):
        return bool(str(value or '').strip())

    basic = data.get('basic', {})

    if section_visible('basic'):
        lines.append(f"姓名: {basic.get('name', '')}")
        lines.append(f"求职意向: {basic.get('job_target', '')}")
        lines.append(f"自我评价: {basic.get('self_evaluation', '')}")
    
    if section_visible('education'):
        education = [
            edu for edu in data.get('education', [])
            if any(has_text(edu.get(key)) for key in ('school', 'major', 'date'))
        ]
        if education:
            lines.append("\n教育背景:")
            for edu in education:
                lines.append(f"- {edu.get('school', '')} | {edu.get('major', '')} | {edu.get('date', '')}")
        
    if section_visible('experience'):
        experience = [
            exp for exp in data.get('experience', [])
            if any(has_text(exp.get(key)) for key in ('company', 'position', 'date', 'description'))
        ]
        if experience:
            lines.append("\n工作经历:")
            for exp in experience:
                lines.append(f"- {exp.get('company', '')} | {exp.get('position', '')} | {exp.get('date', '')}")
                lines.append(f"  描述: {exp.get('description', '')}")
        
    if section_visible('projects'):
        projects = [
            proj for proj in data.get('projects', [])
            if any(has_text(proj.get(key)) for key in ('name', 'role', 'date', 'description'))
        ]
        if projects:
            lines.append("\n项目经历:")
            for proj in projects:
                lines.append(f"- {proj.get('name', '')} | {proj.get('role', '')} | {proj.get('date', '')}")
                lines.append(f"  描述: {proj.get('description', '')}")

    if section_visible('campus_experience'):
        campus_experience = [
            item for item in data.get('campus_experience', [])
            if any(has_text(item.get(key)) for key in ('organization', 'position', 'achievements'))
        ]
        if campus_experience:
            lines.append("\n校园内经历:")
            for item in campus_experience:
                lines.append(f"- {item.get('organization', '')} | {item.get('position', '')}")
                lines.append(f"  主要事迹: {item.get('achievements', '')}")

    if section_visible('awards'):
        awards = [
            award for award in data.get('awards', [])
            if any(has_text(award.get(key)) for key in ('name', 'rank', 'level'))
        ]
        if awards:
            lines.append("\n获奖:")
            for award in awards:
                lines.append(f"- {award.get('name', '')} | {award.get('rank', '')} | {award.get('level', '')}")
        
    if section_visible('skills'):
        skills = [skill for skill in data.get('skills', []) if has_text(skill)]
        if skills:
            lines.append("\n技能:")
            lines.append(", ".join(skills))
    
    return "\n".join(lines)

api_bp = Blueprint('interview_api', __name__)

@api_bp.route('/create', methods=['POST'])
@login_required  # <--- 1. 加上这把锁，确保只有登录用户能创建
def create_session():
    """
    创建一个新的面试会话
    """
    try:
        # 0. 冷却系统守卫：放弃罚时 / 完成冷却 / 复盘门槛
        cd = get_cooldown_status(current_user.id)
        if not cd['can_start']:
            return jsonify({'error': 'cooldown', 'cooldown': cd}), 423

        # 1. 获取表单数据
        target_role = (request.form.get('target_role') or 'Python工程师').strip()[:100]
        voice_type = request.form.get('voice_type', 'zh_male_dayi_saturn_bigtts')
        difficulty = request.form.get('difficulty', '标准模式')
        position_id = request.form.get('position_id', type=int)
        if voice_type not in Config.VOLC_AVAILABLE_VOICES.values():
            voice_type = Config.VOLC_DEFAULT_VOICE
        if difficulty not in {'新手模式', '标准模式', '压力模式'}:
            return jsonify({'error': 'invalid difficulty'}), 400

        from ..models import Position, Resume
        position = None
        position_snapshot = None
        if position_id:
            position = db.session.get(Position, position_id)
            if position is None:
                return jsonify({'error': 'position not found'}), 404
            target_role = position.name
            position_snapshot = {
                'position_id': position.id,
                'position_name': position.name,
                'position_description': position.description or '',
                'company_id': position.company.id if position.company else None,
                'company_name': position.company.name if position.company else '',
                'company_description': position.company.description if position.company else '',
            }
        
        # 处理简历选择
        resume_id = request.form.get('resume_id', type=int)
        use_resume = False
        resume_text = ""
        
        if resume_id:
            resume_obj = db.session.get(Resume, resume_id)
            if not resume_obj or resume_obj.user_id != current_user.id:
                return jsonify({'error': 'resume not found'}), 404
            resume_text = resume_json_to_text(resume_obj.content)
            if not resume_text:
                return jsonify({'error': 'selected resume is empty'}), 400
            use_resume = True

        # 情况 B: 处理简历文件上传 (可选，优先级高于在线简历)
        temporary_resume_path = None
        if 'resume' in request.files:
            file = request.files['resume']
            if file.filename != '':
                extension = os.path.splitext(file.filename)[1].lower()
                if extension not in {'.pdf', '.docx'}:
                    return jsonify({'error': 'resume must be a PDF or DOCX file'}), 400
                temp_dir = os.path.join(current_app.instance_path, 'uploads', 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    prefix='resume_',
                    suffix=extension,
                    dir=temp_dir,
                    delete=False,
                ) as temporary_file:
                    temporary_resume_path = temporary_file.name
                try:
                    file.save(temporary_resume_path)
                    uploaded_text = extract_text_from_file(temporary_resume_path)
                finally:
                    try:
                        os.remove(temporary_resume_path)
                    except OSError:
                        pass
                if not uploaded_text:
                    return jsonify({'error': 'resume could not be parsed or is empty'}), 400
                resume_text = uploaded_text
                resume_id = None
                use_resume = True

        # 4. 创建面试会话
        # === 关键点：使用 current_user.id 而不是写死 1 ===
        session = InterviewSession(
            user_id=current_user.id,
            target_role=target_role,
            position_id=position_id if position_id else None,
            resume_id=resume_id if use_resume else None,
            resume_snapshot=resume_text[:50000] if use_resume else None,
            position_snapshot=position_snapshot,
            llm_model=Config.LLM_MODEL_NAME,
            prompt_version=CHAT_PROMPT_VERSION,
            voice_type=voice_type,
            difficulty=difficulty,
            status="ongoing",
            start_time=datetime.now(),
            use_resume=use_resume
        )
        db.session.add(session)
        db.session.flush()
        first_msg_content = f"你好，我是今天的面试官。我看你申请的是【{target_role}】岗位。"

        if use_resume and resume_text:
            first_msg_content += " 我已经阅读了你的简历，对你的经历很感兴趣。请先做一个简单的自我介绍。"
        else:
            first_msg_content += " 请先做一个简单的自我介绍。"

        # 6. 保存开场白到聊天记录
        welcome_msg = ChatMessage(
            session_id=session.id,
            sender="ai",
            content=first_msg_content,
            timestamp=datetime.now()
        )
        db.session.add(welcome_msg)
        db.session.commit()

        return jsonify({'session_id': session.id, 'message': 'Session created'})

    except Exception as e:
        print(f"Create Session Error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/cooldown-status', methods=['GET'])
@login_required
def cooldown_status():
    """查询当前用户能否开始新面试（冷却/复盘状态）"""
    return jsonify(get_cooldown_status(current_user.id))


@api_bp.route('/resumable', methods=['GET'])
@login_required
def resumable():
    """查询当前用户是否有可续接的进行中面试（10min TTL 内）"""
    s = get_resumable_session(current_user.id)
    if not s:
        return jsonify({'has_session': False})
    return jsonify({
        'has_session': True,
        'session_id': s.id,
        'target_role': s.target_role,
        'start_time': s.start_time.strftime('%Y-%m-%d %H:%M') if s.start_time else None,
        'last_activity': s.last_activity.strftime('%Y-%m-%d %H:%M') if s.last_activity else None,
    })


@api_bp.route('/<int:session_id>/abandon', methods=['POST'])
@login_required
def abandon(session_id):
    """学生主动放弃进行中的面试（触发放弃罚时）"""
    session = InterviewSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if session.status not in ('ongoing', 'expired'):
        return jsonify({'error': '该面试已结束，无需放弃'}), 400
    mark_abandoned(session)
    return jsonify({'status': 'abandoned'})


@api_bp.route('/<int:session_id>/chat', methods=['POST'])
@login_required
def chat(session_id):
    """处理纯文本聊天消息 (支持视觉) — SSE 流式响应：逐 token + 分句 TTS"""
    from flask import Response, stream_with_context
    from ..services.ai_agent import stream_ai_response
    from ..services.tts_service import text_to_speech_chunks

    data = request.get_json(silent=True) or {}
    user_text = data.get('message')
    user_image = data.get('image')

    if not user_text:
        return jsonify({'error': 'Message is empty'}), 400

    # 1. 鉴权 + 获取 Session（必须在任何写操作之前）
    session = InterviewSession.query.get_or_404(session_id)
    if session.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    if session.status != 'ongoing':
        return jsonify({'error': '该面试已结束，无法继续对话'}), 400

    # 2. 视觉分析 (同步先做，结果拼到上下文)
    visual_context_str = ""
    if user_image:
        try:
            visual_context_str = analyze_image(user_image)
        except Exception as e:
            print(f"Visual analyze error: {e}")

    # 3. 保存用户消息 + 刷新活跃时间
    user_msg = ChatMessage(
        session_id=session_id,
        sender="user",
        content=user_text,
        timestamp=datetime.now(),
        visual_context=visual_context_str
    )
    db.session.add(user_msg)
    session.last_activity = datetime.now()
    db.session.commit()

    # 4. 取上下文
    history = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
    role = getattr(session, 'target_role', 'Python工程师')
    difficulty = getattr(session, 'difficulty', '标准模式')

    context_info = ""
    if session.position_snapshot:
        snapshot = session.position_snapshot
        context_info += (
            f"### 公司介绍：{snapshot.get('company_name', '')}\n"
            f"{snapshot.get('company_description', '')}\n\n"
            f"### 岗位介绍：{snapshot.get('position_name', role)}\n"
            f"{snapshot.get('position_description', '')}"
        )
    elif session.position_id:
        from ..models import Position
        pos = db.session.get(Position, session.position_id)
        if pos:
            if pos.company:
                context_info += f"### 公司介绍：{pos.company.name}\n{pos.company.description}\n\n"
            context_info += f"### 岗位介绍：{pos.name}\n{pos.description}"
    if getattr(session, 'use_resume', False):
        resume_context = session.resume_snapshot or session.user.resume_text
        if resume_context:
            context_info += f"\n\n### 求职者简历\n{resume_context}"
    if session.prior_round_summary:
        context_info += (
            "\n\n### 上一轮面试复盘（请针对短板继续追问，避免重复原题）\n"
            + json.dumps(session.prior_round_summary, ensure_ascii=False)
        )

    enable_tts = SystemConfig.get('enable_tts', 'true') == 'true'
    audio_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'audio')

    def sse(obj):
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def generate():
        full_text = ""
        audio_urls = []
        generation_error = None
        try:
            if visual_context_str:
                yield sse({'type': 'visual', 'feedback': visual_context_str})
            # ① 流式输出 AI token（打字机效果）
            try:
                for token in stream_ai_response(
                    history, target_role=role, difficulty=difficulty,
                    context_info=context_info, visual_context_str=visual_context_str,
                    round_num=getattr(session, 'round', 1) or 1
                ):
                    full_text += token
                    yield sse({'type': 'token', 'content': token})
            except Exception as e:
                print(f"❌ Stream AI Error: {e}")
                generation_error = str(e)
                if not full_text:
                    yield sse({'type': 'error', 'message': 'AI 响应中断，请重试'})
                else:
                    yield sse({'type': 'error', 'message': 'AI 响应不完整，请重试'})

            # ② 流式 TTS：分句生成，逐片返回 URL，前端排队播放
            if enable_tts and full_text and not generation_error:
                try:
                    for idx, fn in text_to_speech_chunks(full_text, audio_dir, specific_voice=session.voice_type):
                        url = url_for('static', filename=f'uploads/audio/{fn}')
                        audio_urls.append(url)
                        yield sse({'type': 'audio', 'url': url, 'index': idx})
                except Exception as e:
                    print(f"TTS stream error: {e}")

            # ③ 保存 AI 消息（完整文本 + 音频片段）
            ai_msg = ChatMessage(
                session_id=session_id,
                sender="ai",
                content=full_text,
                audio_url=audio_urls[0] if audio_urls else None,
                audio_urls=audio_urls if audio_urls else None,
                timestamp=datetime.now(),
                generation_status='failed' if generation_error else 'completed',
                model_name=Config.LLM_MODEL_NAME,
                error_message=generation_error,
            )
            db.session.add(ai_msg)
            session.last_activity = datetime.now()
            db.session.commit()
            yield sse({'type': 'done', 'message_id': ai_msg.id})
        except Exception as e:
            print(f"❌ Chat stream error: {e}")
            db.session.rollback()
            yield sse({'type': 'error', 'message': str(e)})

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
def background_report_task(session_id):
    """生成面试报告（RQ 任务 / Thread 通用入口，自建 app 上下文）。"""
    from .. import create_app
    app = create_app()
    with app.app_context():  # 独立上下文，RQ worker 进程与 Thread 回退都适用
        try:
            print(f"⏳ [后台任务] 开始为 Session {session_id} 生成报告...")
            session = db.session.get(InterviewSession, session_id)
            if not session:
                return {'status': 'missing'}
            if session.status == 'completed':
                return {'status': 'already-completed'}

            session.report_attempt_count = (
                session.report_attempt_count or 0
            ) + 1
            session.report_started_at = datetime.now()
            session.report_finished_at = None
            session.report_queue_status = 'started'
            db.session.commit()

            # (A) 获取聊天记录
            history = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()

            # (B) 调用 AI 生成报告 (这里最耗时)
            full_report = generate_interview_report(
                history, session.target_role,
                round_num=session.round or 1,
                difficulty=session.difficulty or '标准模式',
                position_context=session.position_snapshot,
            )

            # (C) 保存数据
            overall = full_report.get('overall', {})
            session.total_score = overall['total_score']
            session.radar_data = overall['scores']
            session.summary_comment = overall['comment']
            session.evaluation_source = full_report.get('evaluation_source', 'ai')
            session.report_model = Config.LLM_REPORT
            session.report_prompt_version = REPORT_PROMPT_VERSION
            session.report_error = None

            # 保存逐句点评
            reviews_list = full_report.get('details', []) or full_report.get('details_list', [])
            user_msgs_db = [
                message
                for message in history
                if message.sender == 'user'
                and message.generation_status == 'completed'
                and (message.content or '').strip()
            ]
            user_msgs_by_id = {message.id: message for message in user_msgs_db}

            for index, review in enumerate(reviews_list):
                if isinstance(review, dict):
                    db_msg = user_msgs_by_id.get(review.get('message_id'))
                    if db_msg is None and index < len(user_msgs_db):
                        # Compatibility for reports produced before message IDs
                        # were included in the response.
                        db_msg = user_msgs_db[index]
                    if db_msg is None:
                        continue
                    db_msg.suggestion = (review.get('suggestion') or '').strip()
                    db_msg.reference_answer = (review.get('reference') or '').strip()
                    db_msg.is_good_response = bool(review.get('is_good', False))

            # (D) 关键：更新状态为 completed
            session.status = 'completed'
            session.report_queue_status = 'completed'
            session.report_finished_at = datetime.now()
            session.report_error = None
            db.session.commit()
            print(f"✅ [后台任务] Session {session_id} 报告生成完毕！")
            from ..services.learning_achievements import notify_wikibook_learning_change
            notify_wikibook_learning_change(session.user_id)
            return {'status': 'completed', 'session_id': session_id}

        except Exception as e:
            print(f"❌ [后台任务] 报告生成失败: {e}")
            db.session.rollback()
            try:
                from rq import get_current_job
                job = get_current_job()
                will_retry = bool(
                    job is not None
                    and (job.retries_left or 0) > 0
                )
                session = db.session.get(InterviewSession, session_id)
                if session:
                    session.status = 'processing' if will_retry else 'failed'
                    session.total_score = None
                    session.radar_data = None
                    session.summary_comment = None
                    session.evaluation_source = None
                    session.report_model = Config.LLM_REPORT
                    session.report_prompt_version = REPORT_PROMPT_VERSION
                    session.report_error = str(e)[:1000]
                    session.report_queue_status = (
                        'retrying' if will_retry else 'failed'
                    )
                    session.report_finished_at = (
                        None if will_retry else datetime.now()
                    )
                    db.session.commit()
            except Exception as e2:
                print(f"❌ [后台任务] 状态回写失败: {e2}")
                db.session.rollback()
            raise


# 3. 修改：结束面试接口
@api_bp.route('/<int:session_id>/finish', methods=['POST'])
@login_required
def finish_session(session_id):
    """结束面试（异步版）"""
    try:
        session = db.get_or_404(InterviewSession, session_id)

        # 鉴权：仅本人或管理员可结束
        if session.user_id != current_user.id and current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403

        # 防止重复提交（failed 状态允许重试）
        if session.status in ['completed', 'processing']:
            return jsonify({
                'status': 'already_finished',
                'report_backend': session.report_queue_backend,
                'report_job_id': session.report_job_id,
                'report_queue_status': session.report_queue_status,
            })
        if session.status not in {'ongoing', 'failed', 'expired'}:
            return jsonify({'error': '当前面试状态不能生成报告'}), 409

        # 1. 立即更新状态为 "processing" (处理中)
        processing_started_at = datetime.now()
        submission_count = (session.report_submission_count or 0) + 1
        session.status = 'processing'
        session.end_time = processing_started_at
        session.last_activity = processing_started_at
        session.report_error = None
        session.report_job_id = None
        session.report_queue_backend = None
        session.report_queue_status = 'enqueueing'
        session.report_submission_count = submission_count
        session.report_attempt_count = 0
        session.report_enqueued_at = processing_started_at
        session.report_started_at = None
        session.report_finished_at = None
        db.session.commit()

        # 2. 入队报告生成任务。生产 rq 模式绝不静默退回线程。
        from ..services.report_queue import ReportQueueError, enqueue_report
        try:
            job = enqueue_report(
                session_id,
                submission_count=submission_count,
                defer_thread_start=True,
            )
        except ReportQueueError as queue_error:
            db.session.expire_all()
            session = db.session.get(InterviewSession, session_id)
            session.status = 'failed'
            session.report_queue_status = 'enqueue_failed'
            session.report_finished_at = datetime.now()
            session.report_error = str(queue_error)[:1000]
            db.session.commit()
            return jsonify({
                'status': 'failed',
                'error': '报告任务入队失败，请稍后重试。',
            }), 503

        # Refresh first so a very fast RQ worker cannot have its state
        # overwritten by this request.
        db.session.refresh(session)
        session.report_job_id = job.get('job_id')
        session.report_queue_backend = job.get('backend')
        if session.report_queue_status == 'enqueueing':
            session.report_queue_status = (
                'queued' if job.get('backend') == 'rq' else 'starting'
            )
        db.session.commit()
        starter = job.get('_start')
        if starter:
            starter()

        # 3. 立即响应前端，不等待 AI
        return jsonify({
            'status': 'processing',
            'message': '面试已结束，AI 正在后台生成报告，请稍后在列表中查看。',
            'report_backend': job.get('backend'),
            'report_job_id': job.get('job_id'),
            'worker_available': job.get('worker_available'),
            'durable': job.get('durable'),
        })

    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/<int:session_id>/report-status', methods=['GET'])
@login_required
def report_status(session_id):
    """查询报告生成状态（前端轮询用）"""
    session = db.get_or_404(InterviewSession, session_id)
    if session.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    from ..services.report_queue import sync_report_job_state
    if sync_report_job_state(session):
        db.session.commit()
    return jsonify({
        'session_id': session.id,
        'status': session.status,  # processing / completed / failed / ...
        'total_score': session.total_score,
        'has_report': session.status == 'completed' and bool(session.summary_comment),
        'report_error': session.report_error if session.status == 'failed' else None,
        'report_job_id': session.report_job_id,
        'report_backend': session.report_queue_backend,
        'report_queue_status': session.report_queue_status,
        'report_submission_count': session.report_submission_count,
        'report_attempt_count': session.report_attempt_count,
    })


@api_bp.route('/<int:session_id>/next-round', methods=['POST'])
@login_required
def next_round(session_id):
    """面试进阶链：基于上一轮 completed session 创建下一轮（复面/终面）。"""
    from sqlalchemy.exc import IntegrityError

    prev = InterviewSession.query.get_or_404(session_id)
    if prev.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if prev.status != 'completed':
        return jsonify({'error': '上一轮面试尚未完成，无法进入下一轮'}), 400
    if (prev.round or 1) >= 3:
        return jsonify({'error': '已是终面，无下一轮'}), 400

    existing = InterviewSession.query.filter_by(parent_session_id=prev.id).first()
    if existing:
        return jsonify({
            'status': 'already_created',
            'session_id': existing.id,
            'round': existing.round,
        }), 409

    # 冷却系统守卫（复用 create_session 同款）
    cd = get_cooldown_status(current_user.id)
    if not cd['can_start']:
        return jsonify({'error': 'cooldown', 'cooldown': cd}), 423

    next_round_num = (prev.round or 1) + 1
    session = InterviewSession(
        user_id=current_user.id,
        target_role=prev.target_role,
        position_id=prev.position_id,
        voice_type=prev.voice_type,
        difficulty=prev.difficulty,
        status="ongoing",
        start_time=datetime.now(),
        last_activity=datetime.now(),
        use_resume=prev.use_resume,
        resume_id=prev.resume_id,
        resume_snapshot=prev.resume_snapshot,
        position_snapshot=prev.position_snapshot,
        prior_round_summary={
            'round': prev.round or 1,
            'total_score': prev.total_score,
            'radar_data': prev.radar_data,
            'summary_comment': prev.summary_comment,
        },
        llm_model=Config.LLM_MODEL_NAME,
        prompt_version=CHAT_PROMPT_VERSION,
        round=next_round_num,
        parent_session_id=prev.id,
    )
    db.session.add(session)
    try:
        db.session.commit()
    except IntegrityError:
        # 并发双击时由数据库唯一索引保证只创建一个子场次。
        db.session.rollback()
        existing = InterviewSession.query.filter_by(parent_session_id=prev.id).first()
        if existing:
            return jsonify({
                'status': 'already_created',
                'session_id': existing.id,
                'round': existing.round,
            }), 409
        raise

    round_name = {2: "复面（技术面）", 3: "终面（高管面）"}.get(next_round_num, f"第{next_round_num}轮")
    first_msg = f"你好，我是本轮的面试官。这是你的{round_name}。我们将重点考察与上一轮不同的方面。请先做一个简短的自我介绍，并说说你希望在本轮展示什么。"
    welcome = ChatMessage(
        session_id=session.id,
        sender="ai",
        content=first_msg,
        timestamp=datetime.now(),
    )
    db.session.add(welcome)
    db.session.commit()

    return jsonify({'session_id': session.id, 'round': next_round_num, 'round_name': round_name})


@api_bp.route('/processing-statuses', methods=['GET'])
@login_required
def processing_statuses():
    """返回当前用户处于 processing 的 session（首页自动轮询刷新用）"""
    from ..utils.session_state import reap_stuck_reports, expire_stale_sessions
    reap_stuck_reports(current_user.id)
    expire_stale_sessions(current_user.id)
    sessions = InterviewSession.query.filter_by(
        user_id=current_user.id, status='processing'
    ).all()
    from ..services.report_queue import sync_report_job_state
    state_changes = [
        sync_report_job_state(session)
        for session in sessions
    ]
    if any(state_changes):
        db.session.commit()
    return jsonify({
        'processing': [
            session.id
            for session in sessions
            if session.status == 'processing'
        ],
    })


@api_bp.route('/random/question', methods=['GET'])
@login_required
def get_random_question():
    """随机抽取一道单题面试题"""
    if current_user.role != 'student':
        return jsonify({'error': 'Only students are allowed'}), 403

    questions = get_random_interview_questions()
    question = random.choice(questions)
    return jsonify({
        'status': 'success',
        'question': question,
        'total_questions': len(questions)
    })


@api_bp.route('/random/evaluate', methods=['POST'])
@login_required
def evaluate_random_question():
    """单题作答评分：返回分数、评价、建议与对应语音"""
    if current_user.role != 'student':
        return jsonify({'error': 'Only students are allowed'}), 403

    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    answer = (data.get('answer') or '').strip()
    image = (data.get('image') or '').strip()

    if not answer:
        return jsonify({'error': 'answer is required'}), 400

    questions = get_random_interview_questions()
    if not question:
        question = random.choice(questions)
    elif question not in questions:
        return jsonify({'error': 'question is not in the active question bank'}), 400

    visual_feedback = ''
    if image and SystemConfig.get('enable_video', 'true') == 'true':
        visual_feedback = analyze_image(image)

    attempt = RandomPracticeAttempt(
        user_id=current_user.id,
        question=question,
        answer=answer,
        visual_feedback=visual_feedback or None,
        status='evaluation_failed',
        model_name=Config.LLM_REPORT,
    )
    db.session.add(attempt)
    try:
        result = evaluate_random_answer(question, answer)
    except AIServiceError as exc:
        attempt.error_message = str(exc)
        db.session.commit()
        return jsonify({
            'status': 'evaluation_failed',
            'attempt_id': attempt.id,
            'error': 'AI 评估暂时不可用，本次回答已保存，可稍后重试。',
        }), 503

    score = int(result.get('score', 0))
    score = max(0, min(100, score))
    evaluation = result['evaluation'].strip()
    suggestion = result['suggestion'].strip()
    attempt.score = score
    attempt.evaluation = evaluation
    attempt.suggestion = suggestion
    attempt.status = 'completed'
    attempt.error_message = None
    db.session.commit()

    evaluation_audio_url = None
    suggestion_audio_url = None

    audio_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'audio')
    dayi_voice = Config.VOLC_AVAILABLE_VOICES.get('大壹老师', 'zh_male_dayi_saturn_bigtts')

    if SystemConfig.get('enable_tts', 'true') == 'true':
        try:
            evaluation_audio = text_to_speech(evaluation, audio_dir, specific_voice=dayi_voice)
            if evaluation_audio:
                evaluation_audio_url = url_for('static', filename=f'uploads/audio/{evaluation_audio}')
        except Exception as e:
            print(f"⚠️ 评价语音生成失败: {e}")

        try:
            suggestion_audio = text_to_speech(suggestion, audio_dir, specific_voice=dayi_voice)
            if suggestion_audio:
                suggestion_audio_url = url_for('static', filename=f'uploads/audio/{suggestion_audio}')
        except Exception as e:
            print(f"⚠️ 建议语音生成失败: {e}")

    return jsonify({
        'status': 'success',
        'attempt_id': attempt.id,
        'question': question,
        'answer': answer,
        'score': score,
        'evaluation': evaluation,
        'suggestion': suggestion,
        'evaluation_audio_url': evaluation_audio_url,
        'suggestion_audio_url': suggestion_audio_url,
        'visual_feedback': visual_feedback,
    })


@api_bp.route('/<int:session_id>/delete', methods=['POST'])
@login_required
def delete_session(session_id):
    """删除面试记录"""
    try:
        session = InterviewSession.query.get_or_404(session_id)

        # 权限检查：只有本人或管理员可以删除
        if session.user_id != current_user.id and current_user.role != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403

        if (
            session.user_id == current_user.id
            and session.status == 'completed'
            and not session.reviewed
        ):
            return jsonify({'error': '请先查看复盘报告，再隐藏该记录'}), 409

        soft_delete_session(
            session,
            current_user.id,
            reason='student_requested' if session.user_id == current_user.id else 'admin_requested',
        )

        return jsonify({'status': 'success'})

    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        print(f"Delete Error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/transcribe', methods=['POST'])
@login_required
def transcribe_audio_only():
    """
    【新增】轻量级接口：仅将语音转换为文字，不生成AI回复
    """
    filepath = None
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file'}), 400

        file = request.files['audio']

        # 1. 保存临时文件
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'temp')
        os.makedirs(upload_folder, exist_ok=True)

        # 使用 uuid 生成唯一文件名，避免冲突
        filename = f"transcribe_{current_user.id}_{uuid.uuid4().hex}.webm"
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        # 2. 本地解码并识别，音频不上传到外部服务。
        user_text = transcribe_audio(filepath)
        print(f"🎤 [STT] 转录结果: {user_text}")

        # 3. 处理空语音
        if not user_text or len(user_text.strip()) == 0:
            return jsonify({'status': 'empty'})

        return jsonify({'status': 'success', 'text': user_text})

    except AIServiceError as e:
        return jsonify({'status': 'error', 'error': str(e)}), 503
    except Exception as e:
        print(f"❌ Transcription Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        for path in {filepath}:
            if not path:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                print(f"⚠️ 删除临时文件失败: {cleanup_error}")
