import { useEffect, useState } from 'react'
import type { Relationship } from '../types'
import { loadRelationships } from '../api'

const RELATION_LABEL: Record<string, string> = {
  CAUSED_BY: '因果',
  LEADS_TO: '导致',
  CORRELATED: '相关',
  RESPONDS_TO: '响应',
}

const RELATION_ARROW: Record<string, string> = {
  CAUSED_BY: '←',
  LEADS_TO: '→',
  CORRELATED: '↔',
  RESPONDS_TO: '→',
}

interface Props {
  entityId: string
  onEntityClick: (targetEntityId: string) => void
}

export default function RelationshipBar({ entityId, onEntityClick }: Props) {
  const [relationships, setRelationships] = useState<Relationship[]>([])

  useEffect(() => {
    let cancelled = false
    loadRelationships(entityId).then((rels) => {
      if (!cancelled) {
        setRelationships(rels.filter((r) => r.confidence >= 0.5))
      }
    })
    return () => {
      cancelled = true
    }
  }, [entityId])

  if (relationships.length === 0) return null

  return (
    <div className="relationship-bar">
      {relationships.map((rel) => (
        <button
          key={rel.rel_id}
          className="relationship-chip"
          onClick={() => onEntityClick(rel.target_entity_id)}
          title={`${rel.relation_type} (置信度 ${(rel.confidence * 100).toFixed(0)}%)`}
        >
          <span className="relationship-arrow">
            {RELATION_ARROW[rel.relation_type] ?? '→'}
          </span>
          <span className="relationship-target">{rel.target_entity_id}</span>
          <span className="relationship-type">
            ({RELATION_LABEL[rel.relation_type] ?? rel.relation_type})
          </span>
        </button>
      ))}
    </div>
  )
}
