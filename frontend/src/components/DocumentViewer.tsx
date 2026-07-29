import { useMemo } from 'react'
import type { Entity } from '../types'
import { buildTermIndex, renderMarkdown } from '../lib/markdown'

interface Props {
  markdown: string
  entities: Entity[]
  selectedId: string | null
  onEntityClick: (entity: Entity) => void
}

export default function DocumentViewer({
  markdown,
  entities,
  selectedId,
  onEntityClick,
}: Props) {
  const content = useMemo(() => {
    const index = buildTermIndex(entities)
    return renderMarkdown(markdown, { index, selectedId, onEntityClick })
  }, [markdown, entities, selectedId, onEntityClick])

  return (
    <div className="doc-sheet">
      <article className="doc-content">{content}</article>
    </div>
  )
}
