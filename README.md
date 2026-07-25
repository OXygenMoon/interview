# AI 模拟面试平台

本仓库采用单一的 Flask 应用、统一账号体系和 SQLite 数据库。简历创建、编辑、预览与面试引用均由 `app/api/resume.py` 和 Flask 模板提供；不再维护独立的 Node/Vue 简历服务。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py bootstrap-db
python run.py
```

默认地址为 `http://127.0.0.1:5001`。生产环境必须配置 `SECRET_KEY`、`LLM_API_KEY`，按需配置火山引擎 TTS 参数。

## 数据库迁移

数据库结构由 Flask-Migrate/Alembic 统一管理，应用启动不再调用
`db.create_all()` 或执行隐式 DDL。

```bash
# 新环境建库、已有 Alembic 数据库升级，以及旧 SQLite 数据库首次接管
flask --app run.py bootstrap-db

# 查看当前版本
flask --app run.py migration-status

# 开发模型变更后生成并检查迁移
flask --app run.py db migrate -m "describe change"
flask --app run.py db upgrade
flask --app run.py db check
```

`bootstrap-db` 对旧数据库会先补齐历史兼容列、验证所有模型表和列，再写入
Alembic 基线版本；不会删除业务数据。生产发布应先备份数据库、执行该命令，
确认 `/readyz` 返回 200 后再切换流量。`/healthz` 仅检查进程与数据库连接，
`/readyz` 还会检查迁移版本是否已到达 head。

## 验证

```bash
python -m compileall -q app tests
pytest -q
```

启动时会执行兼容性迁移、题库修复和存储保留策略。生成的 TTS 音频、转写文件和临时简历不会提交到 Git；保留时长可在管理员“系统设置”中调整。
