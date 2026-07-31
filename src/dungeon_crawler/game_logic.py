"""Deterministic game rules: combat, inventory, win/lose. The LLM decides
*intent*, this layer decides *outcome* - keeps the game fair, reproducible,
and debuggable independent of any model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from dungeon_crawler.schemas import GameState


@dataclass
class AttackResult:
    hit: bool
    damage: int


def resolve_attack(
    *,
    attacker_bonus: int,
    target_ac: int,
    damage_range: tuple[int, int],
    rng: random.Random | None = None,
) -> AttackResult:
    """d20 + attacker_bonus vs target_ac to hit; damage_range rolled on a hit."""
    rng = rng or random.Random()
    roll = rng.randint(1, 20) + attacker_bonus
    hit = roll >= target_ac
    damage = rng.randint(*damage_range) if hit else 0
    return AttackResult(hit=hit, damage=damage)


def apply_damage_to_player(state: GameState, damage: int) -> None:
    state.hp = max(0, state.hp - damage)


def take_item(state: GameState, item: str, available_items: list[str]) -> bool:
    """Move an item from a room's available-items list into the player's inventory."""
    if item not in available_items:
        return False
    available_items.remove(item)
    state.inventory.append(item)
    return True


def use_item(state: GameState, item: str) -> bool:
    """Use a consumable item. Returns True if successful."""
    if item not in state.inventory:
        return False

    # Apply item effects
    if item == "healing potion":
        state.hp = min(state.max_hp, state.hp + 5)

    # Remove item from inventory (it's consumed)
    state.inventory.remove(item)
    return True


def check_end_state(state: GameState, *, win_flag: str) -> None:
    """Sets game_over/outcome. Call once at the end of every turn."""
    if state.hp <= 0:
        state.game_over = True
        state.outcome = "lose"
    elif state.quest_flags.get(win_flag):
        state.game_over = True
        state.outcome = "win"
    elif state.turn_count >= state.max_turns:
        state.game_over = True
        state.outcome = "lose"
