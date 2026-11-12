const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CHECKS = { r1_label: "R1 Label", r2_placement: "R2 Placement", r3_address: "R3 Address",
                 r4_scenario: "R4 Scenario", r5_prohibited: "R5 Prohibited" };
const PHOTO_HOST = "spxblob.blob.core.windows.net";

let tab, photos = [], addressBook = {};

function renderState(s) {
  const box = $("result");
  $("check").disabled = s?.status === "running";
  if (!s) { box.innerHTML = ""; return; }
  if (s.status === "running") { box.innerHTML = `<div class="verdict">Checking…</div><div class="muted">${esc(s.step)}</div>`; return; }
  if (s.status === "error") { box.innerHTML = `<div class="verdict err">Error</div><div class="err">${esc(s.error)}</div>`; return; }
  box.innerHTML =
    `<div class="verdict">${esc(s.trackingId)}: <span class="badge ${s.verdict}">${esc(s.verdict)}</span></div>` +
    Object.entries(CHECKS).map(([k, name]) => {
      const c = s.checks?.[k] || { status: "REVIEW", reason: "" };
      return `<div class="row"><span class="badge ${c.status === "N/A" ? "NA" : c.status}">${esc(c.status)}</span>` +
             `<div><b>${name}</b><div class="muted">${esc(c.reason)}</div></div></div>`;
    }).join("") +
    `<div class="muted" style="margin-top:6px">${esc(s.vendor)} / ${esc(s.model)} · ${s.photos.length} photos · ` +
    `${Math.round((s.finishedAt - s.startedAt) / 1000)}s</div>` +
    `<details><summary class="muted">LLM observations</summary><pre>${esc(JSON.stringify(s.observations, null, 1))}</pre></details>`;
}

function renderPhotos() {
  $("photo-count").textContent = `${photos.filter((p) => p.on).length} of ${photos.length} selected`;
  $("photos").innerHTML = photos.length ? "" : `<div class="muted" style="grid-column:1/-1">No photos found on this page.</div>`;
  photos.forEach((p, i) => {
    const el = document.createElement("div");
    el.className = "thumb" + (p.on ? " on" : "");
    el.title = p.url.split("?")[0];
    el.innerHTML = `<img src="${esc(p.url)}"><span class="n">${i + 1}</span>`;
    el.onclick = () => { p.on = !p.on; renderPhotos(); };
    $("photos").appendChild(el);
  });
}

function fillAddress() {
  const t = $("tracking").value.trim().toUpperCase();
  if (addressBook[t]) {
    $("address").value = addressBook[t];
    $("address-note").textContent = "From your imported tracking_address.json";
  }
}

async function init() {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const settings = await chrome.storage.local.get({ vendor: "anthropic", models: {}, keys: {}, addressBook: {} });
  const prompt = await (await fetch("pod_prompt.json")).json();
  addressBook = settings.addressBook;
  const model = settings.models[settings.vendor] || prompt.default_models[settings.vendor];
  $("model").innerHTML = `${esc(settings.vendor)} / ${esc(model)}` +
    (settings.keys[settings.vendor] ? "" : ` · <span class="err">no API key set</span>`);

  let page = { trackingIds: [], addresses: [], images: [] };
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["collect.js"] });
    page = res.result || page;
  } catch {
    $("address-note").textContent = "Can't read this page (browser pages and the Web Store are off limits).";
  }
  $("tracking-list").innerHTML = page.trackingIds.map((t) => `<option value="${esc(t)}">`).join("");
  $("address-list").innerHTML = page.addresses.map((a) => `<option value="${esc(a)}">`).join("");

  const fromBlob = page.images.some((im) => new URL(im.url).host === PHOTO_HOST);
  photos = page.images.map((im) => ({ ...im, on: !fromBlob || new URL(im.url).host === PHOTO_HOST }));
  renderPhotos();

  const saved = (await chrome.runtime.sendMessage({ type: "getState", tabId: tab.id })) || null;
  $("tracking").value = saved?.trackingId || page.trackingIds[0] || "";
  $("address").value = saved?.address || "";
  if (!$("address").value) fillAddress();
  if (!$("address").value && page.addresses[0]) {
    $("address").value = page.addresses[0];
    $("address-note").textContent = "Detected on the page. Check it before running.";
  }
  renderState(saved);
}

$("tracking").addEventListener("change", fillAddress);
$("options").onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };

$("check").onclick = async () => {
  const trackingId = $("tracking").value.trim().toUpperCase();
  const address = $("address").value.trim();
  const urls = photos.filter((p) => p.on).map((p) => p.url);
  if (!trackingId || !address || !urls.length) {
    renderState({ status: "error", error: "Enter the tracking number and the expected address, and select at least one photo." });
    return;
  }
  // photos hosted outside the SpeedX blob store need a one-time permission to download them
  const origins = [...new Set(urls.map((u) => `${new URL(u).origin}/*`))].filter((o) => !o.includes(PHOTO_HOST));
  if (origins.length && !(await chrome.permissions.request({ origins }))) {
    renderState({ status: "error", error: `Permission to download photos from ${origins.join(", ")} was declined.` });
    return;
  }
  renderState({ status: "running", step: "Starting…" });
  chrome.runtime.sendMessage({ type: "check", tabId: tab.id, job: { trackingId, address, urls } });
};

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "state" && msg.tabId === tab?.id) renderState(msg.state);
});

init();
