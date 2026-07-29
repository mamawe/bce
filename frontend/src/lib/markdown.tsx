// Lightweight markdown renderer (headers, tables, lists, hr, bold) that also
// scans text for known entities and wraps mentions in clickable highlighted
// spans. Implemented with React elements (not dangerouslySetInnerHTML) so
// entity spans are real, accessible, clickable nodes.

import { Fragment, type ReactNode } from 'react'
import type { Entity } from '../types'

interface TermIndex {
  regex: RegExp
  map: Map<string, Entity>
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// 生成允许空格的正则模式：去掉所有空格后，在每个字符之间插入 \s*
// 这样 "SKU宽度" → "S\s*K\s*U\s*宽\s*度"，能匹配 "SKU宽度"、"SKU 宽度" 等
function flexiblePattern(s: string): string {
  const ns = s.replace(/\s+/g, '')
  const escaped = escapeRegExp(ns)
  return escaped.split('').join('\\s*')
}

export function buildTermIndex(entities: Entity[]): TermIndex | null {
  const map = new Map<string, Entity>()
  const terms: string[] = []
  for (const ent of entities) {
    const names = [ent.entity_name, ...(ent.aliases ?? [])]
    for (const name of names) {
      const trimmed = name.trim()
      const key = trimmed.toLowerCase()
      const keyNs = key.replace(/\s+/g, '')
      if (key && !map.has(key)) {
        map.set(key, ent)
        terms.push(trimmed)
      }
      // 无空格 key 也映射，用于 renderInline 的回退查找
      if (keyNs && keyNs !== key && !map.has(keyNs)) {
        map.set(keyNs, ent)
      }
    }
  }
  if (terms.length === 0) return null
  // Longest first so "成交总额" wins over a shorter overlapping alias.
  terms.sort((a, b) => b.length - a.length)
  // 正则使用 flexiblePattern：允许名称中任意位置出现可选空格
  return {
    regex: new RegExp(`(${terms.map(flexiblePattern).join('|')})`, 'gi'),
    map,
  }
}

export interface InlineHandlers {
  index: TermIndex | null
  selectedId: string | null
  onEntityClick: (entity: Entity) => void
}

// Parse **bold** within a plain (non-entity) text segment.
function renderBold(text: string, keyBase: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`${keyBase}-b${i}`}>{part.slice(2, -2)}</strong>
    }
    return <Fragment key={`${keyBase}-t${i}`}>{part}</Fragment>
  })
}

// Split a text segment on entity mentions; wrap matches in clickable spans.
export function renderInline(
  text: string,
  h: InlineHandlers,
  keyBase = 'i',
): ReactNode[] {
  if (!h.index) return renderBold(text, keyBase)
  const segments = text.split(h.index.regex)
  return segments.map((seg, i) => {
    if (!seg) return <Fragment key={`${keyBase}-${i}`} />
    // 先精确查找，再无空格回退（处理 "SKU 宽度" → "sku宽度" 的映射）
    const segLower = seg.toLowerCase()
    const ent = h.index!.map.get(segLower) || h.index!.map.get(segLower.replace(/\s+/g, ''))
    if (ent) {
      const active = ent.entity_id === h.selectedId
      return (
        <span
          key={`${keyBase}-${i}`}
          className={`entity-hit${active ? ' is-active' : ''}`}
          title={`${ent.entity_name} · 点击查看业务上下文`}
          onClick={(e) => {
            e.stopPropagation()
            h.onEntityClick(ent)
          }}
        >
          {seg}
        </span>
      )
    }
    return <Fragment key={`${keyBase}-${i}`}>{renderBold(seg, `${keyBase}-${i}`)}</Fragment>
  })
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c.trim()))
}

function splitTableRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim())
}

export function renderMarkdown(
  md: string,
  h: InlineHandlers,
): ReactNode[] {
  const lines = md.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (trimmed === '') {
      i++
      continue
    }

    // Horizontal rule
    if (/^-{3,}$/.test(trimmed)) {
      blocks.push(<hr key={key++} className="md-hr" />)
      i++
      continue
    }

    // Headers
    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length
      const Tag = (`h${level + 1}` as unknown) as keyof JSX.IntrinsicElements
      blocks.push(
        <Tag key={key++} className={`md-h md-h${level}`}>
          {renderInline(heading[2], h, `h${key}`)}
        </Tag>,
      )
      i++
      continue
    }

    // Table (consecutive lines starting with |)
    if (trimmed.startsWith('|')) {
      const rows: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].trim())
        i++
      }
      const parsed = rows.map(splitTableRow)
      const body = parsed.filter((cells) => !isSeparatorRow(cells))
      const [head, ...rest] = body
      blocks.push(
        <div key={key++} className="md-table-wrap">
          <table className="md-table">
            {head && (
              <thead>
                <tr>
                  {head.map((cell, ci) => (
                    <th key={ci}>{renderInline(cell, h, `th${key}-${ci}`)}</th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {rest.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td key={ci}>{renderInline(cell, h, `td${key}-${ri}-${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    // Unordered list
    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''))
        i++
      }
      blocks.push(
        <ul key={key++} className="md-ul">
          {items.map((item, li) => (
            <li key={li}>{renderInline(item, h, `ul${key}-${li}`)}</li>
          ))}
        </ul>,
      )
      continue
    }

    // Ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''))
        i++
      }
      blocks.push(
        <ol key={key++} className="md-ol">
          {items.map((item, li) => (
            <li key={li}>{renderInline(item, h, `ol${key}-${li}`)}</li>
          ))}
        </ol>,
      )
      continue
    }

    // Paragraph: gather consecutive plain lines; a line ending with 2+ spaces
    // becomes a <br/> (markdown hard break), otherwise join with a space.
    const paraLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^-{3,}$/.test(lines[i].trim()) &&
      !/^#{1,4}\s+/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith('|') &&
      !/^[-*]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i])
      i++
    }
    const paraNodes: ReactNode[] = []
    paraLines.forEach((pl, pi) => {
      const hardBreak = /\s{2,}$/.test(pl)
      paraNodes.push(
        <Fragment key={`p${key}-${pi}`}>
          {renderInline(pl.trim(), h, `p${key}-${pi}`)}
          {hardBreak && pi < paraLines.length - 1 ? <br /> : ' '}
        </Fragment>,
      )
    })
    blocks.push(
      <p key={key++} className="md-p">
        {paraNodes}
      </p>,
    )
  }

  return blocks
}
