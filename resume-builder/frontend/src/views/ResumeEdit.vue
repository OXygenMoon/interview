<template>
  <div class="resume-edit-container">
    <div class="edit-navbar">
      <div class="navbar-left">
        <el-button @click="goBack" type="text" class="back-btn">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <div class="resume-title">
          <el-input
            v-if="editingTitle"
            ref="titleInputRef"
            v-model="resumeTitle"
            @blur="saveTitle"
            @keyup.enter="saveTitle"
            size="small"
            placeholder="请输入简历名称"
          />
          <h2 v-else @click="startEditingTitle">
            {{ resumeTitle || '未命名简历' }}
            <el-icon class="edit-icon"><EditPen /></el-icon>
          </h2>
        </div>
      </div>
      <div class="navbar-right">
        <el-button type="warning" @click="startAiOptimize" :loading="isOptimizing" plain>
          <el-icon v-if="isOptimizing" class="is-loading"><Loading /></el-icon><el-icon v-else><MagicStick /></el-icon> {{ isOptimizing ? 'AI 优化' : '智能优化' }}
        </el-button>
        <el-button @click="saveResume" :loading="saving" type="primary"><el-icon><Check /></el-icon> 保存</el-button>
        <el-dropdown @command="handleExport">
          <el-button><el-icon><Download /></el-icon> 导出</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="pdf">导出为PDF</el-dropdown-item>
              <el-dropdown-item command="html">导出为HTML</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    
    <div class="edit-main" :class="{ 'has-ai-panel': showAiPanel }">
      <div class="form-panel">
        <div class="form-header">
          <h3>填写信息</h3>
          <el-button type="text" @click="toggleAllSections">{{ allExpanded ? '收起全部' : '展开全部' }}</el-button>
        </div>
        <el-scrollbar class="form-scrollbar">
          <el-form ref="formRef" :model="formData" label-position="top" class="resume-form">
            <el-collapse v-model="activeSections">
              <el-collapse-item v-for="(fields, category) in fieldCategories" :key="category" :name="category" :title="getCategoryTitle(category)">
                <div class="form-grid-layout">
                  <template v-for="field in fields" :key="field.name">
                    <div v-if="field.type === 'image'" class="grid-item full-row">
                      <el-form-item :label="field.label">
                        <div class="upload-wrapper">
                          <el-upload class="avatar-uploader" action="#" :auto-upload="false" :show-file-list="false" :on-change="(file) => handleImageUpload(file, field.name)">
                            <div v-if="formData[field.name]" class="avatar-preview" :style="{ backgroundImage: `url(${formData[field.name]})` }"></div>
                            <div v-else class="avatar-uploader-placeholder">
                              <el-icon class="avatar-uploader-icon"><Plus /></el-icon>
                              <div class="upload-text">点击上传</div>
                            </div>
                          </el-upload>
                          <div class="upload-tip">建议 3:4 (如 300x400px)</div>
                        </div>
                      </el-form-item>
                    </div>
                    <div v-else-if="field.type !== 'multi'" class="grid-item">
                      <el-form-item :label="field.label">
                        <component :is="getFieldComponent(field.type)" v-model="formData[field.name]" :placeholder="field.placeholder" :type="field.type === 'textarea' ? 'textarea' : 'text'" :rows="field.type === 'textarea' ? 3 : undefined" @input="updatePreview" />
                      </el-form-item>
                    </div>
                    <div v-if="field.type === 'multi'" class="grid-item full-row">
                      <el-form-item :label="field.label">
                        <div class="multi-items">
                          <div v-for="(item, idx) in formData[field.name]" :key="idx" class="multi-item">
                            <el-input v-model="formData[field.name][idx]" :placeholder="field.placeholder" @input="updatePreview" type="textarea" :rows="2">
                              <template #append><el-button @click="removeMultiItem(field.name, idx)" :icon="Delete" /></template>
                            </el-input>
                          </div>
                          <el-button @click="addMultiItem(field.name)" type="primary" text :icon="Plus" class="add-btn">添加{{ field.label }}</el-button>
                        </div>
                      </el-form-item>
                    </div>
                  </template>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-form>
        </el-scrollbar>
      </div>
      
      <div class="ai-panel" v-if="showAiPanel" v-loading="isOptimizing">
        <div class="ai-header"><h3><el-icon><MagicStick /></el-icon> AI 建议</h3><el-button type="danger" circle size="small" @click="closeAiPanel"><el-icon><Close /></el-icon></el-button></div>
        <div class="ai-content" v-if="aiFormData">
          <el-scrollbar>
            <div v-if="aiFormData.suggestion" class="ai-overall-suggestion"><div class="suggestion-title">整体点评</div>{{ aiFormData.suggestion }}</div>
            <div v-for="(fields, category) in fieldCategories" :key="category + '_ai'" class="ai-section">
              <h4>{{ getCategoryTitle(category) }}</h4>
              <div v-for="field in fields" :key="field.name" class="ai-field-item">
                <div class="ai-field-label">{{ field.label }}</div>
                <div class="ai-field-content">
                  <template v-if="field.type === 'multi' && aiFormData[field.name]">
                    <div v-for="(item, idx) in aiFormData[field.name]" :key="idx" class="ai-multi-row"><div class="ai-text-box">{{ item }}</div></div>
                    <el-button class="apply-btn-block" type="success" plain size="small" @click="applyAiField(field.name)">应用</el-button>
                  </template>
                  <template v-else>
                    <div class="ai-text-box">{{ aiFormData[field.name] || '无建议' }}</div>
                    <el-button class="apply-btn" type="success" circle size="small" @click="applyAiField(field.name)" :disabled="!aiFormData[field.name]"><el-icon><Back /></el-icon></el-button>
                  </template>
                </div>
              </div>
            </div>
          </el-scrollbar>
        </div>
      </div>

      <div class="preview-panel">
        <div class="preview-header"><h3>实时预览</h3></div>
        <el-scrollbar class="preview-scrollbar">
          <div class="preview-workspace">
            <div ref="tempRenderContainer" class="temp-render-layer" v-html="fullRawHtml"></div>
            <div id="print-area" :class="{ 'printing-mode': isExporting }">
              <div v-for="(pageHtml, index) in paginatedPages" :key="index" class="a4-page" v-html="pageHtml"></div>
            </div>
          </div>
        </el-scrollbar>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { useStore } from 'vuex'
