import { useState, useRef, useEffect, useCallback } from 'react'
import type { ChatMessage, CalculationInfo } from '../types'
import { askQuestion, askQuestionStream } from '../api'

const QUICK_QUESTIONS = [
  'GMV 最新值是多少？',
  '各品类毛利率排名',
  '肉类毛利率为什么下降？',
  '总体GMV最近5周趋势',
  '如果猪肉涨价 10% 会怎样？',
]

const QUESTION_TYPE_LABEL: Record<string, string> = {
  FACTUAL: '事实查询',
  AGGREGATION: '聚合统计',
  COMPARISON: '对比分析',
  ANALYTICAL: '归因分析',
  WHAT_IF: '情景模拟',
}

const CONFIDENCE_LABEL: Record<string, { text: string; cls: string }> = {
  high: { text: '高置信', cls: 'conf-high' },
  medium: { text: '中置信', cls: 'conf-medium' },
  low: { text: '低置信', cls: 'conf-low' },
}

interface Props {
  onClose: () => void
  onEntityClick?: (entityId: string) => void
}

// ─── SQL Block ─────────────────────────────────────────────────
function SQLBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea')
      textarea.value = sql
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="chat-sql-block">
      <div className="chat-sql-header">
        <span className="chat-sql-label">SQL</span>
        <button className="chat-sql-copy" onClick={handleCopy}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="chat-sql-code">{sql}</pre>
    </div>
  )
}

