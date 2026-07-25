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

## 独立报告队列

面试报告通过 Redis/RQ 持久队列生成。生产环境必须使用 `rq` 模式，并分别
启动 Web 和 Worker；Redis 或 Worker 不可用时 `/readyz` 会返回 503，Web
不会静默退回可能随进程重启而丢失的线程。

```bash
# 终端一：独立 Worker（内置延迟重试调度）
REPORT_QUEUE_MODE=rq python worker.py

# 终端二：Web
REPORT_QUEUE_MODE=rq python run.py

# 查看积压和 Worker 状态，并执行真实任务探针
flask --app run.py queue-status
flask --app run.py queue-probe

# 校准异常退出后遗留的 processing 状态
flask --app run.py reconcile-report-jobs
```

开发环境默认 `REPORT_QUEUE_MODE=auto`：有 Worker 时使用持久队列，没有时
明确回退本地线程。也可设置为 `thread` 做纯本地调试。任务 ID、提交次数、
实际执行次数、入队/开始/完成时间和队列状态都会写入面试记录；失败任务按
`REPORT_RETRY_INTERVALS` 自动重试，耗尽后才标记为失败。

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

启动时不会执行隐式数据库结构变更；版本迁移必须通过 Alembic 命令完成。
题库修复和存储保留策略只会在数据库版本到达 head 后运行。生成的 TTS
音频、转写文件和临时简历不会提交到 Git；保留时长可在管理员“系统设置”
中调整。
