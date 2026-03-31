from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from .. import db
from ..models import Company, Position

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
    if not current_user.is_authenticated or not current_user.is_admin:
        return False
    return True

@company_bp.route('/create', methods=['POST'])
@login_required
def create_company():
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
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
    data = request.json
    
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
    db.session.delete(company)
    db.session.commit()
    
    return jsonify({'message': 'Company deleted'})

# --- 岗位管理 ---

@company_bp.route('/<int:company_id>/position', methods=['POST'])
@login_required
def create_position(company_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    company = Company.query.get_or_404(company_id)
    data = request.json
    name = data.get('name')
    description = data.get('description', '')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
        
    position = Position(company_id=company.id, name=name, description=description)
    db.session.add(position)
    db.session.commit()
    
    return jsonify({'message': 'Position created', 'id': position.id})

@company_bp.route('/position/<int:position_id>', methods=['PUT'])
@login_required
def update_position(position_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    position = Position.query.get_or_404(position_id)
    data = request.json
    
    position.name = data.get('name', position.name)
    position.description = data.get('description', position.description)
    db.session.commit()
    
    return jsonify({'message': 'Position updated'})

@company_bp.route('/position/<int:position_id>', methods=['DELETE'])
@login_required
def delete_position(position_id):
    if not check_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    position = Position.query.get_or_404(position_id)
    db.session.delete(position)
    db.session.commit()
    
    return jsonify({'message': 'Position deleted'})
