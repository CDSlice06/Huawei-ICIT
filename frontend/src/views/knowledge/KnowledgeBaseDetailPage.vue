<template>
  <div class="kb-detail-page">
    <!-- 顶部导航栏：库名+视图切换+操作（ui-design.md §3.4） -->
    <div class="detail-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" text @click="router.push('/workbench/knowledge-bases')" />
        <h3 class="kb-title">{{ kbName }}</h3>
      </div>
      <div class="header-right">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="cards">卡片视图</el-radio-button>
          <el-radio-button value="map">思维导图</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="genLoading" @click="generateMap">生成导图</el-button>
      </div>
    </div>

    <template v-if="viewMode === 'cards'">
      <!-- 左侧窄标签筛选栏 + 右侧卡片网格（ui-design.md §3.4） -->
      <div class="content-row">
        <aside class="tag-bar">
          <div
            class="tag-item"
            :class="{ active: !selectedTag }"
            @click="selectedTag = ''"
          >
            全部
          </div>
          <div
            v-for="t in allTags"
            :key="t"
            class="tag-item"
            :class="{ active: selectedTag === t }"
            @click="selectedTag = t"
          >
            {{ t }}
          </div>
        </aside>

        <section class="cards-area">
          <el-empty
            v-if="filteredCards.length === 0 && !loading"
            description="还没有内容，去「新建沉淀」导入"
          >
            <el-button type="primary" @click="router.push({ path: '/workbench/import', query: { kb_id: kbId } })">
              去沉淀
            </el-button>
          </el-empty>
          <div class="card-grid">
            <div
              v-for="card in filteredCards"
              :key="card.id"
              class="content-card mw-card"
              @click="router.push(`/card/${card.id}`)"
            >
              <div class="card-top-row">
                <div class="card-title">{{ card.title }}</div>
                <el-button
                  class="card-move-btn"
                  text
                  size="small"
                  @click.stop="openMoveDialog(card)"
                >
                  移动
                </el-button>
              </div>
              <div class="card-summary">{{ card.summary }}</div>
              <div class="card-tags">
                <span v-for="t in card.tags.slice(0, 4)" :key="t" class="mw-tag">{{ t }}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </template>

    <template v-else>
      <!-- 思维导图内嵌视图（复用导图组件，tasks.md 10.5） -->
      <MindMapCanvas :kb-id="kbId" />
    </template>

    <!-- 导图生成进行中提示 -->
    <el-dialog v-model="genDialog" title="导图生成中" width="360px" :show-close="false">
      <el-skeleton :rows="3" animated />
      <p class="mw-caption">AI 正在提炼知识点层级，完成后自动刷新…</p>
    </el-dialog>

    <!-- 移动卡片至其他知识库（tasks.md 10.4，spec §5.4.1规则2） -->
    <el-dialog v-model="moveDialog" title="移动至其他知识库" width="420px">
      <p class="mw-caption">「{{ moveCard?.title }}」将移动到：</p>
      <el-select v-model="moveTargetKb" placeholder="选择目标知识库" style="width: 100%">
        <el-option
          v-for="kb in otherKbs"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="moveDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!moveTargetKb" :loading="moving" @click="confirmMove">
          确定移动
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { cardApi, kbApi, mapApi, type CardItem } from '@/api'
import { watchTask } from '@/utils/taskWatcher'
import MindMapCanvas from '@/components/mindmap/MindMapCanvas.vue'

const route = useRoute()
const router = useRouter()
const kbId = computed(() => route.params.id as string)

const kbName = ref('')
const kbList = ref<{ id: string; name: string }[]>([])
const cards = ref<CardItem[]>([])
const loading = ref(false)
const viewMode = ref<'cards' | 'map'>('cards')
const selectedTag = ref('')
const genLoading = ref(false)
const genDialog = ref(false)

const allTags = computed(() => {
  const set = new Set<string>()
  cards.value.forEach((c) => c.tags.forEach((t) => set.add(t)))
  return Array.from(set)
})

const filteredCards = computed(() =>
  selectedTag.value ? cards.value.filter((c) => c.tags.includes(selectedTag.value)) : cards.value,
)

async function load() {
  loading.value = true
  try {
    const [kbs, cardList] = await Promise.all([
      kbApi.list().catch(() => []),
      cardApi.list({ kb_id: kbId.value, page: 1, size: 100 }).catch(() => ({ items: [], total: 0 })),
    ])
    kbList.value = kbs
    kbName.value = kbs.find((k) => k.id === kbId.value)?.name || '专题库'
    cards.value = cardList.items
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(kbId, load)

async function generateMap() {
  genLoading.value = true
  try {
    const { task_id } = await mapApi.generate(kbId.value)
    genDialog.value = true
    watchTask(task_id, {
      onUpdate: () => {},
      onFinished: (status) => {
        genDialog.value = false
        if (status.status === 'done') {
          ElMessage.success('导图生成完成')
          viewMode.value = 'map'
        } else {
          ElMessage.error(status.error || '导图生成失败')
        }
      },
    })
  } finally {
    genLoading.value = false
  }
}

// ---------- 卡片移动（tasks.md 10.4） ----------
const moveDialog = ref(false)
const moving = ref(false)
const moveCard = ref<CardItem | null>(null)
const moveTargetKb = ref('')

const otherKbs = computed(() => kbList.value.filter((k) => k.id !== kbId.value))

function openMoveDialog(card: CardItem) {
  moveCard.value = card
  moveTargetKb.value = ''
  moveDialog.value = true
}

async function confirmMove() {
  if (!moveCard.value || !moveTargetKb.value) return
  moving.value = true
  try {
    await cardApi.move(moveCard.value.id, moveTargetKb.value)
    ElMessage.success('移动成功')
    moveDialog.value = false
    await load()
  } finally {
    moving.value = false
  }
}
</script>

<style scoped>
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kb-title {
  margin: 0;
  font-size: 18px;
}
.header-right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.content-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 20px;
}
.tag-bar {
  border-right: 1px solid var(--mw-border);
  padding-right: 12px;
}
.tag-item {
  padding: 7px 10px;
  font-size: 13px;
  color: var(--mw-text-secondary);
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
}
.tag-item:hover {
  background: var(--mw-bg-hover);
}
.tag-item.active {
  background: var(--mw-bg-hover);
  color: var(--mw-text-primary);
  font-weight: 600;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.content-card {
  padding: 18px 22px;
  cursor: pointer;
}
.card-top-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.card-move-btn {
  flex-shrink: 0;
  opacity: 0.55;
}
.content-card:hover .card-move-btn {
  opacity: 1;
}
.card-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 8px;
}
.card-summary {
  font-size: 13px;
  color: var(--mw-text-secondary);
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>