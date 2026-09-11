/** 知识库（专题库）列表状态（tasks.md 1.2 占位，10.2 完善）。 */
import { defineStore } from 'pinia'

export interface KnowledgeBaseItem {
  id: string
  name: string
  card_count?: number
  created_at?: string
}

export const useKbStore = defineStore('kb', {
  state: () => ({
    kbList: [] as KnowledgeBaseItem[],
    currentKbId: '',
  }),
  actions: {
    setCurrent(id: string) {
      this.currentKbId = id
    },
  },
})