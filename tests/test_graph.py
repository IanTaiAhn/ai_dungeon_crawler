from langgraph.checkpoint.memory import InMemorySaver

from dungeon_crawler.agents import ScriptedActionProvider
from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import LoreStore, MockEmbedder
from dungeon_crawler.schemas import PersonaConfig


def _run(script, thread_id="t", narrator=None, lore_store=None, persona=None):
    """`script` is a list of raw text commands - ScriptedActionProvider parses
    them the same way a human's typed input would be, then falls back to
    "wait" once exhausted (a script shorter than the session length must not
    exhaust the underlying iterator, since StopIteration raised inside a
    LangGraph node surfaces as a RuntimeError per PEP 479). Standing in for an
    OllamaPlayerAgent lets these tests exercise the persona-driven wiring
    without needing a real model.
    """
    narrator = narrator or MockNarrator()
    lore_store = lore_store or LoreStore(MockEmbedder())
    graph = build_graph(narrator, ScriptedActionProvider(script), InMemorySaver(), lore_store)
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(new_game_state(persona=persona), config)


def test_full_playthrough_can_be_won():
    final = _run(
        [
            "take rusty sword",
            "go north",
            "attack goblin",
            "attack goblin",
            "attack goblin",
            "go east",
            "take ancient amulet",
        ]
    )
    assert final["outcome"] == "win"
    assert final["location"] == "treasure_room"
    assert "ancient amulet" in final["inventory"]


def test_moving_into_a_wall_does_not_change_location():
    final = _run(["go west"] * 40)
    assert final["location"] == "entrance"
    assert final["outcome"] == "lose"  # ran out the turn clock


def test_taking_an_absent_item_fails_gracefully():
    final = _run(["take dragon egg"] + ["wait"] * 39)
    assert "dragon egg" not in final["inventory"]
    assert final["outcome"] == "lose"


def test_game_ends_at_the_turn_limit_if_nothing_else_happens():
    final = _run(["wait"] * 40)
    assert final["turn_count"] == 40
    assert final["game_over"] is True
    assert final["outcome"] == "lose"


def test_retrieved_lore_reaches_the_narrator():
    narrator = MockNarrator()
    lore_store = LoreStore(MockEmbedder())
    lore_store.add_lore(["A crumbling stone entrance, torchlight flickering against moss-covered walls."])
    _run(["wait"], narrator=narrator, lore_store=lore_store)
    assert narrator.last_retrieved_lore
    assert "torchlight" in narrator.last_retrieved_lore[0]


def test_turn_events_are_written_back_and_later_retrievable():
    lore_store = LoreStore(MockEmbedder())
    _run(["take rusty sword", "go north"], lore_store=lore_store)
    results = lore_store.retrieve("rusty sword", k=5)
    assert any("rusty sword" in r for r in results)


def test_persona_config_flows_through_to_persisted_state():
    persona = PersonaConfig(name="Wren", goal="Recover the amulet cautiously", risk_tolerance="low")
    final = _run(["wait"] * 40, persona=persona)
    assert final["persona"].name == "Wren"
    assert final["persona"].goal == "Recover the amulet cautiously"
