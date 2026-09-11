<template>
  <div class="puzzle-page">
    <div class="detail-header">
      <el-button :icon="ArrowLeft" text @click="router.back()" />
      <h3 class="mw-title">拼图回顾</h3>
    </div>

    <!-- 逐层拼装（固定布局简化模式，spec §5.5.1规则8~10） -->
    <template v-if="puzzle && puzzle.progress === 'in_progress'">
      <p class="mw-caption">
        依据你对「{{ kbName }}」知识结构的记忆，逐层还原导图的父子关系：
        先选出根节点，再为每个节点指定上级。
      </p>

      <div class="step-row mw-card">
        <span class="step-label">第 1 步 · 根节点</span>
        <el-select v-model="rootId" placeholder="选择这张导图的根节点" style="width: 320px">
          <el-option v-for="n in puzzle.nodes" :key="n.id" :label="n.title" :value="n.id" />
        </el-select>
      </div>

      <template v-if="rootId">
        <div class="step-row mw-card" v-for="n in pendingNodes" :key="n.id">
          <span class="step-label">「{{ n.title }}」的上级</span>
          <el-select v-model="assignments[n.id]" placeholder="选择上级节点" style="width: 320px">
            <el-option
              v-for="p in placedNodes.filter((x) => x.id !== n.id)"
              :key="p.id"
              :label="p.title"
              :value="p.id"
            />
          </el-select>
        </div>
      </template>

      <div class="submit-row">
        <el-button
          type="primary"
          size="large"
          :disabled="!canSubmit"
          :loading="submitting"
          @click="submitPuzzle"
        >
          提交拼装
        </el-button>
      </div>
    </template>

    <!-- 结果 -->
    <template v-else-if="puzzle && puzzle.progress === 'done'">
      <div class="result-card mw-card">
        <el-result
          :icon="puzzle.result && puzzle.result.correct === puzzle.result.total ? 'success' : 'warning'"
          :title="`拼装正确率 ${puzzle.result ? Math.round((puzzle.result.correct / puzzle.result.total) * 100) : 0}%`"
          :sub-title="`正确 ${puzzle.result?.correct ?? 0} / ${puzzle.result?.total ?? 0} 个节点（判定依据：与原导图父子关系一致性）`"
        >
          <template #extra>
            <el-button type="primary" @click="restart">再试一次</el-button>
            <el-button @click="router.push(`/kb/${route.params.id}`)">返回导图</el-button>
          </template>
        </el-result>
      </div>
    </template>

    <el-empty v-else-if="loadFailed" description="导图不存在或节点过少，无法拼图" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { kbApi, puzzleApi, type PuzzleView } from '@/api'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.id as string)
const kbName = ref('')
const puzzle = ref<PuzzleView | null>(null)
const loadFailed = ref(false)
const submitting = ref(false)

const rootId = ref('')
const assignments = reactive<Record<string, string>>({})

const placedNodes = computed(() => {
  const placed = puzzle.value?.nodes.filter((n) => n.id === rootId.value) ?? []
  // 已指定上级的节点也可作为他人的上级（逐层向下拼装）
  for (const n of puzzle.value?.nodes ?? []) {
    if (assignments[n.id]) placed.push(n)
  }
  return placed
})

const pendingNodes = computed(() =>
  (puzzle.value?.nodes ?? []).filter((n) => n.id !== rootId.value && !assignments[n.id]),
)

const canSubmit = computed(() => {
  if (!puzzle.value || !rootId.value) return false
  return puzzle.value.nodes.every((n) => n.id === rootId.value || assignments[n.id])
})

async function start() {
  loadFailed.value = false
  try {
    puzzle.value = await puzzleApi.create(kbId.value)
    rootId.value = ''
    Object.keys(assignments).forEach((k) => delete assignments[k])
  } catch {
    loadFailed.value = true
  }
}

async function restart() {
  await start()
}

async function submitPuzzle() {
  if (!puzzle.value) return
  submitting.value = true
  try {
    const result = await puzzleApi.submit(
      puzzle.value.puzzle_id,
      Object.fromEntries(puzzle.value.nodes.map((n) => [n.id, n.id === rootId.value ? null : assignments[n.id] || null])),
    )
    ElMessage.success(`拼装完成：正确 ${result.correct}/${result.total}`)
    puzzle.value = {
      ...puzzle.value,
      progress: 'done',
      result: { correct: result.correct, total: result.total, details: result.details },
      completed_at: result.completed_at,
    }
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  kbName.value = (await kbApi.list().catch(() => [])).find((k) => k.id === kbId.value)?.name || '知识库'
  await start()
})
</script>

<style scoped>
.puzzle-page {
  max-width: 720px;
  margin: 0 auto;
}
.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.step-row {
  padding: 14px 20px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.step-label {
  font-size: 14px;
  min-width: 180px;
}
.submit-row {
  margin-top: 20px;
  text-align: center;
}
.result-card {
  padding: 20px;
}
</style>
