"""
API 路由 - BCE 核心接口
v2 新增：POST /ask 端点、实体层级 API、LLM 洞察
v3 新增：异步导入、重复检查
v4 新增：流式问答、实体关系、管道编排
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import database as db
from app.parser.document_parser import parse_markdown
from app.normalizer.entity_normalizer import invalidate_cache
from app.normalizer import entity_hierarchy
from app.normalizer.entity_relationships import get_relationships_for_entity
from app.timeline.timeline_builder import build_timeline_for_entity
from app.evidence.evidence_ranker import get_ranked_evidence
from app.api.ask_handler import handle_ask, classify_question, extract_entities_from_question
from app.api import precompute
from app.reasoning.llm_insight import generate_llm_insight
from app.llm_client import generate_stream
from app.auth.jwt_links import check_link_access
from app.auth.permissions import (
    get_user_max_sensitivity,
    check_entity_access,
    check_insight_access,
    filter_events_by_sensitivity,
    get_user_from_request,
    require_role_above,
)

router = APIRouter(prefix="/api/v1")

# 异步任务追踪（内存字典，重启后丢失）
_async_tasks: dict[str, dict] = {}
_MAX_TASKS = 200  # 防止内存无限增长


def _prune_tasks():
    """清理已完成/失败的任务，保留最近 _MAX_TASKS 条"""
    if len(_async_tasks) <= _MAX_TASKS:
        return
    done_keys = [k for k, v in _async_tasks.items() if v["status"] in ("done", "failed")]
    for k in done_keys[:len(_async_tasks) - _MAX_TASKS]:
        del _async_tasks[k]


# ─── Request/Response Models ────────────────────────────────────

class IngestRequest(BaseModel):
    title: str
    content: str
    source_url: str = ""
    async_mode: bool = True  # v3: 默认异步模式
    push_to: str = ""  # 飞书推送接收人 open_id（可选）


class IngestResponse(BaseModel):
    doc_id: str
    entities_found: int
    events_extracted: int
    decisions_extracted: int


class AskRequest(BaseModel):
    question: str
    context: dict | None = None


class PushGenerateRequest(BaseModel):
    doc_id: str
    user_id: str
    role: str = "viewer"
    push_id: str | None = None  # 可选：用于埋点关联，缺省时自动生成
    base_url: str = ""          # 可选：链接前缀，缺省用相对路径


# ─── Endpoints ──────────────────────────────────────────────────

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "bce", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/entities")
async def list_entities():
    """列出所有已知实体（含层级信息）"""
    entities = db.list_entities_with_hierarchy()
    all_aliases = db.get_all_aliases()
    result = []
    for e in entities:
        result.append({
            "entity_id": e["entity_id"],
            "entity_name": e["entity_name"],
            "category": e["category"],
            "parent_entity_id": e.get("parent_entity_id"),
            "level": e.get("level", 0),
            "sort_order": e.get("sort_order", 0),
            "aliases": all_aliases.get(e["entity_id"], []),
        })
    return {"entities": result}


@router.get("/entities/hierarchy")
async def get_entity_hierarchy():
    """获取实体层级树（用于前端展示）"""
    tree = entity_hierarchy.get_hierarchy_tree(max_depth=5)
    if not tree:
        return {"tree": {}, "message": "暂无实体层级数据"}
    return {"tree": tree}


@router.get("/context")
async def get_context(request: Request, entity_id: str = Query(..., description="实体ID")):
    """
    获取实体的完整上下文：时间线 + 证据 + 指标 + 层级信息
    v3 变更：LLM 洞察改为按需加载（/context/{entity_id}/insight），不再阻塞主请求
    v4 变更：可选权限过滤——请求头 X-User-Role 存在时按事件级敏感度过滤；
             缺省时返回全量数据（向后兼容当前前端）。
    """
    entity = db.get_entity_with_hierarchy(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")

    # 构建时间线（默认剔除已废弃的旧版本事件）
    timeline = build_timeline_for_entity(entity_id)
    timeline = [t for t in timeline if not t.get("deprecated")]

    # ── 可选权限过滤（demo/测试用，基于 X-User-Role 请求头）──
    user_role = request.headers.get("X-User-Role")
    if user_role:
        user = {
            "role": user_role,
            "max_sensitivity": get_user_max_sensitivity(user_role),
            "has_global_view": user_role in ("admin", "executive"),
            "categories": [],
        }
        access = check_entity_access(user, entity)
        if not access["allowed"]:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: {access['reason']}",
            )
        timeline = filter_events_by_sensitivity(timeline, user)

    # 获取排序后的证据
    evidence = get_ranked_evidence(entity_id, top_n=3)
    evidence_out = [
        {
            "doc_title": ev["doc_title"],
            "doc_url": ev["doc_url"],
            "importance_score": ev["importance_score"],
            "reason_code": ev["reason_code"],
        }
        for ev in evidence
    ]

    # 子实体贡献度（如果有层级）
    children_contribution = []
    if db.has_children(entity_id):
        children_contribution = entity_hierarchy.drilldown_contribution(entity_id)

    # 预计算指标
    metrics = precompute.get_metrics(entity_id)
    
    # v5: 从 metric_facts 宽表获取真实指标数据（用于前端摘要卡和趋势图）
    metric_facts = precompute.get_metric_facts_summary(entity_id)
    
    # v5.1: 所有品类最新一周数据（用于"各品类对比"场景）
    all_categories_latest = precompute.get_all_categories_latest()

    return {
        "entity_id": entity_id,
        "entity_name": entity["entity_name"],
        "category": entity["category"],
        "description": entity.get("description", ""),
        "parent_entity_id": entity.get("parent_entity_id"),
        "level": entity.get("level", 0),
        "timeline": timeline,
        "evidence": evidence_out,
        "insight": None,  # v3: 洞察按需加载，前端调 /context/{entity_id}/insight
        "metrics": metrics,
        "metric_facts": metric_facts,
        "all_categories_latest": all_categories_latest,
        "children_contribution": children_contribution,
    }


@router.get("/context/{entity_id}/insight")
async def get_insight(entity_id: str):
    """
    v3 新增：按需获取实体的 LLM 洞察。
    前端在用户切换到"洞察"tab 时才调用此端点。
    """
    entity = db.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")

    insight_result = await generate_llm_insight(entity_id)
    return insight_result


@router.post("/ask")
async def ask(req: AskRequest):
    """
    v2 新增：自然语言问答端点
    完整流程：意图分类 → 数据检索 → LLM 生成 → 回答校验 → 降级策略
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    result = await handle_ask(req.question, req.context)
    return result