import html2pdf from 'html2pdf.js'
import { ArrowLeft, EditPen, Check, Download, Delete, Plus, MagicStick, Loading, Close, Back } from '@element-plus/icons-vue'
import { ElMessage, ElNotification, ElMessageBox } from 'element-plus'
import { resumeApi, templateApi, aiApi, uploadApi } from '../services/api'

const route = useRoute(); const router = useRouter(); const store = useStore()
const templateId = route.params.templateId; const resumeId = route.params.resumeId
const formRef = ref(); const titleInputRef = ref(); const tempRenderContainer = ref() 
const loading = ref(false); const saving = ref(false); const editingTitle = ref(false); const isExporting = ref(false)
const activeSections = ref(['basic', 'education', 'skills', 'experience', 'projects', 'certificates', 'self'])
const allExpanded = computed(() => activeSections.value.length >= 5)
const hasUnsavedChanges = ref(false); const isDataLoaded = ref(false)
const showAiPanel = ref(false); const isOptimizing = ref(false); const aiFormData = ref(null)
const formData = reactive({}); const templateFields = ref([]); const templateHtml = ref(''); const resumeTitle = ref('')
const fullRawHtml = ref(''); const paginatedPages = ref([]) 

const fieldCategories = computed(() => {
  if (!templateFields.value.length) return {}
  const cats = { basic: [], education: [], skills: [], experience: [], projects: [], certificates: [], self: [] }
  const map = {
    avatar: 'basic', name: 'basic', contact: 'basic', email: 'basic', location: 'basic', job_target: 'basic', phone: 'basic',
    school_name: 'education', major: 'education', enrollment_date: 'education', graduation_date: 'education', main_courses: 'education', honors: 'education',
    skills: 'skills', applied_skills: 'skills',
    company: 'experience', position: 'experience', internship_date: 'experience', internship_description: 'experience',
    project_name: 'projects', project_role: 'projects', project_date: 'projects', project_description: 'projects', project_outcome: 'projects',
    certificates: 'certificates', self_evaluation: 'self'
  }
  templateFields.value.forEach(f => { const c = map[f.name] || 'basic'; if (cats[c]) cats[c].push(f) })
  Object.keys(cats).forEach(k => { if (cats[k].length === 0) delete cats[k] })
  return cats
})
const getCategoryTitle = (k) => ({ basic: '基础信息', education: '教育背景', skills: '专业技能', experience: '实习经历', projects: '项目经验', certificates: '证书资质', self: '自我评价' }[k] || '其他')
const getFieldComponent = (type) => 'el-input'

