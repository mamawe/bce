from __future__ import annotations
"""
Ask 端点处理器 - 语义理解 + 维度拆解 + 通用指标查询
核心原则：
1. LLM 理解语义（意图分类 + SQL 生成），规则做快速路径
2. 数值计算在 SQL/Python 层完成，LLM 不参与计算
3. 单值/多维查询统一使用 metric_sql handler，动态路由
"""
import re
import json
import time

from app import database as db
from app.llm_client import generate, LLMError
from app.api import precompute, answer_validator
from app.api.insight import generate_insight as rule_insight
from app.timeline.timeline_builder import build_timeline_for_entity
from app.normalizer import entity_hierarchy


# ─── 实体字典缓存（5 分钟刷新） ──────────────────────────────────

_entity_dict_cache = None
_entity_dict_cache_time = 0


def _get_entity_dict() -> dict:
    """Cached entity dictionary, refreshed every 5 minutes."""
    global _entity_dict_cache, _entity_dict_cache_time
    now = time.time()
    if _entity_dict_cache is None or (now - _entity_dict_cache_time) > 300:
        entities = db.list_entities()
        all_aliases = db.get_all_aliases()
        _entity_dict_cache = {}
        for e in entities:
            eid = e["entity_id"]
            names = [e["entity_name"]] + all_aliases.get(eid, [])
            for name in names:
                _entity_dict_cache[name.lower()] = e
        _entity_dict_cache_time = now
    return _entity_dict_cache


# ─── v2: 语义理解层（LLM 意图分类 + 规则快速路径） ──────────────

# 缓存 LLM 分类结果（避免重复调用）
_intent_cache: dict[str, tuple[str, str]] = {}
_INTENT_CACHE_MAX = 200

# 意图分类 prompt
_CLASSIFY_SYSTEM = """你是一个意图分类器。根据用户问题，判断它属于哪种查询类型。

可选类型：
- METRIC_VALUE: 查询某个指标的具体数值（"GMV是多少"、"最新毛利率"）
- METRIC_DISTRIBUTION: 查询按某个维度的分布/占比/拆解（"各品类GMV占比"、"按商户类型分的毛利率"）
- COMPARISON: 多实体/多时间对比（"肉类和蔬菜哪个GMV高"、"上周对比这周"）
- ATTRIBUTION: 归因分析（"为什么下降"、"原因是什么"）
- TREND: 趋势变化（"最近5周GMV走势"、"毛利率变化趋势"）
- WHAT_IF: 情景模拟（"如果涨价10%"、"假设销量翻倍"）
- ENTITY_LOOKUP: 查询实体信息（"介绍一下肉类"、"沙县小吃的情况"）

规则：
1. 只返回类型名称，不要解释
2. 如果同时涉及数值和维度，选 METRIC_DISTRIBUTION
3. 如果同时涉及数值和对比，选 COMPARISON
4. 如果不确定，返回 UNKNOWN

示例：
Q: 本周GMV是多少
A: METRIC_VALUE

Q: 各品类毛利率排名
A: METRIC_DISTRIBUTION

Q: 肉类为什么卖得不好
A: ATTRIBUTION

Q: 如果下雨销量会怎样
A: WHAT_IF

Q: 各商户类型的客单价对比
A: COMPARISON"""


async def _classify_with_llm(question: str) -> tuple[str, str] | None:
    """LLM 意图分类，返回 (question_type, handler_name) 或 None（失败时）"""
    # 检查缓存
    if question in _intent_cache:
        return _intent_cache[question]

    try:
        raw = await generate(
            question,
            system_prompt=_CLASSIFY_SYSTEM,
            max_tokens=20,
            temperature=0.0,
        )
        intent = raw.strip().upper()

        # 校验返回值合法
        valid_types = {
            "METRIC_VALUE": "metric_sql",
            "METRIC_DISTRIBUTION": "metric_sql",
            "COMPARISON": "metric_sql",
            "ATTRIBUTION": "llm_analytical",
            "TREND": "metric_sql",
            "WHAT_IF": "python_what_if",
            "ENTITY_LOOKUP": "sql_factual",
        }
        if intent in valid_types:
            result = (intent, valid_types[intent])
            # 写入缓存
            if len(_intent_cache) >= _INTENT_CACHE_MAX:
                _intent_cache.clear()
            _intent_cache[question] = result
            return result
        return None
    except (LLMError, TimeoutError):
        return None


