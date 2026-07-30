from __future__ import annotations
from typing import Optional
"""
预计算指标模块 - 所有计算在 SQL/Python 层完成，不经过 LLM
为 /ask 端点和 LLM 洞察提供精确的数值数据
"""
from decimal import Decimal
from collections import Counter
from app import database as db


def get_all_categories_latest(metric_name: Optional[str] = None) -> list[dict]:
    """
    查询所有品类最新一周的指标数据（用于"各品类对比"场景）。
    返回每个品类最新一周的指标列表。
    """
    conn = db.get_connection()
    latest_date = conn.execute(
        "SELECT MAX(report_date) FROM metric_facts WHERE merchant_type IS NULL"
    ).fetchone()[0]

    if metric_name:
        rows = conn.execute(
            """SELECT category, metric_name, metric_value, metric_unit, week_label
               FROM metric_facts 
               WHERE merchant_type IS NULL 
                 AND report_date = ?
                 AND category != '总体'
                 AND metric_name = ?
               ORDER BY metric_value DESC""",
            (latest_date, metric_name),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT category, metric_name, metric_value, metric_unit, week_label
               FROM metric_facts 
               WHERE merchant_type IS NULL 
                 AND report_date = ?
                 AND category != '总体'
               ORDER BY category, metric_name""",
            (latest_date,),
        ).fetchall()

    return [
        {
            "category": r["category"],
            "metric_name": r["metric_name"],
            "metric_value": r["metric_value"],
            "metric_unit": r["metric_unit"],
            "week_label": r["week_label"],
        }
        for r in rows
    ]


def get_metric_facts_summary(entity_id: str) -> list[dict]:
    """
    从 metric_facts 宽表查询实体的真实指标数据。
    返回按 report_date 分组的指标列表，每项包含 metric_name, metric_value, metric_unit。
    
    用于前端摘要卡和趋势图展示真实数据，替代时间线摘要文本解析。
    """
    entity = db.get_entity(entity_id)
    if not entity:
        return []

    entity_name = entity["entity_name"]
    category = entity["category"]

    # 根据实体类型确定过滤条件
    if category == "OBJECT":
        # 品类实体：按 category 过滤
        rows = db.get_connection().execute(
            """SELECT report_date, week_label, category, metric_name, metric_value, metric_unit
               FROM metric_facts 
               WHERE category = ? AND merchant_type IS NULL
               ORDER BY report_date DESC, metric_name""",
            (entity_name,),
        ).fetchall()
    elif category == "OWNER":
        # 商户类型实体：按 merchant_type 过滤
        rows = db.get_connection().execute(
            """SELECT report_date, week_label, category, metric_name, metric_value, metric_unit
               FROM metric_facts 
               WHERE merchant_type = ?
               ORDER BY report_date DESC, metric_name""",
            (entity_name,),
        ).fetchall()
    elif category == "METRIC":
        # 指标实体：从"总体"行按 metric_name 过滤（如 GMV、毛利率、客单价等）
        rows = db.get_connection().execute(
            """SELECT report_date, week_label, category, metric_name, metric_value, metric_unit
               FROM metric_facts 
               WHERE category = '总体' AND metric_name = ? AND merchant_type IS NULL
               ORDER BY report_date DESC""",
            (entity_name,),
        ).fetchall()
    else:
        return []

    # 转换为字典列表
    result = []
    for row in rows:
        result.append({
            "report_date": row["report_date"],
            "week_label": row["week_label"],
            "category": row["category"],
            "metric_name": row["metric_name"],
            "metric_value": row["metric_value"],
            "metric_unit": row["metric_unit"],
        })
    return result


def get_metrics(entity_id: str) -> dict:
    """
    获取实体的预计算指标。
    所有数值在 Python 层精确计算，不经过 LLM。

    返回：
    - event_count: 事件总数
    - fluctuation_count: 波动事件数
    - decision_count: 决策数
    - pending_decisions: 待落地决策数
    - first_seen: 首次出现时间
    - last_seen: 最近出现时间
    - top_attribution: 最高频归因
    - event_type_distribution: 事件类型分布
    """
    events = db.get_events_for_entity(entity_id)
    if not events:
        return {
            "event_count": 0,
            "fluctuation_count": 0,
            "decision_count": 0,
            "pending_decisions": 0,
            "first_seen": None,
            "last_seen": None,
            "top_attribution": None,
            "event_type_distribution": {},
        }

    # 统计事件类型
    event_types = [e.get("event_type", "UNKNOWN") for e in events]
    type_distribution = dict(Counter(event_types))

    # 统计波动事件
    fluctuation_count = type_distribution.get("FLUCTUATION", 0)

    # 统计归因
    attributions = [e.get("attribution", "") for e in events if e.get("attribution")]
    attribution_counter = Counter(attributions)
    top_attribution = attribution_counter.most_common(1)[0][0] if attribution_counter else None

    # 统计决策（批量查询，避免 N+1）
    event_ids = [event["event_id"] for event in events]
    decisions_map = db.get_decisions_for_events(event_ids)
    decision_count = len(decisions_map)
    pending_decisions = sum(
        1 for d in decisions_map.values() if d.get("outcome") == "PENDING"
    )

    # 时间范围
    timestamps = [e.get("occurred_at", "") for e in events if e.get("occurred_at")]
    first_seen = min(timestamps) if timestamps else None
    last_seen = max(timestamps) if timestamps else None

    return {
        "event_count": len(events),
        "fluctuation_count": fluctuation_count,
        "decision_count": decision_count,
        "pending_decisions": pending_decisions,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "top_attribution": top_attribution,
        "event_type_distribution": type_distribution,
    }


def get_rolling_stats(entity_id: str, window: int = 7) -> dict:
    """
    获取实体的滚动统计（最近 N 个事件）。
    用于趋势分析。

    Args:
        entity_id: 实体 ID
        window: 窗口大小（最近 N 个事件）
    """
    events = db.get_events_for_entity(entity_id)
    if not events:
        return {"window": window, "count": 0}

    # 按时间排序，取最近 window 个
    sorted_events = sorted(events, key=lambda e: e.get("occurred_at", ""), reverse=True)
    recent = sorted_events[:window]

    recent_types = [e.get("event_type", "UNKNOWN") for e in recent]
    recent_fluctuations = sum(1 for t in recent_types if t == "FLUCTUATION")

    # 数值统计（从 metric_value 字段）
    values = [e["metric_value"] for e in recent if e.get("metric_value") is not None]
    numeric_stats = {}
    if values:
        numeric_stats = {
            "latest_value": values[0],
            "min_value": min(values),
            "max_value": max(values),
            "avg_value": round(sum(values) / len(values), 2),
            "unit": next((e.get("metric_unit") for e in recent if e.get("metric_unit")), None),
            "trend": "up" if len(values) >= 2 and values[0] > values[1] else "down" if len(values) >= 2 and values[0] < values[1] else "flat",
        }

    return {
        "window": window,
        "count": len(recent),
        "fluctuation_count": recent_fluctuations,
        "fluctuation_rate": round(
            Decimal(str(recent_fluctuations)) / Decimal(str(len(recent))) * 100, 1
        ) if recent else 0,
        "has_recent_fluctuation": recent_fluctuations > 0,
        **numeric_stats,
    }


def get_entity_snapshot(entity_id: str) -> dict:
    """
    获取实体的完整快照（指标 + 滚动统计 + 子实体贡献度）。
    这是 /ask 端点和 LLM 洞察共享的数据源。
    """
    from app.normalizer import entity_hierarchy

    metrics = get_metrics(entity_id)
    rolling = get_rolling_stats(entity_id, window=7)

    # 子实体贡献度（如果有层级）
    children_contribution = []
    if db.has_children(entity_id):
        children_contribution = entity_hierarchy.drilldown_contribution(entity_id)

    return {
        "entity_id": entity_id,
        "metrics": metrics,
        "rolling_stats": rolling,
        "children_contribution": children_contribution,
    }
