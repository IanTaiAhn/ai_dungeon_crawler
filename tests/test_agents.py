from dungeon_crawler.agents import ScriptedActionProvider, _build_agent_prompt
from dungeon_crawler.schemas import GameState, Intent


def test_scripted_action_provider_parses_each_command_in_order():
    provider = ScriptedActionProvider(["go north", "attack goblin"])
    state = GameState(location="entrance")

    first = provider.get_action(state)
    second = provider.get_action(state)

    assert first.intent is Intent.MOVE
    assert first.direction == "north"
    assert second.intent is Intent.ATTACK
    assert second.target == "goblin"


def test_scripted_action_provider_falls_back_to_wait_when_exhausted():
    provider = ScriptedActionProvider(["wait"])
    state = GameState(location="entrance")

    provider.get_action(state)
    fallback = provider.get_action(state)

    assert fallback.intent is Intent.WAIT


def test_agent_prompt_includes_persona_relevant_state():
    state = GameState(
        location="guard_room",
        hp=7,
        max_hp=10,
        inventory=["rusty sword"],
        last_narration="A goblin snarls at you.",
        retrieved_lore=["The goblin in the guard room is territorial."],
    )
    prompt = _build_agent_prompt(state)

    assert "guard_room" in prompt
    assert "7/10" in prompt
    assert "rusty sword" in prompt
    assert "goblin snarls" in prompt
    assert "territorial" in prompt
    assert "move" in prompt  # valid intents listed
