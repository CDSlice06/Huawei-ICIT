<template>
  <div class="import-page">
    <div class="import-box mw-card">
      <h3>新建沉淀</h3>
      <p class="mw-subtitle">文字 / 文档 / 图片，AI 自动编织为结构化知识卡片</p>

      <!-- 录入方式切换（P1-2/P1-3） -->
      <el-radio-group v-model="mode" class="mode-switch" size="small">
        <el-radio-button value="text">粘贴文本</el-radio-button>
        <el-radio-button value="document">上传文档</el-radio-button>
        <el-radio-button value="image">上传图片</el-radio-button>
      </el-radio-group>

      <!-- 文本（P0） -->
      <template v-if="mode === 'text'">
        <el-input
          v-model="content"
          type="textarea"
          :rows="10"
          maxlength="5000"
          show-word-limit
          placeholder="粘贴你想沉淀的文字：读书笔记、课程内容、人生感悟、会议纪要……"
        />
      </template>

      <!-- 文档（P1-2）：PDF/Word/TXT/MD ≤20MB -->
      <template v-else-if="mode === 'document'">
        <div
          class="drop-area"
          :class="{ dragging: docDragging }"
          @dragover.prevent="docDragging = true"
          @dragleave="docDragging = false"
          @drop.prevent="onDropFile($event, 'document')"
        >
          <input
            ref="docInput"
            type="file"
            accept=".pdf,.docx,.txt,.md"
            class="file-input"
            @change="onPickFile($event, 'document')"
          />
          <template v-if="docFile">
            <div class="file-name">📄 {{ docFile.name }}（{{ (docFile.size / 1024 / 1024).toFixed(2) }}MB）</div>
            <el-button link size="small" @click="clearFile('document')">重新选择</el-button>
          </template>
          <template v-else>
            <div class="drop-hint">点击选择或拖入文件（PDF / Word / TXT / Markdown，≤20MB）</div>
            <div class="drop-hint mw-caption">扫描版 PDF 请改用「上传图片」</div>
          </template>
        </div>
      </template>

      <!-- 图片（P1-3）：JPG/PNG ≤10MB，上传前自动压缩 -->
      <template v-else>
        <div
          class="drop-area"
          :class="{ dragging: imgDragging }"
          @dragover.prevent="imgDragging = true"
          @dragleave="imgDragging = false"
          @drop.prevent="onDropFile($event, 'image')"
        >
          <input
            ref="imgInput"
            type="file"
            accept=".jpg,.jpeg,.png"
            class="file-input"
            @change="onPickFile($event, 'image')"
          />
          <template v-if="imgFile">
            <div class="file-name">
              🖼️ {{ imgFile.name }}（{{ (imgFile.size / 1024 / 1024).toFixed(2) }}MB）
              <el-tag v-if="compressed" size="small" type="success">已自动压缩</el-tag>
            </div>
            <el-button link size="small" @click="clearFile('image')">重新选择</el-button>
          </template>
          <template v-else>
            <div class="drop-hint">点击选择或拖入图片（JPG / PNG，≤10MB，自动压缩）</div>
            <div class="drop-hint mw-caption">手写笔记、板书照片、书页翻拍均可识别</div>
          </template>
        </div>
      </template>

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
        :disabled="!canSubmit || parsing"
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
        <el-button v-if="finishedType === 'error' && lastAsset" size="small" @click="retry">
          一键重试
        </el-button>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assetApi, kbApi, type AssetCreated, type KnowledgeBaseItem } from '@/api'
import { watchTask } from '@/utils/taskWatcher'
import { compressImage, uploadFile } from '@/utils/upload'

type Mode = 'text' | 'document' | 'image'

const route = useRoute()
const router = useRouter()

const mode = ref<Mode>('text')
const content = ref('')
const docFile = ref<File | null>(null)
const imgFile = ref<File | null>(null)
const compressed = ref(false)
const docDragging = ref(false)
const imgDragging = ref(false)
const docInput = ref<HTMLInputElement | null>(null)
const imgInput = ref<HTMLInputElement | null>(null)

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

