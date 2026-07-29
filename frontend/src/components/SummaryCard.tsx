import { useState } from 'react'
import type { EntityContext, MetricFact } from '../types'

interface Props {
  context: EntityContext
}

// 指标名中文映射
const METRIC_LABELS: Record<string, string> = {
  GMV: '日均GMV',
  订单量: '日均订单',
  客单价: '客单价',
  复购率: '复购率',
  毛利率: '毛利率',
  净利率: '净利率',
  品类宽度: '品类宽度',
  SKU宽度: 'SKU宽度',
  损耗率: '损耗率',
  运输成本率: '运输成本率',
  仓储成本率: '仓储成本率',
  商品成本率: '商品成本率',
}

/**
 * 归因链摘要卡 — v3: 展示 metric_facts 真实数据 + 各品类对比
 */
export default function SummaryCard({ context }: Props) {
  const { metric_facts, all_categories_latest, timeline } = context
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)

  // 从 metric_facts 获取最新一周的指标
  const latestMetrics = _getLatestMetrics(metric_facts)
  const hasMetricData = latestMetrics.length > 0

  // 取最近一条事件（按时间倒序）
  const sorted = [...timeline].sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at),
  )
  const latest = sorted[0]
  const topEvidence = context.evidence?.[0]

  // 获取所有品类的对比数据
  const categoryComparison = _buildCategoryComparison(all_categories_latest, selectedMetric)
  const availableMetrics = _getAvailableMetrics(all_categories_latest)

  // 如果没有指定指标，默认选第一个有品类数据的指标
  const activeMetric = selectedMetric || availableMetrics[0] || null

  return (
    <div className="summary-card">
      {/* 实体自身核心指标（来自 metric_facts） */}
      {hasMetricData && (
        <div className="summary-metrics">
          <div className="summary-label">核心指标 · {latestMetrics[0]?.week_label || latestMetrics[0]?.report_date}</div>
          <div className="summary-metrics-grid">
            {latestMetrics.map((m, i) => (
              <div key={i} className="summary-metric-item">
                <span className="summary-metric-label">
                  {METRIC_LABELS[m.metric_name] || m.metric_name}
                </span>
                <span className="summary-metric-value">
                  {_formatMetricValue(m)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 各品类对比表（当有 all_categories_latest 数据时展示） */}
      {all_categories_latest && all_categories_latest.length > 0 && (
        <div className="summary-comparison">
          <div className="summary-label">各品类对比</div>
          
          {/* 指标切换 tabs */}
          {availableMetrics.length > 1 && (
            <div className="summary-metric-tabs">
              {availableMetrics.map(m => (
                <button
                  key={m}
                  className={`summary-metric-tab ${activeMetric === m ? 'active' : ''}`}
                  onClick={() => setSelectedMetric(m)}
                >
                  {METRIC_LABELS[m] || m}
                </button>
              ))}
            </div>
          )}

          {/* 对比表格 */}
          {activeMetric && categoryComparison.length > 0 && (
            <div className="summary-comparison-table">
              <div className="summary-comparison-header">
                <span>品类</span>
                <span>{METRIC_LABELS[activeMetric] || activeMetric}</span>
              </div>
              {categoryComparison.map((row) => (
                <div
                  key={row.category}
                  className={`summary-comparison-row ${row.category === context.entity_name ? 'is-current' : ''}`}
                >
                  <span className="summary-comparison-cat">
                    {row.category}
                    {row.category === context.entity_name && ' (当前)'}
                  </span>
                  <span className="summary-comparison-val">
                    {_formatComparisonValue(row.metric_value, row.metric_unit)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 最近事件摘要（无 metric_facts 时作为 fallback） */}
      {!hasMetricData && latest && (
        <>
          <div className="summary-label">最近动态 · {latest.occurred_at}</div>
          <div className="summary-what">{latest.summary}</div>
        </>
      )}

      {/* 归因链（有事件时展示） */}
      {latest && (
        <>
          {/* 为什么 */}
          {latest.attribution && (
            <div className="summary-row">
              <span className="summary-key">归因</span>
              <span className="summary-val">{latest.attribution}</span>
            </div>
          )}

          {/* 做了什么 → 结果 */}
          {latest.decision && (
            <div className="summary-decision">
              <div className="summary-row">
                <span className="summary-key">决策</span>
                <span className="summary-val">{latest.decision.action}</span>
              </div>
              <div className="summary-outcome-row">
                <span className="summary-outcome-label">
                  {latest.decision.outcome_detail || latest.decision.outcome}
                </span>
              </div>
            </div>
          )}
        </>
      )}

      {/* 来源 */}
      {topEvidence && (
        <div className="summary-source">
          <span className="summary-source-icon">📄</span>
          <span className="summary-source-title">{topEvidence.doc_title}</span>
        </div>
      )}

      {/* 历史事件计数提示 */}
      {sorted.length > 1 && (
        <div className="summary-more">
          还有 {sorted.length - 1} 条历史事件 · 见下方时间线
        </div>
      )}
    </div>
  )
}

// ─── 辅助函数 ─────────────────────────────────────────────────

function _getLatestMetrics(metric_facts?: MetricFact[]): MetricFact[] {
  if (!metric_facts || metric_facts.length === 0) return []

  // 找最新报告日期
  const dates = [...new Set(metric_facts.map(m => m.report_date))].sort().reverse()
  const latestDate = dates[0]

  // 筛选最新日期的指标
  // 注意：不过滤 category==='总体'，因为 METRIC 实体（如 GMV）的数据就存储在"总体"行
  return metric_facts
    .filter(m => m.report_date === latestDate)
    .sort((a, b) => (b.metric_value || 0) - (a.metric_value || 0))
    .slice(0, 6)
}

function _getAvailableMetrics(all_categories?: MetricFact[]): string[] {
  if (!all_categories || all_categories.length === 0) return []
  return [...new Set(all_categories.map(m => m.metric_name))]
}

function _buildCategoryComparison(
  all_categories?: MetricFact[],
  metricName?: string | null,
): MetricFact[] {
  if (!all_categories || !metricName) return []

  // 按品类去重，取最新一周
  const byCategory = new Map<string, MetricFact>()
  for (const row of all_categories) {
    if (row.metric_name !== metricName) continue
    const existing = byCategory.get(row.category)
    if (!existing || row.report_date > existing.report_date) {
      byCategory.set(row.category, row)
    }
  }

  return [...byCategory.values()].sort((a, b) => (b.metric_value || 0) - (a.metric_value || 0))
}

function _formatMetricValue(m: MetricFact): string {
  const v = m.metric_value
  if (v === null || v === undefined) return '-'

  const unit = m.metric_unit || ''

  // 百分比指标
  if (unit === '%') {
    return `${v.toFixed(1)}%`
  }

  // 大数值（万级以上）
  if (Math.abs(v) >= 10000) {
    return `${(v / 10000).toFixed(1)}万${unit}`
  }

  // 千级以上
  if (Math.abs(v) >= 1000) {
    return `${v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}${unit}`
  }

  // 普通数值
  return `${v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${unit}`
}

function _formatComparisonValue(v: number | null, unit: string | null): string {
  if (v === null || v === undefined) return '-'
  const u = unit || ''
  if (u === '%') return `${v.toFixed(1)}%`
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}万${u}`
  return `${v.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}${u}`
}
