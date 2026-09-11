<template>
  <div class="forum-page">
    <div class="forum-header">
      <el-radio-group v-model="tab" size="small">
        <el-radio-button value="all">分享广场</el-radio-button>
        <el-radio-button value="mine">我的分享</el-radio-button>
      </el-radio-group>
      <el-button v-if="tab === 'mine'" type="primary" size="small" @click="shareDialog = true">
        分享知识库
      </el-button>
    </div>

    <!-- 分享广场（全体登录用户可见，spec §5.7.1规则5） -->
    <template v-if="tab === 'all'">
      <el-empty v-if="shares.length === 0 && !loading" description="还没有人分享，去「我的分享」成为第一个分享者" />
      <div
        v-for="item in shares"
        :key="item.id"
        class="share-card mw-card"
        @click="router.push(`/workbench/forum/${item.id}`)"
      >
        <div class="share-title">{{ item.title }}</div>
        <div class="share-meta">
          <span>{{ item.sharer_email }}</span>
          <span>{{ item.card_count }} 张卡片</span>
          <span class="mw-caption">分享于 {{ item.shared_at.slice(0, 10) }}</span>
        </div>
      </div>
    </template>

    <!-- 我的分享（管理：更新/取消，spec §5.7.1规则3~4） -->
    <template v-else>
      <el-empty v-if="mine.length === 0 && !loading" description="还没有分享记录" />
      <div v-for="item in mine" :key="item.id" class="share-card mw-card">
        <div class="share-title" @click="item.status === 'shared' && router.push(`/workbench/forum/${item.id}`)">
          {{ item.title }}
          <el-tag v-if="item.status === 'cancelled'" size="small" type="info">已取消</el-tag>
        </div>
        <div class="share-meta">
          <span>{{ item.card_count }} 张卡片</span>
          <span class="mw-caption">快照更新于 {{ item.updated_at.slice(0, 10) }}</span>
        </div>
        <div v-if="item.status === 'shared'" class="share-actions">
          <el-button size="small" @click="confirmUpdate(item)">更新分享</el-button>
          <el-button size="small" type="danger" plain @click="confirmCancel(item)">取消分享</el-button>
        </div>
      </div>
    </template>

    <!-- 分享知识库弹窗（spec §5.7.1规则1） -->
    <el-dialog v-model="shareDialog" title="分享知识库到论坛" width="440px">
      <el-select v-model="shareKbId" placeholder="选择要分享的知识库" style="width: 100%">
        <el-option v-for="kb in shareableKbs" :key="kb.id" :label="`${kb.name}（${kb.card_count} 张卡片）`" :value="kb.id" />
      </el-select>
      <p class="mw-caption">分享将生成当前内容的只读快照，后续编辑不会自动同步</p>
      <template #footer>
        <el-button @click="shareDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!shareKbId" :loading="sharing" @click="doShare">确认分享</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { forumApi, kbApi, type ShareListItem } from '@/api'

const router = useRouter()

const tab = ref<'all' | 'mine'>('all')
const shares = ref<ShareListItem[]>([])
const mine = ref<ShareListItem[]>([])
const loading = ref(false)

const shareDialog = ref(false)
const sharing = ref(false)
const shareKbId = ref('')

const shareableKbs = ref<{ id: string; name: string; card_count: number }[]>([])

async function load() {
  loading.value = true
  try {
    const [all, mineRes] = await Promise.all([
      forumApi.list().catch(() => ({ items: [] })),
      forumApi.mine().catch(() => ({ items: [] })),
    ])
    shares.value = all.items
    mine.value = mineRes.items
  } finally {
    loading.value = false
  }
}

async function doShare() {
  sharing.value = true
  try {
    await forumApi.share(shareKbId.value)
    ElMessage.success('分享成功，论坛可见')
    shareDialog.value = false
    shareKbId.value = ''
    await load()
  } finally {
    sharing.value = false
  }
}

async function confirmUpdate(item: ShareListItem) {
  await ElMessageBox.confirm('旧快照将被原库最新内容覆盖，确定更新？', '更新分享', { type: 'warning' })
  await forumApi.update(item.id)
  ElMessage.success('快照已更新')
  await load()
}

async function confirmCancel(item: ShareListItem) {
  await ElMessageBox.confirm('取消后论坛将立即下线该条目，原库数据不受影响', '取消分享', { type: 'warning' })
  await forumApi.cancel(item.id)
  ElMessage.success('已取消分享')
  await load()
}

onMounted(async () => {
  await load()
  // 可分享的知识库：本人名下含卡片的库
  const kbs = await kbApi.list().catch(() => [])
  shareableKbs.value = kbs.filter((k) => k.card_count > 0)
})
</script>

<style scoped>
.forum-page {
  max-width: 860px;
  margin: 0 auto;
}
.forum-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}
.share-card {
  padding: 16px 20px;
  margin-bottom: 12px;
  cursor: pointer;
}
.share-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.share-meta {
  display: flex;
  gap: 14px;
  font-size: 13px;
  color: var(--mw-text-secondary);
}
.share-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
</style>
