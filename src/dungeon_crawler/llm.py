"""DM narration behind a small interface, so the graph can run against a real
Ollama model locally or a scripted mock anywhere Ollama isn't available (like
this sandbox, or in tests).
"""

from __future__ import annotations

from typing import Protocol

from dungeon_crawler.schemas import GameState, PlayerAction

DM_SYSTEM_PROMPT = (
    "You are the dungeon master for a text adventure. Narrate vividly but "
    "briefly (2-4 sentences). Stay consistent with the established location, "
    "inventory, and events. Never decide the outcome of dice-based actions "
    "yourself - the game engine resolves those and tells you the result to "
    "narrate."
)


class Narrator(Protocol):
    def narrate(
        self, state: GameState, action: PlayerAction | None, retrieved_lore: list[str] | None = None
    ) -> str:
        """Produce the next narration beat given the current state, the
        action just taken (None on the very first turn), and any lore/event
        chunks retrieved for grounding."""
        ...


class OllamaNarrator:
    """Real narrator, backed by a local Ollama model."""

    def __init__(self, model: str = "qwen2.5:7b", temperature: float = 0.8) -> None:
        from langchain_ollama import ChatOllama

        self._llm = ChatOllama(model=model, temperature=temperature)

    def narrate(
        self, state: GameState, action: PlayerAction | None, retrieved_lore: list[str] | None = None
    ) -> str:
        prompt = _build_prompt(state, action, retrieved_lore)
        response = self._llm.invoke(
            [
                {"role": "system", "content": DM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        return response.content


class MockNarrator:
    """Deterministic stand-in for Ollama. Cycles through scripted lines if
    given any, otherwise echoes a template - good enough to exercise the graph
    without a real model, e.g. in this sandbox or in unit tests. Records the
    last retrieved_lore it was called with, so tests can assert retrieval
    actually reached the narrator.
    """

    def __init__(self, scripted_lines: list[str] | None = None) -> None:
        self._lines = scripted_lines or []
        self._calls = 0
        self.last_retrieved_lore: list[str] | None = None

    def narrate(
        self, state: GameState, action: PlayerAction | None, retrieved_lore: list[str] | None = None
    ) -> str:
        self.last_retrieved_lore = retrieved_lore
        if self._calls < len(self._lines):
            line = self._lines[self._calls]
        elif action is None:
            line = f"You find yourself in {state.location}."
        else:
            line = f"You {action.intent.value}" + (f" {action.target}" if action.target else "") + "."
        self._calls += 1
        return line


def _build_prompt(state: GameState, action: PlayerAction | None, retrieved_lore: list[str] | None) -> str:
    lines = [
        f"Location: {state.location}",
        f"HP: {state.hp}/{state.max_hp}",
        f"Inventory: {', '.join(state.inventory) or 'empty'}",
    ]
    if action is not None:
        lines.append(f"Player action: {action.raw_text!r} (parsed as {action.intent.value} {action.target or ''})")
    if state.last_engine_result:
        lines.append(f"Engine result to narrate: {state.last_engine_result}")
    if retrieved_lore:
        lines.append("Relevant lore/history:")
        lines.extend(f"- {chunk}" for chunk in retrieved_lore)
    return "\n".join(lines)
