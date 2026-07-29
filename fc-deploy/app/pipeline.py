"""
BCE 导入管道编排器 - 完整的文档摄取流程
Step 1: 解析文档
Step 2: 规则型提取（确定性数字）
Step 3: 分节 LLM 提取（归因/决策/因果）
Step 4: 合并 + 交叉验证
Step 5: 实体标准化
Step 6: 时间一致性检查
Step 7: 证据调和
Step 8: 跨实体关系
Step 9: 存储到 DB
"""
import re
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.parser.document_parser import parse_markdown, build_extraction_context
from app.extractor.llm_extractor import extract_from_document, extract_section
from app.extractor.rule_based_supplementer import supplement_extraction, parse_metric_values
from app.normalizer.entity_normalizer import normalize_entity
from app.timeline.timeline_builder import store_extracted_events
from app.evidence.evidence_ranker import store_evidence
from app.evidence.reconciliation import reconcile_evidence
from app.normalizer.entity_relationships import extract_and_store_relationships
from app import database as db

logger = logging.getLogger(__name__)


def _has_structured_data(content: str) -> bool:
    """判断文档是否包含表格/结构化数据"""
    lines = content.split("\n")
    table_lines = [l for l in lines if "|" in l and l.strip().startswith("|")]
    return len(table_lines) >= 3


def _split_sections(content: str) -> list[dict[str, str]]:
    """按 ## 标题拆分文档为 sections"""
    lines = content.split("\n")
    sections = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        heading_match = re.match(r"^(#{2,3})\s+(.+)", line)
        if heading_match:
            if current_heading or current_lines:
                sections.append({
                    "heading": current_heading or "intro",
                    "content": "\n".join(current_lines).strip(),
                })
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading or current_lines:
        sections.append({
            "heading": current_heading or "intro",
            "content": "\n".join(current_lines).strip(),
        })

    return [s for s in sections if s["content"].strip()]


async def _extract_sections_parallel(
    sections: list[dict[str, str]], rule_facts: list[dict]
) -> list[dict]:
    """并行提取各章节的因果关系，最多 3 个并发 LLM 调用。"""
    sem = asyncio.Semaphore(3)

    async def extract_one(section: dict[str, str]) -> dict | None:
        if len(section["content"]) < 50:
            return None
        async with sem:
            try:
                return await extract_section(
                    section_text=section["content"],
                    section_heading=section["heading"],
                    rule_facts=rule_facts,
                )
            except Exception as e:
                logger.warning(f"Section extraction failed for '{section['heading']}' (non-fatal): {e}")
                return None

    tasks = [extract_one(s) for s in sections]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def _extract_rule_facts(content: str) -> list[dict]:
    """从规则型提取中获取确定性数字事实"""
    facts = []
    lines = content.split("\n")
    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2 and re.search(r"\d", cells[-1]):
                facts.append({
                    "entity": cells[0],
                    "value": cells[1] if len(cells) > 1 else "",
                    "raw_line": line.strip(),
                    "confidence": 0.9,
                })
    return facts


def _cross_validate(llm_extraction: dict, rule_facts: list[dict]) -> list[dict]:
    """
    交叉验证: LLM 数字 vs 规则数字
    如果 LLM 数字与规则数字冲突且规则置信度 > 0.7，标记为 CONFLICT
    """
    conflicts = []
    for event in llm_extraction.get("timeline_extraction", []):
        summary = event.get("event_summary", "")
        primary = event.get("primary_entity", "")

        for fact in rule_facts:
            if fact["entity"] in primary or primary in fact["entity"]:
                # 检查 LLM 提取的数字是否与规则数字冲突
                llm_numbers = re.findall(r"[\d,]+\.?\d*", summary)
                rule_numbers = re.findall(r"[\d,]+\.?\d*", fact["value"])
                if llm_numbers and rule_numbers:
                    # 简单比较：如果主要数字不一致
                    llm_main = llm_numbers[0].replace(",", "")
                    rule_main = rule_numbers[0].replace(",", "")
                    if llm_main != rule_main and fact["confidence"] > 0.7:
                        conflicts.append({
                            "entity": primary,
                            "llm_value": llm_main,
                            "rule_value": rule_main,
                            "type": "NUMBER_CONFLICT",
                        })
    return conflicts


