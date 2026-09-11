<template>
  <div class="workbench">
    <!-- 顶部概览：3个极简数据卡片（ui-design.md §3.2） -->
    <div class="stat-row">
      <div class="stat-card mw-card">
        <div class="stat-num">{{ kbStats.cardCount }}</div>
        <div class="stat-label">知识卡片总数</div>
      </div>
      <div class="stat-card mw-card">
        <div class="stat-num">{{ kbStats.kbCount }}</div>
        <div class="stat-label">我的专题库</div>
      </div>
      <div class="stat-card mw-card clickable" @click="router.push('/review/today')">
        <div class="stat-num">{{ review.todayCount }}</div>
        <div class="stat-label">今日待回顾</div>
      </div>
    </div>

    <!-- 左65%最近沉淀 / 右35%我的专题（ui-design.md §3.2） -->
    <div class="main-row">
      <section class="recent-pane">
        <div class="pane-header">
          <h3>最近沉淀</h3>
          <el-link :underline="false" @click="router.push('/workbench/import')">去沉淀 →</el-link>
        </div>
        <el-empty v-if="recentCards.length === 0" description="还没有沉淀内容，点击右上角「快速记录」开始" />
        <div
          v-for="card in recentCards"
          :key="card.id"
          class="recent-item mw-card"
          @click="router.push(`/card/${card.id}`)"
        >
          <div class="recent-title">{{ card.title }}</div>
          <div class="recent-summary">{{ card.summary }}</div>
          <div class="recent-meta">
            <span v-for="t in card.tags.slice(0, 3)" :key="t" class="mw-tag">{{ t }}</span>
            <span class="mw-caption">{{ card.created_at?.slice(0, 10) }}</span>
          </div>
        </div>
      </section>

      <aside class="topics-pane">
        <div class="pane-header">
          <h3>我的专题</h3>
          <el-link :underline="false" @click="router.push('/workbench/knowledge-bases')">
            管理全部 →
          </el-link>
        </div>
        <el-empty v-if="kbList.length === 0" description="新建第一个专题库" />
        <div
          v-for="kb in kbList"
          :key="kb.id"
          class="topic-card mw-card"
          @click="router.push(`/kb/${kb.id}`)"
        >
          <div class="topic-name">{{ kb.name }}</div>
          <div class="mw-caption">{{ kb.card_count }} 条内容</div>
        </div>
      </aside>
    </div>

    <!-- 标签云（P1-5，spec §5.4.1规则6 按标签浏览） -->
    <section v-if="tags.length" class="tag-cloud mw-card">
      <div class="pane-header">
        <h3>标签</h3>
        <el-link :underline="false" @click="router.push('/search')">按标签浏览 →</el-link>
      </div>
      <div class="tag-row">
        <span
          v-for="t in tags"
          :key="t.tag"
          class="mw-tag tag-chip"
          @click="router.push({ path: '/search', query: { tag: t.tag } })"
        >
          {{ t.tag }}<span class="tag-count">{{ t.count }}</span>
        </span>
      </div>
    </section>

    <!-- 右下角悬浮「+新建沉淀」主按钮（ui-design.md §3.2） -->
    <div class="fab" title="新建沉淀" @click="router.push('/workbench/import')">+</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { cardApi, kbApi, reviewApi, searchApi, type CardItem, type KnowledgeBaseItem, type TagAgg } from '@/api'
import { useReviewStore } from '@/stores/review'

const router = useRouter()
const review = useReviewStore()

const kbList = ref<KnowledgeBaseItem[]>([])
const recentCards = ref<CardItem[]>([])
const tags = ref<TagAgg[]>([])

const kbStats = computed(() => ({
  cardCount: kbList.value.reduce((sum, kb) => sum + (kb.card_count || 0), 0),
  kbCount: kbList.value.length,
}))

onMounted(async () => {
  const [kbs, today] = await Promise.all([
    kbApi.list(),
    reviewApi.today().catch(() => ({ items: [], total: 0 })),
  ])
  kbList.value = kbs
  review.setTodayCount(today.total)

  const latest = await cardApi.list({ page: 1, size: 8 }).catch(() => ({ items: [], total: 0 }))
  recentCards.value = latest.items

  const tagRes = await searchApi.tags().catch(() => ({ items: [], total: 0 }))
  tags.value = tagRes.items.slice(0, 12)
})
</script>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 28px;
}
.stat-card {
  padding: 24px 28px;
  text-align: left;
}
.stat-card.clickable {
  cursor: pointer;
}
.stat-num {
  font-size: 34px;
  font-weight: 700;
  line-height: 1.2;
}
.stat-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--mw-text-tertiary);
}
.main-row {
  display: grid;
  grid-template-columns: 65fr 35fr;
  gap: 24px;
  align-items: start;
}
.tag-cloud {
  padding: 18px 24px;
  margin-bottom: 28px;
}
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.tag-chip {
  cursor: pointer;
}
.tag-count {
  margin-left: 4px;
  opacity: 0.65;
}
.pane-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 14px;
}
.pane-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.recent-item {
  padding: 16px 20px;
  margin-bottom: 12px;
  cursor: pointer;
}
.recent-title {
  font-weight: 600;
  font-size: 15px;
}
.recent-summary {
  margin: 6px 0 10px;
  font-size: 13px;
  color: var(--mw-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.recent-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}
.topic-card {
  padding: 18px 20px;
  margin-bottom: 12px;
  cursor: pointer;
}
.topic-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 6px;
}
.fab {
  position: fixed;
  right: 48px;
  bottom: 48px;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--mw-accent);
  color: #fff;
  font-size: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(31, 35, 41, 0.25);
  transition: transform 0.15s ease;
  user-select: none;
}
.fab:hover {
  transform: scale(1.06);
}
</style>