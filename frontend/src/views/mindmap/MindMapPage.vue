<template>
  <div class="mindmap-page">
    <!-- 顶部工具栏（ui-design.md §3.5）：编辑能力已内置于画布（P1-6），拼图回顾为P2-2 -->
    <div class="map-toolbar">
      <span class="mw-subtitle">导图空间 · {{ kbName }}</span>
      <div class="toolbar-right">
        <el-button size="small" @click="router.push(`/workbench/kb/${kbId}/map/puzzle`)">拼图回顾</el-button>
      </div>
    </div>
    <MindMapCanvas :kb-id="kbId" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { kbApi } from '@/api'
import MindMapCanvas from '@/components/mindmap/MindMapCanvas.vue'

const route = useRoute()
const router = useRouter()
const kbId = computed(() => route.params.id as string)
const kbName = ref('')

onMounted(async () => {
  const kbs = await kbApi.list().catch(() => [])
  kbName.value = kbs.find((k) => k.id === kbId.value)?.name || ''
})
</script>

<style scoped>
.map-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.toolbar-right {
  display: flex;
  gap: 8px;
}
</style>