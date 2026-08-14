# Running the graph without Ollama

The LangGraph state machine that drives this game (`graph.py`) doesn't call
any LLM directly. Every node that needs language understanding or generation
goes through a small Python `Protocol` interface instead:

- `Narrator` (`llm.py`) - narrates the outcome of a turn
- `Embedder` (`retrieval.py`) - turns text into vectors for lore/event retrieval
- `ActionProvider` (`agents.py`) - decides the next `PlayerAction`

`build_graph()` only knows about these interfaces. It has no idea whether
`narrator.narrate(...)` is calling a real Ollama model or returning a
templated string. That's what makes it possible to run the exact same graph
- same nodes, same edges, same loop, same `interrupt()`/`Command(resume=...)`
mechanics, same checkpointing - with zero LLM calls at all.

## The three real models, and their mock stand-ins

| Real (needs Ollama) | Mock (no model, no network) | Used by |
|---|---|---|
| `OllamaNarrator` (`qwen2.5:7b`) | `MockNarrator` - returns `f"You {intent} {target}."` | `intro_node`, `narrate_node` |
| `OllamaEmbedder` (`nomic-embed-text`) | `MockEmbedder` - hashes words into buckets (word-overlap similarity, no real semantics) | `LoreStore` (`retrieve_node`, `remember_node`) |
| `OllamaPlayerAgent` (`llama3.2:3b`) | `ScriptedActionProvider` - plays back a fixed list of typed commands | `get_action_node` |

Swap the left column for the right column and nothing else in `graph.py`
changes. This is exactly how the test suite works (`tests/helpers.py`
builds the real graph wired with all three mocks) and how
`dungeon-crawler-eval --dry-run` sanity-checks the eval harness without
waiting on real model calls.

## What you get with mocks: correct mechanics, flat prose

Everything *structural* still happens for real:

- The graph really walks node -> edge -> node, looping through
  `get_action -> checkin -> resolve -> retrieve -> narrate -> remember -> check_end`
  until `check_end`'s conditional edge routes to `END`.
- `checkin_node`'s `langgraph.types.interrupt()` really pauses the graph and
  hands control back to Python; resuming with `Command(resume=...)` really
  continues from that exact point.
- Combat math, movement, inventory, quest flags - all of `resolve_node` - is
  deterministic game logic, unaffected by which narrator is plugged in.
- The checkpointer really persists state (here, `InMemorySaver`; the CLI
  uses `SqliteSaver` for on-disk saves).

The only thing that changes is narration quality, because `MockNarrator` is
a template, not a language model:

| Real (`qwen2.5:7b`) | Mock |
|---|---|
| *"The rusty blade bites deep into the goblin's shoulder - it staggers back with a snarl, blood welling dark in the torchlight."* | `You attack goblin.` |
| *"Flame roars from your fingertips and cracks across the golem's frozen hide - shards of black ice hiss and melt where the fire licks."* | `You cast_spell flame crystal golem.` |

So: flat, robotic storytelling, but a fully correct, fully playable game
underneath it.

## The demo script

[`examples/mock_playthrough_demo.py`](examples/mock_playthrough_demo.py)
builds the real graph with all three mocks (`checkin_every=3`, so you can
see both the "before combat" and "every N turns" interrupt triggers fire),
scripts a full playthrough from the entrance to picking up the frostbound
crown, and prints:

- each `invoke()` call and what pause point it ran to
- the payload of every real `interrupt()` along the way, and the
  `Command(resume=...)` call that continues past it
- the full turn-by-turn `log` accumulated in `GameState`, including the
  turns that passed silently *inside* a single `invoke()` call without ever
  interrupting
- the final `graph.get_state(config)` snapshot, proving the checkpointer
  persisted the finished game under its `thread_id`

## Run it yourself

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- nothing else. No Ollama, no GPU, no models to pull.

```bash
git clone <this repo>
cd ai_dungeon_crawler
git checkout claude/langgraph-usage-24jqe8   # or wherever this file landed
uv sync
uv run python examples/mock_playthrough_demo.py
```

You should see the graph pause on interrupts, resume, and eventually print
`GAME OVER ... outcome='win'` followed by the full turn log.

A couple of other mock-only entry points, if you want to poke further:

```bash
uv run pytest -q                      # whole test suite, all mocks, no Ollama touched
uv run dungeon-crawler-eval --dry-run # sanity-checks the eval harness the same way
```

None of these are how you'd actually *play* the game, though - `uv run
dungeon-crawler` (see `running-locally.md`) is hardcoded to the real
`OllamaNarrator`/`OllamaEmbedder`, with no mock flag exposed, so real prose
narration and real lore retrieval require Ollama running locally with the
models pulled.
