from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from .. import db
from ..models import Company, Position, InterviewSession, CompanyAccount

company_bp = Blueprint('company_api', __name__)

# === 公开接口 ===

@company_bp.route('/list', methods=['GET'])
def get_company_list():
    """获取所有公司及旗下岗位（用于前端选择）"""
    companies = Company.query.order_by(Company.created_at.desc()).all()
    result = []
    for comp in companies:
        positions = []
        for pos in comp.positions:
            positions.append({
                'id': pos.id,
                'name': pos.name,
                'description': pos.description
            })
        result.append({
            'id': comp.id,
            'name': comp.name,
            'description': comp.description,
            'positions': positions
        })
    return jsonify(result)

@company_bp.route('/position/<int:position_id>', methods=['GET'])
def get_position_detail(position_id):
    """获取单个岗位详情"""
    pos = Position.query.get_or_404(position_id)
    return jsonify({
        'id': pos.id,
        'name': pos.name,
        'description': pos.description,
        'company_name': pos.company.name,
        'company_description': pos.company.description
    })

# === 管理员接口 (需要权限控制) ===

def check_admin():
    if not current_user.is_authenticated:
        return False
    if not getattr(current_user, 'is_admin', False):
        return False
    return True

@company_bp.route('/create', methods=['POST'])
@login_required
def create_company():
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    description = data.get('description', '')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
        
    company = Company(name=name, description=description)
    db.session.add(company)
    db.session.commit()
    
    return jsonify({'message': 'Company created', 'id': company.id})

@company_bp.route('/<int:company_id>', methods=['PUT'])
@login_required
def update_company(company_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    company = Company.query.get_or_404(company_id)
    data = request.get_json(silent=True) or {}
    
    company.name = data.get('name', company.name)
    company.description = data.get('description', company.description)
    db.session.commit()
    
    return jsonify({'message': 'Company updated'})

@company_bp.route('/<int:company_id>', methods=['DELETE'])
@login_required
def delete_company(company_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    company = Company.query.get_or_404(company_id)
    if CompanyAccount.query.filter_by(company_id=company.id).first() or (
        InterviewSession.query.join(Position).filter(Position.company_id == company.id).first()
    ):
        return jsonify({'error': '公司已有账号或面试记录，不能删除。请先停用公司账号。'}), 409
    db.session.delete(company)
    db.session.commit()
    
    return jsonify({'message': 'Company deleted'})

# --- 岗位管理 ---

def can_manage_positions(company_id):
    return check_admin() or (
        current_user.is_authenticated and current_user.role == 'company'
        and current_user.company_account is not None
        and current_user.company_account.company_id == company_id
    )


def position_input(data, position=None):
    if not isinstance(data, dict):
        raise ValueError('岗位数据必须是对象。')
    name = data.get('name', position.name if position else '')
    description = data.get('description', position.description if position else '') or ''
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('岗位名称不能为空，且最多 100 个字符。')
    if not isinstance(description, str) or len(description) > 20000:
        raise ValueError('岗位要求最多 20000 个字符。')
    return name.strip(), description.strip()


@company_bp.route('/<int:company_id>/position', methods=['POST'])
@login_required
def create_position(company_id):
    if not can_manage_positions(company_id):
        return jsonify({'error': 'Unauthorized'}), 403
    company = Company.query.get_or_404(company_id)
    try:
        name, description = position_input(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify(error=str(error)), 400
    position = Position(company_id=company.id, name=name, description=description)
    db.session.add(position)
    db.session.commit()
    return jsonify({'message': 'Position created', 'id': position.id})


@company_bp.route('/position/<int:position_id>', methods=['PUT'])
@login_required
def update_position(position_id):
    position = Position.query.get_or_404(position_id)
    if not can_manage_positions(position.company_id):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        position.name, position.description = position_input(request.get_json(silent=True) or {}, position)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    db.session.commit()
    return jsonify({'message': 'Position updated'})

@company_bp.route('/position/<int:position_id>', methods=['DELETE'])
@login_required
def delete_position(position_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    position = Position.query.get_or_404(position_id)
    if InterviewSession.query.filter_by(position_id=position.id).first():
        return jsonify({'error': '岗位已有面试记录，不能删除。'}), 409
    db.session.delete(position)
    db.session.commit()
    
    return jsonify({'message': 'Position deleted'})
