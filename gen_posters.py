#!/usr/bin/env python3
"""
Generate 3 poster concepts via gpt-image-2 (same method as projects/anselm-korr).
Reuses the OPENAI_API_KEY from the anselm-korr project's .env.
3:2 landscape (1536x1024), quality high. Saves to ./posters/.
"""
import base64, json, sys, time, urllib.error, urllib.request
from pathlib import Path

KEY_ENV = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/obsidian/bigComp/projects/anselm-korr/.env"
OUT = Path(__file__).resolve().parent / "posters"


def api_key() -> str:
    for line in KEY_ENV.read_text().splitlines():
        if line.strip().startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("OPENAI_API_KEY not found")


CONCEPTS = {
    "1-lights-out-lab": (
        "3:2 cinematic sci-fi poster, highly detailed. A dark lights-out software QA "
        "lab at night. Center: one local aluminium mini-tower with a giant translucent "
        "holographic green EYE iris hovering over its screen, volumetric scan-beams "
        "sweeping a curved wall of dozens of glowing browser windows (login and "
        "checkout forms) where ghost cursors click buttons and tick green PASS marks. "
        "Wired beside it, an amber glass BRAIN orb pulses. Foreground: empty office "
        "chairs, cold coffee, an open 'QA AUTOMATION HANDBOOK', and a hoodie hacker "
        "silhouette dissolving into pixels as he walks out, defeated. Background: faint "
        "code rain, (x,y) coordinate grids, CRT scanlines, red FAIL and green PASS "
        "tags. Near-black background with phosphor green, hazard amber and cyan accents, "
        "risograph grain. Bold condensed headline at top reading 'QA, AUTOMATED — "
        "LOCALLY'. Small mono subtitle 'the machine that tests itself'. "
        "Blade-Runner-meets-blueprint, dense intricate detail, high contrast."
    ),
    "2-eyes-and-brain": (
        "3:2 ultra-detailed character poster. A powerful friendly robot QA agent built "
        "from two glowing modules: a round camera-EYE head emitting green grounding "
        "light, and a translucent amber glass BRAIN core in its chest laced with neural "
        "filaments. It sits amid floating holographic browser panels, reaching with many "
        "slender mechanical fingers to click buttons and fill checkout forms, ticking "
        "green PASS marks. Around it: cute defeated software-BUG insect-robots on their "
        "backs, sticky notes reading 'FLAKY', 'RETRY', 'FIXED', a tiny hoodie hacker "
        "waving a white flag, a humming GPU brick tagged 'LOCAL · $0'. Tons of "
        "micro-detail: tiny code, cursors, coordinate ticks. Near-black background with "
        "phosphor green, amber and cyan, soft rim light, glossy yet maximally dense. "
        "Headline arc reading 'EYES + BRAIN'. Mono tag 'it sees the pixel, it plans the "
        "click'."
    ),
    "3-replace-night-shift": (
        "3:2 bold constructivist WPA propaganda poster, dramatic diagonal composition. "
        "A colossal heroic robot with a single glowing green camera-EYE and an exposed "
        "amber BRAIN strides forward holding a giant glowing mouse-cursor aloft like a "
        "torch, trampling a heap of shattered 'QA AUTOMATION' gears, broken clockwork "
        "and snapped chains; a small hoodie hacker flees. Behind: a sunburst of hundreds "
        "of tiny browser windows and green PASS checkmarks. Heavy halftone, screen-print "
        "grain, hard limited palette: black, phosphor green, hazard amber, signal red, "
        "off-white paper. Huge bold slab slogan across the top reading 'REPLACE THE "
        "NIGHT SHIFT'. Smaller banner 'LOCAL AGENTS TEST WHILE YOU SLEEP — $0'. Stencil "
        "mono fine print, propaganda energy, dense iconographic background, vintage "
        "ink-on-newsprint feel."
    ),
}


def gen(slug: str, prompt: str, key: str):
    body = json.dumps({"model": "gpt-image-2", "prompt": prompt,
                       "n": 1, "size": "1536x1024", "quality": "high"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/generations",
        data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    print(f"[posters] generating {slug} ...", flush=True)
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.load(resp)
    if "error" in data:
        print(f"  ! {data['error']}"); return None
    OUT.mkdir(exist_ok=True)
    out = OUT / f"{slug}.png"
    out.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
    print(f"  saved {out}")
    return out


if __name__ == "__main__":
    key = api_key()
    only = sys.argv[1:] or list(CONCEPTS)
    for slug in only:
        p = CONCEPTS.get(slug) or CONCEPTS[[k for k in CONCEPTS if slug in k][0]]
        try:
            gen(slug if slug in CONCEPTS else [k for k in CONCEPTS if slug in k][0], p, key)
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
