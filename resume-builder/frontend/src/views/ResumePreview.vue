<template>
  <div class="resume-preview-container" v-loading="loading">
    <div class="preview-navbar">
      <div class="navbar-left">
        <el-button @click="goBack" text>
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="page-title">{{ resumeTitle }} - 预览</h2>
      </div>
      <div class="navbar-right">
        <el-button type="primary" @click="goToEdit">
          <el-icon><EditPen /></el-icon> 编辑
        </el-button>
        <el-button type="success" @click="handleExport">
          <el-icon><Download /></el-icon> 导出 PDF
        </el-button>
      </div>
    </div>

    <div class="preview-main">
      <div class="paper-container">
        <div 
          ref="previewContentRef" 
          class="preview-content html-mode" 
          v-html="renderedHtml"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import html2pdf from 'html2pdf.js'
import { ArrowLeft, EditPen, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { resumeApi, templateApi } from '../services/api'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const resumeTitle = ref('')
const renderedHtml = ref('')
const previewContentRef = ref(null)

const resumeId = route.params.resumeId
let templateId = ''

const loadData = async () => {
  if (!resumeId) return
  
  try {
    loading.value = true
    
    // 1. 获取简历
    const resumeRes = await resumeApi.getResumeById(resumeId)
    const resume = resumeRes.data
    resumeTitle.value = resume.title
    templateId = resume.templateId
    
    const formData = resume.content || resume.formData || {}
    
    // 2. 获取模板 HTML
    const tplRes = await templateApi.getTemplateById(templateId)
    let html = tplRes.data.content
    
    // 3. 替换 HTML 变量
    Object.keys(formData).forEach(key => {
      let value = formData[key]
      
      if (Array.isArray(value)) {
        if (value.length > 0) {
          value = value.filter(i => i && i.trim()).map(i => `<li>${i}</li>`).join('')
        } else {
          value = ''
        }
      }
      
      const displayValue = (value === null || value === undefined) ? '' : value
      const regex = new RegExp(`{{${key}}}`, 'g')
      html = html.replace(regex, displayValue)
    })
    
    html = html.replace(/{{.*?}}/g, '')
    renderedHtml.value = html
    
  } catch (error) {
    console.error('加载预览失败:', error)
    ElMessage.error('无法加载预览')
  } finally {
    loading.value = false
  }
}

const goBack = () => router.push('/')

const goToEdit = () => {
  if (templateId && resumeId) router.push(`/edit/${templateId}/${resumeId}`)
}

const handleExport = () => {
  const element = previewContentRef.value
  const opt = {
    margin: 0,
    filename: `${resumeTitle.value || 'resume'}.pdf`,
    image: { type: 'jpeg', quality: 0.98 },
    html2canvas: { scale: 2, useCORS: true },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
  }
  
  html2pdf().set(opt).from(element).save()
}

onMounted(() => {
  loadData()
})
</script>

<style scoped lang="scss">
.resume-preview-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #525659;
}

.preview-navbar {
  height: 60px;
  background: white;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  z-index: 10;
  
  .navbar-left {
    display: flex;
    align-items: center;
    gap: 16px;
    .page-title { font-size: 18px; margin: 0; color: #333; }
  }
  .navbar-right { display: flex; gap: 12px; }
}

.preview-main {
  flex: 1;
  overflow: auto;
  padding: 40px 0;
  display: flex;
  justify-content: center;
  
  .paper-container {
    width: 210mm;
    min-height: 297mm;
    background: white;
    box-shadow: 0 0 20px rgba(0,0,0,0.3);
  }
}

.preview-content {
  /* 确保 HTML 模板填满纸张 */
  height: 100%;
}
</style>