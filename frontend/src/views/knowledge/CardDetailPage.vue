<template>
  <div class="card-detail-page" v-if="card">
    <!-- 左侧同库内容窄栏 + 右侧主内容区（ui-design.md §3.6） -->
    <div class="detail-row">
      <aside class="siblings-bar">
        <div class="mw-caption">同库内容</div>
        <div
          v-for="s in siblings"
          :key="s.id"
          class="sibling-item"
          :class="{ active: s.id === card.id }"
          @click="router.push(`/card/${s.id}`)"
        >
          {{ s.title }}
        </div>
      </aside>

      <section class="main-pane mw-card">
        <!-- 1. 大标题 + 类型标注 -->
        <div class="title-row">
          <h2>{{ card.title }}</h2>
          <span class="mw-tag">知识</span>
        </div>
        <p class="summary">{{ card.summary }}</p>

        <!-- 2. 核心内容区：要点列表（ui-design.md §3.6 知识型卡片） -->
        <div class="section">
          <h4>核心要点</h4>
          <ul>
            <li v-for="(p, i) in card.key_points" :key="i">{{ p }}</li>
          </ul>
        </div>

        <!-- 3. 回顾自测模块：默认隐藏答案，点击显示（ui-design.md §3.6） -->
        <div class="section">
          <h4>回顾自测</h4>
          <div v-for="(qa, i) in card.qa_pairs" :key="i" class="qa-block">
            <div class="qa-q">问：{{ qa.question }}</div>
            <template v-if="revealed.has(i)">
              <div class="qa-a">答：{{ qa.answer }}</div>
            </template>
            <el-button v-else size="small" text type="primary" @click="reveal(i)">
              显示内容
            </el-button>
          </div>
        </div>

        <!-- 4. 标签栏 + 来源溯源入口 -->
        <div class="footer-row">
          <div>
            <span v-for="t in card.tags" :key="t" class="mw-tag">{{ t }}</span>
          </div>
          <div class="actions">
            <el-link :underline="false" @click="showSource">查看来源</el-link>
            <el-link :underline="false" type="primary" @click="editDialog = true">编辑</el-link>
            <el-link :underline="false" type="danger" @click="restructDialog = true">重新生成</el-link>
          </div>
        </div>
        <div class="mw-caption next-review">下次回顾时间：{{ nextReviewHint }}</div>
      </section>
    </div>

    <!-- 编辑弹窗（五字段，要点/问答动态增删，tasks.md 10.4） -->
    <el-dialog v-model="editDialog" title="编辑内容" width="640px" top="6vh">
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="editForm.title" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="editForm.summary" maxlength="300" show-word-limit type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="核心要点">
          <div v-for="(_, i) in editForm.key_points" :key="i" class="row-input">
            <el-input v-model="editForm.key_points[i]" maxlength="200" />
            <el-button text type="danger" @click="editForm.key_points.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="editForm.key_points.push('')">+ 添加要点</el-button>
        </el-form-item>
        <el-form-item label="回顾自测问答">
          <div v-for="(qa, i) in editForm.qa_pairs" :key="i" class="qa-edit-row">
            <el-input v-model="qa.question" placeholder="问题" maxlength="200" />
            <el-input v-model="qa.answer" placeholder="答案" maxlength="500" />
            <el-button text type="danger" @click="editForm.qa_pairs.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="editForm.qa_pairs.push({ question: '', answer: '' })">
            + 添加问答
          </el-button>
        </el-form-item>
        <el-form-item label="标签（逗号分隔）">
          <el-input v-model="tagsText" placeholder="如：读书笔记, 心理学" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重新生成二次确认（明示覆盖，spec §5.3.3异常3） -->
    <el-dialog v-model="restructDialog" title="重新生成卡片" width="440px">
      <p>将基于来源素材重新生成知识卡片，<b>当前编辑内容将被覆盖</b>。确认继续？</p>
      <template #footer>
        <el-button @click="restructDialog = false">取消</el-button>
        <el-button type="primary" :loading="restructLoading" @click="doRestruct">确认重新生成</el-button>
      </template>
    </el-dialog>

    <!-- 来源溯源弹窗（spec §5.3.1规则2） -->
    <el-dialog v-model="sourceDialog" title="来源素材" width="560px">
      <p class="mw-caption">解析状态：{{ source?.parse_status }}</p>
      <pre class="source-pre">{{ source?.raw_content || source?.extracted_text }}</pre>
    </el-dialog>
  </div>

  <el-empty v-else-if="!loading" description="内容不存在" />
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assetApi, cardApi, type CardItem } from '@/api'
import { watchTask } from '@/utils/taskWatcher'

