<template>
  <div class="template-card" @click="handleSelect">
    <div class="template-visual" :class="template.id">
      <div v-if="template.id === 'classic'" class="mini-layout classic">
        <div class="mini-header"></div>
        <div class="mini-line"></div>
        <div class="mini-block"></div>
        <div class="mini-block"></div>
        <div class="mini-block"></div>
      </div>

      <div v-if="template.id === 'modern'" class="mini-layout modern">
        <div class="mini-sidebar"></div>
        <div class="mini-main">
          <div class="mini-block"></div>
          <div class="mini-block"></div>
          <div class="mini-block"></div>
        </div>
      </div>

      <div v-if="template.id === 'technical'" class="mini-layout technical">
        <div class="mini-header"></div>
        <div class="mini-grid">
          <div class="mini-col"></div>
          <div class="mini-col"></div>
        </div>
        <div class="mini-block"></div>
        <div class="mini-block"></div>
      </div>

      <div v-if="template.id === 'creative'" class="mini-layout creative">
        <div class="mini-banner">
          <div class="mini-circle"></div>
        </div>
        <div class="mini-split">
          <div class="mini-left"></div>
          <div class="mini-right"></div>
        </div>
      </div>

      <div class="hover-overlay">
        <el-button type="primary">使用此模板</el-button>
      </div>
    </div>

    <div class="template-footer">
      <div class="template-header-row">
        <h3>{{ template.name }}</h3>
        <el-tag size="small" :type="getTagType(template.category)">{{ template.category }}</el-tag>
      </div>
      <p class="template-desc">{{ getTemplateDesc(template.id) }}</p>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  template: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['select'])

const handleSelect = () => {
  emit('select', props.template.id)
}

const getTagType = (category) => {
  const map = { '通用': '', '商务': 'info', '技术': 'success', '设计': 'warning' }
  return map[category] || ''
}

const getTemplateDesc = (id) => {
  const map = {
    classic: '稳重传统，适合国企、事业单位及传统行业。',
    modern: '左侧导航布局，信息层级分明，适合通用岗位。',
    technical: '紧凑布局，强调技能与项目，程序员首选。',
    creative: '多彩头部设计，视觉冲击力强，适合设计岗。'
  }
  return map[id] || '专业简历模板'
}
</script>

<style scoped lang="scss">
.template-card {
  background: white;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: all 0.3s ease;
  border: 1px solid #eee;
  display: flex;
  flex-direction: column;
  height: 100%;

  &:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
    border-color: #409eff;

    .hover-overlay {
      opacity: 1;
    }
  }
}

.template-visual {
  height: 180px;
  background-color: #f5f7fa;
  position: relative;
  overflow: hidden;
  display: flex;
  justify-content: center;
  padding: 20px;

  .hover-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.3s ease;
    backdrop-filter: blur(2px);
  }
}

/* --- 迷你模板 CSS 绘图 --- */
.mini-layout {
  width: 100px;
  height: 140px;
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  
  /* 通用块 */
  .mini-block { background: #eee; height: 15px; width: 100%; margin-bottom: 2px; }
  
  /* Classic */
  &.classic {
    align-items: center;
    .mini-header { width: 60%; height: 10px; background: #333; margin-bottom: 4px; }
    .mini-line { width: 100%; height: 1px; background: #333; margin-bottom: 6px; }
  }

  /* Modern */
  &.modern {
    flex-direction: row;
    padding: 0;
    gap: 0;
    .mini-sidebar { width: 30%; height: 100%; background: #2c3e50; }
    .mini-main { flex: 1; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
  }

  /* Technical */
  &.technical {
    .mini-header { width: 100%; height: 12px; border-bottom: 2px solid #1b5e20; margin-bottom: 4px; }
    .mini-grid { display: flex; gap: 4px; height: 30px; }
    .mini-col { flex: 1; background: #e8f5e9; }
  }

  /* Creative */
  &.creative {
    padding: 0;
    gap: 0;
    .mini-banner { height: 35px; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; align-items: center; padding-left: 8px; }
    .mini-circle { width: 16px; height: 16px; background: rgba(255,255,255,0.5); border-radius: 50%; }
    .mini-split { display: flex; height: 105px; padding: 4px; gap: 4px; }
    .mini-left { width: 60%; background: #f8f9fa; }
    .mini-right { width: 40%; background: #eee; }
  }
}

.template-footer {
  padding: 16px;
  background: white;
  flex: 1;
  display: flex;
  flex-direction: column;

  .template-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    h3 {
      font-size: 16px;
      font-weight: 600;
      color: #333;
      margin: 0;
    }
  }

  .template-desc {
    font-size: 12px;
    color: #909399;
    line-height: 1.5;
    margin: 0;
  }
}
</style>