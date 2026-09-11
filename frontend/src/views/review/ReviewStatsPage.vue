<template>
  <div class="stats-page">
    <!-- 概览三卡（spec §6.7） -->
    <div class="stat-row">
      <div class="stat-card mw-card">
        <div class="stat-num">{{ stats?.total_reviews ?? '—' }}</div>
        <div class="stat-label">累计复习次数</div>
      </div>
      <div class="stat-card mw-card">
        <div class="stat-num mastered">{{ stats?.mastered_count ?? '—' }}</div>
        <div class="stat-label">已掌握卡片</div>
      </div>
      <div class="stat-card mw-card">
        <div class="stat-num consolidating">{{ stats?.consolidating_count ?? '—' }}</div>
        <div class="stat-label">待巩固卡片</div>
      </div>
      <div class="stat-card mw-card">
        <div class="stat-num streak">🔥 {{ stats?.streak_days ?? '—' }}</div>
        <div class="stat-label">连续打卡（天）</div>
      </div>
    </div>

    <!-- 近14天遗忘趋势（按日完成数与"记住"数） -->
    <div class="trend-card mw-card">
      <div class="trend-header">
        <h3>近 14 天复习趋势</h3>
        <div class="legend">
          <span class="dot done"></span>完成
          <span class="dot remember"></span>记住
        </div>
      </div>
      <div v-if="trend.length" class="trend-bars">
        <div v-for="d in trend" :key="d.date" class="trend-col" :title="`${d.date}：完成 ${d.done}，记住 ${d.remember}`">
          <div class="bar-track">
            <div class="bar done" :style="{ height: barHeight(d.done) }"></div>
            <div class="bar remember" :style="{ height: barHeight(d.remember) }"></div>
          </div>
          <div class="bar-label">{{ d.date.slice(5) }}</div>
        </div>
      </div>
      <el-empty v-else description="暂无复习记录，完成今日复习后这里会出现趋势" :image-size="72" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { reviewApi } from '@/api'

interface TrendDay {
  date: string
  done: number
  remember: number
}

const stats = ref<{
  total_reviews: number
  mastered_count: number
  consolidating_count: number
  trend_data: TrendDay[]
  streak_days: number
} | null>(null)

const trend = computed<TrendDay[]>(() => stats.value?.trend_data ?? [])
const maxDone = computed(() => Math.max(1, ...trend.value.map((d) => d.done)))

function barHeight(n: number): string {
  return `${Math.round((n / maxDone.value) * 100)}%`
}

onMounted(async () => {
  stats.value = await reviewApi.statistics().catch(() => null)
})
</script>

<style scoped>
.stats-page {
  max-width: 860px;
  margin: 0 auto;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}
.stat-card {
  padding: 24px 28px;
}
.stat-num {
  font-size: 32px;
  font-weight: 700;
}
.stat-num.mastered {
  color: var(--el-color-success);
}
.stat-num.consolidating {
  color: var(--el-color-warning);
}
.stat-num.streak {
  color: var(--el-color-danger);
}
.stat-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--mw-text-tertiary);
}
.trend-card {
  padding: 24px 28px;
}
.trend-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.trend-header h3 {
  margin: 0;
  font-size: 15px;
}
.legend {
  font-size: 12px;
  color: var(--mw-text-tertiary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
  margin-left: 8px;
}
.dot.done {
  background: var(--el-color-primary);
}
.dot.remember {
  background: var(--el-color-success);
}
.trend-bars {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  height: 160px;
}
.trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.bar-track {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 3px;
  justify-content: center;
  border-bottom: 1px solid var(--mw-border);
}
.bar {
  width: 10px;
  border-radius: 3px 3px 0 0;
  min-height: 2px;
}
.bar.done {
  background: var(--el-color-primary);
}
.bar.remember {
  background: var(--el-color-success);
}
.bar-label {
  font-size: 10px;
  color: var(--mw-text-tertiary);
  text-align: center;
  margin-top: 6px;
}
</style>
