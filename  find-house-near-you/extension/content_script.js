// Content script reserved for potential DOM-based enhancements.
// Currently unused for selection retrieval because contextMenus provides selectionText directly.
// We keep a simple hook for future use (e.g., scraping structured blocks).

(() => {
  // Example: expose current selection on demand
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "fhny:getSelection") {
      const sel = window.getSelection?.().toString() || "";
      sendResponse({ ok: true, selection: sel });
      return true;
    }
  });
})();
