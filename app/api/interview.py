from flask_login import current_user, login_required
from flask import Blueprint, request, jsonify, url_for, current_app
from datetime import datetime
import json
import os
import random
import time
import uuid
from threading import Thread


# 使用相对导入，引用上一级 app 目录下的 db 和 models
from .. import db
from ..models import InterviewSession, ChatMessage, User, SystemConfig
from ..config import Config

# 引入 AI 服务
from ..services.ai_agent import get_ai_response, generate_interview_report, transcribe_audio, analyze_image, evaluate_random_answer
# 引入 TTS 服务
from ..services.tts_service import text_to_speech
# 引入文件解析服务 (解析简历用)
from ..utils.file_parser import extract_text_from_file

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

DEFAULT_RANDOM_INTERVIEW_QUESTIONS = [
    "请你做一个 1 分钟的自我介绍，并突出与岗位相关的优势。",
    "请分享一个你遇到困难并最终解决的问题，重点说说你的思考过程。",
    "如果你和同事在方案上意见不一致，你会如何推进沟通并达成结果？",
    "请举例说明你如何在压力下保证任务质量和交付时间。",
    "你为什么想加入我们公司？你最看重的是什么？"
]


def get_random_interview_questions():
    """读取随机问题题库，若为空则返回默认题库"""
    raw_value = SystemConfig.get('random_interview_questions', '[]')
    questions = []

    try:
        parsed = json.loads(raw_value) if raw_value else []
        if isinstance(parsed, list):
            questions = [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        questions = []

    return questions if questions else DEFAULT_RANDOM_INTERVIEW_QUESTIONS


@api_bp.route('/create', methods=['POST'])
@login_required  # <--- 1. 加上这把锁，确保只有登录用户能创建
def create_session():
    """
    创建一个新的面试会话
    """
    try:
        # 1. 获取表单数据
        target_role = request.form.get('target_role', 'Python工程师')
        # 如果前端没传音色，默认用配置里的默认值，或者这里写死一个兜底
        voice_type = request.form.get('voice_type', 'zh_male_dayi_saturn_bigtts')
        difficulty = request.form.get('difficulty', '标准模式')
        position_id = request.form.get('position_id', type=int)
        
        # 处理简历选择
        resume_id = request.form.get('resume_id', type=int)
        use_resume = False
        resume_text = ""
        
        # 情况 A: 选择了已有的在线简历
        if resume_id:
            from ..models import Resume
            resume_obj = Resume.query.get(resume_id)
            if resume_obj and resume_obj.user_id == current_user.id:
                resume_text = resume_json_to_text(resume_obj.content)
                current_user.resume_text = resume_text
                db.session.commit()
                use_resume = True

        # 情况 B: 处理简历文件上传 (可选，优先级高于在线简历)
        if 'resume' in request.files:
            file = request.files['resume']
            if file.filename != '':
                # 保存临时文件
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'resumes')
                os.makedirs(upload_folder, exist_ok=True)

                # 生成安全的文件名
                safe_filename = f"resume_{int(time.time())}_{uuid.uuid4().hex[:8]}.{file.filename.split('.')[-1]}"
                filepath = os.path.join(upload_folder, safe_filename)
                file.save(filepath)

                # 解析文本
                uploaded_text = extract_text_from_file(filepath)
                if uploaded_text:
                    resume_text = uploaded_text
                    current_user.resume_text = resume_text
                    db.session.commit()
                    use_resume = True

        # 4. 创建面试会话
        # === 关键点：使用 current_user.id 而不是写死 1 ===
        session = InterviewSession(
            user_id=current_user.id,
            target_role=target_role,
            position_id=position_id if position_id else None,
            voice_type=voice_type,
            difficulty=difficulty,
            status="ongoing",
            start_time=datetime.now(),
            use_resume=use_resume
        )
        db.session.add(session)
        db.session.commit()

        # 5. 生成智能开场白
        # 如果用户刚才传了简历，或者用户数据库里本来就有简历
        user_resume = resume_text if resume_text else current_user.resume_text

        first_msg_content = f"你好，我是今天的面试官。我看你申请的是【{target_role}】岗位。"

        if use_resume and (user_resume or current_user.resume_text):
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


