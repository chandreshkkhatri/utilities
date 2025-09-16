/*
  Background Service Worker (MV3)
  - Creates context menu for selected text
  - Receives selection from content script
  - Parses with AI (OpenAI-compatible) or regex fallback
  - Optionally computes distance via Google Maps if configured
  - Persists structured results to chrome.storage.local
*/

const STORAGE_KEYS = {
  SETTINGS: "fhny_settings", // sync
  RESULTS: "fhny_results", // local
};

// Default settings
const DEFAULT_SETTINGS = {
  aiProvider: "openai",
  openai: {
    baseUrl: "https://api.openai.com/v1",
    apiKey: "",
    model: "gpt-4o-mini",
  },
  // Optional Google Maps for distance calculations
  googleMapsApiKey: "",
  office: { lat: null, lon: null, address: "" },
  // Behavior toggles
  computeDistance: false,
};

// Context menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "fhny_extract_selection",
    title: "Extract rental details from selection",
    contexts: ["selection"],
  });
});

// Listen to context menu clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "fhny_extract_selection") return;
  const selectionText = info.selectionText || "";
  if (!selectionText.trim()) return;

  const settings = await getSettings();
  const parts = splitIntoPosts(selectionText);
  if (!parts.length) return;
  for (const part of parts) {
    await processOneText(part, settings, tab?.url || "", "selection");
  }
});

// Messaging API if needed by popup
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg?.type === "fhny:getResults") {
      const results = await getResults();
      sendResponse({ ok: true, results });
      return;
    }
    if (msg?.type === "fhny:clearResults") {
      await setResults([]);
      sendResponse({ ok: true });
      return;
    }
    if (msg?.type === "fhny:getSettings") {
      const settings = await getSettings();
      sendResponse({ ok: true, settings });
      return;
    }
    if (msg?.type === "fhny:parseText") {
      const selectionText = msg.text || "";
      const settings = await getSettings();
      const parsed = await parseText(selectionText, settings).catch((err) => ({
        error: String(err),
      }));
      if (parsed && !parsed.error) {
        let lat = parsed.latitude != null ? Number(parsed.latitude) : null;
        let lon = parsed.longitude != null ? Number(parsed.longitude) : null;
        if (
          (lat == null || lon == null) &&
          settings.googleMapsApiKey &&
          (parsed.location || parsed.city)
        ) {
          try {
            const geo = await geocodeAddress(
              settings.googleMapsApiKey,
              parsed.location,
              parsed.city
            );
            if (geo) {
              lat = geo.lat;
              lon = geo.lon;
            }
          } catch {}
        }
        let distanceKm = null,
          durationText = null;
        if (
          settings.computeDistance &&
          settings.googleMapsApiKey &&
          settings.office?.lat &&
          settings.office?.lon &&
          lat != null &&
          lon != null
        ) {
          try {
            const out = await distanceViaDirections(
              settings.googleMapsApiKey,
              { lat: settings.office.lat, lon: settings.office.lon },
              { lat, lon }
            );
            distanceKm = out.distanceKm;
            durationText = out.durationText;
          } catch {}
        }
        await addResult({
          message_id: genId(),
          date: new Date().toISOString(),
          location: parsed.location || null,
          city: parsed.city || null,
          rent: parsed.rent || null,
          bhk: parsed.bhk || null,
          additional_details: parsed.additional_details || null,
          latitude: lat,
          longitude: lon,
          distance_from_office_km: distanceKm,
          driving_duration: durationText,
          source: "popup",
          page_url: "",
          original_message: truncate(selectionText, 500),
        });
      }
      sendResponse({ ok: !!parsed && !parsed.error, parsed });
      return;
    }
    if (msg?.type === "fhny:parseTextBatch") {
      const selectionText = msg.text || "";
      const settings = await getSettings();
      const parts = splitIntoPosts(selectionText);
      let count = 0;
      for (const part of parts) {
        try {
          await processOneText(part, settings, "", "popup");
          count++;
        } catch {}
      }
      sendResponse({ ok: true, count });
      return;
    }
  })();
  return true; // async
});

