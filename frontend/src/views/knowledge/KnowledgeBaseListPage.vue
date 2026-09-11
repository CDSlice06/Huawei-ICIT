<template>
  <div class="kb-list-page">
    <!-- 顶部操作区（ui-design.md §3.3） -->
    <div class="toolbar">
      <el-button type="primary" @click="createDialog = true">+ 新建专题库</el-button>
    </div>

    <!-- 网格布局：每行3张专题库卡片（ui-design.md §3.3） -->
    <el-empty v-if="kbList.length === 0 && !loading" description="新建第一个专题库，开始沉淀你的知识">
      <el-button type="primary" @click="createDialog = true">新建专题库</el-button>
    </el-empty>

    <div class="kb-grid">
      <div v-for="kb in kbList" :key="kb.id" class="kb-card mw-card" @click="router.push(`/kb/${kb.id}`)">
        <div class="kb-name">{{ kb.name }}</div>
        <div class="mw-caption">{{ kb.card_count }} 条内容</div>
        <div class="kb-actions" @click.stop>
          <el-dropdown trigger="click" @command="handleCommand">
            <span class="more-btn">⋯</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :command="{ action: 'rename', kb }">重命名</el-dropdown-item>
                <el-dropdown-item :command="{ action: 'delete', kb }" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <!-- 新建/重命名弹窗 -->
    <el-dialog v-model="createDialog" :title="renameTarget ? '重命名专题库' : '新建专题库'" width="420px">
      <el-input v-model="newKbName" maxlength="50" show-word-limit placeholder="专题库名称（如：读书笔记、人生感悟集）" />
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveKb">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { kbApi, type KnowledgeBaseItem } from '@/api'

const router = useRouter()
const kbList = ref<KnowledgeBaseItem[]>([])
const loading = ref(false)
const createDialog = ref(false)
const newKbName = ref('')
const saving = ref(false)
const renameTarget = ref<KnowledgeBaseItem | null>(null)

async function load() {
  loading.value = true
  try {
    kbList.value = await kbApi.list()
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function saveKb() {
  const name = newKbName.value.trim()
  if (!name) return
  saving.value = true
  try {
    if (renameTarget.value) {
      await kbApi.rename(renameTarget.value.id, name)
      ElMessage.success('重命名成功')
    } else {
      await kbApi.create(name)
      ElMessage.success('创建成功')
    }
    createDialog.value = false
    newKbName.value = ''
    renameTarget.value = null
    await load()
  } finally {
    saving.value = false
  }
}

async function handleCommand(cmd: { action: string; kb: KnowledgeBaseItem }) {
  if (cmd.action === 'rename') {
    renameTarget.value = cmd.kb
    newKbName.value = cmd.kb.name
    createDialog.value = true
  } else if (cmd.action === 'delete') {
    // 删除二次确认：先获取级联规模明示数量（spec §5.4.3异常1）
    const info = await kbApi.deleteInfo(cmd.kb.id)
    await ElMessageBox.confirm(
      `该专题库下有 ${info.card_count} 条内容，删除后其卡片、导图与回顾计划将一并移除且不可恢复。确认删除？`,
      '删除专题库',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await kbApi.delete(cmd.kb.id)
    ElMessage.success('已删除')
    await load()
  }
}
</script>

<style scoped>
.toolbar {
  margin-bottom: 20px;
}
.kb-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.kb-card {
  padding: 22px 24px;
  cursor: pointer;
  position: relative;
  min-height: 110px;
}
.kb-name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}
.kb-actions {
  position: absolute;
  right: 14px;
  bottom: 10px;
}
.more-btn {
  cursor: pointer;
  color: var(--mw-text-tertiary);
  font-size: 18px;
  padding: 2px 6px;
  border-radius: 4px;
}
.more-btn:hover {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
}
</style>