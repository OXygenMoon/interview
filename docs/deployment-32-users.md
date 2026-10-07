# 32 人并发部署记录

部署日期：2026-10-07（Asia/Shanghai）。访问入口：http://211.154.20.65:20018。
服务器项目目录为 `/root/projects/interview`，服务器资源为 8 核、约 8 GB 内存。
本次部署保留服务器现有业务版本，没有发布本地尚未提交的业务代码。

## 运行配置

- Nginx `20018` → Gunicorn `127.0.0.1:5001`。
- Gunicorn：4 个 `gthread` 工作进程，每进程 16 个请求处理线程，共 64 个请求处理线程。
- 关闭 Flask 调试、热重载和按请求数量重启 Worker，保留长连接处理余量。
- Nginx 支持 WebSocket Upgrade 和 SSE；关闭响应缓冲，空闲读取超时 300 秒。
- `/static/` 通过应用转发，避免 Nginx 的 `www-data` 无法访问 `/root` 下文件。
- SQLite 启用 WAL，单连接写锁等待 20 秒；每个 Web 进程数据库连接池上限 16。
- 本地识别每个进程使用 1 个模型计算线程；4 个进程可独立执行识别，进程内仍串行。
- Redis/RQ 使用 2 个独立报告 Worker。32 份报告可以入队，但不会同时执行 32 份报告。
- Web 和两个报告 Worker 均由 systemd 管理，已开启开机启动、失败自动重启。
- 生成持久会话密钥并写入服务器 `.env`，文件权限 600；没有将密钥带回本地。

配置文件在 `deploy/` 中。服务器现有 Web 服务的 Nix 库目录 drop-in 保留；
Nix 的 `LD_LIBRARY_PATH` 只用于项目 Python，不能带入系统 Nginx 的配置检查。

## 验证结果

32 个临时学生账号，经本机 Nginx 入口同时请求真实业务接口；测试结束后
账号、面试和聊天记录均已清理。原始结果见 `deployment-32-users-results.json`。

| 测试 | 成功 / 总数 | P95 | 最慢 |
| --- | --- | --- | --- |
| 登录（含读取 CSRF 和密码验证） | 32 / 32 | 1.046 秒 | 1.075 秒 |
| 登录后首页，32 用户各访问 10 次 | 320 / 320 | 0.226 秒 | 0.409 秒 |
| 首次模型加载时录音转写 | 32 / 32 | 7.230 秒 | 7.778 秒 |
| 模型已加载时录音转写 | 32 / 32 | 6.244 秒 | 7.506 秒 |
| 真实模型 SSE 文字对话 | 32 / 32 | 2.351 秒 | 2.473 秒 |

录音样本为模型自带 5.59 秒中文音频。文字对话要求一个简短问题，最慢首字
2.013 秒。长录音、更长回答、视频分析、网络质量和模型服务限额会改变延迟；
这些结果是一次 32 人批次验证，不是持续长时间负载或任意内容的容量保证。

公网 `/login`、`/healthz`、CSS 请求均返回 200；`/readyz` 验证数据库迁移
与报告队列就绪，队列实际探针任务成功完成。Web 未发生自动重启。
语音模型加载后，Web 服务约占 2.25 GB 内存，服务器仍约有 2 GB 可用内存。

## 尚未验证通过的功能

- 火山语音播报实际调用返回 `3001 / requested resource not granted`，32 个
  文字对话均无播报音频。需要在火山平台开通匹配资源或更新服务凭证；修改
  启动进程数量无法解决此权限错误。
- 服务器业务版本没有本地新版本的实时语音 WebSocket 接口。本次 Nginx 与
  Gunicorn 为其保留支持，但未声称验证了 32 人实时语音。
- 当前入口是 HTTP；普通浏览器的麦克风、摄像头授权需要 HTTPS 或 localhost。
  录音转写压力测试直接向服务器上传样本，不能代替浏览器录音流程验证。
- 磁盘约 97% 已使用，部署结束时剩余约 2.3 GB。未清理其他项目的数据。

## 日常管理

```bash
systemctl status interview interview-report@1 interview-report@2
systemctl restart interview
systemctl restart interview-report@1 interview-report@2
journalctl -u interview -f
journalctl -u interview-report@1 -u interview-report@2 -f
curl -fsS http://127.0.0.1:20018/readyz
```

`./run.sh` 在 Linux 默认启动生产 Web；systemd 已占用 5001 时不要再手动
启动一份。macOS 仍使用开发服务器。Linux 开发调试可以显式设置
`APP_RUN_MODE=development`。

如果需要重跑业务压力测试，使用 `scripts/check-deployment-concurrency.py`。
`--chat` 会产生真实模型和语音服务调用；脚本创建临时数据并在正常退出时清理。

## 备份与回退

原 Nginx、systemd、环境文件、启动脚本和部署前 SQLite 快照位于服务器
`/root/interview-deployment-backups/20261007-production-32/`，目录权限 700。
回退启动配置时先停止本项目服务，再恢复该目录中的 Nginx、systemd 和 `run.sh`，
执行 `systemctl daemon-reload`，检查 `nginx -t` 后重新加载 Nginx 并启动 Web。
数据库快照仅用于数据恢复；不要用旧快照覆盖部署后新增的业务数据。