@router.post("/ask/stream")
async def ask_stream(req: AskRequest):
    """
    v4 新增：SSE 流式问答端点
    1. 分类问题
    2. 如果规则型 handler 可回答 → 逐字符流式返回预计算答案
    3. 如果需要 LLM → 调用 LLM stream=True，转发 SSE chunks
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    question = req.question
    context = req.context or {}

    # v2 分类：先规则快速路径 + LLM 兜底
    from app.api.ask_handler import _classify_question_full
    question_type, handler_name = classify_question(question)
    if question_type == "UNKNOWN":
        question_type, handler_name = await _classify_question_full(question)

    # 规则型 handler 可以直接回答的类型（扩展以覆盖更多 v2 类型）
    rule_handlers = {"sql_factual", "precomputed", "metric_sql", "sql_comparison"}

    if handler_name in rule_handlers:
        # 规则型：先计算完整答案，再逐字符流式返回
        import time as _time
        _start_ms = int(_time.time() * 1000)
        result = await handle_ask(question, context)
        answer_text = result.get("answer", "")

        async def stream_rule_answer():
            # 逐字符发送
            for char in answer_text:
                yield f"data: {json.dumps({'type': 'chunk', 'content': char}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)  # 模拟打字效果
            # 元数据事件（含 sql/rows/calculation 供前端展示）
            elapsed = int(_time.time() * 1000) - _start_ms
            meta_event = {
                "type": "meta",
                "question_type": question_type,
                "confidence": result.get("confidence", "high"),
                "fallback_used": result.get("fallback_used", False),
                "response_time_ms": elapsed,
            }
            if result.get("sql"):
                meta_event["sql"] = result["sql"]
            if result.get("rows"):
                meta_event["rows"] = result["rows"]
            if result.get("calculation"):
                meta_event["calculation"] = result["calculation"]
            yield f"data: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_rule_answer(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # LLM 型：流式调用
    entities = extract_entities_from_question(question)
    entity_names = "、".join(e["entity_name"] for e in entities) if entities else "未知"

    # 收集上下文
    timeline_data = []
    if entities:
        for ent in entities[:3]:
            timeline_data.extend(build_timeline_for_entity(ent["entity_id"]))
        timeline_data.sort(key=lambda e: e.get("occurred_at", ""), reverse=True)
        timeline_data = timeline_data[:10]

    timeline_brief = [
        {"time": e.get("occurred_at"), "summary": e.get("summary"), "type": e.get("event_type")}
        for e in timeline_data
    ]

    system_prompt = "你是一个资深商业分析师助手。基于提供的数据简洁回答用户问题，使用中文。"
    user_prompt = f"相关实体: {entity_names}\n"
    if timeline_brief:
        user_prompt += f"时间线数据: {json.dumps(timeline_brief, ensure_ascii=False)}\n"
    user_prompt += f"用户问题: {question}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    async def stream_llm_answer():
        import time as _time
        _start_ms = int(_time.time() * 1000)
        async for chunk in generate_stream(messages):
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        # 元数据事件
        elapsed = int(_time.time() * 1000) - _start_ms
        meta_event = {
            "type": "meta",
            "question_type": question_type,
            "confidence": "medium",
            "fallback_used": False,
            "response_time_ms": elapsed,
        }
        yield f"data: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_llm_answer(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships_endpoint(entity_id: str, min_confidence: float = 0.5):
    """
    v4 新增：获取实体的跨文档关系
    返回置信度阈值以上的因果关系
    """
    entity = db.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")

    relationships = get_relationships_for_entity(entity_id, min_confidence)

    # 补充实体名称
    result = []
    for rel in relationships:
        source_ent = db.get_entity(rel["source_entity_id"])
        target_ent = db.get_entity(rel["target_entity_id"])
        result.append({
            "rel_id": rel["rel_id"],
            "source_entity_id": rel["source_entity_id"],
            "source_entity_name": source_ent["entity_name"] if source_ent else rel["source_entity_id"],
            "target_entity_id": rel["target_entity_id"],
            "target_entity_name": target_ent["entity_name"] if target_ent else rel["target_entity_id"],
            "relation_type": rel["relation_type"],
            "confidence": rel["confidence"],
            "source": rel["source"],
            "evidence_doc_id": rel["evidence_doc_id"],
        })

    return {"entity_id": entity_id, "relationships": result}


@router.get("/documents/check")
async def check_document(title: str = Query(..., description="文档标题")):
    """检查文档是否已存在（按标题匹配）"""
    existing = db.get_document_by_title(title)
    return {
        "exists": existing is not None,
        "doc_id": existing["doc_id"] if existing else None,
        "ingested_at": existing["ingested_at"] if existing else None,
    }


@router.post("/documents/ingest")
async def ingest_document(req: IngestRequest):
    """
    导入文档：解析 → LLM 提取 → 标准化 → 存储
    v3: 默认异步模式，立即返回任务 ID，后台处理 LLM 抽取
    """
    # 输入大小限制
    if len(req.content) > 500_000:  # 500KB limit
        raise HTTPException(413, detail="文档内容超过 500KB 限制")

    # 解析 Markdown
    parsed = parse_markdown(req.content)
    doc_title = req.title or parsed.metadata.title or "Untitled"

    # 生成 doc_id
    doc_id = _generate_doc_id(doc_title, parsed.metadata.date)

    # 存储原始文档（立即完成）
    db.insert_document(
        doc_id=doc_id,
        title=doc_title,
        content=req.content,
        source_url=req.source_url,
        ingested_at=datetime.now(timezone.utc).isoformat(),
    )

    if req.async_mode:
        # 异步模式：立即返回，后台处理
        task_id = str(uuid.uuid4())
        _async_tasks[task_id] = {
            "status": "processing",
            "doc_id": doc_id,
            "title": doc_title,
            "result": None,
            "error": None,
        }
        asyncio.create_task(_process_ingest_async(task_id, req, doc_id, doc_title))
        return {"task_id": task_id, "status": "accepted", "doc_id": doc_id}

    # 同步模式（兼容旧调用）
    result = await _run_ingest_pipeline(req, doc_id, doc_title)
    return result


@router.get("/documents/ingest/{task_id}/status")
async def get_ingest_status(task_id: str):
    """查询异步导入任务状态"""
    if task_id not in _async_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return _async_tasks[task_id]


@router.get("/documents")
async def list_documents():
    """列出已导入的文档"""
    docs = db.list_documents()
    return {"documents": docs}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """获取单个文档的完整内容"""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    return doc


@router.put("/documents/{doc_id}")
async def update_document(doc_id: str, req: IngestRequest):
    """
    更新文档：修改标题/内容 → 清除旧抽取数据 → 重新异步抽取
    """
    existing = db.get_document(doc_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    doc_title = req.title or "Untitled"

    # 更新文档内容
    db.update_document(doc_id, doc_title, req.content, req.source_url)

    # 清除旧的抽取数据（时间线、证据、决策），保留文档行
    _cleanup_extraction_data(doc_id)

    # 重新异步抽取
    task_id = str(uuid.uuid4())
    _async_tasks[task_id] = {
        "status": "processing",
        "doc_id": doc_id,
        "title": doc_title,
        "result": None,
        "error": None,
    }
    asyncio.create_task(_process_ingest_async(task_id, req, doc_id, doc_title))
    return {"task_id": task_id, "status": "accepted", "doc_id": doc_id}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档及其所有关联数据"""
    existing = db.get_document(doc_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    db.delete_document(doc_id)
    return {"deleted": doc_id}


# ─── Push Links & Analytics (v4 安全加固 + 埋点) ─────────────────

@router.get("/view/{doc_id}")
async def view_pushed_document(doc_id: str, auth: str = Query(..., description="JWT auth token")):
    """
    推送链接落地页：校验 JWT + 实时复查 DB 权限。
    - token 过期 / 篡改 / 用户已停用 → 403
    - 校验通过记录 'clicked' 埋点事件，返回文档内容
    """
    access = check_link_access(auth, db)
    if not access.get("allowed"):
        reason = access.get("reason", "access_denied")
        raise HTTPException(status_code=403, detail=f"Access denied: {reason}")

    # token 中的 doc_id 必须与路径一致，防止替换文档 ID 越权
    if access.get("doc_id") != doc_id:
        raise HTTPException(status_code=403, detail="Access denied: doc_mismatch")

    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    # 埋点：记录点击事件（push_id 从 token payload 取，缺省回退到 doc_id）
    try:
        from app.auth.jwt_links import validate_push_link
        payload = validate_push_link(auth)
        push_id = payload.get("push_id") or doc_id
    except Exception:
        push_id = doc_id
    db.record_push_event(push_id=push_id, doc_id=doc_id, user_id=access.get("user_id"), event_type="clicked")

    return {
        "doc_id": doc_id,
        "title": doc.get("title"),
        "content": doc.get("content"),
        "source_url": doc.get("source_url"),
        "ingested_at": doc.get("ingested_at"),
        "viewer": {"user_id": access.get("user_id"), "reason": access.get("reason")},
    }


@router.post("/push/generate")
async def generate_push(req: PushGenerateRequest):
    """
    生成文档推送链接（测试 / 演示用）。
    - 确保用户存在（供点击时实时权限复查）
    - 记录 'sent' 埋点事件
    - 返回带 7 天过期 JWT 的签名链接
    """
    doc = db.get_document(req.doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {req.doc_id}")

    # 确保用户存在且活跃，否则点击时实时校验会拒绝
    if db.get_user(req.user_id) is None:
        db.upsert_user(req.user_id, display_name=req.user_id, role=req.role, is_active=True)

    push_id = req.push_id or f"push_{uuid.uuid4().hex[:8]}"

    # 生成签名链接（JWT 内含 push_id 供点击埋点关联）
    link = _generate_signed_link(req.base_url, req.doc_id, req.user_id, req.role, push_id)

    # 埋点：记录发送事件
    db.record_push_event(push_id=push_id, doc_id=req.doc_id, user_id=req.user_id, event_type="sent")

    return {"push_id": push_id, "doc_id": req.doc_id, "user_id": req.user_id, "link": link}


@router.get("/analytics/push/summary")
async def push_analytics_summary():
    """整体推送统计：总发送、总点击、平均点击率"""
    return db.get_push_summary()


@router.get("/analytics/push/{push_id}")
async def push_analytics(push_id: str):
    """单条推送的点击统计"""
    stats = db.get_push_stats(push_id)
    if stats["sent"] == 0 and stats["clicked"] == 0 and stats["viewed"] == 0:
        raise HTTPException(status_code=404, detail=f"No events found for push_id: {push_id}")
    return stats


# ─── Insights (洞察收集) ─────────────────────────────────────────
#
# v5 修复记录：
# - submit_insight：异步任务化（原文立即入库，LLM 拆解后台进行）
# - 长度限制 + XSS 清洗（bleach）
# - 修复 canonical_name bug → entity_name
# - 片段继承洞察的 entity_id/metric_snapshot 上下文
# - 全链路权限校验：submit/get/list/distill 均需登录
# - distill 使用 author_id 分层抽样 + sample_hash 去重（24h 内相同样本不重复归纳）
# - distill 时把 entity_id 转成 entity_name 人话化展示给 LLM

_INSIGHT_MAX_TEXT_LEN = 5000  # 单条洞察原文最大长度


class InsightSubmitRequest(BaseModel):
    author_id: str
    raw_text: str
    push_id: str | None = None
    doc_id: str | None = None
    entity_id: str | None = None
    metric_snapshot: str | None = None


async def _process_insight_async(task_id: str, insight_id: str, req: InsightSubmitRequest,
                                   clean_text: str, entity_name: str):
    """
    后台异步处理洞察拆解。
    - 调用 LLM 拆解分类
    - 失败时降级为单条"未分类"片段（保证原文不丢）
    - 更新任务状态 + 洞察 status 字段
    """
    from app.reasoning.insight_processor import split_and_classify

    try:
        db.update_insight_status(insight_id, status="processing")
        _async_tasks[task_id]["status"] = "processing"

        fragments = await split_and_classify(
            raw_text=clean_text,
            entity_name=entity_name,
            metric_snapshot=req.metric_snapshot or "",
        )

        # 片段继承洞察的上下文（保证片段不丢关联）
        db.insert_insight_fragments(
            insight_id=insight_id,
            author_id=req.author_id,
            fragments=fragments,
            entity_id=req.entity_id,
            metric_snapshot=req.metric_snapshot,
        )

        db.update_insight_status(insight_id, status="processed")
        _async_tasks[task_id]["status"] = "done"
        _async_tasks[task_id]["result"] = {
            "fragments_count": len(fragments),
            "categories": [f["category"] for f in fragments],
        }
    except Exception as e:
        # 失败时降级：原文已入库，补一条"未分类"片段保证可查询
        try:
            db.insert_insight_fragments(
                insight_id=insight_id,
                author_id=req.author_id,
                fragments=[{"category": "未分类", "content": clean_text}],
                entity_id=req.entity_id,
                metric_snapshot=req.metric_snapshot,
            )
            db.update_insight_status(insight_id, status="failed", error_msg=str(e)[:500])
        except Exception:
            pass
        _async_tasks[task_id]["status"] = "failed"
        _async_tasks[task_id]["error"] = str(e)[:500]
    finally:
        _prune_tasks()


@router.post("/insights/submit")
async def submit_insight(req: InsightSubmitRequest, request: Request):
    """
    提交一条业务洞察（异步处理）。
    - 权限校验：需登录用户
    - 输入验证：长度限制 + XSS 清洗
    - 原文立即入库（status=pending），返回 task_id
    - LLM 拆解在后台进行，完成后更新 status=processed
    - 拆解失败时降级为"未分类"片段，保证原文不丢
    """
    # 权限校验：洞察不公开，必须登录
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录后才能提交洞察")

    # 输入验证：长度限制
    if not req.raw_text or not req.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text 不能为空")
    if len(req.raw_text) > _INSIGHT_MAX_TEXT_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"文本过长（最大 {_INSIGHT_MAX_TEXT_LEN} 字符）",
        )

    # XSS 清洗：移除所有 HTML 标签（洞察是纯文本，不需要富文本）
    try:
        import bleach
        clean_text = bleach.clean(req.raw_text, tags=[], attributes={}, strip=True)
    except ImportError:
        # bleach 未安装时退化为基本清洗
        import re as _re
        clean_text = _re.sub(r"<[^>]+>", "", req.raw_text)

    # 解析实体名（用于 LLM 上下文，修复 canonical_name bug）
    entity_name = ""
    if req.entity_id:
        ent = db.get_entity(req.entity_id)
        if ent:
            # 修复：旧代码用 canonical_name（字段不存在），改为 entity_name
            entity_name = ent.get("entity_name") or ent.get("entity_id", "")

    # 原文立即入库（status=pending），保证不丢
    insight_id = f"insight_{uuid.uuid4().hex[:12]}"
    db.insert_insight(
        insight_id=insight_id,
        author_id=req.author_id,
        raw_text=clean_text,
        push_id=req.push_id,
        doc_id=req.doc_id,
        entity_id=req.entity_id,
        metric_snapshot=req.metric_snapshot,
        status="pending",
    )

    # 创建异步任务追踪
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    _async_tasks[task_id] = {
        "status": "processing",
        "insight_id": insight_id,
        "author_id": req.author_id,
        "result": None,
        "error": None,
    }

    # 后台处理（不阻塞请求）
    asyncio.create_task(_process_insight_async(
        task_id=task_id,
        insight_id=insight_id,
        req=req,
        clean_text=clean_text,
        entity_name=entity_name,
    ))

    return {
        "task_id": task_id,
        "insight_id": insight_id,
        "status": "processing",
        "message": "原文已入库，LLM 拆解在后台进行中",
    }


@router.get("/insights/submit/{task_id}/status")
async def get_insight_task_status(task_id: str, request: Request):
    """查询洞察提交异步任务状态"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")
    if task_id not in _async_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return _async_tasks[task_id]


@router.get("/insights/{insight_id}")
async def get_insight_detail(insight_id: str, request: Request):
    """查询单条洞察原文及其拆解片段（需登录 + 权限校验）"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")

    result = db.get_insight(insight_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Insight not found: {insight_id}")

    # 权限校验：作者本人 / 管理员 / 有实体权限
    access = check_insight_access(user, result)
    if not access["allowed"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: {access['reason']}",
        )
    return result


@router.get("/insights")
async def list_insights(
    request: Request,
    entity_id: str | None = None,
    author_id: str | None = None,
    limit: int = 50,
):
    """列出洞察（按实体或作者筛选），需登录"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")

    if entity_id:
        # 实体权限校验
        entity = db.get_entity(entity_id)
        if entity:
            access = check_entity_access(user, entity)
            if not access["allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied to entity: {access['reason']}",
                )
        rows = db.list_insights_by_entity(entity_id, limit)
        # 非管理员且非本人写的洞察需要逐条校验
        if user.get("role") not in ("admin", "executive"):
            rows = [r for r in rows if r.get("author_id") == user.get("user_id")]
        return rows
    if author_id:
        # 普通用户只能查自己写的
        if user.get("role") not in ("admin", "executive") and author_id != user.get("user_id"):
            raise HTTPException(status_code=403, detail="只能查看自己的洞察")
        return db.list_insights_by_author(author_id, limit)
    return {"total": db.count_insights()}


@router.get("/insights/stats/overview")
async def insights_overview(request: Request):
    """洞察收集统计：总数、各分类片段数（需登录）"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")
    return {
        "total_insights": db.count_insights(),
        "fragment_counts": db.count_fragments(),
    }


