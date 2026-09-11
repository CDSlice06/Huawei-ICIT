<template>
  <el-container class="mw-layout">
    <!-- 左侧固定窄边导航（ui-design.md §2.2/§4.1） -->
    <aside class="mw-sidebar">
      <div class="mw-logo" @click="router.push('/workbench')">
        <span class="mw-logo-name">MemWeave</span>
        <span class="mw-logo-sub">忆织</span>
      </div>
      <nav class="mw-nav">
        <div
          v-for="item in navItems"
          :key="item.key"
          class="mw-nav-group"
        >
          <div
            class="mw-nav-item"
            :class="{ active: isActive(item.path) }"
            @click="router.push(item.path)"
          >
            <el-icon :size="16"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <el-badge
              v-if="item.key === 'review' && reviewCount > 0"
              :value="reviewCount"
              :max="99"
              class="mw-nav-badge"
            />
          </div>
          <div v-if="item.children" class="mw-nav-sub">
            <div
              v-for="child in item.children"
              :key="child.key"
              class="mw-nav-sub-item"
              :class="{ active: isActive(child.path) }"
              @click="router.push(child.path)"
            >
              {{ child.label }}
            </div>
          </div>
        </div>
      </nav>
      <div class="mw-sidebar-footer">
        <div class="mw-nav-item" @click="handleLogout">
          <el-icon :size="16"><SwitchButton /></el-icon>
          <span>退出登录</span>
        </div>
      </div>
    </aside>

    <el-container class="mw-main-container">
      <!-- 顶部通栏（ui-design.md §2.2） -->
      <header class="mw-topbar">
        <span class="mw-topbar-title">{{ pageTitle }}</span>
        <div class="mw-topbar-actions">
          <el-input
            v-model="searchKeyword"
            class="mw-search"
            placeholder="全局搜索"
            :prefix-icon="Search"
            @keyup.enter="goSearch"
          />
          <el-button type="primary" size="small" @click="router.push('/workbench/import')">
            快速记录
          </el-button>
          <el-avatar :size="30">{{ avatarText }}</el-avatar>
        </div>
      </header>

      <!-- 主内容区：居中 1440px（design.md §2.6.5） -->
      <main class="mw-content-area">
        <div class="mw-content">
          <router-view />
        </div>
      </main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Odometer,
  Collection,
  AlarmClock,
  ChatDotRound,
  Reading,
  SwitchButton,
  Search,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi, reviewApi } from '@/api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const searchKeyword = ref('')

interface NavChild {
  key: string
  label: string
  path: string
}
interface NavItem {
  key: string
  label: string
  path: string
  icon: unknown
  children?: NavChild[]
}

const navItems: NavItem[] = [
  { key: 'workbench', label: '工作台', path: '/workbench', icon: Odometer },
  { key: 'kb', label: '知识库', path: '/workbench/knowledge-bases', icon: Collection },
  { key: 'review', label: '回顾中心', path: '/review/today', icon: AlarmClock },
  { key: 'forum', label: '分享广场', path: '/forum', icon: ChatDotRound },
  {
    key: 'study',
    label: '学习沉淀',
    path: '/study/notes',
    icon: Reading,
    children: [
      { key: 'study-notes', label: '知识笔记', path: '/study/notes' },
      { key: 'study-mistakes', label: '错题本', path: '/study/mistakes' },
    ],
  },
]

const pageTitle = computed(() => (route.meta.title as string) || '工作台')
const avatarText = computed(() => (auth.userInfo?.email || 'M').slice(0, 1).toUpperCase())

function isActive(path: string): boolean {
  if (path === '/workbench') return route.path === '/workbench'
  return route.path.startsWith(path)
}

function goSearch() {
  const kw = searchKeyword.value.trim()
  if (kw) router.push({ path: '/search', query: { keyword: kw } })
}

/** 今日待复习数量徽标（tasks.md 10.2 侧边导航入口与徽标） */
const reviewCount = ref(0)
async function loadReviewCount() {
  try {
    const res = await reviewApi.today()
    reviewCount.value = res.total || 0
  } catch {
    reviewCount.value = 0
  }
}
onMounted(loadReviewCount)

async function handleLogout() {
  // 先通知后端删除 Redis 会话，再清本地态（tasks.md 3.2 登出语义）
  try {
    await authApi.logout()
  } catch {
    /* 后端会话已失效也照常登出 */
  }
  auth.clearSession()
  router.push('/login')
}
</script>

<style scoped>
.mw-layout {
  height: 100vh;
}

/* 左侧导航 */
.mw-sidebar {
  width: var(--mw-sidebar-width);
  background: var(--mw-bg-card);
  border-right: 1px solid var(--mw-border);
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
  flex-shrink: 0;
}
.mw-logo {
  padding: 4px 10px 20px;
  cursor: pointer;
}
.mw-logo-name {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.mw-logo-sub {
  margin-left: 8px;
  font-size: 13px;
  color: var(--mw-text-tertiary);
}
.mw-nav {
  flex: 1;
  overflow-y: auto;
}
.mw-nav-group {
  margin-bottom: 4px;
}
.mw-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  font-size: 14px;
  color: var(--mw-text-secondary);
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
}
.mw-nav-item:hover {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
}
.mw-nav-item.active {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
  font-weight: 600;
  /* 选中态：细线条标记，无强高亮色块（ui-design.md §4.1） */
  box-shadow: inset 2px 0 0 var(--mw-text-primary);
}
.mw-nav-badge {
  margin-left: auto;
}
.mw-nav-sub {
  margin: 2px 0 4px;
}
.mw-nav-sub-item {
  padding: 7px 10px 7px 42px;
  font-size: 13px;
  color: var(--mw-text-tertiary);
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
}
.mw-nav-sub-item:hover {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
}
.mw-nav-sub-item.active {
  color: var(--mw-text-primary);
  font-weight: 600;
}
.mw-sidebar-footer {
  border-top: 1px solid var(--mw-border);
  padding-top: 8px;
}

/* 顶部通栏 */
.mw-main-container {
  flex-direction: column;
  min-width: 0;
}
.mw-topbar {
  height: var(--mw-topbar-height);
  background: var(--mw-bg-card);
  border-bottom: 1px solid var(--mw-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  flex-shrink: 0;
}
.mw-topbar-title {
  font-size: 15px;
  font-weight: 600;
}
.mw-topbar-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.mw-search {
  width: 220px;
}

/* 主内容区 */
.mw-content-area {
  overflow-y: auto;
}
.mw-content {
  max-width: var(--mw-content-max-width);
  margin: 0 auto;
  padding: 24px 32px 48px;
}
</style>
