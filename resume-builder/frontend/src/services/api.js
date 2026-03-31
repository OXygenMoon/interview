import axios from 'axios'
import store from '../store'
import { ElMessage } from 'element-plus'

const apiClient = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
})

apiClient.interceptors.request.use(
  config => {
    const token = store.state.token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

apiClient.interceptors.response.use(
  response => response,
  error => {
    if (error.response) {
      // 简单处理错误
      const msg = error.response.data.message || '请求失败'
      if (error.response.status !== 401) { // 401 可能会重定向，不一定每次都弹窗
         ElMessage.error(msg)
      }
    }
    return Promise.reject(error)
  }
)

export const authApi = {
  login: (creds) => apiClient.post('/auth/login', creds),
  register: (data) => apiClient.post('/auth/register', data),
  getCurrentUser: () => apiClient.get('/auth/me')
}

export const resumeApi = {
  getUserResumes: (uid) => apiClient.get('/resumes', { params: { userId: uid } }),
  getResumeById: (id) => apiClient.get(`/resumes/${id}`),
  createResume: (data) => apiClient.post('/resumes', data),
  updateResume: (id, data) => apiClient.put(`/resumes/${id}`, data),
  deleteResume: (id) => apiClient.delete(`/resumes/${id}`)
}

export const templateApi = {
  getAllTemplates: () => apiClient.get('/templates'),
  getTemplateById: (id) => apiClient.get(`/templates/${id}`)
}

export const aiApi = {
  optimizeResume: (formData) => apiClient.post('/ai/optimize', { formData }, { timeout: 60000 })
}

// [新增]
export const uploadApi = {
  uploadImage(file) {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  }
}

export default apiClient