def _compute_sample_hash(fragments: list[dict]) -> str:
    """
    根据样本组成特征生成稳定指纹（用于去重）。
    不再用 fragment_id 集合（随机抽样几乎不会命中），
    改用 (作者数, 分类分布, 时间窗口) 作为指纹，
    这样相似组成的样本会被去重。

    指纹组成：
    - 作者数（如 4authors）
    - 分类分布按字典序拼接（如 "总结:4,策略:2,认知:2"）
    - 时间窗口（按天，如 2026-07-24）
    """
    import hashlib
    from collections import Counter

    if not fragments:
        return "empty"

    # 作者数
    authors = {f.get("author_id") for f in fragments if f.get("author_id")}
    author_part = f"{len(authors)}authors"

    # 分类分布（按分类名排序，避免顺序差异）
    cat_counts = Counter(f["category"] for f in fragments)
    cat_part = ",".join(f"{cat}:{cnt}" for cat, cnt in sorted(cat_counts.items()))

    # 时间窗口（按天）
    timestamps = [f.get("created_at", "") for f in fragments if f.get("created_at")]
    if timestamps:
        # 取最早时间的天
        days = sorted({ts[:10] for ts in timestamps if len(ts) >= 10})
        time_part = days[0] if days else "no_time"
    else:
        time_part = "no_time"

    fingerprint = f"{author_part}|{cat_part}|{time_part}"
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]


