<template>
  <div class="forum-detail">
    <div class="detail-header">
      <el-button :icon="ArrowLeft" text @click="router.push('/workbench/forum')" />
      <div>
        <h3 class="share-title">{{ detail?.title || '分享详情' }}</h3>
        <p class="mw-caption">
          {{ detail?.sharer_email }} 分享于 {{ detail?.shared_at.slice(0, 10) }} · 快照只读
        </p>
      </div>
    </div>

    <!-- 思维导图（快照固定坐标渲染，无任何编辑行为，spec §5.7.1规则6） -->
    <div class="map-box mw-card">
      <h4>思维导图</h4>
      <div ref="mapContainer" class="map-canvas"></div>
    </div>

    <!-- 知识卡片（点击弹窗只读查看） -->
    <h4 class="cards-title">知识卡片（{{ detail?.cards.length ?? 0 }}）</h4>
    <div class="card-grid">
      <div
        v-for="card in detail?.cards ?? []"
        :key="card.id"
        class="snapshot-card mw-card"
        @click="viewCard(card)"
      >
        <div class="card-title">{{ card.title }}</div>
        <div class="card-summary">{{ card.summary }}</div>
        <div class="card-tags">
          <span v-for="t in card.tags.slice(0, 4)" :key="t" class="mw-tag">{{ t }}</span>
        </div>
      </div>
    </div>

    <!-- 卡片只读详情弹窗（无编辑入口，spec §5.7.1规则6） -->
    <el-dialog v-model="cardDialog" :title="viewing?.title" width="560px">
      <template v-if="viewing">
        <div class="field"><span class="label">摘要</span>{{ viewing.summary }}</div>
        <div class="field">
          <span class="label">核心要点</span>
          <ul class="points">
            <li v-for="(p, i) in viewing.key_points" :key="i">{{ p }}</li>
          </ul>
        </div>
        <div class="field">
          <span class="label">自测问答</span>
          <div v-for="(qa, i) in viewing.qa" :key="i" class="qa">
            <div>问：{{ qa.question }}</div>
            <div>答：{{ qa.answer }}</div>
          </div>
        </div>
        <div class="field">
          <span class="label">标签</span>
          <span v-for="t in viewing.tags" :key="t" class="mw-tag">{{ t }}</span>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { forumApi, type SnapshotCard } from '@/api'
import type { Graph } from '@antv/g6'

const route = useRoute()
const router = useRouter()

const detail = ref<Awaited<ReturnType<typeof forumApi.detail>> | null>(null)
const cardDialog = ref(false)
const viewing = ref<SnapshotCard | null>(null)
const mapContainer = ref<HTMLDivElement>()

let graph: Graph | null = null

function viewCard(card: SnapshotCard) {
  viewing.value = card
  cardDialog.value = true
}

/** 快照导图只读渲染：固定坐标（快照内置），无布局引擎/拖拽/编辑行为 */
async function renderMap() {
  const el = mapContainer.value
  const map = detail.value?.mind_maps?.[0]
  if (!el || !map || map.nodes.length === 0) return

  const { Graph } = await import('@antv/g6')
  graph = new Graph({
    container: el,
    autoFit: 'view',
    data: {
      nodes: map.nodes.map((n) => ({
        id: n.id,
        title: n.title,
        card_id: n.card_id,
        style: { x: n.x ?? 0, y: n.y ?? 0 },
      })),
      edges: map.nodes
        .filter((n) => n.parent_id)
        .map((n) => ({ source: n.parent_id as string, target: n.id })),
    },
    node: {
      style: {
        fill: '#ffffff',
        stroke: '#e5e6eb',
        lineWidth: 1,
        size: [150, 36],
        labelText: (d: Record<string, unknown>) => String(d.title ?? ''),
        labelPlacement: 'center',
        labelFontSize: 12,
        labelPadding: [0, 8],
        radius: 6,
      },
    },
    edge: { style: { stroke: '#c9cdd4', lineWidth: 1 } },
    behaviors: ['zoom-canvas'],
  })
  await graph.render()
}

onMounted(async () => {
  detail.value = await forumApi.detail(route.params.id as string).catch(() => null)
  if (detail.value) await renderMap()
})

onBeforeUnmount(() => {
  graph?.destroy()
})
</script>

<style scoped>
.forum-detail {
  max-width: 960px;
  margin: 0 auto;
}
.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
}
.share-title {
  margin: 0;
  font-size: 18px;
}
.map-box {
  padding: 18px 22px;
  margin-bottom: 22px;
}
.map-box h4,
.cards-title {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--mw-text-secondary);
}
.map-canvas {
  height: 360px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.snapshot-card {
  padding: 16px 20px;
  cursor: pointer;
}
.card-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.card-summary {
  font-size: 13px;
  color: var(--mw-text-secondary);
  margin-bottom: 10px;
}
.field {
  margin-bottom: 14px;
  line-height: 1.8;
}
.field .label {
  display: block;
  font-size: 12px;
  color: var(--mw-text-tertiary);
  margin-bottom: 4px;
}
.points {
  margin: 0;
  padding-left: 18px;
}
.qa {
  border-top: 1px dashed var(--mw-border);
  padding: 6px 0;
  font-size: 13px;
}
</style>
