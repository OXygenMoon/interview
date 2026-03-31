<template>
  <div class="resume-card" @click="handleCardClick">
    <div class="card-cover">
      <div class="scale-wrapper">
        <div class="mini-resume-page" :class="resume.templateId">
          <div class="mini-header-section">
            <div v-if="resume.templateId === 'modern' || resume.templateId === 'creative'" class="mini-photo">
              <img v-if="getFieldValue('avatar')" :src="getFieldValue('avatar')" />
            </div>
            <div class="mini-title-group">
              <div class="mini-name">{{ getFieldValue('name') || '您的姓名' }}</div>
              <div class="mini-job">{{ getFieldValue('job_target') || '求职意向' }}</div>
            </div>
          </div>

          <div class="mini-body-section">
            <div class="mini-line w-80"></div>
            <div class="mini-line w-60"></div>
            <div class="mini-gap"></div>
            <div class="mini-sub-title">教育背景</div>
            <div class="mini-line w-100"></div>
            <div class="mini-line w-90"></div>
            <div class="mini-gap"></div>
            <div class="mini-sub-title">工作经历</div>
            <div class="mini-line w-100"></div>
            <div class="mini-line w-100"></div>
            <div class="mini-line w-70"></div>
          </div>
        </div>
      </div>
      
      <div class="card-overlay">
        <el-button-group>
          <el-button type="primary" circle :icon="EditPen" @click.stop="handleCommand('edit')" />
          <el-button type="success" circle :icon="View" @click.stop="handleCommand('preview')" />
          <el-button type="danger" circle :icon="Delete" @click.stop="handleCommand('delete')" />
        </el-button-group>
      </div>
    </div>

    <div class="card-info">
      <div class="info-main">
        <h3 class="resume-title" :title="resume.title">{{ resume.title }}</h3>
        <div class="job-tag">
          <el-icon><Suitcase /></el-icon>
          <span>{{ getFieldValue('job_target') || '未填写岗位' }}</span>
        </div>
      </div>
      
      <div class="info-meta">
        <div class="meta-left">
          <el-tag size="small" effect="plain" type="info">{{ getTemplateName(resume.templateId) }}</el-tag>
        </div>
        <div class="meta-right">
          <span>{{ formatTime(resume.updatedAt) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { EditPen, View, Delete, Suitcase } from '@element-plus/icons-vue'

const props = defineProps({
  resume: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['edit', 'delete', 'preview'])

const handleCardClick = () => {
  emit('edit', props.resume.id)
}

const handleCommand = (cmd) => {
  emit(cmd, props.resume.id)
}

// 辅助函数
const getFieldValue = (field) => {
  return props.resume.formData?.[field] || ''
}

const getTemplateName = (id) => {
  const map = { classic: '经典简洁', modern: '现代模块', technical: '技术突出', creative: '创意设计' }
  return map[id] || '未知模板'
}

const formatTime = (isoString) => {
  if (!isoString) return ''
  const date = new Date(isoString)
  // 简单的 "刚刚", "昨天", "yyyy-mm-dd" 逻辑，或者直接返回日期
  return date.toLocaleDateString() 
}
</script>

<style scoped lang="scss">
.resume-card {
  background: white;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
  transition: all 0.3s ease;
  border: 1px solid #f0f0f0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  height: 100%;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 10px 30px rgba(0,0,0,0.1);
    
    .card-overlay {
      opacity: 1;
    }
  }
}

/* --- 1. 封面预览区 --- */
.card-cover {
  height: 200px;
  background-color: #e9eef3;
  position: relative;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 15px; /* 让纸张稍微露出来一点 */
  
  .card-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.2s ease;
    z-index: 10;
  }
}

/* 缩放容器：将 A4 比例的 div 缩小放入卡片 */
.scale-wrapper {
  width: 210px; /* A4 宽度基准 */
  transform: scale(0.8); 
  transform-origin: top center;
  box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}

.mini-resume-page {
  width: 100%;
  height: 297px; /* A4 高度比例 */
  background: white;
  padding: 15px;
  box-sizing: border-box;
  overflow: hidden;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  
  /* 通用元素样式 */
  .mini-header-section { margin-bottom: 10px; }
  .mini-name { font-weight: bold; font-size: 14px; margin-bottom: 2px; color: #333; }
  .mini-job { font-size: 10px; color: #666; }
  .mini-line { height: 4px; background: #eee; margin-bottom: 4px; border-radius: 2px; }
  .mini-gap { height: 8px; }
  .mini-sub-title { font-weight: bold; font-size: 10px; margin-bottom: 4px; color: #333; }
  .w-100 { width: 100%; } .w-90 { width: 90%; } .w-80 { width: 80%; } .w-70 { width: 70%; } .w-60 { width: 60%; }

  /* --- 模板特定样式微调 --- */
  
  /* Classic: 居中头部，下划线 */
  &.classic {
    .mini-header-section { text-align: center; border-bottom: 2px solid #333; padding-bottom: 5px; }
    .mini-sub-title { border-bottom: 1px solid #ccc; }
  }

  /* Modern: 蓝色调，侧边栏 (这里用简化版顶部模拟) */
  &.modern {
    .mini-name { color: #0d47a1; }
    .mini-sub-title { color: #0d47a1; background: #e3f2fd; padding: 2px; }
    .mini-photo { float: left; width: 30px; height: 30px; border-radius: 50%; background: #eee; margin-right: 8px; overflow: hidden; img { width:100%; height:100%; object-fit:cover; } }
  }

  /* Technical: 绿色调，紧凑 */
  &.technical {
    .mini-name { color: #1b5e20; }
    .mini-sub-title { border-bottom: 2px solid #1b5e20; color: #1b5e20; }
  }

  /* Creative: 紫色调，顶部Banner */
  &.creative {
    padding-top: 0;
    .mini-header-section { background: linear-gradient(135deg, #667eea, #764ba2); padding: 15px; margin: -15px -15px 10px -15px; color: white; }
    .mini-name { color: white; }
    .mini-job { color: rgba(255,255,255,0.8); }
    .mini-sub-title { color: #764ba2; border-left: 3px solid #764ba2; padding-left: 4px; }
  }
}

/* --- 2. 底部信息区 --- */
.card-info {
  padding: 16px;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: white;
  
  .info-main {
    margin-bottom: 12px;
    
    .resume-title {
      font-size: 16px;
      font-weight: 700;
      color: #1a1a1a;
      margin: 0 0 6px 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    
    .job-tag {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      color: #666;
      
      .el-icon { font-size: 14px; }
    }
  }
  
  .info-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 10px;
    border-top: 1px solid #f5f5f5;
    
    .meta-right {
      font-size: 12px;
      color: #999;
    }
  }
}
</style>