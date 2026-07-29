"""
证据调和模块 - 处理新旧文档证据冲突
Layer 1: 置信度衰减（自动，无 LLM）
Layer 2: 冲突检测（LLM 辅助）
Layer 3: 共识保护（规则）
"""
import uuid
from datetime import datetime, timezone

from app import database as db
from app.llm_client import generate_json, LLMError


async def reconcile_evidence(entity_id: str, new_doc_id: str, new_doc_summary: str):
    """
    对新导入文档与已有证据进行调和。

    Layer 1 - 置信度衰减（自动，无 LLM）:
      effective_score = base_score * max(0.3, 1 - 0.05 * weeks_since_publish)

    Layer 2 - 冲突检测（LLM 辅助）:
      对 score >= 3.0 的旧证据，询问 LLM 新旧结论关系

    Layer 3 - 共识保护（规则）:
      如果 >= 3 个文档支持同一归因，单篇新文档的"推翻"不自动执行
    """
    # Layer 1: 置信度衰减
    _apply_confidence_decay(entity_id)

    # Layer 2: 冲突检测
    await _detect_conflicts(entity_id, new_doc_id, new_doc_summary)


def _apply_confidence_decay(entity_id: str):
    """
    Layer 1: 对所有证据应用时间衰减
    effective_score = base_score * max(0.3, 1 - 0.05 * weeks_since_publish)
    """
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT evidence_id, importance_score, published_at, effective_score FROM evidence_links WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()

        now = datetime.now(timezone.utc)

        for row in rows:
            base_score = row["importance_score"]
            published_at = row["published_at"]

            if not published_at:
                # 没有发布时间，使用基础分数
                effective = base_score
            else:
                try:
                    pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    weeks_since = max(0, (now - pub_date).days / 7.0)
                    decay_factor = max(0.3, 1 - 0.05 * weeks_since)
                    effective = base_score * decay_factor
                except (ValueError, TypeError):
                    effective = base_score

            conn.execute(
                "UPDATE evidence_links SET effective_score = ? WHERE evidence_id = ?",
                (effective, row["evidence_id"]),
            )

        conn.commit()
    finally:
        conn.close()


async def _detect_conflicts(entity_id: str, new_doc_id: str, new_doc_summary: str):
    """
    Layer 2 + Layer 3: 冲突检测与共识保护
    """
    conn = db.get_connection()
    try:
        # 获取高分旧证据 (score >= 3.0)
        old_evidence = conn.execute(
            """SELECT evidence_id, doc_title, importance_score, document_id
               FROM evidence_links
               WHERE entity_id = ? AND importance_score >= 3.0 AND document_id != ?""",
            (entity_id, new_doc_id),
        ).fetchall()

        if not old_evidence:
            return

        # Layer 3: 共识保护 - 统计支持同一实体的文档数
        support_count = conn.execute(
            "SELECT COUNT(DISTINCT document_id) as cnt FROM evidence_links WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()["cnt"]

    finally:
        conn.close()

    # Layer 2: 对每条高分旧证据进行 LLM 冲突检测
    for old_ev in old_evidence:
        old_summary = old_ev["doc_title"] or ""
        if not old_summary:
            continue

        try:
            relation = await _classify_evidence_relation(new_doc_summary, old_summary)
        except (LLMError, TimeoutError, Exception):
            continue  # LLM 不可用时跳过冲突检测

        if relation == "部分矛盾":
            _update_evidence_score(old_ev["evidence_id"], factor=0.6, status="PARTIALLY_SUPERSEDED")
        elif relation == "完全推翻":
            # Layer 3: 共识保护
            if support_count >= 3:
                # 不自动执行，标记为 NEEDS_REVIEW
                _mark_needs_review(entity_id, old_ev, new_doc_id, new_doc_summary)
            else:
                _update_evidence_score(old_ev["evidence_id"], factor=0.3, status="DISPUTED")
        # 一致/补充: 不做修改


async def _classify_evidence_relation(new_summary: str, old_summary: str) -> str:
    """调用 LLM 判断新旧证据关系"""
    prompt = f"""请判断以下两个文档结论的关系。

新文档结论: {new_summary}
旧证据: {old_summary}

请返回 JSON 格式:
{{"relation": "一致/补充/部分矛盾/完全推翻"}}

判断标准:
- 一致: 新旧结论完全吻合
- 补充: 新文档补充了旧证据未涉及的信息
- 部分矛盾: 新文档部分内容与旧证据冲突
- 完全推翻: 新文档结论与旧证据完全相反
"""
    result = await generate_json(prompt, timeout=10.0)
    return result.get("relation", "一致")


def _update_evidence_score(evidence_id: int, factor: float, status: str):
    """更新证据分数并标记状态"""
    conn = db.get_connection()
    try:
        conn.execute(
            """UPDATE evidence_links
               SET importance_score = importance_score * ?,
                   effective_score = COALESCE(effective_score, importance_score) * ?,
                   superseded_by = ?
               WHERE evidence_id = ?""",
            (factor, factor, status, evidence_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_needs_review(entity_id: str, old_ev, new_doc_id: str, new_doc_summary: str):
    """共识保护: 标记为需要人工审核"""
    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    db.insert_review_queue(
        review_id=review_id,
        entity_id=entity_id,
        conflict_type="EVIDENCE_CONFLICT",
        description=f"新文档'{new_doc_summary}'可能推翻旧证据'{old_ev['doc_title']}'，但有多文档共识保护",
        old_value=old_ev["doc_title"] or "",
        new_value=new_doc_summary,
    )
