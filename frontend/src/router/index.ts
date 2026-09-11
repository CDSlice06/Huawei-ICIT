/**
 * 路由配置（tasks.md 1.2，按 design.md §2.6.2 注册全部路由 + 全局前置守卫）。
 * 页面文案遵循 ui-design.md（回顾中心/专题库/沉淀 等弱学习感命名）。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'demo', component: () => import('@/views/demo/DemoPage.vue'), meta: { title: 'MemWeave 忆织' } },
    { path: '/login', name: 'login', component: () => import('@/views/auth/LoginPage.vue'), meta: { title: '登录' } },
    { path: '/register', name: 'register', component: () => import('@/views/auth/RegisterPage.vue'), meta: { title: '注册' } },
    {
      path: '/workbench',
      component: () => import('@/components/layout/AppLayout.vue'),
      children: [
        { path: '', name: 'workbench', component: () => import('@/views/workbench/WorkbenchPage.vue'), meta: { title: '工作台', auth: true } },
        { path: 'import', name: 'import', component: () => import('@/views/workbench/ImportPage.vue'), meta: { title: '新建沉淀', auth: true } },
        { path: 'knowledge-bases', name: 'kb-list', component: () => import('@/views/knowledge/KnowledgeBaseListPage.vue'), meta: { title: '知识库', auth: true } },
        { path: 'kb/:id', name: 'kb-detail', component: () => import('@/views/knowledge/KnowledgeBaseDetailPage.vue'), meta: { title: '专题库', auth: true } },
        { path: 'kb/:id/map', name: 'kb-map', component: () => import('@/views/mindmap/MindMapPage.vue'), meta: { title: '导图空间', auth: true } },
        { path: 'kb/:id/map/puzzle', name: 'kb-map-puzzle', component: () => import('@/views/mindmap/PuzzlePage.vue'), meta: { title: '拼图回顾', auth: true } },
        { path: 'card/:id', name: 'card-detail', component: () => import('@/views/knowledge/CardDetailPage.vue'), meta: { title: '内容详情', auth: true } },
        { path: 'search', name: 'search', component: () => import('@/views/knowledge/SearchResultPage.vue'), meta: { title: '搜索', auth: true } },
        { path: 'review/today', name: 'review-today', component: () => import('@/views/review/TodayReviewPage.vue'), meta: { title: '回顾中心', auth: true } },
        { path: 'review/stats', name: 'review-stats', component: () => import('@/views/review/ReviewStatsPage.vue'), meta: { title: '回顾统计', auth: true } },
        { path: 'study/notes', name: 'study-notes', component: () => import('@/views/workbench/StudyNotesPage.vue'), meta: { title: '知识笔记', auth: true } },
        { path: 'study/mistakes', name: 'study-mistakes', component: () => import('@/views/mistake/MistakeListPage.vue'), meta: { title: '错题本', auth: true } },
        { path: 'study/mistakes/quiz/:id', name: 'mistake-quiz', component: () => import('@/views/mistake/MistakeQuizPage.vue'), meta: { title: '错题复盘', auth: true } },
        { path: 'forum', name: 'forum', component: () => import('@/views/forum/ForumListPage.vue'), meta: { title: '分享广场', auth: true } },
        { path: 'forum/:id', name: 'forum-detail', component: () => import('@/views/forum/ForumDetailPage.vue'), meta: { title: '分享详情', auth: true } },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.meta.auth) {
    const auth = useAuthStore()
    if (!auth.isLogged) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · MemWeave 忆织` : 'MemWeave 忆织'
})

export default router