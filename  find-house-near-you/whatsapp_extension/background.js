// background.js
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type === "NEW_MESSAGE") {
    // Store in local storage
    chrome.storage.local.get({ messages: [] }, (data) => {
      const all = data.messages;
      all.push(msg.message);
      chrome.storage.local.set({ messages: all });
    });
  }
});
