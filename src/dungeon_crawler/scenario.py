"""A small, fixed dungeon-crawl scenario. Static content only - anything that
changes during play (items remaining, monster HP) lives on GameState, not here,
so this module stays safe to share across concurrent sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Room:
    name: str
    description: str
    exits: dict[str, str]
    starting_items: list[str] = field(default_factory=list)
    monster: str | None = None
    requires_flag: str | None = None  # gates entry until state.quest_flags[requires_flag] is True


@dataclass(frozen=True)
class Monster:
    name: str
    hp: int
    attack_bonus: int
    ac: int
    damage_range: tuple[int, int]


START_ROOM = "entrance"

# The amulet doesn't win the game by itself - it's a key that resonates with
# the sealed stairwell down to the frozen cavern. KEY_FLAG gates that door;
# WIN_FLAG (set by taking the true relic below) is what actually ends the game.
KEY_ITEM = "ancient amulet"
KEY_FLAG = "amulet_recovered"
WIN_ITEM = "frostbound crown"
WIN_FLAG = "crown_recovered"

DUNGEON: dict[str, Room] = {
    "entrance": Room(
        name="entrance",
        description="A crumbling stone entrance, torchlight flickering against moss-covered walls.",
        exits={"north": "guard_room"},
        starting_items=["rusty sword"],
    ),
    "guard_room": Room(
        name="guard_room",
        description="A cramped guard room. A goblin snarls from the shadows near a locked door.",
        exits={"south": "entrance", "east": "treasure_room"},
        monster="goblin",
    ),
    "treasure_room": Room(
        name="treasure_room",
        description="Gold coins spill across the floor, and an ancient amulet rests on a stone pedestal. A small vial of red liquid sits nearby.",
        exits={"west": "guard_room", "down": "frozen_cavern"},
        starting_items=[KEY_ITEM, "healing potion"],
    ),
    "frozen_cavern": Room(
        name="frozen_cavern",
        description=(
            "A frozen cavern beneath the treasure room, opened by the amulet's resonance. Frost "
            "crawls up walls of black ice, and a crystal golem stands watch over a frostbound crown "
            "set into a pillar of ice at the cavern's heart."
        ),
        exits={"up": "treasure_room"},
        starting_items=[WIN_ITEM],
        monster="crystal golem",
        requires_flag=KEY_FLAG,
    ),
}

MONSTERS: dict[str, Monster] = {
    "goblin": Monster(name="goblin", hp=7, attack_bonus=2, ac=8, damage_range=(1, 4)),
    "crystal golem": Monster(name="crystal golem", hp=14, attack_bonus=3, ac=13, damage_range=(2, 6)),
}


def new_room_items() -> dict[str, list[str]]:
    """A fresh copy of each room's starting items, safe to mutate per-session."""
    return {name: list(room.starting_items) for name, room in DUNGEON.items()}


def monster_max_hp(name: str) -> int:
    return MONSTERS[name].hp
