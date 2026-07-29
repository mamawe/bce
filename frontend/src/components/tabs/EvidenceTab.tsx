import { useState } from 'react'
import type { Evidence } from '../../types'
import { REASON_LABEL } from '../../lib/labels'

interface Props {
  evidence: Evidence[]
  onOpenDocument?: (title: string) => void
}

const DEFAULT_COUNT = 3

function Stars({ score, originalScore }: { score: number; originalScore?: number }) {
  const full = Math.max(0, Math.min(5, Math.round(score)))
  return (
    <span className="stars" title={`重要度 ${score.toFixed(1)} / 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={i < full ? 'star on' : 'star'}>
          ★
        </span>
      ))}
      {originalScore != null && originalScore !== score && (
        <span className="stars-original">({originalScore.toFixed(1)})</span>
      )}
    </span>
  )
}

export default function EvidenceTab({ evidence, onOpenDocument }: Props) {
  const [showAll, setShowAll] = useState(false)
  const [selectedDoc, setSelectedDoc] = useState<Evidence | null>(null)
  const [flagging, setFlagging] = useState(false)
  const [flagged, setFlagged] = useState(false)

  if (evidence.length === 0) {
    return <div className="tab-empty">暂无证据来源</div>
  }

  const sorted = [...evidence].sort(
    (a, b) => (b.effective_score ?? b.importance_score) - (a.effective_score ?? a.importance_score),
  )
  const visible = showAll ? sorted : sorted.slice(0, DEFAULT_COUNT)
  const hasMore = sorted.length > DEFAULT_COUNT

  const handleFlag = async () => {
    if (!selectedDoc || flagging) return
    setFlagging(true)
    try {
      await fetch(`/api/v1/evidence/${encodeURIComponent(selectedDoc.doc_title)}/flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      setFlagged(true)
    } catch {
      // Endpoint may not exist yet — silently ignore
    } finally {
      setFlagging(false)
    }
  }

  const handleSelectDoc = (ev: Evidence) => {
    setSelectedDoc(ev)
    setFlagged(false)
  }

  return (
    <div className="evidence">
      <div className="evidence-list">
        {visible.map((ev, i) => (
          <div key={`${ev.doc_title}-${i}`} className="evidence-item">
            <div className="evidence-rank">{i + 1}</div>
            <div className="evidence-body">
              <div
                className="evidence-title evidence-title-link"
                role="button"
                tabIndex={0}
                onClick={() => handleSelectDoc(ev)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') handleSelectDoc(ev)
                }}
              >
                {ev.doc_title}
                {ev.superseded_by && (
                  <span className="evidence-superseded-badge">已被更新</span>
                )}
              </div>
              <div className="evidence-meta">
                <Stars
                  score={ev.effective_score ?? ev.importance_score}
                  originalScore={ev.effective_score != null && ev.effective_score !== ev.importance_score ? ev.importance_score : undefined}
                />
                <span className={`badge badge-reason r-${ev.reason_code.toLowerCase()}`}>
                  {REASON_LABEL[ev.reason_code]}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
      {hasMore && (
        <button
          className="show-all-btn"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? '收起' : `展开全部（共 ${sorted.length} 条）`}
        </button>
      )}

      {/* Floating modal for selected document */}
      {selectedDoc && (
        <div
          className="evidence-modal-overlay"
          onClick={() => setSelectedDoc(null)}
          role="presentation"
        >
          <div
            className="evidence-modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={selectedDoc.doc_title}
          >
            <div className="evidence-modal-header">
              <span className="evidence-modal-title">{selectedDoc.doc_title}</span>
              <button
                type="button"
                className="evidence-modal-close"
                onClick={() => setSelectedDoc(null)}
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="evidence-modal-body">
              {selectedDoc.superseded_by && (
                <div className="evidence-superseded-badge evidence-superseded-badge-block">
                  已被更新：{selectedDoc.superseded_by}
                </div>
              )}
              <div className="evidence-modal-meta">
                <div className="evidence-modal-row">
                  <span className="evidence-modal-label">重要度</span>
                  <Stars
                    score={selectedDoc.effective_score ?? selectedDoc.importance_score}
                    originalScore={selectedDoc.effective_score != null && selectedDoc.effective_score !== selectedDoc.importance_score ? selectedDoc.importance_score : undefined}
                  />
                </div>
                <div className="evidence-modal-row">
                  <span className="evidence-modal-label">来源类型</span>
                  <span className={`badge badge-reason r-${selectedDoc.reason_code.toLowerCase()}`}>
                    {REASON_LABEL[selectedDoc.reason_code]}
                  </span>
                </div>
                {selectedDoc.doc_url && (
                  <div className="evidence-modal-row">
                    <span className="evidence-modal-label">文档路径</span>
                    <span className="evidence-modal-url">{selectedDoc.doc_url}</span>
                  </div>
                )}
              </div>
              <p className="evidence-modal-hint">
                该文档可在左侧文档查看器中阅读完整内容。
              </p>
            </div>
            <div className="evidence-modal-footer">
              {onOpenDocument && (
                <button
                  type="button"
                  className="evidence-modal-btn primary"
                  onClick={() => {
                    onOpenDocument(selectedDoc.doc_title)
                    setSelectedDoc(null)
                  }}
                >
                  在文档查看器中打开
                </button>
              )}
              <button
                type="button"
                className="evidence-flag-btn"
                onClick={handleFlag}
                disabled={flagging || flagged}
              >
                {flagged ? '已标记' : flagging ? '标记中…' : '标记过时'}
              </button>
              <button
                type="button"
                className="evidence-modal-btn secondary"
                onClick={() => setSelectedDoc(null)}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
