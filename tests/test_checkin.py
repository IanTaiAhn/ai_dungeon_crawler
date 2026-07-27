from langgraph.types import Command

from dungeon_crawler.graph import new_game_state
from helpers import build_test_graph


def test_checkin_disabled_by_default_even_for_combat():
    graph = build_test_graph(["attack goblin"] * 3, checkin_every=None)
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke(new_game_state(), config)
    assert "__interrupt__" not in result
    assert result["outcome"] == "lose"  # ran out the turn clock without ever pausing
    assert result["turn_count"] == 40


def test_combat_always_triggers_a_checkin_when_enabled():
    graph = build_test_graph(["attack goblin"] * 3, checkin_every=100)  # interval far off; only combat should fire
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke(new_game_state(), config)

    assert "__interrupt__" in result
    info = result["__interrupt__"][0].value
    assert info["reason"] == "combat"
    assert info["proposed_action"] == "attack goblin"
    assert info["turn"] == 1


def test_approving_a_checkin_lets_the_proposed_action_resolve():
    graph = build_test_graph(["attack goblin"] + ["wait"] * 39, checkin_every=100)
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke(new_game_state(), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=""), config)  # empty string approves
    assert "goblin" in result["log"][1]  # the attack's engine result was narrated


def test_overriding_a_checkin_replaces_the_action():
    graph = build_test_graph(["attack goblin"] + ["wait"] * 39, checkin_every=100)
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke(new_game_state(), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="wait"), config)  # override: wait instead of attacking
    while "__interrupt__" in result:
        result = graph.invoke(Command(resume=""), config)

    assert result["outcome"] == "lose"  # never actually attacked, ran out the clock
    assert "goblin" not in result["last_engine_result"]


def test_turn_interval_triggers_checkin_on_schedule():
    graph = build_test_graph(["wait"] * 10, checkin_every=3)
    config = {"configurable": {"thread_id": "t"}}
    result = graph.invoke(new_game_state(), config)

    assert "__interrupt__" in result
    info = result["__interrupt__"][0].value
    assert info["reason"] == "every 3 turns"
    assert info["turn"] == 3
