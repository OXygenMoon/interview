# AI 模拟面试平台

本仓库采用单一的 Flask 应用、统一账号体系和 SQLite 数据库。简历创建、编辑、预览与面试引用均由 `app/api/resume.py` 和 Flask 模板提供；不再维护独立的 Node/Vue 简历服务。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

默认地址为 `http://127.0.0.1:5001`。生产环境必须配置 `SECRET_KEY`、`LLM_API_KEY`，按需配置火山引擎 TTS 参数。

## 验证

```bash
python -m compileall -q app tests
pytest -q
```

启动时会执行兼容性迁移、题库修复和存储保留策略。生成的 TTS 音频、转写文件和临时简历不会提交到 Git；保留时长可在管理员“系统设置”中调整。