// Helpers
function genId() {
  return "sel_" + Math.random().toString(36).slice(2, 10);
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(STORAGE_KEYS.SETTINGS, (data) => {
      resolve({
        ...DEFAULT_SETTINGS,
        ...(data?.[STORAGE_KEYS.SETTINGS] || {}),
      });
    });
  });
}

async function getResults() {
  return new Promise((resolve) => {
    chrome.storage.local.get(STORAGE_KEYS.RESULTS, (data) => {
      resolve(data?.[STORAGE_KEYS.RESULTS] || []);
    });
  });
}

async function setResults(results) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEYS.RESULTS]: results }, () =>
      resolve()
    );
  });
}

async function addResult(result) {
  const curr = await getResults();
  curr.unshift(result);
  await setResults(curr);
}

async function parseText(text, settings) {
  const clean = text.trim();
  if (!clean) throw new Error("Empty selection");
  // Prefer AI if key set
  const key = settings?.openai?.apiKey;
  if (key) {
    try {
      const out = await callOpenAI(settings, clean);
      if (out && out.location) return out;
    } catch (e) {
      console.warn("OpenAI parsing failed, falling back to regex", e);
    }
  }
  return regexExtract(clean);
}

function regexExtract(text) {
  // Naive regex-based extraction
  // rent: recognize like 25k, 25000, Rs 25,000, ₹30,000
  const rentMatch = text.match(
    /(?:rs\.?|₹|inr)?\s*([1-9]\d{3,6}|\d{1,2}\s?k)/i
  );
  let rent = null;
  if (rentMatch) {
    const raw = rentMatch[1].replace(/\s+/g, "").toLowerCase();
    rent = raw.endsWith("k")
      ? Number(raw.slice(0, -1)) * 1000
      : Number(raw.replace(/,/g, ""));
    if (Number.isNaN(rent)) rent = null;
  }

  const bhkMatch = text.match(/(\d+\s?-?\s?bhk|studio)/i);
  const bhk = bhkMatch ? bhkMatch[1].toUpperCase() : null;

  // crude location heuristic: phrases after 'at|in|near'
  const locMatch = text.match(
    /(?:at|in|near)\s+([A-Za-z0-9\-\s,()]+?)(?:\.|,|\n|$)/i
  );
  const location = locMatch ? locMatch[1].trim() : null;

  // City heuristic: common Indian metros
  const cities = [
    "Bengaluru",
    "Bangalore",
    "Hyderabad",
    "Chennai",
    "Delhi",
    "Gurgaon",
    "Gurugram",
    "Mumbai",
    "Pune",
    "Noida",
    "Kolkata",
  ];
  const city =
    cities.find((c) => new RegExp(`\\b${c}\\b`, "i").test(text)) || null;

  return {
    location,
    city,
    rent,
    bhk,
    additional_details: null,
  };
}

async function callOpenAI(settings, text) {
  const { openai } = settings;
  const body = {
    model: openai.model || "gpt-4o-mini",
    messages: [
      {
        role: "system",
        content:
          "You extract rental listing details from user-provided text. Respond ONLY with JSON per the provided schema. If a field is unknown, set it to null.",
      },
      {
        role: "user",
        content: `Extract the following fields from the text. Respond with a single JSON object with keys: location (string|null), city (string|null), rent (number|null), bhk (string|null), additional_details (string|null), latitude (number|null), longitude (number|null).\n\nText:\n${text}`,
      },
    ],
    temperature: 0.1,
    response_format: { type: "json_object" },
  };

  const resp = await fetch(
    `${openai.baseUrl.replace(/\/$/, "")}/chat/completions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${openai.apiKey}`,
      },
      body: JSON.stringify(body),
    }
  );
  if (!resp.ok) throw new Error(`OpenAI HTTP ${resp.status}`);
  const data = await resp.json();
  const content = data?.choices?.[0]?.message?.content;
  if (!content) throw new Error("No content from AI");
  return JSON.parse(content);
}

