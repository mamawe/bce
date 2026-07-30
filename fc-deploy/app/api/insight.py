from __future__ import annotations
"""
洞察生成器 - 基于实体时间线生成模式识别、风险提示和建议
MVP 阶段使用规则引擎，不依赖 LLM
"""
import re


def generate_insight(entity_name: str, timeline: list[dict]) -> dict:
    """
    基于时间线数据生成洞察：
    - pattern: 检测重复出现的模式
    - risk: 识别未解决的风险项
    - suggestion: 简单建议
    """
    if not timeline:
        return {
            "pattern": f"暂无 {entity_name} 的历史事件数据",
            "risk": "数据不足，无法评估风险",
            "suggestion": "持续导入周报以积累上下文",
        }

    # ─── 模式检测：统计事件类型和归因关键词 ───
    attributions = [e.get("attribution", "") for e in timeline if e.get("attribution")]

    # 检测重复归因（相同关键词出现多次）
    pattern = _detect_pattern(entity_name, timeline, attributions)

    # ─── 风险识别：查找 PENDING 状态的决策 ───
    risk = _detect_risk(timeline)

    # ─── 建议生成 ───
    suggestion = _generate_suggestion(entity_name, timeline, risk)

    return {
        "pattern": pattern,
        "risk": risk,
        "suggestion": suggestion,
    }


def _detect_pattern(entity_name: str, timeline: list[dict], attributions: list[str]) -> str:
    """检测重复模式"""
    total_events = len(timeline)

    # 统计 FLUCTUATION 类型事件
    fluctuations = [e for e in timeline if e.get("event_type") == "FLUCTUATION"]

    if len(fluctuations) >= 2:
        # 查找归因中的共同关键词
        common_keywords = _find_common_keywords(attributions)
        if common_keywords:
            keywords_str = "、".join(common_keywords[:3])
            return (
                f"{entity_name} 在观察期内出现 {len(fluctuations)} 次波动，"
                f"均与{keywords_str}相关"
            )
        return f"{entity_name} 在观察期内出现 {len(fluctuations)} 次波动，存在周期性风险"

    if total_events >= 3:
        return f"{entity_name} 共有 {total_events} 条事件记录，整体趋势稳定"

    return f"{entity_name} 当前事件记录较少（{total_events} 条），暂无明显模式"


def _detect_risk(timeline: list[dict]) -> str:
    """识别未解决的风险"""
    pending_decisions = []
    for event in timeline:
        decision = event.get("decision")
        if decision and decision.get("outcome") == "PENDING":
            pending_decisions.append(decision)

    if pending_decisions:
        actions = [d.get("action", "未知动作") for d in pending_decisions]
        return f"有 {len(pending_decisions)} 项决策待落地：{'；'.join(actions[:2])}"

    # 检查最近事件是否有负面信号
    if timeline:
        latest = timeline[-1]
        if latest.get("event_type") == "FLUCTUATION" and "下降" in latest.get("summary", ""):
            return f"最近一次事件为下降波动：{latest.get('summary', '')}"

    return "当前无未解决的风险项"


def _generate_suggestion(entity_name: str, timeline: list[dict], risk: str) -> str:
    """生成简单建议"""
    if "待落地" in risk:
        return f"建议跟进 {entity_name} 相关待落地决策的执行进度，设定明确时间节点"

    fluctuations = [e for e in timeline if e.get("event_type") == "FLUCTUATION"]
    if len(fluctuations) >= 2:
        return f"建议为 {entity_name} 建立预警机制，在类似波动出现前主动干预"

    return f"持续关注 {entity_name} 相关指标变化，保持周报导入频率"


def _find_common_keywords(texts: list[str]) -> list[str]:
    """从多段归因文本中找出共同关键词"""
    if len(texts) < 2:
        return []

    # 提取中文词组和关键业务术语
    keyword_sets = []
    for text in texts:
        # 提取 2-6 字的中文词组
        words = set(re.findall(r"[\u4e00-\u9fff]{2,6}", text))
        # 加入英文术语
        words.update(re.findall(r"[A-Za-z]+", text))
        keyword_sets.append(words)

    # 找交集
    common = keyword_sets[0]
    for ks in keyword_sets[1:]:
        common = common & ks

    # 过滤掉太通用的词
    stop_words = {"导致", "下降", "本周", "上周", "环比", "主要", "由于", "因为", "其中"}
    common = common - stop_words

    return list(common)[:5]
