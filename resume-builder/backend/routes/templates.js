const express = require('express');
const router = express.Router();
const path = require('path');
const fs = require('fs').promises;

const TEMPLATES_DIR = path.join(__dirname, '../templates');

// 字段定义映射
const FIELD_DEFINITIONS = {
  // [新增] 头像字段
  avatar: { label: '证件照', type: 'image', placeholder: '请上传照片' },

  // 基础信息
  name: { label: '姓名', type: 'text', placeholder: '请输入姓名' },
  job_target: { label: '求职意向', type: 'text', placeholder: '例如：前端工程师' },
  phone: { label: '电话', type: 'text', placeholder: '请输入手机号' },
  email: { label: '邮箱', type: 'text', placeholder: '请输入邮箱' },
  location: { label: '所在城市', type: 'text', placeholder: '例如：北京' },
  
  // 教育背景
  school_name: { label: '学校名称', type: 'text', placeholder: '请输入学校名称' },
  major: { label: '专业', type: 'text', placeholder: '请输入专业' },
  enrollment_date: { label: '入学时间', type: 'text', placeholder: '例如：2019.09' },
  graduation_date: { label: '毕业时间', type: 'text', placeholder: '例如：2023.06' },
  main_courses: { label: '主修课程', type: 'multi', placeholder: '列出主要相关课程' },
  honors: { label: '在校荣誉', type: 'multi', placeholder: '列出获得的奖项' },
  
  // 技能与经历
  skills: { label: '技能列表', type: 'multi', placeholder: '添加一项技能' },
  applied_skills: { label: '应用技能', type: 'multi', placeholder: '实习中应用的技能' },
  company: { label: '公司名称', type: 'text', placeholder: '请输入公司名称' },
  position: { label: '职位', type: 'text', placeholder: '请输入职位' },
  internship_date: { label: '实习时间', type: 'text', placeholder: '例如：2022.06 - 2022.09' },
  internship_description: { label: '工作内容', type: 'textarea', placeholder: '描述你的主要工作内容' },
  
  // 项目经验
  project_name: { label: '项目名称', type: 'text', placeholder: '请输入项目名称' },
  project_role: { label: '担任角色', type: 'text', placeholder: '例如：负责人 / 核心开发' },
  project_date: { label: '项目时间', type: 'text', placeholder: '例如：2022.10 - 2022.12' },
  project_description: { label: '项目描述', type: 'textarea', placeholder: '项目背景及你的职责' },
  project_outcome: { label: '项目成果', type: 'textarea', placeholder: '取得了什么成果' },
  
  // 其他
  self_evaluation: { label: '自我评价', type: 'textarea', placeholder: '总结你的优势' },
  certificates: { label: '证书资质', type: 'multi', placeholder: '例如：英语六级' },
  
  default: { label: '其他字段', type: 'text', placeholder: '请输入内容' }
};

// 模板元数据
const TEMPLATE_META = {
  classic: { name: '经典简洁', category: '通用', description: '传统、专业的简历模板' },
  modern: { name: '现代模块', category: '商务', description: '左侧导航，右侧内容，清晰明了' },
  technical: { name: '技术突出', category: '技术', description: '强调技能和项目，适合程序员' },
  creative: { name: '创意设计', category: '设计', description: '多彩头部，网格布局' }
};

// 获取所有模板列表
router.get('/', async (req, res) => {
  try {
    try {
      await fs.access(TEMPLATES_DIR);
    } catch {
      await fs.mkdir(TEMPLATES_DIR, { recursive: true });
    }

    const files = await fs.readdir(TEMPLATES_DIR);
    const templates = [];

    for (const file of files) {
      if (path.extname(file) === '.html') {
        const id = path.basename(file, '.html');
        const meta = TEMPLATE_META[id] || {};
        
        templates.push({
          id,
          name: meta.name || (id.charAt(0).toUpperCase() + id.slice(1)),
          description: meta.description || 'HTML Resume Template',
          category: meta.category || '通用',
          thumbnail: `/thumbnails/${id}.png`
        });
      }
    }

    res.json(templates);
  } catch (error) {
    console.error('获取模板列表失败:', error);
    res.status(500).json({ error: '获取模板列表失败' });
  }
});

// 获取单个模板详情
router.get('/:templateId', async (req, res) => {
  try {
    const { templateId } = req.params;
    const filePath = path.join(TEMPLATES_DIR, `${templateId}.html`);
    
    try {
      await fs.access(filePath);
    } catch {
      return res.status(404).json({ error: '模板未找到' });
    }

    const content = await fs.readFile(filePath, 'utf8');
    
    // 解析内容中的变量 {{variable_name}}
    const regex = /\{\{([^}]+)\}\}/g;
    const matches = [...content.matchAll(regex)];
    const uniqueFields = [...new Set(matches.map(m => m[1].trim()))];
    
    // 生成字段配置
    const fields = uniqueFields.map(name => {
      const def = FIELD_DEFINITIONS[name] || { ...FIELD_DEFINITIONS.default, label: name };
      return {
        name,
        ...def
      };
    });

    res.json({
      id: templateId,
      content,
      fields
    });
  } catch (error) {
    console.error('获取模板详情失败:', error);
    res.status(500).json({ error: '获取模板详情失败' });
  }
});

module.exports = router;