# Which Anthropic Workflow Pattern Is This? A Guide

Anthropic's ["Building Effective Agents"](https://www.anthropic.com/research/building-effective-agents)
draws a line between **workflows** (LLMs and tools orchestrated through
predefined code paths) and **agents** (systems where the LLM dynamically
directs its own process and tool usage). It then names six recurring shapes.
This doc walks through all six, then maps this codebase onto them with real
file/line references - the goal is to leave you able to classify *any*
LLM system you look at next, not just this one.

---

## 🧭 The six shapes, briefly

| # | Shape | Core idea | Who's in control of the path? |
|---|-------|-----------|-------------------------------|
| 1 | **Prompt chaining** | Fixed sequence of LLM calls; each step's output feeds the next | The code (path is fixed) |
| 2 | **Routing** | Classify the input, dispatch to one of several specialized paths | The code (path is chosen once, then fixed) |
| 3 | **Parallelization** | Run several LLM calls concurrently (sectioning or voting), then combine | The code (path is fixed, just fanned out) |
| 4 | **Orchestrator-workers** | A central LLM breaks a task into subtasks *at runtime* and delegates | The LLM (subtask list isn't predetermined) |
| 5 | **Evaluator-optimizer** | One LLM generates, another critiques, loop until it passes | The LLM (iteration count isn't predetermined) |
| 6 | **Autonomous agent** | No fixed path at all - the model perceives environment state, picks its own next action/tool, observes the result, repeats until a stopping condition | The LLM (the *entire* loop, not just a step) |

Patterns 1-5 are still **workflows** in Anthropic's sense: however clever, the
control flow is code you could draw as a static diagram before running it.
Pattern 6 is where that stops being true - the diagram would have to be
drawn *while* the system runs, because the model's own decisions change
which edges get taken.

---

## 🏰 Where this project lands: Autonomous Agent (#6), as an umbrella

The top-level shape of `graph.py` is an **autonomous agent loop**, and the
other five patterns show up *nested inside individual turns* of that loop
rather than describing the system as a whole. That's why "umbrella" is the
right word - one big agent loop wrapped around several small, fixed
workflow steps.

```
┌───────────────────────────────────────────────────────────────────┐
│  AUTONOMOUS AGENT  (graph.py's turn loop - runs until game_over)   │
│                                                                     │
│   get_action ──► checkin ──► resolve ──► retrieve ──► narrate ──►  │
│       ▲                        │           └──chain──┘             │
│       │                        └─router─┘                          │
│       └──────────────────── remember ── check_end ─────────────────┘
│                                                                     │
└───────────────────────────────────────────────────────────────────┘
```

### Why it's an agent, not a fixed workflow

Anthropic's test: does the LLM dynamically direct its own process, choosing
its own next action from live environment state, in a loop with no
predetermined length?

- **`get_action_node`** (`src/dungeon_crawler/graph.py:122`) delegates to
  whichever `ActionProvider` is driving the session. In autonomous mode,
  that's `OllamaPlayerAgent` (`agents.py:176`) - each turn it looks at the
  *current* `GameState` (HP, inventory, retrieved lore, spell charges) and
  freely picks one of the `Intent` values (`MOVE`, `ATTACK`, `CAST_SPELL`,
  `TAKE_ITEM`, ...). Nothing in the code predetermines which intent comes
  next; that choice is made by the model, per turn, from the environment.
- The loop itself has **no fixed length**. `check_end_node` (`graph.py:302`)
  and the conditional edge `route_after_check` (`graph.py:307`) send control
  back to `get_action` indefinitely until `state.game_over` - win, lose, or
  turn limit. You can't draw "the" execution path ahead of time; it depends
  on what the agent does.
- The loop is a genuine **perceive → act → observe → repeat** cycle: the
  agent perceives state (`get_action`), acts (`resolve`), observes the
  consequence via retrieval + narration (`retrieve`/`narrate`), and that
  observation becomes part of the state it perceives next turn. This is the
  environment-feedback loop Anthropic describes as the hallmark of an agent.

### The workflow patterns nested inside each turn

- **Routing** (#2) - `resolve_node` (`graph.py:153`) is a router: it
  classifies `action.intent` and dispatches to one deterministic branch per
  case (`MOVE` → movement logic, `ATTACK`/`CAST_SPELL` → `_resolve_combat`,
  `TAKE_ITEM`, `USE_ITEM`, ...). The important nuance: it's routing on the
  *agent's own already-chosen* intent, not classifying raw user input to
  decide what to do next. Routing is a step inside the loop, not the loop's
  shape.
- **Prompt chaining** (#1) - `retrieve_node → narrate_node`
  (`graph.py:287-295`) is a fixed, always-both-steps, always-same-order
  chain: fetch lore, then feed it to the narrator LLM. No branching, no
  variable length - a textbook two-step chain living inside one turn of the
  bigger loop.
- **A human-in-the-loop gate, evaluator-*shaped* but not evaluator-optimizer**
  - `checkin_node` (`graph.py:126`) pauses via a real LangGraph `interrupt()`
    before combat actions (or every N turns) and lets a human approve or
    override the agent's proposed action. It rhymes with pattern #5's
    "check before proceeding," but the evaluator is a *person*, it's
    optional (off by default, disabled entirely in autonomous mode), and
    there's no generate-critique-regenerate cycle - just approve-or-replace.
    Worth naming, but it isn't a clean instance of #5.

### Patterns that are absent, on purpose

- **Parallelization** (#3) - every node runs strictly sequentially; nothing
  fans out into concurrent calls or votes.
- **Orchestrator-workers** (#4) - no LLM is decomposing the turn into
  subtasks and delegating to sub-agents. `_resolve_combat`
  (`graph.py:62-101`) looks like it could be a "worker," but it's plain
  deterministic Python shared by two call sites, not something an LLM
  spun up at runtime.

---

## 🎓 How to classify a system yourself

Ask, in order:

1. **Is there a loop with no fixed length, where the model picks its own
   next action from live state?** If yes → agent (#6), full stop, even if
   the loop contains routers/chains inside it (they're details, not the
   shape).
2. **If no loop like that: is a central LLM breaking the task into
   subtasks at runtime?** → orchestrator-workers (#4).
3. **Is one LLM's output checked/critiqued by another, looping until it
   passes?** → evaluator-optimizer (#5).
4. **Are multiple LLM calls run concurrently and combined?** →
   parallelization (#3).
5. **Is the input classified once, to pick a fixed downstream path?** →
   routing (#2).
6. **Otherwise, is it just a fixed sequence of LLM calls?** → prompt
   chaining (#1).

Applied here: step 1 answers yes immediately (`get_action` → LLM chooses →
loop continues until `game_over`), which is why "agent, with chaining and
routing nested inside" is the right classification rather than trying to
force the whole system into #1 or #2.

---

## 📚 Further reading

- **`ARCHITECTURE.md`** - full system architecture and module breakdown
- **`OBSERVABILITY.md`** - how the turn loop is traced (useful for *seeing*
  the agent's actual runtime path, not just its code)
- Anthropic, ["Building Effective Agents"](https://www.anthropic.com/research/building-effective-agents) -
  the source of this taxonomy
