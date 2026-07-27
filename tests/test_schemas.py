import pytest
from pydantic import ValidationError

from dungeon_crawler.schemas import GameState, Intent, PersonaConfig, PlayerAction


def test_player_action_requires_intent():
    with pytest.raises(ValidationError):
        PlayerAction(raw_text="go north")


def test_player_action_minimal():
    action = PlayerAction(intent=Intent.MOVE, direction="north", raw_text="go north")
    assert action.intent is Intent.MOVE
    assert action.target is None


def test_game_state_defaults():
    state = GameState(location="entrance")
    assert state.hp == state.max_hp == 10
    assert state.turn_count == 0
    assert state.inventory == []
    assert state.persona is None
    assert state.game_over is False


def test_persona_config_requires_goal():
    with pytest.raises(ValidationError):
        PersonaConfig(name="Scout")


def test_game_state_holds_a_persona():
    persona = PersonaConfig(name="Scout", goal="Find the amulet without fighting")
    state = GameState(location="entrance", persona=persona)
    assert state.persona.goal == "Find the amulet without fighting"
