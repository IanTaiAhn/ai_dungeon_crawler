import pytest

from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import MockEmbedder
from dungeon_crawler.schemas import PersonaConfig
from dungeon_crawler.sessions import GameNotFoundError, GameServer

_WIN_SCRIPT = [
    "take rusty sword",
    "go north",
    "attack goblin",
    "attack goblin",
    "attack goblin",
    "attack goblin",
    "attack goblin",  # a few extra in case combat rolls run long
    "go east",
    "take ancient amulet",
    "go down",
    "take frostbound crown",
]


def _server():
    return GameServer(MockNarrator(), MockEmbedder())


def test_start_game_returns_awaiting_action_with_intro_narration():
    result = _server().start_game()
    assert result["status"] == "awaiting_action"
    assert result["turn"] == 1
    assert "thread_id" in result


def test_submit_action_advances_the_turn():
    server = _server()
    thread_id = server.start_game()["thread_id"]
    result = server.submit_action(thread_id, "wait")
    assert result["turn"] == 2


def test_full_playthrough_can_reach_a_terminal_outcome():
    server = _server()
    thread_id = server.start_game()["thread_id"]
    result = None
    for action in _WIN_SCRIPT:
        result = server.submit_action(thread_id, action)
        if result["status"] == "game_over":
            break
    assert result["status"] == "game_over"
    assert result["outcome"] in {"win", "lose"}  # combat is randomized; either is a valid terminal state


def test_submit_action_after_game_over_is_idempotent():
    server = _server()
    thread_id = server.start_game()["thread_id"]
    result = None
    for action in _WIN_SCRIPT + ["wait"] * 40:
        result = server.submit_action(thread_id, action)
        if result["status"] == "game_over":
            break
    assert result["status"] == "game_over"

    again = server.submit_action(thread_id, "wait")
    assert again == result


def test_submit_action_on_unknown_game_raises():
    server = _server()
    with pytest.raises(GameNotFoundError):
        server.submit_action("nonexistent", "wait")


def test_get_status_on_unknown_game_raises():
    server = _server()
    with pytest.raises(GameNotFoundError):
        server.get_status("nonexistent")


def test_get_status_reflects_current_state():
    server = _server()
    thread_id = server.start_game()["thread_id"]
    server.submit_action(thread_id, "take rusty sword")
    status = server.get_status(thread_id)
    assert status["inventory"] == ["rusty sword"]
    assert status["turn_count"] == 1
    assert status["persona"] is None


def test_get_status_reports_persona_name():
    server = _server()
    persona = PersonaConfig(name="Wren", goal="Explore cautiously", risk_tolerance="low")
    thread_id = server.start_game(persona=persona)["thread_id"]
    assert server.get_status(thread_id)["persona"] == "Wren"


def test_separate_games_do_not_share_state():
    server = _server()
    thread_a = server.start_game()["thread_id"]
    thread_b = server.start_game()["thread_id"]
    server.submit_action(thread_a, "take rusty sword")
    assert server.get_status(thread_a)["inventory"] == ["rusty sword"]
    assert server.get_status(thread_b)["inventory"] == []
