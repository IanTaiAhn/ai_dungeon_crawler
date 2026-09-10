# AI Dungeon Crawler

A local, Ollama-powered text adventure. An LLM Dungeon Master narrates your turns using retrieval-augmented generation over a lore corpus, a deterministic engine resolves combat/inventory/movement, and every turn is checkpointed so games can be saved and resumed. You can play it yourself, or hand the controls to an autonomous LLM "persona" agent and watch it play - and score how well it does with the built-in eval harness.

Everything runs against models served locally by [Ollama](https://ollama.com) - no API keys, no cloud calls.

## Features

- **AI Dungeon Master** - narrates outcomes in-voice, grounded in a markdown lore corpus via Chroma vector retrieval
- **Human or AI player** - play at a terminal yourself, or run one of three example personas (`cautious_scout`, `greedy_looter`, `honorable_warden`) autonomously
- **Deterministic game engine** - combat, inventory, and movement are plain rules, not the LLM's judgment call
- **Save/resume** - every turn is checkpointed to SQLite under a named "thread," so `--thread-id my-run-1` picks up where you left off
- **Four entry points into the same engine** - a terminal CLI, an HTTP API (FastAPI), an MCP tool server (for Claude Desktop and other MCP clients), and an eval CLI
- **Eval harness** - scores lore-retrieval quality and runs every persona through the same dungeon for a comparable goal-achievement score
- **Mock mode** - the entire test suite runs against mocked LLMs/embeddings, so `uv run pytest` never needs Ollama running
- **Optional tracing** - wire up [Langfuse](https://langfuse.com) for per-node timing and full prompt/response traces of every turn

## Quick start

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and [Ollama](https://ollama.com/download) installed and running.

```bash
# 1. Clone and install
git clone <this repo>
cd ai_dungeon_crawler
uv sync

# 2. Start Ollama and pull the default models
ollama pull qwen2.5:7b        # DM narrator
ollama pull llama3.2:3b       # autonomous player agent
ollama pull nomic-embed-text  # lore embeddings

# 3. Play
uv run dungeon-crawler
```

You'll get the DM's opening narration, then a `>` prompt. Try `go north`, `attack goblin`, `take rusty sword`, `inspect`, or `flee`.

Want to watch an AI play instead?

```bash
uv run dungeon-crawler --persona personas/cautious_scout.json
```

Don't have Ollama pulled/running yet and just want to see it work? The test suite and the bundled example run entirely on mocks:

```bash
uv run pytest -q
uv run python examples/mock_playthrough_demo.py
```

For the full setup walkthrough - swapping in smaller models on CPU-only machines, the HTTP API, the MCP server, save-slot flags, tracing, and troubleshooting - see **[`running-locally.md`](running-locally.md)**.

## Project layout

```
src/dungeon_crawler/   Core package: graph (LangGraph state machine), game engine,
                       parser, Narrator/Embedder (Ollama), agents, CLI, API, MCP server
lore/                  Markdown lore corpus retrieved by the DM narrator
personas/              Example autonomous-player configs (goal, risk tolerance, values)
evaluation/            Gold Q&A set used to score lore retrieval
examples/              Standalone demo scripts (no Ollama required)
tests/                 Full test suite, run entirely against mocks
```

## Documentation

| Doc | What it covers |
|---|---|
| [`running-locally.md`](running-locally.md) | Full local setup: install, models, CLI flags, HTTP API, MCP server, tracing, troubleshooting |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the game loop, RAG narration, and state machine fit together |
| [`ENTRY-POINTS.md`](ENTRY-POINTS.md) | The CLI, HTTP API, and MCP server explained, and how they share one graph |
| [`AGENT-TAXONOMY.md`](AGENT-TAXONOMY.md) | The different "agent" roles in the codebase (player, DM, eval judge, etc.) |
| [`CHECKPOINTING.md`](CHECKPOINTING.md) | How save/resume and per-turn state persistence work |
| [`MOCK-MODE.md`](MOCK-MODE.md) | How the graph runs without any real LLM, for tests and demos |
| [`OBSERVABILITY.md`](OBSERVABILITY.md) / [`langfuse-setup.md`](langfuse-setup.md) | Optional Langfuse tracing design and setup |
| [`compute-requirements.md`](compute-requirements.md) | Model sizing and hardware requirements |
| [`ai-dungeon-master-project-plan.md`](ai-dungeon-master-project-plan.md) | Original project plan and phase breakdown |

## Testing

```bash
uv run pytest -q
```

The whole suite runs against mocks (`MockNarrator`, `MockEmbedder`, `MockJudge`, `ScriptedActionProvider`) - no Ollama connection required, so this is the fastest way to confirm the code works before touching real models.
