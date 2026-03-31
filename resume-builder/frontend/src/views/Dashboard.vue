<template>
  <div class="dashboard-container">
    <div class="dashboard-navbar">
      <div class="navbar-left">
        <h1 class="logo">简历工坊</h1>
        <span class="welcome">欢迎回来，{{ currentUser?.username }}</span>
      </div>
      <div class="navbar-right">
        <el-button type="primary" @click="createNewResume" size="large">
          <el-icon><Plus /></el-icon>
          新建简历
        </el-button>
        <el-dropdown @command="handleCommand">
          <span class="user-menu">
            <el-avatar :size="36" :src="userAvatar" />
            <span class="username">{{ currentUser?.username }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">
                <el-icon><User /></el-icon>
                个人资料
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    
    <div class="dashboard-main">
      <div class="dashboard-header">
        <h2>我的简历</h2>
        <p class="subtitle">创建、管理和导出您的专业简历</p>
      </div>
      
      <div v-if="loading" class="loading-container">
        <el-skeleton :rows="6" animated />
      </div>
      
      <div v-else-if="resumes.length === 0" class="empty-state">
        <el-empty description="您还没有创建任何简历" :image-size="200">
          <template #image>
            <el-icon :size="80"><Document /></el-icon>
          </template>
          <el-button type="primary" @click="createNewResume" size="large">
            <el-icon><Plus /></el-icon>
            开始创建第一份简历
          </el-button>
        </el-empty>
      </div>
      
      <div v-else class="resumes-container">
        <div class="resumes-grid">
          <resume-card
            v-for="resume in resumes"
            :key="resume.id"
            :resume="resume"
            @edit="editResume"
            @delete="deleteResume"
            @preview="previewResume"
          />
        </div>
      </div>
    </div>
    
    <el-dialog
      v-model="templateDialogVisible"
      title="选择简历模板"
      width="80%"
      class="template-dialog"
    >
      <div class="templates-container">
        <div class="templates-grid">
          <template-card
            v-for="template in templates"
            :key="template.id"
            :template="template"
            @select="selectTemplate"
          />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  User,
  ArrowDown,
  SwitchButton,
  Document
} from '@element-plus/icons-vue'
import ResumeCard from '../components/ResumeCard.vue'
import TemplateCard from '../components/TemplateCard.vue'
import { resumeApi, templateApi } from '../services/api'

const router = useRouter()
const store = useStore()

const loading = ref(false)
const resumes = ref([])
const templates = ref([])
const templateDialogVisible = ref(false)

const currentUser = computed(() => store.state.currentUser)
const userAvatar = computed(() => 
  `https://api.dicebear.com/7.x/avataaars/svg?seed=${currentUser.value?.username}`
)

// 加载简历列表
const loadResumes = async () => {
  if (!currentUser.value) return
  
  try {
    loading.value = true
    const response = await resumeApi.getUserResumes(currentUser.value.id)
    resumes.value = response.data || []
  } catch (error) {
    console.error('加载简历失败:', error)
    ElMessage.error('加载简历失败')
  } finally {
    loading.value = false
  }
}

// 加载模板列表
const loadTemplates = async () => {
  try {
    const response = await templateApi.getAllTemplates()
    templates.value = response.data || []
  } catch (error) {
    console.error('加载模板失败:', error)
  }
}

// 创建新简历
const createNewResume = () => {
  templateDialogVisible.value = true
}

// 选择模板
const selectTemplate = (templateId) => {
  templateDialogVisible.value = false
  router.push(`/edit/${templateId}`)
}

// 编辑简历
const editResume = (resumeId) => {
  const resume = resumes.value.find(r => r.id === resumeId)
  if (resume) {
    router.push(`/edit/${resume.templateId}/${resumeId}`)
  }
}

// 预览简历
const previewResume = (resumeId) => {
  router.push(`/preview/${resumeId}`)
}

// 删除简历
const deleteResume = async (resumeId) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除这份简历吗？删除后无法恢复。',
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    await resumeApi.deleteResume(resumeId, currentUser.value.id)
    resumes.value = resumes.value.filter(r => r.id !== resumeId)
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// 用户菜单命令处理
const handleCommand = (command) => {
  if (command === 'logout') {
    store.dispatch('logout')
    router.push('/login')
  } else if (command === 'profile') {
    ElMessage.info('个人资料功能开发中')
  }
}

onMounted(() => {
  loadResumes()
  loadTemplates()
})
</script>

<style scoped lang="scss">
.dashboard-container {
  min-height: 100vh;
  background-color: #f8f9fa;
}

.dashboard-navbar {
  background: white;
  padding: 0 24px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  position: sticky;
  top: 0;
  z-index: 1000;
  
  .navbar-left {
    display: flex;
    align-items: center;
    gap: 24px;
    
    .logo {
      font-size: 24px;
      font-weight: 600;
      color: #667eea;
      margin: 0;
    }
    
    .welcome {
      color: #666;
      font-size: 14px;
    }
  }
  
  .navbar-right {
    display: flex;
    align-items: center;
    gap: 20px;
    
    .user-menu {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      padding: 8px;
      border-radius: 8px;
      transition: background-color 0.3s ease;
      
      &:hover {
        background-color: #f5f5f5;
      }
      
      .username {
        font-weight: 500;
      }
    }
  }
}

.dashboard-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}

.dashboard-header {
  margin-bottom: 32px;
  
  h2 {
    font-size: 32px;
    font-weight: 600;
    color: #333;
    margin-bottom: 8px;
  }
  
  .subtitle {
    color: #666;
    font-size: 14px;
  }
}

.loading-container {
  background: white;
  border-radius: 12px;
  padding: 40px;
}

.empty-state {
  background: white;
  border-radius: 12px;
  padding: 80px 20px;
  text-align: center;
}

.resumes-container {
  .resumes-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 24px;
  }
}

.template-dialog {
  .el-dialog__body {
    padding: 20px;
  }
}

.templates-container {
  .templates-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 24px;
  }
}

@media (max-width: 768px) {
  .dashboard-navbar {
    padding: 0 16px;
    
    .navbar-left {
      gap: 12px;
      
      .logo {
        font-size: 20px;
      }
      
      .welcome {
        display: none;
      }
    }
    
    .navbar-right {
      .user-menu .username {
        display: none;
      }
    }
  }
  
  .dashboard-main {
    padding: 16px;
  }
  
  .resumes-grid,
  .templates-grid {
    grid-template-columns: 1fr !important;
  }
}
</style>