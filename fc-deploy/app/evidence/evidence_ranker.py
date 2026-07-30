from __future__ import annotations
"""
证据排序器 - 按重要性对实体关联的文档进行排序
权重: FIRST_MENTION=5.0, FINAL_RESOLUTION=5.0, FAILED_CASE=4.0, HIGH_SIMILARITY=3.0, REGULAR=2.0
"""
from app import database as db

# 重要性权重映射
WEIGHT_MAP = {
    "FIRST_MENTION": 5.0,
    "FINAL_RESOLUTION": 5.0,
    "FAILED_CASE": 4.0,
    "HIGH_SIMILARITY": 3.0,
    "REGULAR": 2.0,
}


def store_evidence(entity_id: str, doc_id: str, doc_title: str, doc_url: str,
                   importance_flag: str):
    """存储一条证据链接"""
    score = WEIGHT_MAP.get(importance_flag, 2.0)
    reason_code = importance_flag if importance_flag in WEIGHT_MAP else "REGULAR"
    db.insert_evidence(
        entity_id=entity_id,
        document_id=doc_id,
        doc_title=doc_title,
        doc_url=doc_url,
        importance_score=score,
        reason_code=reason_code,
    )


def get_ranked_evidence(entity_id: str, top_n: int = 3) -> list[dict]:
    """
    获取实体的 top-N 证据文档
    按 importance_score 降序排列
    v2: 查不到直接证据时，搜索同前缀实体的证据
    """
    all_evidence = db.get_evidence_for_entity(entity_id)

    # v2: 无直接证据时，搜索同前缀实体的证据
    if not all_evidence:
        conn = db.get_connection()
        try:
            # 转义 entity_id 中的 LIKE 通配符（_ 和 %），避免误匹配
            escaped_id = entity_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            related = conn.execute(
                "SELECT * FROM evidence_links WHERE entity_id LIKE ? ESCAPE '\\' ORDER BY importance_score DESC",
                (f"{escaped_id}_%",),
            ).fetchall()
            all_evidence = [dict(r) for r in related]
        finally:
            conn.close()

    # 去重：同一文档只保留最高分
    doc_best: dict[str, dict] = {}
    for ev in all_evidence:
        key = ev["document_id"] or ev["doc_title"]
        if key not in doc_best or ev["importance_score"] > doc_best[key]["importance_score"]:
            doc_best[key] = ev

    ranked = sorted(doc_best.values(), key=lambda x: x["importance_score"], reverse=True)
    return ranked[:top_n]
