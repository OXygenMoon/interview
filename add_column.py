from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        # 尝试添加列
        with db.engine.connect() as conn:
            # SQLite 的 BOOLEAN 其实是 INTEGER (0/1)
            conn.execute(text("ALTER TABLE interview_sessions ADD COLUMN use_resume BOOLEAN DEFAULT 0"))
            conn.commit()
        print("✅ Column 'use_resume' added successfully.")
    except Exception as e:
        print(f"⚠️ Error: {e}")