// ─── Result Table ──────────────────────────────────────────────
function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows || rows.length === 0) return null

  // Collect all unique keys from rows
  const allKeys = Array.from(
    new Set(rows.flatMap((row) => Object.keys(row))),
  )

  // Filter out internal/id columns for cleaner display
  const displayKeys = allKeys.filter(
    (k) => k !== 'id' && k !== 'source_doc_id' && k !== 'sensitivity_level',
  )

  // Format cell value
  const formatValue = (key: string, value: unknown): string => {
    if (value === null || value === undefined) return '-'
    if (typeof value === 'number') {
      // Percentage columns
      if (key.includes('pct') || key.includes('rate')) {
        return `${value}%`
      }
      // Large numbers
      if (Math.abs(value) >= 10000) {
        return value.toLocaleString('zh-CN', { maximumFractionDigits: 1 })
      }
      return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    }
    return String(value)
  }

  // Translate column headers
  const headerMap: Record<string, string> = {
    report_date: '日期',
    week_label: '周',
    category: '品类',
    merchant_type: '商户类型',
    metric_name: '指标',
    metric_value: '数值',
    metric_unit: '单位',
    wow_change_pct: '环比',
    yoy_change_pct: '同比',
    fluctuation_count: '波动次数',
    event_count: '事件数',
    decision_count: '决策数',
    top_attribution: '高频归因',
  }

  return (
    <div className="chat-result-table-wrapper">
      <div className="chat-result-table-scroll">
        <table className="chat-result-table">
          <thead>
            <tr>
              {displayKeys.map((key) => (
                <th key={key}>{headerMap[key] || key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {displayKeys.map((key) => (
                  <td key={key} className={typeof row[key] === 'number' ? 'num' : ''}>
                    {formatValue(key, row[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="chat-result-count">共 {rows.length} 行</div>
    </div>
  )
}

// ─── Calculation Card ──────────────────────────────────────────
function CalculationCard({ calculation }: { calculation: CalculationInfo }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="chat-calc-card">
      <div className="chat-calc-header" onClick={() => setExpanded(!expanded)}>
        <span className="chat-calc-icon">🧮</span>
        <span className="chat-calc-title">计算详情</span>
        <span className="chat-calc-toggle">{expanded ? '收起' : '展开'}</span>
      </div>
      {expanded && (
        <div className="chat-calc-body">
          {calculation.formula && (
            <div className="chat-calc-row">
              <span className="chat-calc-label">公式</span>
              <code className="chat-calc-formula">{calculation.formula}</code>
            </div>
          )}
          <div className="chat-calc-row">
            <span className="chat-calc-label">输入</span>
            <span className="chat-calc-value">
              {Object.entries(calculation.input).map(([k, v]) => (
                <span key={k} className="chat-calc-input-item">
                  {k}: {typeof v === 'number' ? v.toLocaleString() : String(v)}
                </span>
              ))}
            </span>
          </div>
          {calculation.result && (
            <div className="chat-calc-row">
              <span className="chat-calc-label">结果</span>
              <span className="chat-calc-result">
                {Object.entries(calculation.result).map(([k, v]) => (
                  <span key={k} className="chat-calc-result-item">
                    <span className="chat-calc-result-key">{k}:</span>
                    <span className="chat-calc-result-val">
                      {typeof v === 'number' ? v.toFixed(2) : String(v)}
                    </span>
                  </span>
                ))}
              </span>
            </div>
          )}
          <div className="chat-calc-explanation">{calculation.explanation}</div>
        </div>
      )}
    </div>
  )
}

// ─── Main ChatPanel ────────────────────────────────────────────

export default function ChatPanel({ onClose }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  const handleSend = useCallback(async (text?: string) => {
    const question = (text ?? input).trim()
    if (!question || loading) return

    setInput('')
    setLoading(true)
    setStreaming(false)

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: question,
      timestamp: Date.now(),
    }
    setMessages((prev) => [...prev, userMsg])

    const assistantId = `a-${Date.now()}`

    try {
      // Try streaming first
      setStreaming(true)
      const resp = await askQuestionStream(
        question,
        (partialText) => {
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === assistantId)
            if (existing) {
              return prev.map((m) =>
                m.id === assistantId ? { ...m, content: partialText } : m,
              )
            }
            return [
              ...prev,
              {
                id: assistantId,
                role: 'assistant' as const,
                content: partialText,
                timestamp: Date.now(),
              },
            ]
          })
        },
      )
      // Finalize with all metadata
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: resp.answer,
                question_type: resp.question_type,
                confidence: resp.confidence,
                fallback_used: resp.fallback_used,
                fallback_reason: resp.fallback_reason,
                response_time_ms: resp.response_time_ms,
                sql: resp.sql,
                rows: resp.rows,
                calculation: resp.calculation,
              }
            : m,
        ),
      )
    } catch {
      // Fallback to non-streaming endpoint
      setStreaming(false)
      try {
        const resp = await askQuestion(question)
        const assistantMsg: ChatMessage = {
          id: assistantId,
          role: 'assistant',
          content: resp.answer,
          question_type: resp.question_type,
          confidence: resp.confidence,
          fallback_used: resp.fallback_used,
          fallback_reason: resp.fallback_reason,
          response_time_ms: resp.response_time_ms,
          sql: resp.sql,
          rows: resp.rows,
          calculation: resp.calculation,
          timestamp: Date.now(),
        }
        setMessages((prev) => {
          const existing = prev.find((m) => m.id === assistantId)
          if (existing) {
            return prev.map((m) => (m.id === assistantId ? assistantMsg : m))
          }
          return [...prev, assistantMsg]
        })
      } catch (err) {
        const errMsg: ChatMessage = {
          id: assistantId,
          role: 'assistant',
          content: `抱歉，查询失败：${err instanceof Error ? err.message : '未知错误'}`,
          confidence: 'low',
          timestamp: Date.now(),
        }
        setMessages((prev) => {
          const existing = prev.find((m) => m.id === assistantId)
          if (existing) {
            return prev.map((m) => (m.id === assistantId ? errMsg : m))
          }
          return [...prev, errMsg]
        })
      }
    } finally {
      setStreaming(false)
      setLoading(false)
    }
  }, [input, loading])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div className="chat-title-row">
          <span className="chat-icon">💬</span>
          <h2 className="chat-title">智能问答</h2>
        </div>
        <button className="chat-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </div>

      <div className="chat-body" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">🔍</div>
            <p className="chat-empty-text">向 BCE 提问任何业务问题</p>
            <p className="chat-empty-hint">
              支持数值查询、排名对比、归因分析、情景模拟
            </p>
            <div className="chat-quick-list">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  className="chat-quick-btn"
                  onClick={() => handleSend(q)}
                  disabled={loading}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`chat-msg chat-msg-${msg.role}`}>
            <div className="chat-msg-content">
              {msg.content.split('\n').map((line, i) => (
                <p key={i}>{line}</p>
              ))}
            </div>

            {/* Structured data display for assistant messages */}
            {msg.role === 'assistant' && (
              <div className="chat-msg-structured">
                {msg.sql && <SQLBlock sql={msg.sql} />}
                {msg.rows && msg.rows.length > 0 && (
                  <ResultTable rows={msg.rows} />
                )}
                {msg.calculation && (
                  <CalculationCard calculation={msg.calculation} />
                )}
              </div>
            )}

            {msg.role === 'assistant' && (msg.confidence || msg.question_type) && (
              <div className="chat-msg-meta">
                {msg.question_type && (
                  <span className="chat-tag chat-tag-type">
                    {QUESTION_TYPE_LABEL[msg.question_type] || msg.question_type}
                  </span>
                )}
                {msg.confidence && (
                  <span className={`chat-tag ${CONFIDENCE_LABEL[msg.confidence]?.cls || ''}`}>
                    {CONFIDENCE_LABEL[msg.confidence]?.text || msg.confidence}
                  </span>
                )}
                {msg.fallback_used && (
                  <span className="chat-tag chat-tag-fallback">
                    降级{msg.fallback_reason ? `: ${msg.fallback_reason}` : ''}
                  </span>
                )}
                {msg.response_time_ms != null && (
                  <span className="chat-tag chat-tag-time">{msg.response_time_ms}ms</span>
                )}
              </div>
            )}
          </div>
        ))}

        {loading && !streaming && (
          <div className="chat-msg chat-msg-assistant">
            <div className="chat-typing streaming-dots">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
      </div>

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          placeholder="输入问题，如「各品类毛利率排名」"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
        />
        <button
          className="chat-send-btn"
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
        >
          {loading ? '思考中…' : '发送'}
        </button>
      </div>
    </div>
  )
}
