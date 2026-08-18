"""Structured data passed through the game graph and persisted between turns."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Intent(str, Enum):
    MOVE = "move"
    ATTACK = "attack"
    CAST_SPELL = "cast_spell"
    ICE_BLAST = "ice_blast"
    USE_ITEM = "use_item"
    TAKE_ITEM = "take_item"
    PLACE_ITEM = "place_item"
    TALK = "talk"
    INSPECT = "inspect"
    FLEE = "flee"
    WAIT = "wait"


class PlayerAction(BaseModel):
    """What both the human path and the player-agent path must produce each turn."""

    intent: Intent
    target: str | None = Field(default=None, description="NPC, item, or object the action targets")
    direction: str | None = Field(default=None, description="Compass/relative direction, for MOVE")
    raw_text: str = Field(description="The original text the action was parsed from")


class RiskTolerance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonaConfig(BaseModel):
    """Defines a player agent's goal and personality. Absent for human-played sessions."""

    name: str
    goal: str = Field(description="What this agent is trying to accomplish this session")
    risk_tolerance: RiskTolerance = RiskTolerance.MEDIUM
    values: list[str] = Field(default_factory=list, description="Traits the agent should weigh, e.g. 'curious', 'greedy'")


class GameState(BaseModel):
    """The object threaded through the LangGraph state machine and checkpointed to disk."""

    location: str
    inventory: list[str] = Field(default_factory=list)
    hp: int = 10
    max_hp: int = 10
    turn_count: int = 0
    max_turns: int = 40
    quest_flags: dict[str, bool] = Field(default_factory=dict)
    spell_charges: int = Field(default=0, description="Remaining flame-spell casts; granted on recovering the amulet")
    persona: PersonaConfig | None = Field(default=None, description="None means a human is playing")
    room_items: dict[str, list[str]] = Field(default_factory=dict, description="Items still lying in each room, keyed by room name")
    monster_hp: dict[str, int] = Field(default_factory=dict, description="Current HP of each named monster, keyed by monster name")
    last_narration: str = ""
    last_action: PlayerAction | None = None
    last_engine_result: str = Field(default="", description="Deterministic outcome of the last action, for the DM to narrate")
    retrieved_lore: list[str] = Field(default_factory=list, description="Lore/event chunks retrieved for the current narration")
    log: list[str] = Field(default_factory=list, description="Turn-by-turn narration/action history")
    game_over: bool = False
    outcome: str | None = Field(default=None, description="'win', 'lose', or None while in progress")