def classify_question(question: str) -> tuple[str, str]:
    """
    v2 分类：先规则快速路径，不命中则标记为 UNKNOWN 推迟到 handle_ask 中 LLM 分类。
    
    Returns:
        (question_type, handler_name) — 规则命中时直接返回
        或 ("UNKNOWN", "") — 不命中，需要 LLM 补充分类
    """
    # 规则快速路径（高频模式，保持低延迟）
    fast_patterns = [
        (r"(如果|假设|预计.*会|将会|情景)", "WHAT_IF", "python_what_if"),
        (r"(为什么|原因|归因|怎么回事|什么决策|做了什么)", "ATTRIBUTION", "llm_analytical"),
        (r"(趋势|走势|变化|最近.*周)", "TREND", "metric_sql"),
        (r"(排名|排序|前[几\d]|top|TOP)", "METRIC_DISTRIBUTION", "metric_sql"),
        (r"(多少|是什么|最新值|当前值|数值|是多少)", "METRIC_VALUE", "metric_sql"),
        (r"(平均|总和|总计|累计|统计|汇总|环比|同比)", "METRIC_VALUE", "metric_sql"),
        (r"(对比|比较|谁更|哪个更|差异|vs|VS)", "COMPARISON", "metric_sql"),
    ]

    for pattern, qtype, handler in fast_patterns:
        if re.search(pattern, question):
            return qtype, handler

    # 含有维度关键词时，直接走 METRIC_DISTRIBUTION
    dimension_kws = [
        r"(各品类|分品类|按品类|品类分布|品类占比|品类.*比例)",
        r"(各商户|分商户|按商户|商户分布|各门店)",
        r"(分城市|按城市|城市分布|各地区)",
        r"(按时间|分时段|各时段|月度|季度)",
    ]
    for kw in dimension_kws:
        if re.search(kw, question):
            return "METRIC_DISTRIBUTION", "metric_sql"

    # 含有时序+指标关键词，走 TREND
    if re.search(r"(周|月|年|时间段|周期)", question) and re.search(
        r"(GMV|订单|毛利|利率|客单价|复购|损耗|成本)", question
    ):
        return "TREND", "metric_sql"

    # 未命中规则，标记 UNKNOWN，推迟到 handle_ask 中调用 LLM
    return "UNKNOWN", ""


async def _classify_question_full(question: str) -> tuple[str, str]:
    """
    完整分类：先规则，再 LLM 兜底。
    """
    qtype, handler = classify_question(question)
    if qtype != "UNKNOWN":
        return qtype, handler

    # LLM 兜底
    llm_result = await _classify_with_llm(question)
    if llm_result:
        return llm_result

    # LLM 也失败 → 默认 metric_sql（最常见的查询类型）
    return "METRIC_VALUE", "metric_sql"


def extract_entities_from_question(question: str) -> list[dict]:
    """
    从问题中提取涉及的实体（v4: 增加位置追踪 + 实体对推导）。
    返回扁平实体列表（兼容旧接口），同时在 `_last_entity_pairs` 中缓存配对关系。
    """
    entity_dict = _get_entity_dict()

    # 按别名长度降序匹配（优先匹配长词，避免短词误匹配）
    sorted_aliases = sorted(entity_dict.keys(), key=len, reverse=True)
    found_entities: list[dict] = []
    found_ids: set[str] = set()
    consumed_ranges: list[tuple[int, int]] = []  # 已匹配的区间，防止重叠

    q_lower = question.lower()

    for alias in sorted_aliases:
        if not alias or len(alias) < 2:
            continue
        if alias not in q_lower:
            continue

        # 找到 alias 在问题中的所有出现位置
        start = 0
        while True:
            idx = q_lower.find(alias, start)
            if idx == -1:
                break
            end = idx + len(alias)

            # 检查是否已被更长的 alias 覆盖
            if any(rs <= idx and end <= re for rs, re in consumed_ranges):
                start = idx + 1
                continue

            ent = entity_dict[alias]
            if ent["entity_id"] not in found_ids:
                # 检查此实体是否有时间线数据
                events = db.get_events_for_entity(ent["entity_id"])
                if not events:
                    conn = db.get_connection()
                    try:
                        row = conn.execute(
                            "SELECT COUNT(*) as c FROM timeline_events WHERE entity_id LIKE ?",
                            (f"{ent['entity_id']}_%",),
                        ).fetchone()
                        has_related = row["c"] > 0 if row else False
                    finally:
                        conn.close()
                else:
                    has_related = False

                found_entities.append({
                    "entity_id": ent["entity_id"],
                    "entity_name": ent["entity_name"],
                    "category": ent["category"],
                    "has_data": bool(events) or has_related,
                    "_pos": idx,  # 内部字段，记录位置
                })
                found_ids.add(ent["entity_id"])
                consumed_ranges.append((idx, end))

            start = idx + 1

    # 推导实体对（维度 + 指标配对）
    global _last_entity_pairs
    _last_entity_pairs = _derive_entity_pairs(found_entities)

    # 移除内部 _pos 字段再返回
    for e in found_entities:
        e.pop("_pos", None)

    # 优先排序有数据的实体
    found_entities.sort(key=lambda e: not e.get("has_data", False))

    return found_entities


# 实体对推导的缓存（同一问题的实体对，供 handle_ask 读取）
_last_entity_pairs = []


