<template>
  <div class="mindmap-canvas">
    <div ref="containerRef" class="canvas-box"></div>

    <!-- 空态/生成引导（tasks.md 10.5） -->
    <div v-if="state === 'empty'" class="empty-overlay">
      <el-empty description="该专题库还没有思维导图">
        <el-button type="primary" :loading="genLoading" @click="generate">生成思维导图</el-button>
      </el-empty>
    </div>

    <div v-if="state === 'generating'" class="empty-overlay">
      <el-skeleton :rows="3" animated style="width: 320px" />
      <p class="mw-caption">AI 正在提炼知识点层级，请稍候…</p>
    </div>

    <div v-if="state === 'error'" class="empty-overlay">
      <el-result status="error" :title="errorMsg">
        <template #extra>
          <el-button @click="load">重试</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { mapApi } from '@/api'
import { watchTask } from '@/utils/taskWatcher'
import type { Graph } from '@antv/g6'

const props = defineProps<{ kbId: string }>()

const router = useRouter()
const containerRef = ref<HTMLDivElement>()
const state = ref<'loading' | 'ready' | 'empty' | 'generating' | 'error'>('loading')
const errorMsg = ref('')
const genLoading = ref(false)

let graph: Graph | null = null
let stopWatcher: (() => void) | null = null

interface FlatNode {
  id: string
  parent_id: string | null
  title: string
  card_id: string | null
}

/** 平铺节点 → G6 树形数据（compactBox 布局入参） */
function toTree(nodes: FlatNode[]): object {
  const byId = new Map<string, Record<string, unknown> & { children?: object[] }>()
  let root: object | null = null
  for (const n of nodes) {
    byId.set(n.id, { id: n.id, title: n.title, card_id: n.card_id })
  }
  for (const n of nodes) {
    const self = byId.get(n.id)!
    if (n.parent_id && byId.has(n.parent_id)) {
      const parent = byId.get(n.parent_id) as { children?: object[] }
      parent.children = parent.children || []
      parent.children.push(self)
    } else if (n.parent_id === null) {
      root = self
    }
  }
  return root || { id: 'virtual-root', title: '（空导图）' }
}

async function render(nodes: FlatNode[]) {
  const el = containerRef.value
  if (!el) return
  if (graph) {
    graph.destroy()
    graph = null
  }
  const { Graph } = await import('@antv/g6')
  graph = new Graph({
    container: el,
    autoFit: 'view',
    data: toTree(nodes),
    // compactBox 树布局：根在左、层级向右舒展（ui-design.md §3.5）
    layout: {
      type: 'compactBox',
      direction: 'LR',
      getHeight: () => 36,
      getWidth: () => 150,
      getVGap: () => 14,
      getHGap: () => 70,
    },
    node: {
      style: {
        fill: '#ffffff',
        stroke: '#e5e6eb',
        lineWidth: 1,
        size: [150, 36],
        labelText: (d: Record<string, unknown>) => String(d.title ?? ''),
        labelPlacement: 'center',
        labelFill: '#1f2329',
        labelFontSize: 12,
        labelPadding: [0, 8],
        radius: 6,
      },
    },
    edge: {
      style: { stroke: '#c9cdd4', lineWidth: 1 },
    },
    behaviors: ['drag-canvas', 'zoom-canvas', 'collapse-expand'],
  })

  // 叶子节点点击跳转卡片详情（spec §5.5.1规则3 溯源）
  graph.on('node:click', (evt: unknown) => {
    const targetType = (evt as { targetType?: string }).targetType
    if (targetType && targetType !== 'node') return
    const nodeId = (evt as { target?: { id?: string } }).target?.id
    if (!nodeId) return
    const node = nodes.find((n) => n.id === nodeId)
    if (node?.card_id) router.push(`/card/${node.card_id}`)
  })

  await graph.render()
}

async function load() {
  state.value = 'loading'
  try {
    const data = await mapApi.getByKb(props.kbId)
    if (!data || data.nodes.length === 0) {
      state.value = 'empty'
      return
    }
    await render(data.nodes)
    state.value = 'ready'
  } catch {
    state.value = 'error'
    errorMsg.value = '导图加载失败'
  }
}

async function generate() {
  genLoading.value = true
  try {
    const { task_id } = await mapApi.generate(props.kbId)
    state.value = 'generating'
    stopWatcher?.()
    stopWatcher = watchTask(task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        genLoading.value = false
        if (status.status === 'done') {
          ElMessage.success('导图生成完成')
          void load()
        } else {
          state.value = 'error'
          errorMsg.value = status.error || '导图生成失败'
        }
      },
    })
  } finally {
    genLoading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  stopWatcher?.()
  graph?.destroy()
})
</script>

<style scoped>
.mindmap-canvas {
  position: relative;
  height: calc(100vh - var(--mw-topbar-height) - 140px);
  min-height: 480px;
  border: 1px solid var(--mw-border);
  border-radius: var(--mw-radius);
  background: var(--mw-bg-card);
  overflow: hidden;
}
.canvas-box {
  width: 100%;
  height: 100%;
}
.empty-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(250, 250, 250, 0.92);
}
</style>