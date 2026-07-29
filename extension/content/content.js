// BCE Content Script — entity detection, highlighting, and interaction.
// Design: "阅读伴随" (reading companion). Lazy, non-blocking, non-intrusive.
(function () {
  "use strict";

  // Guard against double injection.
  if (window.__BCE_CONTENT_LOADED__) return;
  window.__BCE_CONTENT_LOADED__ = true;

  const PANEL = window.__BCE_PANEL__;
  const MOCK = window.__BCE_MOCK__;
  const CACHE_TTL = 4 * 60 * 60 * 1000; // 4 hours

  // ---- Runtime state ----
  const config = { apiUrl: "http://localhost:8000", enabled: true, hoverTrigger: true };
  let termMap = new Map();   // term(lowercased) -> {entity_id, entity_name, category}
  let termRegex = null;      // global regex built from dictionary
  let dictReady = false;
  let started = false;

  const ctxCache = new Map(); // entity key -> {data, demo}
  let io = null;              // IntersectionObserver
  let mo = null;              // MutationObserver
  let moTimer = null;
  const pendingRoots = new Set();

  let hoverTimer = null;
  let hideTimer = null;
  let activeSpan = null;

  // Tags whose subtrees must never be scanned / highlighted.
  const SKIP_TAGS = new Set([
    "SCRIPT", "STYLE", "TEXTAREA", "INPUT", "CODE", "NOSCRIPT",
    "SVG", "IFRAME", "OBJECT", "EMBED", "VIDEO", "AUDIO", "CANVAS",
    "SELECT", "OPTION", "TEMPLATE",
  ]);

  // ---- Small utilities ----
  function fetchWithTimeout(url, options, ms) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms || 8000);
    return fetch(url, Object.assign({}, options, { signal: controller.signal }))
      .finally(() => clearTimeout(timer));
  }
  function storageGet(key) {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.get(key, (r) => resolve(r ? r[key] : undefined));
      } catch (e) { resolve(undefined); }
    });
  }
  function storageSet(key, val) {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.set({ [key]: val }, () => resolve());
      } catch (e) { resolve(); }
    });
  }
  function escRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function apiBase() {
    return (config.apiUrl || "http://localhost:8000").replace(/\/$/, "");
  }

  // ---- Highlight styles (injected into host page; minimal & non-intrusive) ----
  function injectHighlightStyles() {
    if (document.getElementById("bce-highlight-style")) return;
    const style = document.createElement("style");
    style.id = "bce-highlight-style";
    style.textContent =
      ".bce-entity{" +
      "background:rgba(37,99,235,0.08);" +
      "border-bottom:1px solid rgba(37,99,235,0.3);" +
      "cursor:pointer;" +
      "border-radius:2px;" +
      "padding:0 1px;" +
      "transition:background 0.15s ease;" +
      "}" +
      ".bce-entity:hover{background:rgba(37,99,235,0.16);}";
    (document.head || document.documentElement).appendChild(style);
  }

  // ---- Dictionary ----
  function buildDictionary(entities) {
    const map = new Map();
    const terms = [];
    function add(term, meta) {
      if (!term) return;
      const key = term.toLowerCase();
      if (!map.has(key)) {
        map.set(key, meta);
        terms.push(term);
      }
    }
    (entities || []).forEach((ent) => {
      const meta = {
        entity_id: ent.entity_id,
        entity_name: ent.entity_name,
        category: ent.category,
      };
      add(ent.entity_name, meta);
      (ent.aliases || []).forEach((a) => add(a, meta));
    });

    // Longest first so multi-char aliases win over substrings.
    terms.sort((a, b) => b.length - a.length);
    const parts = terms.map((t) => {
      const e = escRegExp(t);
      // Word boundaries for pure ASCII alnum terms (avoid matching inside words).
      if (/^[a-z0-9]+$/i.test(t)) return "(?<![A-Za-z0-9])" + e + "(?![A-Za-z0-9])";
      return e;
    });
    termMap = map;
    termRegex = parts.length ? new RegExp(parts.join("|"), "gi") : null;
    dictReady = parts.length > 0;
  }

  async function loadDictionary(force) {
    if (!force) {
      const cached = await storageGet("bceEntityCache");
      if (cached && cached.entities && cached.entities.length &&
          (Date.now() - (cached.ts || 0)) < CACHE_TTL) {
        buildDictionary(cached.entities);
        return;
      }
    }
    try {
      const resp = await fetchWithTimeout(apiBase() + "/api/v1/entities", { method: "GET" });
      if (!resp.ok) throw new Error("http " + resp.status);
      const json = await resp.json();
      const entities = (json && json.entities) || [];
      if (!entities.length) throw new Error("empty");
      await storageSet("bceEntityCache", { ts: Date.now(), entities });
      buildDictionary(entities);
    } catch (e) {
      buildDictionary(MOCK.FALLBACK_ENTITIES);
    }
  }

  // ---- Text node matching & wrapping ----
  function wrapMatchesInNode(node) {
    const text = node.nodeValue;
    if (!text || text.length <= 2 || text.length >= 5000) return;
    if (!termRegex) return;
    termRegex.lastIndex = 0;
    if (!termRegex.test(text)) return;
    termRegex.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let last = 0;
    let m;
    while ((m = termRegex.exec(text)) !== null) {
      const term = m[0];
      if (term.length === 0) { termRegex.lastIndex++; continue; }
      const start = m.index;
      if (start > last) frag.appendChild(document.createTextNode(text.slice(last, start)));

      const meta = termMap.get(term.toLowerCase());
      const span = document.createElement("span");
      span.className = "bce-entity";
      span.setAttribute("data-entity-id", meta ? meta.entity_id : term);
      span.setAttribute("data-entity-name", meta ? meta.entity_name : term);
      if (meta && meta.category) span.setAttribute("data-entity-category", meta.category);
      span.textContent = term;
      frag.appendChild(span);

      last = start + term.length;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    if (node.parentNode) node.parentNode.replaceChild(frag, node);
  }

  function processElement(el) {
    if (!el || el.nodeType !== 1) return;
    if (el.getAttribute("data-bce-processed") === "1") return;
    el.setAttribute("data-bce-processed", "1");
    // Only handle this element's DIRECT text nodes; nested elements are
    // observed/processed independently, which keeps work granular & lazy.
    const direct = [];
    for (let i = 0; i < el.childNodes.length; i++) {
      const c = el.childNodes[i];
      if (c.nodeType === 3) direct.push(c);
    }
    for (let i = 0; i < direct.length; i++) wrapMatchesInNode(direct[i]);
  }

  function isSkippable(el) {
    if (!el || el.nodeType !== 1) return true;
    if (SKIP_TAGS.has(el.tagName)) return true;
    if (el.classList && el.classList.contains("bce-entity")) return true;
    if (el.id === "bce-shadow-host") return true;
    // Avoid breaking active rich-text editing.
    if (el.isContentEditable) return true;
    return false;
  }

  // Does this element have a direct text node worth observing?
  function hasCandidateText(el) {
    for (let i = 0; i < el.childNodes.length; i++) {
      const c = el.childNodes[i];
      if (c.nodeType === 3) {
        const len = c.nodeValue ? c.nodeValue.length : 0;
        if (len > 2 && len < 5000) return true;
      }
    }
    return false;
  }

  // Walk `root`, observe (don't process) elements that contain candidate text.
  function collectAndObserve(root) {
    if (!config.enabled || !dictReady || !io) return;
    if (!root || root.nodeType !== 1) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
      acceptNode(node) {
        if (isSkippable(node)) return NodeFilter.FILTER_REJECT; // prune subtree
        if (node.getAttribute("data-bce-processed") === "1") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const batch = [];
    let cur = walker.nextNode();
    while (cur) {
      if (hasCandidateText(cur)) batch.push(cur);
      cur = walker.nextNode();
    }
    for (let i = 0; i < batch.length; i++) io.observe(batch[i]);
  }

  // ---- Observers ----
  function setupIntersectionObserver() {
    if (io) return;
    io = new IntersectionObserver((entries) => {
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        if (entry.isIntersecting) {
          io.unobserve(entry.target);
          processElement(entry.target);
        }
      }
    }, { rootMargin: "200px 0px", threshold: 0 });
  }

  function setupMutationObserver() {
    if (mo) return;
    mo = new MutationObserver((mutations) => {
      if (!config.enabled || !dictReady) return;
      for (let i = 0; i < mutations.length; i++) {
        const added = mutations[i].addedNodes;
        for (let j = 0; j < added.length; j++) {
          const n = added[j];
          if (n.nodeType === 1 && !isSkippable(n)) pendingRoots.add(n);
        }
      }
      if (pendingRoots.size) {
        clearTimeout(moTimer);
        moTimer = setTimeout(flushPending, 1000); // debounce 1s for SPAs
      }
    });
    mo.observe(document.body || document.documentElement, { childList: true, subtree: true });
  }

  function flushPending() {
    const roots = Array.from(pendingRoots);
    pendingRoots.clear();
    for (let i = 0; i < roots.length; i++) {
      if (roots[i].isConnected) collectAndObserve(roots[i]);
    }
  }

  // ---- Data fetching ----
  async function fetchContext(id, name) {
    const key = id || name;
    if (ctxCache.has(key)) return ctxCache.get(key);
    let result;
    try {
      const url = apiBase() + "/api/v1/context?entity_id=" + encodeURIComponent(key);
      const resp = await fetchWithTimeout(url, { method: "GET" });
      if (!resp.ok) throw new Error("http " + resp.status);
      const data = await resp.json();
      if (!data || !data.entity_id) throw new Error("bad payload");
      result = { data, demo: false };
    } catch (e) {
      // Fallback / Demo Mode.
      result = { data: MOCK.getMockContext(key, name), demo: true };
    }
    ctxCache.set(key, result);
    return result;
  }

  // ---- Interaction ----
  function metaFromSpan(span) {
    return {
      id: span.getAttribute("data-entity-id") || span.textContent,
      name: span.getAttribute("data-entity-name") || span.textContent,
      category: span.getAttribute("data-entity-category") || "",
    };
  }

  function showMiniFor(span) {
    const { id, name, category } = metaFromSpan(span);
    const rect = span.getBoundingClientRect();
    PANEL.showMini({ name, category, description: "", eventCount: null, evidenceCount: null, anchorRect: rect });
    fetchContext(id, name).then(({ data }) => {
      if (PANEL.isMiniVisible() && activeSpan === span) {
        PANEL.showMini({
          name,
          category: category || data.category,
          description: data.description || "",
          eventCount: (data.timeline || []).length,
          evidenceCount: (data.evidence || []).length,
          anchorRect: span.getBoundingClientRect(),
        });
      }
    }).catch(() => { /* silent: mini card just stays in initial state */ });
  }

  function openPanelFor(span) {
    const { id, name } = metaFromSpan(span);
    PANEL.hideMini();
    PANEL.showLoading(name, false);
    fetchContext(id, name)
      .then(({ data, demo }) => PANEL.render(data, demo))
      .catch(() => PANEL.showError("无法连接到 BCE 服务", () => openPanelFor(span)));
  }

  function getEntitySpan(target) {
    if (!target || !target.closest) return null;
    return target.closest(".bce-entity");
  }

  function onMouseOver(e) {
    if (!config.enabled || !config.hoverTrigger) return;
    const span = getEntitySpan(e.target);
    if (!span) return;
    activeSpan = span;
    clearTimeout(hideTimer);
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      if (activeSpan === span && !PANEL.isOpen()) showMiniFor(span);
    }, 300);
  }

  function onMouseOut(e) {
    const span = getEntitySpan(e.target);
    if (!span) return;
    clearTimeout(hoverTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      // Hide unless the pointer moved onto the mini card (handled via panel callback).
      PANEL.hideMini();
    }, 200);
  }

  function onClick(e) {
    if (!config.enabled) return;
    const span = getEntitySpan(e.target);
    if (!span) return;
    clearTimeout(hoverTimer);
    clearTimeout(hideTimer);
    openPanelFor(span);
  }

  function bindInteractions() {
    document.addEventListener("mouseover", onMouseOver, true);
    document.addEventListener("mouseout", onMouseOut, true);
    document.addEventListener("click", onClick, true);
    // Keep mini visible while the pointer is on it (shadow-DOM events retarget).
    if (PANEL.setMiniHoverHandler) {
      PANEL.setMiniHoverHandler((inside) => {
        if (inside) {
          clearTimeout(hideTimer);
        } else {
          clearTimeout(hideTimer);
          hideTimer = setTimeout(() => PANEL.hideMini(), 200);
        }
      });
    }
  }

  // ---- Enable / disable ----
  function removeAllHighlights() {
    const spans = document.querySelectorAll(".bce-entity");
    spans.forEach((s) => {
      const parent = s.parentNode;
      if (!parent) return;
      parent.replaceChild(document.createTextNode(s.textContent), s);
      parent.normalize();
    });
    document.querySelectorAll("[data-bce-processed]").forEach((el) => {
      el.removeAttribute("data-bce-processed");
    });
    PANEL.close();
  }

  function start() {
    if (started || !config.enabled || !dictReady) return;
    started = true;
    setupIntersectionObserver();
    collectAndObserve(document.body || document.documentElement);
    setupMutationObserver();
  }

  function stop() {
    started = false;
    if (mo) { mo.disconnect(); mo = null; }
    if (io) { io.disconnect(); io = null; }
    removeAllHighlights();
  }

  // ---- Config handling ----
  function applyConfig(cfg) {
    const wasEnabled = config.enabled;
    Object.assign(config, cfg || {});
    if (config.enabled && !wasEnabled) {
      // Re-enable: rebuild observers and rescan.
      if (dictReady) start();
    } else if (!config.enabled && wasEnabled) {
      stop();
    }
  }

  function loadConfig() {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: "GET_CONFIG" }, (resp) => {
          if (chrome.runtime.lastError) { resolve(); return; }
          if (resp && resp.config) applyConfig(resp.config);
          resolve();
        });
      } catch (e) { resolve(); }
    });
  }

  function watchConfigChanges() {
    try {
      chrome.storage.onChanged.addListener((changes, area) => {
        if (area === "local" && changes.bceConfig && changes.bceConfig.newValue) {
          applyConfig(changes.bceConfig.newValue);
        }
      });
    } catch (e) { /* ignore */ }
  }

  // ---- Boot ----
  async function boot() {
    injectHighlightStyles();
    if (PANEL.init) PANEL.init();
    bindInteractions();
    watchConfigChanges();
    await loadConfig();
    await loadDictionary(false);
    if (config.enabled) start();
    // Periodic dictionary refresh (every 4h), bypassing cache.
    setInterval(() => { loadDictionary(true); }, CACHE_TTL);
  }

  if (document.body) {
    boot();
  } else {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  }
})();
