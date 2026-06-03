"""
The agent loop wiring EYES (grounder) + BRAIN (planner).

  observe(page)            -> text observation (visible text + interactive elements)
  run_agent(page, ...)     -> brain picks an action from the observation, eyes
                              localize the target on the screenshot, we execute,
                              repeat until 'done' or max_steps.

This is the eyes+brain matrix the benchmark compares:
  Holo  + LocalModel   (all local, $0)
  Holo  + Sonnet
  Sonnet + Sonnet
"""
from __future__ import annotations

import time

from playwright.sync_api import Page

from harness import RunResult, StepTiming


def observe(page: Page, max_text: int = 1200) -> str:
    """Text view of the page: visible body text + a list of interactive elements."""
    body = page.inner_text("body").strip()
    if len(body) > max_text:
        body = body[:max_text] + " …"
    elements = page.eval_on_selector_all(
        "a, button, input, textarea, select, [role=button], [onclick]",
        """els => els.filter(e => {
              const r = e.getBoundingClientRect();
              const s = getComputedStyle(e);
              return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
           }).slice(0,40).map(e => {
              const tag = e.tagName.toLowerCase();
              const label = (e.innerText || e.value || e.placeholder ||
                             e.getAttribute('aria-label') || '').trim().slice(0,60);
              // disambiguate repeated controls (e.g. 4 identical "Add to cart")
              // by the nearest container's text (the product card / row).
              let ctx = "";
              const box = e.closest('.card, .row, .field, li, tr, form, section');
              if (box) {
                const t = (box.innerText || '').trim().replace(/\\s+/g,' ');
                if (t && t !== label) ctx = t.slice(0, 50);
              }
              return ctx ? `${tag}: "${label}"  (in: ${ctx})` : `${tag}: "${label}"`;
           })""",
    )
    el_list = "\n".join(f"  - {e}" for e in elements) or "  (none)"
    return f"Visible text:\n{body}\n\nInteractive elements:\n{el_list}"


def _shot(page: Page):
    png = page.screenshot()
    vp = page.viewport_size or {"width": 1280, "height": 800}
    return png, vp["width"], vp["height"]


def run_agent(page, goal: str, start_url: str, eyes, brain, expect: str,
              max_steps: int = 14, settle_ms: int = 600) -> RunResult:
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(settle_ms)

    steps: list[StepTiming] = []
    history: list[str] = []
    t0 = time.perf_counter()
    model_time = 0.0
    run_ok = False

    for _ in range(max_steps):
        obs = observe(page)

        # --- BRAIN: decide next action ---
        tb = time.perf_counter()
        try:
            dec = brain.next_action(goal, obs, history)
        except Exception as e:
            steps.append(StepTiming("brain error", time.perf_counter() - tb, ok=False,
                                    detail=f"{type(e).__name__}: {e}"))
            break
        brain_s = time.perf_counter() - tb
        model_time += brain_s

        if dec.action == "done":
            run_ok = dec.success
            steps.append(StepTiming(f"done(success={dec.success})", brain_s, ok=dec.success,
                                    detail=dec.thought[:80]))
            break
        if dec.action not in ("click", "type") or not dec.target:
            steps.append(StepTiming(f"bad decision: {dec.action!r}", brain_s, ok=False,
                                    detail=dec.thought[:80]))
            break

        # --- EYES: localize the brain's target on the screenshot ---
        png, w, h = _shot(page)
        te = time.perf_counter()
        try:
            hit = eyes.locate(png, dec.target, w, h)
        except Exception as e:
            steps.append(StepTiming(f"eyes error on '{dec.target}'", time.perf_counter() - te,
                                    ok=False, detail=f"{type(e).__name__}: {e}"))
            break
        eye_s = time.perf_counter() - te
        model_time += eye_s

        # --- execute ---
        try:
            page.mouse.click(hit.px, hit.py)
            if dec.action == "type":
                page.keyboard.type(dec.text, delay=20)
                desc = f"type '{dec.text}' into '{dec.target}' @({hit.px},{hit.py})"
                history.append(f"typed '{dec.text}' into '{dec.target}'")
            else:
                desc = f"click '{dec.target}' @({hit.px},{hit.py})"
                history.append(f"clicked '{dec.target}'")
            page.wait_for_timeout(settle_ms)
            ok, detail = True, ""
        except Exception as e:
            ok, detail, desc = False, f"{type(e).__name__}: {e}", f"exec '{dec.target}'"

        steps.append(StepTiming(desc, brain_s + eye_s, brain_s + eye_s, ok, detail))

    # cross-check the page actually reached the goal state
    try:
        if expect.lower() in page.inner_text("body").lower():
            run_ok = run_ok or True
        else:
            run_ok = False
    except Exception:
        pass

    return RunResult(
        backend=f"{getattr(eyes,'name','eyes')}  +  {getattr(brain,'name','brain')}",
        ok=run_ok,
        total_seconds=time.perf_counter() - t0,
        localize_seconds=model_time,
        steps=steps,
        in_tokens=eyes.in_tok + brain.in_tok,
        out_tokens=eyes.out_tok + brain.out_tok,
        calls=eyes.calls + brain.calls,
        eye_in=eyes.in_tok, eye_out=eyes.out_tok, eye_calls=eyes.calls,
        brain_in=brain.in_tok, brain_out=brain.out_tok, brain_calls=brain.calls,
    )