def _temporal_consistency_check(extraction: dict) -> list[dict]:
    """时间一致性检查：确保事件时间不早于文档日期"""
    issues = []
    doc_date = extraction.get("document_metadata", {}).get("date", "")
    if not doc_date:
        return issues

    for event in extraction.get("timeline_extraction", []):
        anchor = event.get("time_anchor", "")
        if anchor and doc_date and len(anchor) == 10 and len(doc_date) == 10:
            if anchor > doc_date:
                issues.append({
                    "entity": event.get("primary_entity", ""),
                    "time_anchor": anchor,
                    "doc_date": doc_date,
                    "issue": "event_after_doc_date",
                })
    return issues


def _build_push_summary(entities_found: list, events_extracted: int, decisions_extracted: int) -> list[str]:
    """Build summary lines for Feishu push notification."""
    lines = []
    if entities_found:
        names = [e if isinstance(e, str) else e.get("entity_name", str(e)) for e in entities_found[:5]]
        lines.append(f"识别实体：{'、'.join(names)}")
    if events_extracted:
        lines.append(f"提取时间线事件 {events_extracted} 条")
    if decisions_extracted:
        lines.append(f"提取决策记录 {decisions_extracted} 条")
    if not lines:
        lines.append("文档已完成结构化处理")
    return lines


