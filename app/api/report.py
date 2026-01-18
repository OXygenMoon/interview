from . import api_bp

@api_bp.route('/history', methods=['GET'])
def get_history():
    return {'message': 'History placeholder'}
