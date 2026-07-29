// Shared TypeScript types matching the BCE API contract (v1).

export type Category =
  | 'METRIC'
  | 'OBJECT'
  | 'EVENT'
  | 'DECISION'
  | 'EXPERIMENT'
  | 'OWNER'

export type EventType = 'FLUCTUATION' | 'DECISION' | 'EXPERIMENT' | 'LAUNCH'

export type Outcome = 'SUCCESS' | 'FAILED' | 'INCONCLUSIVE' | 'PENDING'

export type ReasonCode =
  | 'FIRST_MENTION'
  | 'FINAL_RESOLUTION'
  | 'FAILED_CASE'
  | 'HIGH_SIMILARITY'
  | 'REGULAR'

export interface Entity {
  entity_id: string
  entity_name: string
  category: Category
  aliases?: string[]
  description?: string
  parent_entity_id?: string | null
  level?: number
  sort_order?: number
}

// ─── v2 新增类型 ───────────────────────────────────────────────

export interface EntityTreeNode extends Entity {
  children?: EntityTreeNode[]
}

export interface MetricFact {
  report_date: string
  week_label: string
  category: string
  metric_name: string
  metric_value: number
  metric_unit: string | null
}

export interface InsightResult {
  insight: string
  source: 'llm' | 'rules' | 'llm_with_fallback'
  confidence: 'high' | 'medium' | 'low'
  fallback_reason?: string
  validation_errors?: string[]
  rule_insight?: Insight
}

export interface PrecomputedMetrics {
  event_count: number
  fluctuation_count: number
  decision_count: number
  pending_decisions: number
  first_seen: string | null
  last_seen: string | null
  top_attribution: string | null
  event_type_distribution: Record<string, number>
}

export interface ChildContribution {
  entity_id: string
  entity_name: string
  category: string
  level: number
  event_count: number
  contribution_pct: number
  has_children: boolean
}

export interface EntityContextV2 extends Omit<EntityContext, 'insight'> {
  parent_entity_id?: string | null
  level?: number
  insight: InsightResult
  metrics: PrecomputedMetrics
  children_contribution: ChildContribution[]
}

export type QuestionType = 'FACTUAL' | 'AGGREGATION' | 'COMPARISON' | 'ANALYTICAL' | 'WHAT_IF'

export interface AskEntity {
  entity_id: string
  entity_name: string
  category: string
}

export interface AskResponse {
  question: string
  question_type: QuestionType
  entities: AskEntity[]
  answer: string
  confidence: 'high' | 'medium' | 'low'
  fallback_used: boolean
  fallback_reason?: string
  calculation?: CalculationInfo
  validation_errors?: string[]
  response_time_ms: number
  sql?: string
  rows?: Record<string, unknown>[]
}

export interface CalculationInfo {
  type: string
  input: Record<string, unknown>
  formula?: string
  result: Record<string, unknown> | null
  explanation: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  question_type?: QuestionType
  confidence?: 'high' | 'medium' | 'low'
  fallback_used?: boolean
  fallback_reason?: string
  response_time_ms?: number
  sql?: string
  rows?: Record<string, unknown>[]
  calculation?: CalculationInfo
  timestamp: number
}

export interface Decision {
  action: string
  owner: string
  outcome: Outcome
  outcome_detail: string
}

export interface TimelineEvent {
  event_id: string
  occurred_at: string
  time_granularity: string
  summary: string
  event_type: EventType
  attribution?: string
  decision?: Decision
}

export interface Evidence {
  doc_title: string
  doc_url?: string
  importance_score: number
  reason_code: ReasonCode
  superseded_by?: string
  effective_score?: number
  label_version?: number
}

export interface Insight {
  pattern: string
  risk: string
  suggestion: string
}

export interface EntityContext {
  entity_id: string
  entity_name: string
  category: Category
  description?: string
  timeline: TimelineEvent[]
  evidence: Evidence[]
  insight: Insight | InsightResult | null
  metrics?: PrecomputedMetrics
  metric_facts?: MetricFact[]
  all_categories_latest?: MetricFact[]
  children_contribution?: ChildContribution[]
}

export interface Relationship {
  rel_id: string
  source_entity_id: string
  target_entity_id: string
  relation_type: string // CAUSED_BY / LEADS_TO / CORRELATED / RESPONDS_TO
  confidence: number
  source: string
}
