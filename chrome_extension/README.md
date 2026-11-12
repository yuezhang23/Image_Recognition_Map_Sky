# POD photo check: Chrome extension

Checks the POD photos on the page you are viewing against Part A of `POD_standard.md`, using the same prompt, observation schema and rules as `pod_check.py`. It shows the R1–R5 results and the verdict in the popup and in a panel on the page.

## Install

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and pick this `chrome_extension/` folder.
3. Open the extension's **Settings** (the link in the popup, or right-click the icon → Options). Pick a vendor, paste its API key, and click **Save**.
   You can also import `tracking_address.json` there, so the expected address fills in by itself for known tracking numbers.

## Use

1. Open a page that shows a package's delivery photos.
2. Click the extension icon. The popup:
   - finds `SPX…` tracking numbers and a US address on the page and fills them in. Check both before running;
   - lists the photos on the page that are at least 200 px wide and tall, plus links to `.jpg`, `.png` and `.webp` files. If any photo comes from `spxblob.blob.core.windows.net`, only those are selected at first. Click a thumbnail to add or remove it.
3. Click **Check photos**. The photos are downloaded and resized to a longest edge of 1024 px, as `pod_check.py` does. They are sent in one request to the chosen model, and `rules.js` turns the model's observations into the verdict.

The check runs in the background, so you can close the popup. The result appears in a panel at the top right of the page, and the popup shows it again when reopened on the same tab.

Photos hosted anywhere other than the SpeedX blob store need a one-time permission, which Chrome asks for when you click **Check photos**.

## Vendors

| Vendor | Default model | Notes |
|---|---|---|
| Anthropic | `claude-opus-5-5` | Effort `medium`, structured output. On Claude Opus 5 / 5.5, Fable 5.x and Sonnet 5.5, a request the model declines is retried on a fallback model (`fallbacks: "default"`). |
| OpenAI | `gpt-5.5` | Strict JSON schema |
| DeepSeek | `deepseek-flash` | JSON mode, schema in the prompt. Avoid `deepseek-v4-pro`: it ignores images. |
| Qwen | `qwen3.8-omni-flash` | |

API keys are kept in `chrome.storage.local` in this browser profile and are sent only to the API of the vendor they belong to. Anyone with access to this Chrome profile can read them.

## Keeping it in sync with the Python pipeline

- `pod_prompt.json` is generated from `pod_check.py` and `POD_standard.md`. After editing either, run this from the repo root and then reload the extension:

  ```bash
  python chrome_extension/build_prompt.py
  ```

- `rules.js` is a hand port of `rules.py`. After changing `rules.py`, update `rules.js` to match, then check that both give the same result on every saved observation in `results/raw/`:

  ```bash
  node chrome_extension/test_rules_parity.mjs
  ```

## Files

| File | Role |
|---|---|
| `manifest.json` | Manifest V3. Permissions: `activeTab`, `scripting`, `storage`, plus the blob store and the four LLM APIs. |
| `popup.html/js` | Reads the page, lets you pick photos, starts the check, shows the result. |
| `collect.js` | Injected into the page to find tracking numbers, addresses and photos. |
| `background.js` | Service worker: downloads and resizes the photos, calls the LLM, applies the rules, stores the result per tab. |
| `llm.js` | Vendor clients and retry logic, mirroring `llm_vendors.py`. |
| `rules.js` | Port of `rules.py`. |
| `panel.js` | The result panel shown on the page. |
| `options.html/js` | Vendor, model, API keys and the address import. |
