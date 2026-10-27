"""Vision LLM clients behind one interface: extract(system, images, schema) -> dict.

images is a list of (label, base64_jpeg) tuples.
"""
import json
import os
import random
import time

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5.5",
    # deepseek-v4-pro accepts image input but silently ignores it; deepseek-flash actually sees images
    "deepseek": "deepseek-flash",
}


def _backoff(attempt):
    time.sleep(min(2 ** attempt + random.uniform(0, 1), 60))


class AnthropicClient:
    def __init__(self, model):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=5)
        self.model = model

    def extract(self, system, images, schema):
        content = []
        for label, b64 in images:
            content.append({"type": "text", "text": label})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        content.append({"type": "text", "text": "Report your observations for every image."})
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"model refused: {response.stop_details}")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


class OpenAIClient:
    base_url = None
    key_env = "OPENAI_API_KEY"
    # DeepSeek only supports json_object mode, so the schema goes in the prompt
    strict_schema = True

    def __init__(self, model):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ[self.key_env], base_url=self.base_url, max_retries=5)
        self.model = model

    def extract(self, system, images, schema):
        content = []
        for label, b64 in images:
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        content.append({"type": "text", "text": "Report your observations for every image as JSON."})
        if self.strict_schema:
            response_format = {"type": "json_schema",
                               "json_schema": {"name": "pod_observations", "schema": schema, "strict": True}}
        else:
            system = f"{system}\n\nReturn only a JSON object matching this JSON schema:\n{json.dumps(schema)}"
            response_format = {"type": "json_object"}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            response_format=response_format,
        )
        return json.loads(response.choices[0].message.content)


class DeepSeekClient(OpenAIClient):
    base_url = "https://api.deepseek.com"
    key_env = "DEEPSEEK_API_KEY"
    strict_schema = False


VENDORS = {"anthropic": AnthropicClient, "openai": OpenAIClient, "deepseek": DeepSeekClient}


def make_client(vendor, model=None):
    return VENDORS[vendor](model or DEFAULT_MODELS[vendor])


def check_vision(client):
    """Fail fast if the model drops images without erroring: ask it to read a number drawn on a test image."""
    import base64, io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(img).text((60, 40), "4826", fill="black", font=ImageFont.load_default(size=110))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    schema = {"type": "object", "properties": {"number": {"type": "string"}},
              "required": ["number"], "additionalProperties": False}
    try:
        data = client.extract("Read the number shown in the image.",
                              [("image_1", base64.standard_b64encode(buf.getvalue()).decode())], schema)
    except Exception as e:
        raise SystemExit(f"{client.model}: vision check failed: {e}")
    if "4826" not in str(data.get("number")):
        raise SystemExit(f"{client.model} could not read the test image (got {data!r}); "
                         "it probably ignores image input - pick a vision-capable model with --model")


def extract_with_retry(client, system, images, schema, validate, attempts=3):
    """Call the model, validate the JSON, and retry on parse/validation or transient errors."""
    last = None
    for attempt in range(attempts):
        try:
            return validate(client.extract(system, images, schema))
        except (json.JSONDecodeError, ValueError, KeyError, StopIteration) as e:
            last = e  # malformed output: retry right away
        except Exception as e:
            # SDKs already retry 429/5xx; only back off on what slips through
            status = getattr(e, "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            last = e
            _backoff(attempt)
    raise RuntimeError(f"extraction failed after {attempts} attempts: {last}")
