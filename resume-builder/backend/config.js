/**
 * ============================================
 *  配置文件 - 所有密钥/Token 集中管理
 * ============================================
 *
 * 引用外部 .env 文件的方式（任选其一）：
 *
 *   方式一（推荐）：安装 dotenv，在 server.js 最顶部加一行：
 *       require('dotenv').config({ path: require('path').join(__dirname, '.env') });
 *       然后在项目根目录创建 .env 文件：
 *           JWT_SECRET=your-secret-here
 *           COZE_API_TOKEN=pat_xxxx
 *           COZE_BOT_ID=75947xxxx
 *
 *   方式二：启动时通过环境变量注入（Docker / systemd）：
 *       JWT_SECRET=xxx COZE_API_TOKEN=xxx node server.js
 *
 *   方式三：直接修改下方 fallback 值（仅开发环境，切勿提交到 Git）
 */

module.exports = {
  // JWT 签名密钥（生产环境务必通过环境变量设置）
  JWT_SECRET: process.env.JWT_SECRET || 'resume-builder-secret-key-change-in-production',

  // Coze AI 配置
  COZE_API_TOKEN: process.env.COZE_API_TOKEN || 'pat_9iOGYL7TROzEAbfjWPTDaqtkWipTrXVx6bZFi0b4CA9DjNmgrB2p9G7JdyVRGFm5',
  COZE_BOT_ID: process.env.COZE_BOT_ID || '7594734352358047782',

  // 服务端口
  PORT: process.env.PORT || 3001,
};
