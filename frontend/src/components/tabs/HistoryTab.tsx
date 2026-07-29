import { useMemo, useState } from 'react'
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import type { TimelineEvent, MetricFact } from '../../types'
import { EVENT_TYPE_LABEL, GRANULARITY_LABEL } from '../../lib/labels'

interface Props {
  timeline: TimelineEvent[]
  metric_facts?: MetricFact[]
}

interface ChartPoint {
  date: string
  [key: string]: string | number | null
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

// 指标颜色映射
const METRIC_COLORS: Record<string, string> = {
  GMV: '#2563eb',
  订单量: '#7c3aed',
  客单价: '#f59e0b',
  复购率: '#16a34a',
  毛利率: '#dc2626',
  净利率: '#0891b2',
  品类宽度: '#db2777',
  SKU宽度: '#65a30d',
  损耗率: '#ea580c',
  运输成本率: '#4f46e5',
  仓储成本率: '#0d9488',
  商品成本率: '#be123c',
}

function CustomTooltip({ active, payload, label }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string; payload: ChartPoint }>
  label?: string
}) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-date">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="chart-tooltip-row">
          <span className="chart-tooltip-dot" style={{ background: p.color }} />
          <span className="chart-tooltip-name">{p.name}:</span>
          <span className="chart-tooltip-value">{p.value !== null ? p.value.toLocaleString() : '-'}</span>
        </div>
      ))}
    </div>
  )
}

export default function HistoryTab({ timeline, metric_facts }: Props) {
  const sorted = useMemo(
    () =>
      [...timeline].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at)),
    [timeline],
  )

  const [expanded, setExpanded] = useState<string | null>(
    sorted.length > 0 ? sorted[sorted.length - 1].event_id : null,
  )

  // ── 基于 metric_facts 构建图表数据 ──
  const { chartData, metricNames, chartUnit } = useMemo(() => {
    if (!metric_facts || metric_facts.length === 0) {
      return { chartData: [] as ChartPoint[], metricNames: [] as string[], chartUnit: '' }
    }

    // 提取所有指标名（对于 METRIC 实体，数据存储在"总体"行，不能过滤）
    const hasNonOverall = metric_facts.some(m => m.category !== '总体')
    const names = [...new Set(
      metric_facts
        .filter(m => hasNonOverall ? m.category !== '总体' : true)
        .map(m => m.metric_name)
    )]

    // 提取所有日期
    const dates = [...new Set(metric_facts.map(m => m.report_date))].sort()

    // 构建图表数据点
    const data: ChartPoint[] = dates.map(date => {
      const point: ChartPoint = { date }
      for (const name of names) {
        const fact = metric_facts.find(
          m => m.report_date === date && m.metric_name === name && (hasNonOverall ? m.category !== '总体' : true)
        )
        point[name] = fact?.metric_value ?? null
      }
      return point
    })

    // 确定单位（从第一个有效指标获取）
    const unit = metric_facts.find(m => m.metric_unit)?.metric_unit || ''

    return { chartData: data, metricNames: names, chartUnit: unit }
  }, [metric_facts])

  const hasChartData = chartData.length >= 2 && metricNames.length > 0

  if (sorted.length === 0 && !hasChartData) {
    return <div className="tab-empty">暂无时间线事件</div>
  }

  return (
    <div className="history-chart-tab">
      {/* 趋势图 - 带指标名的多线图表 */}
      {hasChartData && (
        <div className="chart-section">
          <div className="chart-title">
            指标趋势{chartUnit ? `（${chartUnit}）` : ''}
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart
              data={chartData}
              margin={{ top: 8, right: 8, bottom: 4, left: -8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f1f3" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#9ca3af' }}
                tickLine={false}
                axisLine={{ stroke: '#e5e7eb' }}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#9ca3af' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => v.toLocaleString()}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11, paddingTop: 4 }}
                iconType="circle"
                iconSize={8}
              />
              {metricNames.map(name => (
                <Line
                  key={name}
                  type="monotone"
                  dataKey={name}
                  name={METRIC_LABELS[name] || name}
                  stroke={METRIC_COLORS[name] || '#6b7280'}
                  strokeWidth={2}
                  dot={{ r: 3, fill: METRIC_COLORS[name] || '#6b7280', strokeWidth: 0 }}
                  activeDot={{ r: 5, fill: METRIC_COLORS[name] || '#6b7280' }}
                  connectNulls
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Event List with detail expansion */}
      <div className="chart-event-list">
        {sorted.map((evt) => {
          const open = expanded === evt.event_id
          const typeClass = `t-${evt.event_type.toLowerCase()}`
          return (
            <div key={evt.event_id} className={`chart-event-item ${typeClass}`}>
              <div
                className={`chart-event-row${open ? ' is-open' : ''}`}
                onClick={() => setExpanded(open ? null : evt.event_id)}
              >
                <div className="chart-event-left">
                  <span className="chart-event-dot" style={{ background: '#2563eb' }} />
                  <div className="chart-event-info">
                    <span className="chart-event-date">
                      {evt.occurred_at}
                      <span className="tl-gran">
                        {GRANULARITY_LABEL[evt.time_granularity] ?? evt.time_granularity}
                      </span>
                    </span>
                    <span className="chart-event-summary">{evt.summary}</span>
                  </div>
                </div>
                <div className="chart-event-right">
                  <span className={`badge badge-type ${typeClass}`}>
                    {EVENT_TYPE_LABEL[evt.event_type]}
                  </span>
                </div>
              </div>

              {open && (
                <div className="chart-event-detail">
                  {evt.attribution && (
                    <div className="detail-block">
                      <div className="detail-label">📝 归因分析</div>
                      <div className="detail-text">{evt.attribution}</div>
                    </div>
                  )}
                  {evt.decision && (
                    <div className="detail-block">
                      <div className="detail-label">🎯 关联决策</div>
                      <div className="detail-decision">
                        <span className="detail-metric-item">
                          动作：{evt.decision.action}
                        </span>
                        <span className="detail-metric-item">
                          结果：{evt.decision.outcome}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
