const express = require('express');
const router = express.Router();
const path = require('path');
const fs = require('fs').promises;
const authMiddleware = require('../middleware/auth');

router.use(authMiddleware);

const DATA_FILE = path.join(__dirname, '../data/resumes.json');

const generateId = () => Date.now().toString(36) + Math.random().toString(36).substr(2, 5);

async function getResumesData() {
  try {
    try {
      await fs.access(DATA_FILE);
    } catch {
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

async function saveResumesData(data) {
  await fs.writeFile(DATA_FILE, JSON.stringify(data, null, 2), 'utf8');
}

function checkOwnership(resume, req) {
  if (!resume) return false;
  return String(resume.userId) === String(req.user.userId);
}

/**
 * GET /api/resumes
 * 获取当前用户的简历列表
 */
router.get('/', async (req, res) => {
  try {
    const resumesMap = await getResumesData();
    let resumesList = Object.values(resumesMap);

    resumesList = resumesList.filter(r => String(r.userId) === String(req.user.userId));
    resumesList.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));

    res.json(resumesList);
  } catch (error) {
    console.error('获取简历列表错误:', error);
    res.status(500).json({ error: '获取简历列表失败' });
  }
});

/**
 * GET /api/resumes/:id
 */
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const resumesMap = await getResumesData();
    const resume = resumesMap[id];

    if (!resume) {
      return res.status(404).json({ error: '简历未找到' });
    }
    if (!checkOwnership(resume, req)) {
      return res.status(403).json({ error: '无权访问此简历' });
    }

    res.json(resume);
  } catch (error) {
    res.status(500).json({ error: '获取简历详情失败' });
  }
});

/**
 * POST /api/resumes
 */
router.post('/', async (req, res) => {
  try {
    const { templateId, title, content } = req.body;

    if (!templateId) {
      return res.status(400).json({ error: '缺少必要参数' });
    }

    const id = generateId();
    const now = Date.now();

    const newResume = {
      id,
      userId: req.user.userId,
      templateId,
      title: title || '未命名简历',
      content: content || {},
      createdAt: now,
      updatedAt: now,
      thumbnail: ''
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
    if (!checkOwnership(resume, req)) {
      return res.status(403).json({ error: '无权修改此简历' });
    }

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
 */
router.delete('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const resumesMap = await getResumesData();

    if (!resumesMap[id]) {
      return res.status(404).json({ error: '简历未找到' });
    }
    if (!checkOwnership(resumesMap[id], req)) {
      return res.status(403).json({ error: '无权删除此简历' });
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
