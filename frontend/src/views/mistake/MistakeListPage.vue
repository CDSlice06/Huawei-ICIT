<template>
  <div class="mistake-page">
    <!-- 页头：筛选 + 录入/测验入口 -->
    <div class="page-header">
      <el-radio-group v-model="masteryFilter" size="small" @change="load">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="unmastered">未掌握</el-radio-button>
        <el-radio-button value="mastered">已掌握</el-radio-button>
      </el-radio-group>
      <div class="header-actions">
        <el-button size="small" @click="quizDialog = true">发起测验</el-button>
        <el-button type="primary" size="small" @click="openImportDialog">录入错题</el-button>
      </div>
    </div>

    <!-- 未完成测验续答横幅（§5.8.3异常4 中断恢复） -->
    <el-alert v-if="resumeQuiz" type="warning" :closable="false" class="resume-banner">
      <template #title>
        有一场未完成的测验（已答 {{ resumeQuiz.marks.length }}/{{ resumeQuiz.total }} 题）
        <el-button link type="primary" size="small" @click="goQuiz(resumeQuiz.quiz_id)">继续作答</el-button>
        <el-button link size="small" @click="discardResume">放弃</el-button>
      </template>
    </el-alert>

    <!-- 错题列表 -->
    <el-empty v-if="items.length === 0 && !loading" description="错题本暂无条目，点击「录入错题」开始沉淀" />
    <div v-else class="mistake-list" v-loading="loading">
      <div v-for="m in items" :key="m.id" class="mistake-card mw-card">
        <div class="card-head">
          <el-tag :type="m.mastery === 'mastered' ? 'success' : 'danger'" size="small">
            {{ m.mastery === 'mastered' ? '已掌握' : '未掌握' }}
          </el-tag>
          <el-tag size="small" type="info">{{ m.source_type === 'image' ? '图片' : '文本' }}</el-tag>
          <span v-for="t in m.tags.slice(0, 3)" :key="t" class="mw-tag">{{ t }}</span>
          <span class="card-time">{{ m.created_at.slice(0, 10) }}</span>
        </div>

        <!-- 解析中/失败态 -->
        <template v-if="m.parse_status !== 'done'">
          <div class="card-question" v-if="m.parse_status === 'parsing'">
            AI 解析中…
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>
          <template v-else>
            <div class="card-question failed">解析失败，原文已保留</div>
            <div class="card-actions">
              <el-button size="small" type="primary" :loading="m._retrying" @click="retryParse(m)">
                一键重试
              </el-button>
              <el-button size="small" @click="openEditDialog(m)">手动补全</el-button>
              <el-button size="small" type="danger" plain @click="confirmDelete(m)">删除</el-button>
            </div>
          </template>
        </template>

        <!-- 正常态：题目（答案揭示在详情/测验中） -->
        <template v-else>
          <div class="card-question">{{ m.question }}</div>
          <div class="card-actions">
            <el-button size="small" @click="openEditDialog(m)">编辑</el-button>
            <el-button size="small" @click="toggleMastery(m)">
              {{ m.mastery === 'mastered' ? '重置为未掌握' : '标记已掌握' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="confirmDelete(m)">删除</el-button>
          </div>
        </template>
      </div>
    </div>

    <!-- 录入弹窗：一键零配置（spec §5.8.1规则1） -->
    <el-dialog v-model="importDialog" title="录入错题" width="520px">
      <el-input
        v-model="importContent"
        type="textarea"
        :rows="6"
        maxlength="5000"
        show-word-limit
        placeholder="粘贴错题内容（题干、你的作答、正确答案等，AI 将解析出题目/答案/错因）"
      />
      <p class="mw-caption">
        图片录入需华为云 OBS 直传能力（P1-3）开通后可用，当前请使用文本描述
      </p>
      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!importContent.trim()" :loading="importing" @click="submitImport">
          一键录入
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗（§5.8.1规则3） -->
    <el-dialog v-model="editDialog" title="编辑错题" width="560px">
      <el-form label-position="top">
        <el-form-item label="题目内容">
          <el-input v-model="editForm.question" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item label="正确答案">
          <el-input v-model="editForm.answer" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item label="错误原因解析">
          <el-input v-model="editForm.error_analysis" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item label="标签（回车添加，最多10个）">
          <el-input v-model="tagInput" placeholder="输入标签后回车" @keydown.enter.prevent="addTag" />
          <div class="tag-row">
            <el-tag
              v-for="t in editForm.tags"
              :key="t"
              closable
              size="small"
              @close="editForm.tags = editForm.tags.filter((x) => x !== t)"
            >
              {{ t }}
            </el-tag>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 发起测验弹窗（spec §5.8.1规则5） -->
    <el-dialog v-model="quizDialog" title="发起错题测验" width="440px">
      <el-form label-position="top">
        <el-form-item label="抽取策略">
          <el-radio-group v-model="quizForm.strategy">
            <el-radio value="sequential">按录入顺序</el-radio>
            <el-radio value="random">随机抽取</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="抽取数量">
          <el-input-number v-model="quizForm.count" :min="1" :max="50" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="quizForm.includeMastered">将「已掌握」条目纳入抽取范围</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="quizDialog = false">取消</el-button>
        <el-button type="primary" :loading="startingQuiz" @click="startQuiz">开始测验</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { mistakeApi, type MistakeItem, type QuizState } from '@/api'
import { watchTask } from '@/utils/taskWatcher'

const router = useRouter()

const RESUME_KEY = 'mw_quiz_in_progress'

const items = ref<(MistakeItem & { _retrying?: boolean })[]>([])
const loading = ref(false)
const masteryFilter = ref<'all' | 'unmastered' | 'mastered'>('all')

const importDialog = ref(false)
const importContent = ref('')
const importing = ref(false)

const editDialog = ref(false)
const saving = ref(false)
const tagInput = ref('')
const editForm = reactive({
  id: '',
  question: '',
  answer: '',
  error_analysis: '',
  tags: [] as string[],
})

const quizDialog = ref(false)
const startingQuiz = ref(false)
const quizForm = reactive({
  strategy: 'sequential' as 'sequential' | 'random',
  count: 10,
  includeMastered: false,
})

const resumeQuiz = ref<QuizState | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await mistakeApi.list({
      mastery: masteryFilter.value,
      page: 1,
      size: 100,
    })
    items.value = res.items
  } finally {
    loading.value = false
  }
}

