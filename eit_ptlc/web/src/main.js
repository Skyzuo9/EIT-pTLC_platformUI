// Vue3 应用入口: 装配 Pinia + 路由
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia()).use(router)

// 深链先完成路由解析再挂载, 防止 /3d 首帧短暂创建默认动作页的 ExplorerDock.
router.isReady().then(() => app.mount('#app'))
