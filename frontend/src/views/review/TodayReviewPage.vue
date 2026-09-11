<template>
  <div class="review-page">
    <!-- 顶部切换（ui-design.md §3.7） -->
    <div class="tab-row">
      <span class="tab active">今日回顾</span>
      <span class="tab" @click="router.push('/review/stats')">回顾统计</span>
    </div>

    <!-- 复习中：大尺寸居中回顾卡片（ui-design.md §3.7） -->
    <div v-if="current" class="review-card mw-card">
      <div class="progress mw-caption">{{ index + 1 }} / {{ items.length }}</div>
      <div class="review-title">{{ current.title }}</div>

      <div class="qa-area">
        <template v-for="(qa, i) in current.qa_pairs" :key="i">
          <div class="qa-q">{{ qa.question }}</div>
          <template v-if="revealed">
            <div class="qa-a">{{ qa.answer }}</div>
          </template>
        </template>
      </div>

      <div v-if="!revealed" class="reveal-row">
        <el-button type="primary" @click="revealed = true">显示内容</el-button>
      </div>

      <template v-else>
        <!-- 三档自评（前端文案映射：印象模糊→forget / 有新感悟→blur / 已牢记→remember，ui-design.md 文案映射表） -->
        <div class="rating-row">
          <el-button @click="submit('forget')">印象模糊</el-button>
          <el-button @click="submit('blur')">有新感悟</el-button>
          <el-button type="primary" @click="submit('remember')">已牢记</el-button>
        </div>
      </template>

      <div v-if="feedback" class="feedback mw-caption">{{ feedback }}</div>
    </div>

    <!-- 全部完成 -->
    <div v-else-if="completedCount > 0" class="review-card mw-card center">
      <h3>本轮回顾完成 🎉</h3>
      <p class="mw-subtitle">已完成 {{ completedCount }} 条回顾，下次回顾时间已按遗忘曲线排定</p>
    </div>

    <!-- 空态 -->
    <div v-else class="review-card mw-card center">
      <el-empty description="今日没有待回顾的内容" />
      <el-button type="primary" @click="router.push('/workbench/import')">沉淀新内容</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reviewApi, type ReviewItem } from '@/api'
import { useReviewStore } from '@/stores/review'

const router = useRouter()
const review = useReviewStore()

const items = ref<ReviewItem[]>([])
const index = ref(0)
const revealed = ref(false)
const feedback = ref('')
const completedCount = ref(0)

const current = computed(() => (index.value < items.value.length ? items.value[index.value] : null))

onMounted(async () => {
  const data = await reviewApi.today()
  items.value = data.items
  review.setTodayCount(data.total)
})

async function submit(rating: 'forget' | 'blur' | 'remember') {
  if (!current.value) return
  try {
    const result = await reviewApi.submit(current.value.task_id, rating)
    completedCount.value += 1
    feedback.value =
      rating === 'forget'
        ? '没关系，这条内容将在明天重新回到你的回顾列表'
        : `下次回顾：${result.next_review_date}（间隔 ${result.next_interval_days} 天）`
    revealed.value = false
    index.value += 1
    review.setTodayCount(items.value.length - index.value)
  } catch {
    ElMessage.error('提交失败，请重试')
  }
}
</script>

<style scoped>
.tab-row {
  display: flex;
  gap: 20px;
  margin-bottom: 24px;
}
.tab {
  font-size: 15px;
  color: var(--mw-text-tertiary);
  cursor: pointer;
  padding-bottom: 6px;
}
.tab.active {
  color: var(--mw-text-primary);
  font-weight: 600;
  border-bottom: 2px solid var(--mw-text-primary);
}
.review-card {
  max-width: 680px;
  margin: 0 auto;
  padding: 36px 44px;
  text-align: center;
  min-height: 320px;
}
.review-card.center {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.progress {
  margin-bottom: 16px;
}
.review-title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 24px;
}
.qa-area {
  text-align: left;
  margin-bottom: 24px;
}
.qa-q {
  font-size: 15px;
  margin-bottom: 10px;
}
.qa-a {
  font-size: 14px;
  background: var(--mw-bg-hover);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
}
.reveal-row {
  display: flex;
  justify-content: center;
}
.rating-row {
  display: flex;
  justify-content: center;
  gap: 16px;
}
.feedback {
  margin-top: 18px;
}
</style>