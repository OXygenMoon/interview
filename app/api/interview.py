from flask_login import current_user, login_required
from flask import Blueprint, request, jsonify, url_for, current_app
from datetime import datetime
import json
import os
import time
import uuid
from threading import Thread


# 使用相对导入，引用上一级 app 目录下的 db 和 models
from .. import db
from ..models import InterviewSession, ChatMessage, User

# 引入 AI 服务
from ..services.ai_agent import get_ai_response, generate_interview_report, transcribe_audio
# 引入 TTS 服务
from ..services.tts_service import text_to_speech
# 引入文件解析服务 (解析简历用)
from ..utils.file_parser import extract_text_from_file

api_bp = Blueprint('interview_api', __name__)


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

        # 2. 处理简历文件上传 (可选)
        resume_text = ""
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
                resume_text = extract_text_from_file(filepath)

                # 3. 将解析出的简历更新到【当前登录用户】的资料中
                if resume_text:
                    current_user.resume_text = resume_text
                    db.session.commit()  # 保存简历更新

        # 4. 创建面试会话
        # === 关键点：使用 current_user.id 而不是写死 1 ===
        session = InterviewSession(
            user_id=current_user.id,
            target_role=target_role,
            voice_type=voice_type,
            difficulty=difficulty,
            status="ongoing",
            start_time=datetime.now()
        )
        db.session.add(session)
        db.session.commit()

        # 5. 生成智能开场白
        # 如果用户刚才传了简历，或者用户数据库里本来就有简历
        user_resume = resume_text if resume_text else current_user.resume_text

        first_msg_content = f"你好，我是今天的面试官。我看你申请的是【{target_role}】岗位。"

        if user_resume:
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
    """处理纯文本聊天消息"""
    try:
        data = request.json
        user_text = data.get('message')
        if not user_text:
            return jsonify({'error': 'Message is empty'}), 400

        # 1. 保存用户消息
        user_msg = ChatMessage(session_id=session_id, sender="user", content=user_text, timestamp=datetime.now())
        db.session.add(user_msg)
        db.session.commit()

        # 2. 获取上下文和 Session 信息
        history = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
        # 使用 get_or_404 防止 ID 不存在报错
        session = InterviewSession.query.get_or_404(session_id)

        # 3. 调用 AI 大脑
        role = getattr(session, 'target_role', 'Python工程师')

        # === ✅ 修改点 1：获取当前面试的难度模式 ===
        difficulty = getattr(session, 'difficulty', '标准模式')

        # === ✅ 修改点 2：将 difficulty 传给 AI 服务 ===
        # 注意：请确保 app/services/ai_agent.py 里的 get_ai_response 函数定义也已经增加了 difficulty 参数
        ai_text = get_ai_response(history, target_role=role, difficulty=difficulty)

        # 4. 生成语音 (TTS)
        audio_url = None
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