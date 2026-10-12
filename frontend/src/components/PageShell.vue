<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  CheckCircle2,
  FlaskConical,
  ChevronDown,
  Flame,
  SquarePen,
  Layers,
  LibraryBig,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  User,
  X
} from 'lucide-vue-next'
import AppLogo from './AppLogo.vue'
import ChatConversationPanel from './ChatConversationPanel.vue'
import PersonalProfile from './PersonalProfile.vue'
import SystemStatus from './SystemStatus.vue'
import ModelConfiguration from './ModelConfiguration.vue'
import ModelComparison from './ModelComparison.vue'
import HotConfiguration from './HotConfiguration.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'

defineProps({
  title: String,
  subtitle: String,
  immersive: Boolean,
  hideNavigation: Boolean
})

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const app = useAppStore()
const ui = useUiStore()
const mobileMedia = window.matchMedia('(max-width: 900px)')
const mobileViewport = ref(mobileMedia.matches)
const sidebarCollapsed = computed(() => ui.sidebarCollapsed && !mobileViewport.value)
const mobileOpen = ref(false)
const accountOpen = ref(false)
const sidebarRef = ref(null)
const navigationRef = ref(null)
const activeIndicatorTop = ref(0)
const activeIndicatorVisible = ref(false)
/** 个人资料弹窗。 */
const profileOpen = ref(false)
const systemStatusOpen = ref(false)
const modelConfigurationOpen = ref(false)
const modelComparisonOpen = ref(false)
const hotConfigurationOpen = ref(false)
const profileSaved = ref(false)
let profileSavedTimer

/** Local knowledge tools share the conversation sidebar. */
const navItems = [
  { to: '/documents', label: '知识资料', icon: LibraryBig },
  { to: '/workbench/daily-hot', label: '每日热点', icon: Flame },
  { to: '/visualization', label: '知识可视化', icon: Layers }
]

const isChatPage = computed(() => route.name === 'chat')
const isWorkbenchPage = computed(() => route.name === 'workbench')

function updateActiveIndicator(ensureVisible = false) {
  const sidebar = sidebarRef.value
  const navigation = navigationRef.value
  const active = navigation?.querySelector('a.rail-active')
  if (!sidebar || !navigation || !active) {
    activeIndicatorVisible.value = false
    return
  }

  let navigationBounds = navigation.getBoundingClientRect()
  let activeBounds = active.getBoundingClientRect()
  if (ensureVisible) {
    if (activeBounds.top < navigationBounds.top) {
      navigation.scrollTop += activeBounds.top - navigationBounds.top
    } else if (activeBounds.bottom > navigationBounds.bottom) {
      navigation.scrollTop += activeBounds.bottom - navigationBounds.bottom
    }
    navigationBounds = navigation.getBoundingClientRect()
    activeBounds = active.getBoundingClientRect()
  }

  activeIndicatorVisible.value = activeBounds.bottom > navigationBounds.top && activeBounds.top < navigationBounds.bottom
  activeIndicatorTop.value = activeBounds.top - sidebar.getBoundingClientRect().top + activeBounds.height / 2
}

const handleWindowResize = () => updateActiveIndicator()
const handleMobileChange = event => { mobileViewport.value = event.matches; accountOpen.value = false }

watch(sidebarCollapsed, async () => {
  accountOpen.value = false
  await nextTick()
  updateActiveIndicator(true)
})

function toggleSidebar() { ui.sidebarCollapsed = !ui.sidebarCollapsed }
function sidebarTransitionEnd(event) {
  if (event.target === sidebarRef.value && event.propertyName === 'width') updateActiveIndicator()
}

watch(() => route.path, async () => {
  await nextTick()
  updateActiveIndicator(true)
})

async function startNewChat() {
  await chat.newChat()
  mobileOpen.value = false
  if (route.path !== '/') await router.push('/')
}

async function logout() {
  await auth.logout()
  router.push('/login')
}

function openProfile() {
  accountOpen.value = false
  profileOpen.value = true
}

function openSystemStatus() {
  accountOpen.value = false
  systemStatusOpen.value = true
}

function profileDidSave() {
  profileSaved.value = true
  window.clearTimeout(profileSavedTimer)
  profileSavedTimer = window.setTimeout(() => { profileSaved.value = false }, 2800)
}

onMounted(() => {
  app.load()
  if (!chat.loaded) chat.loadConversations()
  nextTick(() => updateActiveIndicator(true))
  window.addEventListener('resize', handleWindowResize)
  mobileMedia.addEventListener('change', handleMobileChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleWindowResize)
  mobileMedia.removeEventListener('change', handleMobileChange)
  window.clearTimeout(profileSavedTimer)
})
</script>

