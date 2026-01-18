# app/api/__init__.py
from flask import Blueprint

# 定义一个空的通用 API 蓝图（暂时用不到，但也留着防止报错）
api_bp = Blueprint('api', __name__)

# 注意：这里不要再 import interview 了，我们在主程序里直接 import 它