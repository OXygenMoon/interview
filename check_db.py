from app import create_app, db
# 必须导入新定义的模型，这样 SQLAlchemy 才能识别到它们
from app.models import LearningCategory, LearningMaterial, UserLearningProgress

app = create_app()

with app.app_context():
    print("🔄 正在检查数据库结构...")
    # create_all 只会创建不存在的表，不会影响已有数据
    db.create_all()
    print("✅ 数据库更新完成！")
    print("   - 新增表: learning_categories")
    print("   - 新增表: learning_materials")
    print("   - 新增表: user_learning_progress")