/**
 * API 层封装（tasks.md 10.x）：
 * auth / kb / asset / card / map / review / task
 */
import request from './request'

export interface UserBrief {
  id: string
  email: string
}

export const authApi = {
  register: (email: string, password: string) =>
    request.post<never, { token: string; user: UserBrief }>('/auth/register', { email, password }),
  login: (email: string, password: string) =>
    request.post<never, { token: string; user: UserBrief }>('/auth/login', { email, password }),
  logout: () => request.post('/auth/logout'),
  me: () => request.get<never, UserBrief>('/auth/me'),
}

export interface KnowledgeBaseItem {
  id: string
  name: string
  card_count: number
  created_at: string
}

export const kbApi = {
  create: (name: string) =>
    request.post<never, { id: string; name: string }>('/knowledge-bases', { name }),
  list: () => request.get<never, KnowledgeBaseItem[]>('/knowledge-bases'),
  rename: (id: string, name: string) => request.put(`/knowledge-bases/${id}`, { name }),
  /** 两段式删除：confirm=false 仅返回级联规模（后端 DELETE 路由，勿用 GET） */
  deleteInfo: (id: string) =>
    request.delete<never, { require_confirm: boolean; card_count: number }>(
      `/knowledge-bases/${id}?confirm=false`,
    ),
  delete: (id: string) => request.delete(`/knowledge-bases/${id}?confirm=true`),
}

export interface AssetCreated {
  task_id: string
  asset_id: string
}

export const assetApi = {
  importText: (content: string, kbId?: string) =>
    request.post<never, AssetCreated>('/assets/text', { content, kb_id: kbId || null }),
  get: (id: string) => request.get<never, Record<string, unknown>>(`/assets/${id}`),
  remove: (id: string) => request.delete(`/assets/${id}`),
  restruct: (id: string) =>
    request.post<never, { task_id: string }>(`/assets/${id}/restruct`),
}

export interface CardItem {
  id: string
  kb_id: string
  asset_id: string
  title: string
  summary: string
  key_points: string[]
  qa_pairs: { question: string; answer: string }[]
  tags: string[]
  review_interval_days: number
  review_count: number
  created_at: string
}

export const cardApi = {
  list: (params: { kb_id?: string; tag?: string; page?: number; size?: number }) =>
    request.get<never, { items: CardItem[]; total: number; page: number; size: number }>(
      '/cards',
      { params },
    ),
  get: (id: string) => request.get<never, CardItem>(`/cards/${id}`),
  update: (
    id: string,
    payload: Partial<Pick<CardItem, 'title' | 'summary' | 'key_points' | 'qa_pairs' | 'tags'>>,
  ) => request.put<never, CardItem>(`/cards/${id}`, payload),
  remove: (id: string) => request.delete(`/cards/${id}`),
  move: (id: string, targetKbId: string) =>
    request.post(`/cards/${id}/move`, { target_kb_id: targetKbId }),
}

export interface MapNodeItem {
  id: string
  parent_id: string | null
  title: string
  card_id: string | null
  pos_x: number | null
  pos_y: number | null
}

export interface MapData {
  map_id: string
  kb_id: string
  version_source: string
  nodes: MapNodeItem[]
}

export const mapApi = {
  generate: (kbId: string) =>
    request.post<never, { task_id: string }>('/mind-maps/generate', { kb_id: kbId }),
  getByKb: (kbId: string) =>
    request.get<never, MapData | null>(`/mind-maps/${kbId}`),
}

export interface ReviewItem {
  task_id: string
  card_id: string
  title: string
  qa_pairs: { question: string; answer: string }[]
  planned_date: string
  overdue: boolean
}

export interface RatingResult {
  rating: string
  next_interval_days: number
  next_review_date: string
  next_task_id: string
}

export const reviewApi = {
  today: () =>
    request.get<never, { items: ReviewItem[]; total: number }>('/reviews/today'),
  submit: (taskId: string, rating: 'forget' | 'blur' | 'remember') =>
    request.post<never, RatingResult>(`/reviews/${taskId}/submit`, { rating }),
}

export interface TaskStatus {
  task_id: string
  type: string
  ref_id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'not_found'
  retry_count: number
  error: string | null
}

export const taskApi = {
  get: (taskId: string) => request.get<never, TaskStatus>(`/tasks/${taskId}`),
}