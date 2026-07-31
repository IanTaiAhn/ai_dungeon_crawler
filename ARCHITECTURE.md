# Architecture Guide: AI Dungeon Crawler

## 🎮 What This Project Is

This is an **AI-powered text adventure game** where you explore a dungeon with three key innovations:

1. **The DM is an AI** that narrates your actions using retrieval-augmented generation (RAG)
2. **The player can be an AI too** with different personalities/goals
3. **Everything is measurable** - you can score how well the AI performs

Think of it as a fully autonomous game where two AIs can play against each other while you watch.

---

## 📊 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     You (or an AI Persona)                   │
└────────────────────────┬────────────────────────────────────┘
                         │ Types: "go north"
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Parser (parser.py)                        │
│          Converts text → Intent (MOVE, ATTACK, etc.)         │
└────────────────────────┬────────────────────────────────────┘
                         │ PlayerAction
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Game Engine (game_logic.py)                     │
│       Deterministic rules: combat, inventory, HP             │
└────────────────────────┬────────────────────────────────────┘
                         │ Outcome: "You hit the goblin!"
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 Retrieval (retrieval.py)                     │
│      Chroma DB fetches relevant lore about what happened     │
└────────────────────────┬────────────────────────────────────┘
                         │ Retrieved chunks
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Narrator (llm.py)                          │
│         Ollama LLM narrates outcome in DM's voice            │
└────────────────────────┬────────────────────────────────────┘
                         │ "Your blade finds its mark..."
                         ▼
                    [Repeat next turn]
```

---

## 🎯 The Game Loop (graph.py)

This is the heart of the system. It's a **LangGraph state machine** that runs every turn:

```python
START
  ↓
intro_node          # DM sets the scene with opening narration
  ↓
get_action_node     # Player (human or AI) decides what to do
  ↓
checkin_node        # (Optional) Pause for human approval
  ↓
resolve_node        # Game engine applies the action (dice rolls, HP changes)
  ↓
retrieve_node       # Fetch relevant lore from Chroma
  ↓
narrate_node        # DM narrates what happened
  ↓
remember_node       # Store this turn's events back into Chroma
  ↓
check_end_node      # Did you win/lose/hit turn limit?
  ↓
[Loop back to get_action OR END]
```

### Key Insight: **The LLM never decides outcomes**
- **Bad**: LLM decides "you hit the goblin" (hallucination risk)
- **Good**: Game engine rolls dice → LLM narrates the result

This keeps the game fair and debuggable.

---

## 🤖 The Three Ways to Play

### 1. **Human Mode** (HumanActionProvider)
```bash
uv run dungeon-crawler
```

- You type commands at a `>` prompt
- `parser.py` converts "go north" → `Intent.MOVE, direction="north"`
- Game engine resolves it
- DM narrates the result

### 2. **Autonomous AI Mode** (OllamaPlayerAgent)
```bash
uv run dungeon-crawler --persona personas/cautious_scout.json
```

- **No human input needed!**
- Each turn, the AI agent gets a persona config:
  ```json
  {
    "name": "Wren the Scout",
    "goal": "Map out the dungeon safely",
    "risk_tolerance": "low",
    "values": ["caution", "thoroughness"]
  }
  ```
- The agent uses structured output to generate a `PlayerAction`
- Runs until game over (win/lose/turn limit)

### 3. **Server Mode** (InterruptActionProvider)
```bash
uvicorn dungeon_crawler.api:app_factory --factory
```

- Exposes REST API: `POST /games` to start, `POST /games/{id}/actions` to submit turns
- Or MCP tool server: external agents can call `take_action("go north")`

---

## 🧠 The RAG System (retrieval.py)

### Two Collections in Chroma:

1. **Lore collection** (static, loaded once):
   - `lore/world.md` → "The Sunken Outpost is an abandoned border keep..."
   - `lore/history.md` → "The garrison sealed an artifact before fleeing..."
   - `lore/npcs.md` → "Goblins are territorial scavengers..."

2. **Event collection** (dynamic, grows each turn):
   - Turn 0: "The adventure begins in the entrance"
   - Turn 1: "You took the rusty sword"
   - Turn 2: "You attacked the goblin and dealt 4 damage"

### How It Works:
```python
# Before narration:
query = "You hit the goblin for 4 damage"
chunks = lore_store.retrieve(query, k=3)
# → ["Goblins are territorial...", "The guard room...", ...]

narrator.narrate(action, result, retrieved_lore=chunks)
# → DM uses chunks to make narration consistent with established lore

# After narration:
lore_store.add_event("Turn 5: goblin defeated", turn=5)
# → Future turns can retrieve "what happened earlier"
```

**Why this matters**: The DM "remembers" what happened 20 turns ago and references it!

---

## 🎭 Personas & Goal-Driven Play

Each persona is a JSON file defining **how the AI should behave**:

```json
{
  "name": "Bram the Looter",
  "goal": "Grab valuable items quickly",
  "risk_tolerance": "high",
  "values": ["greed", "speed", "opportunism"]
}
```

The agent gets this as a **system prompt**:
```
You are playing as Bram the Looter. Your goal: Grab valuable items quickly.
Risk tolerance: high. Values: greed, speed, opportunism.

