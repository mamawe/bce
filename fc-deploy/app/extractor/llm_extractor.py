from __future__ import annotations
"""
LLM 提取器 - 调用智谱 GLM-4.7-Flash 从文档中提取结构化信息
使用共享 llm_client，支持模型降级链
v2: 支持分节提取和因果关系抽取
v3: 使用共享 llm_client（含限速、退避、连接复用），移除直接 httpx 调用
"""
import json
import logging
from typing import Any

from app.llm_client import generate_json, LLMError

logger = logging.getLogger(__name__)

# 提取 prompt：必须显式列出所有 JSON 字段名（json_object 模式要求）
EXTRACTION_SYSTEM_PROMPT = """你是一个商业文档分析引擎。你的任务是从周报文档中提取结构化的商业上下文信息。

请严格按照以下 JSON 格式返回结果，所有字段必须存在：

{
  "document_metadata": {
    "doc_id": "文档ID，从标题推断，格式如 doc_2026_w12",
    "title": "文档标题",
    "date": "文档日期，格式 YYYY-MM-DD"
  },
  "entities_mentioned": [
    {
      "raw_text": "文档中出现的原始文本",
      "normalized_candidate": "标准化名称",
      "category": "类别，必须是以下之一: METRIC, OBJECT, EVENT, DECISION, EXPERIMENT, OWNER"
    }
  ],
  "timeline_extraction": [
    {
      "time_anchor": "时间锚点，格式 YYYY-MM-DD",
      "primary_entity": "主要关联实体的标准化名称",
      "event_summary": "事件摘要，一句话描述",
      "event_type": "事件类型，必须是以下之一: FLUCTUATION, DECISION, EXPERIMENT, LAUNCH",
      "attribution": "归因分析，描述因果关系",
      "decision": {
        "action": "采取的决策动作",
        "owner": "责任人或团队",
        "outcome": "结果状态: SUCCESS, FAILED, INCONCLUSIVE, PENDING",
        "outcome_detail": "结果描述"
      },
      "importance_flag": "重要性标记: FIRST_MENTION, FINAL_RESOLUTION, FAILED_CASE, HIGH_SIMILARITY, REGULAR"
    }
  ],
  "causally_related_entities": [
    {
      "source_entity": "因果关系中的原因实体",
      "target_entity": "因果关系中的结果实体",
      "relation_type": "关系类型: CAUSED_BY, LEADS_TO, CORRELATED, RESPONDS_TO",
      "explicit": true
    }
  ]
}

提取规则：
1. entities_mentioned: 提取所有关键业务实体，包括指标(METRIC)、业务对象(OBJECT)、事件(EVENT)、决策(DECISION)、实验(EXPERIMENT)、负责人(OWNER)
2. timeline_extraction: 为文档中提到的每个指标和品类都创建时间线事件，不要遗漏：
   - 所有 METRIC（GMV、毛利率、净利率、客单价、转化率、复购率、CAC、DAU、CTR、SKU宽度、品类宽度等）只要有数据就创建事件
   - 所有 OBJECT（冻品、肉类、蔬菜、水产、豆制品、调料品类、米类、面类、油类、蛋类等）只要在文档中被提到就创建事件
   - 所有 OWNER（商户类型如沙县小吃、麻辣烫店、兰州拉面店、黄焖鸡店、酸辣粉店等）只要在文档中被提到就创建事件
   - 每个事件用一句话总结该实体在本期报告中的表现（数值+变化趋势）
3. 如果事件关联了决策，decision 字段填写完整；否则 decision 各字段填空字符串
4. importance_flag 判断标准：首次提及某问题=FIRST_MENTION，问题最终解决=FINAL_RESOLUTION，失败案例=FAILED_CASE，与历史事件高度相似=HIGH_SIMILARITY，其他=REGULAR
5. event_type 判断标准：数据波动/变化=FLUCTUATION，决策行动=DECISION，实验测试=EXPERIMENT，新功能/活动上线=LAUNCH
6. 实体标准化名称要统一：不要在名称后面加数值（如"GMV 1,847 万元"应标准化为"GMV"），商户类型不要加"店"后缀（如"沙县小吃店"应标准化为"沙县小吃"）
7. causally_related_entities: 提取文档中明确表述的因果关系（如"A导致B"、"因为X所以Y"），explicit=true 表示文档明确陈述，false 表示你推断的
8. 只返回 JSON，不要添加任何额外文字"""


