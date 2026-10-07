# 线上模拟面试语音识别 503 排查

目标站点：`http://211.154.20.65:20018`。

## 确认的原因

Web 和数据库健康检查正常。线上 Python 环境已安装 `sherpa-onnx`、
`numpy`、`pydub`，但系统没有 `ffmpeg`、`ffprobe`，且
`/root/projects/interview/.local/asr/sensevoice` 模型目录不存在。
浏览器录音解码和本地模型加载因此都无法完成；原接口将所有异常转换为 503。

此外，线上使用 Python 3.13.8，移除了 `audioop`，直接导入 `pydub` 会产生
`ModuleNotFoundError`。补充 `audioop-lts==0.2.2` 并仅在 Python 3.13 及以上
安装，恢复 `pydub` 的音频处理。

服务器使用 Nix Python，检查命令必须继承 Web 进程的 `LD_LIBRARY_PATH`；
否则单独启动的 Python 可能无法加载 `libstdc++.so.6`，与 Web 的运行环境不同。
同一路径若传给 Ubuntu 的 `ffmpeg`，会错误加载 Nix C++ 库并报缺少
`GLIBC_2.38`／`GLIBC_2.36`。解码改为显式启动 ffmpeg 并仅从子进程
环境移除 `LD_LIBRARY_PATH`，保留 Web 进程识别模型所需的库路径。

## 修复和验证

安装 Ubuntu `ffmpeg`，传输本机已通过准备脚本校验的模型，并逐一核对
模型、词表和示例音频的 SHA-256。部署自检脚本已增加 `--check`，
不下载模型，检查解码组件、加载模型并实际识别中文示例的 WebM 录音。

本地代码同时保留浏览器录音的实际 MIME 类型，区分损坏录音的 400 与
服务不可用的 503，并记录完整异常堆栈。浏览器上传格式、JSON／HTML 错误
恢复和后端回归测试共 56 项通过。

新增 Nix 子进程环境隔离测试后，相关测试共 57 项通过。

已在线上安装系统解码组件、Python 3.13 兼容依赖并准备模型；部署了
`local_asr.py` 的解码环境隔离修复、自检脚本及依赖清单，原文件保存在
服务器 `.local/asr-fix-backup/`。其他本地接口日志和前端改进保留在当前工作区。

线上 `--check` 已通过：WebM 解码和 SenseVoice 实际识别成功。
通过现有账号的短期签名会话测试公网 `/api/interview/transcribe`（不提交面试回答）：

| 录音格式 | 响应 | 用时 | 结果 |
| --- | --- | --- | --- |
| WebM / Opus | HTTP 200 | 3.36 秒 | success，返回非空中文识别文本 |
| MP4 / AAC | HTTP 200 | 0.53 秒 | success，返回非空中文识别文本 |

示例为模型自带的公开中文音频，验证用时不能代表所有设备、录音长度和负载。
