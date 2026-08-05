# Setting up Langfuse tracing

Step-by-step guide to standing up a local Langfuse instance and pointing
this repo's tracing at it. See `OBSERVABILITY.md` for the design/how it's
wired into the code; this doc is just the operational how-to.

Tracing is entirely optional - skip this if you don't need it. Nothing
here is required to play, test, or serve the game.

## 1. Prerequisites

- Docker + Docker Compose
- This repo synced (`uv sync`) on a commit that includes the tracing code
  (merged in PR #10)

## 2. Stand up Langfuse

Langfuse's self-host stack (Postgres, ClickHouse, Redis, blob storage, the
web + worker services) isn't vendored in this repo - it's a separate
multi-service stack, so clone Langfuse itself and use their compose file
rather than a copy that would drift out of sync:

```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse
docker compose up -d
```

First boot pulls several images and can take a minute or two. Check
`docker compose ps` until everything is healthy. Full self-host docs (auth
providers, production hardening, etc.): https://langfuse.com/self-hosting

## 3. Create a project and API keys

1. Open http://localhost:3000
2. Sign up (this is your local instance - any email/password works)
3. Create an organization, then a project (e.g. "dungeon-crawler")
4. Project Settings -> API Keys -> "Create new API key". Copy both the
   Public Key (`pk-...`) and Secret Key (`sk-...`) - the secret is only
   shown once.

## 4. Point dungeon-crawler at it

Back in this repo's shell:

```bash
export LANGFUSE_PUBLIC_KEY=pk-...
export LANGFUSE_SECRET_KEY=sk-...
export LANGFUSE_HOST=http://localhost:3000
```

Put these in your shell profile (`~/.zshrc`, `~/.bashrc`) so they persist,
or in a local `.env` you `source` before running the game. Either way,
don't commit them - `.gitignore` doesn't currently exclude `.env`, so add
it there first if you go that route.

## 5. Verify the plumbing (no Ollama needed)

`--dry-run` swaps in `MockNarrator`/`MockJudge`, so no LLM spans show up,
but the graph's per-node spans still do - a good smoke test that the
env vars and callback wiring actually work before involving Ollama:

```bash
uv run dungeon-crawler-eval --dry-run
```

In the Langfuse UI, go to **Tracing -> Traces**. You should see one trace
per persona, tagged `eval` + the persona's name, each with 8 nested node
spans (`intro`, `get_action`, `checkin`, `resolve`, `retrieve`, `narrate`,
`remember`, `check_end`) showing that node's input state, output diff, and
timing.

## 6. See real LLM spans (needs Ollama)

With Ollama running and models pulled (see `running-locally.md`):

```bash
uv run dungeon-crawler --thread-id trace-test
```

Play a couple of turns, then quit. In the Langfuse UI:

- **Sessions** tab -> find `trace-test` -> every turn's trace is grouped
  into one timeline for the session.
- Open a trace -> node spans nested in turn order.
- Open the `narrate`/`get_action` node's nested generation span -> full
  prompt, completion, latency, and (if `langchain-ollama` populates it for
  the model in use) token usage.

For server-driven play (`api.py`/`mcp_server.py`/`sessions.py`), every
`submit_action` call is its own trace, since `InterruptActionProvider`
pauses on every turn - the same `thread_id`-as-session grouping stitches
those back into one timeline per game.

## 7. Turning it off

Unset the two required env vars and tracing goes back to a no-op - nothing
else about the app changes:

```bash
unset LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
```

## Tearing down Langfuse

```bash
cd path/to/langfuse
docker compose down        # stop, keep data
docker compose down -v     # stop and wipe data
```

## See also

- `OBSERVABILITY.md` - design and implementation notes for the tracing
  code in this repo.
- `running-locally.md` §9 - the short version of the env vars.
