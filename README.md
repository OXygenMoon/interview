# AI 模拟面试平台

本仓库采用单一的 Flask 应用、统一账号体系和 SQLite 数据库。简历创建、编辑、预览与面试引用均由 `app/api/resume.py` 和 Flask 模板提供；不再维护独立的 Node/Vue 简历服务。

面向学生、教师和管理员的完整操作说明见
[平台使用说明](docs/平台使用说明.md)。

## 本地运行

服务器的 32 人并发生产部署、验证结果和服务管理命令见
[部署记录](docs/deployment-32-users.md)。

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
共享的简历和能力分析功能也使用此文本模型。模拟面试的「开始实时对话」
使用豆包 3.0 全双工语音模型，持续上传麦克风音频并流式返回文字和语音，
支持开口打断、手动打断和静音；文字回答与评分报告仍使用 DeepSeek。
单题练习和录音转写接口保留部署机器上的 SenseVoice。
更新配置后重启 Web 与报告 Worker，使两者使用同一模型。

## 公司工作台与校企合作

管理员在「教学管理 → 校企合作管理」（`/admin/partnerships`）选择已有公司
或新建合作公司，填写联系人、登录账号与至少 10 位的初始密码即可开户。
支持同一公司多个联系人账号、更新联系人、停用/启用及重置密码；公司账号
首次登录与密码重置后必须修改密码。公司资料仍在「企业与岗位管理」维护。

公司通过统一登录页进入 `/company`，可查看、新增、编辑本公司的岗位，
按岗位筛选学生面试记录。公司与学生、管理员共用面试报告及只读对话页面，
包含能力雷达图、逐句点评、参考回答和画面仪态复盘；面试记录表格与管理员共用。
递交简历共用管理员的 A4 预览、模板切换、一页纸排版及打印 / PDF。
学生结束该公司的岗位面试后，记录自动汇入，生成中的报告也会显示状态。
简历显示面试时的内容，不读取学生后续修改的简历或未递交的其他简历；
新面试保存可见简历内容、模板及排版密度，并继承到下一轮；隐藏模块不递交。
旧面试和文件上传只保留解析文本的记录，在同一 A4 预览中展示原有文本，
不会用学生后来修改的简历补充历史内容。未递交简历与缺少历史快照的情况会显示为空。

岗位的「一键推荐学生」采用可解释的评分：岗位专业技能 60% + 面试综合分
40%，参考分至少 75、专业技能至少 60。只比较学生在该岗位的最近一次已完成
面试，每人展示一次；不使用规则兜底评分、缺失评分、已删除记录或停用学生。
推荐页面提供评分依据、面试证据与递交简历入口。

更新后运行 `flask --app run.py bootstrap-db`，将数据库升级到
`20261008_resume_document`，然后重启 Web 与 Worker。迁移新增公司账号关联表及递交简历排版快照，
保留现有公司、岗位和面试数据。已有公司账号或面试记录的公司，以及已有面试
记录的岗位，不允许删除，以保留历史记录归属。

## 实时语音配置

