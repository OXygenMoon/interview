import re
from urllib.parse import urlsplit

import requests
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import db, Resume

resume_bp = Blueprint('resume_api', __name__)

@resume_bp.route('/create', methods=['POST'])
@login_required
def create_resume():
    """创建新简历"""
    # 1. 数量限制检查
    count = Resume.query.filter_by(user_id=current_user.id).count()
    if count >= 5:
        return jsonify({'success': False, 'error': '最多只能创建 5 份简历'}), 400

    data = request.get_json(silent=True) or {}
    title = data.get('title', '我的简历').strip() or '我的简历'
    import_basic = data.get('import_basic', False)
    
    # 2. 准备初始内容
    content = {
        "basic": {},
        "education": [],
        "experience": [],
        "projects": [],
        "campus_experience": [{}],
        "awards": [{}],
        "skills": [],
        "hiddenSections": {
            "basic": False,
            "education": False,
            "experience": False,
            "projects": False,
            "campus_experience": False,
            "awards": False,
            "skills": False
        },
        "layout": {
            "density": 0
        }
    }
    
    # 3. 如果选择导入基础信息
    if import_basic and current_user.profile_info:
        content['basic'] = current_user.profile_info
    else:
        # 默认填充一点点
        content['basic'] = {
            "name": current_user.truename,
            "email": f"{current_user.username}@example.com" if current_user.username else ""
        }

    # 4. 创建
    resume = Resume(
        user_id=current_user.id,
        title=title,
        template_id='modern',
        content=content
    )
    db.session.add(resume)
    db.session.commit()
    
    return jsonify({'success': True, 'id': resume.id})


@resume_bp.route('/list', methods=['GET'])
@login_required
def get_resumes():
    resumes = Resume.query.filter_by(user_id=current_user.id).order_by(Resume.updated_at.desc()).all()
    return jsonify([{
        'id': r.id,
        'title': r.title,
        'template_id': r.template_id,
        'updated_at': r.updated_at.strftime('%Y-%m-%d %H:%M')
    } for r in resumes])

@resume_bp.route('/<int:id>', methods=['GET'])
@login_required
def get_resume(id):
    resume = Resume.query.get_or_404(id)
    if resume.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({
        'id': resume.id,
        'title': resume.title,
        'template_id': resume.template_id,
        'content': resume.content
    })

@resume_bp.route('/save', methods=['POST'])
@login_required
def save_resume():
    data = request.get_json(silent=True) or {}
    resume_id = data.get('id')
    content = data.get('content')
    title = data.get('title', '我的简历')
    template_id = data.get('template_id', 'modern')

    if resume_id:
        resume = db.session.get(Resume, resume_id)
        if resume and resume.user_id == current_user.id:
            resume.content = content
            resume.title = title
            resume.template_id = template_id
            db.session.commit()
            return jsonify({'success': True, 'id': resume.id})
        elif resume:
             return jsonify({'error': 'Unauthorized'}), 403

    # Create new
    resume = Resume(
        user_id=current_user.id,
        title=title,
        template_id=template_id,
        content=content
    )
    db.session.add(resume)
    db.session.commit()
    return jsonify({'success': True, 'id': resume.id})

@resume_bp.route('/rename', methods=['POST'])
@login_required
def rename_resume():
    """重命名简历"""
    data = request.get_json(silent=True) or {}
    resume_id = data.get('id')
    new_title = data.get('title')
    
    if not resume_id or not new_title:
        return jsonify({'error': '参数不完整'}), 400
        
    resume = Resume.query.get_or_404(resume_id)
    if resume.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
        
    resume.title = new_title.strip()
    db.session.commit()
    
    return jsonify({'success': True})


@resume_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_resume(id):
    resume = Resume.query.get_or_404(id)
    if resume.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(resume)
    db.session.commit()
    return jsonify({'success': True})

@resume_bp.route('/optimize', methods=['POST'])
@login_required
def optimize_resume():
    """
    AI 简历优化接口，使用服务端配置的模型
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': '请求格式错误'}), 400
    field_value = data.get('content', '')
    field_type = data.get('type', '自我评价')
    
    if not isinstance(field_value, str) or not field_value.strip():
        return jsonify({'success': False, 'error': '内容为空'}), 400
    if not isinstance(field_type, str):
        return jsonify({'success': False, 'error': '简历字段类型错误'}), 400

    prompt = f"""
    你是一个专业的简历优化专家。
    请优化以下这段简历中的【{field_type}】内容。
    
    要求：
    1. 语言风格职业、干练、有吸引力，符合行业标准。
    2. 突出已有的核心优势和成果，使用积极的动词；不得编造经历、职责或量化数据。
    3. 仅返回优化后的文本内容，不要包含任何前言、后语或解释。
    4. 不要使用 Markdown 代码块符号。
    
    原始内容：
    {field_value}
    """
    
    # 与面试共用服务端模型配置，包含 DeepSeek 最新模型 deepseek-flash。
    api_key = current_app.config.get('LLM_API_KEY')
    base_url = current_app.config.get('LLM_BASE_URL')
    model_name = current_app.config.get('LLM_MODEL_NAME')

    if not api_key or not base_url or not model_name:
        current_app.logger.error('Resume AI configuration is incomplete')
        return jsonify({'success': False, 'error': '系统配置错误，请检查 AI 密钥、服务地址和模型'}), 500

    url = f"{base_url.rstrip('/')}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一位专业的求职顾问和简历优化专家。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    # 使用同一份运行时配置，避免导入面试客户端及其模块级 Config。
    if urlsplit(base_url).hostname == 'api.deepseek.com':
        payload['thinking'] = {'type': current_app.config.get('LLM_THINKING', 'disabled')}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            current_app.logger.warning('Resume AI provider returned HTTP %s', response.status_code)
            return jsonify({'success': False, 'error': f'AI 服务请求失败 (状态码: {response.status_code})'}), 502
            
        res_data = response.json()
        
        choices = res_data.get('choices') if isinstance(res_data, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return jsonify({'success': False, 'error': 'AI 返回的数据格式异常'}), 502
        choice = choices[0]
        if choice.get('finish_reason') == 'length':
            return jsonify({'success': False, 'error': 'AI 返回内容不完整，请缩短原文后重试'}), 502
        message = choice.get('message')
        full_content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(full_content, str):
            return jsonify({'success': False, 'error': 'AI 未返回有效内容'}), 502
        
        # 清洗 Markdown
        clean_text = re.sub(r'^\s*```[^\n]*\n|\n?```\s*$', '', full_content).strip()
        clean_text = clean_text.replace('`', '')
        
        if not clean_text:
            return jsonify({'success': False, 'error': 'AI 未返回有效内容'}), 502

        return jsonify({
            'success': True, 
            'suggestion': clean_text
        })
                 
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'AI服务响应超时，请稍后再试'}), 504
    except requests.exceptions.RequestException:
        current_app.logger.warning('Resume AI provider request failed')
        return jsonify({'success': False, 'error': 'AI 服务暂时不可用，请稍后再试'}), 502
    except ValueError:
        return jsonify({'success': False, 'error': 'AI 返回的数据格式异常'}), 502
