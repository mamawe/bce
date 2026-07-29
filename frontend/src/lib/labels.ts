// Shared label maps + small presentational helpers for badges.

import type { Category, EventType, Outcome, ReasonCode } from '../types'

export const CATEGORY_LABEL: Record<Category, string> = {
  METRIC: '指标',
  OBJECT: '对象',
  EVENT: '事件',
  DECISION: '决策',
  EXPERIMENT: '实验',
  OWNER: '责任人',
}

export const EVENT_TYPE_LABEL: Record<EventType, string> = {
  FLUCTUATION: '波动',
  DECISION: '决策',
  EXPERIMENT: '实验',
  LAUNCH: '上线',
}

export const OUTCOME_LABEL: Record<Outcome, string> = {
  SUCCESS: '成功',
  FAILED: '失败',
  INCONCLUSIVE: '待验证',
  PENDING: '进行中',
}

export const REASON_LABEL: Record<ReasonCode, string> = {
  FIRST_MENTION: '首次提出',
  FINAL_RESOLUTION: '最终闭环',
  FAILED_CASE: '失败案例',
  HIGH_SIMILARITY: '高相似',
  REGULAR: '普通提及',
}

export const GRANULARITY_LABEL: Record<string, string> = {
  DAY: '日',
  WEEK: '周',
  MONTH: '月',
  QUARTER: '季',
}
