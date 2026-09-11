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
  importDocument: (obsKey: string, filename: string, kbId?: string) =>
    request.post<never, AssetCreated>('/assets/document', {
      obs_key: obsKey,
      filename,
      kb_id: kbId || null,
    }),
  importImage: (obsKey: string, kbId?: string) =>
    request.post<never, AssetCreated>('/assets/image', { obs_key: obsKey, kb_id: kbId || null }),
  get: (id: string) => request.get<never, Record<string, unknown>>(`/assets/${id}`),
  remove: (id: string) => request.delete(`/assets/${id}`),
  restruct: (id: string) =>
    request.post<never, { task_id: string }>(`/assets/${id}/restruct`),
}

// ---------- OBS 直传（P1-2/3，design §2.5.4） ----------

export interface UploadTicket {
  mode: 'obs' | 'local'
  obs_key: string
  upload_url: string
  method: 'PUT' | 'POST'
  headers: Record<string, string>
  expires_at: string
}

export const obsApi = {
  presign: (filename: string, contentType: string, kind: 'document' | 'image') =>
    request.get<never, UploadTicket>('/obs/presign', {
      params: { filename, content_type: contentType, kind },
    }),
  /** 本地回退模式的后端代存（OBS 模式由浏览器直传，不经过此方法） */
  localUpload: (obsKey: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request.post<never, { obs_key: string; size: number }>('/obs/local-upload', form, {
      params: { obs_key: obsKey },
    })
  },
  fileUrl: (obsKey: string) => `/api/obs/file/${obsKey}`,
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
  /** 批量编辑节点（P1-6，spec §5.5.1规则4~7）：标题/父子/位置/增删，版本置"手动编辑" */
  updateNodes: (
    kbId: string,
    payload: {
      updates?: { id: string; title?: string; parent_id?: string | null; pos_x?: number | null; pos_y?: number | null; card_id?: string | null }[]
      additions?: { parent_id?: string; title: string }[]
      deletions?: string[]
    },
  ) => request.put<never, MapData>(`/mind-maps/${kbId}/nodes`, payload),
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
  /** 复习统计（P1-7，spec §6.7） */
  statistics: () =>
    request.get<never, {
      total_reviews: number
      mastered_count: number
      consolidating_count: number
      trend_data: { date: string; done: number; remember: number }[]
      streak_days: number
    }>('/reviews/statistics'),
}

export interface TaskStatus {
  task_id: string
  type: string
  ref_id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'not_found'
  retry_count: number
  error: string | null
}

// ---------- 搜索与标签（P1-4/P1-5，spec §5.4.1规则4/6） ----------

export interface SearchHit {
  id: string
  kb_id: string | null
  relevance: number
}

export interface SearchCardHit extends SearchHit {
  title: string
  snippet: string
  tags: string[]
}

export interface SearchAssetHit extends SearchHit {
  asset_type: string
  snippet: string
}

export interface SearchMistakeHit extends SearchHit {
  question: string
  snippet: string
  mastery: string
  tags: string[]
}

export interface SearchResult {
  keyword: string
  cards: SearchCardHit[]
  assets: SearchAssetHit[]
  mistakes: SearchMistakeHit[]
  counts: { cards: number; assets: number; mistakes: number }
}

export interface TagAgg {
  tag: string
  count: number
}

export const searchApi = {
  search: (keyword: string, kbId?: string, type: 'all' | 'card' | 'asset' | 'mistake' = 'all') =>
    request.get<never, SearchResult>('/search', {
      params: { keyword, kb_id: kbId || undefined, type },
    }),
  tags: () => request.get<never, { items: TagAgg[]; total: number }>('/tags'),
}

export const taskApi = {
  get: (taskId: string) => request.get<never, TaskStatus>(`/tasks/${taskId}`),
}

// ---------- 错题本（P1-1，spec §5.8、design §2.2.2.8） ----------

export interface MistakeItem {
  id: string
  question: string
  answer: string
  error_analysis: string
  tags: string[]
  source_type: 'image' | 'text'
  obs_key: string | null
  kb_id: string | null
  card_id: string | null
  mastery: 'unmastered' | 'mastered'
  parse_status: 'parsing' | 'done' | 'failed'
  created_at: string
}

export interface QuizItemView {
  entry_id: string
  question: string
  tags: string[]
  source_type: 'image' | 'text'
  obs_key: string | null
}

export type QuizMark = 'mastered' | 'still_not'

export interface QuizStartResult {
  quiz_id: string
  strategy: 'sequential' | 'random'
  scope: { scope: string; count: number }
  total: number
  items: QuizItemView[]
}

export interface QuizState {
  quiz_id: string
  strategy: 'sequential' | 'random'
  scope: { scope: string; count: number }
  progress: 'in_progress' | 'done' | 'abandoned'
  total: number
  marks: { entry_id: string; mark: QuizMark }[]
  pending: QuizItemView[]
  started_at: string
  ended_at: string | null
}

export const mistakeApi = {
  importText: (content: string) =>
    request.post<never, { task_id: string; mistake_id: string }>('/mistakes/text', { content }),
  /** 图片录入依赖 OBS 直传（P1-3）落地后开放 */
  importImage: (obsKey: string) =>
    request.post<never, { task_id: string; mistake_id: string }>('/mistakes/image', { obs_key: obsKey }),
  list: (params: {
    mastery?: 'unmastered' | 'mastered' | 'all'
    parse_status?: 'parsing' | 'done' | 'failed'
    page?: number
    size?: number
  }) => request.get<never, { items: MistakeItem[]; total: number; page: number; size: number }>('/mistakes', { params }),
  get: (id: string) => request.get<never, MistakeItem>(`/mistakes/${id}`),
  update: (
    id: string,
    payload: Partial<Pick<MistakeItem, 'question' | 'answer' | 'error_analysis' | 'tags' | 'kb_id' | 'card_id'>>,
  ) => request.put<never, MistakeItem>(`/mistakes/${id}`, payload),
  remove: (id: string) => request.delete(`/mistakes/${id}`),
  setMastery: (id: string, mastery: 'mastered' | 'unmastered') =>
    request.patch<never, MistakeItem>(`/mistakes/${id}/mastery`, { mastery }),
  reparse: (id: string) =>
    request.post<never, { task_id: string; mistake_id: string }>(`/mistakes/${id}/reparse`),
  startQuiz: (payload: { strategy: 'sequential' | 'random'; count: number; scope: 'unmastered' | 'all' }) =>
    request.post<never, QuizStartResult>('/mistakes/quiz', payload),
  quizState: (quizId: string) => request.get<never, QuizState>(`/mistakes/quiz/${quizId}`),
  quizAnswer: (quizId: string, entryId: string, mark: QuizMark) =>
    request.post<never, { marked: number; total: number; finished: boolean; entry_mastery: string }>(
      `/mistakes/quiz/${quizId}/answer`,
      { entry_id: entryId, mark },
    ),
  quizAbandon: (quizId: string) =>
    request.patch<never, unknown>(`/mistakes/quiz/${quizId}/status`, { status: 'abandoned' }),
}