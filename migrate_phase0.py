"""
Phase 0 一次性迁移：
1. 给 interview_sessions 表增加 last_activity / reviewed / abandoned 列
2. 向 system_configs 表写入冷却系统默认配置

用法：在项目根目录执行  .venv/bin/python migrate_phase0.py
SQLite 支持 ALTER TABLE ADD COLUMN，安全且保留现有数据。
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'app.db')


def add_column(cur, table, col, decl):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        print(f"  + {table}.{col} {decl}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  = {table}.{col} 已存在，跳过")
        else:
            raise


def seed_config(cur, key, value, description):
    cur.execute("SELECT id FROM system_configs WHERE key = ?", (key,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO system_configs (key, value, description) VALUES (?, ?, ?)",
            (key, value, description),
        )
        print(f"  + system_configs.{key} = {value}")
    else:
        print(f"  = system_configs.{key} 已存在，跳过")


def main():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在：{DB_PATH}，跳过（首次启动 db.create_all 会自动建表）")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("[1/2] 扩展 interview_sessions 表...")
    add_column(cur, "interview_sessions", "last_activity", "DATETIME")
    add_column(cur, "interview_sessions", "reviewed", "BOOLEAN DEFAULT 0")
    add_column(cur, "interview_sessions", "abandoned", "BOOLEAN DEFAULT 0")

    # 旧数据回填 last_activity = start_time，避免立即被判过期
    cur.execute("UPDATE interview_sessions SET last_activity = start_time WHERE last_activity IS NULL")
    print(f"  ~ 回填 last_activity = start_time，影响 {cur.rowcount} 行")

    print("[2/2] 写入冷却系统默认配置...")
    seed_config(cur, "session_ttl_minutes", "10", "ongoing 面试无活动多久后判为 expired（分钟）")
    seed_config(cur, "cooldown_abandon_minutes", "10", "中途放弃后再次开始面试的冷却罚时（分钟）")
    seed_config(cur, "cooldown_complete_minutes", "30", "完成一次面试后再次开始的冷却时长（分钟）")
    seed_config(cur, "cooldown_requires_review", "true", "完成后是否强制复盘上次报告才能开始下一次")

    conn.commit()
    conn.close()
    print("迁移完成。")


if __name__ == "__main__":
    main()
