# Observability design: Langfuse tracing for the game graph

Status: implemented. `src/dungeon_crawler/observability.py` plus wiring in
`sessions.py`, `cli.py`, `evaluation.py`. Standing up a Langfuse instance
and setting `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` is still a manual
step outside this repo - see `running-locally.md` for the env vars.

## Goal

Give every graph run — interactive play, server-driven sessions, and eval
playthroughs — a trace in a self-hosted Langfuse instance showing:

- **Per-node timing/inputs/outputs** for each of the 8 nodes in
  `graph.py`'s `StateGraph` (`intro`, `get_action`, `checkin`, `resolve`,
  `retrieve`, `narrate`, `remember`, `check_end`).
- **Per-LLM-call detail** — raw prompt, raw response, latency, token usage —
  for all three Ollama call sites: `OllamaNarrator.narrate()` (`llm.py:43`),
  `OllamaPlayerAgent.get_action()` (`agents.py:177`), and
  `OllamaJudge.score()` (`evaluation.py:106`).

Everything stays local: Langfuse self-hosted, Ollama local, nothing leaves
the machine. That matches the project's existing "no cloud LLM calls"
posture (see `running-locally.md`).

## Why this is a small integration, not a big one

The graph is a LangGraph `StateGraph`, and all three LLM call sites use
`ChatOllama` (a LangChain `Runnable`). Langfuse ships a LangChain-compatible
`CallbackHandler`. LangChain propagates callbacks through nested `Runnable`
calls automatically via a contextvar — so a node function that calls
`self._llm.invoke([...])` *without* explicitly forwarding `config` still
picks up the parent run's callbacks, as long as it runs synchronously in the
same call stack (true here — nothing in this codebase crosses a thread or
async task boundary between a node and its LLM call).

Practical result: **attach one `CallbackHandler` to the top-level
`graph.invoke(...)` call, and both the node-level spans and the nested
LLM-call spans appear automatically**, nested correctly, with no changes
needed inside `graph.py`, `llm.py`, `agents.py`, or `evaluation.py`'s
call-site code itself. The only wiring needed is at the handful of places
that already build the `config` dict passed to `.invoke()`.

Token usage: `langchain-ollama` populates `usage_metadata` on the returned
`AIMessage`, which LangChain callbacks forward automatically. This needs to
be confirmed empirically once implemented (open risk, not a blocker) — if
usage comes back empty for some models, we'd still get prompt/response/
latency, just not a token count, and can revisit then.

## Trace boundaries: one invoke() call = one trace

This project has three distinct call patterns for `graph.invoke()`, and it
matters for how traces group in the Langfuse UI:

| Caller | Pattern | What ends up in one trace |
|---|---|---|
| `sessions.py` `GameServer` (API/MCP) | `InterruptActionProvider` interrupts on *every* turn (`agents.py:197-206`) | One trace per turn (`start_game` = intro turn, each `submit_action` = one more turn) |
| `cli.py` human play | No interrupt unless `--checkin-every` set; `input()` blocks in-process | One trace for the *entire game*, unless a checkin interrupt splits it into more |
| `evaluation.py` `run_persona_playthrough` | No interrupts (checkin disabled by default) | One trace for the entire playthrough |

