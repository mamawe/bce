// BCE Mock Data — used when the backend is unreachable (Demo Mode).
// Shapes match the API contract in API_CONTRACT.md exactly.
(function () {
  "use strict";

  // Fallback entity list mirroring GET /entities response.
  const FALLBACK_ENTITIES = [
    { entity_id: "METRIC_GMV", entity_name: "GMV", category: "METRIC", aliases: ["成交总额", "流水"] },
    { entity_id: "METRIC_CTR", entity_name: "CTR", category: "METRIC", aliases: ["点击率"] },
    { entity_id: "METRIC_DAU", entity_name: "DAU", category: "METRIC", aliases: ["日活"] },
    { entity_id: "METRIC_CAC", entity_name: "CAC", category: "METRIC", aliases: ["获客成本"] },
    { entity_id: "METRIC_CVR", entity_name: "转化率", category: "METRIC", aliases: ["CVR"] },
    { entity_id: "METRIC_REFUND", entity_name: "退款率", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_RETENTION", entity_name: "留存率", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_ORDERS", entity_name: "订单量", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_AOV", entity_name: "客单价", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_REPURCHASE", entity_name: "复购率", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_GROSS_MARGIN", entity_name: "毛利率", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_NET_MARGIN", entity_name: "净利率", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_CATEGORY_WIDTH", entity_name: "品类宽度", category: "METRIC", aliases: [] },
    { entity_id: "METRIC_FULFILLMENT_COST", entity_name: "履约成本", category: "METRIC", aliases: [] },
  ];

  // Full context for GMV (Demo Mode), matching GET /context response.
  const MOCK_CONTEXT = {
    METRIC_GMV: {
      entity_id: "METRIC_GMV",
      entity_name: "GMV",
      category: "METRIC",
      description: "成交总额（Gross Merchandise Volume）",
      timeline: [
        {
          event_id: "evt_001",
          occurred_at: "2026-03-22",
          time_granularity: "WEEK",
          summary: "GMV 环比下降 12%（约 144 万）",
          event_type: "FLUCTUATION",
          attribution: "广告渠道 B（抖音信息流）预算于 3/14 被财务审批卡住，实际投放预算骤减 40%，新客获取量从日均 3,200 降至 1,900。",
          decision: {
            action: "从渠道 A 临时调配 15 万预算至渠道 B，同时加速渠道 B 预算审批",
            owner: "增长运营组 · 张三",
            outcome: "SUCCESS",
            outcome_detail: "渠道 B 于 3/20 恢复投放，3/22 新客量回升至 2,800/日，W13 GMV 恢复正常水平",
          },
        },
        {
          event_id: "evt_002",
          occurred_at: "2026-03-19",
          time_granularity: "WEEK",
          summary: "发放 5 元无门槛优惠券刺激转化",
          event_type: "DECISION",
          attribution: "为对冲 GMV 下降，向近 7 日注册未下单用户推送 5 元券",
          decision: {
            action: "向近 7 日注册未下单用户推送 5 元无门槛券",
            owner: "用户运营组 · 李四",
            outcome: "INCONCLUSIVE",
            outcome_detail: "核销率 12%，带动增量 GMV 约 8 万，边际效应不明显",
          },
        },
        {
          event_id: "evt_003",
          occurred_at: "2026-05-18",
          time_granularity: "WEEK",
          summary: "渠道 B 月审批试点上线，预算前置预案启动",
          event_type: "LAUNCH",
          attribution: "针对审批流程变更风险，提前 2 周锁定渠道 B 预算",
          decision: {
            action: "建立预算前置预警机制，月初前 2 周完成审批",
            owner: "增长运营组",
            outcome: "SUCCESS",
            outcome_detail: "W20 GMV 平稳，未出现断档",
          },
        },
      ],
      evidence: [
        {
          doc_title: "2026年第12周增长团队复盘周报",
          doc_url: "/samples/week12_growth_review.md",
          importance_score: 5.0,
          reason_code: "FINAL_RESOLUTION",
        },
        {
          doc_title: "2026年第20周增长团队复盘周报",
          doc_url: "/samples/week20_growth_review.md",
          importance_score: 4.0,
          reason_code: "FAILED_CASE",
        },
        {
          doc_title: "2026年第28周增长团队复盘周报",
          doc_url: "/samples/week28_growth_review.md",
          importance_score: 2.0,
          reason_code: "REGULAR",
        },
      ],
      insight: {
        pattern: "GMV 在近 6 个月内出现 3 次类似下降，均与渠道预算调整相关。",
        risk: "渠道 B 预算审批流程变更（周审批改月审批）可能导致每月月初再次出现断档。",
        suggestion: "关注渠道 B 预算审批节点，提前 2 周预警并锁定预算。",
      },
    },
  };

  // Generic stub context for any other entity in Demo Mode.
  function stubContext(entityId, entityName) {
    return {
      entity_id: entityId,
      entity_name: entityName || entityId,
      category: "METRIC",
      description: "演示模式下的示例实体",
      timeline: [
        {
          event_id: "evt_demo_1",
          occurred_at: "2026-05-01",
          time_granularity: "MONTH",
          summary: `${entityName || entityId} 出现一次波动`,
          event_type: "FLUCTUATION",
          attribution: "演示数据：归因链路示例。",
          decision: {
            action: "演示决策动作",
            owner: "演示责任人",
            outcome: "PENDING",
            outcome_detail: "结果待观察",
          },
        },
      ],
      evidence: [
        {
          doc_title: "示例文档",
          doc_url: "#",
          importance_score: 3.0,
          reason_code: "REGULAR",
        },
      ],
      insight: {
        pattern: "演示规律：暂无足够数据。",
        risk: "演示风险：暂无足够数据。",
        suggestion: "演示建议：连接 BCE 后端以获取真实上下文。",
      },
    };
  }

  window.__BCE_MOCK__ = {
    FALLBACK_ENTITIES: FALLBACK_ENTITIES,
    MOCK_CONTEXT: MOCK_CONTEXT,
    getMockContext: function (entityId, entityName) {
      return MOCK_CONTEXT[entityId] || stubContext(entityId, entityName);
    },
  };
})();