async def _process_distill_async(
    task_id: str,
    fragments: list[dict],
    sample_hash: str,
    category: str | None,
    user_id: str,
):
    """
    后台异步执行 LLM 归纳。
    - 片段 entity_id 人话化
    - 调用 LLM 归纳
    - 入库 insight_distillations
    - 更新任务状态
    """
    from app.reasoning.insight_processor import distill_fragments

    try:
        _async_tasks[task_id]["status"] = "processing"

        # 片段 entity_id 人话化
        entity_cache: dict[str, str] = {}
        for frag in fragments:
            eid = frag.get("entity_id")
            if eid and eid not in entity_cache:
                ent = db.get_entity(eid)
                entity_cache[eid] = ent.get("entity_name", eid) if ent else eid
            if eid:
                frag["entity_name"] = entity_cache[eid]

        # 调用 LLM 归纳
        result = await distill_fragments(fragments)

        distillation_id = f"distill_{uuid.uuid4().hex[:12]}"
        batch_source = f"manual_{category or 'all'}"
        db.insert_distillation(
            distillation_id=distillation_id,
            batch_source=batch_source,
            sample_size=len(fragments),
            category_breakdown=result["category_breakdown"],
            summary=result["summary"],
            raw_llm_output=result["raw"],
            sample_hash=sample_hash,
            time_range=result.get("time_range", ""),
            author_count=result.get("author_count", 0),
        )

        _async_tasks[task_id]["status"] = "done"
        _async_tasks[task_id]["result"] = {
            "distillation_id": distillation_id,
            "sample_size": len(fragments),
            "category_breakdown": result["category_breakdown"],
            "summary": result["summary"],
            "time_range": result.get("time_range", ""),
            "author_count": result.get("author_count", 0),
            "sample_hash": sample_hash,
        }
    except Exception as e:
        _async_tasks[task_id]["status"] = "failed"
        _async_tasks[task_id]["error"] = str(e)[:500]
    finally:
        _prune_tasks()