Current situation:
- Location: entrance
- HP: 10/10
- Inventory: empty
- Available exits: north

What do you do?
```

The AI then generates a structured `PlayerAction` (not free text!):
```python
PlayerAction(
    intent=Intent.MOVE,
    direction="north",
    raw_text="rush north to find treasure"
)
```

---

## 📈 Evaluation System (evaluation.py)

### Two Metrics:

1. **Retrieval Quality** (`evaluation/lore_qa.json`):
   ```json
   {
     "question": "Who sealed the artifact?",
     "expected_keywords": ["paymaster", "garrison", "seal"]
   }
   ```
   - Retrieves chunks for each question
   - Checks if expected keywords appear in top-k results
   - Outputs **recall@k** score

2. **Goal Achievement** (LLM judge):
   - Reads full game transcript
   - Reads persona's stated goal
   - Scores 1-5 with rationale:
     ```
     Score: 4/5
     Rationale: "Wren successfully mapped all rooms and retrieved
     the amulet without unnecessary combat, consistent with their
     cautious approach."
     ```

---

## 🔧 Checkpointing & Save/Resume

Uses **LangGraph's built-in checkpointer** with SQLite:

```python
checkpointer = SqliteSaver(conn, serde=checkpoint_serde())
graph = build_graph(..., checkpointer=checkpointer)

config = {"configurable": {"thread_id": "my-save-slot"}}
graph.invoke(initial_state, config)  # Saves after every node

# Later:
graph.invoke(None, config)  # Resumes from last checkpoint!
```

Every turn is automatically saved. You can:
- Close the game mid-session
- Run `dungeon-crawler --thread-id my-save-slot` later
- Pick up exactly where you left off

---

## 🧪 Testing Philosophy

**All tests run WITHOUT Ollama** using mocks:

```python
graph = build_test_graph(
    script=["go north", "attack goblin", "take amulet"],  # Scripted actions
    narrator=MockNarrator(),      # Returns deterministic narration
    lore_store=MockLoreStore()    # Returns deterministic chunks
)

result = graph.invoke(new_game_state())
assert result["location"] == "treasure_room"
assert result["game_over"] == True
```

This means:
- ✅ Tests run in CI without GPU/Ollama
- ✅ Fast (~seconds, not minutes)
- ✅ Deterministic (no flaky LLM outputs)

---

## 🎪 The Three Serving Modes

| Mode | How to Run | Use Case |
|------|-----------|----------|
| **CLI** | `uv run dungeon-crawler` | Local play, testing personas |
| **REST API** | `uvicorn dungeon_crawler.api:app_factory --factory` | Web frontend, mobile app |
| **MCP Server** | `python -m dungeon_crawler.mcp_server` | Claude Desktop, other MCP clients can play the game as a tool |

All three modes use the **same graph**, just different action providers!

---

## 🔥 What Makes This Interesting

1. **LangGraph orchestration**: Shows how to build a complex multi-step workflow with checkpointing and conditional routing

2. **RAG done right**: Lore stays consistent because the DM retrieves before narrating, and new events are stored for later retrieval

3. **Structured outputs**: The AI agent doesn't generate free text that gets parsed - it generates a validated Pydantic object directly

4. **Separation of concerns**:
   - Game logic = boring deterministic Python
   - Narration = creative LLM work
   - Actions = either human OR AI (same interface)

5. **Evaluation as a first-class feature**: Not "vibes" - actual numeric scores for retrieval and goal-achievement

---

## 🚀 Quick Mental Model

```
Scenario (3 rooms, 1 goblin, 1 amulet)
    ↓
Graph orchestrates the loop
    ↓
Player decides → Engine resolves → Chroma retrieves → DM narrates
    ↓
Repeat until win/lose/turn limit
    ↓
