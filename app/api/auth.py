from . import api_bp

@api_bp.route('/login', methods=['POST'])
def login():
    return {'message': 'Login placeholder'}
