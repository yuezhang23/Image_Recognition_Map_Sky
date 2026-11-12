// Vision LLM clients, mirroring llm_vendors.py. Each returns the parsed observations object.
// Calls are plain fetch() from the service worker; the extension has host permissions for these APIs.

export const VENDORS = {
  anthropic: { label: "Anthropic", keyName: "anthropic" },
  openai: { label: "OpenAI", keyName: "openai", baseUrl: "https://api.openai.com/v1", strict: true },
  deepseek: { label: "DeepSeek", keyName: "deepseek", baseUrl: "https://api.deepseek.com", strict: false },
  qwen: { label: "Qwen", keyName: "qwen", baseUrl: "https://us-east-1.maas.qwencloudapi.com/compatible-mode/v1", strict: true },
};

class HttpError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}: ${body.slice(0, 500)}`);
    this.status = status;
  }
}

async function postJson(url, headers, body) {
  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
  const text = await res.text();
  if (!res.ok) throw new HttpError(res.status, text);
  return JSON.parse(text);
}

async function anthropic(apiKey, model, system, images, schema) {
  const content = [];
  for (const [label, b64] of images) {
    content.push({ type: "text", text: label });
    content.push({ type: "image", source: { type: "base64", media_type: "image/jpeg", data: b64 } });
  }
  content.push({ type: "text", text: "Report your observations for every image." });
  const body = {
    model,
    max_tokens: 16000,
    system,
    output_config: { effort: "medium", format: { type: "json_schema", schema } },
    messages: [{ role: "user", content }],
  };
  const headers = {
    "x-api-key": apiKey,
    "anthropic-version": "2026-10-21",
    // required for requests that carry a browser/extension Origin
    "anthropic-dangerous-direct-browser-access": "true",
  };
  if (/^claude-(opus-5|fable-5|sonnet-5-5)/.test(model)) {
    // on a safety decline, the API re-runs the request on a fallback model instead of returning nothing
    headers["anthropic-beta"] = "server-side-fallback-2026-07-01";
    body.fallbacks = "default";
  }
  const response = await postJson("https://api.anthropic.com/v1/messages", headers, body);
  if (response.stop_reason === "refusal") throw new Error(`model refused: ${JSON.stringify(response.stop_details)}`);
  const text = response.content.find((b) => b.type === "text");
  if (!text) throw new SyntaxError("no text block in response");
  return JSON.parse(text.text);
}

async function openaiCompatible(vendor, apiKey, model, system, images, schema) {
  const v = VENDORS[vendor];
  const content = [];
  for (const [label, b64] of images) {
    content.push({ type: "text", text: label });
    content.push({ type: "image_url", image_url: { url: `data:image/jpeg;base64,${b64}` } });
  }
  content.push({ type: "text", text: "Report your observations for every image as JSON." });
  let responseFormat;
  if (v.strict) {
    responseFormat = { type: "json_schema", json_schema: { name: "pod_observations", schema, strict: true } };
  } else {
    // DeepSeek only supports json_object mode, so the schema goes in the prompt
    system = `${system}\n\nReturn only a JSON object matching this JSON schema:\n${JSON.stringify(schema)}`;
    responseFormat = { type: "json_object" };
  }
  const response = await postJson(`${v.baseUrl}/chat/completions`, { authorization: `Bearer ${apiKey}` }, {
    model,
    messages: [{ role: "system", content: system }, { role: "user", content }],
    response_format: responseFormat,
  });
  let data = JSON.parse(response.choices[0].message.content);
  // Qwen does not strictly enforce the schema: the object sometimes comes back wrapped in a one-item list
  if (Array.isArray(data) && data.length === 1 && data[0] && typeof data[0] === "object") data = data[0];
  return data;
}

export function extract(vendor, apiKey, model, system, images, schema) {
  if (vendor === "anthropic") return anthropic(apiKey, model, system, images, schema);
  return openaiCompatible(vendor, apiKey, model, system, images, schema);
}

// Lightweight stand-in for the pydantic validation in pod_check.py: reject output the rules can't use.
export function validate(data) {
  if (!data || typeof data !== "object" || !Array.isArray(data.images)) throw new TypeError("missing images list");
  for (const im of data.images) {
    if (!im || typeof im !== "object" || !Number.isInteger(im.index) || !Array.isArray(im.types)) {
      throw new TypeError(`malformed image entry: ${JSON.stringify(im).slice(0, 200)}`);
    }
  }
  return data;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Same policy as extract_with_retry: retry malformed output at once, back off on 429/5xx/network errors.
export async function extractWithRetry(vendor, apiKey, model, system, images, schema, attempts = 3) {
  let last;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return validate(await extract(vendor, apiKey, model, system, images, schema));
    } catch (e) {
      last = e;
      if (e instanceof SyntaxError || e instanceof TypeError && !(e.message || "").includes("fetch")) continue;
      if (e instanceof HttpError && e.status < 500 && e.status !== 429) throw e;
      await sleep(Math.min(2 ** attempt * 1000 + Math.random() * 1000, 60000));
    }
  }
  throw new Error(`extraction failed after ${attempts} attempts: ${last?.message || last}`);
}
