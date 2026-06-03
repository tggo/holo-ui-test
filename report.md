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
| **Holo + LocalModel** | Holo 3.1 (local) | qwen2.5:7b (local) | ✅ | 88–98 s | 75–91 s | 8 | 9.9k | 5.5k | **$0** |
| **Holo + Sonnet** | Holo 3.1 (local) | Sonnet 4.6 | ✅ | 58 s | 52 s | 8 | 9.9k | 6.2k | brain only |
| **Sonnet + Sonnet** | Sonnet 4.6 | Sonnet 4.6 | ✅ | **40 s** | 34 s | 8 | 11.6k | 6.2k | all cloud |

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
  Slower (~90 s) but $0 and nothing leaves the machine.
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
