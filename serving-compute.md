# Serving compute & cost estimate

Reference notes on what it costs to put this project online somewhere people can try it, as a **low-traffic public demo** — distinct from `compute-requirements.md`, which sizes hardware for running the full local-Ollama stack yourself. This doc assumes no dedicated audience: occasional, bursty visitors, not sustained concurrent load.

## Why this isn't a GPU-sizing problem

Serving concurrent LLM traffic is fundamentally a queueing problem: `concurrency ≈ arrival rate × time-in-system` (Little's Law), and once utilization (`ρ = arrival rate / service rate`) climbs, wait time blows up nonlinearly rather than degrading gracefully (`W_q = ρ / (μ(1 - ρ))`, the standard M/M/1 result). That math matters when you're provisioning a GPU to survive real concurrent load.

It doesn't apply here. At near-zero expected traffic, `ρ` stays close to 0 almost all the time — there's essentially never a queue to reason about. So the decision that actually matters isn't throughput capacity, it's **idle cost, cold-start latency, and operational simplicity**.

## Architecture for the public demo

Keep the LangGraph structure exactly as-is (`graph.py` doesn't change) and swap only the collaborators the graph calls out to, via the interfaces the codebase already defines:

| Piece | Local/dev | Public demo | Why |
|---|---|---|---|
| Narrator (`llm.py`'s `Narrator` protocol) | `OllamaNarrator` | New `AnthropicNarrator` hitting the Claude API | No GPU to provision or keep warm; pay per token instead |
| Embedder (`retrieval.py`'s `Embedder` protocol) | `OllamaEmbedder` | Stays **local, CPU-only** (a small embedding model) | Lore corpus is a few markdown files; turn-summary embeddings are short text. Cheap enough on CPU that it doesn't need a hosted API or GPU at all |
| Checkpointer | `SqliteSaver` | Same — `SqliteSaver` | Fine for a single instance at demo scale. Only becomes a bottleneck if you horizontally scale to multiple replicas (not needed here) |
| Serving layer | `uvicorn` locally | Same FastAPI app (`api.py`), deployed | Already exists — `GameServer` + `InterruptActionProvider` handle turn-by-turn HTTP already |

Because `Narrator`/`Embedder` are Protocols, this is a new ~20-line class each, not a graph rewrite.

## LLM cost (Claude API)

Per turn, the narration call is small: `DM_SYSTEM_PROMPT` caps output at "2-4 sentences," and the prompt is just game state plus a few short retrieved-lore chunks — roughly 400 input tokens, 120 output tokens. Autonomous/persona mode adds a similarly small player-agent call.

**Claude Haiku 4.5** ($1 / $5 per million input/output tokens) is the right default — this is a small, structured task, not a reasoning-heavy one. Claude Sonnet 5 ($3 / $15, or $2 / $10 introductory through 2026-08-31) is the upgrade if you want noticeably richer prose.

| | Haiku 4.5 | Sonnet 5 |
|---|---|---|
| Per turn | ~$0.001 | ~$0.002–0.003 |
| Per 20-turn playthrough | ~$0.02 | ~$0.04–0.06 |
| 100 playthroughs/month (generous for this project) | ~$2 | ~$4–6 |
| 1,000 playthroughs/month (very generous) | ~$20 | ~$40–60 |

Realistic spend for a project with no dedicated audience: **cents to a couple dollars a month.**

## Hosting cost (Render)

| Plan | Price | Specs | Notes |
|---|---|---|---|
| Free web service | $0/mo | 512MB RAM, 0.1 CPU | Spins down after 15 min of no traffic; ~1 min cold-start on the next request. **Cannot attach a persistent disk** — any local filesystem writes (the SQLite checkpoint DB, the Chroma event store) reset on every spin-down, restart, or redeploy |
| Starter web service | $7/mo | 512MB RAM, 0.5 CPU | Always-on, no cold start |
| Persistent disk | $0.25/GB/month | — | Paid plans only. A couple GB comfortably covers the SQLite save DB + Chroma corpus |
| Workspace plan | Hobby tier is free | — | Covers a personal project; no need for the $25/mo Pro workspace tier here |

The free tier's no-persistent-disk limitation is the real tradeoff to know about: on free, every save-game and every turn of "remembered" lore/event history (`remember_node` writing into Chroma) evaporates the moment the instance spins down from inactivity — which, on a demo nobody's continuously hitting, is often. If save/resume across visits matters, that's what the $7 Starter + disk buys you.

## Total monthly estimate

| Setup | Render | Claude API | Total | Tradeoff |
|---|---|---|---|---|
| Free tier, ephemeral saves | $0 | ~$0–2 | **~$0–2/mo** | Cold start (~1 min) on first hit after idle; saves/lore memory don't survive a spin-down |
| Starter + 2GB disk, persistent | $7 + $0.50 | ~$0–5 | **~$8–13/mo** | Always-on, no cold start, saves and lore memory persist across visits |

Either way, this is a hobby-project cost, not a provisioning problem — which is the point of skipping the GPU-sizing exercise entirely for this deployment.

## Still open (not a cost question)

These don't change the numbers above but are worth calling out as gaps if this goes further:

- **No auth**, but `POST /games` is now capped per client IP (`X-Forwarded-For`, falling back to the socket address) at `DAILY_RUN_LIMIT` (default 2) new games/day — see `rate_limit.py`. Combined with the existing 40-turn-per-run cap, that bounds worst-case daily LLM/embedding cost per visitor even with no login.
- **Postgres checkpointer** (`langgraph-checkpoint-postgres`) is only needed if you outgrow a single Render instance — not a concern at this scale.
- **Tracing/observability** (Langfuse/LangSmith, listed as a stretch goal in the project plan) still isn't wired into the code — not a cost item, but worth having before debugging a live deploy blind.

## Sources

- [Render Pricing](https://render.com/pricing)
- [Render Docs — Deploy for Free](https://render.com/docs/free)
- [Render Docs — FAQ](https://render.com/docs/faq)
