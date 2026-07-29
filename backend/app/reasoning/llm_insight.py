"""
LLM 洞察生成器 - 用 LLM 推理替换规则引擎
失败时自动降级到规则引擎（insight.py）
核心原则：LLM 不参与计算，所有数值由 precompute.py 预计算
"""
import json

from app import database as db
from app.llm_client import generate, LLMError
from app.api import precompute
from app.api.insight import generate_insight as rule_insight
from app.api.answer_validator import validate_answer
from app.timeline.timeline_builder import build_timeline_for_entity
from app.normalizer import entity_hierarchy


async def generate_llm_insight(entity_id: str) -> dict:
    """
    基于实体时间线 + 预计算指标 + 子实体贡献度，用 LLM 生成洞察。
    失败时降级到规则引擎。

    Returns:
        {
            "insight": str,          # 洞察文本
            "source": str,           # "llm" | "rules" | "llm_with_fallback"
            "confidence": str,       # "high" | "medium" | "low"
            "fallback_reason": str,  # 降级原因（如果有）
            "validation_errors": list,  # 校验错误（如果有）
        }
    """
    # 1. 获取结构化数据（全部 SQL/Python 计算，不经过 LLM）
    entity = db.get_entity(entity_id)
    if not entity:
        return _rule_fallback(entity_id, "实体不存在")

    entity_name = entity["entity_name"]
    timeline = build_timeline_for_entity(entity_id)
    metrics = precompute.get_metrics(entity_id)

    # 子实体贡献度
    children = []
    if db.has_children(entity_id):
        children = entity_hierarchy.drilldown_contribution(entity_id)

    # 如果没有数据，直接返回
    if not timeline and metrics["event_count"] == 0:
        return {
            "insight": f"暂无 {entity_name} 的历史数据。",
            "source": "rules",
            "confidence": "low",
            "fallback_reason": "无数据",
        }

    # 2. 构建 prompt
    prompt = _build_insight_prompt(entity_name, timeline, metrics, children)

    # 3. LLM 推理（5s 超时）
    try:
        response = await generate(prompt, timeout=15.0, temperature=0.3, max_tokens=1024)

        # 4. 校验
        validation = validate_answer(response, timeline, metrics, [{"entity_name": entity_name}])

        if validation["passed"]:
            return {
                "insight": response,
                "source": "llm",
                "confidence": "high",
            }
        else:
            # 校验失败：保留 LLM 结果但标记低置信度
            rule_result = rule_insight(entity_name, timeline)
            return {
                "insight": response,
                "rule_insight": rule_result,
                "source": "llm_with_fallback",
                "confidence": "low",
                "validation_errors": validation["errors"],
            }

    except (TimeoutError, LLMError) as e:
        return _rule_fallback_with_data(entity_name, entity_id, timeline, str(e))


def _rule_fallback(entity_id: str, reason: str) -> dict:
    """降级到规则引擎"""
    entity = db.get_entity(entity_id)
    entity_name = entity["entity_name"] if entity else entity_id
    timeline = build_timeline_for_entity(entity_id)
    return _rule_fallback_with_data(entity_name, entity_id, timeline, reason)


def _rule_fallback_with_data(entity_name: str, entity_id: str,
                              timeline: list[dict], reason: str) -> dict:
    """带数据的降级"""
    rule_result = rule_insight(entity_name, timeline)
    return {
        "insight": _format_rule_insight(rule_result),
        "source": "rules",
        "confidence": "medium",
        "fallback_reason": reason,
    }


def _format_rule_insight(rule_result) -> str:
    """将规则引擎结果格式化为字符串"""
    if isinstance(rule_result, str):
        return rule_result
    if isinstance(rule_result, dict):
        parts = []
        for key, label in [("pattern", "模式"), ("risk", "风险"), ("suggestion", "建议")]:
            value = rule_result.get(key)
            if value:
                parts.append(f"【{label}】{value}")
        return "\n".join(parts) if parts else "暂无可用的分析结果"
    return str(rule_result)


def _build_insight_prompt(entity_name: str, timeline: list[dict],
                           metrics: dict, children: list[dict]) -> str:
    """
    构建 LLM 洞察生成 prompt。
    注意：prompt 中不包含任何需要 LLM 计算的数字，所有数值都已预计算好。
    """
    # 精简 timeline，只保留关键字段
    timeline_brief = [
        {
            "time": e.get("occurred_at"),
            "summary": e.get("summary"),
            "type": e.get("event_type"),
            "attribution": e.get("attribution"),
            "decision_action": e.get("decision", {}).get("action") if e.get("decision") else None,
            "decision_outcome": e.get("decision", {}).get("outcome") if e.get("decision") else None,
        }
        for e in timeline[-10:]  # 最近 10 条
    ]

    return f"""你是一个资深商业分析师。基于以下数据生成业务洞察。

## 实体
{entity_name}

## 时间线事件（最近 {len(timeline_brief)} 条）
{json.dumps(timeline_brief, ensure_ascii=False, indent=2)}

## 预计算指标
{json.dumps(metrics, ensure_ascii=False, indent=2)}

## 子实体贡献度
{json.dumps(children, ensure_ascii=False, indent=2) if children else '无子实体'}

## 请生成洞察，包含以下维度（如果数据支持）：

1. **模式识别**：这个实体最近出现了什么模式？（重复波动？趋势变化？季节性？）
2. **根因分析**：如果出现了异常，根因是什么？从子实体贡献度中找线索。
3. **风险提示**：当前状态是否值得关注？风险等级（高/中/低）？
4. **建议行动**：基于历史经验，建议采取什么具体行动？

## 要求：
- 只使用提供的数据，不要编造任何数字或事实。
- 所有数字引用预计算指标中的精确值。
- 如果数据不足以支持某个维度，说"数据不足"并说明缺少什么。
- 引用具体日期和事件。
- 输出格式：用 Markdown 分段，每个维度一个小标题。
"""
