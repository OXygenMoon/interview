<template>
  <div class="login-container">
    <div class="login-wrapper">
      <div class="login-header">
        <h1>简历制作系统</h1>
        <p class="subtitle">为技校学生打造的专属简历工具</p>
      </div>
      
      <div class="login-card">
        <h2>用户登录</h2>
        
        <el-form
          ref="loginForm"
          :model="form"
          :rules="rules"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <el-form-item prop="email">
            <el-input
              v-model="form.email"
              placeholder="请输入邮箱"
              size="large"
              :prefix-icon="User"
            />
          </el-form-item>
          
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form-item>
        </el-form>
        
        <div class="login-footer">
          <p>
            还没有账号？
            <router-link to="/register" class="link">立即注册</router-link>
          </p>
        </div>
      </div>
      
      <div class="features">
        <div class="feature">
          <el-icon size="24"><Document /></el-icon>
          <h3>专业模板</h3>
          <p>多种简历模板，专为技校学生设计</p>
        </div>
        <div class="feature">
          <el-icon size="24"><EditPen /></el-icon>
          <h3>实时预览</h3>
          <p>填写内容即时生成简历预览</p>
        </div>
        <div class="feature">
          <el-icon size="24"><Download /></el-icon>
          <h3>一键导出</h3>
          <p>支持PDF、Markdown格式导出</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { User, Lock, Document, EditPen, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const router = useRouter()
const store = useStore()

const loginForm = ref()
const loading = ref(false)

const form = reactive({
  email: '',
  password: ''
})

const rules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!loginForm.value) return
  
  try {
    await loginForm.value.validate()
    loading.value = true
    
    await store.dispatch('login', {
      email: form.email,
      password: form.password
    })
    
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch (error) {
    ElMessage.error(error.error || '登录失败，请检查邮箱和密码')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="scss">
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.login-wrapper {
  width: 100%;
  max-width: 1200px;
}

.login-header {
  text-align: center;
  margin-bottom: 40px;
  color: white;
  
  h1 {
    font-size: 48px;
    font-weight: 600;
    margin-bottom: 16px;
    text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }
  
  .subtitle {
    font-size: 18px;
    opacity: 0.9;
  }
}

.login-card {
  background: white;
  border-radius: 20px;
  padding: 40px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  margin: 0 auto 60px;
  max-width: 400px;
  
  h2 {
    font-size: 28px;
    margin-bottom: 30px;
    text-align: center;
    color: #333;
    font-weight: 600;
  }
}

.login-form {
  .el-form-item {
    margin-bottom: 24px;
  }
}

.login-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 500;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  
  &:hover {
    opacity: 0.9;
  }
}

.login-footer {
  text-align: center;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid #eee;
  
  p {
    color: #666;
    margin: 0;
  }
  
  .link {
    color: #667eea;
    text-decoration: none;
    font-weight: 500;
    
    &:hover {
      text-decoration: underline;
    }
  }
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 30px;
  margin-top: 40px;
}

.feature {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  padding: 30px;
  text-align: center;
  color: white;
  transition: transform 0.3s ease;
  
  &:hover {
    transform: translateY(-5px);
    background: rgba(255, 255, 255, 0.15);
  }
  
  .el-icon {
    margin-bottom: 20px;
    color: white;
  }
  
  h3 {
    font-size: 20px;
    margin-bottom: 12px;
    font-weight: 600;
  }
  
  p {
    opacity: 0.9;
    line-height: 1.6;
    margin: 0;
  }
}

@media (max-width: 768px) {
  .login-header {
    h1 {
      font-size: 36px;
    }
  }
  
  .login-card {
    padding: 30px 20px;
  }
  
  .features {
    grid-template-columns: 1fr;
  }
}
</style>