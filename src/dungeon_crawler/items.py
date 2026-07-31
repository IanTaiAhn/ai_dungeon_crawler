"""Item definitions and mechanics.

Items can be weapons (passive bonuses), consumables (active use effects),
or quest items (story/goal markers with no mechanical effect).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dungeon_crawler.schemas import GameState


class ItemType(str, Enum):
    WEAPON = "weapon"
    CONSUMABLE = "consumable"
    QUEST = "quest"


@dataclass
class WeaponStats:
    """Combat bonuses provided by a weapon."""
    attack_bonus: int
    damage_bonus: int  # Added to min and max of damage range


@dataclass
class ItemDefinition:
    """Defines an item's type and mechanical effects."""
    name: str
    item_type: ItemType
    weapon_stats: WeaponStats | None = None
    description: str = ""


# Item registry - defines all items in the game
ITEMS: dict[str, ItemDefinition] = {
    "rusty sword": ItemDefinition(
        name="rusty sword",
        item_type=ItemType.WEAPON,
        weapon_stats=WeaponStats(attack_bonus=2, damage_bonus=2),
        description="A dull, pitted blade that still has some edge"
    ),
    "healing potion": ItemDefinition(
        name="healing potion",
        item_type=ItemType.CONSUMABLE,
        description="A small vial of red liquid that restores vitality"
    ),
    "ancient amulet": ItemDefinition(
        name="ancient amulet",
        item_type=ItemType.QUEST,
        description="A mystical amulet that pulses with ancient power"
    ),
}


def get_item_definition(item_name: str) -> ItemDefinition | None:
    """Look up an item's definition."""
    return ITEMS.get(item_name)


def is_usable_item(item_name: str) -> bool:
    """Returns True if the item can be actively 'used' (not a passive weapon or quest item)."""
    item_def = get_item_definition(item_name)
    if not item_def:
        return False
    return item_def.item_type == ItemType.CONSUMABLE


def get_equipped_weapon(state: GameState) -> ItemDefinition | None:
    """Returns the first weapon found in inventory, or None if unarmed."""
    for item_name in state.inventory:
        item_def = get_item_definition(item_name)
        if item_def and item_def.item_type == ItemType.WEAPON:
            return item_def
    return None


def get_weapon_stats(state: GameState) -> tuple[int, int]:
    """
    Returns (attack_bonus, damage_bonus) based on equipped weapon.
    Defaults to (0, 0) if unarmed.
    """
    weapon = get_equipped_weapon(state)
    if weapon and weapon.weapon_stats:
        return (weapon.weapon_stats.attack_bonus, weapon.weapon_stats.damage_bonus)
    return (0, 0)
