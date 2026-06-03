# holo-ui-test

Prototype harness for **UI testing with a computer-use model**, and a benchmark
comparing a **local Holo 3.1** grounder against **Claude** across the two roles a
UI agent needs. See `report.md` for results.

## Idea

Instead of brittle CSS selectors, describe an element in plain language ("the
blue Search button") and a vision model returns where to click. Two roles:

- **Eyes (grounding):** screenshot + target description → `(x,y)`.
- **Brain (planning):** page text + goal + history → next action.

The benchmark swaps who fills each role:

| Config | Eyes | Brain |
|---|---|---|
| **Holo + LocalModel** | Holo 3.1 35B (local) | qwen2.5:7b (local) — fully local, $0 |
| **Holo + Sonnet** | Holo 3.1 (local) | Claude Sonnet 4.6 |
| **Sonnet + Sonnet** | Claude Sonnet 4.6 | Claude Sonnet 4.6 |

## Layout

```
harness.py         Hit, RunResult (+ eyes/brain token split), Step types, run_scenario
holo.py            Holo eyes — HoloLocalizer, talks to llama-server (OpenAI API)
claude_backend.py  Sonnet eyes — ClaudeLocalizer (also legacy full-agent helper)
brain.py           planners — LocalBrain (Ollama, CPU/GPU) + SonnetBrain (Claude)
agent.py           observe(page) + run_agent(): wires eyes + brain into a loop
scenarios.py       tasks: simple-search and checkout-flow (steps + goal + expect)
demo_site/         self-contained local pages (no network jitter)
bench.py           runs the eyes+brain matrix, prints + appends to report.md
report.md          results & verdict
```

## Runtime — two model servers, two ports

```
:8080   llama.cpp llama-server   →  Holo 3.1 (eyes / grounding, on the Metal GPU)
:11434  ollama (official build)  →  brain models (qwen2.5:7b, llama3.2:3b)
```

### Holo via llama.cpp (NOT ollama)

Ollama can't run Holo: its engine doesn't implement the `qwen35moe` arch, and the
`hf.co/Hcompany/Holo-3.1-35B-A3B-GGUF` pull shortcut returns HTTP 400 on the
manifest. So we serve the cached GGUF + vision projector directly with llama.cpp:

```bash
brew install llama.cpp
B=~/.ollama/models/blobs           # blobs cached from the (failed) ollama pull
llama-server \
  -m   $B/sha256-6bfe5d1bd8e0…      # q4_k_m.gguf  (21 GB)
  --mmproj $B/sha256-d4baaa5ba48e…  # mmproj.f16.gguf (vision, 0.9 GB)
  --alias holo31 --host 127.0.0.1 --port 8080 \
  -c 4096 -ngl 999 -fa on --jinja
```

(If you don't have the blobs, `llama-server -hf Hcompany/Holo-3.1-35B-A3B-GGUF:Q4_K_M`
downloads them.)

### Brain via official ollama

The Homebrew ollama 0.30.x bottle is broken (ships only the MLX runner, no
`llama-server` → GGUF models fail). Use the official build from ollama.com.

```bash
ollama pull qwen2.5:7b        # the planner (7B q4 ≈ 4.7 GB)
```

### GPU memory (Apple Silicon)

Holo's 21 GB live on the Metal GPU. A co-resident brain there overflows the
default working-set (~27 GB on a 36 GB Mac) → Metal OOM. Either run the brain on
CPU (default here, `LocalBrain(gpu=False)` → `num_gpu=0`), or raise the limit:

```bash
sudo sysctl iogpu.wired_limit_mb=31000   # leaves ~5 GB for the OS; resets on reboot
.venv/bin/python bench.py --brain-gpu …  # then the brain can share the GPU
```

## Setup

```bash
.venv/bin/pip install openai playwright pydantic anthropic
.venv/bin/python -m playwright install chromium
echo 'ANTHROPIC_API_KEY=sk-ant-…' >> .env     # auto-loaded; needed for Sonnet roles
```

## Run

```bash
# all three configs, watch the browser
.venv/bin/python bench.py --scenario checkout-flow --headed

# just the fully-local one
.venv/bin/python bench.py --only "Holo + LocalModel" --brain-model qwen2.5:7b

# local brain on the GPU (after raising the wired limit)
.venv/bin/python bench.py --only "Holo + LocalModel" --brain-gpu
```

`Total` = end-to-end wall time. `Model-time` = time in the models. Token columns
are split **eyes vs brain** — the screenshot dominates the eyes side, so the
fully-local config is the cheapest by tokens and $0 by cost.

## Gotchas learned the hard way

- Holo coordinates are a **0..1000 grid** relative to the screenshot; scale
  against the exact viewport (1280×800). Claude eyes use **actual pixels** (its
  native format) — forcing the 0..1000 grid onto Claude hurts its accuracy.
- The brain must **disambiguate repeated controls** ("Add to cart" ×4). The
  observation tags each element with its container text (`(in: Mechanical
  Keyboard $89)`) so the brain can say "Add to cart for Mechanical Keyboard".
- Parse model JSON with `JSONDecoder().raw_decode` from the first `{` — both
  Claude and small local models append prose after the object.
- A 3B brain is too weak (loops, emits `click|type`); 7B (qwen2.5) is the floor
  that plans this flow reliably.
```