def _derive_entity_pairs(entities: list[dict]) -> list[dict]:
    """
    根据实体在问题中的位置推导"维度 + 指标"配对。
    
    规则：
    - OBJECT/OWNER（维度）后面紧跟 METRIC（指标）→ 配对
    - 相邻的 OBJECT + METRIC 视为一组查询条件
    
    示例：
    "沙县小吃商户品类宽度" → [(OWNER_沙县小吃, METRIC_品类宽度)]
    "蔬菜品类 GMV" → [(OBJECT_蔬菜, METRIC_GMV)]
    "蔬菜损耗率" → [(OBJECT_蔬菜, METRIC_损耗率)]
    """
    if len(entities) < 2:
        return []

    # 按位置排序（实体在问题中的出现顺序）
    sorted_ents = sorted(
        [e for e in entities if "_pos" in e],
        key=lambda e: e["_pos"],
    )
    if len(sorted_ents) < 2:
        return []

    pairs: list[dict] = []
    i = 0
    while i < len(sorted_ents) - 1:
        cur = sorted_ents[i]
        nxt = sorted_ents[i + 1]
        cur_cat = cur.get("category", "")
        nxt_cat = nxt.get("category", "")

        # 维度类型（前面） + 指标类型（后面）
        dim_types = {"OBJECT", "OWNER", "EVENT"}
        metric_types = {"METRIC"}

        if cur_cat in dim_types and nxt_cat in metric_types:
            pairs.append({
                "dimension": {
                    "entity_id": cur["entity_id"],
                    "entity_name": cur["entity_name"],
                    "category": cur_cat,
                },
                "metric": {
                    "entity_id": nxt["entity_id"],
                    "entity_name": nxt["entity_name"],
                    "category": nxt_cat,
                },
                "dimension_type": "category" if cur_cat == "OBJECT" else "merchant_type" if cur_cat == "OWNER" else "event",
            })
            i += 2  # 跳过已配对的两个实体
        else:
            i += 1

    return pairs


def get_last_entity_pairs() -> list[dict]:
    """获取最近一次实体提取的配对关系（供 handler 使用）。"""
    return _last_entity_pairs


# ─── 主处理函数 ────────────────────────────────────────────────

async def handle_ask(question: str, context: dict = None) -> dict:
    """
    /ask 端点主入口。
    完整流程：分类 → 数据检索 → LLM 生成 → 校验 → 降级

    Args:
        question: 用户问题
        context: 可选上下文（entity_ids, time_range, document_ids）

    Returns:
        结构化回答
    """
    start_time = time.time()
    context = context or {}

    # Step 1: 意图分类（规则快速路径 + LLM 兜底）
    question_type, handler_name = classify_question(question)
    
    # 规则未命中时，调用 LLM 语义理解
    if question_type == "UNKNOWN":
        question_type, handler_name = await _classify_question_full(question)

    # 提取实体
    entities = extract_entities_from_question(question)

    # 如果 context 中指定了 entity_ids，补充进来
    for eid in context.get("entity_ids", []):
        ent = db.get_entity(eid)
        if ent and ent["entity_id"] not in {e["entity_id"] for e in entities}:
            entities.append({
                "entity_id": ent["entity_id"],
                "entity_name": ent["entity_name"],
                "category": ent["category"],
            })

    # Step 2: 根据 handler 分发
    handler = HANDLERS.get(handler_name, _handle_llm_general)

    try:
        result = await handler(question, entities, context)
    except Exception as e:
        # handler 异常时，先尝试通用 LLM 回答，再降级到规则引擎
        try:
            result = await _handle_llm_general(question, entities, context)
        except Exception:
            result = await _fallback_to_rules(question, entities, str(e))

    result["question"] = question
    result["question_type"] = question_type
    result["entities"] = entities
    result["response_time_ms"] = int((time.time() - start_time) * 1000)

    return result


# ─── Handler 1: sql_factual（事实查询，纯 SQL，不经过 LLM） ──────

async def _handle_sql_factual(question: str, entities: list[dict], context: dict) -> dict:
    """事实查询：直接从时间线和预计算指标中提取答案"""
    if not entities:
        return {
            "answer": "无法识别问题中涉及的实体，请尝试明确实体名称。",
            "confidence": "low",
            "fallback_used": False,
        }

    entity_id = entities[0]["entity_id"]
    timeline = build_timeline_for_entity(entity_id)
    metrics = precompute.get_metrics(entity_id)

    if not timeline:
        return {
            "answer": f"暂无 {entities[0]['entity_name']} 的历史数据。",
            "confidence": "medium",
            "fallback_used": False,
        }

    # 取最近的事件作为事实
    latest = timeline[-1] if timeline else {}
    metric_value = latest.get("metric_value")
    metric_unit = latest.get("metric_unit") or ""
    metric_delta_pct = latest.get("metric_delta_pct")
    entity_name = entities[0]['entity_name']
    occurred_at = latest.get('occurred_at', '未知时间')

    # 优先用精确数值回答
    if metric_value is not None:
        value_str = f"{metric_value:,.1f}" if isinstance(metric_value, float) else f"{metric_value:,}"
        answer_parts = [f"{entity_name} 最新值（{occurred_at}）：{value_str} {metric_unit}".strip()]
        if metric_delta_pct is not None:
            direction = "上升" if metric_delta_pct >= 0 else "下降"
            answer_parts[0] += f"，环比{direction} {abs(metric_delta_pct)}%"
    else:
        latest_summary = latest.get("summary", "无数据")
        answer_parts = [f"{entity_name} 最新记录（{occurred_at}）：{latest_summary}"]

    answer_parts.append(f"共 {metrics['event_count']} 条事件记录，其中 {metrics['fluctuation_count']} 次波动。")

    if metrics["pending_decisions"] > 0:
        answer_parts.append(f"当前有 {metrics['pending_decisions']} 项待落地决策。")

    return {
        "answer": " ".join(answer_parts),
        "confidence": "high",
        "fallback_used": False,
    }


