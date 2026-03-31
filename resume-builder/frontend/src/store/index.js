import { createStore } from 'vuex'
import api from '../services/api'

export default createStore({
  state: {
    currentUser: null,
    token: localStorage.getItem('token') || null,
    isLoading: false
  },
  mutations: {
    SET_USER(state, user) {
      state.currentUser = user
    },
    SET_TOKEN(state, token) {
      state.token = token
      if (token) {
        localStorage.setItem('token', token)
        api.defaults.headers.common['Authorization'] = `Bearer ${token}`
      } else {
        localStorage.removeItem('token')
        delete api.defaults.headers.common['Authorization']
      }
    },
    SET_LOADING(state, isLoading) {
      state.isLoading = isLoading
    },
    LOGOUT(state) {
      state.currentUser = null
      state.token = null
      localStorage.removeItem('token')
      delete api.defaults.headers.common['Authorization']
    }
  },
  actions: {
    async login({ commit }, credentials) {
      try {
        commit('SET_LOADING', true)
        const response = await api.post('/auth/login', credentials)
        
        commit('SET_TOKEN', response.data.token)
        commit('SET_USER', response.data.user)
        
        return response.data
      } catch (error) {
        throw error.response?.data || { error: '登录失败' }
      } finally {
        commit('SET_LOADING', false)
      }
    },
    
    async register({ commit }, userData) {
      try {
        commit('SET_LOADING', true)
        const response = await api.post('/auth/register', userData)
        
        commit('SET_TOKEN', response.data.token)
        commit('SET_USER', response.data.user)
        
        return response.data
      } catch (error) {
        throw error.response?.data || { error: '注册失败' }
      } finally {
        commit('SET_LOADING', false)
      }
    },
    
    async verifyToken({ commit, state }) {
      try {
        if (!state.token) return false
        
        const response = await api.post('/auth/verify', {}, {
          headers: { Authorization: `Bearer ${state.token}` }
        })
        
        if (response.data.valid) {
          commit('SET_USER', response.data.user)
          return true
        }
      } catch (error) {
        console.error('Token验证失败:', error)
      }
      
      commit('LOGOUT')
      return false
    },
    
    logout({ commit }) {
      commit('LOGOUT')
    }
  },
  getters: {
    isAuthenticated: state => !!state.token,
    currentUser: state => state.currentUser,
    isLoading: state => state.isLoading
  }
})