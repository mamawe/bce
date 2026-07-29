import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Entity, EntityContext, EntityTreeNode } from './types'
import {
  checkDocumentExists,
  deleteDocument,
  getDocumentContent,
  getIngestStatus,
  ingestDocumentAsync,
  listDocuments,
  loadContext,
  loadEntities,
  loadEntityHierarchy,
  updateDocumentAsync,
} from './api'
import type { DocListItem } from './api'
import { REPORTS } from './data/reports'
import DocumentViewer from './components/DocumentViewer'
import ContextPanel from './components/ContextPanel'
import ChatPanel from './components/ChatPanel'
import EntityTree from './components/EntityTree'

type SidePanel = 'context' | 'chat' | 'tree' | null

// 判断当前选中的是否为已导入文档（非内置示例）
function isImportedDoc(key: string): boolean {
  return !REPORTS.some((r) => r.key === key)
}

export default function App() {
  const [entities, setEntities] = useState<Entity[]>([])
  const [live, setLive] = useState<boolean>(false)
  const [docKey, setDocKey] = useState<string>(REPORTS[0].key)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [context, setContext] = useState<EntityContext | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [sidePanel, setSidePanel] = useState<SidePanel>('context')
  const [treeData, setTreeData] = useState<EntityTreeNode>({} as EntityTreeNode)
  const [treeLive, setTreeLive] = useState<boolean>(false)

  // 导入/编辑文档模态框状态
  const [importOpen, setImportOpen] = useState<boolean>(false)
  // 编辑模式：null=新建导入，string=编辑此 doc_id
  const [editDocId, setEditDocId] = useState<string | null>(null)
  const [importFileName, setImportFileName] = useState<string>('')
  const [importContent, setImportContent] = useState<string>('')
  const [importLoading, setImportLoading] = useState<boolean>(false)
  const [importError, setImportError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 导入 Tab：local=本地文件, feishu=飞书知识库
  const [importTab, setImportTab] = useState<'local' | 'feishu'>('local')
  const [feishuSpaces, setFeishuSpaces] = useState<Array<{ space_id: string; name: string }>>([])
  const [feishuLoading, setFeishuLoading] = useState(false)
  const [feishuSyncing, setFeishuSyncing] = useState(false)
  const [feishuMsg, setFeishuMsg] = useState<string | null>(null)

  // Toast 通知
  const [toast, setToast] = useState<{ type: 'ok' | 'err' | 'info'; msg: string } | null>(null)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = useCallback((type: 'ok' | 'err' | 'info', msg: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({ type, msg })
    toastTimerRef.current = setTimeout(() => setToast(null), 5000)
  }, [])

  // 已导入文档列表
  const [importedDocs, setImportedDocs] = useState<DocListItem[]>([])
  // 当前文档内容
  const [docContent, setDocContent] = useState<string>(REPORTS[0].markdown)

  // 轮询取消标志
  const pollCancelRef = useRef<boolean>(false)

  const refreshImportedDocs = useCallback(() => {
    listDocuments().then(setImportedDocs).catch(() => {})
  }, [])

  // 加载当前选中文档的内容
  const loadDocContent = useCallback(async (key: string) => {
    const builtin = REPORTS.find((r) => r.key === key)
    if (builtin) {
      setDocContent(builtin.markdown)
      return
    }
    try {
      const doc = await getDocumentContent(key)
      setDocContent(doc.content)
    } catch {
      showToast('err', '加载文档内容失败')
    }
  }, [showToast])

  // docKey 变化时加载对应文档内容
  useEffect(() => {
    loadDocContent(docKey)
  }, [docKey, loadDocContent])

  // 当已导入文档列表变化时，如果有导入文档且当前选中的是示例报告，自动切换到最新的导入文档
  useEffect(() => {
    if (importedDocs.length > 0 && REPORTS.some((r) => r.key === docKey)) {
      // 按 doc_id 降序排列（doc_id 编码了年份和周数，如 doc_2026_w29 > doc_2026_w20）
      // 这样最新一期的报告排在最前
      const sorted = [...importedDocs].sort((a, b) =>
        b.doc_id.localeCompare(a.doc_id),
      )
      setDocKey(sorted[0].doc_id)
    }
  }, [importedDocs, docKey])

  useEffect(() => {
    let cancelled = false
    loadEntities().then((res) => {
      if (cancelled) return
      setEntities(res.data)
      setLive(res.live)
    })
    loadEntityHierarchy().then((res) => {
      if (cancelled) return
      setTreeData(res.data)
      setTreeLive(res.live)
    })
    refreshImportedDocs()
    return () => {
      cancelled = true
      pollCancelRef.current = true // 停止所有轮询
    }
  }, [refreshImportedDocs])

  const handleEntityClick = useCallback((entity: Entity) => {
    setSelectedId(entity.entity_id)
    setSidePanel('context')
    setLoading(true)
    setContext(null)
    loadContext(entity.entity_id).then((res) => {
      setContext(res.data)
      setLive(res.live)
      setLoading(false)
    }).catch(() => {
      setLoading(false)
      showToast('err', '加载实体上下文失败，请检查网络连接')
    })
  }, [showToast])

  const handleEntitySelectFromTree = useCallback((entityId: string) => {
    const entity = entities.find((e) => e.entity_id === entityId)
    if (entity) {
      handleEntityClick(entity)
    } else {
      setSelectedId(entityId)
      setSidePanel('context')
      setLoading(true)
      setContext(null)
      loadContext(entityId).then((res) => {
        setContext(res.data)
        setLive(res.live)
        setLoading(false)
      }).catch(() => {
        setLoading(false)
        showToast('err', '加载实体上下文失败，请检查网络连接')
      })
    }
  }, [entities, handleEntityClick])

  const handleClose = useCallback(() => {
    setSelectedId(null)
    setContext(null)
  }, [])

  const handleOpenDocument = useCallback((title: string) => {
    const doc = importedDocs.find((d) => d.title === title)
    if (doc) {
      setDocKey(doc.doc_id)
    }
  }, [importedDocs])

  // ─── 导入/编辑模态框 ──────────────────────────────────────────

  const openImport = useCallback(() => {
    setEditDocId(null)
    setImportFileName('')
    setImportContent('')
    setImportError(null)
    setImportLoading(false)
    setImportOpen(true)
  }, [])

  const openEdit = useCallback(async (docId: string) => {
    setEditDocId(docId)
    setImportError(null)
    setImportLoading(true)
    setImportOpen(true)
    try {
      const doc = await getDocumentContent(docId)
      setImportFileName(doc.title)
      setImportContent(doc.content)
    } catch {
      setImportError('加载文档内容失败')
    } finally {
      setImportLoading(false)
    }
  }, [])

  const closeImport = useCallback(() => {
    if (importLoading) return
    setImportOpen(false)
  }, [importLoading])

  // ─── 飞书知识库同步 ──────────────────────────────────────────
  const loadFeishuSpaces = useCallback(async () => {
    setFeishuLoading(true)
    setFeishuMsg(null)
    try {
      const res = await fetch('/api/v1/lark/spaces')
      const data = await res.json()
      setFeishuSpaces(data.spaces || [])
      if (!data.spaces?.length) setFeishuMsg('未找到知识库（需先在飞书后台开通 wiki 权限）')
    } catch {
      setFeishuMsg('无法连接飞书服务')
    } finally {
      setFeishuLoading(false)
    }
  }, [])

  const handleFileSelected = useCallback(async (file: File) => {
    setImportFileName(file.name.replace(/\.(md|markdown|txt)$/i, ''))
    setImportError(null)
    const reader = new FileReader()
    reader.onload = () => {
      setImportContent(String(reader.result || ''))
    }
    reader.onerror = () => {
      setImportError('文件读取失败')
    }
    reader.readAsText(file)
  }, [])

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleFileSelected(file)
    }
    e.target.value = ''
  }, [handleFileSelected])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const file = e.dataTransfer.files?.[0]
    if (file) {
      handleFileSelected(file)
    }
  }, [handleFileSelected])

  // 统一的轮询逻辑（新建和编辑共用）
  const pollTaskStatus = useCallback(async (taskId: string, title: string, onDone: () => void) => {
    pollCancelRef.current = false
    for (let i = 0; i < 60; i++) {
      if (pollCancelRef.current) return
      await new Promise((r) => setTimeout(r, 2000))
      if (pollCancelRef.current) return
      try {
        const status = await getIngestStatus(taskId)
        if (status.status === 'done') {
          const r = status.result
          const parts: string[] = [`「${title}」处理完成`]
          if (r) {
            if (r.entities_found) parts.push(`抽取 ${r.entities_found} 个实体`)
            if (r.events_extracted) parts.push(`${r.events_extracted} 个事件`)
          }
          showToast('ok', parts.join('，'))
          onDone()
          return
        }
        if (status.status === 'failed') {
          showToast('err', `「${title}」处理失败：${status.error || '未知错误'}`)
          return
        }
      } catch {
        // 继续轮询
      }
    }
    showToast('err', `「${title}」处理超时，请稍后刷新查看`)
  }, [showToast])

  const refreshAll = useCallback(() => {
    loadEntities().then((res) => { setEntities(res.data); setLive(res.live) })
    loadEntityHierarchy().then((res) => { setTreeData(res.data); setTreeLive(res.live) })
    refreshImportedDocs()
  }, [refreshImportedDocs])

  const handleFeishuSync = useCallback(async (spaceId: string) => {
    setFeishuSyncing(true)
    setFeishuMsg(null)
    try {
      const res = await fetch('/api/v1/lark/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ space_id: spaceId }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setFeishuMsg(`同步完成：${data.synced ?? 0} 篇文档已导入`)
      if (data.synced > 0) refreshAll()
    } catch {
      setFeishuMsg('同步失败，请检查后端服务')
    } finally {
      setFeishuSyncing(false)
    }
  }, [refreshAll])

  const handleSubmitImport = useCallback(async () => {
    const title = importFileName.trim()
    const content = importContent.trim()
    if (!title || !content) {
      setImportError('标题和内容不能为空')
      return
    }
    setImportLoading(true)
    setImportError(null)

    try {
      if (editDocId) {
        // ─── 编辑模式：更新文档 + 重新抽取 ───
        const { task_id } = await updateDocumentAsync(editDocId, title, content)
        setImportOpen(false)
        setImportLoading(false)
        showToast('info', `「${title}」正在后台重新抽取...`)
        pollTaskStatus(task_id, title, () => {
          refreshAll()
          loadDocContent(editDocId)
        })
      } else {
        // ─── 新建模式：检查重复 → 异步导入 ───
        const check = await checkDocumentExists(title)
        if (check.exists) {
          setImportError(`文档「${title}」已存在，无需重复导入`)
          setImportLoading(false)
          return
        }
        const { task_id } = await ingestDocumentAsync(title, content)
        setImportOpen(false)
        setImportLoading(false)
        showToast('info', `「${title}」正在后台导入中...`)
        pollTaskStatus(task_id, title, refreshAll)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setImportError(msg.includes('abort') || msg.includes('timeout') ? '操作超时，请稍后重试' : `操作失败：${msg}`)
      setImportLoading(false)
    }
  }, [importFileName, importContent, editDocId, showToast, pollTaskStatus, refreshAll, loadDocContent])

  // ─── 删除文档 ──────────────────────────────────────────────────

  const handleDeleteDoc = useCallback(async (docId: string) => {
    const doc = importedDocs.find((d) => d.doc_id === docId)
    const title = doc?.title || docId
    if (!window.confirm(`确定删除「${title}」吗？\n删除后不可恢复，关联的实体和事件也会被清除。`)) {
      return
    }
    try {
      // 先清除选中状态，避免 context panel 用旧数据触发请求
      setSelectedId(null)
      setContext(null)
      // 执行删除
      await deleteDocument(docId)
      showToast('ok', `「${title}」已删除`)
      // 如果删除的是当前文档，切换到最新的剩余文档
      if (docKey === docId) {
        const remaining = importedDocs
          .filter((d) => d.doc_id !== docId)
          .sort((a, b) => b.doc_id.localeCompare(a.doc_id))
        if (remaining.length > 0) {
          setDocKey(remaining[0].doc_id)
        } else {
          setDocKey(REPORTS[0].key)
        }
      }
      // 后台刷新，不阻塞 UI
      setTimeout(() => refreshAll(), 0)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      showToast('err', `删除失败：${msg}`)
    }
  }, [importedDocs, docKey, showToast, refreshAll])

  const doc = useMemo(() => ({ markdown: docContent }), [docContent])
  const currentIsImported = isImportedDoc(docKey)

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-left">
          <span className="logo-mark">B</span>
          <div className="brand-text">
            <span className="brand-name">BCE</span>
            <span className="brand-sub">Business Context Engine</span>
          </div>
        </div>
        <div className="topbar-center">
          <button
            className={`nav-btn ${sidePanel === 'tree' ? 'is-active' : ''}`}
            onClick={() => setSidePanel(sidePanel === 'tree' ? 'context' : 'tree')}
          >
            🗂 实体层级
          </button>
          <button
            className={`nav-btn ${sidePanel === 'chat' ? 'is-active' : ''}`}
            onClick={() => setSidePanel(sidePanel === 'chat' ? 'context' : 'chat')}
          >
            💬 智能问答
          </button>
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className="import-btn"
            onClick={openImport}
          >
            ＋ 导入文档
          </button>
          <label className="doc-select-label" htmlFor="doc-select">
            报告
          </label>
          <select
            id="doc-select"
            className="doc-select"
            value={docKey}
            onChange={(e) => setDocKey(e.target.value)}
          >
            {importedDocs.length === 0 && (
              <optgroup label="示例报告">
                {REPORTS.map((r) => (
                  <option key={r.key} value={r.key}>{r.label}</option>
                ))}
              </optgroup>
            )}
            {importedDocs.length > 0 && (
              <optgroup label="已导入文档">
                {[...importedDocs]
                  .sort((a, b) => b.doc_id.localeCompare(a.doc_id))
                  .map((d) => (
                    <option key={d.doc_id} value={d.doc_id}>{d.title}</option>
                  ))}
              </optgroup>
            )}
          </select>
          {currentIsImported && (
            <div className="doc-actions">
              <button
                type="button"
                className="doc-action-btn"
                title="编辑文档"
                onClick={() => openEdit(docKey)}
              >
                ✏️
              </button>
              <button
                type="button"
                className="doc-action-btn"
                title="删除文档"
                onClick={() => handleDeleteDoc(docKey)}
              >
                🗑
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="layout">
        <main className="doc-pane">
          <div className="doc-hint">
            阅读周报，点击文中<span className="hint-sample">高亮的指标</span>查看其业务上下文
          </div>
          <DocumentViewer
            markdown={doc.markdown}
            entities={entities}
            selectedId={selectedId}
            onEntityClick={handleEntityClick}
          />
        </main>

        {sidePanel === 'context' && selectedId && (
          <ContextPanel
            context={context}
            loading={loading}
            live={live}
            onClose={handleClose}
            onOpenDocument={handleOpenDocument}
          />
        )}

        {sidePanel === 'chat' && (
          <ChatPanel
            onClose={() => setSidePanel(selectedId ? 'context' : null)}
          />
        )}

        {sidePanel === 'tree' && (
          <EntityTree
            tree={treeData}
            live={treeLive}
            selectedId={selectedId}
            onEntityClick={handleEntitySelectFromTree}
            onClose={() => setSidePanel(selectedId ? 'context' : null)}
          />
        )}
      </div>

      {toast && (
        <div className={`toast toast-${toast.type}`}>
          <span className="toast-icon">
            {toast.type === 'ok' ? '✓' : toast.type === 'err' ? '✕' : 'ℹ'}
          </span>
          <span className="toast-msg">{toast.msg}</span>
          <button
            type="button"
            className="toast-close"
            onClick={() => setToast(null)}
          >
            ×
          </button>
        </div>
      )}

      {importOpen && (
        <div
          className="modal-overlay"
          onClick={closeImport}
          role="presentation"
        >
          <div
            className="modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={editDocId ? '编辑文档' : '导入文档'}
          >
            <div className="modal-header">
              <span className="modal-title">{editDocId ? '编辑文档' : '导入文档'}</span>
              <button
                type="button"
                className="modal-close"
                onClick={closeImport}
                disabled={importLoading}
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              {/* Tab 切换 */}
              {!editDocId && (
                <div className="import-tabs">
                  <button
                    type="button"
                    className={`import-tab ${importTab === 'local' ? 'active' : ''}`}
                    onClick={() => setImportTab('local')}
                  >
                    📁 本地文件
                  </button>
                  <button
                    type="button"
                    className={`import-tab ${importTab === 'feishu' ? 'active' : ''}`}
                    onClick={() => { setImportTab('feishu'); loadFeishuSpaces() }}
                  >
                    🔗 飞书知识库
                  </button>
                </div>
              )}

              {/* 飞书知识库 Tab */}
              {!editDocId && importTab === 'feishu' ? (
                <div className="feishu-sync-panel">
                  {feishuLoading && <p className="feishu-loading">加载知识库列表...</p>}
                  {!feishuLoading && feishuSpaces.length > 0 && (
                    <ul className="feishu-space-list">
                      {feishuSpaces.map((sp) => (
                        <li key={sp.space_id} className="feishu-space-item">
                          <span className="feishu-space-name">{sp.name || sp.space_id}</span>
                          <button
                            type="button"
                            className="modal-btn primary feishu-sync-btn"
                            onClick={() => handleFeishuSync(sp.space_id)}
                            disabled={feishuSyncing}
                          >
                            {feishuSyncing ? '同步中...' : '同步'}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {feishuMsg && <p className="feishu-msg">{feishuMsg}</p>}
                </div>
              ) : (
              <>
              {/* 编辑模式：标题可修改 + 内容可粘贴/编辑 */}
              {/* 新建模式：选文件或拖拽，标题从文件名提取 */}
              {editDocId ? (
                <>
                  <label className="import-field-label">标题</label>
                  <input
                    type="text"
                    className="import-title-input"
                    value={importFileName}
                    onChange={(e) => setImportFileName(e.target.value)}
                    disabled={importLoading}
                    placeholder="文档标题"
                  />
                  <label className="import-field-label">内容（Markdown）</label>
                  <textarea
                    className="import-content-textarea"
                    value={importContent}
                    onChange={(e) => setImportContent(e.target.value)}
                    disabled={importLoading}
                    placeholder="粘贴或编辑 Markdown 内容..."
                    rows={16}
                  />
                </>
              ) : (
                <>
                  <div
                    className={`import-drop-zone ${importFileName ? 'has-file' : ''}`}
                    onClick={() => fileInputRef.current?.click()}
                    onDrop={handleDrop}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation() }}
                    onDragEnter={(e) => { e.preventDefault(); e.stopPropagation() }}
                  >
                    {importFileName ? (
                      <div className="import-file-info">
                        <span className="import-file-icon">📄</span>
                        <span className="import-file-name">{importFileName}</span>
                        <button
                          type="button"
                          className="import-file-clear"
                          onClick={(e) => {
                            e.stopPropagation()
                            setImportFileName('')
                            setImportContent('')
                          }}
                          disabled={importLoading}
                        >
                          ×
                        </button>
                      </div>
                    ) : (
                      <div className="import-drop-hint">
                        <span className="import-drop-icon">📁</span>
                        <p>点击选择文件或拖拽到此处</p>
                        <p className="import-drop-formats">支持 .md / .markdown / .txt</p>
                      </div>
                    )}
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".md,.markdown,.txt"
                      onChange={handleFileInputChange}
                      style={{ display: 'none' }}
                    />
                  </div>
                  {importFileName && (
                    <>
                      <label className="import-field-label">标题（可修改）</label>
                      <input
                        type="text"
                        className="import-title-input"
                        value={importFileName}
                        onChange={(e) => setImportFileName(e.target.value)}
                        disabled={importLoading}
                      />
                    </>
                  )}
                </>
              )}
              </>
              )}
              {importError && <div className="modal-msg err">{importError}</div>}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="modal-btn secondary"
                onClick={closeImport}
                disabled={importLoading}
              >
                取消
              </button>
              <button
                type="button"
                className="modal-btn primary"
                onClick={handleSubmitImport}
                disabled={importLoading || !importContent.trim() || !importFileName.trim()}
              >
                {importLoading
                  ? (editDocId ? '保存中...' : '导入中...')
                  : (editDocId ? '保存并重新抽取' : '导入')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
