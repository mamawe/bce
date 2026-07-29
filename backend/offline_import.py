"""
离线导入脚本 - 不依赖 LLM API，纯规则提取

用途：快速重建数据库，用于验证实体关联修复
运行：cd backend && python -m offline_import
"""
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

# 确保能 import app 包
sys.path.insert(0, str(Path(__file__).parent))

from app import database as db
from app.normalizer.entity_normalizer import seed_aliases, normalize_entity
from app.extractor.rule_based_supplementer import supplement_extraction
from app.timeline.timeline_builder import store_extracted_events
from app.evidence.evidence_ranker import store_evidence
from app.parser.document_parser import parse_markdown, build_extraction_context

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def build_minimal_extraction(parsed, content: str) -> dict:
    """
    构建最小化的提取结果（空 entities + 空 timeline），
    然后交给 rule_based_supplementer 填充。
    这样完全绕过 LLM，纯规则提取。
    """
    extraction = {
        "document_metadata": {
            "doc_id": "",
            "title": parsed.metadata.title if parsed.metadata else "",
            "date": "",
        },
        "entities_mentioned": [],
        "timeline_extraction": [],
    }
    # rule_based_supplementer 会扫描文档文本，补充所有已知指标/品类/商户类型
    return supplement_extraction(extraction, content)


def main():
    # 1. 建表 + 种子
    db.create_tables()
    db.migrate_hierarchy_fields()
    seed_aliases()
    print(f"[离线导入] 数据库已初始化: {db.DB_PATH}")

    if not SAMPLES_DIR.exists():
        print(f"[离线导入] 样本目录不存在: {SAMPLES_DIR}")
        return

    sample_files = sorted(SAMPLES_DIR.glob("*.md"))
    print(f"[离线导入] 发现 {len(sample_files)} 个样本文件")

    total_entities = 0
    total_events = 0

    for filepath in sample_files:
        content = filepath.read_text(encoding="utf-8")
        parsed = parse_markdown(content)
        title = parsed.metadata.title if parsed.metadata else filepath.stem

        # 生成 doc_id
        year_match = re.search(r"(\d{4})\s*年", title)
        week_match = re.search(r"第\s*(\d+)\s*周", title)
        if year_match and week_match:
            doc_id = f"doc_{year_match.group(1)}_w{int(week_match.group(1)):02d}"
        else:
            doc_id = f"doc_{filepath.stem}"

        # 存储文档
        db.insert_document(
            doc_id=doc_id,
            title=title,
            content=content,
            source_url=f"/samples/{filepath.name}",
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )

        # 纯规则提取（绕过 LLM）
        extraction = build_minimal_extraction(parsed, content)
        print(f"[离线导入] {title}: {len(extraction.get('entities_mentioned', []))} 实体, "
              f"{len(extraction.get('timeline_extraction', []))} 事件")

        # 实体标准化
        entity_mapping: dict[str, str] = {}
        for ent in extraction.get("entities_mentioned", []):
            raw = ent.get("raw_text", "") or ent.get("normalized_candidate", "")
            category = ent.get("category", "OBJECT")
            if not raw:
                continue
            eid = normalize_entity(raw, category)
            entity_mapping[raw] = eid
            norm = ent.get("normalized_candidate", "")
            if norm:
                entity_mapping[norm] = eid

        # 存储事件
        store_extracted_events(extraction, doc_id, entity_mapping)
        total_events += len(extraction.get("timeline_extraction", []))

        # 存储证据
        for event in extraction.get("timeline_extraction", []):
            primary = event.get("primary_entity", "")
            eid = entity_mapping.get(primary)
            if eid:
                store_evidence(
                    entity_id=eid,
                    doc_id=doc_id,
                    doc_title=title,
                    doc_url=f"/samples/{filepath.name}",
                    importance_flag=event.get("importance_flag", "REGULAR"),
                )

        total_entities += len(entity_mapping)
        print(f"[离线导入] 已导入: {title} ({doc_id})")

    print(f"[离线导入] 全部完成: {len(sample_files)} 文件, "
          f"{total_entities} 实体映射, {total_events} 事件")


if __name__ == "__main__":
    main()