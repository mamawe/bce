"""
时间线构建器 - 将提取的事件按时间排序，关联决策，构建实体时间线
"""
import uuid
from app import database as db
from app.normalizer.entity_normalizer import normalize_entity


def build_timeline_for_entity(entity_id: str) -> list[dict]:
    """
    构建某实体的完整时间线
    返回按 occurred_at 排序的事件列表，每个事件附带关联的 decision
    v2: 查不到直接事件时，搜索同前缀和别名关联的实体事件
    """
    events = db.get_events_for_entity_and_related(entity_id)
    timeline = []

    # 批量获取所有决策，避免 N+1 查询
    event_ids = [event["event_id"] for event in events]
    decisions_map = db.get_decisions_for_events(event_ids)

    for event in events:
        decision = decisions_map.get(event["event_id"])
        entry = {
            "event_id": event["event_id"],
            "occurred_at": event["occurred_at"],
            "time_granularity": event["time_granularity"],
            "summary": event["summary"],
            "event_type": event["event_type"],
            "attribution": event["attribution"],
            "decision": None,
            "metric_value": event.get("metric_value"),
            "metric_unit": event.get("metric_unit"),
            "metric_delta": event.get("metric_delta"),
            "metric_delta_pct": event.get("metric_delta_pct"),
            "sensitivity_level": event.get("sensitivity_level", 1),
            "deprecated": bool(event.get("deprecated", 0)),
            "doc_version": event.get("doc_version", 1),
        }
        if decision:
            entry["decision"] = {
                "action": decision["action_taken"],
                "owner": decision["owner"],
                "outcome": decision["outcome"],
                "outcome_detail": decision["outcome_detail"],
            }
        timeline.append(entry)

    # 按时间排序
    timeline.sort(key=lambda x: x["occurred_at"])
    return timeline


def store_extracted_events(extraction: dict, doc_id: str, entity_mapping: dict,
                           doc_version: int = 1):
    """
    将 LLM 提取的时间线事件存入数据库
    entity_mapping: {normalized_name: entity_id} 的映射
    v2: primary_entity 未在 mapping 中时，回退到 normalize_entity 查找/创建实体
    v4: 写入 metric_* 字段与 doc_version
    """
    for i, event in enumerate(extraction.get("timeline_extraction", [])):
        primary_entity = event.get("primary_entity", "")
        entity_id = entity_mapping.get(primary_entity)

        # 回退：如果 primary_entity 不在 mapping 中，尝试 normalize_entity
        # 这处理 LLM 在 primary_entity 中使用与 entities_mentioned 不同名称的情况
        if not entity_id and primary_entity:
            entity_id = normalize_entity(primary_entity, "OBJECT")
            entity_mapping[primary_entity] = entity_id  # 缓存，避免重复 normalize

        if not entity_id:
            continue  # 跳过无法映射的事件

        event_id = f"evt_{doc_id}_{i:03d}"
        time_anchor = event.get("time_anchor", "")
        # 尝试标准化日期格式
        occurred_at = _normalize_date(time_anchor)

        db.insert_event(
            event_id=event_id,
            entity_id=entity_id,
            occurred_at=occurred_at,
            time_granularity="WEEK",  # 周报默认粒度为 WEEK
            summary=event.get("event_summary", ""),
            event_type=event.get("event_type", "FLUCTUATION"),
            attribution=event.get("attribution", ""),
            document_id=doc_id,
            metric_value=event.get("metric_value"),
            metric_unit=event.get("metric_unit"),
            metric_delta=event.get("metric_delta"),
            metric_delta_pct=event.get("metric_delta_pct"),
            doc_version=doc_version,
        )

        # 存储关联决策
        decision = event.get("decision", {})
        if decision and decision.get("action"):
            decision_id = f"dec_{doc_id}_{i:03d}"
            db.insert_decision(
                decision_id=decision_id,
                event_id=event_id,
                action_taken=decision.get("action", ""),
                owner=decision.get("owner", ""),
                outcome=decision.get("outcome", "PENDING"),
                outcome_detail=decision.get("outcome_detail", ""),
            )


def _normalize_date(date_str: str) -> str:
    """
    将各种日期格式标准化为 YYYY-MM-DD
    处理: 2026-03-22, 2026/03/22, 3/18, W12 等
    """
    if not date_str:
        return "1970-01-01"

    # 已经是标准格式
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str

    # 斜杠格式 2026/03/22
    if "/" in date_str and len(date_str) >= 8:
        return date_str.replace("/", "-")

    # 短格式 3/18 -> 需要年份上下文，这里简单处理
    # 返回原始字符串，让下游处理
    return date_str
