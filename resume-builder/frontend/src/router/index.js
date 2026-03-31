import { createRouter, createWebHistory } from 'vue-router'
import store from '../store'
import Dashboard from '../views/Dashboard.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import ResumeEdit from '../views/ResumeEdit.vue'
import ResumePreview from '../views/ResumePreview.vue'
import NotFound from '../views/NotFound.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: { requiresAuth: true }
  },
  // [修复] 添加兼容路由：如果访问 /dashboard，自动跳回 /
  {
    path: '/dashboard',
    redirect: '/'
  },
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { guest: true }
  },
  {
    path: '/register',
    name: 'Register',
    component: Register,
    meta: { guest: true }
  },
  {
    path: '/edit/:templateId/:resumeId?',
    name: 'ResumeEdit',
    component: ResumeEdit,
    meta: { requiresAuth: true }
  },
  {
    path: '/preview/:resumeId',
    name: 'ResumePreview',
    component: ResumePreview,
    meta: { requiresAuth: true }
  },
  // 404 捕获路由（必须放在最后）
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: NotFound
  }
]

const router = createRouter({
  history: createWebHistory(process.env.BASE_URL),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const loggedIn = store.state.currentUser
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const isGuest = to.matched.some(record => record.meta.guest)

  if (requiresAuth && !loggedIn) {
    next('/login')
  } else if (isGuest && loggedIn) {
    next('/')
  } else {
    next()
  }
})

export default router