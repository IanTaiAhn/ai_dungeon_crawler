# Checkpointing & Save System Explained

## What is `--thread-id`?

The `--thread-id` is a **save slot identifier**. Think of it like:
- Save Slot 1, Save Slot 2, Save Slot 3 in a traditional video game
- Each `thread_id` is a completely independent game session
- You can have multiple saved games and switch between them

### Examples:
```bash
# These are all DIFFERENT save slots:
uv run dungeon-crawler --thread-id my-first-run
uv run dungeon-crawler --thread-id speedrun-attempt
uv run dungeon-crawler --thread-id scout-playthrough
uv run dungeon-crawler --thread-id default  # (this is the default if you don't specify)
```

---

## How Save/Resume Works

### The Magic: LangGraph's Checkpointing System

LangGraph automatically saves the **entire game state** after EVERY node in the graph:

```
intro_node → [CHECKPOINT] → get_action_node → [CHECKPOINT] → checkin_node → [CHECKPOINT] → ...
```

Each checkpoint contains:
- Your location
- Your HP
- Your inventory
- Monster HP
- Quest flags
- The last narration
- The last action you took
- Turn count
- Everything in `GameState`

### The Code Flow

#### 1. **When you start the game** (cli.py lines 87-93):

```python
with closing(sqlite3.connect(args.db, check_same_thread=False)) as conn:
    checkpointer = SqliteSaver(conn, serde=checkpoint_serde())
    graph = build_graph(narrator, action_provider, checkpointer, lore_store, checkin_every=checkin_every)
    config = {"configurable": {"thread_id": args.thread_id}}

    existing = graph.get_state(config)
    initial = None if existing.values else new_game_state(persona=persona)
```

**What happens:**

1. **Connect to SQLite database** (`dungeon_crawler.sqlite`)
2. **Create a checkpointer** that knows how to serialize your custom Pydantic types
3. **Build the graph** with the checkpointer attached
4. **Create a config** with your thread_id

5. **Check if a save exists**:
   ```python
   existing = graph.get_state(config)
   ```
   - Queries the database: "Do I have any checkpoints for thread_id='default'?"
   - If yes: `existing.values` will contain the last saved state
   - If no: `existing.values` will be empty

6. **Decide what to do**:
   ```python
   initial = None if existing.values else new_game_state(persona=persona)
   ```
   - **If save exists** (`existing.values` is truthy): `initial = None`
     - This tells LangGraph: "Resume from the last checkpoint"
   - **If no save** (`existing.values` is empty/falsy): `initial = new_game_state(...)`
     - This tells LangGraph: "Start a fresh game with this initial state"

#### 2. **During gameplay** (automatic):

Every time a graph node completes, LangGraph:
```python
# Pseudocode of what LangGraph does internally:
def run_node(node_name, state, config):
    new_state = node_function(state)

    # AUTOMATIC CHECKPOINT after every node!
    checkpointer.save(
        thread_id=config["thread_id"],
        checkpoint_id=generate_uuid(),
        state=new_state,
        parent_checkpoint_id=previous_checkpoint_id
    )

    return new_state
```

This creates a **checkpoint chain** - a linked list of game states:

```
START
  ↓ checkpoint_id: abc123 (parent: None)
intro_node completed
  ↓ checkpoint_id: def456 (parent: abc123)
get_action_node completed
  ↓ checkpoint_id: ghi789 (parent: def456)
resolve_node completed
  ↓ checkpoint_id: jkl012 (parent: ghi789)
... and so on
```

---

## The Database Structure

### Tables:

#### **`checkpoints` table:**
```sql
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,           -- Your save slot ID ("default", "run-1", etc.)
    checkpoint_ns TEXT NOT NULL,       -- Namespace (usually empty)
    checkpoint_id TEXT NOT NULL,       -- Unique ID for this checkpoint (UUID)
    parent_checkpoint_id TEXT,         -- Points to the previous checkpoint (linked list)
    type TEXT,                         -- Serialization type ("msgpack")
    checkpoint BLOB,                   -- The actual game state (binary)
    metadata BLOB,                     -- Extra info (node name, timestamp, etc.)
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)
```

#### **`writes` table:**
Contains intermediate state updates during graph execution (technical detail, less important for understanding saves).

### Example Query:

```bash
# See all your saved games:
python -c "
import sqlite3
conn = sqlite3.connect('dungeon_crawler.sqlite')
cursor = conn.cursor()
cursor.execute('SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id')
for thread_id, count in cursor.fetchall():
    print(f'{thread_id}: {count} checkpoints')
"
```

Output:
```
default: 283 checkpoints
my-run: 45 checkpoints
scout-attempt: 120 checkpoints
```

---

## How Resume Works

When you run with an existing `thread_id`:

```bash
uv run dungeon-crawler --thread-id default
```

1. **Graph checks for existing state**:
   ```python
   existing = graph.get_state(config)
   # Queries: SELECT * FROM checkpoints WHERE thread_id = 'default' ORDER BY checkpoint_id DESC LIMIT 1
   ```

2. **If found, resume from last checkpoint**:
   ```python
   initial = None  # Signals: "Don't create new state, resume from saved"
   ```

