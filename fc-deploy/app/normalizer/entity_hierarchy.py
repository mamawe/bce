from __future__ import annotations
"""
实体层级管理 - 递归查询、roll-up、drill-down
基于 SQLite WITH RECURSIVE 实现多级实体分类
"""
from decimal import Decimal
from app import database as db


def get_descendant_ids(entity_id: str) -> list[str]:
    """递归获取所有子孙实体 ID（含自身）"""
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            WITH RECURSIVE descendants AS (
                SELECT entity_id FROM entities WHERE entity_id = ?
                UNION ALL
                SELECT e.entity_id FROM entities e
                JOIN descendants d ON e.parent_entity_id = d.entity_id
            )
            SELECT entity_id FROM descendants
        """, (entity_id,)).fetchall()
        return [row["entity_id"] for row in rows]
    finally:
        conn.close()


def get_ancestor_ids(entity_id: str) -> list[str]:
    """递归获取所有祖先实体 ID（从根到自身）"""
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            WITH RECURSIVE ancestors AS (
                SELECT entity_id, parent_entity_id, level FROM entities WHERE entity_id = ?
                UNION ALL
                SELECT e.entity_id, e.parent_entity_id, e.level
                FROM entities e
                JOIN ancestors a ON e.entity_id = a.parent_entity_id
            )
            SELECT entity_id FROM ancestors ORDER BY level
        """, (entity_id,)).fetchall()
        return [row["entity_id"] for row in rows]
    finally:
        conn.close()


def rollup_timeline(entity_id: str) -> list[dict]:
    """聚合实体及其所有子孙的时间线事件"""
    from app.timeline.timeline_builder import build_timeline_for_entity

    all_ids = get_descendant_ids(entity_id)
    events = []
    for eid in all_ids:
        events.extend(build_timeline_for_entity(eid))
    return sorted(events, key=lambda e: e.get("occurred_at", ""), reverse=True)


def drilldown_contribution(entity_id: str) -> list[dict]:
    """
    分析直接子实体对父实体的贡献度。
    返回每个子实体的权重百分比和事件数。
    注意：所有数值计算在 Python 层完成，不经过 LLM。
    """
    children = db.get_children(entity_id)
    if not children:
        return []

    # 统计每个子实体的事件数
    child_data = []
    total_events = 0
    for child in children:
        events = db.get_events_for_entity(child["entity_id"])
        event_count = len(events)
        total_events += event_count
        child_data.append({
            "entity_id": child["entity_id"],
            "entity_name": child["entity_name"],
            "category": child["category"],
            "level": child.get("level", 0),
            "event_count": event_count,
            "has_children": db.has_children(child["entity_id"]),
        })

    # 计算贡献度（按事件数加权）
    if total_events > 0:
        for cd in child_data:
            cd["contribution_pct"] = round(
                Decimal(str(cd["event_count"])) / Decimal(str(total_events)) * 100, 1
            )
    else:
        for cd in child_data:
            cd["contribution_pct"] = 0.0

    return sorted(child_data, key=lambda c: c["contribution_pct"], reverse=True)


def get_hierarchy_tree(entity_id: str = None, max_depth: int = 5) -> dict:
    """
    获取实体层级树（用于前端展示）。
    如果指定 entity_id，则返回该实体为根的子树；否则返回完整树。
    """
    conn = db.get_connection()
    try:
        if entity_id:
            root = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if not root:
                return {}
            root_dict = dict(root)
        else:
            # 获取所有 level=0 的根节点
            roots = conn.execute(
                "SELECT * FROM entities WHERE parent_entity_id IS NULL ORDER BY sort_order"
            ).fetchall()
            if not roots:
                return {}
            if len(roots) == 1:
                root_dict = dict(roots[0])
            else:
                # 多根节点，构建虚拟根
                root_dict = {
                    "entity_id": "ROOT",
                    "entity_name": "全部",
                    "category": "ROOT",
                    "level": -1,
                    "children": [dict(r) for r in roots]
                }

        # 递归构建子树
        _build_tree_recursive(conn, root_dict, max_depth, 0)
        return root_dict
    finally:
        conn.close()


def _build_tree_recursive(conn, node: dict, max_depth: int, current_depth: int):
    """递归构建子树"""
    if current_depth >= max_depth:
        return
    children = conn.execute(
        "SELECT * FROM entities WHERE parent_entity_id = ? ORDER BY sort_order",
        (node["entity_id"],),
    ).fetchall()
    if children:
        node["children"] = []
        for child in children:
            child_dict = dict(child)
            _build_tree_recursive(conn, child_dict, max_depth, current_depth + 1)
            node["children"].append(child_dict)


def build_hierarchy_prompt() -> str:
    """
    从数据库读取实体层级树，构建 prompt 注入文本。
    用于 LLM 抽取时引导关联到正确层级的实体。
    """
    tree = get_hierarchy_tree(max_depth=5)
    if not tree:
        return ""

    lines = ["已知实体层级（请将抽取的事件关联到最精确的层级实体）："]
    _append_tree_lines(tree, lines, 0)
    return "\n".join(lines)


def _append_tree_lines(node: dict, lines: list, depth: int):
    """递归构建缩进树文本"""
    indent = "  " * depth
    name = node.get("entity_name", node.get("entity_id", ""))
    lines.append(f"{indent}- {name}")
    for child in node.get("children", []):
        _append_tree_lines(child, lines, depth + 1)
