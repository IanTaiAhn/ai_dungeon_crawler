from langgraph.checkpoint.memory import InMemorySaver

from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import MockNarrator


def _scripted_actions(script):
    it = iter(script)

    def action_source(state):
        return next(it)

    return action_source


def _run(script, thread_id="t"):
    graph = build_graph(MockNarrator(), _scripted_actions(script), InMemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(new_game_state(), config)


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
