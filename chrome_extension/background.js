// Service worker: downloads the selected photos, asks the vision LLM for observations, applies rules.js,
// stores the result per tab and shows it in a panel on the page.
import { extractWithRetry } from "./llm.js";
import { evaluate } from "./rules.js";

let promptPromise;
function loadPrompt() {
  promptPromise ??= fetch(chrome.runtime.getURL("pod_prompt.json")).then((r) => r.json());
  return promptPromise;
}

export async function getSettings() {
  const prompt = await loadPrompt();
  const s = await chrome.storage.local.get({ vendor: "anthropic", models: {}, keys: {} });
  return { ...s, model: s.models[s.vendor] || prompt.default_models[s.vendor] };
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// Same preprocessing as load_images(): RGB, longest edge at most max_edge, JPEG quality 90.
async function loadImage(url, maxEdge) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`photo download failed (${res.status}): ${url.split("?")[0]}`);
  const bitmap = await createImageBitmap(await res.blob());
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale), h = Math.round(bitmap.height * scale);
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  const jpeg = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.9 });
  return toBase64(await jpeg.arrayBuffer());
}

const fileName = (url) => decodeURIComponent(url.split("?")[0].split("/").pop() || "photo");

async function showOnPage(tabId, state) {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["panel.js"] });
    await chrome.scripting.executeScript({ target: { tabId }, func: (s) => window.__podShowPanel(s), args: [state] });
  } catch {
    // the tab navigated away or does not allow scripts; the popup still shows the result
  }
}

async function setState(tabId, state) {
  await chrome.storage.session.set({ [`tab:${tabId}`]: state });
  chrome.runtime.sendMessage({ type: "state", tabId, state }).catch(() => {});
  await showOnPage(tabId, state);
}

async function runCheck(tabId, { trackingId, address, urls }) {
  // keep the service worker alive while the (possibly minute-long) LLM call is in flight
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(), 20000);
  const base = { trackingId, address, photos: urls.map(fileName), startedAt: Date.now() };
  try {
    const prompt = await loadPrompt();
    const { vendor, model, keys } = await getSettings();
    const apiKey = keys[vendor];
    if (!apiKey) throw new Error(`No ${vendor} API key. Add one on the extension's options page.`);
    await setState(tabId, { ...base, status: "running", vendor, model, step: `Downloading ${urls.length} photos…` });
    const b64 = await Promise.all(urls.map((u) => loadImage(u, prompt.max_edge)));
    const images = b64.map((data, i) => [`image_${i + 1} (${fileName(urls[i])})`, data]);
    await setState(tabId, { ...base, status: "running", vendor, model, step: `Asking ${model}…` });
    const observations = await extractWithRetry(vendor, apiKey, model, prompt.system, images, prompt.schema);
    const result = evaluate(observations, trackingId, address);
    await setState(tabId, { ...base, status: "done", vendor, model, ...result, observations, finishedAt: Date.now() });
  } catch (e) {
    await setState(tabId, { ...base, status: "error", error: e.message || String(e) });
  } finally {
    clearInterval(keepAlive);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "check") {
    runCheck(msg.tabId, msg.job);
    sendResponse({ ok: true });
  } else if (msg.type === "getState") {
    chrome.storage.session.get(`tab:${msg.tabId}`).then((r) => sendResponse(r[`tab:${msg.tabId}`] || null));
    return true;
  }
});

chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove(`tab:${tabId}`));
