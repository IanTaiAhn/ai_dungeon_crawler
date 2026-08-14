# Entry points: how `dungeon-crawler` actually starts, and where MCP fits

It's easy to assume `mcp_server.py` is the glue holding the CLI, the graph,
and the LLMs together, since it's the file that literally imports `mcp` and
sounds central. It isn't. This project has **three separate, independent
entry points** that each build (or reuse) the same LangGraph graph, and MCP
is only involved in one of them.

## The three entry points

| Entry point | Command | Who's driving the game | Touches `mcp_server.py`? |
|---|---|---|---|
| `cli.py` | `uv run dungeon-crawler` | You, typing at a terminal - or `OllamaPlayerAgent` if you pass `--persona` | No |
| `api.py` | `uv run uvicorn dungeon_crawler.api:app_factory --factory` | Anything speaking HTTP (curl, a web frontend) | No |
| `mcp_server.py` | `uv run python -m dungeon_crawler.mcp_server` | An MCP client (Claude Desktop, another agent) | Yes - this **is** it |

They're started separately, for different purposes. Nothing here requires
running more than one at a time, and nothing in the CLI, the API, or the
test suite depends on the MCP server being up.

## Where each one is defined

`pyproject.toml` maps the two installed commands directly to their `main()`
functions:

```toml
[project.scripts]
dungeon-crawler = "dungeon_crawler.cli:main"
dungeon-crawler-eval = "dungeon_crawler.eval_cli:main"
```

So `uv run dungeon-crawler` runs `cli.py:main()` - full stop. `mcp_server.py`
is never imported.

## The actual call chain for `uv run dungeon-crawler`

```
uv run dungeon-crawler
  -> cli.py: main()
      -> build_graph(narrator, action_provider, checkpointer, lore_store, ...)   # graph.py
      -> _run_until_done(graph, initial, config)                                 # loops invoke()/Command(resume=...)
```

This is exactly the node -> edge -> node loop, `interrupt()` /
`Command(resume=...)` cycle, and checkpointing covered in the rest of this
project's docs (see `MOCK-MODE.md`) and demonstrated in
`examples/mock_playthrough_demo.py`. None of it touches MCP.

## Where MCP actually comes in

`mcp_server.py` is a third, alternate way to expose the *same* underlying
game to an *external* caller - not something the other two entry points rely
on. Unlike `cli.py`/`api.py`, which call `build_graph()` directly,
`mcp_server.py` goes through `sessions.py`'s `GameServer` (the same wrapper
`api.py` uses), which owns one compiled graph and answers `start_game`
/ `submit_action` / `get_status` calls by thread_id.

`create_mcp_server()` wraps those `GameServer` methods as five
`@mcp.tool()`-decorated functions - `start_game`, `take_action`,
`check_inventory`, `save_game`, `roll_dice` - using the official `mcp`
Python SDK's `FastMCP`. Run with `python -m dungeon_crawler.mcp_server`, it
speaks MCP over stdio, so an MCP-compatible client (e.g. Claude Desktop) can
discover those tools and call them directly, without knowing or caring that
LangGraph is running underneath.

This works because `sessions.py` always uses `InterruptActionProvider`:
every turn pauses on a real `langgraph.types.interrupt()` waiting for
`player_action`, instead of blocking on a local `input()` the way
`HumanActionProvider` does. That's what lets an external MCP tool call
resume the paused graph with `Command(resume=raw_text)` - the identical
mechanism the CLI's `_run_until_done` loop uses internally, just triggered
by an MCP client instead of a Python `while` loop.

## The point of building it this way

The same stateful, interrupt-driven graph can serve two very different
kinds of "agent":

1. **An LLM embedded inside the graph** - `OllamaPlayerAgent` in
   `agents.py`, called from `get_action_node`. It has no concept of
   "tools"; it's just a function call in the loop, producing a
   `PlayerAction` via structured output.
2. **An LLM entirely external to the graph, via MCP** - it never sees
   `GameState`, `PlayerAction`, or LangGraph at all. It just sees five
   named tools with schemas and calls them, the same way it would call a
   filesystem or database MCP server.

Neither one is "the real" way to play - they're two different integration
patterns living side by side in the same codebase, both sitting on top of
the identical compiled graph.

## `sessions.py` is not MCP-only - it's shared by the API and MCP surfaces

It's tempting to read "`mcp_server.py` goes through `sessions.py`'s
`GameServer`" as "`sessions.py` exists for MCP." It doesn't -
`api.py` uses the exact same `GameServer`:

```python
# api.py
from dungeon_crawler.sessions import GameNotFoundError, GameServer
...
server = GameServer(narrator, embedder, lore_dir=lore_dir, db_path=db_path, lore_collection_name="lore")
```

```python
# mcp_server.py
from dungeon_crawler.sessions import GameNotFoundError, GameServer
...
server = GameServer(narrator, embedder, lore_dir=lore_dir, db_path=db_path, lore_collection_name="lore")
```

`sessions.py`'s own docstring says as much: *"Shared game-session management
for the serving layer (FastAPI + MCP)."* It exists because the API and MCP
server have the same shape of problem - stateless request/response calls,
many concurrently active games addressed by `thread_id`, and turns that must
resume via a real `interrupt()`/`Command(resume=...)` rather than block on a
local `input()`. `GameServer` was written once to solve that for both.

`cli.py` is the odd one out: it never touches `sessions.py` at all. It calls
`build_graph()` directly, because a single long-lived terminal process
holding one game in memory doesn't need the multi-game/resumable-per-request
abstraction `GameServer` provides.

### File-by-file, by mode

| File | CLI (human) | CLI (`--persona`) | HTTP API | MCP server |
|---|:---:|:---:|:---:|:---:|
| `schemas.py`, `graph.py`, `game_logic.py`, `items.py`, `scenario.py`, `parser.py`, `checkpointing.py` | Y | Y | Y | Y |
| `llm.py` (`Narrator`), `retrieval.py` (`Embedder`/`LoreStore`) | Y | Y | Y | Y |
| `observability.py` (`trace_config`) | Y | Y | Y (via `sessions.py`) | Y (via `sessions.py`) |
| `agents.py`: `HumanActionProvider` | Y | - | - | - |
| `agents.py`: `OllamaPlayerAgent` | - | Y | - | - |
| `agents.py`: `InterruptActionProvider` | - | - | Y | Y |
| `sessions.py` (`GameServer`) | - | - | Y | Y |
| `api.py` | - | - | Y | - |
| `mcp_server.py` | - | - | - | Y |

The top two rows are the real game engine - every mode runs the identical
`build_graph()` output. Everything below that is which turn-source
(`ActionProvider`) is wired in, and whether the surface needs `GameServer`'s
multi-game bookkeeping or just calls `build_graph()` straight, like `cli.py`
does.

## Quick reference: what to run for what

```bash
uv run dungeon-crawler                                    # play at a terminal
uv run dungeon-crawler --persona personas/greedy_looter.json  # watch an autonomous persona
uv run uvicorn dungeon_crawler.api:app_factory --factory --reload  # HTTP API
uv run python -m dungeon_crawler.mcp_server                # MCP tool server (e.g. for Claude Desktop)
uv run python examples/mock_playthrough_demo.py            # graph + mocks, no Ollama, no MCP
uv run pytest -q                                           # test suite, all mocks
```

See `running-locally.md` for full setup/flags, and `MOCK-MODE.md` for how
the graph runs without any LLM at all.