// --- 修复后的分页算法 ---
const calculatePagination = () => {
  const container = tempRenderContainer.value
  if (!container || !container.firstElementChild) return

  const templateRoot = container.firstElementChild.cloneNode(true)
  const styleTag = templateRoot.querySelector('style')
  const cssText = styleTag ? styleTag.outerHTML : ''
  if (styleTag) styleTag.remove()

  const sidebarLayer = templateRoot.querySelector('.sidebar-layer')
  const sidebarHTML = sidebarLayer ? sidebarLayer.outerHTML : ''
  let initialHeight = 0
  
  if (sidebarLayer) {
    const realSidebar = tempRenderContainer.value.querySelector('.sidebar-layer')
    if (realSidebar) {
      const style = window.getComputedStyle(realSidebar)
      if (style.position !== 'absolute' && style.position !== 'fixed') {
        initialHeight = realSidebar.getBoundingClientRect().height
      }
    }
    sidebarLayer.remove()
  }

  const mainFlowContainer = templateRoot.querySelector('.main-flow') || templateRoot
  const children = Array.from(mainFlowContainer.children)
  
  const pages = []
  let currentPageContent = []
  let currentHeight = initialHeight
  
  // 安全高度 930px
  const MAX_HEIGHT = 930

  const createPageHtml = (content, isFirstPage) => {
    // 关键修正：移除内联 padding，让 CSS 生效
    const mainHtml = `<div class="main-flow">${content}</div>`
    const sidebar = isFirstPage ? sidebarHTML : ''
    const pageClass = isFirstPage ? 'page-first' : 'page-following'
    return `${cssText}<div class="${templateRoot.className} ${pageClass}" style="min-height:100%; height:100%; position:relative; overflow:hidden; margin:0; padding:0;">${sidebar}${mainHtml}</div>`
  }

  const pushPage = (isFirstPage) => {
    if (currentPageContent.length > 0 || isFirstPage) { 
      const body = currentPageContent.map(el => el.outerHTML).join('')
      pages.push(createPageHtml(body, isFirstPage))
    }
    currentPageContent = []
    currentHeight = 0
  }

  const realMainContainer = tempRenderContainer.value.querySelector('.main-flow') || tempRenderContainer.value.firstElementChild
  const realChildren = realMainContainer.children

  for (let i = 0; i < children.length; i++) {
    const child = children[i]
    if (child.tagName === 'STYLE' || child.classList.contains('sidebar-layer')) continue;

    const rect = realChildren[i].getBoundingClientRect()
    const style = window.getComputedStyle(realChildren[i])
    const h = rect.height + parseFloat(style.marginTop) + parseFloat(style.marginBottom)
    
    if (h > MAX_HEIGHT) {
      pushPage(pages.length === 0)
      currentPageContent.push(child)
      pushPage(false)
      continue
    }

    if (currentHeight + h > MAX_HEIGHT) {
      pushPage(pages.length === 0) 
      currentPageContent.push(child) 
      currentHeight = h
    } else {
      let isOrphan = false
      if ((child.classList.contains('section-title') || child.tagName.startsWith('H')) && i + 1 < children.length) {
        const nextRect = realChildren[i+1].getBoundingClientRect()
        const nextH = nextRect.height + 40 
        if (currentHeight + h + nextH > MAX_HEIGHT) isOrphan = true
      }
      
      if (isOrphan) {
        pushPage(pages.length === 0)
        currentPageContent.push(child)
        currentHeight = h
      } else {
        currentPageContent.push(child)
        currentHeight += h
      }
    }
  }
  
  if (currentPageContent.length > 0) {
    pushPage(pages.length === 0)
  } else if (pages.length === 0) {
    pushPage(true)
  }
  
  paginatedPages.value = pages
}