@api_bp.route('/<int:session_id>/chat', methods=['POST'])
def chat(session_id):
    """处理纯文本聊天消息 (支持视觉)"""
    try:
        data = request.json
        user_text = data.get('message')
        user_image = data.get('image')  # 新增：接收图片 Base64

        if not user_text:
            return jsonify({'error': 'Message is empty'}), 400

        # 1. 视觉分析 (如果有图片)
        visual_context_str = ""
        if user_image:
            # 异步调用还是同步？为了对话连贯性，这里暂时同步调用
            # Qwen-VL 响应通常较快
            visual_context_str = analyze_image(user_image)

        # 2. 保存用户消息
        user_msg = ChatMessage(
            session_id=session_id,
            sender="user",
            content=user_text,
            timestamp=datetime.now(),
            visual_context=visual_context_str  # 保存视觉标签
        )
        db.session.add(user_msg)
        db.session.commit()

        # 3. 获取上下文和 Session 信息
        history = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
        # 使用 get_or_404 防止 ID 不存在报错
        session = InterviewSession.query.get_or_404(session_id)

        # 4. 调用 AI 大脑
        role = getattr(session, 'target_role', 'Python工程师')

        # === ✅ 修改点 1：获取当前面试的难度模式 ===
        difficulty = getattr(session, 'difficulty', '标准模式')

        # === 构建上下文信息 ===
        context_info = ""
        if session.position_id:
            from ..models import Position
            pos = Position.query.get(session.position_id)
            if pos:
                if pos.company:
                     context_info += f"### 公司介绍：{pos.company.name}\n{pos.company.description}\n\n"
                context_info += f"### 岗位介绍：{pos.name}\n{pos.description}"

        # 5. 如果启用了简历，将简历拼接到 context_info
        if getattr(session, 'use_resume', False) and session.user.resume_text:
            context_info += f"\n\n### 求职者简历\n{session.user.resume_text}"

        # === ✅ 修改点 2：将 difficulty 和 visual_context 传给 AI 服务 ===
        ai_text = get_ai_response(
            history,
            target_role=role,
            difficulty=difficulty,
            context_info=context_info,
            visual_context_str=visual_context_str
        )

        # 6. 生成语音 (TTS)
        audio_url = None
        
        # 检查系统配置：是否启用了 TTS
        enable_tts = SystemConfig.get('enable_tts', 'true') == 'true'
        
        if enable_tts:
            try:
                audio_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'audio')
                # 传入 session 中保存的 voice_type
                audio_filename = text_to_speech(ai_text, audio_dir, specific_voice=session.voice_type)

                if audio_filename:
                    audio_url = url_for('static', filename=f'uploads/audio/{audio_filename}')
            except Exception as tts_error:
                print(f"TTS Generation Failed: {tts_error}")
                # TTS 失败不应阻断流程，继续返回文字

        # 5. 保存 AI 消息
        ai_msg = ChatMessage(
            session_id=session_id,
            sender="ai",
            content=ai_text,
            audio_url=audio_url,
            timestamp=datetime.now()
        )
        db.session.add(ai_msg)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'ai_response': ai_text,
            'audio_url': audio_url
        })

    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({'error': str(e)}), 500



@api_bp.route('/<int:session_id>/visual_feedback', methods=['POST'])
def visual_feedback(session_id):
    """
    处理纯视觉分析请求 (不产生对话)
    """
    try:
        data = request.json
        image_base64 = data.get('image')

        if not image_base64:
            return jsonify({'status': 'ignored'})

        # 调用 VLM 分析
        # 注意：这里我们希望得到更具体的反馈，而不仅仅是标签
        # 但为了复用 analyze_image，我们暂且使用它
        feedback_str = analyze_image(image_base64)

        if not feedback_str:
            return jsonify({'status': 'ignored'})

        # 可选：将分析结果异步保存到最新的 ChatMessage 中？
        # 或者仅仅返回给前端显示？这里选择仅仅返回给前端
        
        return jsonify({
            'status': 'success',
            'feedback': feedback_str
        })

    except Exception as e:
        print(f"Visual Feedback Error: {e}")
        return jsonify({'error': str(e)}), 500