3. **LangGraph loads the state**:
   - Deserializes the `checkpoint` BLOB
   - Reconstructs your `GameState` object with all fields
   - Continues execution from the next node after the last checkpoint

4. **If the last checkpoint was at game_over=True**:
   - The graph immediately goes to END
   - You see the final narration and outcome
   - This is what happened to you!

---

## Your Specific Problem

You ran:
```bash
uv run dungeon-crawler
```

This used the default `thread_id = "default"`, which had **283 saved checkpoints** from a previous playthrough.

The last checkpoint looked like:
```python
GameState(
    game_over=True,        # ← Game already ended!
    outcome="lose",        # ← Lost the game
    turn_count=40,         # ← Hit the turn limit
    last_narration="You back away, weapon raised...",
    # ... rest of state
)
```

So when you "resumed", the graph said:
- "Oh, `game_over=True`? I'm done here!"
- Printed the last narration
- Printed the outcome
- Exited immediately

---

## Serialization: How Complex Objects Are Saved

### The Challenge:

SQLite stores BLOBs (binary data), but `GameState` contains custom Pydantic objects:
```python
class GameState(BaseModel):
    intent: Intent               # Custom enum
    last_action: PlayerAction    # Custom Pydantic model
    persona: PersonaConfig       # Custom Pydantic model
    risk_tolerance: RiskTolerance  # Custom enum
    # ... etc
```

### The Solution (checkpointing.py):

```python
def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            Intent,
            RiskTolerance,
            PlayerAction,
            PersonaConfig
        ]
    )
```

**What this does:**
1. Uses **MessagePack** (like JSON but binary, faster, smaller)
2. **Allowlists** your custom types so they serialize correctly
3. LangGraph uses this to:
   - **Save**: `GameState` → msgpack bytes → SQLite BLOB
   - **Load**: SQLite BLOB → msgpack bytes → `GameState`

Without this, you'd get warnings/errors about unknown types.

---

## Best Practices

### 1. **Use Descriptive Thread IDs:**
```bash
# Good:
uv run dungeon-crawler --thread-id scout-run-2024-01-15
uv run dungeon-crawler --thread-id greedy-speedrun-attempt-3

# Less helpful:
uv run dungeon-crawler --thread-id a
uv run dungeon-crawler --thread-id test
```

### 2. **List Your Saved Games:**
```bash
python -c "
import sqlite3
conn = sqlite3.connect('dungeon_crawler.sqlite')
cursor = conn.cursor()
cursor.execute('''
    SELECT thread_id, COUNT(*) as turns, MAX(checkpoint_id) as last_checkpoint
    FROM checkpoints
    GROUP BY thread_id
''')
for thread_id, turns, last_checkpoint in cursor.fetchall():
    print(f'{thread_id}: {turns} turns saved')
"
```

### 3. **Delete Old Saves:**
```bash
# Delete a specific thread:
python -c "
import sqlite3
conn = sqlite3.connect('dungeon_crawler.sqlite')
conn.execute('DELETE FROM checkpoints WHERE thread_id = \"default\"')
conn.execute('DELETE FROM writes WHERE thread_id = \"default\"')
conn.commit()
print('Deleted thread: default')
"

# Or just delete the whole database:
rm dungeon_crawler.sqlite
```

### 4. **Fresh Start Every Time:**
```bash
# Use a timestamp or counter:
uv run dungeon-crawler --thread-id "run-$(date +%s)"

# Or manually:
uv run dungeon-crawler --thread-id run-1
uv run dungeon-crawler --thread-id run-2
# ... etc
```

---

## Advanced: Inspecting Saved State

Want to see what's in a checkpoint? Here's how:

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from dungeon_crawler.checkpointing import checkpoint_serde

conn = sqlite3.connect('dungeon_crawler.sqlite')
checkpointer = SqliteSaver(conn, serde=checkpoint_serde())

# Load state for a specific thread
config = {"configurable": {"thread_id": "default"}}
state = checkpointer.get(config)

if state:
    print(f"Location: {state.values['location']}")
    print(f"HP: {state.values['hp']}/{state.values['max_hp']}")
    print(f"Inventory: {state.values['inventory']}")
    print(f"Turn: {state.values['turn_count']}")
    print(f"Game Over: {state.values['game_over']}")
    print(f"Outcome: {state.values.get('outcome', 'N/A')}")
else:
    print("No saved game found")
```

---

## Key Takeaways

1. **`--thread-id`** = save slot identifier (like "Save 1", "Save 2")
2. **Every graph node** creates a checkpoint automatically
3. **SQLite stores** the serialized game state
4. **Resume behavior**: If checkpoint exists, resume from it; otherwise, start new
5. **Your issue**: Resumed from a game-over checkpoint
6. **Solution**: Use a new `--thread-id` or delete the old save

This system gives you:
- ✅ Automatic save after every turn
- ✅ Multiple save slots
- ✅ Resume from any point
- ✅ No manual "save game" command needed
- ✅ Crash-proof (state is persisted immediately)

It's like having autosave turned on in a modern video game, but with the ability to manage multiple save files manually via the `--thread-id` parameter.
