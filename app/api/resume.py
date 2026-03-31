from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.models import db, Resume
import json
import requests
import re

resume_bp = Blueprint('resume_api', __name__)

@resume_bp.route('/create', methods=['POST'])
@login_required
def create_resume():
    """创建新简历"""
    # 1. 数量限制检查
    count = Resume.query.filter_by(user_id=current_user.id).count()
    if count >= 5:
        return jsonify({'success': False, 'error': '最多只能创建 5 份简历'}), 400

    data = request.json
    title = data.get('title', '我的简历').strip() or '我的简历'
    import_basic = data.get('import_basic', False)
    
    # 2. 准备初始内容
    content = {
        "basic": {},
        "education": [],
        "experience": [],
        "projects": [],
        "skills": []
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
    data = request.json
    resume_id = data.get('id')
    content = data.get('content')
    title = data.get('title', '我的简历')
    template_id = data.get('template_id', 'modern')

    if resume_id:
        resume = Resume.query.get(resume_id)
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
    data = request.json
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
    AI 简历优化接口 (修复版)
    """
    data = request.json
    field_value = data.get('content', '')
    field_type = data.get('type', '自我评价')
    
    if not field_value:
        return jsonify({'error': '内容为空'}), 400

    # 建议将 Token 放入环境变量，不要硬编码在代码中
    token = 'pat_9iOGYL7TROzEAbfjWPTDaqtkWipTrXVx6bZFi0b4CA9DjNmgrB2p9G7JdyVRGFm5'
    bot_id = '7594734352358047782'
    
    url = 'https://api.coze.cn/v3/chat'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    prompt = f"""
    你是一个专业的简历优化专家。
    请优化以下这段简历中的【{field_type}】内容。
    
    要求：
    1. 语言风格职业、干练、有吸引力。
    2. 突出核心优势和成果。
    3. 仅返回优化后的文本内容，不要包含任何前言后语，不要使用 Markdown 代码块。
    
    原始内容：
    {field_value}
    """
    
    payload = {
        "bot_id": bot_id,
        "user_id": f"user_{current_user.id}",
        "stream": True,
        "auto_save_history": False,
        "additional_messages": [
            {
                "role": "user",
                "content": prompt,
                "content_type": "text"
            }
        ]
    }
    
    try:
        # 1. 发起请求
        resp = requests.post(url, json=payload, headers=headers, timeout=60, stream=True)
        
        # 2. 【关键】检查状态码。如果不是 200，说明请求本身就失败了（如 Token 错误、参数错误）
        if resp.status_code != 200:
            error_msg = resp.text # 获取非流式的错误响应体
            print(f"API Error: Status {resp.status_code}, Body: {error_msg}")
            return jsonify({'success': False, 'error': f'API 请求失败: {resp.status_code}'})
        
        full_content = ""
        current_event = None # 用于记录当前行的事件类型

        # 3. 解析 SSE 流
        for line in resp.iter_lines():
            if line:
                decoded_line = line.decode('utf-8').strip()
                
                # 处理 event 行 (例如: event:conversation.message.delta)
                if decoded_line.startswith('event:'):
                    current_event = decoded_line[6:].strip()
                
                # 处理 data 行 (例如: data:{"content": "..."})
                elif decoded_line.startswith('data:'):
                    json_str = decoded_line[5:].strip()
                    try:
                        data_payload = json.loads(json_str)
                        
                        # 根据之前捕获的 event 类型处理数据
                        if current_event == 'conversation.message.delta':
                            # 在 delta 事件中，内容通常在 content 字段，类型在 type 字段
                            if data_payload.get('type') == 'answer':
                                content = data_payload.get('content', '')
                                full_content += content
                                # print(f"DEBUG: Chunk: {content}") # 调试用
                                
                        elif current_event == 'conversation.message.completed':
                            # 如果是 completed 事件，且之前没拼接到内容（防止丢包），尝试获取
                            if data_payload.get('type') == 'answer' and not full_content:
                                full_content = data_payload.get('content', '')

                    except Exception as e:
                        print(f"JSON Parse Error: {e}")
                        pass
        
        if not full_content:
             print("DEBUG: Full content is empty after parsing.")
             return jsonify({'success': False, 'error': 'AI 未返回有效内容'})

        # 4. 后处理：清洗 Markdown
        clean_text = re.sub(r'```.*?```', '', full_content, flags=re.DOTALL).strip()
        clean_text = clean_text.replace('`', '')
        
        return jsonify({'success': True, 'suggestion': clean_text})
                 
    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})