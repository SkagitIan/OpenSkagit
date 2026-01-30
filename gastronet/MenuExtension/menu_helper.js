const API_BASE = `${location.origin}/api/gastronet/human-in-loop`;

async function fetchJson(path, init = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Invalid JSON response: ${error.message}`);
  }
}

async function fetchNextRestaurant() {
  return fetchJson("/next-restaurant/");
}

async function extractMenuItems(text) {
  if (!text || typeof text !== "string") {
    throw new Error("text payload is required");
  }
  return fetchJson("/extract-menu-items/", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

async function saveMenuItems(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("payload is required");
  }
  return fetchJson("/save-menu-items/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      let data;
      switch (message.type) {
        case "nextRestaurant":
          data = await fetchNextRestaurant();
          break;
        case "extractMenuItems":
          data = await extractMenuItems(message.payload?.text);
          break;
        case "saveMenuItems":
          data = await saveMenuItems(message.payload);
          break;
        default:
          throw new Error("Unknown request type");
      }
      sendResponse({ success: true, data });
    } catch (error) {
      sendResponse({ success: false, error: error.message || String(error) });
    }
  })();
  return true;
});
