<template>
  <div class="search-page">
    <!-- 关键词搜索模式 -->
    <template v-if="mode === 'keyword'">
      <div class="search-head">
        <el-input
          v-model="keyword"
          class="search-input"
          placeholder="搜索知识卡片、素材、错题…"
          clearable
          @keyup.enter="doSearch"
        >
          <template #append>
            <el-button @click="doSearch">搜索</el-button>
          </template>
        </el-input>
      </div>

      <el-empty v-if="searched && total === 0" :description="`没有找到与「${keyword}」相关的内容`" />

      <template v-if="result">
        <!-- 卡片 -->
        <section v-if="result.cards.length" class="hit-group">
          <h4 class="group-title">知识卡片（{{ result.counts.cards }}）</h4>
          <div
            v-for="hit in result.cards"
            :key="hit.id"
            class="hit-card mw-card"
            @click="router.push(`/card/${hit.id}`)"
          >
            <div class="hit-title"><span v-for="(seg, i) in highlight(hit.title)" :key="i" :class="{ hit: seg.hit }">{{ seg.t }}</span></div>
            <div class="hit-snippet"><span v-for="(seg, i) in highlight(hit.snippet)" :key="i" :class="{ hit: seg.hit }">{{ seg.t }}</span></div>
            <div class="hit-meta">
              <span v-for="t in hit.tags.slice(0, 4)" :key="t" class="mw-tag">{{ t }}</span>
            </div>
          </div>
        </section>

        <!-- 素材 -->
        <section v-if="result.assets.length" class="hit-group">
          <h4 class="group-title">来源素材（{{ result.counts.assets }}）</h4>
          <div v-for="hit in result.assets" :key="hit.id" class="hit-card mw-card" @click="showAsset(hit.id)">
            <div class="hit-title">
              <el-tag size="small" type="info">{{ typeLabel(hit.asset_type) }}</el-tag>
              <span class="hit-snippet"><span v-for="(seg, i) in highlight(hit.snippet)" :key="i" :class="{ hit: seg.hit }">{{ seg.t }}</span></span>
            </div>
          </div>
        </section>

        <!-- 错题 -->
        <section v-if="result.mistakes.length" class="hit-group">
          <h4 class="group-title">错题（{{ result.counts.mistakes }}）</h4>
          <div
            v-for="hit in result.mistakes"
            :key="hit.id"
            class="hit-card mw-card"
            @click="router.push('/workbench/study/mistakes')"
          >
            <div class="hit-title"><span v-for="(seg, i) in highlight(hit.question)" :key="i" :class="{ hit: seg.hit }">{{ seg.t }}</span></div>
            <div class="hit-snippet"><span v-for="(seg, i) in highlight(hit.snippet)" :key="i" :class="{ hit: seg.hit }">{{ seg.t }}</span></div>
            <div class="hit-meta">
              <el-tag size="small" :type="hit.mastery === 'mastered' ? 'success' : 'danger'">
                {{ hit.mastery === 'mastered' ? '已掌握' : '未掌握' }}
              </el-tag>
              <span v-for="t in hit.tags.slice(0, 3)" :key="t" class="mw-tag">{{ t }}</span>
            </div>
          </div>
        </section>
      </template>
    </template>

    <!-- 标签浏览模式（spec §5.4.1规则6） -->
    <template v-else>
      <div class="search-head">
        <h3 class="mw-title">标签：{{ tag }}</h3>
        <el-button link @click="router.push('/search')">清空筛选</el-button>
      </div>
      <el-empty v-if="tagCards.length === 0" description="该标签下暂无卡片" />
      <div class="card-grid">
        <div
          v-for="card in tagCards"
          :key="card.id"
          class="hit-card mw-card"
          @click="router.push(`/card/${card.id}`)"
        >
          <div class="hit-title">{{ card.title }}</div>
          <div class="hit-snippet">{{ card.summary }}</div>
          <div class="hit-meta">
            <span v-for="t in card.tags.slice(0, 4)" :key="t" class="mw-tag">{{ t }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 素材原文弹窗 -->
    <el-dialog v-model="assetDialog" title="素材原文" width="640px">
      <p class="asset-text">{{ assetText }}</p>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assetApi, cardApi, searchApi, type CardItem, type SearchResult } from '@/api'

const route = useRoute()
const router = useRouter()

const mode = computed(() => (route.query.tag ? 'tag' : 'keyword'))
const keyword = ref((route.query.keyword as string) || '')
const tag = computed(() => (route.query.tag as string) || '')
const result = ref<SearchResult | null>(null)
const searched = ref(false)
const tagCards = ref<CardItem[]>([])
const assetDialog = ref(false)
const assetText = ref('')

const total = computed(() =>
  result.value ? result.value.counts.cards + result.value.counts.assets + result.value.counts.mistakes : 0,
)

async function doSearch() {
  const kw = keyword.value.trim()
  if (!kw) return
  result.value = await searchApi.search(kw)
  searched.value = true
}

async function loadTagCards() {
  if (!tag.value) return
  const res = await cardApi.list({ tag: tag.value, page: 1, size: 100 }).catch(() => ({ items: [] }))
  tagCards.value = res.items
}

async function showAsset(id: string) {
  const asset = await assetApi.get(id).catch(() => null)
  const raw = (asset?.extracted_text as string) || (asset?.raw_content as string) || '（无正文）'
  assetText.value = raw
  assetDialog.value = true
}

/** 关键词高亮：拆分为命中/非命中片段（避免v-html注入，纯文本渲染） */
function highlight(text: string): { t: string; hit: boolean }[] {
  const kw = (mode.value === 'keyword' ? keyword.value : '').trim()
  if (!kw || !text) return [{ t: text, hit: false }]
  const parts: { t: string; hit: boolean }[] = []
  const lower = text.toLowerCase()
  const lowerKw = kw.toLowerCase()
  let i = 0
  while (i < text.length) {
    const pos = lower.indexOf(lowerKw, i)
    if (pos < 0) {
      parts.push({ t: text.slice(i), hit: false })
      break
    }
    if (pos > i) parts.push({ t: text.slice(i, pos), hit: false })
    parts.push({ t: text.slice(pos, pos + kw.length), hit: true })
    i = pos + kw.length
  }
  return parts
}

function typeLabel(t: string): string {
  return { text: '文本', doc: '文档', image: '图片' }[t] || t
}

watch(
  () => route.query,
  (q) => {
    keyword.value = (q.keyword as string) || ''
    if (q.keyword) void doSearch()
    if (q.tag) void loadTagCards()
  },
)

onMounted(() => {
  if (route.query.keyword) void doSearch()
  if (route.query.tag) void loadTagCards()
})
</script>

<style scoped>
.search-page {
  max-width: 860px;
  margin: 0 auto;
}
.search-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}
.search-input {
  flex: 1;
}
.group-title {
  margin: 22px 0 10px;
  font-size: 14px;
  color: var(--mw-text-secondary);
}
.hit-card {
  padding: 14px 18px;
  margin-bottom: 10px;
  cursor: pointer;
}
.hit-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.hit-snippet {
  font-size: 13px;
  color: var(--mw-text-secondary);
  line-height: 1.7;
}
.hit-meta {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  align-items: center;
}
.hit-title :deep(.hit),
.hit-snippet :deep(.hit) {
  color: var(--el-color-primary);
  font-weight: 700;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.asset-text {
  white-space: pre-wrap;
  line-height: 1.8;
  max-height: 50vh;
  overflow-y: auto;
}
</style>
