import type { TimelineEvent } from '../../types'
import { OUTCOME_LABEL } from '../../lib/labels'

interface Props {
  timeline: TimelineEvent[]
}

export default function DecisionTab({ timeline }: Props) {
  const decisions = timeline
    .filter((evt) => evt.decision)
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((evt) => ({
      key: evt.event_id,
      occurred_at: evt.occurred_at,
      action: evt.decision!.action,
      owner: evt.decision!.owner,
      outcome: evt.decision!.outcome,
      outcome_detail: evt.decision!.outcome_detail,
      attribution: evt.attribution,
    }))

  if (decisions.length === 0) {
    return <div className="tab-empty">暂无关联决策</div>
  }

  return (
    <div className="decision-list">
      {decisions.map((d) => (
        <div key={d.key} className="decision-card">
          <div className="decision-head">
            <span className="decision-date">{d.occurred_at}</span>
            <span className={`badge badge-outcome o-${d.outcome.toLowerCase()}`}>
              {OUTCOME_LABEL[d.outcome]}
            </span>
          </div>
          <div className="decision-action">{d.action}</div>
          <div className="decision-owner">责任人：{d.owner}</div>
          {d.outcome_detail && (
            <div className="decision-detail">
              <span className="detail-label">结果</span>
              {d.outcome_detail}
            </div>
          )}
          {d.attribution && (
            <div className="decision-detail">
              <span className="detail-label">归因</span>
              {d.attribution}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