Since server-driven play produces many short traces (one per turn) rather
than one long one, we need a way to stitch them back together in the
Langfuse UI. Langfuse's `session_id` is exactly this: every place that
already threads a `thread_id` through `config = {"configurable": {"thread_id": ...}}`
(see `sessions.py:59,64,74`, `cli.py:90`, `evaluation.py:179`) gets the same
value passed as `metadata={"langfuse_session_id": thread_id}`. In the
Langfuse UI, that groups every trace for one game session — across turns,
across process restarts if resumed — into a single timeline. This is a
natural fit since `thread_id` already *is* this project's session concept
(it's the checkpointer key too).

Interrupts themselves aren't exceptions from the graph's perspective —
LangGraph catches `GraphInterrupt` internally and `invoke()` returns
normally with `__interrupt__` in the result. So a trace that ends at an
interrupt should complete as a normal (non-errored) trace, just short. Worth
confirming visually once wired up, but no special-casing should be needed.

## What's new

**1. New module: `src/dungeon_crawler/observability.py`**

- `get_langfuse_handler() -> CallbackHandler | None` — returns `None`
  unless `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in the
  environment (standard Langfuse SDK env vars, read automatically by their
  client — `LANGFUSE_HOST` too, for pointing at the self-hosted instance).
  Caches a singleton handler when enabled. This means tracing is **opt-in
  by absence of config** — no code path requires a Langfuse instance to be
  running, which matters because `uv run pytest -q` must keep working fully
  offline (per `running-locally.md`), as must this sandbox.
- `trace_config(thread_id: str, *, tags: list[str] | None = None, **metadata) -> dict`
  — builds the `configurable`/`callbacks`/`metadata` dict merging in
  `langfuse_session_id=thread_id`, so call sites don't hand-roll this.

**2. Wiring at existing config-construction points** (no new call sites,
just extending dicts already being built):

- `sessions.py:59,64,74` (`GameServer.start_game/submit_action/get_status`)
- `cli.py:90` (`config = {"configurable": {"thread_id": args.thread_id}}`)
- `evaluation.py:179` (`run_persona_playthrough`) — also tag these
  `tags=["eval", persona.name]` so eval runs are visually distinguishable
  from interactive play in the Langfuse UI.
- `eval_cli.py` and `api.py`/`mcp_server.py` only need updates if they build
  their own `config` dicts separately from `sessions.py`/`evaluation.py` —
  needs a quick check during implementation, but based on the read-through
  so far, they delegate through `GameServer`/`run_persona_playthrough` and
  shouldn't need direct changes.

**3. New dependencies**: `langfuse` added to `pyproject.toml` as a plain
dependency (not an optional extra) — gating activation via env-var-presence
(rather than via `try/except ImportError`) keeps the code simpler, matching
this project's general preference for minimal conditional-import machinery.

One discovery during implementation: Langfuse's LangChain callback
integration (`langfuse.langchain.CallbackHandler`) requires the full
`langchain` package to be importable (it branches on `langchain.__version__`
internally), not just `langchain-core`/`langchain-ollama`, which is all this
project needed before. `langchain` was added alongside it. This did *not*
force any version changes elsewhere — the project's existing loose `>=`
pins on `langgraph`/`langchain-core`/`langchain-ollama` were already
resolving to their current 1.x lines before this change (verified via
`uv.lock` diff), so no upgrade cascade happened.

**4. Self-hosted Langfuse instance.** Needs Postgres + ClickHouse + Redis +
blob storage per Langfuse's current self-host requirements. Not vendored in
this repo (see open question 1 below, resolved as documentation-only) —
standing one up is an external prerequisite, same as Ollama.

**5. Failure behavior verified.** With `LANGFUSE_PUBLIC_KEY`/`_SECRET_KEY`
set but the Langfuse host unreachable, a full session start/submit-action
round-trip through `GameServer` still completes normally — span export
failures are retried and logged by the background OTel exporter, never
raised into game logic. Tracing being down does not mean gameplay is down.

## What's deliberately out of scope

- No custom spans inside `game_logic.py`'s deterministic dice/combat math —
  node-level tracing on `resolve_node` already captures its input state and
  output diff, which is enough resolution.
- No change to `graph.py` node function signatures — they don't need to
  accept or forward `config`/`callbacks` explicitly; ambient propagation
  handles it.
- No tracing added to `HumanActionProvider` or `ScriptedActionProvider`
  paths beyond what the graph-level callback already captures — they don't
  make LLM calls, so there's nothing extra to instrument there.

## Still open / not implemented

1. **Standing up Langfuse itself** — resolved as documentation-only (see
   `running-locally.md` §9): a running Langfuse instance is an external
   prerequisite, not vendored via a `docker-compose.yml` in this repo.
2. **Stretch goal, not done**: Langfuse supports attaching *scores* to a
   trace. `evaluation.py`'s existing `GoalScore` (1-5 + rationale from
   `OllamaJudge`, `evaluation.py:69-71`) maps directly onto that — pushing
   it as a trace score would turn Langfuse into a lightweight eval
   dashboard, not just a tracer, letting you compare persona runs visually
   over time. Left as a follow-up.
3. No tags/metadata beyond `thread_id`-as-session and the `eval` +
   persona-name eval tags were added. No `environment` tag or similar —
   add if it becomes useful.
4. **Not yet verified against a real Langfuse instance + real Ollama**:
   the wiring was verified with `uv run pytest -q` (fully mocked, 77
   passing) and with a real `CallbackHandler` pointed at an unreachable
   host (confirms graceful degradation, not correct trace content). Actually
   opening the Langfuse UI and confirming node spans nest correctly under
   LLM spans, with real prompt/response/latency/token data, still needs a
   local Ollama + Langfuse instance to do.

## Rollout status

1. ~~Stand up Langfuse locally~~ — deferred to whoever runs this with
   tracing on; not required for the code to work.
2. Done: `langfuse` (+ `langchain`, a required transitive need) added;
   `observability.py` written.
3. Done: `trace_config()` wired into `sessions.py`, `cli.py`,
   `evaluation.py`. `api.py`/`mcp_server.py` needed no direct changes —
   they delegate through `GameServer`/`run_persona_playthrough`.
4. Not done — needs a real Langfuse + Ollama instance (see open item 4
   above).
5. Done: `running-locally.md` §9 documents the env vars and behavior.
6. Not done (stretch, see open item 2 above).
