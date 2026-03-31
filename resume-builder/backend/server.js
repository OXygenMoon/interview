const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs').promises;
const helmet = require('helmet');
// rateLimit 暂时移除或调大限制，避免上传大文件时被误杀
// const rateLimit = require('express-rate-limit'); 

const app = express();
const PORT = process.env.PORT || 3001;

// 定义目录路径
const dataDir = path.join(__dirname, 'data');
const templatesDir = path.join(__dirname, 'templates');
const uploadsDir = path.join(__dirname, 'uploads'); // [新增]

// 安全中间件配置
// 注意：Helmet 默认会阻止加载外部图片，这里需要放宽 CSP 或者暂时禁用 CSP 以便加载本地图片
app.use(helmet({
  contentSecurityPolicy: false,
  crossOriginResourcePolicy: false
}));

app.use(cors({
  origin: true,
  credentials: true
}));

app.use(express.json({ limit: '10mb' })); // 调大 JSON 限制
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// [新增] 静态文件服务：将 /api/uploads 映射到本地 uploads 目录
// 这样前端访问 /api/uploads/xxx.jpg 就能拿到图片
app.use('/api/uploads', express.static(uploadsDir));

// 导入路由
const authRoutes = require('./routes/auth');
const resumeRoutes = require('./routes/resumes');
const templateRoutes = require('./routes/templates');
const aiRoutes = require('./routes/ai');
const uploadRoutes = require('./routes/upload'); // [新增]

// 使用路由
app.use('/api/auth', authRoutes);
app.use('/api/resumes', resumeRoutes);
app.use('/api/templates', templateRoutes);
app.use('/api/ai', aiRoutes);
app.use('/api/upload', uploadRoutes); // [新增]

// 健康检查
app.get('/api/health', (req, res) => {
  res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// 初始化服务器
async function initializeServer() {
  try {
    // 确保目录存在
    await fs.mkdir(dataDir, { recursive: true });
    await fs.mkdir(templatesDir, { recursive: true });
    await fs.mkdir(uploadsDir, { recursive: true }); // [新增]
    
    // 初始化数据文件
    const defaultFiles = [
      { path: path.join(dataDir, 'users.json'), content: '[]' },
      { path: path.join(dataDir, 'resumes.json'), content: '{}' }
    ];

    for (const file of defaultFiles) {
      try {
        await fs.access(file.path);
      } catch {
        await fs.writeFile(file.path, file.content, 'utf8');
      }
    }

    app.listen(PORT, () => {
      console.log(`🚀 Server running on http://localhost:${PORT}`);
    });
  } catch (error) {
    console.error('Initialization failed:', error);
    process.exit(1);
  }
}

initializeServer();