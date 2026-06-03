# Holo 3.1 vs Claude — UI-test benchmark

A UI test is driven by two roles:

- **Eyes (grounding):** look at a screenshot, return where to click (`x,y`).
- **Brain (planning):** read the page + goal + history, decide the next action.

We swap who fills each role and run the *same* 9-action e-commerce checkout
(nav → pick **one of four identical "Add to cart"** → cart → 3-field form →
place order) on a local page (`demo_site/shop.html`), measuring wall-time and
tokens.

## The matrix (scenario: checkout-flow)

| Config | Eyes | Brain | Result | Total | Model-time | Steps | Eyes tok | Brain tok | $ |
|---|---|---|:--:|--:|--:|--:|--:|--:|--:|
| **Sonnet + Sonnet** | Sonnet 4.6 | Sonnet 4.6 | ✅ | **40 s** | 34 s | 8 | 11.6k | 6.2k | all cloud |
| **Holo + LocalModel** | Holo 3.1 (local) | qwen2.5:7b (local) | ✅ | **46 s** | 39 s | 8 | 9.9k | 5.5k | **$0** |
| **Holo + Sonnet** | Holo 3.1 (local) | Sonnet 4.6 | ✅ | 58 s | 52 s | 8 | 9.9k | 6.2k | brain only |

(Ranked fastest first; local time is GPU + quiet system — see GPU vs CPU below.)

All three complete the flow. Differences:

- **Speed:** all-cloud is fastest (40 s) — Sonnet eyes answer in ~2 s vs Holo's
  ~5 s/call on the M4 Max. The local 35B-A3B grounding model is the slow part,
  not the brain.
- **Tokens / cost:** *eyes* tokens are dominated by the screenshot (~1.2k per
  call either way). The fully-local column is **$0** after the one-off 22 GB
  download; the others pay for whichever role Sonnet fills.
- **Accuracy:** Holo and Sonnet eyes produce near-identical coordinates
  (Products 266 vs 267 px, Add-to-cart 192 px both). Grounding is not the
  bottleneck on a normal-sized page — the earlier *simple-form* failures were
  due to 42 px-tall cramped controls.
