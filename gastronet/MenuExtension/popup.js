const BASE_URL = "https://openskagit.com";
let currentRestaurantId = null;
let currentSourceUrl = "";
let extractedItems = [];
let helperTabId = null;
const injectedHelperTabs = new Set();

const statusEl = document.getElementById("status");
const nameEl = document.getElementById("restaurant-name");

function setStatus(message) {
  statusEl.innerText = message;
}

function ensureHelperTab() {
  if (!helperTabId) {
    throw new Error(
      "Open the staff console tab on openskagit.com and click \"Load Next Restaurant\" from there first."
    );
  }
}

async function ensureHelperScript(tabId) {
  if (!injectedHelperTabs.has(tabId)) {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["menu_helper.js"],
    });
    injectedHelperTabs.add(tabId);
  }
}

function sendToHelper(message) {
  ensureHelperTab();
  return new Promise((resolve, reject) => {
    (async () => {
      try {
        await ensureHelperScript(helperTabId);
        chrome.tabs.sendMessage(helperTabId, message, (response) => {
          const err = chrome.runtime.lastError;
          if (err) {
            helperTabId = null;
            reject(new Error(err.message));
            return;
          }
          resolve(response);
        });
      } catch (error) {
        helperTabId = null;
        reject(error);
      }
    })();
  });
}

function getActiveTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(err);
        return;
      }
      resolve(tabs[0]);
    });
  });
}

document.getElementById("btn-next").addEventListener("click", async () => {
  setStatus("Loading next restaurant...");
  try {
    const activeTab = await getActiveTab();
    if (!activeTab?.url?.startsWith(BASE_URL)) {
      throw new Error(`Activate a staff openskagit.com tab before fetching data.`);
    }
    helperTabId = activeTab.id;

    const helperResponse = await sendToHelper({ type: "nextRestaurant" });
    if (!helperResponse?.success) {
      throw new Error(helperResponse?.error || "no response from helper");
    }

    const data = helperResponse.data;
    const menuUrl = data.menu_url || data.website;
    if (!menuUrl) {
      throw new Error("Restaurant does not expose a menu URL.");
    }
    currentRestaurantId = data.id;
    currentSourceUrl = menuUrl;
    nameEl.innerText = data.name || "Unnamed Restaurant";
    statusEl.innerText = `Loaded ${data.name || "restaurant"}. Opening menu...`;

    await chrome.tabs.create({ url: menuUrl });
    document.getElementById("btn-save").style.display = "none";
    extractedItems = [];
  } catch (error) {
    setStatus(`Error: ${error.message}`);
  }
});

document.getElementById("btn-scrape").addEventListener("click", async () => {
  setStatus("Extracting page text and calling AI...");
  try {
    ensureHelperTab();
    const menuTab = await getActiveTab();
    if (!menuTab || menuTab.url?.startsWith(BASE_URL)) {
      throw new Error("Switch to the restaurant page before scraping.");
    }

    const [result] = await chrome.scripting.executeScript({
      target: { tabId: menuTab.id },
      func: () => document.body.innerText,
    });
    const text = (result && result.result) || "";
    if (!text) {
      throw new Error("Could not read text from the page.");
    }

    const helperResponse = await sendToHelper({
      type: "extractMenuItems",
      payload: { text },
    });
    if (!helperResponse?.success) {
      throw new Error(helperResponse?.error || "AI returned no data");
    }

    extractedItems = helperResponse.data?.items || [];
    statusEl.innerText = `AI found ${extractedItems.length} items. Confirm and save.`;
    document.getElementById("btn-save").style.display = "block";
  } catch (error) {
    setStatus(`AI Error: ${error.message}`);
  }
});

document.getElementById("btn-save").addEventListener("click", async () => {
  setStatus("Saving to database...");
  try {
    ensureHelperTab();
    if (!currentRestaurantId || !extractedItems.length) {
      throw new Error("No extracted items to save.");
    }

    const helperResponse = await sendToHelper({
      type: "saveMenuItems",
      payload: {
        restaurant_id: currentRestaurantId,
        items: extractedItems,
        source_url: currentSourceUrl,
      },
    });
    if (!helperResponse?.success) {
      throw new Error(helperResponse?.error || "save request failed");
    }

    const result = helperResponse.data;
    if (result.status !== "success") {
      throw new Error(result.error || "unexpected response");
    }

    setStatus(`Success! Ingested ${result.ingested} items.`);
    document.getElementById("btn-save").style.display = "none";
    extractedItems = [];
  } catch (error) {
    setStatus(`Save Error: ${error.message}`);
  }
});
