"""
BCE 种子数据脚本
将三份样本周报的结构化数据直接灌入 DB，用于无 LLM key 时的端到端演示。
有真实 ZHIPU_API_KEY 后，LLM 管线会自动完成此步骤。
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "bce.db"


def seed():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")

    # 检查是否已有时间线数据，避免重复灌入
    cnt = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    if cnt > 0:
        print(f"已有 {cnt} 条时间线事件，跳过种子数据")
        conn.close()
        return

    # === 确保实体存在 ===
    entities = [
        ("METRIC_GMV", "GMV", "METRIC", "成交总额"),
        ("METRIC_CTR", "CTR", "METRIC", "点击率"),
        ("METRIC_DAU", "DAU", "METRIC", "日活跃用户"),
        ("METRIC_CAC", "CAC", "METRIC", "获客成本"),
        ("METRIC_CVR", "转化率", "METRIC", "下单转化率"),
        ("OBJECT_CHANNEL_B", "渠道B", "OBJECT", "抖音信息流广告渠道"),
        ("EVENT_618", "618大促", "EVENT", "618年中大促活动"),
        ("EXPERIMENT_LANDING_AB", "落地页A/B Test", "EXPERIMENT", "落地页简化实验"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO entities (entity_id, entity_name, category, description) VALUES (?,?,?,?)",
        entities,
    )

    # === GMV 时间线 ===
    gmv_events = [
        ("evt_gmv_w12", "METRIC_GMV", "2026-03-22", "WEEK",
         "GMV 环比下降 12%（约144万）", "FLUCTUATION",
         "广告渠道B预算于3/14被财务审批卡住，实际投放预算骤减40%，新客获取量从日均3200降至1900",
         "doc_2026_w12"),
        ("evt_gmv_w20", "METRIC_GMV", "2026-05-17", "WEEK",
         "GMV 环比增长 3.1%，创近8周新高（1320万）", "FLUCTUATION",
         "渠道B预算审批流程优化落地（双周审批）+ 落地页A/B Test转化率提升18% + 618预热带动自然流量+15%",
         "doc_2026_w20"),
        ("evt_gmv_w28", "METRIC_GMV", "2026-07-12", "WEEK",
         "GMV 环比下降 12.6%（约170万），与W12高度相似", "FLUCTUATION",
         "渠道B 7月预算于7/5到期，新审批延迟至7/8，3天投放空窗期。与W12为同一系统性问题复发",
         "doc_2026_w28"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO timeline_events (event_id, entity_id, occurred_at, time_granularity, summary, event_type, attribution, document_id) VALUES (?,?,?,?,?,?,?,?)",
        gmv_events,
    )

    # === GMV 决策 ===
    gmv_decisions = [
        ("dec_w12_1", "evt_gmv_w12",
         "临时调配渠道A预算15万补齐渠道B，加速渠道B预算审批",
         "增长运营组 张三", "SUCCESS",
         "渠道B于3/20恢复正常投放，3/22新客量回升至2800/日"),
        ("dec_w12_2", "evt_gmv_w12",
         "向近7日注册未下单用户推送5元无门槛优惠券",
         "用户运营组 李四", "FAILED",
         "核销率12%，带动增量GMV约8万，边际效应不明显"),
        ("dec_w28_1", "evt_gmv_w28",
         "检测到渠道B断档后立即启动渠道A补量20万预算（复用W12经验）",
         "增长运营组 王五", "SUCCESS",
         "新客量维持2800/日，比W12恢复速度快2天"),
        ("dec_w28_2", "evt_gmv_w28",
         "联合财务部推动渠道B预算从逐次审批改为月度预拨+季度复核",
         "增长运营组负责人 赵六", "PENDING",
         "7/10发起，财务侧预计8月落地"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO decisions (decision_id, event_id, action_taken, owner, outcome, outcome_detail) VALUES (?,?,?,?,?,?)",
        gmv_decisions,
    )

    # === 转化率 时间线 ===
    cvr_events = [
        ("evt_cvr_w12", "METRIC_CVR", "2026-03-22", "WEEK",
         "转化率环比下降0.3pp（3.1%→2.8%）", "FLUCTUATION",
         "疑似落地页加载速度问题，待进一步归因", "doc_2026_w12"),
        ("evt_cvr_w20", "METRIC_CVR", "2026-05-17", "WEEK",
         "转化率提升至3.3%（+0.3pp），落地页实验成功", "EXPERIMENT",
         "落地页A/B Test：简化首屏+单CTA，B组转化率3.3% vs A组2.8%，p<0.01显著", "doc_2026_w20"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO timeline_events (event_id, entity_id, occurred_at, time_granularity, summary, event_type, attribution, document_id) VALUES (?,?,?,?,?,?,?,?)",
        cvr_events,
    )
    conn.execute(
        "INSERT OR IGNORE INTO decisions (decision_id, event_id, action_taken, owner, outcome, outcome_detail) VALUES (?,?,?,?,?,?)",
        ("dec_cvr_w20", "evt_cvr_w20", "全量切换至落地页B方案（简化首屏+单CTA）", "产品组 陈七", "SUCCESS",
         "转化率提升18%，后续新落地页默认采用单CTA模板"),
    )

    # === CAC 时间线 ===
    conn.execute(
        "INSERT OR IGNORE INTO timeline_events (event_id, entity_id, occurred_at, time_granularity, summary, event_type, attribution, document_id) VALUES (?,?,?,?,?,?,?,?)",
        ("evt_cac_w12", "METRIC_CAC", "2026-03-22", "WEEK",
         "CAC环比上升18.7%（32→38元）", "FLUCTUATION",
         "渠道B预算断档后被迫加大渠道A投放，渠道A单价更高", "doc_2026_w12"),
    )

    # === 渠道B 时间线 ===
    conn.execute(
        "INSERT OR IGNORE INTO timeline_events (event_id, entity_id, occurred_at, time_granularity, summary, event_type, attribution, document_id) VALUES (?,?,?,?,?,?,?,?)",
        ("evt_chb_w28", "OBJECT_CHANNEL_B", "2026-07-12", "WEEK",
         "渠道B预算审批问题第三次出现，确认为系统性风险", "FLUCTUATION",
         "W12/W28两次断档均为审批流程问题，非偶发。月度预拨方案PENDING", "doc_2026_w28"),
    )

    # === Evidence Links (GMV) ===
    gmv_evidence = [
        ("METRIC_GMV", "doc_2026_w12", "2026年第12周 增长团队复盘周报", "/samples/week12_growth_review.md", 5.0, "FIRST_MENTION"),
        ("METRIC_GMV", "doc_2026_w28", "2026年第28周 增长团队复盘周报", "/samples/week28_growth_review.md", 5.0, "FINAL_RESOLUTION"),
        ("METRIC_GMV", "doc_2026_w20", "2026年第20周 增长团队复盘周报", "/samples/week20_growth_review.md", 3.0, "HIGH_SIMILARITY"),
    ]
    conn.executemany(
        "INSERT INTO evidence_links (entity_id, document_id, doc_title, doc_url, importance_score, reason_code) VALUES (?,?,?,?,?,?)",
        gmv_evidence,
    )

    # === Evidence Links (转化率) ===
    conn.executemany(
        "INSERT INTO evidence_links (entity_id, document_id, doc_title, doc_url, importance_score, reason_code) VALUES (?,?,?,?,?,?)",
        [
            ("METRIC_CVR", "doc_2026_w20", "2026年第20周 增长团队复盘周报", "/samples/week20_growth_review.md", 5.0, "FINAL_RESOLUTION"),
            ("METRIC_CVR", "doc_2026_w12", "2026年第12周 增长团队复盘周报", "/samples/week12_growth_review.md", 4.0, "FIRST_MENTION"),
        ],
    )

    conn.commit()
    conn.close()
    print("✅ 种子数据灌入完成：GMV 3事件4决策 / 转化率 2事件1决策 / CAC 1事件 / 渠道B 1事件 / 证据链 5条")


if __name__ == "__main__":
    seed()
