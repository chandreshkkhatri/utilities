const KEY = "fhny_settings";

function getEl(id) {
  return document.getElementById(id);
}

function loadSettings() {
  chrome.storage.sync.get(KEY, (data) => {
    const s = data?.[KEY] || {};
    getEl("ai_baseUrl").value =
      s.openai?.baseUrl || "https://api.openai.com/v1";
    getEl("ai_key").value = s.openai?.apiKey || "";
    getEl("ai_model").value = s.openai?.model || "gpt-4o-mini";
    getEl("office_lat").value = s.office?.lat ?? "";
    getEl("office_lon").value = s.office?.lon ?? "";
    getEl("office_address").value = s.office?.address || "";
    getEl("compute_distance").checked = !!s.computeDistance;
    getEl("gmaps_key").value = s.googleMapsApiKey || "";
  });
}

function saveSettings() {
  const s = {
    aiProvider: "openai",
    openai: {
      baseUrl: getEl("ai_baseUrl").value.trim() || "https://api.openai.com/v1",
      apiKey: getEl("ai_key").value.trim(),
      model: getEl("ai_model").value.trim() || "gpt-4o-mini",
    },
    office: {
      lat: parseFloat(getEl("office_lat").value) || null,
      lon: parseFloat(getEl("office_lon").value) || null,
      address: getEl("office_address").value.trim(),
    },
    computeDistance: getEl("compute_distance").checked,
    googleMapsApiKey: getEl("gmaps_key").value.trim(),
  };
  chrome.storage.sync.set({ [KEY]: s }, () => {
    const st = document.getElementById("status");
    st.textContent = "Saved";
    setTimeout(() => (st.textContent = ""), 1200);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  document.getElementById("saveBtn").addEventListener("click", saveSettings);
});