# ─── Handler 2: precomputed（聚合查询，预计算，不经过 LLM） ──────

async def _handle_precomputed(question: str, entities: list[dict], context: dict) -> dict:
    """聚合查询：使用预计算指标"""
    if not entities:
        return {
            "answer": "无法识别问题中涉及的实体，请尝试明确实体名称。",
            "confidence": "low",
            "fallback_used": False,
        }

    entity_id = entities[0]["entity_id"]
    metrics = precompute.get_metrics(entity_id)
    rolling = precompute.get_rolling_stats(entity_id, window=7)

    answer_parts = [
        f"{entities[0]['entity_name']} 统计汇总：",
        f"- 事件总数：{metrics['event_count']}",
        f"- 波动次数：{metrics['fluctuation_count']}",
        f"- 决策数：{metrics['decision_count']}（待落地：{metrics['pending_decisions']}）",
        f"- 首次记录：{metrics.get('first_seen', '未知')}",
        f"- 最近记录：{metrics.get('last_seen', '未知')}",
    ]

    if rolling["count"] > 0:
        answer_parts.append(
            f"- 最近 {rolling['count']} 条事件中，波动 {rolling['fluctuation_count']} 次"
            f"（波动率 {rolling['fluctuation_rate']}%）"
        )

    if metrics.get("top_attribution"):
        answer_parts.append(f"- 最高频归因：{metrics['top_attribution']}")

    # 子实体贡献度（如果有层级）
    if db.has_children(entity_id):
        contributions = entity_hierarchy.drilldown_contribution(entity_id)
        if contributions:
            answer_parts.append("\n子实体贡献度：")
            for c in contributions[:5]:
                answer_parts.append(
                    f"  - {c['entity_name']}：{c['event_count']} 条事件（{c['contribution_pct']}%）"
                )

    return {
        "answer": "\n".join(answer_parts),
        "confidence": "high",
        "fallback_used": False,
    }


# ─── Handler 3: sql_comparison（对比查询，SQL + LLM 解释） ──────

async def _handle_sql_comparison(question: str, entities: list[dict], context: dict) -> dict:
    """对比查询：SQL 查询多个实体 + LLM 解释差异"""
    if len(entities) < 2:
        return {
            "answer": "对比查询需要至少两个实体，请明确要对比的实体。",
            "confidence": "low",
            "fallback_used": False,
        }

    # 获取每个实体的指标（SQL 计算）
    comparison_data = []
    for ent in entities[:4]:  # 最多对比 4 个
        metrics = precompute.get_metrics(ent["entity_id"])
        comparison_data.append({
            "entity_name": ent["entity_name"],
            "event_count": metrics["event_count"],
            "fluctuation_count": metrics["fluctuation_count"],
            "pending_decisions": metrics["pending_decisions"],
            "last_seen": metrics.get("last_seen"),
            "top_attribution": metrics.get("top_attribution"),
        })

    # LLM 解释差异
    prompt = _build_comparison_prompt(question, comparison_data)

    try:
        answer = await generate(prompt, timeout=15.0)
        validation = answer_validator.validate_answer(
            answer, [], {"comparison_data": comparison_data}, entities
        )

        confidence = "high" if validation["passed"] else "medium"

        return {
            "answer": answer,
            "confidence": confidence,
            "fallback_used": False,
            "validation_errors": validation.get("errors", []),
        }
    except (TimeoutError, LLMError):
        # 降级：直接返回对比数据
        answer_lines = ["对比结果（数据）："]
        for item in comparison_data:
            answer_lines.append(
                f"- {item['entity_name']}：{item['event_count']} 条事件，"
                f"{item['fluctuation_count']} 次波动"
            )
        return {
            "answer": "\n".join(answer_lines),
            "confidence": "medium",
            "fallback_used": True,
            "fallback_reason": "LLM 不可用，返回原始数据",
        }


# ─── Handler 4: llm_analytical（归因分析，LLM 推理） ────────────