<template>
  <div class="workspace-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <Transition name="profile-save-toast">
      <div v-if="profileSaved" class="profile-save-toast" role="status">
        <span><CheckCircle2 :size="20" /></span>
        <div>
          <strong>保存成功</strong>
          <small>个人资料已更新</small>
        </div>
      </div>
    </Transition>
    <button v-if="!hideNavigation" class="icon-btn mobile-menu" aria-label="打开导航" @click="mobileOpen = true">
      <Menu :size="20" />
    </button>
    <div v-if="mobileOpen" class="drawer-mask" @click="mobileOpen = false" />

    <aside
      v-if="!hideNavigation"
      ref="sidebarRef"
      class="workspace-nav"
      :class="{ open: mobileOpen, collapsed: sidebarCollapsed, 'chat-navigation': isChatPage }"
      @transitionend="sidebarTransitionEnd"
    >
      <span
        v-show="activeIndicatorVisible"
        class="sidebar-active-indicator"
        :style="{ top: `${activeIndicatorTop}px` }"
        aria-hidden="true"
      />
      <div class="nav-logo">
        <button v-if="sidebarCollapsed" class="logo-expand-control" type="button" data-tooltip="展开侧栏" aria-label="展开侧栏" aria-expanded="false" @click="toggleSidebar">
          <AppLogo compact />
          <span class="logo-expand-icon"><PanelLeftOpen :size="21" /></span>
        </button>
        <template v-else>
          <AppLogo compact />
          <div class="sidebar-brand-copy"><strong class="sidebar-brand-name">MindPilot</strong><small>智能知识管家</small></div>
          <button class="nav-collapse-control" type="button" data-tooltip="收起侧栏" aria-label="收起侧栏" aria-expanded="true" @click="toggleSidebar"><PanelLeftClose :size="19" /></button>
        </template>
        <button class="icon-btn nav-close" aria-label="关闭导航" @click="mobileOpen = false">
          <X :size="18" />
        </button>
      </div>

      <button class="sidebar-new-chat" type="button" aria-label="新聊天" data-tooltip="新聊天" @click="startNewChat">
        <SquarePen :size="19" />
        <span>新聊天</span>
      </button>

      <nav ref="navigationRef" class="primary-navigation" aria-label="主要导航" @scroll="updateActiveIndicator()">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :class="{ 'rail-active': route.path === item.to }"
          active-class="rail-route-active"
          exact-active-class="rail-route-exact"
          :data-tooltip="item.label"
          :aria-label="item.label"
          @click="mobileOpen = false"
        >
          <span class="nav-icon"><component :is="item.icon" :size="19" /></span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div v-show="!sidebarCollapsed" class="sidebar-history">
        <ChatConversationPanel @navigate="mobileOpen = false" />
      </div>
      <button
        class="sidebar-account-trigger"
        :class="{ active: accountOpen }"
        type="button"
        data-tooltip="个人中心"
        aria-label="个人中心"
        @click="accountOpen = !accountOpen"
      >
        <span class="avatar"><img v-if="auth.user?.avatar" :src="auth.user.avatar" alt="个人头像" /><User v-else :size="20" /></span>
        <span>
          <strong>{{ auth.user?.displayName || auth.user?.username || '本地知识管理者' }}</strong>
        </span>
        <ChevronDown :size="15" />
      </button>
    </aside>

    <main
      class="workspace-main"
      :class="{ 'workspace-main-immersive': immersive, 'workspace-main-workbench': isWorkbenchPage, 'workspace-main-fullscreen': hideNavigation, 'sidebar-is-collapsed': sidebarCollapsed }"
    >
      <header v-if="!immersive" class="page-header">
        <div class="page-heading">
          <span class="page-heading-kicker"><i />MINDPILOT WORKSPACE</span>
          <h1>{{ title }}</h1>
          <p>{{ subtitle }}</p>
        </div>
        <div class="page-header-actions"><slot name="actions" /></div>
      </header>
      <div class="page-content" :class="{ 'page-content-immersive': immersive, 'page-content-workbench': isWorkbenchPage }"><slot /></div>
    </main>

    <div v-if="accountOpen" class="account-menu-dismiss" @click="accountOpen = false" />
    <Transition name="account-menu">
      <section v-if="accountOpen" class="account-tool-menu">
        <div class="account-tool-group">
          <button type="button" @click="openSystemStatus">
            <span><Settings2 :size="18" /></span>
            <div><strong>系统状态</strong><small>本地数据库、资料索引与任务</small></div>
          </button>
          <button type="button" @click="openProfile">
            <span><User :size="18" /></span>
            <div><strong>个人资料</strong><small>头像、名称与使用统计</small></div>
          </button>
          <button type="button" @click="accountOpen = false; modelConfigurationOpen = true">
            <span><Settings2 :size="18" /></span>
            <div><strong>模型配置</strong><small>厂商密钥、模型与接口</small></div>
          </button>
          <button type="button" @click="accountOpen = false; hotConfigurationOpen = true">
            <span><Flame :size="18" /></span>
            <div><strong>热点配置</strong><small>关注主题、关键词与获取范围</small></div>
          </button>
          <button type="button" @click="accountOpen = false; modelComparisonOpen = true">
            <span><FlaskConical :size="18" /></span>
            <div><strong>模型对比测试</strong><small>同题对比回答、耗时与用量</small></div>
          </button>
        </div>
        <button class="account-logout" type="button" @click="logout">
          <LogOut :size="17" />退出登录
        </button>
      </section>
    </Transition>

    <Transition name="modal">
      <SystemStatus v-if="systemStatusOpen" @close="systemStatusOpen = false" />
    </Transition>
    <Transition name="modal">
      <ModelConfiguration v-if="modelConfigurationOpen" @close="modelConfigurationOpen = false" />
    </Transition>
    <Transition name="modal">
      <HotConfiguration v-if="hotConfigurationOpen" @close="hotConfigurationOpen = false" />
    </Transition>
    <Transition name="modal">
      <ModelComparison v-if="modelComparisonOpen" @close="modelComparisonOpen = false" @configure="modelComparisonOpen = false; modelConfigurationOpen = true" />
    </Transition>
    <Transition name="modal">
      <PersonalProfile v-if="profileOpen" @close="profileOpen = false" @saved="profileDidSave" />
    </Transition>

  </div>
</template>
