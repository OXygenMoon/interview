from functools import wraps
from flask import abort
from flask_login import current_user

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 允许 老师、系主任、校领导 访问
        if not current_user.is_teacher:
            abort(403) # 403 禁止访问
        return f(*args, **kwargs)
    return decorated_function

def dept_head_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 允许 系主任、校领导 访问
        if not current_user.is_dept_head:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 仅允许 校领导 访问
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function