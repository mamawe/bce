import { useEffect, useState } from 'react'
import { loadInsight } from '../../api'
import type { Insight, InsightResult } from '../../types'

interface Props {
  entityId: string
  contextInsight?: Insight | InsightResult | null
}

export default function InsightTab({ entityId, contextInsight }: Props) {
  const [insight, setInsight] = useState<InsightResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loadInsight(entityId).then((result) => {
      if (cancelled) return
      if (result) {
        setInsight(result)
      } else {
        setError('洞察生成失败，请稍后重试')
      }
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [entityId])

  if (loading) {
    return (
      <div className="insight">
        <div className="insight-loading">
          <span className="spinner" />
          <span>正在生成洞察…</span>
        </div>
      </div>
    )
  }

  // If API insight failed but we have old-format context insight (pattern/risk/suggestion), use it as fallback
  if (error && contextInsight && 'pattern' in contextInsight) {
    const legacy = contextInsight as Insight
    return (
      <div className="insight">
        <div className="insight-card i-pattern">
          <div className="insight-icon">📊</div>
          <div>
            <div className="insight-label">规律</div>
            <div className="insight-text">{legacy.pattern}</div>
          </div>
        </div>
        <div className="insight-card i-risk">
          <div className="insight-icon">⚠️</div>
          <div>
            <div className="insight-label">风险</div>
            <div className="insight-text">{legacy.risk}</div>
          </div>
        </div>
        <div className="insight-card i-suggest">
          <div className="insight-icon">💡</div>
          <div>
            <div className="insight-label">建议</div>
            <div className="insight-text">{legacy.suggestion}</div>
          </div>
        </div>
        <div className="insight-disclaimer">AI 生成内容，仅供参考</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="insight">
        <div className="tab-empty">{error}</div>
      </div>
    )
  }

  if (!insight || !insight.insight) {
    return (
      <div className="insight">
        <div className="tab-empty">暂无洞察数据</div>
      </div>
    )
  }

  const sourceLabel = insight.source === 'llm' ? 'LLM 推理' : insight.source === 'rules' ? '规则引擎' : 'LLM + 降级'
  const confidenceLabel = insight.confidence === 'high' ? '高' : insight.confidence === 'medium' ? '中' : '低'

  return (
    <div className="insight">
      <div className="insight-text-block">
        {insight.insight.split('\n').map((line, i) => (
          <p key={i} className="insight-line">{line || '\u00A0'}</p>
        ))}
      </div>
      <div className="insight-meta-footer">
        <span className={`badge badge-source s-${insight.source}`}>{sourceLabel}</span>
        <span className={`badge badge-confidence c-${insight.confidence}`}>置信度：{confidenceLabel}</span>
      </div>
      {insight.fallback_reason && (
        <div className="insight-disclaimer">降级原因：{insight.fallback_reason}</div>
      )}
      <div className="insight-disclaimer">AI 生成内容，仅供参考</div>
    </div>
  )
}
