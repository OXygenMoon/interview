# 实时语音的 3 秒静音等待

实时语音按麦克风 PCM 的声音活动计时，连续安静满 3 秒才向页面发送面试官的文字和音频。继续说话重新计时；麦克风和 20 ms 音频上传持续运行。初次欢迎语和文字模式的 TTS 不经过此等待逻辑。

当前使用的全双工模型 `1.2.6.1` 会在短暂停顿时提前生成回复。2026-10-07 使用真实服务测试 `extension.asr.extra.enable_custom_vad=true` 和 `end_smooth_window_ms=3000` 后，仍在音频结束约 1.2 秒时收到 ASR 完成及回复，因此不能仅依赖该旧参数实现产品要求。

`app/services/realtime_turns.py` 在服务端暂存提前生成的回复事件，满 3 秒后按原顺序释放，文字、音频与数据库保存采用同一条路径。候选人继续说话时取消未播出的回复，丢弃其迟到事件，避免把未听到的追问写入本地历史。模型可能将候选人分段识别为多条记录；这里控制回复的实际显示与播报时机，不改写模型的语音转写结果。

低音量回答由 ASR 开始和文字进度辅助检测；重复识别快照不延长等待，正常音量的识别延迟不叠加到麦克风计时上。单个 20 ms 瞬时声音不重置计时。上传中断不被当作静音，明确点击静音后仍能释放待播回复。停止通话或点击打断会丢弃尚未播出的回复。

验证：

- 单元测试覆盖 3 秒边界、继续说话重新计时、取消后的迟到事件、上传停滞与显式静音、低音量 ASR 和延迟识别文本。
- 真实 Chromium → Flask WebSocket → 模拟上游测试：停顿 2 秒后继续作答，只显示和保存第二次追问，文字与音频均在最后有声帧约 3 秒后送达。
- 真实 Chromium → Flask → 豆包服务：连续上传约 26 秒，两段合成测试语音；首段未播追问被取消，最终回复首个音频包在最后有声帧后 **3003 ms** 到达浏览器。无服务错误、无 WebSocket 帧错误，连接正常关闭（1000）。测试使用临时数据库，没有写入真实面试记录。
- 实时语音、输入模式切换、管理员开关与文字 TTS 的相关回归测试通过。

刷新页面并重新建立实时语音连接后使用新逻辑。网络与模型生成可能带来额外延迟；3 秒是最早放行时机。

协议参考：[全双工接口](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=zh)、[接入必读](https://docs.volcengine.com/docs/DoubaoVoice/access-mustread?lang=zh)、[旧版自定义判停参数](https://docs.volcengine.com/docs/DoubaoVoice/End-to-endreal-timespeechlargemodelAPIaccessdocument?lang=zh)。
