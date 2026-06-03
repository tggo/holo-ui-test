"""
UI-test harness shared by the localizer backends (Holo / Claude).

A Scenario is a flat list of Steps. The harness drives a Playwright page and,
whenever a step needs to find something on screen, it calls the injected
`Localizer`. That's the only thing that differs between backend A (local Holo)
and backend B (Claude vision) — the steps are identical, so the comparison is
apples-to-apples.

Every localize call is timed; run_scenario returns a RunResult with per-step
and total timings plus pass/fail.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, Union

from playwright.sync_api import Page


@dataclass
class Hit:
    """A localized element, normalized (0..1000) and absolute pixels."""
    nx: int
    ny: int
    px: int
    py: int


class Localizer(Protocol):
    name: str

    def locate(self, png_bytes: bytes, target: str, width: int, height: int) -> Hit:
        """Return where `target` is in the screenshot."""
        ...


# ---- Steps -----------------------------------------------------------------
# A step is (kind, payload). Kept deliberately tiny — enough to express a real
# login/search flow without turning into a DSL.

@dataclass
class Goto:
    url: str

@dataclass
class Click:
    target: str          # natural-language description handed to the Localizer

@dataclass
class Type:
    target: str
    text: str

@dataclass
class Assert:
    """Pass if `must_contain` is present in the page's visible text."""
    must_contain: str

Step = Union[Goto, Click, Type, Assert]


@dataclass
class StepTiming:
    desc: str
    seconds: float
    localize_seconds: float = 0.0   # time spent in the model, if any
    ok: bool = True
    detail: str = ""


@dataclass
class RunResult:
    backend: str
    ok: bool
    total_seconds: float
    localize_seconds: float          # summed model time only
    steps: list[StepTiming] = field(default_factory=list)
    in_tokens: int = 0               # prompt tokens (images dominate)
    out_tokens: int = 0
    calls: int = 0                   # model round-trips
    # role breakdown (eyes = grounding, brain = planning)
    eye_in: int = 0
    eye_out: int = 0
    eye_calls: int = 0
    brain_in: int = 0
    brain_out: int = 0
    brain_calls: int = 0

    @property
    def tokens(self) -> int:
        return self.in_tokens + self.out_tokens

    def summary(self) -> str:
        flag = "PASS" if self.ok else "FAIL"
        return (f"[{flag}] {self.backend:<26} "
                f"total={self.total_seconds:6.2f}s  "
                f"model={self.localize_seconds:6.2f}s  "
                f"calls={self.calls:2d}  "
                f"tok={self.tokens:6d} (eyes {self.eye_in+self.eye_out}/brain {self.brain_in+self.brain_out})")


def _screenshot(page: Page) -> tuple[bytes, int, int]:
    png = page.screenshot()
    vp = page.viewport_size or {"width": 1280, "height": 800}
    return png, vp["width"], vp["height"]


def run_scenario(page: Page, scenario: list[Step], loc: Localizer,
                 settle_ms: int = 600) -> RunResult:
    steps: list[StepTiming] = []
    model_total = 0.0
    run_ok = True
    t0 = time.perf_counter()

    for step in scenario:
        s_start = time.perf_counter()
        loc_s = 0.0
        ok = True
        detail = ""
        try:
            if isinstance(step, Goto):
                page.goto(step.url, wait_until="domcontentloaded")
                desc = f"goto {step.url}"

            elif isinstance(step, Click):
                png, w, h = _screenshot(page)
                m0 = time.perf_counter()
                hit = loc.locate(png, step.target, w, h)
                loc_s = time.perf_counter() - m0
                page.mouse.click(hit.px, hit.py)
                desc = f"click '{step.target}' @({hit.px},{hit.py})"

            elif isinstance(step, Type):
                png, w, h = _screenshot(page)
                m0 = time.perf_counter()
                hit = loc.locate(png, step.target, w, h)
                loc_s = time.perf_counter() - m0
                page.mouse.click(hit.px, hit.py)
                page.keyboard.type(step.text, delay=20)
                desc = f"type into '{step.target}' @({hit.px},{hit.py})"

            elif isinstance(step, Assert):
                body = page.inner_text("body")
                ok = step.must_contain.lower() in body.lower()
                detail = "" if ok else f"missing: {step.must_contain!r}"
                desc = f"assert contains '{step.must_contain}'"
            else:
                raise ValueError(f"unknown step: {step!r}")

            page.wait_for_timeout(settle_ms)
        except Exception as e:  # a backend miss or a flaky page shouldn't crash the bench
            ok = False
            detail = f"{type(e).__name__}: {e}"
            desc = f"{type(step).__name__} (errored)"

        dt = time.perf_counter() - s_start
        model_total += loc_s
        run_ok = run_ok and ok
        steps.append(StepTiming(desc, dt, loc_s, ok, detail))

    return RunResult(
        backend=loc.name,
        ok=run_ok,
        total_seconds=time.perf_counter() - t0,
        localize_seconds=model_total,
        steps=steps,
        in_tokens=getattr(loc, "in_tok", 0),
        out_tokens=getattr(loc, "out_tok", 0),
        calls=getattr(loc, "calls", 0),
    )