@router.post("/insights/distill")
async def distill_insights(
    request: Request,
    sample_size: int = 30,
    category: str | None = None,
    force: bool = False,
):
    """
    手动触发一次随机归纳（异步处理）。
    - 权限：dept_lead 及以上
    - 抽样：按 author_id 分层随机抽样
    - 去重：24h 内相似样本指纹不重复归纳（除非 force=True）
    - 异步：立即返回 task_id，后台 LLM 归纳，通过 /insights/distill/{task_id}/status 查询
    """
    user = get_user_from_request(request)
    require_role_above(user, "dept_lead")

    # 按作者分层抽样
    fragments = db.get_random_fragments_stratified(sample_size=sample_size, category=category)
    if not fragments:
        raise HTTPException(status_code=400, detail="没有可归纳的片段")

    # 计算 sample_hash（基于组成特征，而非 fragment_id 集合）
    sample_hash = _compute_sample_hash(fragments)

    # 去重检查（除非 force=True）
    if not force:
        recent = db.get_recent_distillation_by_hash(sample_hash, within_hours=24)
        if recent:
            return {
                "skipped": True,
                "reason": "24小时内已对相似样本做过归纳",
                "existing_distillation_id": recent["distillation_id"],
                "existing_summary": recent["summary"][:200],
                "sample_hash": sample_hash,
            }

    # 异步任务化：立即返回 task_id
    task_id = f"distill_task_{uuid.uuid4().hex[:12]}"
    _async_tasks[task_id] = {
        "status": "processing",
        "type": "distill",
        "sample_size": len(fragments),
        "sample_hash": sample_hash,
        "category": category,
        "triggered_by": user.get("user_id"),
        "result": None,
        "error": None,
    }

    asyncio.create_task(_process_distill_async(
        task_id=task_id,
        fragments=fragments,
        sample_hash=sample_hash,
        category=category,
        user_id=user.get("user_id"),
    ))

    return {
        "task_id": task_id,
        "status": "processing",
        "sample_size": len(fragments),
        "sample_hash": sample_hash,
        "message": "LLM 归纳在后台进行中，请轮询 /insights/distill/{task_id}/status 查询结果",
    }


