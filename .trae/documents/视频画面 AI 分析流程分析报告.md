# 视频画面 AI 分析流程报告

## 1. 处理流程 (Process Flow)
视频画面的发送与分析是一个**前端主动截帧、后端被动分析**的过程：

1.  **截取画面**: 前端 (`chat.html`) 从用户的摄像头视频流中截取一帧画面。
2.  **转换格式**: 将画面绘制到 Canvas 上并转换为 Base64 编码的 JPEG 图片。
3.  **发送请求**: 通过 HTTP POST 请求将图片发送给后端。
4.  **模型分析**: 后端 (`ai_agent.py`) 接收图片，调用视觉大模型 (VLM) 进行分析，生成 JSON 格式的评价标签。
5.  **返回结果**: 后端将评价标签返回给前端，前端实时更新界面上的“AI 视觉观察”卡片。

## 2. 发送频率 (Frequency)
目前有两种触发机制，频率如下：

*   **定时触发**: **每 8 秒一次**。
    *   代码位置: `app/templates/chat.html` 第 310 行 `setInterval(performVisualAnalysis, 8000);`。
    *   目的: 提供持续的实时视觉反馈（如“眼神飘忽”、“神情紧张”）。
*   **交互触发**: **每次发送消息时**。
    *   代码位置: `app/templates/chat.html` 第 485-494 行。
    *   目的: 让 AI 在回答问题时也能结合用户当时的表情状态。

## 3. 评价维度 (Evaluation Dimensions)
根据 `ai_agent.py` 中的 System Prompt 和 `chat.html` 的展示逻辑，主要评价以下三个维度：

1.  **眼神 (Eyes)**
    *   关注点: 视线接触、自信程度。
    *   标签示例: `眼神飘忽`、`直视镜头`、`眼神躲闪`。
2.  **表情 (Expression)**
    *   关注点: 情绪状态、微表情。
    *   标签示例: `神情紧张`、`面带微笑`、`表情自然`、`疑惑`。
3.  **体态 (Posture)**
    *   关注点: 坐姿、肢体语言。
    *   标签示例: `身体僵硬`、`坐姿端正`、`摇头晃脑`。

## 4. 关键代码位置
*   **前端频率控制**: [chat.html](file:///root/projects/interview/app/templates/chat.html#L310) (Line 310)
*   **后端分析逻辑**: [ai_agent.py](file:///root/projects/interview/app/services/ai_agent.py#L347) (Line 347 `analyze_image` 函数)
