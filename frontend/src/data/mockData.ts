// Hardcoded mock data matching the API contract.
// Used as a fallback when the backend (http://localhost:8000) is unavailable,
// so the demo works fully standalone. Content is derived from the sample
// weekly reports (W12 / W20 / W28).

import type { Entity, EntityContext } from '../types'

export const MOCK_ENTITIES: Entity[] = [
  {
    entity_id: 'METRIC_GMV',
    entity_name: 'GMV',
    category: 'METRIC',
    aliases: ['成交总额', '流水'],
    description: '成交总额',
  },
  {
    entity_id: 'METRIC_DAU',
    entity_name: 'DAU',
    category: 'METRIC',
    aliases: ['日活'],
    description: '日活跃用户数',
  },
  {
    entity_id: 'METRIC_CTR',
    entity_name: 'CTR',
    category: 'METRIC',
    aliases: ['点击率'],
    description: '广告点击率',
  },
  {
    entity_id: 'METRIC_CVR',
    entity_name: '转化率',
    category: 'METRIC',
    description: '下单转化率',
  },
  {
    entity_id: 'METRIC_CAC',
    entity_name: 'CAC',
    category: 'METRIC',
    aliases: ['获客成本'],
    description: '单客获取成本',
  },
  {
    entity_id: 'OBJ_CHANNEL_B',
    entity_name: '渠道B',
    category: 'OBJECT',
    aliases: ['渠道 B', '抖音信息流'],
    description: '抖音信息流投放渠道',
  },
  {
    entity_id: 'OBJ_CHANNEL_A',
    entity_name: '渠道A',
    category: 'OBJECT',
    aliases: ['渠道 A', '微信朋友圈'],
    description: '微信朋友圈投放渠道',
  },
  {
    entity_id: 'OBJ_LANDING',
    entity_name: '落地页',
    category: 'OBJECT',
    description: '广告投放落地页',
  },
  {
    entity_id: 'EXP_LP_ABTEST',
    entity_name: 'A/B Test',
    category: 'EXPERIMENT',
    aliases: ['A/B测试'],
    description: '落地页简化实验',
  },
  {
    entity_id: 'OWN_GROWTH',
    entity_name: '增长运营组',
    category: 'OWNER',
    description: '增长运营团队',
  },
  {
    entity_id: 'EVT_618',
    entity_name: '618',
    category: 'EVENT',
    description: '618 大促活动',
  },
]

