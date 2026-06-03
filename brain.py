"""
The BRAIN — decides the next action from a *text* observation of the page
(visible text + a list of interactive elements) plus the goal and history.

It deliberately does NOT see pixels: that's the EYES' job (eyes.py / the
localizers). The brain emits a natural-language target ("the Cart link"); the
eyes turn it into a click coordinate. This split is the canonical Holo design —
a grounding model + a separate reasoning LLM — and it lets the brain be a small
local text model.

Two implementations:
  LocalBrain  — a light model via Ollama (OpenAI-compatible, localhost:11434)
  SonnetBrain — Claude
Both expose next_action(goal, observation, history) -> Decision and track tokens.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

_SYS = """You drive a web UI to accomplish a goal. You are given the goal, a text \
observation of the current page (visible text + the interactive elements), and the \
history of actions already taken. Decide the SINGLE next action.

Reply with ONLY a JSON object, where "action" is exactly one of click, type, done:
{"thought":"...","action":"click","target":"...","text":"","success":false}

Rules:
- "target" must identify ONE element from the "Interactive elements" list. If several \
share a label (e.g. many "Add to cart"), DISAMBIGUATE using the "(in: ...)" context, \
e.g. target = "Add to cart for Mechanical Keyboard".
- To press a button/link, target its action label (e.g. "Add to cart", "Proceed to \
checkout") — NOT the product name text.
- Use "type" to fill an input; set "text" to the value. It clicks the field then types.
- Look at history: NEVER repeat an action already done successfully. Move forward.
- When the page shows the goal is achieved, action "done", success true.

Example: goal "add the Webcam to the cart".
Observation lists: button: "Add to cart" (in: Webcam HD $45), button: "Add to cart" (in: USB-C Cable $12)
Correct reply: {"thought":"add the Webcam one","action":"click","target":"Add to cart for Webcam HD","text":"","success":false}
"""


@dataclass
class Decision:
    action: str            # click | type | done
    target: str = ""
    text: str = ""
    success: bool = False
    thought: str = ""


def _parse(raw: str) -> Decision:
    # grab the FIRST complete JSON object; tolerate prose / a second object after it
    s = raw.find("{")
    if s < 0:
        raise ValueError(f"no JSON object in: {raw[:80]!r}")
    d, _ = json.JSONDecoder().raw_decode(raw[s:])
    act = str(d.get("action", "")).lower().strip()
    # salvage sloppy outputs like "click|type" or "click the button"
    for cand in ("done", "type", "click"):
        if cand in act:
            act = cand
            break
    return Decision(
        action=act,
        target=d.get("target", "") or "",
        text=d.get("text", "") or "",
        success=bool(d.get("success", False)),
        thought=d.get("thought", "") or "",
    )


def _user_msg(goal: str, observation: str, history: list[str]) -> str:
    hist = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(history)) or "  (none yet)"
    return (f"GOAL:\n{goal}\n\nPAGE OBSERVATION:\n{observation}\n\n"
            f"ACTIONS TAKEN SO FAR:\n{hist}\n\nNext action as JSON:")


class LocalBrain:
    """Light local model via Ollama as the planner.

    Forced onto CPU (options.num_gpu=0): the GPU is fully occupied by Holo's
    21 GB on Metal, so a co-resident brain there triggers Metal OOM. CPU keeps
    the two engines isolated. Uses Ollama's native /api/chat for that control.
    """
    def __init__(self, model: str = "qwen2.5:7b",
                 host: str = "http://localhost:11434", gpu: bool = False):
        self.model = model
        self.name = f"local:{model}"
        self.url = host.rstrip("/") + "/api/chat"
        self.num_gpu = None if gpu else 0   # 0 => CPU only
        self.in_tok = self.out_tok = self.calls = 0

    def _call(self, user: str, temp: float) -> tuple[str, int, int]:
        opts = {"temperature": temp, "num_predict": 400}
        if self.num_gpu is not None:
            opts["num_gpu"] = self.num_gpu
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": _SYS},
                         {"role": "user", "content": user}],
            "format": "json", "stream": False, "options": opts,
        }).encode()
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            d = json.loads(resp.read())
        return (d.get("message", {}).get("content", ""),
                d.get("prompt_eval_count", 0), d.get("eval_count", 0))

    def next_action(self, goal: str, observation: str, history: list[str]) -> Decision:
        user = _user_msg(goal, observation, history)
        last_err = None
        for attempt in range(3):  # small local models occasionally emit empty/garbage
            content, pin, pout = self._call(user, 0.0 if attempt == 0 else 0.3)
            self.calls += 1
            self.in_tok += pin
            self.out_tok += pout
            try:
                return _parse(content)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
        raise ValueError(f"brain produced no valid JSON after 3 tries: {last_err}")


class SonnetBrain:
    """Claude as the planner (text-only observation, same contract as LocalBrain)."""
    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.model = model
        self.name = model
        self.client = anthropic.Anthropic()
        self.in_tok = self.out_tok = self.calls = 0

    def next_action(self, goal: str, observation: str, history: list[str]) -> Decision:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            system=_SYS,
            messages=[{"role": "user", "content": _user_msg(goal, observation, history)}],
        )
        self.calls += 1
        self.in_tok += msg.usage.input_tokens
        self.out_tok += msg.usage.output_tokens
        text = "".join(b.text for b in msg.content if b.type == "text")
        return _parse(text)
