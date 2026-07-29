import { useState, useCallback } from 'react'
import type { EntityTreeNode } from '../types'

interface Props {
  tree: EntityTreeNode
  live: boolean
  selectedId: string | null
  onEntityClick: (entityId: string) => void
  onClose: () => void
}

export default function EntityTree({ tree, live, selectedId, onEntityClick, onClose }: Props) {
  return (
    <div className="entity-tree-panel">
      <div className="tree-header">
        <div className="tree-title-row">
          <span className="tree-icon">🗂</span>
          <h2 className="tree-title">实体层级</h2>
        </div>
        <button className="tree-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </div>
      <div className="tree-body">
        {!live || !tree?.entity_id ? (
          <div className="tree-empty">
            <p>暂无层级数据</p>
            <p className="tree-empty-hint">导入文档后，实体会自动建立层级关系</p>
          </div>
        ) : (
          <TreeNode
            node={tree}
            depth={0}
            selectedId={selectedId}
            onEntityClick={onEntityClick}
          />
        )}
      </div>
      <div className="tree-footer">
        <span className={`source-dot ${live ? 'live' : 'mock'}`} />
        {live ? '实时层级数据' : '无层级数据'}
      </div>
    </div>
  )
}

interface TreeNodeProps {
  node: EntityTreeNode
  depth: number
  selectedId: string | null
  onEntityClick: (entityId: string) => void
}

function TreeNode({ node, depth, selectedId, onEntityClick }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 2) // 默认展开前 2 层
  const hasChildren = node.children && node.children.length > 0
  const isSelected = selectedId === node.entity_id

  const handleClick = useCallback(() => {
    if (node.entity_id && node.entity_id !== 'ROOT') {
      onEntityClick(node.entity_id)
    }
  }, [node.entity_id, onEntityClick])

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setExpanded((prev) => !prev)
  }, [])

  if (node.entity_id === 'ROOT') {
    // 虚拟根节点，只渲染子节点
    return (
      <div className="tree-root">
        {node.children?.map((child) => (
          <TreeNode
            key={child.entity_id}
            node={child}
            depth={depth}
            selectedId={selectedId}
            onEntityClick={onEntityClick}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="tree-node" style={{ marginLeft: depth > 0 ? 16 : 0 }}>
      <div
        className={`tree-node-row ${isSelected ? 'is-selected' : ''}`}
        onClick={handleClick}
      >
        {hasChildren ? (
          <button
            className="tree-toggle"
            onClick={handleToggle}
            aria-label={expanded ? '折叠' : '展开'}
          >
            {expanded ? '▾' : '▸'}
          </button>
        ) : (
          <span className="tree-toggle-placeholder" />
        )}
        <span
          className={`tree-node-name level-${node.level ?? 0}`}
          title={node.description || node.entity_name}
        >
          {node.entity_name}
        </span>
        {node.category && (
          <span className={`tree-node-badge cat-${node.category.toLowerCase()}`}>
            {node.category}
          </span>
        )}
      </div>

      {hasChildren && expanded && (
        <div className="tree-children">
          {node.children!.map((child) => (
            <TreeNode
              key={child.entity_id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onEntityClick={onEntityClick}
            />
          ))}
        </div>
      )}
    </div>
  )
}
