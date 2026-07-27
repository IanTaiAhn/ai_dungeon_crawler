"""Turn-taking strategies that decide the next PlayerAction: a human at a
terminal, an autonomous LLM-driven player agent following a PersonaConfig, or
a scripted stand-in for the sandbox and tests. All three implement the same
ActionProvider interface, so the graph doesn't care which one is driving.
"""

from __future__ import annotations

from typing import Protocol

from dungeon_crawler.parser import parse_action
from dungeon_crawler.schemas import GameState, Intent, PersonaConfig, PlayerAction

PLAYER_AGENT_SYSTEM_PROMPT = (
    "You are playing a text adventure as {name}. Your goal this session: "
    "{goal}\n"
    "Risk tolerance: {risk_tolerance}. Values to weigh when deciding: "
    "{values}.\n"
    "Decide your next action from the current situation. Be decisive - "
    "commit to an action rather than deliberating. Stay in character and "
    "consistent with your stated goal across turns.\n"
    "Fill in: intent (one of the valid intents listed below), target (the "
    "NPC/item/object, if any), direction (only for the move intent), and "
    "raw_text (a short first-person phrase describing the action, e.g. "
    "'go north' or 'attack the goblin')."
)


class ActionProvider(Protocol):
    def get_action(self, state: GameState) -> PlayerAction:
        """Decide the next action given the current game state."""
        ...


class HumanActionProvider:
    """Prompts a human at the terminal, then parses their free text."""

    def get_action(self, state: GameState) -> PlayerAction:
        print(f"\n{state.last_narration}\n")
        raw = input("> ")
        return parse_action(raw)


class OllamaPlayerAgent:
    """Autonomous player agent: a smaller/quantized model decides each turn's
    action from its PersonaConfig, via structured output validated straight
    into a PlayerAction (no free-text parsing step, unlike the human path).
    """

    def __init__(self, persona: PersonaConfig, model: str = "llama3.2:3b", temperature: float = 0.3) -> None:
        from langchain_ollama import ChatOllama

        self._persona = persona
        self._structured_llm = ChatOllama(model=model, temperature=temperature).with_structured_output(PlayerAction)

    def get_action(self, state: GameState) -> PlayerAction:
        print(f"\n{state.last_narration}\n")
        system = PLAYER_AGENT_SYSTEM_PROMPT.format(
            name=self._persona.name,
            goal=self._persona.goal,
            risk_tolerance=self._persona.risk_tolerance.value,
            values=", ".join(self._persona.values) or "none specified",
        )
        result = self._structured_llm.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": _build_agent_prompt(state)},
            ]
        )
        action = result if isinstance(result, PlayerAction) else PlayerAction.model_validate(result)
        print(f"> {action.raw_text}")
        return action


class ScriptedActionProvider:
    """Deterministic stand-in for an LLM player agent - cycles through a
    scripted list of raw text commands, parsed the same way a human's would
    be. Used in the sandbox (no Ollama/GPU here) and in tests.
    """

    def __init__(self, script: list[str]) -> None:
        self._remaining = iter(script)

    def get_action(self, state: GameState) -> PlayerAction:
        return parse_action(next(self._remaining, "wait"))


def _build_agent_prompt(state: GameState) -> str:
    lines = [
        f"Narration: {state.last_narration}",
        f"Location: {state.location}",
        f"HP: {state.hp}/{state.max_hp}",
        f"Inventory: {', '.join(state.inventory) or 'empty'}",
    ]
    if state.retrieved_lore:
        lines.append("Relevant lore/history:")
        lines.extend(f"- {chunk}" for chunk in state.retrieved_lore)
    lines.append(f"Valid intents: {', '.join(i.value for i in Intent)}")
    return "\n".join(lines)
