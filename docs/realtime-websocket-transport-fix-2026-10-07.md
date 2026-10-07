# 实时语音 Invalid frame header 修复

浏览器报错位置是 WebSocket 构造函数所在行，故障发生在服务端传输与关闭流程。
在 Chromium 中模拟语音服务报错后关闭连接，修复前连续 5 次出现
`Invalid frame header`，关闭码均为 1006。

## 原因与修复

- Werkzeug 为请求保留 socket 的文件引用，WebSocket 库的 `close()` 不会立即
  使连接不可写。路由返回后追加的 HTTP 响应被浏览器当成 WebSocket 帧解析。
  现在先发协议关闭帧，再 shutdown 连接，阻止升级后追加 HTTP 响应。
- simple-websocket 1.1.0 的应用发送、心跳及协议响应都调用 socket `send()`，
  不处理短写，也不串行写入。新增传输适配器，对所有这些写入使用锁和
  `sendall()`，保证完整帧不会被心跳插入或截断。
- 已升级连接中的鉴权、初始化及运行异常通过 WebSocket 错误事件反馈，
  并执行相同的关闭流程，避免 HTTP 错误页写入。
- 前端失败时立即释放麦克风，不再向失败连接发送 `session.close` 并等待
  4 秒。用户正常停止仍等待最后一句话保存。旧连接关闭事件不会解除新连接
  的关闭等待，已取消启动的连接不会继续发送初始化事件。
- 前端脚本缓存版本更新为 `voice-transport-20261007-2`。

上游维护者也记录了 Werkzeug 关闭 WebSocket 时的兼容问题：
[flask-sock discussion #96](https://github.com/miguelgrinberg/flask-sock/discussions/96)。

## 验证

- 同一 Chromium 复现程序修复后连续 5 次正常关闭，码为 1000，没有帧错误。
- 43 项针对性回归测试通过：鉴权、管理员开关、音色传递、失败后重新连接、
  连续 PCM 上传、最终转写保存，以及真实 Chromium 连接关闭。
- 强制底层每次最多写 997 字节，同时将心跳周期压缩到 50 ms，真实浏览器
  仍完整收到至少 60 个音频分片，最后一句话保存成功，无帧错误。
- 实际语音 API 使用临时数据库和合成中文输入验证：持续上传 45 秒，
  跨过默认 20 秒心跳的两次发送，共上传 2249 个 PCM 分片，收到 36 个音频
  分片（687688 字节）、保存 2 段回答；关闭码 1000，WebSocket 和服务端错误
  均为零。整个验证未修改业务面试记录。

```bash
.venv/bin/python -m pytest -q \
  tests/test_websocket_transport.py tests/e2e/test_realtime_transport.py \
  tests/test_realtime_voice.py tests/test_realtime_voice_settings.py \
  tests/e2e/test_realtime_voice.py tests/e2e/test_realtime_voice_settings.py \
  tests/test_voice_options.py
```