async def _handle_llm_analytical(question: str, entities: list[dict], context: dict) -> dict:
    """归因分析：结构化数据 + LLM 推理 + 校验 + 降级"""
    if not entities:
        return {
            "answer": "无法识别问题中涉及的实体，请尝试明确实体名称。",
            "confidence": "low",
            "fallback_used": False,
        }

    # 收集所有相关实体的数据（含子孙实体）
    all_entity_ids = set()
    for ent in entities:
        all_entity_ids.add(ent["entity_id"])
        # 如果有子孙实体，也纳入
        descendants = entity_hierarchy.get_descendant_ids(ent["entity_id"])
        all_entity_ids.update(descendants)

    # 获取时间线（SQL）
    timeline = []
    for eid in all_entity_ids:
        timeline.extend(build_timeline_for_entity(eid))

    # 按时间排序，取最近 10 条
    timeline.sort(key=lambda e: e.get("occurred_at", ""), reverse=True)
    timeline = timeline[:10]

    # 获取预计算指标（Python 计算）
    entity_id = entities[0]["entity_id"]
    metrics = precompute.get_metrics(entity_id)

    # 子实体贡献度
    children = []
    if db.has_children(entity_id):
        children = entity_hierarchy.drilldown_contribution(entity_id)

    # 如果没有数据
    if not timeline and not metrics["event_count"]:
        return {
            "answer": f"暂无 {entities[0]['entity_name']} 的历史数据，无法进行归因分析。",
            "confidence": "low",
            "fallback_used": False,
        }

    # LLM 推理
    prompt = _build_analytical_prompt(question, entities, timeline, metrics, children)

    try:
        answer = await generate(prompt, timeout=15.0)

        # 回答校验
        validation = answer_validator.validate_answer(answer, timeline, metrics, entities)

        if validation["passed"]:
            return {
                "answer": answer,
                "confidence": "high",
                "fallback_used": False,
            }
        else:
            # 校验失败：保留 LLM 结果但降级置信度
            rule_result = rule_insight(entities[0]["entity_name"], timeline)
            return {
                "answer": answer,
                "rule_insight": rule_result,
                "confidence": "low",
                "fallback_used": False,
                "validation_errors": validation["errors"],
            }

    except (TimeoutError, LLMError) as e:
        # 降级到规则引擎
        rule_result = rule_insight(entities[0]["entity_name"], timeline)
        return {
            "answer": _format_rule_insight(rule_result),
            "confidence": "medium",
            "fallback_used": True,
            "fallback_reason": str(e),
        }


# ─── Handler 5: python_what_if（情景分析，Python 计算 + LLM 解释） ─

async def _handle_python_what_if(question: str, entities: list[dict], context: dict) -> dict:
    """情景分析：Python 精确计算 + LLM 解释"""
    if not entities:
        return {
            "answer": "无法识别问题中涉及的实体，请尝试明确实体名称。",
            "confidence": "low",
            "fallback_used": False,
        }

    entity_id = entities[0]["entity_id"]
    metrics = precompute.get_metrics(entity_id)
    timeline = build_timeline_for_entity(entity_id)

    # 提取问题中的数字参数（如"涨价10%"中的10）
    numbers = re.findall(r"(\d+\.?\d*)\s*[%％]", question)
    hypothetical_value = float(numbers[0]) if numbers else None

    # 基于当前指标做 what-if 计算（Python Decimal 精确计算）
    calculation = {
        "type": "what_if",
        "input": {
            "event_count": metrics["event_count"],
            "fluctuation_count": metrics["fluctuation_count"],
            "hypothetical_pct": hypothetical_value,
        },
    }

    # 简单的 what-if：如果波动率增加 X%，预计影响
    if hypothetical_value is not None and metrics["event_count"] > 0:
        from decimal import Decimal, getcontext
        getcontext().prec = 10

        current_rate = Decimal(str(metrics["fluctuation_count"])) / Decimal(str(metrics["event_count"]))
        adjusted_rate = current_rate * (Decimal("1") + Decimal(str(hypothetical_value)) / Decimal("100"))
        calculation["formula"] = "fluctuation_rate * (1 + hypothetical_pct / 100)"
        calculation["result"] = {
            "current_fluctuation_rate": float(current_rate * 100),
            "adjusted_fluctuation_rate": float(adjusted_rate * 100),
        }
        calculation["explanation"] = (
            f"如果波动因素增加 {hypothetical_value}%，"
            f"波动率将从 {float(current_rate*100):.1f}% 升至 {float(adjusted_rate*100):.1f}%"
        )
    else:
        calculation["result"] = None
        calculation["explanation"] = "无法从问题中提取假设参数，请明确指定（如'涨价10%'）"

    # LLM 解释
    prompt = _build_what_if_prompt(question, entities, metrics, calculation)

    try:
        answer = await generate(prompt, timeout=15.0)
        validation = answer_validator.validate_answer(answer, timeline, metrics, entities)

        return {
            "answer": answer,
            "calculation": calculation,
            "confidence": "high" if validation["passed"] else "medium",
            "fallback_used": False,
        }

    except (TimeoutError, LLMError):
        # 降级：直接返回计算结果
        return {
            "answer": calculation["explanation"],
            "calculation": calculation,
            "confidence": "medium",
            "fallback_used": True,
            "fallback_reason": "LLM 不可用，返回原始计算结果",
        }


# ─── Handler 6: llm_general（通用 LLM 回答，兜底） ──────────────