export const MOCK_CONTEXTS: Record<string, EntityContext> = {
  METRIC_GMV: {
    entity_id: 'METRIC_GMV',
    entity_name: 'GMV',
    category: 'METRIC',
    description: '成交总额',
    timeline: [
      {
        event_id: 'evt_gmv_w12_drop',
        occurred_at: '2026-03-22',
        time_granularity: 'WEEK',
        summary: 'GMV 环比下降 12%（约 144 万），未达周目标',
        event_type: 'FLUCTUATION',
        attribution:
          '广告渠道 B 预算于 3/14 被财务审批流程卡住，投放预算骤减 40%，新客获取量从日均 3,200 降至 1,900，沿"曝光→注册→首单"链路传导至 GMV。',
        decision: {
          action: '从渠道 A 临时调配 15 万预算补齐渠道 B，同时加速渠道 B 预算审批',
          owner: '增长运营组 · 张三',
          outcome: 'SUCCESS',
          outcome_detail: '渠道 B 于 3/20 恢复正常投放，3/22 新客量回升至 2,800/日，W13 GMV 恢复正常水平。',
        },
      },
      {
        event_id: 'evt_gmv_w12_coupon',
        occurred_at: '2026-03-19',
        time_granularity: 'WEEK',
        summary: '发放 5 元无门槛优惠券刺激首单转化',
        event_type: 'DECISION',
        attribution: '新客断档期间，尝试用补贴直接拉动首单转化以对冲 GMV 下滑。',
        decision: {
          action: '向近 7 日注册未下单用户推送 5 元无门槛券',
          owner: '用户运营组 · 李四',
          outcome: 'INCONCLUSIVE',
          outcome_detail: '核销率 12%，带动增量 GMV 约 8 万，边际效应不明显，未能扭转大盘。',
        },
      },
      {
        event_id: 'evt_gmv_w20_high',
        occurred_at: '2026-05-17',
        time_granularity: 'WEEK',
        summary: 'GMV 环比增长 3.1%，创近 8 周新高',
        event_type: 'FLUCTUATION',
        attribution:
          '渠道 B 预算审批流程优化落地（周审批→双周审批）+ 落地页 A/B Test 全量切换 + 618 预热提前启动，三因素叠加。',
        decision: {
          action: '全量切换至落地页 B 方案（简化首屏 + 单 CTA）',
          owner: '产品组 · 陈七',
          outcome: 'SUCCESS',
          outcome_detail: '转化率从 2.8% 提升至 3.3%（+18%，p < 0.01），成为 GMV 回升的核心驱动之一。',
        },
      },
      {
        event_id: 'evt_gmv_w28_drop',
        occurred_at: '2026-07-12',
        time_granularity: 'WEEK',
        summary: 'GMV 环比下降 12.6%（约 170 万），与 W12 高度相似',
        event_type: 'FLUCTUATION',
        attribution:
          '渠道 B 7 月预算于 7/5 到期，新一期审批延迟至 7/8 通过，出现 3 天投放空窗，新客从日均 3,500 降至 2,100。属 W12 同一系统性问题复发。',
        decision: {
          action: '复用 W12 经验，检测到断档后立即启动渠道 A 补量 20 万预算',
          owner: '增长运营组 · 王五',
          outcome: 'SUCCESS',
          outcome_detail: '新客量维持在 2,800/日，比 W12 恢复速度快 2 天，缓解了部分影响。',
        },
      },
      {
        event_id: 'evt_gmv_w28_prepay',
        occurred_at: '2026-07-10',
        time_granularity: 'WEEK',
        summary: '推动渠道 B 预算审批改为"月度预拨 + 季度复核"',
        event_type: 'DECISION',
        attribution: '两次断档证明临时调配只能缓解，需流程级方案根治。',
        decision: {
          action: '联合财务部推动渠道 B 预算从"逐次审批"改为"月度预拨 + 季度复核"',
          owner: '增长运营组负责人 · 赵六',
          outcome: 'PENDING',
          outcome_detail: '7/10 发起，财务侧预计 8 月落地。',
        },
      },
    ],
    evidence: [
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 5.0,
        reason_code: 'FINAL_RESOLUTION',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 4.8,
        reason_code: 'HIGH_SIMILARITY',
      },
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 3.2,
        reason_code: 'REGULAR',
      },
      {
        doc_title: '增长团队 W11 日常数据监控简报',
        doc_url: '/samples/w11_monitor.md',
        importance_score: 2.5,
        reason_code: 'FIRST_MENTION',
      },
    ],
    insight: {
      pattern:
        'GMV 近半年出现 3 次显著波动，均与渠道 B 预算审批节奏强相关；临时调配渠道 A 可缓解，但无法根治。',
      risk: '渠道 B 预算月度预拨方案若 8 月仍未落地，Q3 大概率再次出现断档式下跌。',
      suggestion: '关注渠道 B 预算审批节点与月度预拨方案进展，提前 2 周预警；同步评估渠道 C 作为结构性对冲。',
    },
  },

  METRIC_CVR: {
    entity_id: 'METRIC_CVR',
    entity_name: '转化率',
    category: 'METRIC',
    description: '下单转化率',
    timeline: [
      {
        event_id: 'evt_cvr_w12_drop',
        occurred_at: '2026-03-22',
        time_granularity: 'WEEK',
        summary: '转化率环比下降 0.3pp（3.1% → 2.8%）',
        event_type: 'FLUCTUATION',
        attribution: '疑似落地页加载速度 / 信息过载问题，尚未完全归因。',
        decision: {
          action: '启动落地页 A/B Test，验证"简化首屏 + 强化 CTA"假设',
          owner: '产品组 · 陈七',
          outcome: 'SUCCESS',
          outcome_detail: 'W20 结果出炉：B 组转化率 3.3%，较 A 组提升 18%。',
        },
      },
      {
        event_id: 'evt_cvr_w20_abtest',
        occurred_at: '2026-05-17',
        time_granularity: 'WEEK',
        summary: '落地页 A/B Test 显著正向：B 组 3.3% vs A 组 2.8%',
        event_type: 'EXPERIMENT',
        attribution: '首屏信息过载是主因，简化首屏 + 单 CTA 有效降低决策成本。',
        decision: {
          action: '全量切换至 B 组方案，后续新落地页默认采用单 CTA 模板',
          owner: '产品组 · 陈七',
          outcome: 'SUCCESS',
          outcome_detail: '提升 18%（p < 0.01 显著），样本量 A/B 各 12,000 UV。',
        },
      },
      {
        event_id: 'evt_cvr_w28_drop',
        occurred_at: '2026-07-12',
        time_granularity: 'WEEK',
        summary: '转化率小幅回落 0.2pp（3.2% → 3.0%）',
        event_type: 'FLUCTUATION',
        attribution: '落地页红利衰减，计划启动新一轮 A/B Test。',
      },
    ],
    evidence: [
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 5.0,
        reason_code: 'FINAL_RESOLUTION',
      },
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 3.5,
        reason_code: 'FIRST_MENTION',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 3.0,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: '转化率对落地页形态高度敏感，简化首屏带来 18% 提升，但红利约 6-8 周后开始衰减。',
      risk: '落地页红利衰减若与渠道断档叠加，可能放大 GMV 波动幅度。',
      suggestion: '建立落地页定期迭代机制，每 6-8 周运行一次 A/B Test 以维持转化水位。',
    },
  },

  METRIC_CAC: {
    entity_id: 'METRIC_CAC',
    entity_name: 'CAC',
    category: 'METRIC',
    description: '单客获取成本',
    timeline: [
      {
        event_id: 'evt_cac_w12_up',
        occurred_at: '2026-03-22',
        time_granularity: 'WEEK',
        summary: 'CAC 环比上升 18.7%（32 → 38 元）',
        event_type: 'FLUCTUATION',
        attribution: '渠道 B 断档后由成本更高的渠道 A 补量，叠加 5 元优惠券补贴。',
        decision: {
          action: '临时调配渠道 A 预算补齐并加速渠道 B 审批',
          owner: '增长运营组 · 张三',
          outcome: 'SUCCESS',
          outcome_detail: '渠道 B 恢复投放后，W13 CAC 回落至正常区间。',
        },
      },
      {
        event_id: 'evt_cac_w28_up',
        occurred_at: '2026-07-12',
        time_granularity: 'WEEK',
        summary: 'CAC 环比上升 17.1%（35 → 41 元）',
        event_type: 'FLUCTUATION',
        attribution: '渠道 B 空窗期再次由渠道 A 补量，单次补量成本较 W12 上升。',
      },
    ],
    evidence: [
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 4.5,
        reason_code: 'FINAL_RESOLUTION',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 4.0,
        reason_code: 'HIGH_SIMILARITY',
      },
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 2.5,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: 'CAC 与渠道 B 投放连续性负相关：每次渠道 B 断档、渠道 A 补量都伴随 CAC 阶段性抬升。',
      risk: '若长期依赖渠道 A 补量，整体获客成本中枢可能结构性上移。',
      suggestion: '将 CAC 作为渠道 B 断档的伴随监控指标，并在预算配比评估中纳入成本维度。',
    },
  },

  OBJ_CHANNEL_B: {
    entity_id: 'OBJ_CHANNEL_B',
    entity_name: '渠道B',
    category: 'OBJECT',
    description: '抖音信息流投放渠道',
    timeline: [
      {
        event_id: 'evt_chb_w12_cut',
        occurred_at: '2026-03-14',
        time_granularity: 'DAY',
        summary: '渠道 B 预算被财务审批卡住，投放骤减 40%',
        event_type: 'FLUCTUATION',
        attribution: '预算采用逐次审批，3/14 未通过，导致新客获取量从日均 3,200 降至 1,900。',
        decision: {
          action: '从渠道 A 临时调配 15 万预算补齐，加速渠道 B 审批',
          owner: '增长运营组 · 张三',
          outcome: 'SUCCESS',
          outcome_detail: '3/20 恢复正常投放，3/22 新客回升至 2,800/日。',
        },
      },
      {
        event_id: 'evt_chb_w20_flow',
        occurred_at: '2026-05-17',
        time_granularity: 'WEEK',
        summary: '渠道 B 预算审批流程优化落地（周审批 → 双周审批）',
        event_type: 'LAUNCH',
        attribution: 'W12 复盘推动的流程级解决方案，投放连续性改善。',
        decision: {
          action: '推动预算审批流程从周审批改为双周审批',
          owner: '增长运营组',
          outcome: 'SUCCESS',
          outcome_detail: '投放连续性改善，W20 各指标全面回升。',
        },
      },
      {
        event_id: 'evt_chb_w28_gap',
        occurred_at: '2026-07-05',
        time_granularity: 'DAY',
        summary: '渠道 B 7 月预算审批延迟，出现 3 天投放空窗',
        event_type: 'FLUCTUATION',
        attribution: '预算到期与新一期审批衔接断档，新客从日均 3,500 降至 2,100。',
        decision: {
          action: '提前启动渠道 A 补量 20 万预算（复用 W12 经验）',
          owner: '增长运营组 · 王五',
          outcome: 'SUCCESS',
          outcome_detail: '新客维持 2,800/日，比 W12 恢复速度快 2 天。',
        },
      },
      {
        event_id: 'evt_chb_w28_prepay',
        occurred_at: '2026-07-10',
        time_granularity: 'WEEK',
        summary: '推动渠道 B 预算改为"月度预拨 + 季度复核"',
        event_type: 'DECISION',
        attribution: '两次断档证明需流程级根治方案。',
        decision: {
          action: '联合财务部推动月度预拨 + 季度复核',
          owner: '增长运营组负责人 · 赵六',
          outcome: 'PENDING',
          outcome_detail: '财务侧预计 8 月落地。',
        },
      },
    ],
    evidence: [
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 5.0,
        reason_code: 'FIRST_MENTION',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 5.0,
        reason_code: 'HIGH_SIMILARITY',
      },
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 4.0,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: '渠道 B 的两次断档（W12 / W28）根因一致：预算审批节奏与投放周期不匹配，属系统性流程问题。',
      risk: '月度预拨方案若 8 月无法落地，Q3 内大概率再次出现断档。',
      suggestion: '将渠道 B 预算审批节点纳入预警日历；同步开拓渠道 C 分散单渠道依赖风险。',
    },
  },

  OBJ_LANDING: {
    entity_id: 'OBJ_LANDING',
    entity_name: '落地页',
    category: 'OBJECT',
    description: '广告投放落地页',
    timeline: [
      {
        event_id: 'evt_lp_w20_abtest',
        occurred_at: '2026-05-17',
        time_granularity: 'WEEK',
        summary: '落地页 A/B Test 结果出炉，B 组转化率提升 18%',
        event_type: 'EXPERIMENT',
        attribution: '原版首屏信息过载，简化首屏 + 单 CTA 降低决策成本。',
        decision: {
          action: '全量切换至 B 组方案，新落地页默认采用单 CTA 模板',
          owner: '产品组 · 陈七',
          outcome: 'SUCCESS',
          outcome_detail: 'B 组 3.3% vs A 组 2.8%，p < 0.01 显著。',
        },
      },
      {
        event_id: 'evt_lp_w28_retest',
        occurred_at: '2026-07-12',
        time_granularity: 'WEEK',
        summary: '转化率回落，计划启动新一轮落地页 A/B Test',
        event_type: 'DECISION',
        attribution: '上一轮红利衰减，需持续迭代维持转化水位。',
        decision: {
          action: '启动新一轮落地页 A/B Test',
          owner: '产品组',
          outcome: 'PENDING',
          outcome_detail: 'W28 提出，尚未启动。',
        },
      },
    ],
    evidence: [
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 5.0,
        reason_code: 'FINAL_RESOLUTION',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 3.0,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: '落地页"少即是多"假设被验证：简化首屏 + 单 CTA 可显著提升转化。',
      risk: '单次优化红利会随时间衰减，缺乏持续迭代将导致转化回落。',
      suggestion: '沉淀单 CTA 模板为默认规范，并建立周期性 A/B Test 迭代节奏。',
    },
  },

  METRIC_CTR: {
    entity_id: 'METRIC_CTR',
    entity_name: 'CTR',
    category: 'METRIC',
    description: '广告点击率',
    timeline: [
      {
        event_id: 'evt_ctr_w12',
        occurred_at: '2026-03-22',
        time_granularity: 'WEEK',
        summary: 'CTR 微升 0.1pp（4.1% → 4.2%）',
        event_type: 'FLUCTUATION',
        attribution: '整体稳定，无显著干预动作。',
      },
      {
        event_id: 'evt_ctr_w28',
        occurred_at: '2026-07-12',
        time_granularity: 'WEEK',
        summary: 'CTR 微降 0.1pp（4.6% → 4.5%）',
        event_type: 'FLUCTUATION',
        attribution: '处于正常波动范围。',
      },
    ],
    evidence: [
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 2.5,
        reason_code: 'REGULAR',
      },
      {
        doc_title: '2026年第28周 增长团队复盘周报',
        doc_url: '/samples/week28_growth_review.md',
        importance_score: 2.5,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: 'CTR 长期稳定在 4.1%–4.6% 区间，波动幅度小，非近期 GMV 波动的主要驱动。',
      risk: '当前无显著风险。',
      suggestion: '维持常规监控即可，无需额外干预。',
    },
  },

  METRIC_DAU: {
    entity_id: 'METRIC_DAU',
    entity_name: 'DAU',
    category: 'METRIC',
    description: '日活跃用户数',
    timeline: [
      {
        event_id: 'evt_dau_w12',
        occurred_at: '2026-03-22',
        time_granularity: 'WEEK',
        summary: 'DAU 下降 3.3%（85,100 → 82,300）',
        event_type: 'FLUCTUATION',
        attribution: '受渠道 B 断档、新客减少拖累。',
      },
      {
        event_id: 'evt_dau_w20',
        occurred_at: '2026-05-17',
        time_granularity: 'WEEK',
        summary: 'DAU 增长 2.7%（86,400 → 88,700）',
        event_type: 'FLUCTUATION',
        attribution: '618 预热 + 落地页优化共同带动。',
      },
    ],
    evidence: [
      {
        doc_title: '2026年第12周 增长团队复盘周报',
        doc_url: '/samples/week12_growth_review.md',
        importance_score: 3.0,
        reason_code: 'REGULAR',
      },
      {
        doc_title: '2026年第20周 增长团队复盘周报',
        doc_url: '/samples/week20_growth_review.md',
        importance_score: 3.0,
        reason_code: 'REGULAR',
      },
    ],
    insight: {
      pattern: 'DAU 波动主要由新客获取量驱动，与渠道 B 投放连续性正相关。',
      risk: '渠道断档期间 DAU 增长承压。',
      suggestion: '将 DAU 作为渠道健康度的辅助观察指标。',
    },
  },
}

// Build a minimal placeholder context for any entity id not covered above
// (e.g. when the live backend returns entities the mock doesn't know about).
export function buildFallbackContext(entityId: string): EntityContext {
  const ent = MOCK_ENTITIES.find((e) => e.entity_id === entityId)
  return {
    entity_id: entityId,
    entity_name: ent?.entity_name ?? entityId,
    category: ent?.category ?? 'OBJECT',
    description: ent?.description,
    timeline: [],
    evidence: [],
    insight: {
      pattern: '暂无足够数据归纳规律。',
      risk: '暂无显著风险信号。',
      suggestion: '暂无建议，待更多文档接入后补充。',
    },
  }
}
