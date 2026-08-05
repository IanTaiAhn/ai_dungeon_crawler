# Running it locally

Short answer: **no, `uv sync` alone is not enough.** This project is Ollama-powered — every mode (human play, autonomous persona, eval, API, MCP) talks to a locally running Ollama server for narration, decisions, and embeddings. `uv sync` gets the Python side installed; you still need Ollama installed, running, and holding the right models pulled before anything that actually calls a model will work.

The one thing that *doesn't* need Ollama: `uv run pytest -q`. The whole test suite runs against mocks (`MockNarrator`, `MockEmbedder`, `MockJudge`, `ScriptedActionProvider`), by design, so you can verify the code works before touching Ollama at all.

## 1. Prerequisites

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/getting-started/installation/).
- **[Ollama](https://ollama.com/download)** installed and running (`ollama serve`, or just open the desktop app - it runs a local server on `localhost:11434`).
- Enough RAM/disk/VRAM for the models below - see `compute-requirements.md` for the full breakdown (short version: ~15-20GB disk, 16GB RAM minimum, a GPU is nice-to-have not required).

Verify Ollama is actually up before going further:

```bash
ollama list          # should run without error, even if empty
curl -s localhost:11434
```

## 2. Install the project

```bash
git clone <this repo>
cd ai_dungeon_crawler
uv sync
```

This installs `dungeon-crawler` and its dependencies (LangGraph, LangChain's Ollama integrations, Chroma, FastAPI, the MCP SDK, pytest) into `.venv/`.

## 3. Pull the models

The CLI's defaults match what `compute-requirements.md` recommends. Pull all three:

```bash
ollama pull qwen2.5:7b        # DM narrator (--model default)
ollama pull llama3.2:3b       # player agent (--player-model default)
ollama pull nomic-embed-text  # lore embeddings (--embedding-model default)
```

If your machine is CPU-only or short on RAM, swap in something smaller (`qwen2.5:3b`, `llama3.2:1b`, etc.) via the `--model`/`--player-model`/`--embedding-model` flags everywhere below - nothing is hardcoded to these exact names. The project plan flags player-agent model size as an open question worth benchmarking: if its decisions come out incoherent, try a smaller quant before blaming the code.

## 4. Play it yourself

```bash
uv run dungeon-crawler
```

You'll get the DM's opening narration, then a `>` prompt. Type free-text commands - the parser understands things like:

```
go north / go south / go east / go west
attack goblin
take rusty sword
use torch
talk to goblin
inspect
flee
wait
```

**Save/resume**: every turn is checkpointed to `dungeon_crawler.sqlite` (a real save, not just in-memory) under a "thread" name. Just re-run the same command to resume where you left off:

```bash
uv run dungeon-crawler --thread-id my-run-1
```

Different `--thread-id` values are independent save slots. Useful flags:

| Flag | Default | What it does |
|---|---|---|
| `--thread-id` | `default` | Save slot to start or resume |
| `--db` | `dungeon_crawler.sqlite` | Save-game database path |
| `--model` | `qwen2.5:7b` | DM narrator model |
| `--embedding-model` | `nomic-embed-text` | Lore embedding model |
| `--lore-dir` | `lore/` | Lore corpus directory |
| `--chroma-dir` | `dungeon_crawler_chroma/` | Persistent lore/event vector store |
| `--checkin-every` | `None` | (Human mode only) Pause for approval before combat and every N turns |

## 5. Watch an autonomous persona play

```bash
uv run dungeon-crawler --persona personas/cautious_scout.json
```

Three example personas ship in `personas/`: `cautious_scout.json`, `greedy_looter.json`, `honorable_warden.json`. Each is a small JSON file matching `PersonaConfig` - copy one to write your own (`name`, `goal`, `risk_tolerance`, `values`).

The agent plays autonomously from start to finish without interruption. Add `--player-model` to pick the agent's model:

```bash
uv run dungeon-crawler --persona personas/greedy_looter.json --player-model llama3.2:3b
```

**Note**: `--checkin-every` is automatically disabled in autonomous mode. If you want human oversight during play, run without `--persona` and type the actions yourself.

## 6. Compare personas with the eval harness

```bash
uv run dungeon-crawler-eval
```

This scores retrieval quality against a small gold Q&A set (`evaluation/lore_qa.json`), then runs every persona in `personas/` through the same dungeon and prints a goal-achievement score (1-5, with a rationale) for each - "numbers instead of vibes," per the project plan.

Want to sanity-check the harness itself without waiting on real model calls?

```bash
uv run dungeon-crawler-eval --dry-run
```

`--dry-run` swaps in mocks and one fixed scripted playthrough for every persona - it proves the pipeline wiring works, but it says nothing about how any persona actually plays (that needs the real agent).

## 7. Run it as an HTTP API

```bash
uv run uvicorn dungeon_crawler.api:app_factory --factory --reload
```

(`--factory` matters here - it defers building the real Ollama-backed app until uvicorn starts it, rather than at import time.)

```bash
# start a game
curl -s -X POST localhost:8000/games -H 'content-type: application/json' -d '{}'
# -> {"thread_id": "...", "status": "awaiting_action", "narration": "...", "location": "entrance", "turn": 1}

# submit a turn (use the thread_id from above)
curl -s -X POST localhost:8000/games/<thread_id>/actions -H 'content-type: application/json' -d '{"raw_text": "go north"}'

# check status any time, without advancing a turn
curl -s localhost:8000/games/<thread_id>
```

Start with a persona instead of a human by passing `{"persona_name": "cautious_scout"}` to `POST /games` (the name is a file stem from `personas/`).

## 8. Run it as an MCP tool server

```bash
uv run python -m dungeon_crawler.mcp_server
```

This speaks MCP over stdio, exposing `start_game`, `take_action`, `check_inventory`, `save_game`, and `roll_dice` as tools - point an MCP-compatible client (e.g. Claude Desktop's config) at it to let another agent play the dungeon crawler as an external tool user instead of through LangGraph directly.

## 9. Tracing (optional)

Every graph run can optionally be traced to a self-hosted
[Langfuse](https://langfuse.com/) instance - per-node timing/inputs/outputs
for each step of the turn loop, plus prompt/response/latency/token usage for
every Ollama call (narration, the autonomous player agent, and the eval
judge). See `OBSERVABILITY.md` for the design.

Tracing is off by default and requires no code changes to disable - it only
activates when both env vars below are set, so nothing here is required to
play, test, or serve the game:

```bash
export LANGFUSE_PUBLIC_KEY=pk-...
export LANGFUSE_SECRET_KEY=sk-...
export LANGFUSE_HOST=http://localhost:3000  # or your self-hosted instance
```

With those set, `uv run dungeon-crawler`, the API/MCP servers, and
`uv run dungeon-crawler-eval` all send traces automatically. Games are
grouped in the Langfuse UI by `--thread-id`/session, so a whole playthrough
(across turns, and across resumes) shows up as one timeline. Eval runs are
additionally tagged `eval` + the persona name.

If Langfuse is unreachable, traces fail to export in the background without
affecting gameplay - see `OBSERVABILITY.md` for details.

## Troubleshooting

- **`ConnectionError: Failed to connect to Ollama`** - Ollama isn't running. Start it (`ollama serve` or the desktop app) and confirm with `ollama list`.
- **Model not found / 404 from Ollama** - you haven't pulled it yet; see step 3, or pass a model you *have* pulled via the relevant `--model` flag.
- **Narration feels slow / laggy** - expected on CPU-only per `compute-requirements.md` (~3-8 tok/s on a 7-8B model); try a smaller `--model`, or get it onto a GPU.
- **Running out of disk mid-pull** - model weights are the bulk of the ~15-20GB footprint; see `compute-requirements.md` for per-model sizes before choosing which to pull.
- **Tests failing** - `uv run pytest -q` should never touch Ollama; a failure there is a real code issue, not a "go pull a model" issue.

## See also

- `ai-dungeon-master-project-plan.md` - the original layer-by-layer plan and phase breakdown.
- `compute-requirements.md` - model sizing and hardware requirements in more detail.
- `OBSERVABILITY.md` - the Langfuse tracing design.