async def _handle_llm_general(question: str, entities: list[dict], context: dict) -> dict:
    """通用 LLM 回答：收集实体上下文，让 LLM 自由作答。仅 LLM 失败时降级到规则。"""
    # 收集上下文
    timeline = []
    metrics = {}
    children = []

    if entities:
        all_entity_ids = set()
        for ent in entities:
            all_entity_ids.add(ent["entity_id"])
            descendants = entity_hierarchy.get_descendant_ids(ent["entity_id"])
            all_entity_ids.update(descendants)

        for eid in all_entity_ids:
            timeline.extend(build_timeline_for_entity(eid))

        timeline.sort(key=lambda e: e.get("occurred_at", ""), reverse=True)
        timeline = timeline[:15]

        entity_id = entities[0]["entity_id"]
        metrics = precompute.get_metrics(entity_id)

        if db.has_children(entity_id):
            children = entity_hierarchy.drilldown_contribution(entity_id)

    # 构建 prompt
    prompt = _build_general_prompt(question, entities, timeline, metrics, children)

    try:
        answer = await generate(prompt, timeout=20.0)
        return {
            "answer": answer,
            "source": "llm",
            "confidence": "medium",
            "fallback_used": False,
        }
    except (TimeoutError, LLMError) as e:
        # LLM 不可用，降级到规则引擎
        if entities and timeline:
            rule_result = rule_insight(entities[0]["entity_name"], timeline)
            return {
                "answer": _format_rule_insight(rule_result),
                "source": "rules",
                "confidence": "low",
                "fallback_used": True,
                "fallback_reason": f"LLM 不可用: {e}",
            }
        return {
            "answer": "系统暂时无法处理该问题（LLM 服务不可用），请稍后重试。",
            "source": "rules",
            "confidence": "low",
            "fallback_used": True,
            "fallback_reason": f"LLM 不可用: {e}",
        }


# ─── 降级策略 ──────────────────────────────────────────────────

async def _fallback_to_rules(question: str, entities: list[dict], reason: str) -> dict:
    """降级到规则引擎"""
    if not entities:
        return {
            "answer": "系统暂时无法处理该问题，且无法识别相关实体。",
            "confidence": "low",
            "fallback_used": True,
            "fallback_reason": reason,
        }

    entity_id = entities[0]["entity_id"]
    timeline = build_timeline_for_entity(entity_id)
    rule_result = rule_insight(entities[0]["entity_name"], timeline)

    return {
        "answer": _format_rule_insight(rule_result),
        "confidence": "medium",
        "fallback_used": True,
        "fallback_reason": reason,
    }


def _format_rule_insight(rule_result: dict) -> str:
    """将规则引擎的 dict 结果格式化为文本"""
    parts = []
    if isinstance(rule_result, dict):
        for key, label in [("pattern", "模式"), ("risk", "风险"), ("suggestion", "建议")]:
            value = rule_result.get(key)
            if value:
                parts.append(f"【{label}】{value}")
    elif isinstance(rule_result, str):
        parts.append(rule_result)

    return "\n".join(parts) if parts else "暂无可用的分析结果"


# ─── Prompt 构建 ───────────────────────────────────────────────

def _build_analytical_prompt(question: str, entities: list[dict],
                              timeline: list[dict], metrics: dict,
                              children: list[dict]) -> str:
    """构建归因分析 prompt"""
    entity_names = "、".join(e["entity_name"] for e in entities)

    # 将 timeline 序列化时只保留关键字段
    timeline_brief = [
        {
            "time": e.get("occurred_at"),
            "summary": e.get("summary"),
            "type": e.get("event_type"),
            "attribution": e.get("attribution"),
            "decision": e.get("decision", {}).get("action") if e.get("decision") else None,
        }
        for e in timeline
    ]

    return f"""你是一个资深商业分析师。基于以下结构化数据回答问题。

## 实体
{entity_names}

## 时间线事件（最近 {len(timeline)} 条）
{json.dumps(timeline_brief, ensure_ascii=False, indent=2)}

## 预计算指标
{json.dumps(metrics, ensure_ascii=False, indent=2)}

## 子实体贡献度
{json.dumps(children, ensure_ascii=False, indent=2) if children else '无子实体'}

## 问题
{question}

## 要求
1. 只使用提供的数据，不要编造任何数字或事实。
2. 所有数字引用预计算指标中的精确值。
3. 如果数据不足以回答，说"数据不足"并说明缺少什么。
4. 引用具体日期和事件作为来源。
5. 回答简洁，重点突出因果分析。
"""


def _build_comparison_prompt(question: str, comparison_data: list[dict]) -> str:
    """构建对比查询 prompt"""
    return f"""你是一个商业分析师。基于以下对比数据回答问题。

## 对比数据
{json.dumps(comparison_data, ensure_ascii=False, indent=2)}

## 问题
{question}

## 要求
1. 只使用提供的数据，不要编造数字。
2. 清晰列出各实体的关键指标差异。
3. 指出最显著的差异点。
"""


def _build_what_if_prompt(question: str, entities: list[dict],
                           metrics: dict, calculation: dict) -> str:
    """构建情景分析 prompt"""
    return f"""你是一个商业分析师。基于以下计算结果回答问题。

## 实体
{entities[0]['entity_name'] if entities else '未知'}

## 当前指标
{json.dumps(metrics, ensure_ascii=False, indent=2)}

## 计算结果（Python 精确计算）
{json.dumps(calculation, ensure_ascii=False, indent=2)}

## 问题
{question}

## 要求
1. 基于计算结果解释情景分析的含义。
2. 不要重新计算，直接引用计算结果中的数字。
3. 如果计算结果为空，说明参数不足。
"""


