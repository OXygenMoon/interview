from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
import os
import time
import uuid

from .. import db
from ..utils.file_parser import extract_text_from_file
from ..services.ai_agent import analyze_resume_tags, anonymize_resume_pii

user_bp = Blueprint('user_api', __name__)


@user_bp.route('/resume/upload', methods=['POST'])
@login_required
def upload_resume():
    """上传并解析简历文件"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        # 保存临时文件
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'resumes')
        os.makedirs(upload_folder, exist_ok=True)
        safe_filename = f"resume_{current_user.id}_{int(time.time())}.{file.filename.split('.')[-1]}"
        filepath = os.path.join(upload_folder, safe_filename)
        file.save(filepath)

        # 解析文本
        text = extract_text_from_file(filepath)

        # 删除临时文件 (为了隐私，不留底，只留解析后的文本)
        try:
            os.remove(filepath)
        except:
            pass

        return jsonify({'status': 'success', 'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@user_bp.route('/resume/save', methods=['POST'])
@login_required
def save_resume():
    """保存简历文本，并自动提取标签"""
    data = request.json
    text = data.get('text', '').strip()

    if not text:
        return jsonify({'error': 'Empty content'}), 400

    try:
        # 1. 保存文本
        current_user.resume_text = text

        # 2. 调用 AI 提取标签 (想法二)
        tags = analyze_resume_tags(text)
        current_user.resume_tags = tags

        db.session.commit()

        return jsonify({'status': 'success', 'tags': tags})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@user_bp.route('/resume/anonymize', methods=['POST'])
@login_required
def anonymize_resume():
    """调用 AI 进行隐私脱敏 (想法三)"""
    data = request.json
    text = data.get('text', '')

    try:
        safe_text = anonymize_resume_pii(text)
        return jsonify({'status': 'success', 'text': safe_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500