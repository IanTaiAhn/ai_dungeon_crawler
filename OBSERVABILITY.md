# Observability design: Langfuse tracing for the game graph

Status: design draft, not yet implemented.

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

**3. New dependency**: `langfuse` added to `pyproject.toml`. Proposing it as
a plain dependency (not an optional extra) — it's a lightweight HTTP client
with no heavy transitive deps, and gating activation via env-var-presence
(rather than via `try/except ImportError`) keeps the code simpler, matching
this project's general preference for minimal conditional-import
machinery.

**4. Self-hosted Langfuse instance.** Needs Postgres + ClickHouse + Redis +
blob storage per Langfuse's current self-host requirements. Open question
below on how to stand this up.

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

## Open questions before implementation

1. **Standing up Langfuse itself** — vendor a `docker-compose.yml` in this
   repo (convenient, but another multi-service stack to keep in sync with
   upstream Langfuse's own compose file as it evolves), or just document
   pointing at Langfuse's own self-hosting repo/instructions and treat "a
   running Langfuse instance" as an external prerequisite, the same way
   Ollama already is? **Leaning toward documenting-only**, to avoid owning
   a copy of Langfuse's infra config.
2. **Stretch goal**: Langfuse supports attaching *scores* to a trace.
   `evaluation.py`'s existing `GoalScore` (1-5 + rationale from
   `OllamaJudge`, `evaluation.py:69-71`) maps directly onto that — pushing
   it as a trace score would turn Langfuse into a lightweight eval
   dashboard, not just a tracer, letting you compare persona runs visually
   over time. Worth doing, but proposing it as a follow-up after basic
   tracing works, not bundled into the first pass.
3. Any preference on tags/metadata beyond `thread_id`-as-session and the
   eval tags above (e.g. an `environment` tag for local vs. some future
   deployment)?

## Rollout plan

1. Stand up Langfuse locally (per open question 1), get API keys.
2. Add `langfuse` dependency; write `observability.py`.
3. Wire `trace_config()` into `sessions.py`, `cli.py`, `evaluation.py`.
4. Play a real game against local Ollama with tracing on; confirm in the
   Langfuse UI: node spans nested correctly, LLM spans show prompt/response/
   latency/tokens, multi-turn server sessions group under one `session_id`,
   an interrupted trace shows as complete-not-errored.
5. Update `running-locally.md` with the new env vars and an optional
   "tracing" section.
6. (Stretch) wire `GoalScore` into Langfuse trace scores for eval runs.