def _build_general_prompt(question: str, entities: list[dict],
                           timeline: list[dict], metrics: dict,
                           children: list[dict]) -> str:
    """构建通用 LLM 回答 prompt"""
    entity_names = "、".join(e["entity_name"] for e in entities) if entities else "未知"

    timeline_brief = [
        {
            "time": e.get("occurred_at"),
            "summary": e.get("summary"),
            "type": e.get("event_type"),
            "attribution": e.get("attribution"),
        }
        for e in timeline
    ] if timeline else []

    context_parts = [f"## 相关实体\n{entity_names}"]

    if timeline_brief:
        context_parts.append(
            f"## 时间线事件（最近 {len(timeline_brief)} 条）\n"
            f"{json.dumps(timeline_brief, ensure_ascii=False, indent=2)}"
        )

    if metrics:
        context_parts.append(
            f"## 预计算指标\n{json.dumps(metrics, ensure_ascii=False, indent=2)}"
        )

    if children:
        context_parts.append(
            f"## 子实体贡献度\n{json.dumps(children, ensure_ascii=False, indent=2)}"
        )

    context_block = "\n\n".join(context_parts)

    return f"""你是一个资深商业分析师助手。基于以下已有的结构化数据，尽可能回答用户的问题。

{context_block}

## 用户问题
{question}

## 要求
1. 只使用提供的数据，不要编造任何数字或事实。
2. 如果数据不足以完整回答，基于已有数据给出部分回答，并说明哪些方面数据不足。
3. 回答简洁、有条理，使用中文。
4. 如果完全没有相关数据，诚实告知用户当前系统暂无相关信息。
"""


# ─── Handler 6: metric_sql（NL→SQL 查宽表） ──────────────────────

_METRIC_SQL_SYSTEM = """你是一个 SQL 生成器。根据用户的自然语言问题，生成查询 metric_facts 表的 SQLite SQL。

表结构：
CREATE TABLE metric_facts (
    id INTEGER PRIMARY KEY,
    report_date TEXT,        -- 日期，如 2026-07-28
    week_label TEXT,         -- 周标签，如 2026-W30
    category TEXT,           -- 品类：总体/蔬菜/肉类/蛋类/米类/面类/调料类/油类/水产/豆制品/冻品
    merchant_type TEXT,      -- 商户类型：NULL/酸辣粉/兰州拉面/沙县小吃/黄焖鸡/麻辣烫
    metric_name TEXT,        -- 指标名：GMV/订单量/客单价/复购率/品类宽度/毛利率/净利率/商品成本率/运输成本率/仓储成本率/损耗率
    metric_value REAL,       -- 数值（GMV 为日均值，单位万元）
    metric_unit TEXT,        -- 单位：万元/单/元/%/个
    wow_change_pct REAL,     -- 环比变化%
    yoy_change_pct REAL,     -- 同比变化%
    source_doc_id TEXT,
    sensitivity_level INTEGER
);

⚠️ 重要数据上下文：
- 数据库中的年份是 2026，week_label 格式为 2026-W20 到 2026-W30
- 永远不要使用 2023、2024、2025 等年份，数据全部是 2026 年的
- GMV 存储的是日均值（万元/日），不是周合计
- 要查最新一周直接用 ORDER BY report_date DESC LIMIT 1 或 week_label=(SELECT MAX(week_label) FROM metric_facts)

规则：
1. 只生成 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP
2. "最新/最近/本周" → ORDER BY report_date DESC LIMIT 1
3. "上周" → ORDER BY report_date DESC LIMIT 1 OFFSET 1
4. "趋势" → 按 report_date 排序取最近 N 条
5. "排名" → ORDER BY metric_value DESC
6. "对比" → 用 WHERE category IN (...) 或 GROUP BY category
⚠️ 关键规则：
7. "各品类/各分类/各个品类/每一类" → 必须加 `AND category!='总体'`（"总体"=所有品类之和，包含会重复计算，"总体"会占约50%）
8. 查询特定品类 → 用 `category='品类名'`
9. 查品类或总体数据时（非商户维度），加 AND merchant_type IS NULL
10. 查商户数据时，加 AND merchant_type IS NOT NULL
11. "占比" → 使用窗口函数：metric_value * 100.0 / SUM(metric_value) OVER ()
12. "合计/总计" → GMV 存储的是日均值（万元/日），周合计 = 日均 × 7
13. "最新/最近/本周" → ORDER BY report_date DESC LIMIT 1
14. "上周" → ORDER BY report_date DESC LIMIT 1 OFFSET 1
15. 只输出 SQL，不要解释

示例：
用户: 肉类最新GMV是多少
SQL: SELECT metric_value, metric_unit, report_date, wow_change_pct FROM metric_facts WHERE category='肉类' AND metric_name='GMV' AND merchant_type IS NULL ORDER BY report_date DESC LIMIT 1

用户: 各品类毛利率排名
SQL: SELECT category, metric_value, metric_unit FROM metric_facts WHERE metric_name='毛利率' AND week_label=(SELECT MAX(week_label) FROM metric_facts) AND category!='总体' AND merchant_type IS NULL ORDER BY metric_value DESC

用户: 各品类GMV占比是多少
SQL: SELECT category, metric_value, metric_unit, ROUND(metric_value * 100.0 / SUM(metric_value) OVER (), 1) AS pct FROM metric_facts WHERE metric_name='GMV' AND week_label=(SELECT MAX(week_label) FROM metric_facts) AND category!='总体' AND merchant_type IS NULL ORDER BY metric_value DESC

用户: 各品类日均GMV和占比
SQL: SELECT category, metric_value AS daily_gmv, metric_unit, ROUND(metric_value * 100.0 / SUM(metric_value) OVER (), 1) AS pct FROM metric_facts WHERE metric_name='GMV' AND week_label=(SELECT MAX(week_label) FROM metric_facts) AND category!='总体' AND merchant_type IS NULL ORDER BY metric_value DESC

用户: 各品类贡献了多少
SQL: SELECT category, metric_value AS daily_gmv, metric_unit, ROUND(metric_value * 100.0 / SUM(metric_value) OVER (), 1) AS pct FROM metric_facts WHERE metric_name='GMV' AND week_label=(SELECT MAX(week_label) FROM metric_facts) AND category!='总体' AND merchant_type IS NULL ORDER BY metric_value DESC

用户: 本周GMV日均是多少？合计又是多少？各品类占比是多少？
SQL: SELECT category, metric_value as daily_gmv, metric_unit, ROUND(metric_value * 7, 0) as weekly_total, ROUND(metric_value * 100.0 / SUM(metric_value) OVER (), 1) AS pct FROM metric_facts WHERE metric_name='GMV' AND week_label=(SELECT MAX(week_label) FROM metric_facts) AND category!='总体' AND merchant_type IS NULL ORDER BY metric_value DESC

用户: 总体GMV最近5周趋势
SQL: SELECT week_label, metric_value, wow_change_pct FROM metric_facts WHERE category='总体' AND metric_name='GMV' AND merchant_type IS NULL ORDER BY report_date DESC LIMIT 5
"""