async def run_ingest_pipeline(title: str, content: str, source_url: str = None, push_to: str = None) -> dict[str, Any]:
    """
    完整的文档摄取管道。

    Returns:
        ingestion result dict with doc_id, entities_found, events_extracted, etc.
    """
    # Step 1: 解析文档
    parsed = parse_markdown(content)
    doc_title = title or parsed.metadata.title or "Untitled"

    # 生成 doc_id
    year_match = re.search(r"(\d{4})\s*年", doc_title)
    week_match = re.search(r"第\s*(\d+)\s*周", doc_title)
    if year_match and week_match:
        doc_id = f"doc_{year_match.group(1)}_w{int(week_match.group(1)):02d}"
    else:
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"

    # ── 文档版本化：检测重复文档（按 source_url 或标题）──
    existing = None
    if source_url:
        existing = db.get_document_by_source(source_url)
    if not existing:
        existing = db.get_document_by_title(doc_title)

    version_update = False
    new_version = 1
    if existing:
        old_doc_id = existing["doc_id"]
        # 废弃旧版本事件，并递增版本号
        db.deprecate_events_for_doc(old_doc_id, version=(existing.get("doc_version") or 1) + 1)
        new_version = db.increment_document_version(old_doc_id)
        # 复用已有 doc_id，保证多次摄取归并到同一文档
        doc_id = old_doc_id
        version_update = True
    else:
        new_version = 1

    # 存储原始文档
    db.insert_document(
        doc_id=doc_id,
        title=doc_title,
        content=content,
        source_url=source_url or "",
        ingested_at=datetime.now(timezone.utc).isoformat(),
        doc_version=new_version,
    )

    # Step 2: 规则型提取 - 提取确定性数字
    has_tables = _has_structured_data(content)
    rule_facts = _extract_rule_facts(content) if has_tables else []

    # Step 3: LLM 提取
    if has_tables:
        # 结构化文档: 规则优先路径
        # 规则提取数字，LLM 提取归因/决策/因果
        extraction_context = build_extraction_context(parsed)
        extraction = await extract_from_document(extraction_context)

        # 分节 LLM 提取（补充因果关系）- 并行
        sections = _split_sections(content)
        section_results = await _extract_sections_parallel(sections, rule_facts)
        all_causal_entities = []
        for section_result in section_results:
            causal = section_result.get("causally_related_entities", [])
            all_causal_entities.extend(causal)

        if all_causal_entities:
            extraction["causally_related_entities"] = all_causal_entities

    else:
        # 纯叙述文档: LLM 做完整提取
        extraction_context = build_extraction_context(parsed)
        extraction = await extract_from_document(extraction_context)

        # 分节提取因果关系 - 并行
        sections = _split_sections(content)
        section_results = await _extract_sections_parallel(sections, [])
        all_causal_entities = []
        for section_result in section_results:
            causal = section_result.get("causally_related_entities", [])
            all_causal_entities.extend(causal)

        if all_causal_entities:
            extraction["causally_related_entities"] = all_causal_entities

    # 规则型后处理：补充 LLM 遗漏的实体和时间线事件
    extraction = supplement_extraction(extraction, content)

    # 指标数值回填：确保所有事件（规则路径 + LLM 路径）都带有结构化指标值
    for event in extraction.get("timeline_extraction", []):
        if event.get("metric_value") is not None:
            continue
        summary = event.get("event_summary", "")
        if not summary:
            continue
        parsed = parse_metric_values(summary)
        event["metric_value"] = parsed["value"]
        event["metric_unit"] = parsed["unit"]
        event["metric_delta"] = parsed["delta"]
        event["metric_delta_pct"] = parsed["delta_pct"]

    # Step 4: 合并 + 交叉验证
    conflicts = _cross_validate(extraction, rule_facts) if rule_facts else []

    # 将冲突写入 review_queue
    for conflict in conflicts:
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        db.insert_review_queue(
            review_id=review_id,
            entity_id=conflict.get("entity", ""),
            conflict_type="NUMBER_CONFLICT",
            description=f"LLM值({conflict['llm_value']}) vs 规则值({conflict['rule_value']})",
            old_value=conflict["rule_value"],
            new_value=conflict["llm_value"],
        )

    # Step 5: 实体标准化
    entity_mapping: dict[str, str] = {}
    entities_found = set()

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
        entities_found.add(eid)

    # Step 6: 时间一致性检查
    temporal_issues = _temporal_consistency_check(extraction)
    for issue in temporal_issues:
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        db.insert_review_queue(
            review_id=review_id,
            entity_id=issue.get("entity", ""),
            conflict_type="NUMBER_CONFLICT",
            description=f"事件时间({issue['time_anchor']})晚于文档日期({issue['doc_date']})",
            old_value=issue["doc_date"],
            new_value=issue["time_anchor"],
        )

    # Step 9 (partial): 存储事件和证据
    store_extracted_events(extraction, doc_id, entity_mapping, doc_version=new_version)

    events_extracted = len(extraction.get("timeline_extraction", []))
    decisions_extracted = 0

    for event in extraction.get("timeline_extraction", []):
        primary = event.get("primary_entity", "")
        eid = entity_mapping.get(primary)
        if not eid:
            continue
        importance_flag = event.get("importance_flag", "REGULAR")
        store_evidence(
            entity_id=eid,
            doc_id=doc_id,
            doc_title=doc_title,
            doc_url=source_url or f"/documents/{doc_id}",
            importance_flag=importance_flag,
        )
        decision = event.get("decision", {})
        if decision and decision.get("action"):
            decisions_extracted += 1

    # Step 7: 证据调和
    for eid in entities_found:
        try:
            await reconcile_evidence(
                entity_id=eid,
                new_doc_id=doc_id,
                new_doc_summary=doc_title,
            )
        except Exception as e:
            logger.warning(f"Evidence reconciliation failed for {eid} (non-fatal): {e}")

    # Step 8: 跨实体关系
    try:
        await extract_and_store_relationships(extraction, doc_id)
    except Exception as e:
        logger.warning(f"Relationship extraction failed (non-fatal): {e}")

    # Step 9: 飞书推送（可选）
    if push_to:
        try:
            from app.lark.im_push import send_push_notification
            summary_lines = _build_push_summary(entities_found, events_extracted, decisions_extracted)
            bce_link = f"http://localhost:5173/?doc={doc_id}"
            await send_push_notification(
                receive_id=push_to,
                doc_title=doc_title,
                summary_lines=summary_lines,
                bce_link=bce_link,
            )
        except Exception as e:
            logger.warning(f"Feishu push failed (non-fatal): {e}")

    return {
        "doc_id": doc_id,
        "title": doc_title,
        "entities_found": len(entities_found),
        "events_extracted": events_extracted,
        "decisions_extracted": decisions_extracted,
        "conflicts": len(conflicts),
        "temporal_issues": len(temporal_issues),
        "has_structured_data": has_tables,
        "version_update": version_update,
        "new_version": new_version,
    }
