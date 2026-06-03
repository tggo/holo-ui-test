"""
Backend A — local Holo 3.1 (Ollama) as the element localizer.

Talks to Ollama's OpenAI-compatible endpoint. The model has vision baked into
the GGUF, so a plain chat.completions call with an image works.

Prompt + output format are exactly per https://hub.hcompany.ai/element-localization:
target description -> {"x","y"} in a 0..1000 grid.
"""
from __future__ import annotations

import base64
import os

from openai import OpenAI
from pydantic import BaseModel, Field

from harness import Hit

# Served by a standalone llama.cpp `llama-server` (NOT ollama): ollama 0.23.2's
# engine doesn't implement the `qwen35moe` arch, and the hf.co/... pull shortcut
# 400s on the manifest. llama-server loads the cached GGUF + mmproj directly.
# See README "gotchas" for the launch command.
MODEL = "holo31"
BASE_URL = os.environ.get("HOLO_BASE_URL", "http://127.0.0.1:8080/v1")

_SYS = (
    "Localize an element on the GUI image according to the provided target "
    "and output a click position.\n"
    ' * You must output a valid JSON following the format: {{"x": <int>, "y": <int>}}\n'
    " Your target is:\n{element}"
)

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "point",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                "y": {"type": "integer", "minimum": 0, "maximum": 1000},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
}


class _Point(BaseModel):
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)


class HoloLocalizer:
    name = "holo-3.1-35b (llama.cpp local)"

    def __init__(self, base_url: str = BASE_URL):
        self.client = OpenAI(base_url=base_url, api_key="llama")
        self.in_tok = self.out_tok = self.calls = 0

    def locate(self, png_bytes: bytes, target: str, width: int, height: int) -> Hit:
        uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        resp = self.client.chat.completions.create(
            model=MODEL,
            temperature=0.0,
            messages=[
                {"role": "system", "content": _SYS.format(element=target)},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": uri}},
                    {"type": "text", "text": target},
                ]},
            ],
            response_format=_SCHEMA,
        )
        self.calls += 1
        if resp.usage:
            self.in_tok += resp.usage.prompt_tokens or 0
            self.out_tok += resp.usage.completion_tokens or 0
        p = _Point.model_validate_json(resp.choices[0].message.content)
        return Hit(p.x, p.y, int(p.x / 1000 * width), int(p.y / 1000 * height))
