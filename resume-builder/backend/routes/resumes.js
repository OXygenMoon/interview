const express = require('express');
const router = express.Router();
const path = require('path');
const fs = require('fs').promises;

// 数据文件路径
const DATA_FILE = path.join(__dirname, '../data/resumes.json');

// 简易 ID 生成器 (不依赖外部库)
const generateId = () => Date.now().toString(36) + Math.random().toString(36).substr(2, 5);

// 辅助函数：读取所有简历数据
async function getResumesData() {
  try {
    // 确保文件存在
    try {
      await fs.access(DATA_FILE);
    } catch {
      // 文件不存在则初始化为空对象
      await fs.writeFile(DATA_FILE, '{}', 'utf8');
      return {};
    }

    const content = await fs.readFile(DATA_FILE, 'utf8');
    return content ? JSON.parse(content) : {};
  } catch (error) {
    console.error('读取简历数据失败:', error);
    return {};
  }
}

// 辅助函数：保存所有简历数据
async function saveResumesData(data) {
  await fs.writeFile(DATA_FILE, JSON.stringify(data, null, 2), 'utf8');
}

/**
 * GET /api/resumes
 * 获取简历列表 (支持 ?userId=xxx 过滤)
 */
router.get('/', async (req, res) => {
  try {
    const { userId } = req.query;
    const resumesMap = await getResumesData();
    
    // 1. 将 Map 对象转换为数组 (关键步骤：前端需要数组)
    let resumesList = Object.values(resumesMap);

    // 2. 如果有 userId 参数，进行过滤
    if (userId) {
      resumesList = resumesList.filter(r => String(r.userId) === String(userId));
    }

    // 3. 按最后更新时间倒序排序 (最近的在前面)
    resumesList.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));

    res.json(resumesList);
  } catch (error) {
    console.error('获取简历列表错误:', error);
    res.status(500).json({ error: '获取简历列表失败' });
  }
});

/**
 * GET /api/resumes/:id
 * 获取单份简历详情
 */
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const resumesMap = await getResumesData();
    const resume = resumesMap[id];

    if (!resume) {
      return res.status(404).json({ error: '简历未找到' });
    }

    res.json(resume);
  } catch (error) {
    res.status(500).json({ error: '获取简历详情失败' });
  }
});

/**
 * POST /api/resumes
 * 创建新简历
 */
router.post('/', async (req, res) => {
  try {
    const { userId, templateId, title, content } = req.body;
    
    if (!userId || !templateId) {
      return res.status(400).json({ error: '缺少必要参数' });
    }

    const id = generateId();
    const now = Date.now();

    const newResume = {
      id,
      userId,
      templateId,
      title: title || '未命名简历',
      content: content || {}, // 存储表单数据
      createdAt: now,
      updatedAt: now,
      thumbnail: '' // 预留字段
    };

    const resumesMap = await getResumesData();
    resumesMap[id] = newResume;
    await saveResumesData(resumesMap);

    res.status(201).json(newResume);
  } catch (error) {
    console.error('创建简历错误:', error);
    res.status(500).json({ error: '创建简历失败' });
  }
});

/**
 * PUT /api/resumes/:id
 * 更新简历
 */
router.put('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const updates = req.body;
    
    const resumesMap = await getResumesData();
    const resume = resumesMap[id];

    if (!resume) {
      return res.status(404).json({ error: '简历未找到' });
    }

    // 更新字段 (保护 id 和 userId 不被修改)
    const updatedResume = {
      ...resume,
      ...updates,
      id: resume.id,
      userId: resume.userId,
      updatedAt: Date.now()
    };

    resumesMap[id] = updatedResume;
    await saveResumesData(resumesMap);

    res.json(updatedResume);
  } catch (error) {
    console.error('更新简历错误:', error);
    res.status(500).json({ error: '更新简历失败' });
  }
});

/**
 * DELETE /api/resumes/:id
 * 删除简历
 */
router.delete('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const resumesMap = await getResumesData();

    if (!resumesMap[id]) {
      return res.status(404).json({ error: '简历未找到' });
    }

    delete resumesMap[id];
    await saveResumesData(resumesMap);

    res.json({ success: true, message: '简历已删除' });
  } catch (error) {
    console.error('删除简历错误:', error);
    res.status(500).json({ error: '删除简历失败' });
  }
});

module.exports = router;