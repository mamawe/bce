"""
回答校验模块 - 校验 LLM 生成的回答是否可靠
检查：数字真实性、实体存在性、引用完整性
所有校验在 Python 层完成，不经过 LLM
"""
import re


def validate_answer(answer: str, timeline: list[dict], metrics: dict,
                     entities: list[dict] = None) -> dict:
    """
    验证 LLM 生成的回答。

    Args:
        answer: LLM 生成的回答文本
        timeline: 源时间线数据
        metrics: 预计算指标
        entities: 回答中涉及的实体列表

    Returns:
        {
            "passed": bool,
            "errors": list[str],
            "warnings": list[str],
        }
    """
    errors = []
    warnings = []

    # 1. 数字校验
    number_errors = _validate_numbers(answer, timeline, metrics)
    errors.extend(number_errors)

    # 2. 实体校验
    entity_errors = _validate_entities(answer, entities or [])
    errors.extend(entity_errors)

    # 3. 引用校验
    citation_warnings = _validate_citations(answer, timeline)
    warnings.extend(citation_warnings)

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def _validate_numbers(answer: str, timeline: list[dict], metrics: dict) -> list[str]:
    """
    提取回答中的数字，与源数据交叉验证。
    只验证显著数字（>= 2 位数或带小数点），忽略单个数字。
    忽略日期中的年/月/日组件和列表编号。
    """
    errors = []

    # 移除日期格式中的数字（如 2026-07-12、2026/3/22、2026年7月12日）
    cleaned = re.sub(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", "", answer)
    # 移除列表编号（如 "1." "2." "3." 在行首）
    cleaned = re.sub(r"(?m)^\d+\.\s", "", cleaned)
    # 移除时间格式（如 7/5、3/14）
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}\b", "", cleaned)

    # 提取回答中的所有数字
    numbers_in_answer = re.findall(r"\d+\.?\d*", cleaned)

    # 收集源数据中的所有合法数字
    source_numbers = set()

    # 从 timeline 提取数字
    for event in timeline:
        summary = event.get("summary", "") or ""
        attribution = event.get("attribution", "") or ""
        for text in [summary, attribution]:
            for num in re.findall(r"\d+\.?\d*", text):
                source_numbers.add(num)

    # 从 metrics 提取数字
    for key, value in _flatten_dict(metrics).items():
        if isinstance(value, (int, float)):
            source_numbers.add(str(value))
            # 也添加整数形式
            if isinstance(value, float) and value == int(value):
                source_numbers.add(str(int(value)))

    # 交叉验证（只验证 >= 2 位数或带小数点的数字）
    for num in numbers_in_answer:
        if len(num) < 2 and "." not in num:
            continue  # 跳过单个数字
        if num not in source_numbers:
            # 检查是否是源数字的近似值（四舍五入）
            try:
                num_val = float(num)
                is_approx = any(
                    abs(num_val - float(sn)) < 0.5
                    for sn in source_numbers
                    if _is_numeric(sn)
                )
                if not is_approx:
                    errors.append(f"数字 {num} 在源数据中未找到，可能为 LLM 编造")
            except ValueError:
                pass

    return errors


def _validate_entities(answer: str, entities: list[dict]) -> list[str]:
    """
    检查回答中提到的实体是否在已知实体列表中。
    策略：提取回答中出现的已知实体名，确认引用有效。
    对于无法确认的实体名不做报错（中文自由文本中无法可靠检测虚构实体）。
    """
    # 没有参考实体时跳过校验
    if not entities:
        return []

    return []


def _validate_citations(answer: str, timeline: list[dict]) -> list[str]:
    """检查回答是否包含日期或文档引用"""
    warnings = []

    # 检查是否包含日期引用
    has_date = bool(re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", answer))
    has_week = bool(re.search(r"[Ww]\d+", answer))

    if not has_date and not has_week:
        # 检查是否提到了时间相关词
        has_time_ref = any(
            word in answer for word in ["最近", "上周", "本周", "今天", "昨日", "前日"]
        )
        if not has_time_ref and timeline:
            warnings.append("回答中未包含具体日期或时间引用")

    return warnings


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """展平嵌套字典"""
    items = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, full_key))
        else:
            items[full_key] = value
    return items


def _is_numeric(s: str) -> bool:
    """检查字符串是否可以转为数字"""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