async function distanceViaDirections(apiKey, origin, dest) {
  const params = new URLSearchParams({
    origin: `${origin.lat},${origin.lon}`,
    destination: `${dest.lat},${dest.lon}`,
    key: apiKey,
  });
  const url = `https://maps.googleapis.com/maps/api/directions/json?${params.toString()}`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Directions HTTP ${resp.status}`);
  const data = await resp.json();
  const leg = data?.routes?.[0]?.legs?.[0];
  if (!leg) throw new Error("No routes");
  return {
    distanceKm: Math.round((leg.distance.value / 1000) * 100) / 100,
    durationText: leg.duration.text,
  };
}

async function geocodeAddress(apiKey, location, city) {
  const address = [location, city].filter(Boolean).join(", ");
  const params = new URLSearchParams({ address, key: apiKey });
  const url = `https://maps.googleapis.com/maps/api/geocode/json?${params.toString()}`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Geocode HTTP ${resp.status}`);
  const data = await resp.json();
  const res = data?.results?.[0];
  if (!res) return null;
  const loc = res.geometry?.location;
  if (!loc) return null;
  return { lat: loc.lat, lon: loc.lng };
}

function splitIntoPosts(text) {
  const norm = (text || "").replace(/\r\n/g, "\n").trim();
  if (!norm) return [];
  let parts = norm
    .split(/\n{2,}/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 15);
  if (parts.length <= 1) {
    parts = norm
      .split(/\n\s*[-=_]{3,}\s*\n/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 15);
  }
  // safety cap to avoid huge selections
  return parts.slice(0, 30);
}

async function processOneText(selectionText, settings, pageUrl, source) {
  const parsed = await parseText(selectionText, settings).catch((err) => ({
    error: String(err),
  }));
  if (!parsed || parsed.error) {
    await addResult({
      message_id: genId(),
      date: new Date().toISOString(),
      location: null,
      city: null,
      rent: null,
      bhk: null,
      additional_details: `Parsing failed: ${
        parsed && parsed.error ? parsed.error : "Unknown error"
      }`,
      latitude: null,
      longitude: null,
      distance_from_office_km: null,
      driving_duration: null,
      source,
      page_url: pageUrl,
      original_message: truncate(selectionText, 500),
    });
    return;
  }
  let lat = parsed.latitude != null ? Number(parsed.latitude) : null;
  let lon = parsed.longitude != null ? Number(parsed.longitude) : null;
  if (
    (lat == null || lon == null) &&
    settings.googleMapsApiKey &&
    (parsed.location || parsed.city)
  ) {
    try {
      const geo = await geocodeAddress(
        settings.googleMapsApiKey,
        parsed.location,
        parsed.city
      );
      if (geo) {
        lat = geo.lat;
        lon = geo.lon;
      }
    } catch {}
  }
  let distanceKm = null,
    durationText = null;
  if (
    settings.computeDistance &&
    settings.googleMapsApiKey &&
    settings.office?.lat &&
    settings.office?.lon &&
    lat != null &&
    lon != null
  ) {
    try {
      const out = await distanceViaDirections(
        settings.googleMapsApiKey,
        { lat: settings.office.lat, lon: settings.office.lon },
        { lat, lon }
      );
      distanceKm = out.distanceKm;
      durationText = out.durationText;
    } catch {}
  }
  await addResult({
    message_id: genId(),
    date: new Date().toISOString(),
    location: parsed.location || null,
    city: parsed.city || null,
    rent: parsed.rent || null,
    bhk: parsed.bhk || null,
    additional_details: parsed.additional_details || null,
    latitude: lat,
    longitude: lon,
    distance_from_office_km: distanceKm,
    driving_duration: durationText,
    source,
    page_url: pageUrl,
    original_message: truncate(selectionText, 500),
  });
}
