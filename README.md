# AI 模拟面试平台

本仓库采用单一的 Flask 应用、统一账号体系和 SQLite 数据库。简历创建、编辑、预览与面试引用均由 `app/api/resume.py` 和 Flask 模板提供；不再维护独立的 Node/Vue 简历服务。

面向学生、教师和管理员的完整操作说明见
[平台使用说明](docs/平台使用说明.md)。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium
cp .env.example .env
flask --app run.py bootstrap-db
python run.py
```

默认地址为 `http://127.0.0.1:5001`。生产环境必须配置 `SECRET_KEY`、`LLM_API_KEY`，按需配置火山引擎 TTS 参数。

面试对话、评分报告和视觉分析默认使用 DeepSeek-V4.1-Flash（API 模型名
`deepseek-flash`），服务地址为 `https://api.deepseek.com`。`LLM_API_KEY`
填写 DeepSeek 密钥；模型与地址可通过 `.env.example` 中的配置覆盖。面试
默认关闭思考模式（`LLM_THINKING=disabled`），以减少短回复延迟。
共享的简历和能力分析功能也使用此文本模型。语音识别改为在部署机器上
运行 SenseVoice，录音不发送给云端 ASR；转写文字进入 DeepSeek 面试对话。
语音播放继续使用豆包／火山引擎。
更新配置后重启 Web 与报告 Worker，使两者使用同一模型。

本地语音识别依赖系统 `ffmpeg`（macOS：`brew install ffmpeg`；Ubuntu：
`apt-get install ffmpeg`）。安装 Python 依赖后，在每台部署机器上执行一次：

```bash
python scripts/prepare_local_asr.py
```

脚本下载并校验约 158 MB 的模型包，模型保存在被 Git 忽略的
`.local/asr/sensevoice`。识别时无需联网或 API 密钥；每个 Web Worker
首次识别时加载一次模型。可通过 `ASR_MODEL_DIR`、`ASR_LANGUAGE` 和
`ASR_NUM_THREADS` 设置模型目录、语言及 CPU 线程数。

## 凭证安全

`.env` 只保存在部署主机，不得提交到 Git。若任何真实凭证曾进入 Git 历史，
仅删除当前文件并不能使其失效：应先在对应服务商控制台撤销并重新签发凭证，
再更新生产 `.env`。清理共享仓库历史需要在维护窗口协调所有协作者，使用
`git-filter-repo` 等工具改写历史、强制推送，并要求所有副本重新同步；不要在
正常发布流程中自动执行这类破坏性操作。

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
`/readyz` 还会检查迁移版本是否已到达 head。若旧数据中同一场面试错误关联了
多个下一轮，会保留全部会话、保留 ID 最小的下一轮关联，并将其余重复关联置空，
从而在不删除会话的前提下恢复唯一性约束。

## 验证

```bash
python -m compileall -q app tests
flake8 app tests run.py worker.py --select=E9,F63,F7,F82
pytest -q tests/test_regressions.py
pytest -q tests/e2e -m e2e
```

端到端测试会自动创建临时 SQLite 数据库、固定测试账号和随机本地端口，
并启动无头 Chromium。它不会读取或修改 `instance/app.db`。失败时截图和
可回放 trace 会保存在 `test-results/`；该目录不提交到 Git。

启动时不会执行隐式数据库结构变更；版本迁移必须通过 Alembic 命令完成。
题库修复和存储保留策略只会在数据库版本到达 head 后运行。生成的 TTS
音频、转写文件和临时简历不会提交到 Git；保留时长可在管理员“系统设置”
中调整。

## 前端主题与资源构建

正式页面共用“柔彩创意”主题：`app/static/css/playful.css` 定义视觉与响应式规则，
`tailwind.config.cjs` 定义 Tailwind/DaisyUI 的色板。导航统一在
`app/templates/_navbar.html`，直接挂载于 `body`，使用固定定位悬浮于顶部。

导航中的“主题”面板支持亮色与暗色；亮色可选奶油、鼠尾草、雾蓝、薰衣草和玫瑰。
选择保存在当前浏览器，并同步到同源标签页；暗色切回亮色时恢复上次的色调。
没有保存偏好时跟随系统外观。旧版亮暗模式的保存值仍然兼容。
`scripts/theme-palettes.cjs` 统一定义新增亮色色板，构建时生成
`light-themes.css` 与 `theme-utilities.css`，并同步 DaisyUI 组件颜色。

修改模板中的 utility 类或升级前端依赖后，重新构建并提交生成文件：

```bash
npm ci
npm run build:assets
```

构建会生成 `app/static/css/ui.css` 与 `app/static/vendor/` 中的图表、Markdown
资源。应用运行时直接提供这些本地文件，无需 Node.js 或浏览器端 Tailwind CDN。
简历打印使用浏览器原生打印，界面导航和页脚不进入打印内容。

全站主题、悬浮导航、手机菜单、管理弹窗和简历预览回归：

```bash
pytest -q tests/e2e/test_playful_ui.py tests/e2e/test_theme_switcher.py
```

## Interview / WikiBook 账号关联

两站可通过账号设置建立一对一关联，并从导航一键切换登录。配置、接口、迁移和测试说明见 [账号关联说明](docs/account-linking.md)。未配置共享密钥与两站地址时，功能保持关闭。
