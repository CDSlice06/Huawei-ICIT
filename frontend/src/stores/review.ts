/** 回顾（复习）状态（tasks.md 1.2 占位，10.6 完善）。 */
import { defineStore } from 'pinia'

export const useReviewStore = defineStore('review', {
  state: () => ({
    todayCount: 0,
  }),
  actions: {
    setTodayCount(n: number) {
      this.todayCount = n
    },
  },
})