async function checkResume() {
  const quizId = localStorage.getItem(RESUME_KEY)
  if (!quizId) return
  try {
    const state = await mistakeApi.quizState(quizId)
    if (state.progress === 'in_progress') {
      resumeQuiz.value = state
    } else {
      localStorage.removeItem(RESUME_KEY)
    }
  } catch {
    localStorage.removeItem(RESUME_KEY)
  }
}

function goQuiz(quizId: string) {
  router.push(`/workbench/study/mistakes/quiz/${quizId}`)
}

async function discardResume() {
  if (!resumeQuiz.value) return
  await ElMessageBox.confirm('放弃后已提交的标记不会回滚，确定放弃？', '放弃测验', { type: 'warning' })
  await mistakeApi.quizAbandon(resumeQuiz.value.quiz_id)
  localStorage.removeItem(RESUME_KEY)
  resumeQuiz.value = null
}

// ---------- 录入 ----------

function openImportDialog() {
  importContent.value = ''
  importDialog.value = true
}

async function submitImport() {
  importing.value = true
  try {
    const { task_id } = await mistakeApi.importText(importContent.value.trim())
    importDialog.value = false
    ElMessage.success('已提交，AI 解析中')
    watchTask(task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        if (status.status === 'done') {
          ElMessage.success('错题解析完成')
        } else {
          ElMessage.error(status.error || '解析失败，可在列表中一键重试')
        }
        void load()
      },
    })
    void load()
  } finally {
    importing.value = false
  }
}

async function retryParse(m: MistakeItem & { _retrying?: boolean }) {
  m._retrying = true
  try {
    const { task_id } = await mistakeApi.reparse(m.id)
    watchTask(task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        if (status.status !== 'done') ElMessage.error(status.error || '重试解析仍失败')
        void load()
      },
    })
  } finally {
    m._retrying = false
  }
}

// ---------- 编辑 / 删除 / 掌握状态 ----------

function openEditDialog(m: MistakeItem) {
  editForm.id = m.id
  editForm.question = m.question
  editForm.answer = m.answer
  editForm.error_analysis = m.error_analysis
  editForm.tags = [...m.tags]
  editDialog.value = true
}

function addTag() {
  const t = tagInput.value.trim()
  if (!t) return
  if (t.length > 20) {
    ElMessage.warning('标签不超过20字符')
    return
  }
  if (editForm.tags.length >= 10) {
    ElMessage.warning('标签最多10个')
    return
  }
  if (!editForm.tags.includes(t)) editForm.tags.push(t)
  tagInput.value = ''
}

async function saveEdit() {
  saving.value = true
  try {
    await mistakeApi.update(editForm.id, {
      question: editForm.question,
      answer: editForm.answer,
      error_analysis: editForm.error_analysis,
      tags: editForm.tags,
    })
    ElMessage.success('已保存')
    editDialog.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function confirmDelete(m: MistakeItem) {
  await ElMessageBox.confirm('删除后该条目将从错题本与测验抽取范围中移除，确定删除？', '删除错题', {
    type: 'warning',
  })
  await mistakeApi.remove(m.id)
  ElMessage.success('已删除')
  await load()
}

async function toggleMastery(m: MistakeItem) {
  const target = m.mastery === 'mastered' ? 'unmastered' : 'mastered'
  await mistakeApi.setMastery(m.id, target)
  m.mastery = target
}

// ---------- 测验 ----------

async function startQuiz() {
  startingQuiz.value = true
  try {
    const res = await mistakeApi.startQuiz({
      strategy: quizForm.strategy,
      count: quizForm.count,
      scope: quizForm.includeMastered ? 'all' : 'unmastered',
    })
    localStorage.setItem(RESUME_KEY, res.quiz_id)
    quizDialog.value = false
    goQuiz(res.quiz_id)
  } finally {
    startingQuiz.value = false
  }
}

onMounted(() => {
  void load()
  void checkResume()
})
</script>

<style scoped>
.mistake-page {
  padding-top: 4px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-actions {
  display: flex;
  gap: 10px;
}
.resume-banner {
  margin-bottom: 16px;
}
.mistake-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mistake-card {
  padding: 16px 20px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.card-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--mw-text-tertiary);
}
.card-question {
  font-size: 14px;
  line-height: 1.7;
  margin-bottom: 10px;
  white-space: pre-wrap;
}
.card-question.failed {
  color: var(--el-color-danger);
}
.card-actions {
  display: flex;
  gap: 8px;
}
.tag-row {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
