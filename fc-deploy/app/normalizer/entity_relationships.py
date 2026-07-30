from __future__ import annotations
"""
跨文档实体关系模块 - 提取和存储实体间因果关系
Tier 1 (confidence 0.9): LLM 显式因果陈述
Tier 2 (confidence 0.6): LLM 推断
Tier 3 (confidence 0.3): 时间共现（不写入主表，存 candidates）
"""
import uuid
from datetime import datetime, timezone

from app import database as db
from app.normalizer.entity_normalizer import normalize_entity


async def extract_and_store_relationships(extraction_result: dict, doc_id: str):
    """
    从提取结果中抽取实体关系并存储。

    Tier 1 (confidence 0.9): 显式因果陈述
      - LLM 输出 causally_related_entities with relation_type
      - 直接存入 entity_relationships 表

    Tier 2 (confidence 0.6): LLM 推断
      - 从 causally_related_entities 中推断的间接关系
      - source='llm_inferred'

    Tier 3 (confidence 0.3): 时间共现
      - 同周 ±3天: A=FLUCTUATION + B=DECISION → candidate
      - 仅 >= 2 次共现后升级为 Tier 2
      - 存入 relationship_candidates 表
    """
    # Tier 1 & 2: 从 causally_related_entities 提取
    causal_entities = extraction_result.get("causally_related_entities", [])

    for item in causal_entities:
        source_name = item.get("source_entity", "")
        target_name = item.get("target_entity", "")
        relation_type = item.get("relation_type", "CORRELATED")
        is_explicit = item.get("explicit", False)

        if not source_name or not target_name:
            continue

        # 标准化实体名
        source_id = normalize_entity(source_name, "OBJECT")
        target_id = normalize_entity(target_name, "OBJECT")

        if source_id == target_id:
            continue

        confidence = 0.9 if is_explicit else 0.6
        source_label = "explicit" if is_explicit else "llm_inferred"

        rel_id = f"rel_{uuid.uuid4().hex[:12]}"
        db.insert_entity_relationship(
            rel_id=rel_id,
            source_entity_id=source_id,
            target_entity_id=target_id,
            relation_type=_normalize_relation_type(relation_type),
            confidence=confidence,
            source=source_label,
            evidence_doc_id=doc_id,
        )

    # Tier 3: 时间共现检测
    _detect_temporal_co_occurrence(extraction_result, doc_id)


def _detect_temporal_co_occurrence(extraction_result: dict, doc_id: str):
    """
    Tier 3: 检测时间共现关系
    同文档中 A=FLUCTUATION + B=DECISION → 候选关系
    """
    events = extraction_result.get("timeline_extraction", [])
    if len(events) < 2:
        return

    fluctuations = []
    decisions = []

    for event in events:
        etype = event.get("event_type", "")
        entity = event.get("primary_entity", "")
        if not entity:
            continue
        if etype == "FLUCTUATION":
            fluctuations.append(entity)
        elif etype == "DECISION":
            decisions.append(entity)

    # 对每对 (FLUCTUATION, DECISION) 创建候选
    for fluc_entity in fluctuations:
        for dec_entity in decisions:
            if fluc_entity == dec_entity:
                continue

            source_id = normalize_entity(fluc_entity, "OBJECT")
            target_id = normalize_entity(dec_entity, "OBJECT")

            if source_id == target_id:
                continue

            _upsert_candidate(source_id, target_id)


def _upsert_candidate(entity_a: str, entity_b: str):
    """创建或更新关系候选（增加共现计数）"""
    conn = db.get_connection()
    try:
        # 确保排序一致（避免 A-B 和 B-A 重复）
        a, b = sorted([entity_a, entity_b])

        existing = conn.execute(
            "SELECT candidate_id, co_occurrence_count FROM relationship_candidates WHERE entity_a = ? AND entity_b = ?",
            (a, b),
        ).fetchone()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            new_count = existing["co_occurrence_count"] + 1
            conn.execute(
                "UPDATE relationship_candidates SET co_occurrence_count = ?, last_seen = ? WHERE candidate_id = ?",
                (new_count, now, existing["candidate_id"]),
            )

            # 升级: >= 2 次共现后升级为 Tier 2 关系
            if new_count >= 2:
                _upgrade_candidate_to_relationship(a, b, existing["candidate_id"])
        else:
            candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO relationship_candidates (candidate_id, entity_a, entity_b, co_occurrence_count, first_seen, last_seen)
                   VALUES (?, ?, ?, 1, ?, ?)""",
                (candidate_id, a, b, now, now),
            )

        conn.commit()
    finally:
        conn.close()


def _upgrade_candidate_to_relationship(entity_a: str, entity_b: str, candidate_id: str):
    """将候选关系升级为正式关系 (Tier 2)"""
    conn = db.get_connection()
    try:
        # 检查是否已存在正式关系
        existing = conn.execute(
            "SELECT rel_id FROM entity_relationships WHERE source_entity_id = ? AND target_entity_id = ? AND source = 'co_occurrence'",
            (entity_a, entity_b),
        ).fetchone()

        if not existing:
            rel_id = f"rel_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO entity_relationships (rel_id, source_entity_id, target_entity_id, relation_type, confidence, source, evidence_doc_id, created_at)
                   VALUES (?, ?, ?, 'CORRELATED', 0.6, 'co_occurrence', '', ?)""",
                (rel_id, entity_a, entity_b, datetime.now(timezone.utc).isoformat()),
            )

        conn.commit()
    finally:
        conn.close()


def _normalize_relation_type(relation_type: str) -> str:
    """标准化关系类型"""
    valid_types = {"CAUSED_BY", "LEADS_TO", "CORRELATED", "RESPONDS_TO"}
    upper = relation_type.upper().replace(" ", "_")
    if upper in valid_types:
        return upper
    return "CORRELATED"


def get_relationships_for_entity(entity_id: str, min_confidence: float = 0.5) -> list[dict]:
    """返回实体置信度阈值以上的关系"""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM entity_relationships
               WHERE (source_entity_id = ? OR target_entity_id = ?) AND confidence >= ?
               ORDER BY confidence DESC""",
            (entity_id, entity_id, min_confidence),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
