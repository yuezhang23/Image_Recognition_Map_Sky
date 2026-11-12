import { VENDORS } from "./llm.js";

const $ = (id) => document.getElementById(id);
const prompt = await (await fetch("pod_prompt.json")).json();
const s = await chrome.storage.local.get({ vendor: "anthropic", models: {}, keys: {}, addressBook: {} });
let book = s.addressBook;

$("vendor").innerHTML = Object.entries(VENDORS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
$("vendor").value = s.vendor;
const showModel = () => {
  $("model").placeholder = prompt.default_models[$("vendor").value];
  $("model").value = s.models[$("vendor").value] || "";
};
showModel();
$("vendor").onchange = showModel;
$("model").oninput = () => { s.models[$("vendor").value] = $("model").value.trim(); };

$("keys").innerHTML = Object.entries(VENDORS).map(([k, v]) =>
  `<label>${v.label} <input type="password" id="key-${k}" autocomplete="off"></label>`).join("");
for (const k of Object.keys(VENDORS)) $(`key-${k}`).value = s.keys[k] || "";

const showBook = () => { $("book-status").textContent = `${Object.keys(book).length} addresses stored`; };
showBook();
$("book").onchange = async () => {
  try {
    const data = JSON.parse(await $("book").files[0].text());
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("expected {tracking_id: address}");
    book = Object.fromEntries(Object.entries(data).filter(([, v]) => typeof v === "string"));
    showBook();
  } catch (e) {
    $("book-status").textContent = `Could not read file: ${e.message}`;
  }
};

$("save").onclick = async () => {
  const keys = Object.fromEntries(Object.keys(VENDORS).map((k) => [k, $(`key-${k}`).value.trim()]));
  const models = Object.fromEntries(Object.entries(s.models).filter(([, m]) => m));
  await chrome.storage.local.set({ vendor: $("vendor").value, models, keys, addressBook: book });
  $("saved").textContent = "Saved.";
  setTimeout(() => { $("saved").textContent = ""; }, 2000);
};