def background_report_task(app, session_id):
    """后台线程：执行耗时的 AI 分析任务"""
    with app.app_context():  # 必须手动推入应用上下文，否则无法访问数据库
        try:
            print(f"⏳ [后台任务] 开始为 Session {session_id} 生成报告...")
            session = InterviewSession.query.get(session_id)
            if not session:
                return

            # (A) 获取聊天记录
            history = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()

            # (B) 调用 AI 生成报告 (这里最耗时)
            full_report = generate_interview_report(history, session.target_role)

            # (C) 保存数据
            overall = full_report.get('overall', {})
            session.total_score = overall.get('total_score', 0)
            session.radar_data = overall.get('scores', {})
            session.summary_comment = overall.get('comment', "无评语")

            # 保存逐句点评
            reviews_list = full_report.get('details', []) or full_report.get('details_list', [])
            user_msgs_db = [m for m in history if m.sender == 'user']

            for db_msg, review in zip(user_msgs_db, reviews_list):
                if isinstance(review, dict):
                    db_msg.suggestion = review.get('suggestion', '').strip()
                    db_msg.reference_answer = review.get('reference', '').strip()
                    db_msg.is_good_response = review.get('is_good', False)

            # (D) 关键：更新状态为 completed
            session.status = 'completed'
            db.session.commit()
            print(f"✅ [后台任务] Session {session_id} 报告生成完毕！")

        except Exception as e:
            print(f"❌ [后台任务] 报告生成失败: {e}")
            # 可选：如果失败，将状态改回 failed 或 completed 但分数为0
            # session.status = 'failed'
            # db.session.commit()


# 3. 修改：结束面试接口
@api_bp.route('/<int:session_id>/finish', methods=['POST'])
def finish_session(session_id):
    """结束面试（异步版）"""
    try:
        session = InterviewSession.query.get_or_404(session_id)

        # 防止重复提交
        if session.status in ['completed', 'processing']:
            return jsonify({'status': 'already_finished'})

        # 1. 立即更新状态为 "processing" (处理中)
        session.status = 'processing'
        session.end_time = datetime.now()
        db.session.commit()

        # 2. 启动后台线程
        # 注意：必须获取真实的 app 对象传给线程，current_app 是代理对象，线程中无法直接使用
        app = current_app._get_current_object()
        thread = Thread(target=background_report_task, args=(app, session_id))
        thread.start()

        # 3. 立即响应前端，不等待 AI
        return jsonify({
            'status': 'processing',
            'message': '面试已结束，AI 正在后台生成报告，请稍后在列表中查看。'
        })

    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


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

    data = request.json or {}
    question = (data.get('question') or '').strip()
    answer = (data.get('answer') or '').strip()

    if not answer:
        return jsonify({'error': 'answer is required'}), 400

    if not question:
        question = random.choice(get_random_interview_questions())

    result = evaluate_random_answer(question, answer)
    score = int(result.get('score', 0))
    score = max(0, min(100, score))
    evaluation = (result.get('evaluation') or '').strip() or "表达较完整，建议继续强化结构化表达。"
    suggestion = (result.get('suggestion') or '').strip() or "建议使用 STAR 法则组织答案：情境-任务-行动-结果。"

    evaluation_audio_url = None
    suggestion_audio_url = None

    audio_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'audio')
    dayi_voice = Config.VOLC_AVAILABLE_VOICES.get('大壹老师', 'zh_male_dayi_saturn_bigtts')

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
        'question': question,
        'answer': answer,
        'score': score,
        'evaluation': evaluation,
        'suggestion': suggestion,
        'evaluation_audio_url': evaluation_audio_url,
        'suggestion_audio_url': suggestion_audio_url
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

        # 1. 先删除关联的聊天记录
        ChatMessage.query.filter_by(session_id=session.id).delete()

        # 2. 再删除会话本身
        db.session.delete(session)
        db.session.commit()

        return jsonify({'status': 'success'})

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

        # 2. 调用 STT 服务 (Whisper/Volcengine等)
        print(f"🎤 [STT] 开始转录: {filepath}")
        user_text = transcribe_audio(filepath)
        print(f"🎤 [STT] 转录结果: {user_text}")

        # 3. 删除临时文件 (用完即焚)
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"⚠️ 删除临时文件失败: {e}")

        # 4. 处理空语音
        if not user_text or len(user_text.strip()) == 0:
            return jsonify({'status': 'empty'})

        return jsonify({'status': 'success', 'text': user_text})

    except Exception as e:
        print(f"❌ Transcription Error: {e}")
        return jsonify({'error': str(e)}), 500
