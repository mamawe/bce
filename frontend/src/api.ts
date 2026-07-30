// Thin fetch layer over the BCE backend (proxied at /api → localhost:8000).
// Every call falls back to mock data if the backend is unavailable, so the
// demo always works standalone.

import type { Entity, EntityContext, EntityTreeNode, AskResponse, InsightResult, Relationship } from './types'
import { MOCK_CONTEXTS, MOCK_ENTITIES, buildFallbackContext } from './data/mockData'

const BASE = '/api/v1'
const TIMEOUT_MS = 2500
const ENTITIES_TIMEOUT_MS = 15000 // /entities / /entities/hierarchy 冷启动+全量查询，放宽到 15s
const CONTEXT_TIMEOUT_MS = 10000 // /context 含数据库查询，放宽到 10s
const ASK_TIMEOUT_MS = 30000 // /ask 需要 LLM 推理，超时放宽到 30s
const INSIGHT_TIMEOUT_MS = 30000 // /context/{id}/insight 需要 LLM 推理
const INGEST_TIMEOUT_MS = 300000 // /documents/ingest 需要 LLM 抽取，超时放宽到 5min

async function tryFetchJson(path: string, timeoutMs = TIMEOUT_MS, retries = 0): Promise<unknown> {
  let lastErr: unknown
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const res = await fetch(BASE + path, { signal: controller.signal })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return await res.json()
    } catch (err) {
      lastErr = err
      // 非 AbortError 直接抛出（业务错误无需重试）
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 超时节流：避免立即重试打到冷启动中的后端，等 1s
        if (attempt < retries) await new Promise((r) => setTimeout(r, 1000))
        continue
      }
      throw err
    } finally {
      clearTimeout(timer)
    }
  }
  throw lastErr
}

async function tryPostJson(path: string, body: unknown, timeoutMs = TIMEOUT_MS): Promise<unknown> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

