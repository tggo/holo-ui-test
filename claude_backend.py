"""
Claude backends — for the comparison against local Holo.

Backend B  : ClaudeLocalizer — drop-in Localizer. Same harness, same steps;
             Claude vision returns the same {x,y} (0..1000) grid as Holo, so
             we measure the *vision step* head-to-head.

Backend C  : ClaudeAgent — no Holo, no fixed step list. Claude is given the
             high-level goal + a tiny tool set (click/type/done) and drives the
             page itself in a screenshot->decide->act loop. Measures full
             agentic wall-time for "the same actions".

Both read ANTHROPIC_API_KEY from the environment.
Model ids: claude-sonnet-4-6, claude-haiku-4-5-20251001.
"""
from __future__ import annotations

import base64
import json
import time

import anthropic
from playwright.sync_api import Page

from harness import Hit, RunResult, StepTiming

# ---- Backend B: Claude as a pure localizer ---------------------------------

# Claude is trained to output *actual pixel* coordinates for the image it sees,
# not a normalized grid — so we give it the exact image size and ask for pixels.
# (Forcing Holo's 0..1000 grid onto Claude handicaps it; this is the fair contract.)
_LOC_SYS = (
    "You are a precise GUI element localizer. The screenshot is exactly "
    "{w}x{h} pixels. Given a target description, output the pixel click position "
    'as JSON {{"x":int,"y":int}} where (0,0) is the top-left corner and x<{w}, '
    "y<{h}. Aim for the visual center of the element. Output ONLY the JSON."
)


class ClaudeLocalizer:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        self.name = f"{model} (localizer)"
        self.client = anthropic.Anthropic()
        self.in_tok = self.out_tok = self.calls = 0

    def locate(self, png_bytes: bytes, target: str, width: int, height: int) -> Hit:
        b64 = base64.b64encode(png_bytes).decode()
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=128,
            system=_LOC_SYS.format(w=width, h=height),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": f"Target: {target}"},
                ],
            }],
        )
        self.calls += 1
        self.in_tok += msg.usage.input_tokens
        self.out_tok += msg.usage.output_tokens
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        # grab the first complete JSON object; tolerate ```json fences / trailing prose
        s = text.find("{")
        data, _ = json.JSONDecoder().raw_decode(text[s:])
        px, py = int(data["x"]), int(data["y"])
        px = max(0, min(px, width - 1))
        py = max(0, min(py, height - 1))
        return Hit(int(px / width * 1000), int(py / height * 1000), px, py)


# ---- Backend C: full Claude computer-use agent -----------------------------

_AGENT_TOOLS = [
    {
        "name": "click",
        "description": "Click an element described in natural language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "what to click"},
                "x": {"type": "integer", "description": "x pixel, 0=left"},
                "y": {"type": "integer", "description": "y pixel, 0=top"},
            },
            "required": ["target", "x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Click a field then type text into it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["target", "x", "y", "text"],
        },
    },
    {
        "name": "done",
        "description": "Call when the goal is achieved or impossible.",
        "input_schema": {
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "reason": {"type": "string"}},
            "required": ["success"],
        },
    },
]

_AGENT_SYS = (
    "You are a UI test agent driving a real web browser. You see a screenshot "
    "after every action; it is exactly {w}x{h} pixels. Coordinates you give are "
    "actual pixels, (0,0) at the top-left. Take ONE action per turn using the "
    "provided tools. After an action the new screenshot shows the result — if "
    "nothing changed your click probably missed, so adjust. Be efficient: reach "
    "the goal in as few actions as possible, then call done."
)


def _shot(page: Page) -> tuple[str, int, int]:
    png = page.screenshot()
    vp = page.viewport_size or {"width": 1280, "height": 800}
    return base64.b64encode(png).decode(), vp["width"], vp["height"]


def run_claude_agent(page: Page, goal: str, start_url: str,
                     model: str = "claude-sonnet-4-6",
                     max_steps: int = 12, settle_ms: int = 600) -> RunResult:
    client = anthropic.Anthropic()
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(settle_ms)
    sys_prompt = _AGENT_SYS  # filled in with real dimensions after first screenshot

    steps: list[StepTiming] = []
    t0 = time.perf_counter()
    model_total = 0.0
    in_tok = out_tok = calls = 0
    run_ok = False

    b64, w, h = _shot(page)
    sys_prompt = _AGENT_SYS.format(w=w, h=h)
    history = [{
        "role": "user",
        "content": [
            {"type": "text", "text": f"Goal: {goal}\nStart URL: {start_url}\nCurrent screenshot:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        ],
    }]

    for _ in range(max_steps):
        m0 = time.perf_counter()
        msg = client.messages.create(
            model=model, max_tokens=1024, system=sys_prompt,
            tools=_AGENT_TOOLS, messages=history,
        )
        model_total += time.perf_counter() - m0
        calls += 1
        in_tok += msg.usage.input_tokens
        out_tok += msg.usage.output_tokens
        history.append({"role": "assistant", "content": msg.content})

        tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
        if tool_use is None:
            steps.append(StepTiming("model returned no tool_use", 0.0, ok=False))
            break

        s_start = time.perf_counter()
        name, args = tool_use.name, tool_use.input
        ok, detail = True, ""

        if name == "done":
            run_ok = bool(args.get("success"))
            steps.append(StepTiming(f"done(success={run_ok})",
                                    time.perf_counter() - s_start, ok=run_ok,
                                    detail=args.get("reason", "")))
            break

        try:
            px = max(0, min(int(args["x"]), w - 1))
            py = max(0, min(int(args["y"]), h - 1))
            if name == "click":
                page.mouse.click(px, py)
                desc = f"click '{args['target']}' @({px},{py})"
            elif name == "type_text":
                page.mouse.click(px, py)
                page.keyboard.type(args["text"], delay=20)
                desc = f"type into '{args['target']}' @({px},{py})"
            else:
                ok, desc = False, f"unknown tool {name}"
            page.wait_for_timeout(settle_ms)
        except Exception as e:
            ok, detail, desc = False, f"{type(e).__name__}: {e}", f"{name} (errored)"

        steps.append(StepTiming(desc, time.perf_counter() - s_start, ok=ok, detail=detail))

        b64, w, h = _shot(page)
        history.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use.id,
                 "content": "action done; new screenshot:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            ],
        })

    return RunResult(
        backend=f"{model} (full agent)",
        ok=run_ok,
        total_seconds=time.perf_counter() - t0,
        localize_seconds=model_total,
        steps=steps,
        in_tokens=in_tok,
        out_tokens=out_tok,
        calls=calls,
    )
