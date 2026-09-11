<template>
  <div class="quiz-page">
    <!-- 进行中：先题目后揭示（spec §5.8.1规则6） -->
    <template v-if="state && state.progress === 'in_progress' && current">
      <div class="quiz-head">
        <span class="quiz-progress">第 {{ answeredCount + 1 }} / {{ state.total }} 题</span>
        <el-button link type="danger" size="small" @click="abandonQuiz">放弃测验</el-button>
      </div>
      <el-progress
        :percentage="Math.round((answeredCount / state.total) * 100)"
        :show-text="false"
        class="quiz-bar"
      />

      <div class="quiz-card mw-card">
        <div class="quiz-label">题目</div>
        <div class="quiz-question">{{ current.question }}</div>

        <template v-if="!revealed">
          <p class="mw-caption quiz-tip">先回忆作答，再揭示答案</p>
          <el-button type="primary" :loading="revealing" @click="reveal">显示答案</el-button>
        </template>

        <template v-else>
          <div class="quiz-label">正确答案</div>
          <div class="quiz-answer">{{ detail?.answer }}</div>
          <div class="quiz-label">错误原因解析</div>
          <div class="quiz-answer">{{ detail?.error_analysis }}</div>
          <div v-if="detail?.tags?.length" class="quiz-tags">
            <span v-for="t in detail.tags" :key="t" class="mw-tag">{{ t }}</span>
          </div>

          <div class="mark-row">
            <el-button type="danger" plain :loading="marking" @click="mark('still_not')">仍不会</el-button>
            <el-button type="success" :loading="marking" @click="mark('mastered')">已掌握</el-button>
          </div>
        </template>
      </div>
    </template>

    <!-- 汇总：完成或放弃 -->
    <template v-else-if="state">
      <div class="quiz-card mw-card summary">
        <el-result
          :icon="state.progress === 'done' ? 'success' : 'info'"
          :title="state.progress === 'done' ? '测验完成' : '测验已放弃'"
          :sub-title="summaryText"
        >
          <template #extra>
            <el-button type="primary" @click="backToList">返回错题本</el-button>
          </template>
        </el-result>
        <div v-if="state.marks.length" class="summary-marks">
          <div v-for="m in state.marks" :key="m.entry_id" class="mark-line">
            <span>{{ questionOf(m.entry_id) }}</span>
            <el-tag :type="m.mark === 'mastered' ? 'success' : 'danger'" size="small">
              {{ m.mark === 'mastered' ? '已掌握' : '仍不会' }}
            </el-tag>
          </div>
        </div>
      </div>
    </template>

    <el-empty v-else-if="loadFailed" description="测验记录不存在">
      <el-button type="primary" @click="backToList">返回错题本</el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mistakeApi, type MistakeItem, type QuizState } from '@/api'

const route = useRoute()
const router = useRouter()

const RESUME_KEY = 'mw_quiz_in_progress'

const quizId = computed(() => route.params.id as string)
const state = ref<QuizState | null>(null)
const detail = ref<MistakeItem | null>(null)
const revealed = ref(false)
const revealing = ref(false)
const marking = ref(false)
const loadFailed = ref(false)
/** 逐题标记期间暂存的题目文本（汇总页展示用） */
const questionCache = ref<Record<string, string>>({})

const answeredCount = computed(() => state.value?.marks.length ?? 0)
const current = computed(() => state.value?.pending[0] ?? null)
const masteredCount = computed(() => state.value?.marks.filter((m) => m.mark === 'mastered').length ?? 0)

const summaryText = computed(() => {
  if (!state.value) return ''
  return state.value.progress === 'done'
    ? `共 ${state.value.total} 题，已掌握 ${masteredCount.value} 题，待巩固 ${state.value.total - masteredCount.value} 题`
    : `已答 ${state.value.marks.length} 题（已掌握 ${masteredCount.value}），已提交的标记保持有效`
})

function questionOf(entryId: string): string {
  return questionCache.value[entryId] || '（题目内容）'
}

async function load() {
  loadFailed.value = false
  try {
    const s = await mistakeApi.quizState(quizId.value)
    state.value = s
    s.pending.forEach((p) => {
      questionCache.value[p.entry_id] = p.question
    })
    revealed.value = false
    detail.value = null
    if (s.progress !== 'in_progress') {
      localStorage.removeItem(RESUME_KEY)
    }
  } catch {
    loadFailed.value = true
  }
}

async function reveal() {
  if (!current.value) return
  revealing.value = true
  try {
    detail.value = await mistakeApi.get(current.value.entry_id)
    revealed.value = true
  } finally {
    revealing.value = false
  }
}

async function mark(mark: 'mastered' | 'still_not') {
  if (!current.value) return
  marking.value = true
  try {
    const result = await mistakeApi.quizAnswer(quizId.value, current.value.entry_id, mark)
    if (result.finished) {
      ElMessage.success('测验完成')
    }
    await load()
  } finally {
    marking.value = false
  }
}

async function abandonQuiz() {
  await ElMessageBox.confirm('放弃后已提交的标记不会回滚，确定放弃？', '放弃测验', { type: 'warning' })
  await mistakeApi.quizAbandon(quizId.value)
  localStorage.removeItem(RESUME_KEY)
  await load()
}

function backToList() {
  router.push('/workbench/study/mistakes')
}

onMounted(load)
</script>

<style scoped>
.quiz-page {
  max-width: 760px;
  margin: 0 auto;
  padding-top: 4px;
}
.quiz-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.quiz-progress {
  font-size: 13px;
  color: var(--mw-text-secondary);
}
.quiz-bar {
  margin-bottom: 20px;
}
.quiz-card {
  padding: 28px 32px;
}
.quiz-label {
  font-size: 12px;
  color: var(--mw-text-tertiary);
  margin-bottom: 6px;
}
.quiz-question {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.8;
  margin-bottom: 20px;
  white-space: pre-wrap;
}
.quiz-answer {
  font-size: 14px;
  line-height: 1.8;
  margin-bottom: 16px;
  white-space: pre-wrap;
}
.quiz-tip {
  margin: 4px 0 14px;
}
.quiz-tags {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
}
.mark-row {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
.summary-marks {
  margin-top: 8px;
}
.mark-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--mw-border);
  font-size: 13px;
}
</style>
