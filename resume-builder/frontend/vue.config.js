const { defineConfig } = require('@vue/cli-service')

// 动态获取端口
const backendPort = process.env.BACKEND_PORT || 3001
const frontendPort = process.env.FRONTEND_PORT || 8080

module.exports = defineConfig({
  transpileDependencies: true,
  lintOnSave: false,
  
  devServer: {
    port: frontendPort,
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
        // 删除 pathRewrite，因为后端路由已经包含了 /api 前缀
      }
    },
    client: {
      overlay: {
        warnings: false,
        errors: true
      }
    }
  },
  
  css: {
    loaderOptions: {
      scss: {
        additionalData: `@import "@/assets/styles/variables.scss";`
      }
    }
  },
  
  publicPath: process.env.NODE_ENV === 'production' ? './' : '/',
  productionSourceMap: false,
  outputDir: 'dist',
  assetsDir: 'static'
})