def _execute_metric_sql(sql: str) -> list[dict]:
    """Execute SQL against metric_facts, return rows as dicts."""
    import sqlite3
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return []
    # 禁止危险操作
    for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH"):
        if kw in sql_upper:
            return []
    conn = db.get_connection()
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


async def _handle_metric_sql(question: str, entities: list[dict], context: dict) -> dict:
    """NL→SQL 查宽表：LLM 生成 SQL，执行后格式化返回。"""
    try:
        sql = await generate(
            question,
            system_prompt=_METRIC_SQL_SYSTEM,
            max_tokens=500,
            timeout=5.0,  # SQL 生成要快，超时则降级
        )
        # 提取 SQL（可能被 ```sql ``` 包裹或带 SQL: 前缀）
        sql = sql.strip()
        if sql.startswith("```"):
            sql = sql.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        # 去除 LLM 额外添加的 "SQL:" 前缀
        sql = re.sub(r"^(?:SQL|sql)\s*[:：]?\s*", "", sql)

        rows = _execute_metric_sql(sql)

        if not rows:
            return {
                "answer": "查询未返回结果，请尝试更具体的描述。",
                "confidence": "low",
                "fallback_used": False,
                "sql": sql,
            }

        # 格式化结果
        if len(rows) == 1:
            r = rows[0]
            parts = []
            if "metric_value" in r:
                val = f"{r['metric_value']:,.1f}" if isinstance(r["metric_value"], float) else str(r["metric_value"])
                unit = r.get("metric_unit", "")
                parts.append(f"{val} {unit}".strip())
            if "wow_change_pct" in r and r["wow_change_pct"] is not None:
                direction = "上升" if r["wow_change_pct"] >= 0 else "下降"
                parts.append(f"环比{direction} {abs(r['wow_change_pct'])}%")
            if "report_date" in r:
                parts.append(f"（{r['report_date']}）")
            answer = "，".join(parts) if parts else str(rows[0])
        else:
            # 多行结果，格式化为列表
            lines = []
            for i, r in enumerate(rows[:10], 1):
                parts = []
                if "category" in r and r["category"]:
                    parts.append(r["category"])
                if "merchant_type" in r and r["merchant_type"]:
                    parts.append(r["merchant_type"])
                if "metric_value" in r:
                    val = f"{r['metric_value']:,.1f}" if isinstance(r["metric_value"], float) else str(r["metric_value"])
                    unit = r.get("metric_unit", "")
                    parts.append(f"{val}{unit}")
                if "wow_change_pct" in r and r["wow_change_pct"] is not None:
                    parts.append(f"(环比{'+' if r['wow_change_pct']>=0 else ''}{r['wow_change_pct']}%)")
                lines.append(f"{i}. {' '.join(parts)}")
            answer = "\n".join(lines)

        return {
            "answer": answer,
            "confidence": "high",
            "fallback_used": False,
            "sql": sql,
            "rows": rows,
            "row_count": len(rows),
        }
    except LLMError:
        return {
            "answer": "SQL 生成服务暂不可用，请稍后重试。",
            "confidence": "low",
            "fallback_used": True,
        }


# ─── Handler 注册表 ────────────────────────────────────────────

HANDLERS = {
    "sql_factual": _handle_sql_factual,
    "precomputed": _handle_precomputed,
    "sql_comparison": _handle_sql_comparison,
    "metric_sql": _handle_metric_sql,
    "llm_analytical": _handle_llm_analytical,
    "python_what_if": _handle_python_what_if,
    "llm_general": _handle_llm_general,
}