@router.get("/insights/distill/{task_id}/status")
async def get_distill_task_status(task_id: str, request: Request):
    """查询 distill 异步任务状态"""
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")
    if task_id not in _async_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return _async_tasks[task_id]


@router.get("/insights/distill/list")
async def list_distillations(limit: int = 20, request: Request = None):
    """列出历史归纳产出（需登录）"""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")
    return db.list_distillations(limit)


def _generate_signed_link(base_url: str, doc_id: str, user_id: str, role: str, push_id: str) -> str:
    """生成带 push_id 的签名推送链接（复用 jwt_links 的密钥与过期策略）"""
    import time
    import jwt
    from app.auth.jwt_links import SECRET_KEY, ALGORITHM, LINK_EXPIRY_DAYS
    payload = {
        "doc_id": doc_id,
        "user_id": user_id,
        "role": role,
        "push_id": push_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + LINK_EXPIRY_DAYS * 86400,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return f"{base_url}/view/{doc_id}?auth={token}"


# ─── Helpers ────────────────────────────────────────────────────

def _cleanup_extraction_data(doc_id: str):
    """清除文档关联的抽取数据（时间线、证据、决策），保留文档行本身"""
    conn = db.get_connection()
    try:
        event_ids = [
            r["event_id"]
            for r in conn.execute(
                "SELECT event_id FROM timeline_events WHERE document_id = ?", (doc_id,)
            ).fetchall()
        ]
        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            conn.execute(f"DELETE FROM decisions WHERE event_id IN ({placeholders})", event_ids)
        conn.execute("DELETE FROM evidence_links WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM timeline_events WHERE document_id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def _generate_doc_id(title: str, date: str) -> str:
    """从标题和日期生成 doc_id，如 doc_2026_w12"""
    import re
    # 尝试从标题中提取年份和周数
    year_match = re.search(r"(\d{4})\s*年", title)
    week_match = re.search(r"第\s*(\d+)\s*周", title)

    if year_match and week_match:
        return f"doc_{year_match.group(1)}_w{int(week_match.group(1)):02d}"

    # 回退：用日期或 UUID
    if date:
        return f"doc_{date.replace('-', '')}"
    return f"doc_{uuid.uuid4().hex[:8]}"


async def _run_ingest_pipeline(req: IngestRequest, doc_id: str, doc_title: str) -> IngestResponse:
    """执行完整的 LLM 抽取管道（使用 pipeline 编排器）"""
    from app.pipeline import run_ingest_pipeline

    result = await run_ingest_pipeline(
        title=doc_title,
        content=req.content,
        source_url=req.source_url or None,
        push_to=req.push_to or None,
    )

    return IngestResponse(
        doc_id=result["doc_id"],
        entities_found=result["entities_found"],
        events_extracted=result["events_extracted"],
        decisions_extracted=result["decisions_extracted"],
    )


async def _process_ingest_async(task_id: str, req: IngestRequest, doc_id: str, doc_title: str):
    """后台异步处理 LLM 抽取"""
    try:
        result = await _run_ingest_pipeline(req, doc_id, doc_title)
        invalidate_cache()  # 导入完成后刷新实体缓存
        _async_tasks[task_id] = {
            "status": "done",
            "doc_id": doc_id,
            "title": doc_title,
            "result": {
                "entities_found": result.entities_found,
                "events_extracted": result.events_extracted,
                "decisions_extracted": result.decisions_extracted,
            },
            "error": None,
        }
    except Exception as e:
        _async_tasks[task_id] = {
            "status": "failed",
            "doc_id": doc_id,
            "title": doc_title,
            "result": None,
            "error": str(e),
        }
    finally:
        _prune_tasks()
