import { useEffect, useState } from 'react'
import type { EntityContext } from '../types'
import { CATEGORY_LABEL } from '../lib/labels'
import SummaryCard from './SummaryCard'
import RelationshipBar from './RelationshipBar'
import HistoryTab from './tabs/HistoryTab'
import DecisionTab from './tabs/DecisionTab'
import EvidenceTab from './tabs/EvidenceTab'
import InsightTab from './tabs/InsightTab'

interface Props {
  context: EntityContext | null
  loading: boolean
  live: boolean
  onClose: () => void
  onOpenDocument?: (title: string) => void
  onEntityClick?: (entityId: string) => void
}

type TabKey = 'history' | 'decision' | 'evidence' | 'insight'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'history', label: '历史' },
  { key: 'decision', label: '决策' },
  { key: 'evidence', label: '证据' },
  { key: 'insight', label: '洞察' },
]

export default function ContextPanel({ context, loading, live, onClose, onOpenDocument, onEntityClick }: Props) {
  const [tab, setTab] = useState<TabKey>('history')

  // Reset to the first tab whenever a new entity is opened.
  useEffect(() => {
    setTab('history')
  }, [context?.entity_id])

  const decisionCount =
    context?.timeline.filter((e) => e.decision).length ?? 0

  return (
    <aside className="context-panel">
      <div className="panel-header">
        {loading || !context ? (
          <div className="panel-title-skeleton" />
        ) : (
          <>
            <div className="panel-title-row">
              <h2 className="panel-title">{context.entity_name}</h2>
              <span className={`badge badge-category c-${context.category.toLowerCase()}`}>
                {CATEGORY_LABEL[context.category]}
              </span>
            </div>
            {context.description && (
              <div className="panel-desc">{context.description}</div>
            )}
          </>
        )}
        <button className="panel-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </div>

      {/* 约束路径：归因链摘要卡，首屏必现 */}
      {!loading && context && context.timeline.length > 0 && (
        <SummaryCard context={context} />
      )}

      {/* 关联实体 */}
      {!loading && context && onEntityClick && (
        <RelationshipBar entityId={context.entity_id} onEntityClick={onEntityClick} />
      )}

      <div className="panel-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`panel-tab${tab === t.key ? ' is-active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {loading || !context ? (
          <div className="panel-loading">
            <span className="spinner" />
            <span>正在加载上下文…</span>
          </div>
        ) : (
          <>
            {tab === 'history' && <HistoryTab timeline={context.timeline} metric_facts={context.metric_facts} />}
            {tab === 'decision' && <DecisionTab timeline={context.timeline} />}
            {tab === 'evidence' && <EvidenceTab evidence={context.evidence} onOpenDocument={onOpenDocument} />}
            {tab === 'insight' && <InsightTab entityId={context.entity_id} contextInsight={context.insight} />}
          </>
        )}
      </div>

      <div className="panel-footer">
        <span className={`source-dot ${live ? 'live' : 'mock'}`} />
        {live ? '来自后端实时数据' : '演示数据（后端未连接）'}
        {context && !loading && tab === 'decision' && decisionCount > 0 && (
          <span className="footer-count">{decisionCount} 项决策</span>
        )}
      </div>
    </aside>
  )
}
