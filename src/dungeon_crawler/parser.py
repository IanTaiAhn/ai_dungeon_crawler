"""Rule-based parsing of free-text input into a PlayerAction. Deliberately
simple for phase 1 - swap for LLM-based structured extraction later if
raw-text coverage becomes a problem.
"""

from __future__ import annotations

from dungeon_crawler.schemas import Intent, PlayerAction

_DIRECTIONS = {"north", "south", "east", "west", "up", "down", "n", "s", "e", "w"}
_DIRECTION_ALIASES = {"n": "north", "s": "south", "e": "east", "w": "west"}

_VERB_INTENTS: dict[str, Intent] = {
    "go": Intent.MOVE,
    "move": Intent.MOVE,
    "walk": Intent.MOVE,
    "attack": Intent.ATTACK,
    "fight": Intent.ATTACK,
    "hit": Intent.ATTACK,
    "take": Intent.TAKE_ITEM,
    "grab": Intent.TAKE_ITEM,
    "pick": Intent.TAKE_ITEM,
    "use": Intent.USE_ITEM,
    "talk": Intent.TALK,
    "speak": Intent.TALK,
    "look": Intent.INSPECT,
    "inspect": Intent.INSPECT,
    "examine": Intent.INSPECT,
    "flee": Intent.FLEE,
    "run": Intent.FLEE,
    "wait": Intent.WAIT,
}


def parse_action(raw_text: str) -> PlayerAction:
    text = raw_text.strip().lower()

    if text in _DIRECTIONS:
        return PlayerAction(intent=Intent.MOVE, direction=_DIRECTION_ALIASES.get(text, text), raw_text=raw_text)

    words = text.split()
    if not words:
        return PlayerAction(intent=Intent.WAIT, raw_text=raw_text)

    verb, *rest = words
    intent = _VERB_INTENTS.get(verb)
    target = " ".join(w for w in rest if w not in {"to", "the", "at"}) or None

    if intent is None:
        return PlayerAction(intent=Intent.INSPECT, target=target, raw_text=raw_text)

    if intent is Intent.MOVE:
        direction = _DIRECTION_ALIASES.get(target, target) if target else None
        return PlayerAction(intent=Intent.MOVE, direction=direction, raw_text=raw_text)

    return PlayerAction(intent=intent, target=target, raw_text=raw_text)
