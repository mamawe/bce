"""
规则型后处理器 - 补充 LLM 提取遗漏的实体和时间线事件

LLM 往往只提取"有趣"的事件（如 A/B Test、决策），而遗漏常规指标和品类的
时间线事件。此模块通过扫描文档文本，确保所有提到的指标/品类/商户类型都有
对应的实体和时间线事件。

工作流程：
1. 定义已知实体清单（指标、品类、商户类型）
2. 扫描文档文本，找出所有被提及的实体
3. 对于 LLM 遗漏的实体，补充 entities_mentioned 和 timeline_extraction
"""
import re

# ─── 已知实体清单 ──────────────────────────────────────────────

# 核心指标（METRIC）
KNOWN_METRICS = [
    ("GMV", ["日均 GMV", "GMV（万元）", "日均GMV"]),
    ("订单量", ["日均订单量", "日均订单", "订单量（单）"]),
    ("客单价", ["客单价（元）"]),
    ("复购率", []),
    ("品类宽度", []),
    ("SKU宽度", ["SKU 宽度", "SKU宽度"]),
    ("毛利率", []),
    ("净利率", []),
    ("转化率", ["CVR"]),
    ("损耗率", []),
]

# 品类（OBJECT）
KNOWN_CATEGORIES = [
    "蔬菜", "肉类", "蛋类", "米类", "面类",
    "调料类", "油类", "水产", "豆制品", "冻品",
]

# 商户类型（OWNER）- 标准化名称（不带"店"后缀）
KNOWN_MERCHANT_TYPES = [
    ("沙县小吃", ["沙县小吃店", "沙县小吃商户"]),
    ("酸辣粉", ["酸辣粉店", "酸辣粉商户"]),
    ("兰州拉面", ["兰州拉面店", "兰州拉面商户"]),
    ("黄焖鸡", ["黄焖鸡店", "黄焖鸡商户"]),
    ("麻辣烫", ["麻辣烫店", "麻辣烫商户"]),
]


def supplement_extraction(extraction: dict, document_text: str) -> dict:
    """
    补充 LLM 提取结果中遗漏的实体和时间线事件

    Args:
        extraction: LLM 返回的提取结果
        document_text: 原始文档文本

    Returns:
        补充后的 extraction dict
    """
    text = document_text
    text_lower = text.lower()

    # 收集 LLM 已提取的实体名（用于去重）
    existing_entity_names = set()
    for ent in extraction.get("entities_mentioned", []):
        raw = ent.get("raw_text", "") or ent.get("normalized_candidate", "")
        norm = ent.get("normalized_candidate", "") or ent.get("raw_text", "")
        if raw:
            existing_entity_names.add(raw.lower())
        if norm:
            existing_entity_names.add(norm.lower())

    # 收集 LLM 已创建的事件 primary_entity（用于去重）
    existing_event_entities = set()
    for evt in extraction.get("timeline_extraction", []):
        primary = evt.get("primary_entity", "")
        if primary:
            existing_event_entities.add(primary.lower())

    # 提取文档日期作为时间锚点
    time_anchor = _extract_document_date(text)

    new_entities = []
    new_events = []

    # ─── 补充指标实体 ──────────────────────────────────────────
    for name, aliases in KNOWN_METRICS:
        # 检查文档中是否提到了此指标
        search_terms = [name] + aliases
        found = any(term in text for term in search_terms)
        if not found:
            continue

        # 检查是否已在 entities_mentioned 中
        if name.lower() in existing_entity_names:
            # 已提取，但检查是否有事件
            if name.lower() not in existing_event_entities:
                event = _create_metric_event(name, text, time_anchor)
                if event:
                    new_events.append(event)
                    existing_event_entities.add(name.lower())
            continue

        # 补充实体
        new_entities.append({
            "raw_text": name,
            "normalized_candidate": name,
            "category": "METRIC",
        })
        existing_entity_names.add(name.lower())

        # 补充事件
        if name.lower() not in existing_event_entities:
            event = _create_metric_event(name, text, time_anchor)
            if event:
                new_events.append(event)
                existing_event_entities.add(name.lower())

    # ─── 补充品类实体 ──────────────────────────────────────────
    for name in KNOWN_CATEGORIES:
        found = name in text
        if not found:
            continue

        if name.lower() in existing_entity_names:
            if name.lower() not in existing_event_entities:
                event = _create_category_event(name, text, time_anchor)
                if event:
                    new_events.append(event)
                    existing_event_entities.add(name.lower())
            continue

        new_entities.append({
            "raw_text": name,
            "normalized_candidate": name,
            "category": "OBJECT",
        })
        existing_entity_names.add(name.lower())

        if name.lower() not in existing_event_entities:
            event = _create_category_event(name, text, time_anchor)
            if event:
                new_events.append(event)
                existing_event_entities.add(name.lower())

    # ─── 补充商户类型实体 ──────────────────────────────────────
    for name, aliases in KNOWN_MERCHANT_TYPES:
        search_terms = [name] + aliases
        found = any(term in text for term in search_terms)
        if not found:
            continue

        # 检查是否已提取（包括别名）
        already_extracted = any(
            term.lower() in existing_entity_names for term in search_terms
        )

        if already_extracted:
            # 已提取，检查事件
            if name.lower() not in existing_event_entities:
                event = _create_merchant_event(name, text, time_anchor)
                if event:
                    new_events.append(event)
                    existing_event_entities.add(name.lower())
            continue

        # 补充实体（标准化名称，不带"店"后缀）
        new_entities.append({
            "raw_text": name,
            "normalized_candidate": name,
            "category": "OWNER",
        })
        existing_entity_names.add(name.lower())

        if name.lower() not in existing_event_entities:
            event = _create_merchant_event(name, text, time_anchor)
            if event:
                new_events.append(event)
                existing_event_entities.add(name.lower())

    # 合并到 extraction
    if new_entities:
        extraction["entities_mentioned"].extend(new_entities)
    if new_events:
        extraction["timeline_extraction"].extend(new_events)

    return extraction


