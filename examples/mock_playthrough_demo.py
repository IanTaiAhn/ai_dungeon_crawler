"""Runs the real LangGraph dungeon-crawl graph end to end with mocks standing
in for Ollama (MockNarrator, MockEmbedder) -- same wiring as tests/helpers.py
uses for the test suite. No GPU/Ollama needed; `uv sync` is enough.

A single graph.invoke() call walks node -> edge -> node automatically,
looping turn after turn (get_action -> checkin -> resolve -> retrieve ->
narrate -> remember -> check_end -> back to get_action) until it either hits
a real interrupt() inside checkin_node, or check_end routes to END. So the
outer Python loop here only has to react at pause points, exactly like
cli.py's _run_until_done -- everything between pauses happens inside
LangGraph's runtime, not in this script.

Run it:
    uv run python examples/mock_playthrough_demo.py

See MOCK-MODE.md for what this demonstrates and why it works without Ollama.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from dungeon_crawler.agents import ScriptedActionProvider
from dungeon_crawler.checkpointing import checkpoint_serde
from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import LoreStore, MockEmbedder

SCRIPT = [
    "take rusty sword",
    "go north",
    "attack goblin",
    "attack goblin",
    "attack goblin",
    "attack goblin",
    "go east",
    "take ancient amulet",
    "take healing potion",
    "go down",
    "cast flame at crystal golem",
    "cast flame at crystal golem",
    "cast flame at crystal golem",
    "attack crystal golem",
    "attack crystal golem",
    "attack crystal golem",
    "attack crystal golem",
    "take frostbound crown",
]

lore_store = LoreStore(MockEmbedder())
checkpointer = InMemorySaver(serde=checkpoint_serde())
graph = build_graph(
    MockNarrator(),
    ScriptedActionProvider(SCRIPT),
    checkpointer,
    lore_store,
    checkin_every=3,  # pause before every combat action, and every 3rd turn otherwise
)

config = {"configurable": {"thread_id": "demo-1"}}

print("=" * 70)
print("invoke() #1 -- runs intro, then loops turns until first pause point")
print("=" * 70)
result = graph.invoke(new_game_state(), config)

call_n = 1
while "__interrupt__" in result:
    info = result["__interrupt__"][0].value
    print("\n--- paused: real langgraph.types.interrupt() fired inside checkin_node ---")
    print(f"  reason:          {info['reason']}")
    print(f"  upcoming turn:   {info['turn']}")
    print(f"  location:        {info['location']}")
    print(f"  DM said:         {info['narration']!r}")
    print(f"  proposed action: {info['proposed_action']!r}")
    print("  -> resuming with Command(resume='') (the human 'approve' response)")

    call_n += 1
    print(f"\n{'=' * 70}")
    print(f"invoke() #{call_n} -- resumes checkin_node, then loops until next pause point")
    print("=" * 70)
    result = graph.invoke(Command(resume=""), config)

print(f"\n{'#' * 70}")
print(f"# GAME OVER after {call_n} graph.invoke() calls total. outcome={result['outcome']!r}")
print(f"{'#' * 70}\n")

print("Full turn-by-turn log accumulated in GameState.log across every turn")
print("(this is what actually happened turn-by-turn, including the turns that")
print("passed without an interrupt -- LangGraph looped through them internally):\n")
for line in result["log"]:
    print(f"  {line}")

print(
    f"\nFinal state: location={result['location']!r} hp={result['hp']}/{result['max_hp']} "
    f"turn_count={result['turn_count']} inventory={result['inventory']}"
)

state_snapshot = graph.get_state(config)
print(
    f"\ngraph.get_state(config) after the run -- proof the checkpointer persisted it "
    f"under thread_id={config['configurable']['thread_id']!r}:"
)
print(f"  next node to run on resume: {state_snapshot.next!r} (empty tuple = finished)")
