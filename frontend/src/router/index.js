import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

/**
 * 路由表保留 AI 助手、知识资料与知识可视化等页面。
 * 模型配置从账户菜单打开，由后端读写 .mindpoilt/models.json。
 * 后端模式先验证刷新 Cookie 恢复登录，再检查页面访问权限。
 */
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { guest: true, title: '登录' }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/Register.vue'),
    meta: { guest: true, title: '注册' }
  },
  {
    path: '/',
    name: 'chat',
    component: () => import('@/views/Home.vue'),
    meta: { auth: true, title: '智能知识管家' }
  },
  {
    path: '/documents',
    name: 'documents',
    component: () => import('@/views/DocumentCenter.vue'),
    meta: { auth: true, title: '知识资料' }
  },
  {
    path: '/conversation-map',
    name: 'conversation-map',
    component: () => import('@/views/ConversationMap.vue'),
    meta: { auth: true, title: '会话地图' }
  },
  {
    path: '/wiki',
    name: 'wiki',
    component: () => import('@/views/WikiCenter.vue'),
    meta: { auth: true, title: 'LLM Wiki' }
  },
  {
    path: '/visualization',
    name: 'visualization',
    component: () => import('@/views/Visualization.vue'),
    meta: { auth: true, title: '知识可视化' }
  },
  {
    path: '/assistant',
    name: 'assistant',
    component: () => import('@/views/Assistant.vue'),
    meta: { auth: true, title: 'AI管家' }
  },
  {
    path: '/workbench/:section(daily-hot)',
    name: 'workbench',
    component: () => import('@/views/Workbench.vue'),
    meta: { auth: true, title: '个人工作台' }
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  // 桌面构建使用 Hash 路由，避免打包后本地直接打开时刷新 404。
  history: import.meta.env.MODE === 'desktop' ? createWebHashHistory() : createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.restore()
  if (to.meta.auth && !auth.isLoggedIn) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.meta.guest && auth.isLoggedIn) return '/'
  return true
})

router.afterEach((to, from, failure) => {
  if (failure) return
  if (to.name === 'conversation-map' && from.name !== 'conversation-map' && from.meta.auth) {
    useUiStore().conversationMapReturnPath = from.fullPath
  }
  const title = to.meta.title
  document.title = title ? `${title} · MindPilot` : 'MindPilot · 本地个人知识助手'
})

export default router
