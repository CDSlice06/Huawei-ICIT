/**
 * 任务状态订阅工具（tasks.md 10.3）：
 * EventSource（httpOnly Cookie 同源自动携带）订阅 SSE，断开降级 2 秒轮询。
 */
import { taskApi, type TaskStatus } from '@/api'

export interface WatchOptions {
  onUpdate: (status: TaskStatus) => void
  /** 终态（done/failed）回调，触发后停止监听 */
  onFinished: (status: TaskStatus) => void
}

export function watchTask(taskId: string, options: WatchOptions): () => void {
  let stopped = false
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let source: EventSource | null = null
  let polling = false

  const handle = (status: TaskStatus) => {
    if (stopped) return
    options.onUpdate(status)
    if (status.status === 'done' || status.status === 'failed') {
      cleanup()
      options.onFinished(status)
    }
  }

  const startPolling = () => {
    if (polling || stopped) return
    polling = true
    const poll = async () => {
      if (stopped) return
      try {
        const status = await taskApi.get(taskId)
        handle(status)
      } catch {
        /* 忽略单次轮询失败 */
      }
      if (!stopped && polling) pollTimer = setTimeout(poll, 2000)
    }
    void poll()
  }

  const cleanup = () => {
    stopped = true
    if (source) {
      source.close()
      source = null
    }
    if (pollTimer) clearTimeout(pollTimer)
  }

  // SSE 主通道：onerror 关闭后降级轮询
  try {
    source = new EventSource(`/api/tasks/${taskId}/stream`)
    source.onmessage = (ev) => {
      try {
        handle(JSON.parse(ev.data) as TaskStatus)
      } catch {
        /* 跳过无法解析的事件 */
      }
    }
    source.onerror = () => {
      if (source) source.close()
      source = null
      startPolling()
    }
  } catch {
    startPolling()
  }

  return cleanup
}