在服务端 `.env` 设置 `VOLC_API_KEY`（豆包语音控制台「API Key 管理」中的密钥），
并确保该 Key 已开通实时语音服务。鉴权请求头的
`X-Api-Key` 使用此密钥；密钥不会下发给浏览器。接口为
`wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`，
模型版本为 `1.2.6.1`，按官方 3.0 JSON 事件协议接入。
默认男声为云舟，原 VV／晓甜选择映射为实时模型支持的 VV／小何音色。
前台「选择面试官音色」另提供云舟、小天、小何、知性灿灿、儒雅逸辰
五款 2.0 音色，选择后用于本场面试的实时对话和文字模式语音播报。
音色 ID 依据[火山引擎官方音色列表](https://docs.volcengine.com/docs/DoubaoVoice/Tonelist-1?lang=zh)。
如需覆盖默认男声，在 `.env` 设置 `VOLC_REALTIME_VOICE`。

安装更新后的 `requirements.txt` 并重启 Web。正式使用时浏览器需通过 HTTPS 或
localhost 访问才能授权麦克风。使用 Nginx 时需部署更新后的
`interview_nginx` 中的 WebSocket Upgrade／Connection 转发配置；现有
Gunicorn `gthread` 配置支持此连接，每个实时会话占用一个服务线程。

HTTP 访问时，正式面试和随机问题面试会显示麦克风、摄像头设置说明，
可一键复制当前站点地址（协议、主机、端口）和浏览器设置地址。
桌面 Chrome / Edge 可以手动添加本站测试例外，Android Chrome 视版本
可尝试相同的 flags 选项；iPhone / iPad 和应用内浏览器优先使用可信 HTTPS。
网页不能直接写入浏览器策略，例外不加密 HTTP，设置后仍需授权设备权限。
平台按实际 `window.isSecureContext` 判断，已添加并生效的例外不会被误拦截。
Chrome 策略参考 [OverrideSecurityRestrictionsOnInsecureOrigin](https://chromeenterprise.google/policies/override-security-restrictions-on-insecure-origin/)，
测试设置参考 [Chromium 官方说明](https://www.chromium.org/Home/chromium-security/deprecating-powerful-features-on-insecure-origins/)。

音频按 20 ms 分包，输入单声道 16 kHz PCM16，输出 24 kHz PCM16。
用户与面试官文字记录由服务端保存，支持刷新后续接、评分和复盘。
摄像头观察单独请求，不阻塞语音流；面试官语音仍按现有 30 天策略留存。
管理员可在「系统设置 → AI 面试官配置」单独开关「实时语音交互」，默认开启。
保存后立即控制新连接，已有实时会话会在约 2 秒内停止并保存最后一句回答。
「文字对话语音播报 (TTS)」独立控制文字模式的语音输出。
面试页面的文字输入和实时语音控件互斥显示。切回文字会停止麦克风，
文字回复自动语音播放，点击回复可重播；开启实时通话会停止文字播报。
实时通话中，连续安静满 3 秒才显示和播放面试官回复；继续说话会重新计时。
麦克风持续上传，短暂停顿不关闭连接。全双工模型可能提前生成回复，服务端
暂存这些文字与音频，候选人继续说话时取消暂存回复，避免播报和保存未听到的追问。
如果环境音导致一直无法判停，可点击实时语音控件中的「我说完了」立即结束
本次回答，跳过 3 秒静音等待。接话期间暂停麦克风上传，播报结束后自动恢复；
也可点击「打断面试官」提前恢复回答，通话连接和麦克风设备保持打开。
新 Key 默认通过已开通的实时语音服务强制朗读文字，不访问麦克风，
并沿用本场面试选择的音色，无需额外开通独立 TTS 资源。
如已开通独立 TTS v3，可设置 `VOLC_TTS_RESOURCE_ID` 为对应的
`seed-tts-1.0`／`seed-tts-2.0` 资源。未配置新 Key 时保留旧 TTS 凭证兼容。

协议依据：[实时语音 3.0](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=zh)、
[接入必读](https://docs.volcengine.com/docs/DoubaoVoice/access-mustread?lang=zh)。

本地语音识别依赖系统 `ffmpeg`（macOS：`brew install ffmpeg`；Ubuntu：
`apt-get install ffmpeg`）。安装 Python 依赖后，在每台部署机器上执行一次：

```bash
python scripts/prepare_local_asr.py
python scripts/prepare_local_asr.py --check
```

脚本下载并校验约 158 MB 的模型包，模型保存在被 Git 忽略的
`.local/asr/sensevoice`。识别时无需联网或 API 密钥；每个 Web Worker
首次识别时加载一次模型。可通过 `ASR_MODEL_DIR`、`ASR_LANGUAGE` 和
`ASR_NUM_THREADS` 设置模型目录、语言及 CPU 线程数。
Python 3.13 及以上会按依赖清单安装 `audioop-lts`，补齐 `pydub` 所需的
音频处理模块；请使用完整的 `requirements.txt` 安装依赖。

若面试转写返回 503，在服务器上使用 Web 服务相同的 Python 虚拟环境、用户
和 `PATH` 运行上述 `--check` 命令。它不下载模型，会检查 `ffmpeg`／`ffprobe`、
识别依赖及模型加载，并用模型自带的中文示例验证 WebM 解码和实际转写。
缺少模型时先执行准备命令；缺少依赖时安装 `requirements.txt` 和系统 `ffmpeg`，
然后重启 Web 服务。后端日志会保留完整异常堆栈；损坏的录音返回 400，
不再被误报为语音服务 503。

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

### 共享测试账号

```bash
flask --app run.py bootstrap-db
flask --app run.py seed-test-accounts
```

`seed-test-accounts` 可重复运行，在「测试组 / 测试班」中创建 10 个学生账号
`interview_test01` 至 `interview_test10`。访问 `/test-accounts` 或点击登录页的
「使用测试账号体验」即可查看占用状态并一键登录，无需共享密码。
页面每 5 秒刷新状态；数据库原子占用保证每个账号同一时间只有一个浏览器登录，
密码登录和跨站切换也遵循此限制。同一浏览器中的多个标签页共用登录。
平台页面每 30 秒续期，退出立即释放，关闭全部页面或断网约 3 分钟后释放；
租约过期后旧登录失效，必须重新选择账号。

这些账号完成或放弃面试后均等待 5 分钟，不要求先查看上次报告；进行中的面试
仍需续接或结束。普通学生继续使用管理员设置的间隔和复盘要求。测试账号中的
资料、简历和练习记录由使用者共享，并可在班级管理和能力画像中按「测试班」查看。
管理员可以停用测试账号；重复初始化不会重新启用账号、修改密码或清除记录。

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
`app/templates/_navbar.html`，直接挂载于 `body`，固定在页面顶部。

全站排版与控件细化规则位于 `app/static/css/refinement.css`，新增设计变量的
源文件为根目录 `tokens.css`；CSS 构建自动生成 `app/static/css/tokens.css`。
登录图片使用本地 WebP。设计决定、修改项与验证记录见
[前端优化记录](docs/frontend-refinement-2026-10-07.md)。

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
