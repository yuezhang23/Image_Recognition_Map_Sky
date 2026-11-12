"""Write chrome_extension/pod_prompt.json from pod_check.py so the extension sends the same system prompt and
observation schema as the Python pipeline.

Run from the repo root after editing POD_standard.md or pod_check.py, then reload the extension:

python chrome_extension/build_prompt.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pod_check  # noqa: E402
from llm_vendors import DEFAULT_MODELS  # noqa: E402

out = os.path.join(ROOT, "chrome_extension", "pod_prompt.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({
        "system": pod_check.system_prompt(os.path.join(ROOT, "POD_standard.md")),
        "schema": pod_check.OBSERVATION_SCHEMA,
        "max_edge": pod_check.MAX_EDGE,
        "default_models": DEFAULT_MODELS,
    }, f, indent=1, ensure_ascii=False)
print("wrote", out)