async function tryPutJson(path: string, body: unknown, timeoutMs = TIMEOUT_MS): Promise<unknown> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(BASE + path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

async function tryDeleteJson(path: string, timeoutMs = TIMEOUT_MS): Promise<unknown> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(BASE + path, { method: 'DELETE', signal: controller.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

export interface LoadResult<T> {
  data: T
  live: boolean
}

export async function loadEntities(): Promise<LoadResult<Entity[]>> {
  try {
    const json = (await tryFetchJson('/entities', ENTITIES_TIMEOUT_MS, 2)) as { entities?: Entity[] }
    if (Array.isArray(json?.entities) && json.entities.length > 0) {
      return { data: json.entities, live: true }
    }
    throw new Error('empty entities')
  } catch {
    return { data: MOCK_ENTITIES, live: false }
  }
}

export async function loadContext(entityId: string): Promise<LoadResult<EntityContext>> {
  try {
    const json = (await tryFetchJson(
      `/context?entity_id=${encodeURIComponent(entityId)}`,
      CONTEXT_TIMEOUT_MS,
    )) as EntityContext | null
    if (json && json.entity_id) {
      return { data: json, live: true }
    }
    throw new Error('empty context')
  } catch {
    const mock = MOCK_CONTEXTS[entityId] ?? buildFallbackContext(entityId)
    return { data: mock, live: false }
  }
}

// v3: 按需加载 LLM 洞察（用户切换到"洞察"tab 时才调用）
export async function loadInsight(entityId: string): Promise<InsightResult | null> {
  try {
    const json = (await tryFetchJson(
      `/context/${encodeURIComponent(entityId)}/insight`,
      INSIGHT_TIMEOUT_MS,
    )) as InsightResult | null
    return json
  } catch {
    return null
  }
}

export async function loadEntityHierarchy(): Promise<LoadResult<EntityTreeNode>> {
  try {
    const json = (await tryFetchJson('/entities/hierarchy', ENTITIES_TIMEOUT_MS, 2)) as { tree?: EntityTreeNode }
    if (json?.tree && Object.keys(json.tree).length > 0) {
      return { data: json.tree, live: true }
    }
    throw new Error('empty hierarchy')
  } catch {
    return { data: {} as EntityTreeNode, live: false }
  }
}

export async function askQuestion(question: string, context?: Record<string, unknown>): Promise<AskResponse> {
  const json = (await tryPostJson('/ask', { question, context }, ASK_TIMEOUT_MS)) as AskResponse
  return json
}

/**
 * SSE streaming version of askQuestion.
 * Calls onChunk for each text delta, returns final metadata from the last SSE event.
 */
export async function askQuestionStream(
  question: string,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<AskResponse> {
  const response = await fetch(`${BASE}/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('No readable stream')
  }

  const decoder = new TextDecoder()
  let accumulated = ''
  let meta: Partial<AskResponse> = {}
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    // Keep the last incomplete line in the buffer
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      const payload = trimmed.slice(6)

      if (payload === '[DONE]') continue

      try {
        const event = JSON.parse(payload) as
          | { type: 'chunk'; content: string }
          | {
              type: 'meta'
              question_type?: string
              confidence?: string
              fallback_used?: boolean
              fallback_reason?: string
              response_time_ms?: number
              sql?: string
              rows?: Record<string, unknown>[]
              calculation?: {
                type: string
                input: Record<string, unknown>
                formula?: string
                result: Record<string, unknown> | null
                explanation: string
              }
            }

        if (event.type === 'chunk') {
          accumulated += event.content
          onChunk(accumulated)
        } else if (event.type === 'meta') {
          meta = {
            question_type: event.question_type as AskResponse['question_type'],
            confidence: event.confidence as AskResponse['confidence'],
            fallback_used: event.fallback_used,
            fallback_reason: event.fallback_reason,
            response_time_ms: event.response_time_ms,
            sql: event.sql,
            rows: event.rows,
            calculation: event.calculation,
          }
        }
      } catch {
        // Skip malformed JSON lines
      }
    }
  }

  return {
    question,
    question_type: meta.question_type ?? 'FACTUAL',
    entities: [],
    answer: accumulated,
    confidence: meta.confidence ?? 'medium',
    fallback_used: meta.fallback_used ?? false,
    fallback_reason: meta.fallback_reason,
    response_time_ms: meta.response_time_ms ?? 0,
    sql: meta.sql,
    rows: meta.rows,
    calculation: meta.calculation,
  }
}

/**
 * Load entity relationships. Returns [] on any error.
 */
export async function loadRelationships(entityId: string): Promise<Relationship[]> {
  try {
    const json = (await tryFetchJson(
      `/entities/${encodeURIComponent(entityId)}/relationships`,
    )) as { relationships?: Relationship[] }
    return json.relationships ?? []
  } catch {
    return []
  }
}

export interface IngestResult {
  document_id?: string
  entities_extracted?: number
  [key: string]: unknown
}

export interface CheckResult {
  exists: boolean
  doc_id: string | null
  ingested_at: string | null
}

export interface AsyncIngestAccepted {
  task_id: string
  status: 'accepted'
  doc_id: string
}

export interface AsyncIngestStatus {
  status: 'processing' | 'done' | 'failed'
  doc_id: string
  title: string
  result: {
    entities_found: number
    events_extracted: number
    decisions_extracted: number
  } | null
  error: string | null
}

// 检查文档是否已存在（按标题）
export async function checkDocumentExists(title: string): Promise<CheckResult> {
  const json = await tryFetchJson(
    `/documents/check?title=${encodeURIComponent(title)}`,
  ) as CheckResult
  return json
}

// 异步导入文档：立即返回 task_id，后台处理 LLM 抽取
export async function ingestDocumentAsync(title: string, content: string): Promise<AsyncIngestAccepted> {
  const json = (await tryPostJson(
    '/documents/ingest',
    { title, content, async_mode: true },
    INGEST_TIMEOUT_MS,
  )) as AsyncIngestAccepted
  return json
}

// 查询异步导入任务状态（用默认超时即可，状态查询不应长时间等待）
export async function getIngestStatus(taskId: string): Promise<AsyncIngestStatus> {
  const json = await tryFetchJson(
    `/documents/ingest/${taskId}/status`,
  ) as AsyncIngestStatus
  return json
}

export interface DocListItem {
  doc_id: string
  title: string
  source_url: string | null
  ingested_at: string
}

export interface DocDetail {
  doc_id: string
  title: string
  content: string
  source_url: string | null
  ingested_at: string
}

// 列出已导入的文档
export async function listDocuments(): Promise<DocListItem[]> {
  const json = await tryFetchJson('/documents') as { documents: DocListItem[] }
  return json.documents ?? []
}

// 获取单个文档的完整内容
export async function getDocumentContent(docId: string): Promise<DocDetail> {
  return (await tryFetchJson(`/documents/${encodeURIComponent(docId)}`)) as DocDetail
}

// 删除文档（含关联的实体、事件、证据）
export async function deleteDocument(docId: string): Promise<{ deleted: string }> {
  return (await tryDeleteJson(`/documents/${encodeURIComponent(docId)}`)) as { deleted: string }
}

// 更新文档（修改标题/内容后重新异步抽取）
export async function updateDocumentAsync(
  docId: string,
  title: string,
  content: string,
): Promise<AsyncIngestAccepted> {
  return (await tryPutJson(
    `/documents/${encodeURIComponent(docId)}`,
    { title, content, async_mode: true },
    INGEST_TIMEOUT_MS,
  )) as AsyncIngestAccepted
}
