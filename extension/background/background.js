// BCE Background Service Worker
// Manages extension lifecycle, config (API base URL), and message passing.

const DEFAULT_CONFIG = {
  apiUrl: "http://localhost:8000",
  enabled: true,
  hoverTrigger: true, // true = hover trigger, false = click-only trigger
};

// Ensure defaults exist on install / update.
chrome.runtime.onInstalled.addListener((details) => {
  chrome.storage.local.get("bceConfig", (result) => {
    const current = result.bceConfig || {};
    const merged = Object.assign({}, DEFAULT_CONFIG, current);
    chrome.storage.local.set({ bceConfig: merged });
  });

  if (details.reason === "install") {
    // Seed entity cache so first page load is fast even before API responds.
    chrome.storage.local.set({
      bceEntityCache: {
        ts: 0,
        entities: null,
      },
    });
  }
});

// Central message router between content scripts and the popup.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return false;

  switch (msg.type) {
    case "GET_CONFIG": {
      chrome.storage.local.get("bceConfig", (result) => {
        sendResponse({ config: Object.assign({}, DEFAULT_CONFIG, result.bceConfig) });
      });
      return true; // async
    }

    default:
      return false;
  }
});
