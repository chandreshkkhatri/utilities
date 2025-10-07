// Listen for incoming messages in the chat container
(function () {
  // The main panel containing all chats might not have a stable class,
  // but it's usually the main content area.
  const chatSelector = "div[role='application']";
  let lastProcessed = new Set();

  function extractMessages() {
    const container = document.querySelector(chatSelector);
    if (!container) {
      console.log("WhatsApp Extractor: Chat container not found.");
      return;
    }

    // Find all message elements. They have a 'data-pre-plain-text' attribute.
    const messages = container.querySelectorAll("div[data-pre-plain-text]");
    messages.forEach((elem) => {
      // The 'data-id' attribute seems to be a reliable unique identifier for a message.
      const parentMessageNode = elem.closest("div[data-id]");
      if (!parentMessageNode) return;

      const id = parentMessageNode.getAttribute("data-id");
      if (lastProcessed.has(id)) return;
      lastProcessed.add(id);

      const pre = elem.getAttribute("data-pre-plain-text");
      if (!pre) return;

      // Extract timestamp from the attribute, e.g., "[9:09 pm, 6/7/2025]..."
      const tsMatch = pre.match(/\[(.*?)\]/);
      const ts = tsMatch ? tsMatch[1] : "No timestamp";

      // The text is inside a child span with the 'selectable-text' class.
      const textSpan = elem.querySelector("span.selectable-text");
      const text = textSpan ? textSpan.innerText : "";

      if (text) {
        const message = { id, timestamp: ts, text };
        // Send to background script
        chrome.runtime.sendMessage({ type: "NEW_MESSAGE", message });
      }
    });
  }

  // Use a MutationObserver to detect when new messages are loaded.
  const observer = new MutationObserver((mutations) => {
    // A timeout helps batch processing and avoid running on every small DOM change.
    setTimeout(extractMessages, 500);
  });

  // Start observing once the main application container is available.
  const startObserving = () => {
    const app = document.querySelector(chatSelector);
    if (app) {
      observer.observe(app, { childList: true, subtree: true });
      extractMessages(); // Initial extraction
    } else {
      // If the app isn't ready, try again shortly.
      setTimeout(startObserving, 1000);
    }
  };

  // The script runs at 'document_idle', so the page should be mostly loaded.
  startObserving();
})();
