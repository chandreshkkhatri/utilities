// popup.js
function renderMessages(list) {
  const container = document.getElementById("messages");
  container.innerHTML = "";
  list.forEach((m) => {
    const div = document.createElement("div");
    div.textContent = `${m.timestamp}: ${m.text}`;
    container.appendChild(div);
  });
}

function downloadJSON(list) {
  const blob = new Blob([JSON.stringify(list, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "whatsapp_messages.json";
  a.click();
  URL.revokeObjectURL(url);
}

// Load stored messages
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get({ messages: [] }, (data) => {
    renderMessages(data.messages);
    document
      .getElementById("download")
      .addEventListener("click", () => downloadJSON(data.messages));
  });
});
