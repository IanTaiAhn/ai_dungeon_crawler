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
    accepts_item: str | None = None  # item that can be PLACE_ITEM'd here, e.g. an altar or pedestal


@dataclass(frozen=True)
class Monster:
    name: str
    hp: int
    attack_bonus: int
    ac: int
    damage_range: tuple[int, int]
    weak_to_fire: bool = False


START_ROOM = "entrance"

# The amulet doesn't win the game by itself - it's a key that resonates with
# the sealed stairwell down to the frozen cavern. KEY_FLAG gates that door.
# Recovering the crown from the frozen cavern isn't the ending either: the
# crown itself resonates with a sealed way down into the volcanic depths
# (CROWN_FLAG gates that door), and the game is only actually won by carrying
# the crown to the volcanic heart and setting it into the stone hollow there
# (WIN_FLAG), which is what check_end_state watches for.
KEY_ITEM = "ancient amulet"
KEY_FLAG = "amulet_recovered"
WIN_ITEM = "frostbound crown"
CROWN_FLAG = "crown_recovered"
WIN_FLAG = "crown_placed"

# The amulet also carries a dormant flame ward: recovering it grants a
# limited number of flame-spell casts, a stronger-but-scarce alternative to
# a weapon's unlimited-but-weaker physical attacks.
FLAME_SPELL_CHARGES = 3
FLAME_SPELL_ATTACK_BONUS = 4
FLAME_SPELL_DAMAGE_RANGE = (3, 6)
FLAME_SPELL_WEAKNESS_BONUS = 3  # extra damage on a hit against a weak_to_fire monster

# The crown answers a different kind of desperation: once it's in the
# player's inventory and HP drops to the threshold, its ice blast becomes
# available. Unlimited (unlike the amulet's flame charges) - but the HP
# restore only ever fires the first time it's used, tracked via ICE_BLAST_FLAG.
ICE_BLAST_HP_THRESHOLD = 2
ICE_BLAST_HEAL_AMOUNT = 5
ICE_BLAST_ATTACK_BONUS = 4
ICE_BLAST_DAMAGE_RANGE = (3, 6)
ICE_BLAST_FLAG = "ice_blast_used"

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
        exits={"up": "treasure_room", "down": "volcanic_passage"},
        starting_items=[WIN_ITEM],
        monster="crystal golem",
        requires_flag=KEY_FLAG,
    ),
    "volcanic_passage": Room(
        name="volcanic_passage",
        description=(
            "The frost gives way without warning: a crack in the cavern floor, warmed by the crown's "
            "own heat, opens onto a narrow passage of black rock. Heat shimmers off the walls and a "
            "distant orange glow pulses from somewhere below - a magma hound, molten cracks veining "
            "its hide, blocks the way down."
        ),
        exits={"up": "frozen_cavern", "down": "volcanic_depths"},
        monster="magma hound",
        requires_flag=CROWN_FLAG,
    ),
    "volcanic_depths": Room(
        name="volcanic_depths",
        description=(
            "Rivers of lava crawl between broken black columns, the heat pressing in from every side. "
            "An ember wraith peels itself off a burning wall, drawn by the cold still clinging to the "
            "crown in your pack."
        ),
        exits={"up": "volcanic_passage", "down": "volcanic_heart"},
        monster="ember wraith",
    ),
    "volcanic_heart": Room(
        name="volcanic_heart",
        description=(
            "The passage opens into a vast volcanic chamber, its ceiling lost in heat-haze, a lake of "
            "lava churning below a stone ledge. At the ledge's center, worn smooth by something that "
            "stood here long before you, is a hollow shaped for exactly one thing: a crown."
        ),
        exits={"up": "volcanic_depths"},
        accepts_item=WIN_ITEM,
    ),
}

MONSTERS: dict[str, Monster] = {
    "goblin": Monster(name="goblin", hp=7, attack_bonus=2, ac=8, damage_range=(1, 4)),
    "crystal golem": Monster(name="crystal golem", hp=14, attack_bonus=3, ac=13, damage_range=(2, 6), weak_to_fire=True),
    "magma hound": Monster(name="magma hound", hp=10, attack_bonus=3, ac=11, damage_range=(2, 5)),
    "ember wraith": Monster(name="ember wraith", hp=16, attack_bonus=4, ac=12, damage_range=(3, 7)),
}


def new_room_items() -> dict[str, list[str]]:
    """A fresh copy of each room's starting items, safe to mutate per-session."""
    return {name: list(room.starting_items) for name, room in DUNGEON.items()}


def monster_max_hp(name: str) -> int:
    return MONSTERS[name].hp