const canSubmit = computed(() => {
  if (mode.value === 'text') return Boolean(content.value.trim())
  if (mode.value === 'document') return Boolean(docFile.value)
  return Boolean(imgFile.value)
})

onMounted(async () => {
  kbList.value = await kbApi.list().catch(() => [])
  // 记忆上次使用的知识库；支持 ?kb_id= 从库详情页跳入
  const fromQuery = route.query.kb_id as string | undefined
  const lastUsed = localStorage.getItem('mw_last_kb')
  kbId.value = fromQuery || lastUsed || ''
})

// ---------- 文件选择 ----------

function onPickFile(event: Event, kind: 'document' | 'image') {
  const input = event.target as HTMLInputElement
  if (input.files?.[0]) void acceptFile(input.files[0], kind)
  input.value = ''
}

function onDropFile(event: DragEvent, kind: 'document' | 'image') {
  docDragging.value = false
  imgDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) void acceptFile(file, kind)
}

async function acceptFile(file: File, kind: 'document' | 'image') {
  finished.value = false
  if (kind === 'document') {
    if (file.size > 20 * 1024 * 1024) {
      ElMessage.warning('文档超过20MB上限')
      return
    }
    docFile.value = file
  } else {
    if (file.size > 10 * 1024 * 1024) {
      ElMessage.warning('图片超过10MB上限')
      return
    }
    imgFile.value = file
    compressed.value = false
    imgFile.value = await compressImage(file)
    compressed.value = imgFile.value !== file
  }
}

function clearFile(kind: 'document' | 'image') {
  if (kind === 'document') docFile.value = null
  else imgFile.value = null
  finished.value = false
}

// ---------- 提交 ----------

async function submit() {
  submitting.value = true
  finished.value = false
  try {
    let created: AssetCreated
    if (mode.value === 'text') {
      created = await assetApi.importText(content.value.trim(), kbId.value || undefined)
    } else if (mode.value === 'document' && docFile.value) {
      const obsKey = await uploadFile(docFile.value, 'document')
      created = await assetApi.importDocument(obsKey, docFile.value.name, kbId.value || undefined)
    } else if (mode.value === 'image' && imgFile.value) {
      const obsKey = await uploadFile(imgFile.value, 'image')
      created = await assetApi.importImage(obsKey, kbId.value || undefined)
    } else {
      return
    }
    lastAsset.value = created
    lastTaskId.value = created.task_id
    if (kbId.value) localStorage.setItem('mw_last_kb', kbId.value)
    startWatch(() => (content.value = ''))
  } catch (err: unknown) {
    const body = (err as { message?: string }).message
    if (body?.includes('已有任务')) ElMessage.warning('已有任务解析中，请稍候')
  } finally {
    submitting.value = false
  }
}

function startWatch(onSuccess: () => void) {
  parsing.value = true
  stopWatcher?.()
  stopWatcher = watchTask(lastTaskId.value!, {
    onUpdate: () => {},
    onFinished: (status) => {
      parsing.value = false
      finished.value = true
      if (status.status === 'done') {
        finishedType.value = 'success'
        finishedTitle.value = '知识卡片编织完成'
        onSuccess()
      } else {
        finishedType.value = 'error'
        finishedTitle.value = status.error || '解析失败，素材已保留，可一键重试'
      }
    },
  })
}

async function retry() {
  if (!lastAsset.value) return
  const created = await assetApi.restruct(lastAsset.value.asset_id)
  lastTaskId.value = created.task_id
  finished.value = false
  startWatch(() => (content.value = ''))
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
.mode-switch {
  margin: 14px 0 16px;
}
.drop-area {
  position: relative;
  border: 1.5px dashed var(--mw-border);
  border-radius: 10px;
  padding: 36px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
}
.drop-area.dragging,
.drop-area:hover {
  border-color: var(--el-color-primary);
}
.drop-area .file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.drop-hint {
  font-size: 14px;
}
.file-name {
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
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
