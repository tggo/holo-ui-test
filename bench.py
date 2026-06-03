"""
Benchmark — the eyes+brain matrix. Same goal, same page; we swap who does the
GROUNDING (eyes) and who does the PLANNING (brain):

  1. Holo + LocalModel   eyes=Holo (llama.cpp)   brain=light local model (Ollama)   → fully local, $0
  2. Holo + Sonnet       eyes=Holo               brain=Claude Sonnet 4.6
  3. Sonnet + Sonnet     eyes=Claude Sonnet 4.6  brain=Claude Sonnet 4.6

Prints a timing + token comparison (split eyes vs brain) and appends to report.md.

Usage:
  .venv/bin/python bench.py                       # all three configs
  .venv/bin/python bench.py --only "Holo + LocalModel" --headed
  .venv/bin/python bench.py --brain-model qwen2.5:7b --loc-model claude-sonnet-4-6
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path


def _load_dotenv():
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

from playwright.sync_api import sync_playwright

import scenarios
from agent import run_agent

REPORT = Path(__file__).parent / "report.md"


def _new_page(pw, headed):
    browser = pw.chromium.launch(headless=not headed)
    page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
    page.on("dialog", lambda d: d.accept())
    return browser, page


def make_configs(brain_model, sonnet_model, brain_gpu=False):
    """Each config returns (label, lambda -> (eyes, brain), needs_key)."""
    def holo():
        from holo import HoloLocalizer
        return HoloLocalizer()

    def sonnet_eyes():
        from claude_backend import ClaudeLocalizer
        return ClaudeLocalizer(sonnet_model)

    def local_brain():
        from brain import LocalBrain
        return LocalBrain(brain_model, gpu=brain_gpu)

    def sonnet_brain():
        from brain import SonnetBrain
        return SonnetBrain(sonnet_model)

    return [
        (f"Holo + LocalModel ({brain_model})", lambda: (holo(), local_brain()), False),
        ("Holo + Sonnet",                      lambda: (holo(), sonnet_brain()), True),
        ("Sonnet + Sonnet",                    lambda: (sonnet_eyes(), sonnet_brain()), True),
    ]


def write_report(scn, rows, brain_model, sonnet_model):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        f"\n## {scn.name} (eyes+brain) — {stamp}\n",
        f"Page: `{Path(scn.url).name}` · local brain: `{brain_model}` · cloud: `{sonnet_model}`\n",
        "| Config | Result | Total s | Model s | Steps | Eyes tok | Brain tok | Total tok |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for label, r in rows:
        L.append(f"| {label} | {'✅' if r.ok else '❌'} | {r.total_seconds:.1f} | "
                 f"{r.localize_seconds:.1f} | {r.eye_calls} | {r.eye_in+r.eye_out} | "
                 f"{r.brain_in+r.brain_out} | {r.tokens} |")
    for label, r in rows:
        L.append(f"\n<details><summary>{label} — steps</summary>\n")
        for st in r.steps:
            tag = "ok" if st.ok else "ERR"
            d = f" — {st.detail}" if st.detail else ""
            L.append(f"- `[{tag}]` {st.seconds:.2f}s — {st.desc}{d}")
        L.append("\n</details>")
    head = REPORT.read_text() if REPORT.exists() else "# Holo 3.1 vs Claude — UI-test benchmark\n"
    REPORT.write_text(head + "\n".join(L) + "\n")
    print(f"\n→ appended to {REPORT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=scenarios.DEFAULT, choices=list(scenarios.ALL))
    ap.add_argument("--only", action="append", help="config label substring (repeatable)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--brain-model", default="llama3.2:3b")
    ap.add_argument("--loc-model", default="claude-sonnet-4-6")
    ap.add_argument("--brain-gpu", action="store_true",
                    help="run the local brain on GPU (needs raised iogpu.wired_limit_mb)")
    args = ap.parse_args()

    scn = scenarios.ALL[args.scenario]
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    configs = make_configs(args.brain_model, args.loc_model, args.brain_gpu)
    if args.only:
        configs = [c for c in configs if any(o.lower() in c[0].lower() for o in args.only)]

    rows = []
    with sync_playwright() as pw:
        for label, build, needs_key in configs:
            if needs_key and not have_key:
                print(f"-- skip '{label}' (no ANTHROPIC_API_KEY)", file=sys.stderr)
                continue
            print(f">> {label} …", file=sys.stderr)
            browser, page = _new_page(pw, args.headed)
            try:
                eyes, brain = build()
                r = run_agent(page, scn.goal, scn.url, eyes, brain, scn.expect)
                rows.append((label, r))
            except Exception as e:
                print(f"   '{label}' failed: {type(e).__name__}: {e}", file=sys.stderr)
            finally:
                browser.close()

    print("\n" + "=" * 80)
    print(f"RESULTS — scenario '{scn.name}', eyes + brain matrix")
    print("=" * 80)
    for label, r in rows:
        print(f"{label:34} {r.summary()}")
    if rows:
        write_report(scn, rows, args.brain_model, args.loc_model)


if __name__ == "__main__":
    main()