def _extract_document_date(text: str) -> str:
    """从文档中提取日期作为时间锚点"""
    # 尝试匹配 "2026-05-19" 格式
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)

    # 尝试匹配 "第XX周" 并估算日期
    m = re.search(r"(\d{4})年第(\d+)周", text)
    if m:
        year = int(m.group(1))
        week = int(m.group(2))
        # 简单估算：第1周 = 1月第一周
        month = max(1, (week - 1) * 7 // 30 + 1)
        day = max(1, (week - 1) * 7 % 30 + 1)
        return f"{year}-{month:02d}-{day:02d}"

    return "2026-01-01"


def parse_metric_values(summary: str) -> dict:
    """Extract numeric values from summary text.

    Handles patterns like:
        "GMV：日均 GMV（万元）1,520 / 1,474 / +3.1%"
        "毛利率 | 19.2%"

    Returns:
        {"value": float|None, "unit": str|None,
         "delta": float|None, "delta_pct": float|None}
    """
    result = {"value": None, "unit": None, "delta": None, "delta_pct": None}
    if not summary:
        return result

    # Extract unit from （万元）/（元）/（%）
    unit_match = re.search(r'（([^）]+)）', summary)
    if unit_match:
        result["unit"] = unit_match.group(1)

    # Extract "current / previous / ±change%" pattern
    nums_match = re.search(
        r'([\d,]+(?:\.\d+)?)\s*/\s*([\d,]+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)\s*(?:%|pp)',
        summary,
    )
    if nums_match:
        current = float(nums_match.group(1).replace(',', ''))
        previous = float(nums_match.group(2).replace(',', ''))
        change_pct = float(nums_match.group(3))
        result["value"] = current
        result["delta"] = round(current - previous, 2)
        result["delta_pct"] = change_pct
        return result

    # Fallback: single percentage value like "毛利率 | 19.2%"
    pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', summary)
    if pct_match:
        result["value"] = float(pct_match.group(1))
        result["unit"] = result["unit"] or "%"

    return result


def _create_metric_event(metric_name: str, text: str, time_anchor: str) -> dict | None:
    """为指标创建时间线事件，从文档中提取相关数据"""
    summary = _extract_metric_summary(metric_name, text)
    if not summary:
        summary = f"本期报告中提到了{metric_name}"

    metrics = parse_metric_values(summary)

    return {
        "time_anchor": time_anchor,
        "primary_entity": metric_name,
        "event_summary": summary,
        "event_type": "FLUCTUATION",
        "attribution": "",
        "decision": {"action": "", "owner": "", "outcome": "", "outcome_detail": ""},
        "importance_flag": "REGULAR",
        "metric_value": metrics["value"],
        "metric_unit": metrics["unit"],
        "metric_delta": metrics["delta"],
        "metric_delta_pct": metrics["delta_pct"],
    }


def _create_category_event(category_name: str, text: str, time_anchor: str) -> dict | None:
    """为品类创建时间线事件"""
    summary = _extract_category_summary(category_name, text)
    if not summary:
        summary = f"本期报告中提到了{category_name}品类"

    return {
        "time_anchor": time_anchor,
        "primary_entity": category_name,
        "event_summary": summary,
        "event_type": "FLUCTUATION",
        "attribution": "",
        "decision": {"action": "", "owner": "", "outcome": "", "outcome_detail": ""},
        "importance_flag": "REGULAR",
    }


def _create_merchant_event(merchant_name: str, text: str, time_anchor: str) -> dict | None:
    """为商户类型创建时间线事件"""
    summary = _extract_merchant_summary(merchant_name, text)
    if not summary:
        summary = f"本期报告中提到了{merchant_name}商户"

    return {
        "time_anchor": time_anchor,
        "primary_entity": merchant_name,
        "event_summary": summary,
        "event_type": "FLUCTUATION",
        "attribution": "",
        "decision": {"action": "", "owner": "", "outcome": "", "outcome_detail": ""},
        "importance_flag": "REGULAR",
    }


def _extract_metric_summary(metric_name: str, text: str) -> str | None:
    """从文档中提取指标的数值摘要"""
    # 尝试从表格行中提取
    # 匹配格式：| 指标名 | 数值 | 数值 | 环比 | ...
    lines = text.split("\n")
    for line in lines:
        if metric_name in line and "|" in line:
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            if len(cells) >= 3:
                # 尝试找到包含数值的单元格
                value_cells = [c for c in cells[1:] if re.search(r"\d", c)]
                if value_cells:
                    return f"{metric_name}：{cells[0]}{' / '.join(value_cells[:3])}"

    # 尝试从段落中提取
    for line in lines:
        if metric_name in line:
            # 找到包含数值的句子
            sentences = re.split(r"[。；\n]", line)
            for s in sentences:
                if metric_name in s and re.search(r"\d", s):
                    return s.strip()[:120]

    return None


def _extract_category_summary(category_name: str, text: str) -> str | None:
    """从文档中提取品类的数值摘要"""
    lines = text.split("\n")
    for line in lines:
        if category_name in line and "|" in line:
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            if len(cells) >= 3:
                value_cells = [c for c in cells[1:] if re.search(r"\d", c)]
                if value_cells:
                    return f"{category_name}：{' / '.join(value_cells[:4])}"

    # 从段落中提取
    for line in lines:
        if category_name in line:
            sentences = re.split(r"[。；\n]", line)
            for s in sentences:
                if category_name in s and re.search(r"\d", s):
                    return s.strip()[:120]

    return None


def _extract_merchant_summary(merchant_name: str, text: str) -> str | None:
    """从文档中提取商户类型的数值摘要"""
    # 搜索商户名称及其变体
    search_terms = [merchant_name, merchant_name + "店", merchant_name + "商户"]

    lines = text.split("\n")
    for line in lines:
        if any(term in line for term in search_terms) and "|" in line:
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            if len(cells) >= 3:
                value_cells = [c for c in cells[1:] if re.search(r"\d", c)]
                if value_cells:
                    return f"{merchant_name}：{' / '.join(value_cells[:4])}"

    # 从段落中提取
    for line in lines:
        if any(term in line for term in search_terms):
            sentences = re.split(r"[。；\n]", line)
            for s in sentences:
                if any(term in s for term in search_terms) and re.search(r"\d", s):
                    return s.strip()[:120]

    return None