# 分节提取 prompt：专注于归因/决策/因果，不重复提取数字
SECTION_EXTRACTION_SYSTEM_PROMPT = """你是一个商业文档分析引擎。你的任务是从文档的单个章节中提取因果关系和归因分析。

请严格按照以下 JSON 格式返回结果：

{
  "causally_related_entities": [
    {
      "source_entity": "因果关系中的原因实体（标准化名称）",
      "target_entity": "因果关系中的结果实体（标准化名称）",
      "relation_type": "关系类型: CAUSED_BY, LEADS_TO, CORRELATED, RESPONDS_TO",
      "explicit": true
    }
  ],
  "attributions": [
    {
      "entity": "相关实体",
      "attribution": "归因描述",
      "decision_context": "相关决策背景（如有）"
    }
  ]
}

提取规则：
1. 专注于提取归因分析、决策记录和因果关系
2. 不要单独列出数字值，但可以在归因描述中引用
3. explicit=true 表示文档明确陈述的因果关系，false 表示你从上下文推断的
4. 实体名称要标准化（不带数值后缀）
5. 只返回 JSON，不要添加任何额外文字"""


async def extract_from_document(document_text: str) -> dict[str, Any]:
    """
    调用 GLM 提取文档中的实体和时间线事件
    使用共享 llm_client（含模型降级链、限速、退避）
    v2: 注入已知实体层级树，引导 LLM 关联到正确层级的实体
    v3: 使用共享 llm_client，移除直接 httpx 调用
    """
    # v2: 注入实体层级提示（如果数据库中已有层级数据）
    hierarchy_hint = ""
    try:
        from app.normalizer.entity_hierarchy import build_hierarchy_prompt
        hierarchy_hint = build_hierarchy_prompt()
        if hierarchy_hint:
            hierarchy_hint = f"\n\n{hierarchy_hint}"
    except Exception:
        pass  # 层级提示不可用时不影响主流程

    user_message = f"请分析以下商业周报文档，提取结构化信息：\n\n{document_text}{hierarchy_hint}"

    try:
        result = await generate_json(
            prompt=user_message,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            temperature=0.1,
            timeout=60.0,
        )
        return _validate_extraction(result)
    except (LLMError, TimeoutError) as e:
        logger.error(f"提取失败，返回空结构: {e}")
        return _empty_extraction()


def _validate_extraction(data: dict) -> dict:
    """确保返回结构完整，缺失字段补默认值"""
    if "document_metadata" not in data:
        data["document_metadata"] = {"doc_id": "", "title": "", "date": ""}
    if "entities_mentioned" not in data:
        data["entities_mentioned"] = []
    if "timeline_extraction" not in data:
        data["timeline_extraction"] = []
    if "causally_related_entities" not in data:
        data["causally_related_entities"] = []

    # 确保每个 timeline event 有 decision 字段
    for event in data["timeline_extraction"]:
        if "decision" not in event:
            event["decision"] = {"action": "", "owner": "", "outcome": "", "outcome_detail": ""}
        if "importance_flag" not in event:
            event["importance_flag"] = "REGULAR"

    return data


def _empty_extraction() -> dict:
    """LLM 不可用时的空结构，保证下游不崩溃"""
    return {
        "document_metadata": {"doc_id": "", "title": "", "date": ""},
        "entities_mentioned": [],
        "timeline_extraction": [],
        "causally_related_entities": [],
    }


async def extract_section(
    section_text: str,
    section_heading: str = "",
    rule_facts: list[dict] | None = None,
) -> dict[str, Any]:
    """
    分节 LLM 提取：专注于归因/决策/因果关系。
    接受单个 section 的文本，告知 LLM 哪些数字已由规则引擎确认。

    Args:
        section_text: 章节文本内容
        section_heading: 章节标题
        rule_facts: 规则引擎已确认的数字事实列表

    Returns:
        包含 causally_related_entities 和 attributions 的 dict
    """
    # 构建规则事实提示
    rule_facts_hint = ""
    if rule_facts:
        facts_str = "; ".join(
            f"{f.get('entity', '')}: {f.get('value', '')}" for f in rule_facts[:10]
        )
        rule_facts_hint = f"\n\n以下数字已由规则引擎确认: {facts_str}。请专注于提取归因分析、决策记录和因果关系，不要单独列出数字值，但可以在归因描述中引用。"

    user_message = f"请分析以下章节（{section_heading}），提取因果关系和归因分析：\n\n{section_text}{rule_facts_hint}"

    try:
        result = await generate_json(
            prompt=user_message,
            system_prompt=SECTION_EXTRACTION_SYSTEM_PROMPT,
            temperature=0.1,
            timeout=30.0,
        )

        # 确保结构完整
        if "causally_related_entities" not in result:
            result["causally_related_entities"] = []
        if "attributions" not in result:
            result["attributions"] = []

        return result

    except (LLMError, TimeoutError):
        # 所有模型失败，返回空结构
        return {"causally_related_entities": [], "attributions": []}

