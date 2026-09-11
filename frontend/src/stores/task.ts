/** 异步任务状态（SSE推送更新，tasks.md 1.2 占位，10.3 完善）。 */
import { defineStore } from 'pinia'

export interface ActiveTask {
  taskId: string
  status: 'pending' | 'running' | 'done' | 'failed'
  message?: string
}

export const useTaskStore = defineStore('task', {
  state: () => ({
    activeTasks: [] as ActiveTask[],
  }),
  actions: {
    upsert(task: ActiveTask) {
      const idx = this.activeTasks.findIndex((t) => t.taskId === task.taskId)
      if (idx >= 0) this.activeTasks[idx] = task
      else this.activeTasks.push(task)
    },
    remove(taskId: string) {
      this.activeTasks = this.activeTasks.filter((t) => t.taskId !== taskId)
    },
  },
})