Evaluation scores how well the AI played
```

The whole thing is **LangGraph + Ollama + Chroma + Pydantic** glued together with really clean abstractions.

---

## 📁 Repository Structure

```
C:\Users\ianta\ai_dungeon_crawler\
├── src/dungeon_crawler/          # Main application source code
├── tests/                        # Test suite
├── personas/                     # Player agent configuration files
├── lore/                        # Lore corpus (markdown) for RAG
├── evaluation/                  # Evaluation datasets and scoring
├── dungeon_crawler_chroma/      # Persistent vector store (Chroma database)
├── pyproject.toml              # Project configuration (uv, dependencies)
├── running-locally.md          # Quick start guide
├── ai-dungeon-master-project-plan.md  # Detailed project architecture
└── compute-requirements.md     # Hardware/model requirements
```

### Core Modules

#### **Game Engine & State Management**

| File | Purpose |
|------|---------|
| `schemas.py` | Pydantic models: `Intent`, `PlayerAction`, `PersonaConfig`, `GameState`, `RiskTolerance` |
| `scenario.py` | Static dungeon layout: 3-room fixed scenario with rooms, monsters, starting items |
| `game_logic.py` | Deterministic rules: combat resolution (d20+bonus vs AC), damage, inventory, win/lose checks |
| `graph.py` | LangGraph orchestration: turn loop (intro → get-action → checkin → resolve → retrieve → narrate → remember → check-end) |

#### **Agent & Action Handling**

| File | Purpose |
|------|---------|
| `agents.py` | Action providers: `HumanActionProvider` (terminal), `OllamaPlayerAgent` (autonomous LLM-driven), `ScriptedActionProvider` (tests), `InterruptActionProvider` (served games) |
| `parser.py` | Rule-based parser: converts free text ("go north", "attack goblin") into `PlayerAction` intents |

#### **LLM Integration**

| File | Purpose |
|------|---------|
| `llm.py` | Narrator interface: `OllamaNarrator` (real Ollama model), `MockNarrator` (deterministic stand-in for tests/sandbox) |

#### **Retrieval-Augmented Generation (RAG)**

| File | Purpose |
|------|---------|
| `retrieval.py` | Lore RAG: `Embedder` interface, `OllamaEmbedder` (real), `MockEmbedder` (deterministic hashing), `LoreStore` (Chroma-backed vector DB) |

#### **Serving & API**

| File | Purpose |
|------|---------|
| `api.py` | FastAPI wrapper: `/games` (POST to start), `/games/{id}/actions` (submit turn), `/games/{id}` (status) |
| `sessions.py` | `GameServer`: manages one compiled graph serving multiple concurrent games via thread_id |
| `mcp_server.py` | MCP tool server: exposes `start_game`, `take_action`, `check_inventory`, `save_game`, `roll_dice` as standard MCP tools |

#### **Evaluation & Quality Metrics**

| File | Purpose |
|------|---------|
| `evaluation.py` | Two-part scorer: retrieval quality (gold Q&A recall@k), goal-achievement (LLM judge or heuristic mock) |

#### **Persistence**

| File | Purpose |
|------|---------|
| `checkpointing.py` | Shared serializer config for LangGraph's SQLite checkpointer (allowlists custom Pydantic types) |

---

## 🎯 Entry Points

**CLI Commands** (configured in `pyproject.toml`):

- **`dungeon-crawler`** → Terminal-based play (human or persona-driven)
- **`dungeon-crawler-eval`** → Evaluation harness (retrieval quality + goal achievement scoring)

**Key CLI Flags**:
- `--thread-id`: Save slot name (default: "default")
- `--model`: DM narrator model (default: "qwen2.5:7b")
- `--embedding-model`: Lore RAG embedder (default: "nomic-embed-text")
- `--player-model`: Autonomous agent model (default: "llama3.2:3b")
- `--persona`: Path to persona JSON to play autonomously
- `--checkin-every`: Pause frequency for human approval (human mode only, disabled in autonomous mode)
- `--lore-dir`, `--chroma-dir`, `--db`: Path configurations

---

## 🧩 Dependency Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Model serving** | Ollama (local) | DM narrator, player agent, embeddings |
| **Orchestration** | LangGraph 0.2+ | State machine, graph compilation, checkpointing, interrupts |
| **Structured types** | Pydantic 2.7+ | Validates actions, schemas, game state |
| **Retrieval** | Chroma 0.5+ | Vector store for lore corpus & dynamic events |
| **LLM chains** | LangChain + LangChain-Ollama | Model integration |
| **Serving** | FastAPI 0.140.7+ | HTTP API |
| **Async server** | Uvicorn 0.51.0+ | ASGI server for FastAPI |
| **Tool protocol** | MCP 1.28.1+ | Model Context Protocol for tool exposure |
| **Testing** | pytest 9.1.1+ | Test runner |

---

## 📚 Further Reading

- **`running-locally.md`** - Step-by-step setup guide
- **`ai-dungeon-master-project-plan.md`** - Original design document with 7-layer breakdown
- **`compute-requirements.md`** - Hardware specs and model sizing guidance

---

## 🎓 Key Takeaways

This project demonstrates:

✅ **LangGraph** for stateful, resumable agent workflows
✅ **RAG** with dynamic memory (lore + runtime events)
✅ **Structured outputs** for reliable AI agent behavior
✅ **Separation of LLM narration from deterministic game logic**
✅ **Multiple serving modes** from a single graph
✅ **Evaluation-first design** with measurable quality metrics
✅ **Production-ready patterns**: checkpointing, error handling, testing without LLMs

It's a complete end-to-end system showing how to build autonomous AI agents that are both creative (narration) and reliable (game mechanics).
