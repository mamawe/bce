// BCE Context Panel — rendered inside a Shadow DOM for full style isolation.
// Exposes window.__BCE_PANEL__ used by content.js.
(function () {
  "use strict";

  // ---- Theme tokens (CSS custom properties) ----
  const COLORS = {
    FLUCTUATION: "#f59e0b",
    DECISION: "#2563eb",
    EXPERIMENT: "#8b5cf6",
    LAUNCH: "#16a34a",
    SUCCESS: "#16a34a",
    FAILED: "#dc2626",
    PENDING: "#f59e0b",
    INCONCLUSIVE: "#6b7280",
  };

  const EVENT_TYPE_LABEL = {
    FLUCTUATION: "波动",
    DECISION: "决策",
    EXPERIMENT: "实验",
    LAUNCH: "上线",
  };

  const OUTCOME_LABEL = {
    SUCCESS: "成功",
    FAILED: "失败",
    PENDING: "进行中",
    INCONCLUSIVE: "无定论",
  };

  const REASON_LABEL = {
    FIRST_MENTION: "首次提出",
    FINAL_RESOLUTION: "最终闭环",
    FAILED_CASE: "失败案例",
    HIGH_SIMILARITY: "高度相似",
    REGULAR: "普通提及",
  };

  const CATEGORY_LABEL = {
    METRIC: "指标",
    OBJECT: "对象",
    EVENT: "事件",
    DECISION: "决策",
    EXPERIMENT: "实验",
    OWNER: "责任人",
  };

  // ---- Helpers ----
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function stars(score) {
    const full = Math.round(Math.max(0, Math.min(5, Number(score) || 0)));
    return "★".repeat(full) + "☆".repeat(5 - full);
  }

  // ---- Styles (scoped to shadow root) ----
  const PANEL_CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .bce-root {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.55;
      color: #1f2937;
      --bce-primary: #2563eb;
      --bce-border: #e5e7eb;
      --bce-muted: #6b7280;
      --bce-bg: #ffffff;
      --bce-bg-soft: #f9fafb;
    }

    /* ===== Side Panel ===== */
    .bce-panel {
      position: fixed;
      top: 10px;
      right: 10px;
      bottom: 10px;
      width: 380px;
      max-width: calc(100vw - 20px);
      background: var(--bce-bg);
      border-left: 3px solid var(--bce-primary);
      border-radius: 8px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.08);
      z-index: 2147483647;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transform: translateX(110%);
      transition: transform 0.2s ease;
    }
    .bce-panel.bce-open { transform: translateX(0); }

    .bce-header {
      padding: 14px 16px 10px;
      border-bottom: 1px solid var(--bce-border);
      flex: 0 0 auto;
    }
    .bce-header-top { display: flex; align-items: flex-start; gap: 8px; }
    .bce-title-wrap { flex: 1; min-width: 0; }
    .bce-title {
      font-size: 17px; font-weight: 700; color: #111827;
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    }
    .bce-category {
      font-size: 11px; font-weight: 600; color: var(--bce-primary);
      background: rgba(37,99,235,0.1); padding: 1px 7px; border-radius: 10px;
      white-space: nowrap;
    }
    .bce-desc { font-size: 12px; color: var(--bce-muted); margin-top: 3px; }
    .bce-close {
      border: none; background: transparent; cursor: pointer;
      font-size: 20px; line-height: 1; color: var(--bce-muted);
      padding: 2px 6px; border-radius: 6px; flex: 0 0 auto;
    }
    .bce-close:hover { background: var(--bce-bg-soft); color: #111827; }

    .bce-demo-badge {
      display: inline-block; font-size: 10px; font-weight: 700;
      color: #b45309; background: #fef3c7; border: 1px solid #fde68a;
      padding: 1px 6px; border-radius: 8px; margin-left: 2px;
    }

    /* ===== Summary Card (约束路径·首屏) ===== */
    .bce-summary { flex: 0 0 auto; }
    .bce-summary:empty { display: none; }
    .bce-summary-card {
      margin: 10px 12px 0; padding: 10px 12px;
      background: #eff4ff; border: 1px solid rgba(37,99,235,0.12);
      border-radius: 8px; font-size: 12.5px; line-height: 1.45;
    }
    .bce-summary-label {
      font-size: 10.5px; font-weight: 700; color: var(--bce-primary);
      text-transform: uppercase; letter-spacing: 0.3px; margin-bottom: 5px;
    }
    .bce-summary-what { font-size: 13px; font-weight: 600; color: #1f2937; margin-bottom: 6px; }
    .bce-summary-row { display: flex; gap: 6px; margin-bottom: 4px; }
    .bce-summary-key { flex: 0 0 26px; color: var(--bce-muted); font-weight: 500; }
    .bce-summary-val { flex: 1; color: #4b5563; }
    .bce-summary-decision { margin-top: 5px; padding-top: 5px; border-top: 1px dashed rgba(37,99,235,0.15); }
    .bce-summary-outcome { display: flex; align-items: flex-start; gap: 5px; margin-top: 3px; padding-left: 32px; }
    .bce-summary-outcome-detail { font-size: 11.5px; color: #4b5563; }
    .bce-summary-source {
      display: flex; align-items: center; gap: 4px; margin-top: 6px;
      padding-top: 5px; border-top: 1px solid rgba(37,99,235,0.08);
      font-size: 11px; color: var(--bce-muted);
    }
    .bce-summary-source-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bce-summary-more { margin-top: 5px; font-size: 10.5px; color: var(--bce-muted); }

    /* ===== Tabs ===== */
    .bce-tabs {
      display: flex; border-bottom: 1px solid var(--bce-border);
      flex: 0 0 auto; padding: 0 8px; margin-top: 10px;
    }
    .bce-tab {
      flex: 1; text-align: center; padding: 10px 4px; cursor: pointer;
      font-size: 13px; font-weight: 600; color: var(--bce-muted);
      border: none; background: transparent; position: relative;
      transition: color 0.15s ease;
    }
    .bce-tab:hover { color: #374151; }
    .bce-tab.bce-active { color: var(--bce-primary); }
    .bce-tab.bce-active::after {
      content: ""; position: absolute; left: 16px; right: 16px; bottom: -1px;
      height: 2px; background: var(--bce-primary); border-radius: 2px;
    }

    /* ===== Content ===== */
    .bce-content { flex: 1; overflow-y: auto; padding: 14px 16px 20px; }
    .bce-empty { color: var(--bce-muted); text-align: center; padding: 30px 0; font-size: 13px; }

    /* Timeline */
    .bce-timeline { position: relative; padding-left: 20px; }
    .bce-timeline::before {
      content: ""; position: absolute; left: 5px; top: 4px; bottom: 4px;
      width: 2px; background: var(--bce-border);
    }
    .bce-event { position: relative; margin-bottom: 16px; }
    .bce-dot {
      position: absolute; left: -20px; top: 4px; width: 12px; height: 12px;
      border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px var(--bce-border);
    }
    .bce-event-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .bce-event-date { font-size: 11px; color: var(--bce-muted); font-variant-numeric: tabular-nums; }
    .bce-event-type {
      font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 8px; color: #fff;
    }
    .bce-event-summary { font-size: 13px; font-weight: 600; color: #111827; margin: 3px 0; }
    .bce-toggle {
      border: none; background: transparent; color: var(--bce-primary);
      font-size: 12px; cursor: pointer; padding: 0; font-weight: 600;
    }
    .bce-detail {
      margin-top: 6px; padding: 8px 10px; background: var(--bce-bg-soft);
      border-radius: 6px; font-size: 12px; display: none;
    }
    .bce-detail.bce-show { display: block; }
    .bce-detail-row { margin-bottom: 5px; }
    .bce-detail-row:last-child { margin-bottom: 0; }
    .bce-k { color: var(--bce-muted); font-weight: 600; }

    /* Decision cards */
    .bce-card {
      border: 1px solid var(--bce-border); border-radius: 8px;
      padding: 11px 12px; margin-bottom: 10px; background: var(--bce-bg);
    }
    .bce-card-action { font-size: 13px; font-weight: 600; color: #111827; margin-bottom: 6px; }
    .bce-card-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
    .bce-owner { color: var(--bce-muted); }
    .bce-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; color: #fff; }
    .bce-card-detail { font-size: 12px; color: #374151; margin-top: 7px; padding-top: 7px; border-top: 1px dashed var(--bce-border); }

    /* Evidence */
    .bce-ev {
      display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--bce-border);
      align-items: flex-start;
    }
    .bce-ev:last-child { border-bottom: none; }
    .bce-ev-stars { color: #f59e0b; font-size: 12px; letter-spacing: 1px; white-space: nowrap; line-height: 1.7; }
    .bce-ev-body { flex: 1; min-width: 0; }
    .bce-ev-title { font-size: 13px; font-weight: 600; color: #111827; }
    .bce-ev-title a { color: inherit; text-decoration: none; }
    .bce-ev-title a:hover { color: var(--bce-primary); text-decoration: underline; }
    .bce-reason {
      display: inline-block; font-size: 10px; font-weight: 700; margin-top: 4px;
      padding: 1px 7px; border-radius: 8px; background: rgba(37,99,235,0.1); color: var(--bce-primary);
    }

    /* Insight */
    .bce-insight-block { border-radius: 8px; padding: 11px 12px; margin-bottom: 10px; }
    .bce-insight-title { font-size: 12px; font-weight: 700; margin-bottom: 5px; display: flex; align-items: center; gap: 6px; }
    .bce-insight-text { font-size: 13px; color: #1f2937; }
    .bce-i-pattern { background: #eff6ff; }
    .bce-i-pattern .bce-insight-title { color: #1d4ed8; }
    .bce-i-risk { background: #fef2f2; }
    .bce-i-risk .bce-insight-title { color: #b91c1c; }
    .bce-i-suggestion { background: #f0fdf4; }
    .bce-i-suggestion .bce-insight-title { color: #15803d; }
    .bce-disclaimer { font-size: 11px; color: var(--bce-muted); text-align: center; margin-top: 12px; }

    /* Skeleton */
    .bce-skel { margin-bottom: 14px; }
    .bce-skel-line {
      height: 12px; border-radius: 6px; margin-bottom: 8px;
      background: linear-gradient(90deg, #eef0f3 25%, #e2e6eb 37%, #eef0f3 63%);
      background-size: 400% 100%; animation: bce-shimmer 1.4s ease infinite;
    }
    @keyframes bce-shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }

    /* Error */
    .bce-error {
      text-align: center; padding: 30px 16px; color: var(--bce-muted); font-size: 13px;
    }
    .bce-error-icon { font-size: 30px; margin-bottom: 8px; }
    .bce-retry {
      margin-top: 12px; border: 1px solid var(--bce-border); background: var(--bce-bg);
      color: var(--bce-primary); font-weight: 600; padding: 6px 16px; border-radius: 6px; cursor: pointer;
    }
    .bce-retry:hover { background: var(--bce-bg-soft); }

    /* ===== Mini Context Card ===== */
    .bce-mini {
      position: fixed; z-index: 2147483647; width: 280px;
      background: var(--bce-bg); border: 1px solid var(--bce-border);
      border-left: 3px solid var(--bce-primary); border-radius: 8px;
      box-shadow: 0 8px 28px rgba(0,0,0,0.16); padding: 11px 13px;
      opacity: 0; transform: translateY(4px); transition: opacity 0.15s ease, transform 0.15s ease;
      pointer-events: none;
    }
    .bce-mini.bce-show { opacity: 1; transform: translateY(0); pointer-events: auto; }
    .bce-mini-title { font-size: 14px; font-weight: 700; color: #111827; display: flex; align-items: center; gap: 6px; }
    .bce-mini-desc { font-size: 12px; color: var(--bce-muted); margin: 3px 0 8px; }
    .bce-mini-stat { font-size: 12px; color: #374151; margin-bottom: 3px; }
    .bce-mini-stat b { color: var(--bce-primary); }
    .bce-mini-hint { font-size: 11px; color: var(--bce-muted); margin-top: 8px; padding-top: 7px; border-top: 1px dashed var(--bce-border); }
  `;

  // ---- State ----
  let host = null;       // <div> appended to body
  let shadow = null;     // shadow root
  let panelEl = null;
  let miniEl = null;
  let currentData = null;
  let currentDemo = false;
  let activeTab = "history";
  let onRetry = null;
  let miniHoverCb = null;

  function ensureDom() {
    if (shadow) return;
    host = document.createElement("div");
    host.id = "bce-shadow-host";
    // host itself must not affect layout
    host.style.cssText = "all:initial;position:absolute;width:0;height:0;";
    shadow = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = PANEL_CSS;
    shadow.appendChild(style);

    const root = document.createElement("div");
    root.className = "bce-root";
    root.innerHTML = `
      <div class="bce-panel" role="dialog" aria-label="BCE 上下文面板">
        <div class="bce-header">
          <div class="bce-header-top">
            <div class="bce-title-wrap">
              <div class="bce-title"><span class="bce-title-text"></span><span class="bce-category"></span><span class="bce-demo-slot"></span></div>
              <div class="bce-desc"></div>
            </div>
            <button class="bce-close" title="关闭">×</button>
          </div>
        </div>
        <div class="bce-summary"></div>
        <div class="bce-tabs">
          <button class="bce-tab" data-tab="history">历史</button>
          <button class="bce-tab" data-tab="decision">决策</button>
          <button class="bce-tab" data-tab="evidence">证据</button>
          <button class="bce-tab" data-tab="insight">洞察</button>
        </div>
        <div class="bce-content"></div>
      </div>
      <div class="bce-mini"></div>
    `;
    shadow.appendChild(root);

    panelEl = shadow.querySelector(".bce-panel");
    miniEl = shadow.querySelector(".bce-mini");

    shadow.querySelector(".bce-close").addEventListener("click", () => api.close());
    shadow.querySelectorAll(".bce-tab").forEach((t) => {
      t.addEventListener("click", () => {
        activeTab = t.getAttribute("data-tab");
        renderActiveTab();
      });
    });
    // Keep the mini card alive while the pointer moves onto it.
    miniEl.addEventListener("mouseenter", () => { if (miniHoverCb) miniHoverCb(true); });
    miniEl.addEventListener("mouseleave", () => { if (miniHoverCb) miniHoverCb(false); });
    // Prevent panel interactions from bubbling into the host page.
    panelEl.addEventListener("click", (e) => e.stopPropagation());
  }

  function setTabs() {
    shadow.querySelectorAll(".bce-tab").forEach((t) => {
      t.classList.toggle("bce-active", t.getAttribute("data-tab") === activeTab);
    });
  }

  function contentEl() {
    return shadow.querySelector(".bce-content");
  }

  // ---- Tab renderers ----
  function renderHistory(timeline) {
    if (!timeline || !timeline.length) return `<div class="bce-empty">暂无历史事件</div>`;
    const sorted = [...timeline].sort((a, b) => (a.occurred_at || "").localeCompare(b.occurred_at || ""));
    const items = sorted.map((ev) => {
      const color = COLORS[ev.event_type] || "#6b7280";
      const typeLabel = EVENT_TYPE_LABEL[ev.event_type] || ev.event_type || "事件";
      const d = ev.decision || {};
      const hasDetail = ev.attribution || d.action;
      const detailHtml = hasDetail ? `
        <div class="bce-detail">
          ${ev.attribution ? `<div class="bce-detail-row"><span class="bce-k">归因：</span>${esc(ev.attribution)}</div>` : ""}
          ${d.action ? `<div class="bce-detail-row"><span class="bce-k">决策：</span>${esc(d.action)}</div>` : ""}
          ${d.owner ? `<div class="bce-detail-row"><span class="bce-k">责任人：</span>${esc(d.owner)}</div>` : ""}
          ${d.outcome_detail ? `<div class="bce-detail-row"><span class="bce-k">结果：</span>${esc(d.outcome_detail)}</div>` : ""}
        </div>` : "";
      return `
        <div class="bce-event">
          <span class="bce-dot" style="background:${color}"></span>
          <div class="bce-event-head">
            <span class="bce-event-date">${esc(ev.occurred_at)}</span>
            <span class="bce-event-type" style="background:${color}">${esc(typeLabel)}</span>
          </div>
          <div class="bce-event-summary">${esc(ev.summary)}</div>
          ${hasDetail ? `<button class="bce-toggle">展开详情 ▾</button>` : ""}
          ${detailHtml}
        </div>`;
    }).join("");
    return `<div class="bce-timeline">${items}</div>`;
  }

  function renderDecisions(timeline) {
    const decisions = (timeline || [])
      .filter((ev) => ev.decision && ev.decision.action)
      .map((ev) => ({ date: ev.occurred_at, d: ev.decision }));
    if (!decisions.length) return `<div class="bce-empty">暂无决策记录</div>`;
    return decisions.map(({ date, d }) => {
      const color = COLORS[d.outcome] || "#6b7280";
      const label = OUTCOME_LABEL[d.outcome] || d.outcome || "未知";
      return `
        <div class="bce-card">
          <div class="bce-card-action">${esc(d.action)}</div>
          <div class="bce-card-meta">
            ${d.owner ? `<span class="bce-owner">👤 ${esc(d.owner)}</span>` : ""}
            ${date ? `<span class="bce-owner">${esc(date)}</span>` : ""}
            <span class="bce-badge" style="background:${color}">${esc(label)}</span>
          </div>
          ${d.outcome_detail ? `<div class="bce-card-detail">${esc(d.outcome_detail)}</div>` : ""}
        </div>`;
    }).join("");
  }

  function renderEvidence(evidence) {
    if (!evidence || !evidence.length) return `<div class="bce-empty">暂无证据来源</div>`;
    const sorted = evidence.slice().sort((a, b) => (b.importance_score || 0) - (a.importance_score || 0));
    return sorted.map((e) => {
      const reason = REASON_LABEL[e.reason_code] || e.reason_code || "";
      const url = e.doc_url && e.doc_url !== "#" ? e.doc_url : null;
      const title = url
        ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(e.doc_title)}</a>`
        : esc(e.doc_title);
      return `
        <div class="bce-ev">
          <div class="bce-ev-stars">${stars(e.importance_score)}</div>
          <div class="bce-ev-body">
            <div class="bce-ev-title">${title}</div>
            ${reason ? `<span class="bce-reason">${esc(reason)}</span>` : ""}
          </div>
        </div>`;
    }).join("");
  }

  function renderInsight(insight) {
    if (!insight) return `<div class="bce-empty">暂无洞察</div>`;
    return `
      <div class="bce-insight-block bce-i-pattern">
        <div class="bce-insight-title">📈 规律</div>
        <div class="bce-insight-text">${esc(insight.pattern) || "—"}</div>
      </div>
      <div class="bce-insight-block bce-i-risk">
        <div class="bce-insight-title">⚠️ 风险</div>
        <div class="bce-insight-text">${esc(insight.risk) || "—"}</div>
      </div>
      <div class="bce-insight-block bce-i-suggestion">
        <div class="bce-insight-title">💡 建议</div>
        <div class="bce-insight-text">${esc(insight.suggestion) || "—"}</div>
      </div>
      <div class="bce-disclaimer">AI 生成，仅供参考</div>
    `;
  }

  function renderActiveTab() {
    if (!currentData) return;
    setTabs();
    const c = contentEl();
    switch (activeTab) {
      case "history": c.innerHTML = renderHistory(currentData.timeline); break;
      case "decision": c.innerHTML = renderDecisions(currentData.timeline); break;
      case "evidence": c.innerHTML = renderEvidence(currentData.evidence); break;
      case "insight": c.innerHTML = renderInsight(currentData.insight); break;
    }
    bindToggles();
  }

  function bindToggles() {
    contentEl().querySelectorAll(".bce-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const detail = btn.parentElement.querySelector(".bce-detail");
        if (!detail) return;
        const open = detail.classList.toggle("bce-show");
        btn.textContent = open ? "收起详情 ▴" : "展开详情 ▾";
      });
    });
  }

  // ---- Summary Card (约束路径·首屏) ----
  function renderSummary(data) {
    const el = shadow.querySelector(".bce-summary");
    if (!data || !data.timeline || !data.timeline.length) { el.innerHTML = ""; return; }
    const sorted = [...data.timeline].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
    const latest = sorted[0];
    const d = latest.decision || {};
    const topEv = (data.evidence && data.evidence[0]) || null;
    const outcomeColor = COLORS[d.outcome] || "#6b7280";

    let html = `<div class="bce-summary-card">`;
    html += `<div class="bce-summary-label">最近动态 · ${esc(latest.occurred_at)}</div>`;
    html += `<div class="bce-summary-what">${esc(latest.summary)}</div>`;
    if (latest.attribution) {
      html += `<div class="bce-summary-row"><span class="bce-summary-key">归因</span><span class="bce-summary-val">${esc(latest.attribution)}</span></div>`;
    }
    if (d.action) {
      html += `<div class="bce-summary-decision">`;
      html += `<div class="bce-summary-row"><span class="bce-summary-key">决策</span><span class="bce-summary-val">${esc(d.action)}</span></div>`;
      html += `<div class="bce-summary-outcome">`;
      html += `<span class="bce-outcome" style="color:${outcomeColor};border-color:${outcomeColor}">${OUTCOME_LABEL[d.outcome] || d.outcome || ""}</span>`;
      if (d.outcome_detail) html += `<span class="bce-summary-outcome-detail">${esc(d.outcome_detail)}</span>`;
      html += `</div></div>`;
    }
    if (topEv) {
      html += `<div class="bce-summary-source">📄 <span class="bce-summary-source-title">${esc(topEv.doc_title)}</span></div>`;
    }
    if (sorted.length > 1) {
      html += `<div class="bce-summary-more">还有 ${sorted.length - 1} 条历史事件 · 见下方时间线</div>`;
    }
    html += `</div>`;
    el.innerHTML = html;
  }

  // ---- Public API ----
  const api = {
    init: ensureDom,

    setMiniHoverHandler(cb) {
      miniHoverCb = cb;
    },

    showLoading(entityName, isDemo) {
      ensureDom();
      currentData = null;
      currentDemo = !!isDemo;
      activeTab = "history";
      shadow.querySelector(".bce-title-text").textContent = entityName || "加载中";
      shadow.querySelector(".bce-category").textContent = "";
      shadow.querySelector(".bce-desc").textContent = "";
      shadow.querySelector(".bce-demo-slot").innerHTML =
        isDemo ? `<span class="bce-demo-badge">Demo Mode</span>` : "";
      shadow.querySelector(".bce-summary").innerHTML = "";
      setTabs();
      contentEl().innerHTML = `
        <div class="bce-skel">
          <div class="bce-skel-line" style="width:60%"></div>
          <div class="bce-skel-line" style="width:90%"></div>
          <div class="bce-skel-line" style="width:75%"></div>
          <div class="bce-skel-line" style="width:40%"></div>
        </div>`;
      panelEl.classList.add("bce-open");
    },

    render(data, isDemo) {
      ensureDom();
      currentData = data;
      currentDemo = !!isDemo;
      shadow.querySelector(".bce-title-text").textContent = data.entity_name || data.entity_id;
      const catEl = shadow.querySelector(".bce-category");
      catEl.textContent = CATEGORY_LABEL[data.category] || data.category || "";
      catEl.style.display = data.category ? "" : "none";
      shadow.querySelector(".bce-desc").textContent = data.description || "";
      shadow.querySelector(".bce-demo-slot").innerHTML =
        isDemo ? `<span class="bce-demo-badge">Demo Mode</span>` : "";
      renderSummary(data);
      renderActiveTab();
      panelEl.classList.add("bce-open");
    },

    showError(message, retryFn) {
      ensureDom();
      onRetry = retryFn || null;
      contentEl().innerHTML = `
        <div class="bce-error">
          <div class="bce-error-icon">🔌</div>
          <div>${esc(message || "无法连接到 BCE 服务")}</div>
          ${onRetry ? `<button class="bce-retry">重试</button>` : ""}
        </div>`;
      const btn = contentEl().querySelector(".bce-retry");
      if (btn && onRetry) btn.addEventListener("click", () => onRetry());
      panelEl.classList.add("bce-open");
    },

    close() {
      if (panelEl) panelEl.classList.remove("bce-open");
      api.hideMini();
    },

    isOpen() {
      return !!(panelEl && panelEl.classList.contains("bce-open"));
    },

    // ---- Mini card ----
    showMini(opts) {
      ensureDom();
      const { name, description, category, eventCount, evidenceCount, anchorRect } = opts;
      miniEl.innerHTML = `
        <div class="bce-mini-title">
          ${esc(name)}
          ${category ? `<span class="bce-category">${esc(CATEGORY_LABEL[category] || category)}</span>` : ""}
        </div>
        ${description ? `<div class="bce-mini-desc">${esc(description)}</div>` : ""}
        <div class="bce-mini-stat">📅 历史事件 <b>${eventCount != null ? eventCount : "—"}</b> 条</div>
        <div class="bce-mini-stat">📚 证据来源 <b>${evidenceCount != null ? evidenceCount : "—"}</b> 条</div>
        <div class="bce-mini-hint">点击实体查看完整上下文 →</div>
      `;
      // Position near the entity, keep within viewport.
      const w = 280;
      let left = anchorRect.left;
      let top = anchorRect.bottom + 8;
      if (left + w > window.innerWidth - 10) left = window.innerWidth - w - 10;
      if (left < 10) left = 10;
      if (top + 160 > window.innerHeight - 10) top = Math.max(10, anchorRect.top - 160);
      miniEl.style.left = left + "px";
      miniEl.style.top = top + "px";
      miniEl.classList.add("bce-show");
    },

    hideMini() {
      if (miniEl) miniEl.classList.remove("bce-show");
    },

    isMiniVisible() {
      return !!(miniEl && miniEl.classList.contains("bce-show"));
    },
  };

  window.__BCE_PANEL__ = api;
})();