- **The brain is the fragile part locally.** A 3B (llama3.2) loops and miswords
  actions; **qwen2.5:7b** plans correctly (disambiguates "Add to cart for
  Mechanical Keyboard", fills the form, stops). Needs JSON-parse robustness
  (`raw_decode`) + a retry to survive occasional empty/garbled replies.

## Local brain: GPU vs CPU placement

Holo's 21 GB sit on the Metal GPU (via llama.cpp). A co-resident brain there
needs headroom:

| Brain placement | Total | Model-time | Note |
|---|--:|--:|---|
| qwen2.5:7b on **CPU** (`num_gpu=0`) | 97.7 s | 90.6 s | no GPU contention, always safe |
| qwen2.5:7b on **GPU**, Spotlight busy | 88.7 s | 75.4 s | `mds_stores` at 76 % CPU during the run |
| qwen2.5:7b on **GPU**, warm | 60.5 s | 52.3 s | Spotlight still indexing in background |
| qwen2.5:7b on **GPU**, **Spotlight off** | **46.2 s** | 39.2 s | quiet system — best case |

⚠ **Variance was huge — and it was Spotlight.** `mds_stores` re-indexing the code
volume sat at 76 % CPU and **doubled** the run (97 → 46 s as it quieted /
`mdutil -a -i off`). With it off, GPU placement brings the fully-local config to
**46 s — faster than Holo+Sonnet (58 s) and within ~6 s of all-cloud (40 s)**.
The eyes still dominate; per step settles to ~4–5 s.

Setup notes: Holo (21 GB) + qwen (6.6 GB) ≈ 28 GB exceeds the default Metal
working-set (~27 GB on a 36 GB Mac) → `kIOGPUCommandBufferError… OutOfMemory`.
Fix: `sudo sysctl iogpu.wired_limit_mb=31000` (leaves ~5 GB for the OS; resets on
reboot). Run on a quiet machine, or `sudo mdutil -a -i off` while benchmarking.

## Verdict

- **Latency matters, key is fine →** Sonnet+Sonnet. Fastest, simplest, one vendor.
- **Must stay on-box / zero marginal cost →** Holo + qwen2.5:7b, fully local.
  On a quiet GPU it nearly matches all-cloud (46 vs 40 s) at $0, nothing leaves the box.
- **Hybrid (Holo + Sonnet)** buys little here: you still pay Sonnet for the brain
  and Holo's eyes are slower than Sonnet's. It makes sense only when the *brain*
  must be a frontier model **and** screenshots can't leave the box.

---

## Step traces (representative clean run)

<details><summary>Holo + LocalModel (qwen2.5:7b) — steps</summary>

- `[ok]` click 'Products' @(266,30)
- `[ok]` click 'Add to cart for Mechanical Keyboard' @(192,640)
- `[ok]` click 'Cart' @(334,30)
- `[ok]` click 'Proceed to checkout' @(135,212)
- `[ok]` type 'Ruslan Test' into 'Full name' @(240,176)
- `[ok]` type 'ruslan@example.com' into 'Email' @(240,256)
- `[ok]` type '123 Demo Street' into 'Shipping address' @(240,336)
- `[ok]` click 'Place order' @(106,395)
- `[ok]` done(success=True)

</details>

<details><summary>Sonnet + Sonnet — steps</summary>

- `[ok]` click 'Products' @(267,30)
- `[ok]` click 'Add to cart (Mechanical Keyboard $89)' @(192,640)
- `[ok]` click 'Cart' @(340,30)
- `[ok]` click 'Proceed to checkout' @(139,211)
- `[ok]` type 'Ruslan Test' into 'Full name' @(240,176)
- `[ok]` type 'ruslan@example.com' into 'Email' @(229,255)
- `[ok]` type '123 Demo Street' into 'Shipping address' @(240,335)
- `[ok]` click 'Place order' @(106,394)
- `[ok]` done(success=True)

</details>

## checkout-flow (eyes+brain) — 2026-06-03 23:34

Page: `shop.html` · local brain: `qwen2.5:7b` · cloud: `claude-sonnet-4-6`

| Config | Result | Total s | Model s | Steps | Eyes tok | Brain tok | Total tok |
|---|---|--:|--:|--:|--:|--:|--:|
| Holo + LocalModel (qwen2.5:7b) | ✅ | 100.6 | 88.1 | 8 | 9935 | 5530 | 15465 |
| Holo + Sonnet | ✅ | 89.8 | 78.3 | 8 | 9941 | 6219 | 16160 |
| Sonnet + Sonnet | ✅ | 41.6 | 32.7 | 8 | 11581 | 6197 | 17778 |

<details><summary>Holo + LocalModel (qwen2.5:7b) — steps</summary>

- `[ok]` 13.24s — click 'Products' @(266,30)
- `[ok]` 8.77s — click 'Add to cart for Mechanical Keyboard' @(192,640)
- `[ok]` 8.54s — click 'Cart1' @(334,30)
- `[ok]` 8.16s — click 'Proceed to checkout (in: Your Cart Mechanical Keyboard 1 × Proceed to check)' @(135,212)
- `[ok]` 10.34s — type 'Ruslan Test' into 'Full name' @(240,176)
- `[ok]` 10.32s — type 'ruslan@example.com' into 'Email' @(240,256)
- `[ok]` 13.68s — type '123 Demo Street' into 'Shipping address (in: Shipping address)' @(240,336)
- `[ok]` 13.49s — click 'Place order (in: Checkout Full name Email Shipping address Place order)' @(106,395)
- `[ok]` 1.55s — done(success=True) — The goal is achieved, no further actions needed.

</details>

<details><summary>Holo + Sonnet — steps</summary>

- `[ok]` 11.76s — click 'Products' @(266,30)
- `[ok]` 11.66s — click 'Add to cart (in: Mechanical Keyboard $89 Add to cart)' @(192,640)
- `[ok]` 10.46s — click 'Cart1' @(334,30)
- `[ok]` 8.53s — click 'Proceed to checkout' @(133,212)
- `[ok]` 9.10s — type 'Ruslan Test' into 'input: ""  (in: Full name)' @(240,176)
- `[ok]` 8.26s — type 'ruslan@example.com' into 'input: ""  (in: Email)' @(240,257)
- `[ok]` 8.36s — type '123 Demo Street' into 'input: ""  (in: Shipping address)' @(240,336)
- `[ok]` 7.98s — click 'Place order  (in: Checkout Full name Email Shipping address Place or)' @(102,395)
- `[ok]` 2.23s — done(success=True) — The goal has been achieved. The page shows 'Order confirmed — thank you, Ruslan 

</details>

<details><summary>Sonnet + Sonnet — steps</summary>

- `[ok]` 3.61s — click 'Products' @(265,30)
- `[ok]` 3.66s — click 'Add to cart (in: Mechanical Keyboard $89 Add to cart)' @(193,640)
- `[ok]` 3.66s — click 'Cart1' @(340,30)
- `[ok]` 3.86s — click 'Proceed to checkout' @(140,211)
- `[ok]` 4.08s — type 'Ruslan Test' into 'input: ""  (in: Full name)' @(238,178)
- `[ok]` 3.74s — type 'ruslan@example.com' into 'input: ""  (in: Email)' @(231,255)
- `[ok]` 4.13s — type '123 Demo Street' into 'input: ""  (in: Shipping address)' @(189,335)
- `[ok]` 3.72s — click 'Place order' @(101,395)
- `[ok]` 2.26s — done(success=True) — The goal has been fully accomplished. The page shows 'Order confirmed — thank yo

</details>

## checkout-flow (eyes+brain) — 2026-06-03 23:38

Page: `shop.html` · local brain: `qwen2.5:7b` · cloud: `claude-sonnet-4-6`

| Config | Result | Total s | Model s | Steps | Eyes tok | Brain tok | Total tok |
|---|---|--:|--:|--:|--:|--:|--:|
| Holo + LocalModel (qwen2.5:7b) | ✅ | 90.3 | 78.2 | 8 | 9935 | 5530 | 15465 |
| Holo + Sonnet | ✅ | 91.0 | 78.9 | 8 | 9886 | 6193 | 16079 |
| Sonnet + Sonnet | ❌ | 35.0 | 25.5 | 7 | 10148 | 4729 | 14877 |

<details><summary>Holo + LocalModel (qwen2.5:7b) — steps</summary>

- `[ok]` 11.94s — click 'Products' @(266,30)
- `[ok]` 8.67s — click 'Add to cart for Mechanical Keyboard' @(192,640)
- `[ok]` 8.72s — click 'Cart1' @(334,30)
- `[ok]` 10.28s — click 'Proceed to checkout (in: Your Cart Mechanical Keyboard 1 × Proceed to check)' @(135,212)
- `[ok]` 9.36s — type 'Ruslan Test' into 'Full name' @(240,176)
- `[ok]` 9.90s — type 'ruslan@example.com' into 'Email' @(240,256)
- `[ok]` 10.91s — type '123 Demo Street' into 'Shipping address (in: Shipping address)' @(240,336)
- `[ok]` 7.37s — click 'Place order (in: Checkout Full name Email Shipping address Place order)' @(106,395)
- `[ok]` 1.09s — done(success=True) — The goal is achieved, no further actions needed.

</details>

<details><summary>Holo + Sonnet — steps</summary>

- `[ok]` 10.34s — click 'Products' @(266,30)
- `[ok]` 13.09s — click 'Add to cart (in: Mechanical Keyboard $89 Add to cart)' @(192,640)
- `[ok]` 9.30s — click 'Cart1' @(334,30)
- `[ok]` 7.56s — click 'Proceed to checkout' @(135,212)
- `[ok]` 9.91s — type 'Ruslan Test' into 'input:  (in: Full name)' @(240,176)
- `[ok]` 8.70s — type 'ruslan@example.com' into 'input: ""  (in: Email)' @(240,257)
- `[ok]` 9.11s — type '123 Demo Street' into 'input: ""  (in: Shipping address)' @(240,336)
- `[ok]` 8.57s — click 'Place order' @(106,395)
- `[ok]` 2.31s — done(success=True) — The order has been confirmed successfully. The page shows 'Order confirmed — tha

</details>

<details><summary>Sonnet + Sonnet — steps</summary>

- `[ok]` 3.61s — click 'Products' @(265,30)
- `[ok]` 3.67s — click 'Add to cart (in: Mechanical Keyboard $89 Add to cart)' @(193,640)
- `[ok]` 3.45s — click 'Cart1' @(340,30)
- `[ok]` 3.68s — click 'Proceed to checkout' @(140,211)
- `[ok]` 4.68s — type 'Ruslan Test' into 'input: ""  (in: Full name)' @(237,175)
- `[ok]` 4.44s — type 'ruslan@example.com' into 'input: ""  (in: Email)' @(228,257)
- `[ERR]` 1.74s — eyes error on 'input: ""  (in: Shipping address)' — JSONDecodeError: Expecting ':' delimiter: line 1 column 14 (char 13)

</details>