const route = useRoute()
const router = useRouter()
const cardId = computed(() => route.params.id as string)

const card = ref<CardItem | null>(null)
const siblings = ref<CardItem[]>([])
const loading = ref(true)
const revealed = ref(new Set<number>())
const editDialog = ref(false)
const saving = ref(false)
const sourceDialog = ref(false)
const source = ref<Record<string, unknown> | null>(null)
const restructDialog = ref(false)
const restructLoading = ref(false)

const editForm = reactive({
  title: '',
  summary: '',
  key_points: [] as string[],
  qa_pairs: [] as { question: string; answer: string }[],
})
const tagsText = ref('')

const nextReviewHint = computed(() => {
  if (!card.value) return '—'
  const days = card.value.review_interval_days || 1
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
})

function reveal(i: number) {
  revealed.value.add(i)
}

async function load() {
  loading.value = true
  try {
    card.value = await cardApi.get(cardId.value)
    siblings.value = (
      await cardApi.list({ kb_id: card.value.kb_id, page: 1, size: 50 }).catch(() => ({ items: [] }))
    ).items
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openEdit() {
  if (!card.value) return
  editForm.title = card.value.title
  editForm.summary = card.value.summary
  editForm.key_points = [...card.value.key_points]
  editForm.qa_pairs = card.value.qa_pairs.map((q) => ({ ...q }))
  tagsText.value = card.value.tags.join(', ')
  editDialog.value = true
}

// 编辑按钮点击直接打开弹窗
import { watch } from 'vue'
watch(editDialog, (v) => {
  if (v) openEdit()
})

async function saveEdit() {
  if (!card.value) return
  saving.value = true
  try {
    const tags = tagsText.value
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean)
      .slice(0, 10)
    card.value = await cardApi.update(card.value.id, {
      title: editForm.title,
      summary: editForm.summary,
      key_points: editForm.key_points.filter((p) => p.trim()),
      qa_pairs: editForm.qa_pairs.filter((q) => q.question.trim() && q.answer.trim()),
      tags,
    })
    editDialog.value = false
    ElMessage.success('保存成功')
  } finally {
    saving.value = false
  }
}

async function showSource() {
  if (!card.value) return
  source.value = await assetApi.get(card.value.asset_id)
  sourceDialog.value = true
}

async function doRestruct() {
  if (!card.value) return
  restructLoading.value = true
  try {
    const { task_id } = await assetApi.restruct(card.value.asset_id)
    restructDialog.value = false
    ElMessage.info('重新生成中，完成后请刷新查看')
    watchTask(task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        if (status.status === 'done') {
          ElMessage.success('卡片已重新生成')
          void load()
        } else {
          ElMessage.error(status.error || '重新生成失败')
        }
      },
    })
  } finally {
    restructLoading.value = false
  }
}
</script>

<style scoped>
.detail-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 20px;
  align-items: start;
}
.siblings-bar {
  border-right: 1px solid var(--mw-border);
  padding-right: 10px;
}
.sibling-item {
  padding: 7px 10px;
  font-size: 13px;
  color: var(--mw-text-secondary);
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sibling-item:hover {
  background: var(--mw-bg-hover);
}
.sibling-item.active {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
  font-weight: 600;
}
.main-pane {
  padding: 28px 32px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title-row h2 {
  margin: 0;
  font-size: 22px;
}
.summary {
  color: var(--mw-text-secondary);
  font-size: 14px;
  margin: 10px 0 24px;
}
.section {
  margin-bottom: 24px;
}
.section h4 {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--mw-text-tertiary);
  font-weight: 600;
}
.section ul {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
  font-size: 14px;
}
.qa-block {
  margin-bottom: 12px;
}
.qa-q {
  font-size: 14px;
  margin-bottom: 6px;
}
.qa-a {
  font-size: 14px;
  color: var(--mw-text-primary);
  background: var(--mw-bg-hover);
  padding: 8px 12px;
  border-radius: 6px;
}
.footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--mw-border);
  padding-top: 14px;
}
.actions {
  display: flex;
  gap: 14px;
}
.next-review {
  margin-top: 8px;
}
.row-input {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  width: 100%;
}
.qa-edit-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  margin-bottom: 8px;
  width: 100%;
}
.source-pre {
  background: var(--mw-bg-page);
  border: 1px solid var(--mw-border);
  border-radius: 6px;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow-y: auto;
  font-size: 13px;
}
</style>