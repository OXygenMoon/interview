const express = require('express');
const router = express.Router();
const { CozeAPI } = require('@coze/api');

// 初始化 Coze 客户端 (使用您提供的 Token)
// 注意：实际生产中 Token 应放在环境变量中，这里按要求直接写入
const apiClient = new CozeAPI({
  token: 'pat_9iOGYL7TROzEAbfjWPTDaqtkWipTrXVx6bZFi0b4CA9DjNmgrB2p9G7JdyVRGFm5',
  baseURL: 'https://api.coze.cn'
});

const BOT_ID = '7594734352358047782';

/**
 * POST /api/ai/optimize
 * 接收简历数据，调用 AI 进行优化
 */
router.post('/optimize', async (req, res) => {
  const { formData } = req.body;

  if (!formData) {
    return res.status(400).json({ error: '缺少简历数据' });
  }

  // 构建 Prompt：强制要求返回 JSON，以便前端映射
  const prompt = `
    你是一个专业的简历优化专家。请优化以下简历数据，使其表达更专业、更有吸引力，重点优化工作描述和自我评价。
    
    【重要要求】：
    1. 保持数据的原始结构不变。
    2. 必须且只能返回标准的 JSON 格式字符串，不要包含 Markdown 标记（如 \`\`\`json）。
    3. JSON 的 key 必须与输入数据完全一致。
    4. 优化后的内容语言风格要职业、干练。

    以下是原始简历数据：
    ${JSON.stringify(formData)}
  `;

  try {
    // 设置响应头，支持流式输出 (Server-Sent Events 简化版，或者直接等待完整响应)
    // 为了简化前端解析逻辑，保证表单映射准确，我们这里采用“等待完整响应”策略
    // 因为前端需要解析 JSON，如果流式返回 JSON 片段很难实时解析显示
    
    const stream = await apiClient.chat.stream({
      bot_id: BOT_ID,
      user_id: 'user_' + Date.now(), // 简单的临时 ID
      additional_messages: [
        {
          role: 'user',
          content: prompt,
          content_type: 'text',
          type: 'question'
        }
      ],
      auto_save_history: false,
    });

    let fullResponse = '';

    for await (const part of stream) {
      if (part.event === 'conversation.message.completed') {
        const message = part.data;
        if (message.type === 'answer') {
          fullResponse = message.content;
        }
      }
    }

    // 尝试清洗数据，防止 AI 返回 Markdown 代码块
    let cleanJson = fullResponse.replace(/```json/g, '').replace(/```/g, '').trim();
    
    // 尝试解析 JSON 验证有效性
    try {
      const optimizedData = JSON.parse(cleanJson);
      res.json({ success: true, data: optimizedData });
    } catch (e) {
      console.error('AI 返回的数据不是有效的 JSON:', cleanJson);
      // 如果解析失败，返回原始文本，前端做容错
      res.json({ success: false, raw: fullResponse, error: 'AI 解析失败' });
    }

  } catch (error) {
    console.error('Coze API 调用失败:', error);
    res.status(500).json({ error: 'AI 服务暂时不可用' });
  }
});

module.exports = router;