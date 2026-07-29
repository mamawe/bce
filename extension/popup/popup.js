// BCE Popup — quick settings + backend status.
(function () {
  "use strict";

  const DEFAULT_CONFIG = {
    apiUrl: "http://localhost:8000",
    enabled: true,
    hoverTrigger: true,
  };

  const el = {
    apiUrl: document.getElementById("apiUrl"),
    enabled: document.getElementById("enabled"),
    hoverTrigger: document.getElementById("hoverTrigger"),
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),
    recheck: document.getElementById("recheck"),
    savedTip: document.getElementById("savedTip"),
  };

  let saveTipTimer = null;

  function loadConfig() {
    return new Promise((resolve) => {
      chrome.storage.local.get("bceConfig", (r) => {
        resolve(Object.assign({}, DEFAULT_CONFIG, (r && r.bceConfig) || {}));
      });
    });
  }

  function saveConfig(patch) {
    return new Promise((resolve) => {
      chrome.storage.local.get("bceConfig", (r) => {
        const next = Object.assign({}, DEFAULT_CONFIG, (r && r.bceConfig) || {}, patch);
        chrome.storage.local.set({ bceConfig: next }, () => resolve(next));
      });
    });
  }

  function flashSaved() {
    el.savedTip.classList.add("show");
    clearTimeout(saveTipTimer);
    saveTipTimer = setTimeout(() => el.savedTip.classList.remove("show"), 1200);
  }

  function setStatus(state, text) {
    el.statusDot.className = "dot " + state;
    el.statusText.textContent = text;
  }

  function checkHealth(apiUrl) {
    setStatus("loading", "检测中…");
    const url = (apiUrl || DEFAULT_CONFIG.apiUrl).replace(/\/$/, "");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    fetch(url + "/api/v1/health", { method: "GET", signal: controller.signal })
      .then((r) => {
        if (r.ok) setStatus("ok", "已连接 · " + url);
        else setStatus("bad", "服务异常（HTTP " + r.status + "）");
      })
      .catch(() => setStatus("bad", "无法连接到 BCE 服务"))
      .finally(() => clearTimeout(timer));
  }

  async function init() {
    const cfg = await loadConfig();
    el.apiUrl.value = cfg.apiUrl;
    el.enabled.checked = !!cfg.enabled;
    el.hoverTrigger.checked = !!cfg.hoverTrigger;

    let urlTimer = null;
    el.apiUrl.addEventListener("input", () => {
      clearTimeout(urlTimer);
      urlTimer = setTimeout(async () => {
        const val = el.apiUrl.value.trim() || DEFAULT_CONFIG.apiUrl;
        await saveConfig({ apiUrl: val });
        flashSaved();
        checkHealth(val);
      }, 400);
    });

    el.enabled.addEventListener("change", async () => {
      await saveConfig({ enabled: el.enabled.checked });
      flashSaved();
    });

    el.hoverTrigger.addEventListener("change", async () => {
      await saveConfig({ hoverTrigger: el.hoverTrigger.checked });
      flashSaved();
    });

    el.recheck.addEventListener("click", () => {
      checkHealth(el.apiUrl.value.trim() || DEFAULT_CONFIG.apiUrl);
    });

    checkHealth(cfg.apiUrl);
  }

  init();
})();