watch(formData, () => { if (isDataLoaded.value) hasUnsavedChanges.value = true; updatePreview() }, { deep: true })
onBeforeRouteLeave((to, from, next) => {
  if (hasUnsavedChanges.value) {
    ElMessageBox.confirm('未保存，确定离开？', '提示', { type: 'warning' }).then(() => next()).catch(() => next(false))
  } else { next() }
})

const addMultiItem = (f) => { if (!Array.isArray(formData[f])) formData[f] = []; formData[f].push(''); updatePreview() }
const removeMultiItem = (f, i) => { if (Array.isArray(formData[f])) formData[f].splice(i, 1); updatePreview() }
const handleImageUpload = async (file, f) => {
  const isJPGOrPNG = file.raw.type === 'image/jpeg' || file.raw.type === 'image/png';
  if (!isJPGOrPNG) { ElMessage.error('仅支持 JPG/PNG'); return; }
  try {
    const res = await uploadApi.uploadImage(file.raw);
    if (res.data.success) { formData[f] = res.data.url; updatePreview(); }
  } catch { ElMessage.error('上传失败'); }
}
const startAiOptimize = async () => {
  showAiPanel.value = true; isOptimizing.value = true; aiFormData.value = null
  try { const res = await aiApi.optimizeResume(formData); if (res.data.success) aiFormData.value = res.data.data } catch { showAiPanel.value = false } finally { isOptimizing.value = false }
}
const closeAiPanel = () => { showAiPanel.value = false; aiFormData.value = null }
const applyAiField = (f) => { if (aiFormData.value?.[f]) { formData[f] = aiFormData.value[f]; updatePreview() } }
const loadTemplate = async () => {
  try { loading.value = true; const res = await templateApi.getTemplateById(templateId); templateHtml.value = res.data.content; templateFields.value = res.data.fields || []; templateFields.value.forEach(f => { if (!(f.name in formData)) formData[f.name] = f.type === 'multi' ? [] : '' }); updatePreview() } catch {} finally { loading.value = false }
}
const loadResumeData = async () => {
  if (!resumeId) return; try { const res = await resumeApi.getResumeById(resumeId); resumeTitle.value = res.data.title; if (res.data.content) Object.assign(formData, res.data.content); updatePreview() } catch {}
}
const updatePreview = () => {
  if (!templateHtml.value) return
  let html = templateHtml.value
  Object.keys(formData).forEach(k => {
    let v = formData[k]
    if (Array.isArray(v)) v = v.filter(i => i && i.trim()).map(i => `<li>${i}</li>`).join('') || ''
    if (k === 'avatar' && !v) v = ''
    html = html.replace(new RegExp(`{{${k}}}`, 'g'), v || '')
  })
  fullRawHtml.value = html
  nextTick(calculatePagination)
}
const saveResume = async () => {
  try { saving.value = true; const p = { userId: store.state.currentUser.id, title: resumeTitle.value, templateId, content: formData, formData }; if (resumeId) await resumeApi.updateResume(resumeId, p); else { const r = await resumeApi.createResume(p); router.replace(`/edit/${templateId}/${r.data.id}`) }; hasUnsavedChanges.value = false; ElMessage.success('保存成功') } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleExport = (type) => {
  if (type === 'pdf') {
    isExporting.value = true 
    setTimeout(() => {
      const element = document.getElementById('print-area')
      html2pdf().set({ 
        margin: 0, 
        filename: `${resumeTitle.value}.pdf`, 
        image: { type: 'jpeg', quality: 1 }, 
        html2canvas: { scale: 2, useCORS: true, scrollY: 0, windowWidth: 1200 }, 
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
        pagebreak: { mode: 'avoid-all' }
      }).from(element).save().then(() => { isExporting.value = false })
    }, 100)
  }
}
const goBack = () => router.push('/dashboard'); const startEditingTitle = () => { editingTitle.value = true; nextTick(() => titleInputRef.value?.focus()) }; const saveTitle = () => { editingTitle.value = false; if(!resumeTitle.value) resumeTitle.value = '未命名简历' }; const toggleAllSections = () => { activeSections.value = allExpanded.value ? [] : Object.keys(fieldCategories.value) }
onMounted(async () => { await loadTemplate(); await loadResumeData(); nextTick(() => { isDataLoaded.value = true; hasUnsavedChanges.value = false }) })
</script>

<style scoped lang="scss">
.resume-edit-container { height: 100vh; display: flex; flex-direction: column; background: #f8f9fa; }
.edit-navbar { height: 60px; background: white; border-bottom: 1px solid #dcdfe6; display: flex; justify-content: space-between; align-items: center; padding: 0 20px; }
.navbar-left { display: flex; align-items: center; gap: 20px; }
.back-btn { font-size: 14px; color: #606266; margin-right: 15px; } 
.resume-title h2 { font-size: 16px; margin: 0; cursor: pointer; display: flex; align-items: center; gap: 8px; }
.edit-icon { color: #909399; font-size: 14px; }
.edit-main { flex: 1; overflow: hidden; padding: 20px; gap: 20px; display: grid; grid-template-columns: 420px 1fr; grid-template-rows: minmax(0, 1fr); transition: 0.3s; &.has-ai-panel { grid-template-columns: 1fr 1fr 1fr; min-width: 1200px; } }
.form-panel { background: white; border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; height: 100%; }
.form-header { padding: 20px 25px; border-bottom: 1px solid #ebeef5; display: flex; justify-content: space-between; align-items: center; h3 { margin: 0; font-size: 16px; } }
.form-grid-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
.grid-item { min-width: 0; }
.grid-item.full-row { grid-column: span 2; }
.upload-wrapper { display: flex; justify-content: flex-start; padding: 5px 0; }
.avatar-uploader { width: 120px; height: 160px; border: 1px dashed #d9d9d9; border-radius: 6px; cursor: pointer; position: relative; overflow: hidden; background-color: #fafafa; transition: border-color .3s; }
.avatar-uploader:hover { border-color: #409eff; }
.avatar-uploader :deep(.el-upload) { width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; }
.avatar-preview { width: 100%; height: 100%; background-size: cover; background-position: center; background-repeat: no-repeat; display: block; }
.avatar-uploader-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8c939d; height: 100%; width: 100%; pointer-events: none; }
.avatar-uploader-icon { font-size: 28px; margin-bottom: 5px; }
.upload-text { font-size: 12px; }
.upload-tip { font-size: 12px; color: #909399; margin-left: 15px; align-self: flex-end; padding-bottom: 5px; }
.preview-panel { background: #525659; display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.preview-header { background: white; border-bottom: 1px solid #dcdfe6; padding: 15px 20px; h3 { margin: 0; color: #1a1a1a; font-weight: 800; font-size: 18px; } }
.preview-workspace { display: flex; justify-content: center; padding-bottom: 40px; position: relative; margin-top: 20px;}
.temp-render-layer { position: absolute; top: 0; left: 0; width: 210mm; visibility: hidden; pointer-events: none; z-index: -1; background: white; }
#print-area { font-size: 0; line-height: 0; }
.a4-page { background: white; width: 210mm; height: 297mm; margin-bottom: 20px; box-shadow: 0 0 15px rgba(0,0,0,0.5); overflow: hidden; position: relative; font-size: 14px; line-height: 1.5; }
/* 关键修正：导出时限制高度为 296mm */
#print-area.printing-mode .a4-page { margin-bottom: 0; box-shadow: none; border: none; height: 296mm; min-height: 296mm; overflow: hidden; }
.ai-panel { border: 1px solid #e6a23c; background: #fffdf9; .ai-header { padding: 15px; border-bottom: 1px solid #faecd8; display: flex; justify-content: space-between; } .ai-content { padding: 20px; flex: 1; overflow: auto; } }
.ai-box { background: white; border: 1px solid #e4e7ed; padding: 8px; border-radius: 4px; font-size: 13px; color: #606266; margin-bottom: 5px; }
.resume-form { padding-right: 10px; }
.form-scrollbar { flex: 1; padding: 0 20px 20px; }
.add-btn { width: 100%; border: 1px dashed #dcdfe6; margin-top: 5px; }
.multi-items .multi-item { margin-bottom: 8px; display: flex; gap: 5px; }
</style>