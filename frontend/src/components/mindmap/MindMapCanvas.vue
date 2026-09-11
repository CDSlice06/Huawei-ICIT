<template>
  <div class="mindmap-canvas">
    <div ref="containerRef" class="canvas-box"></div>

    <!-- 编辑提示（手动编辑后可自由拖拽排版） -->
    <div v-if="state === 'ready'" class="edit-hint mw-caption">
      双击节点可编辑标题 / 调整父节点 / 增删节点；拖动节点可自由排版（自动保存）
    </div>

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

    <!-- 节点编辑弹窗（P1-6，spec §5.5.1规则4~7） -->
    <el-dialog v-model="editDialog" title="编辑节点" width="440px">
      <el-form label-position="top">
        <el-form-item label="节点标题">
          <el-input v-model="editForm.title" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="父节点（调整层级关系，禁止成环）">
          <el-select v-model="editForm.parentId" style="width: 100%">
            <el-option
              v-for="n in parentCandidates()"
              :key="n.id"
              :label="n.title"
              :value="n.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-popconfirm title="删除该节点？（仅叶子节点可删除）" @confirm="deleteNode">
          <template #reference>
            <el-button type="danger" plain style="float: left">删除节点</el-button>
          </template>
        </el-popconfirm>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingNode" @click="saveNodeEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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
let currentNodes: FlatNode[] = []

const editDialog = ref(false)
const savingNode = ref(false)
const editForm = reactive({ id: '', title: '', parentId: '' })

interface FlatNode {
  id: string
  parent_id: string | null
  title: string
  card_id: string | null
  pos_x: number | null
  pos_y: number | null
}

/** 是否为手动编排且带坐标 → 固定布局渲染（spec §6.4规则7） */
function hasManualPositions(nodes: FlatNode[]): boolean {
  return nodes.length > 0 && nodes.every((n) => n.pos_x !== null && n.pos_y !== null)
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

/** 平铺节点 → 固定坐标数据（手动编排模式） */
function toFixed(nodes: FlatNode[]): object {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      title: n.title,
      card_id: n.card_id,
      style: { x: n.pos_x as number, y: n.pos_y as number },
    })),
    edges: nodes
      .filter((n) => n.parent_id)
      .map((n) => ({ source: n.parent_id as string, target: n.id })),
  }
}

const NODE_STYLE = {
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
} as const

async function render(nodes: FlatNode[], manual: boolean) {
  const el = containerRef.value
  if (!el) return
  if (graph) {
    graph.destroy()
    graph = null
  }
  currentNodes = nodes
  const { Graph } = await import('@antv/g6')

  const options: Record<string, unknown> = {
    container: el,
    autoFit: 'view',
    node: { style: { ...NODE_STYLE } },
    edge: { style: { stroke: '#c9cdd4', lineWidth: 1 } },
    behaviors: ['drag-canvas', 'zoom-canvas', 'collapse-expand', 'drag-element'],
  }
  if (manual) {
    options.data = toFixed(nodes) // 自由坐标（手动编排后）
  } else {
    options.data = toTree(nodes)
    // compactBox 树布局：根在左、层级向右舒展（ui-design.md §3.5）
    options.layout = {
      type: 'compactBox',
      direction: 'LR',
      getHeight: () => 36,
      getWidth: () => 150,
      getVGap: () => 14,
      getHGap: () => 70,
    }
  }
  graph = new Graph(options as never)

  // 叶子节点单击跳转卡片详情（spec §5.5.1规则3 溯源）
  graph.on('node:click', (evt: unknown) => {
    const targetType = (evt as { targetType?: string }).targetType
    if (targetType && targetType !== 'node') return
    const nodeId = (evt as { target?: { id?: string } }).target?.id
    if (!nodeId) return
    const node = currentNodes.find((n) => n.id === nodeId)
    if (node?.card_id) router.push(`/card/${node.card_id}`)
  })

  // 双击进入节点编辑（标题/父节点/删除，P1-6）
  graph.on('node:dblclick', (evt: unknown) => {
    const nodeId = (evt as { target?: { id?: string } }).target?.id
    const node = currentNodes.find((n) => n.id === nodeId)
    if (!node) return
    editForm.id = node.id
    editForm.title = node.title
    editForm.parentId = node.parent_id || ''
    editDialog.value = true
  })

  // 拖拽结束：批量保存节点坐标 → 版本来源自动置"手动编辑"（spec §5.5.1规则7）
  graph.on('node:dragend', () => {
    if (manual) {
      void persistPositions()
      return
    }
    // 自动布局模式下首次拖拽：先整树转为固定坐标模式再保存
    void convertToManual()
  })

  await graph.render()
}

async function persistPositions() {
  if (!graph) return
  try {
    const data = (graph.getNodeData?.() ?? []) as { id: string; style?: { x?: number; y?: number } }[]
    const updates = data
      .filter((d) => typeof d.style?.x === 'number' && typeof d.style?.y === 'number')
      .map((d) => ({ id: d.id, pos_x: d.style!.x as number, pos_y: d.style!.y as number }))
    if (!updates.length) return
    await mapApi.updateNodes(props.kbId, { updates })
  } catch {
    /* 位置保存失败不打断浏览；下次拖拽会再次尝试 */
  }
}

async function convertToManual() {
  if (!graph) return
  try {
    const data = (graph.getNodeData?.() ?? []) as { id: string; style?: { x?: number; y?: number } }[]
    const updates = data
      .filter((d) => typeof d.style?.x === 'number' && typeof d.style?.y === 'number')
      .map((d) => ({ id: d.id, pos_x: d.style!.x as number, pos_y: d.style!.y as number }))
    if (!updates.length) return
    await mapApi.updateNodes(props.kbId, { updates })
    currentNodes = currentNodes.map((n) => {
      const u = updates.find((x) => x.id === n.id)
      return u ? { ...n, pos_x: u.pos_x, pos_y: u.pos_y } : n
    })
    await render(currentNodes, true) // 切换为自由坐标模式
  } catch {
    /* 忽略 */
  }
}

// ---------- 节点编辑弹窗 ----------

const parentCandidates = () => currentNodes.filter((n) => n.id !== editForm.id)

async function saveNodeEdit() {
  savingNode.value = true
  try {
    await mapApi.updateNodes(props.kbId, {
      updates: [
        {
          id: editForm.id,
          title: editForm.title,
          parent_id: editForm.parentId || null,
        },
      ],
    })
    ElMessage.success('已保存（版本来源：手动编辑）')
    editDialog.value = false
    await load()
  } finally {
    savingNode.value = false
  }
}

async function deleteNode() {
  try {
    await mapApi.updateNodes(props.kbId, { deletions: [editForm.id] })
    ElMessage.success('节点已删除')
    editDialog.value = false
    await load()
  } catch {
    /* 非叶子节点删除被后端拦截，提示已由拦截器展示 */
  }
}

async function load() {
  state.value = 'loading'
  try {
    const data = await mapApi.getByKb(props.kbId)
    if (!data || data.nodes.length === 0) {
      state.value = 'empty'
      return
    }
    await render(data.nodes, hasManualPositions(data.nodes))
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
.edit-hint {
  position: absolute;
  left: 12px;
  bottom: 10px;
  background: rgba(255, 255, 255, 0.9);
  padding: 4px 10px;
  border-radius: 6px;
  pointer-events: none;
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
