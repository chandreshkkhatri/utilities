const tableHeaders = [
  "date",
  "location",
  "city",
  "rent",
  "bhk",
  "additional_details",
  "latitude",
  "longitude",
  "distance_from_office_km",
  "driving_duration",
  "page_url",
  "source",
  "original_message",
];

function render(results) {
  const container = document.getElementById("results");
  if (!results.length) {
    container.innerHTML =
      '<p class="empty">No results yet. Select text on a page and choose "Extract rental details" or paste text above.</p>';
    return;
  }
  const thead =
    "<thead><tr>" +
    tableHeaders.map((h) => `<th>${h}</th>`).join("") +
    "</tr></thead>";
  const rows = results
    .map((r) => {
      const cells = tableHeaders
        .map((k) => {
          const v = r[k] == null ? "" : String(r[k]);
          return `<td>${escapeHtml(v)}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  container.innerHTML = `<table>${thead}<tbody>${rows}</tbody></table>`;
}

function escapeHtml(str) {
  return str.replace(
    /[&<>"]+/g,
    (s) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[s])
  );
}

function toCSV(results) {
  const header = tableHeaders.join(",");
  const lines = results.map((r) =>
    tableHeaders.map((k) => csvCell(r[k])).join(",")
  );
  return [header, ...lines].join("\n");
}

function csvCell(v) {
  if (v == null) return "";
  const s = String(v).replace(/"/g, '""');
  return '"' + s + '"';
}

function download(filename, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function loadResults() {
  const resp = await chrome.runtime.sendMessage({ type: "fhny:getResults" });
  return resp?.results || [];
}

async function clearResults() {
  await chrome.runtime.sendMessage({ type: "fhny:clearResults" });
}

async function parseText(text) {
  // For single paste, use batch to allow multiple posts separated by blank lines
  const resp = await chrome.runtime.sendMessage({
    type: "fhny:parseTextBatch",
    text,
  });
  return resp;
}

document.addEventListener("DOMContentLoaded", async () => {
  let results = await loadResults();
  render(results);

  const exportBtn = document.getElementById("exportCsvBtn");
  exportBtn.addEventListener("click", async () => {
    results = await loadResults();
    if (!results.length) return;
    download("house_listings.csv", toCSV(results));
  });

  const clearBtn = document.getElementById("clearBtn");
  clearBtn.addEventListener("click", async () => {
    await clearResults();
    results = [];
    render(results);
  });

  const parseBtn = document.getElementById("parseBtn");
  const pasteInput = document.getElementById("pasteInput");
  const status = document.getElementById("status");
  parseBtn.addEventListener("click", async () => {
    const text = pasteInput.value.trim();
    if (!text) return;
    status.textContent = "Parsing...";
    parseBtn.disabled = true;
    try {
      const resp = await parseText(text);
      if (!resp.ok) {
        status.textContent = "Parse failed";
      } else {
        const c = resp.count ?? 1;
        status.textContent = `Parsed ${c} post${c === 1 ? "" : "s"}.`;
      }
    } catch (e) {
      status.textContent = "Error";
    } finally {
      parseBtn.disabled = false;
      results = await loadResults();
      render(results);
      setTimeout(() => (status.textContent = ""), 1500);
    }
  });
});
