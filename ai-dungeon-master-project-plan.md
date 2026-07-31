# AI dungeon master — project plan

A local, Ollama-powered text adventure with an autonomous player agent, built to learn LangGraph, LangChain, RAG, and agent evaluation along the way.

## Goal

Build a text-adventure game where:
- A **DM agent** narrates the world and responds to actions, grounded in a small lore corpus via RAG.
- A **player agent**, given a persona/goal, autonomously decides what to do each turn — no human typing required (though a human can jump in via an interrupt).
- Game state persists across turns and can be saved/resumed.
- The whole thing is measurable — you can tell whether the player agent is actually pursuing its stated goal, and whether retrieval/generation are doing their jobs.

---

## Layer-by-layer breakdown

### 1. Model layer — Ollama
- [ ] Pull a mid-size model for the **DM** (narration quality matters more than speed — runs once per turn).
- [ ] Pull a **smaller/quantized model** for the **player agent** (runs every turn, speed matters more than depth).
- [ ] Pull an embedding model (`nomic-embed-text` or similar) for the lore RAG pipeline.
- [ ] Decide Modelfiles for each: DM gets a "voice" system prompt + higher temperature; player agent gets the persona/goal as its system prompt + lower temperature (more decisive, less rambling).

### 2. Orchestration layer — LangGraph
- [ ] Define the shared game state object (location, inventory, HP, quest flags, turn count, persona description).
- [ ] Build the `StateGraph`: retrieve lore → narrate → player agent decides → parse/validate → branch (combat / explore / inventory) → update & save state → check win/lose → loop or end.
- [ ] Wire the conditional edge for the combat/explore/inventory branch.
- [ ] Add a **checkpointer** for save/resume.
- [ ] Add an **interrupt** node for the optional human check-in (every N turns, or on high-stakes actions like combat).

### 3. Structured data layer — Pydantic
- [ ] `PlayerAction` schema (intent, target, direction, etc.) — what both the human path and the player agent path must produce.
- [ ] `GameState` schema — the object passed through the graph and persisted.
- [ ] `PersonaConfig` schema — how a player agent's goal/personality is defined and passed in at game start.

### 4. Retrieval layer — Chroma (or FAISS)
- [ ] Write/collect a small lore corpus (world description, factions, key NPCs, past significant events).
- [ ] Chunking strategy — start naive (fixed-size), revisit if retrieval quality is bad.
- [ ] Embed with the Ollama embedding model, store in Chroma.
- [ ] Retrieval step feeding into the narrate node, plus a mechanism to **write new events back into the store** as the game progresses (so the DM can "remember" what happened 20 turns ago).

### 5. Game logic layer — plain Python, no AI
- [ ] Combat resolution (dice rolls, HP math).
- [ ] Inventory rules.
- [ ] Win/lose condition checks.
- Keep this layer boring and deterministic on purpose — the LLM decides *intent*, this layer decides *outcome*. Keeps the game fair and debuggable.

### 6. Evaluation & observability layer
- [ ] Tracing: LangSmith or Langfuse (open source) wired into the graph so you can see retrieved chunks, parsed actions, and model reasoning per turn.
- [ ] A small gold Q&A/retrieval test set for the lore corpus (RAGAS-style: context precision/recall, faithfulness).
- [ ] A "goal achievement" scorer for the player agent — given the persona description and a full transcript, did the agent actually behave consistently with its stated goal?

### 7. Serving layer — optional / stretch
- [ ] Wrap the graph in FastAPI so it's a deployable app, not just a script.
- [ ] Stretch: expose game actions (`roll_dice`, `check_inventory`, `save_game`) as an **MCP server** instead of hardcoded graph tools.

---

## Suggested build order (phased, each phase playable)

| Phase | What you build | You can... |
|---|---|---|
| 0 | Ollama installed, models pulled, project scaffolded | Confirm `ollama run` works for both models |
| 1 | Core loop: DM (Ollama) + human player + Pydantic action schema + LangGraph checkpointing, **no RAG yet** | Play a bare-bones adventure end to end in the terminal |
| 2 | Add Chroma + lore corpus + retrieval before narration | Notice the DM referencing established lore instead of improvising inconsistently |
| 3 | Swap human input for the **player agent** (persona-driven, quantized model, think-and-decide node) | Watch an AI play the game according to a description you gave it |
| 4 | Add the human check-in interrupt | Optional pause for approval in human mode (`--checkin-every`) |
| 5 | Add the eval harness (retrieval metrics + goal-achievement scoring) | Run 2–3 different personas through the same scenario and compare, with numbers instead of vibes |
| 6 (stretch) | FastAPI wrapper, MCP tool server, deploy somewhere | Show it off as a real portfolio artifact |

Each phase should leave you with something that actually runs — don't move to the next layer until the current one is playable end to end.

---

## Tech stack summary

| Layer | Tool | Role |
|---|---|---|
| Model serving | Ollama | Runs DM model, player-agent model, embedding model |
| Orchestration | LangGraph | State machine, branching, checkpointing, interrupts |
| Structured output | Pydantic | Validates actions and game state |
| Retrieval | Chroma (or FAISS) | Stores/retrieves world lore and past events |
| Game rules | Plain Python | Combat/inventory/win-lose logic |
| Tracing | LangSmith or Langfuse | See what happened on any given turn |
| Evaluation | RAGAS + custom scorer | Retrieval quality + goal-achievement quality |
| Serving (stretch) | FastAPI | Deployable API/web app |
| Tooling (stretch) | MCP server | Exposes game actions as standard agent tools |

---

## Open questions to settle before coding

- **Setting/scope**: fixed short scenario (dungeon crawl, one session) vs. open-ended world? Start fixed — much easier to write lore and eval for.
- **Model sizes**: how small can the player-agent model go before its decisions get incoherent? Worth benchmarking 2–3 quant levels before committing.
- **Turn limit**: cap turns per session so games (and eval runs) don't run forever.
- **Persona format**: free-text description, or a light structured schema (goals, risk tolerance, values)? Structured is easier to eval against later.
- **Single vs. multi-agent play**: just one player agent for now, or design the state object so a second player agent could join later?

## Definition of done for MVP

- A human can play a full session start to finish, save, and resume it.
- Swapping in a player-agent persona produces a full autonomous playthrough with no human input.
- You can point to a trace of any given turn and explain why the DM said what it said, and why the player agent chose what it chose.
