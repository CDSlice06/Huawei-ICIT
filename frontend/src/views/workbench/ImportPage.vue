<template>
  <div class="import-page">
    <div class="import-box mw-card">
      <h3>新建沉淀</h3>
      <p class="mw-subtitle">粘贴文字，AI 自动编织为结构化知识卡片</p>

      <el-input
        v-model="content"
        type="textarea"
        :rows="10"
        maxlength="5000"
        show-word-limit
        placeholder="粘贴你想沉淀的文字：读书笔记、课程内容、人生感悟、会议纪要……"
      />

      <div class="kb-select">
        <span class="mw-subtitle">沉淀到：</span>
        <el-select v-model="kbId" placeholder="默认知识库" style="width: 240px" clearable>
          <el-option
            v-for="kb in kbList"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </div>

      <el-button
        type="primary"
        size="large"
        class="submit-btn"
        :loading="submitting"
        :disabled="!content.trim() || parsing"
        @click="submit"
      >
        一键沉淀
      </el-button>

      <!-- 解析状态流（SSE+轮询降级，tasks.md 10.3） -->
      <div v-if="parsing" class="parsing-status">
        <el-skeleton :rows="3" animated />
        <p class="mw-caption">AI 正在编织你的知识卡片，可离开此页面稍后回来…</p>
      </div>

      <el-alert
        v-if="finished"
        :title="finishedTitle"
        :type="finishedType"
        show-icon
        :closable="false"
        style="margin-top: 16px"
      >
        <el-button v-if="finishedType === 'success'" size="small" @click="viewCards">
          查看卡片
        </el-button>
        <el-button v-if="finishedType === 'error' && lastTaskId" size="small" @click="retry">
          一键重试
        </el-button>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assetApi, kbApi, type AssetCreated, type KnowledgeBaseItem } from '@/api'
import { watchTask } from '@/utils/taskWatcher'

const route = useRoute()
const router = useRouter()

const content = ref('')
const kbId = ref<string>('')
const kbList = ref<KnowledgeBaseItem[]>([])
const submitting = ref(false)
const parsing = ref(false)
const finished = ref(false)
const finishedType = ref<'success' | 'error'>('success')
const finishedTitle = ref('')
const lastTaskId = ref<string | null>(null)
const lastAsset = ref<AssetCreated | null>(null)
let stopWatcher: (() => void) | null = null

onMounted(async () => {
  kbList.value = await kbApi.list().catch(() => [])
  // 记忆上次使用的知识库；支持 ?kb_id= 从库详情页跳入
  const fromQuery = route.query.kb_id as string | undefined
  const lastUsed = localStorage.getItem('mw_last_kb')
  kbId.value = fromQuery || lastUsed || ''
})

async function submit() {
  submitting.value = true
  finished.value = false
  try {
    const created = await assetApi.importText(content.value.trim(), kbId.value || undefined)
    lastAsset.value = created
    lastTaskId.value = created.task_id
    if (kbId.value) localStorage.setItem('mw_last_kb', kbId.value)
    parsing.value = true
    stopWatcher?.()
    stopWatcher = watchTask(created.task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        parsing.value = false
        finished.value = true
        if (status.status === 'done') {
          finishedType.value = 'success'
          finishedTitle.value = '知识卡片编织完成'
          content.value = ''
        } else {
          finishedType.value = 'error'
          finishedTitle.value = status.error || '解析失败，素材已保留，可一键重试'
        }
      },
    })
  } catch (err: unknown) {
    const body = (err as { message?: string }).message
    if (body?.includes('已有任务')) ElMessage.warning('已有任务解析中，请稍候')
  } finally {
    submitting.value = false
  }
}

async function retry() {
  if (!lastAsset.value) return
  const created = await assetApi.restruct(lastAsset.value.asset_id)
  lastTaskId.value = created.task_id
  finished.value = false
  parsing.value = true
  stopWatcher?.()
  stopWatcher = watchTask(created.task_id, {
    onUpdate: () => {},
    onFinished: (status) => {
      parsing.value = false
      finished.value = true
      finishedType.value = status.status === 'done' ? 'success' : 'error'
      finishedTitle.value =
        status.status === 'done' ? '知识卡片编织完成' : status.error || '解析失败'
      if (status.status === 'done') content.value = ''
    },
  })
}

function viewCards() {
  router.push('/workbench/knowledge-bases')
}
</script>

<style scoped>
.import-page {
  max-width: 860px;
  margin: 0 auto;
}
.import-box {
  padding: 28px 32px;
}
.import-box h3 {
  margin: 0 0 6px;
  font-size: 18px;
}
.kb-select {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 20px;
}
.submit-btn {
  width: 100%;
}
.parsing-status {
  margin-top: 20px;
}
</style>