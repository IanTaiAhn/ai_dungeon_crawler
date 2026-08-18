"""Turn-taking strategies that decide the next PlayerAction: a human at a
terminal, an autonomous LLM-driven player agent following a PersonaConfig, or
a scripted stand-in for the sandbox and tests. All three implement the same
ActionProvider interface, so the graph doesn't care which one is driving.
"""

from __future__ import annotations

from typing import Protocol

from langgraph.types import interrupt

from dungeon_crawler import scenario
from dungeon_crawler.items import get_equipped_weapon, is_usable_item
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
    "'go north' or 'attack the goblin').\n"
    "If you're carrying the amulet, cast_spell channels its flame ward "
    "against whatever's here - stronger than a physical attack but limited "
    "by the charge count reported below, so weigh unlimited attack against "
    "scarce cast_spell rather than always picking one.\n"
    "If you're carrying the frostbound crown and your HP is critical, "
    "ice_blast becomes available - unlimited, and the first time you ever "
    "use it, it also restores HP before it strikes. Use it as your escape "
    "from a near-death situation rather than saving it."
)


class ActionProvider(Protocol):
    def get_action(self, state: GameState) -> PlayerAction:
        """Decide the next action given the current game state."""
        ...


class HumanActionProvider:
    """Prompts a human at the terminal with a numbered menu of available actions."""

    def get_action(self, state: GameState) -> PlayerAction:
        print(f"\n{state.last_narration}\n", flush=True)

        # Display status
        self._display_status(state)

        # Build list of available actions based on current state
        actions = self._build_action_menu(state)

        # Display the menu
        print("\nAvailable actions:")
        for i, (description, _) in enumerate(actions, 1):
            print(f"  {i}. {description}")

        # Get player choice
        while True:
            try:
                choice = input("\nChoose action (number): ").strip()
                index = int(choice) - 1
                if 0 <= index < len(actions):
                    _, action = actions[index]
                    return action
                else:
                    print(f"Please enter a number between 1 and {len(actions)}")
            except ValueError:
                print("Please enter a valid number")
            except (KeyboardInterrupt, EOFError):
                # Allow Ctrl+C or Ctrl+D to exit gracefully
                raise

    def _display_status(self, state: GameState) -> None:
        """Display current player status."""
        room = scenario.DUNGEON[state.location]

        print("=" * 60)
        print(f"Location: {room.name.replace('_', ' ').title()}")
        print(f"HP: {state.hp}/{state.max_hp}")

        # Show equipped weapon
        weapon = get_equipped_weapon(state)
        if weapon and weapon.weapon_stats:
            print(f"Weapon: {weapon.name} (+{weapon.weapon_stats.attack_bonus} hit, +{weapon.weapon_stats.damage_bonus} dmg)")
        else:
            print(f"Weapon: (unarmed)")

        print(f"Inventory: {', '.join(state.inventory) if state.inventory else '(empty)'}")
        if state.quest_flags.get(scenario.KEY_FLAG):
            print(f"Flame spell charges: {state.spell_charges}")
        if scenario.WIN_ITEM in state.inventory and state.hp <= scenario.ICE_BLAST_HP_THRESHOLD:
            print("The frostbound crown pulses violently - its ice blast is ready.")
        print(f"Turn: {state.turn_count}/{state.max_turns}")

        # Show monster status if present
        if room.monster:
            monster_hp = state.monster_hp.get(room.monster, scenario.monster_max_hp(room.monster))
            if monster_hp > 0:
                print(f"Enemy: {room.monster} ({monster_hp} HP)")

        print("=" * 60)

    def _build_action_menu(self, state: GameState) -> list[tuple[str, PlayerAction]]:
        """Returns list of (description, PlayerAction) tuples for available actions."""
        actions: list[tuple[str, PlayerAction]] = []

        room = scenario.DUNGEON[state.location]

        # Movement options (skip exits sealed behind a quest flag we don't have yet)
        for direction, dest in sorted(room.exits.items()):
            dest_room = scenario.DUNGEON[dest]
            if dest_room.requires_flag and not state.quest_flags.get(dest_room.requires_flag):
                continue
            dest_name = dest.replace("_", " ")
            actions.append((
                f"Go {direction} to {dest_name}",
                PlayerAction(intent=Intent.MOVE, direction=direction, raw_text=f"go {direction}")
            ))

        # Attack option (if there's a living monster)
        if room.monster:
            current_hp = state.monster_hp.get(room.monster, scenario.monster_max_hp(room.monster))
            if current_hp > 0:
                actions.append((
                    f"Attack the {room.monster}",
                    PlayerAction(intent=Intent.ATTACK, target=room.monster, raw_text=f"attack {room.monster}")
                ))

                # Cast flame spell option (once the amulet is recovered and charges remain)
                if state.quest_flags.get(scenario.KEY_FLAG) and state.spell_charges > 0:
                    charges = state.spell_charges
                    actions.append((
                        f"Cast flame spell at the {room.monster} ({charges} charge{'s' if charges != 1 else ''} left)",
                        PlayerAction(
                            intent=Intent.CAST_SPELL, target=room.monster, raw_text=f"cast flame at {room.monster}"
                        )
                    ))

        # Ice blast option: the crown answers once carried and HP is critical.
        # Heals the first time it's ever used regardless of whether there's
        # anything here to fight, so it's offered even without a living monster.
        if scenario.WIN_ITEM in state.inventory and state.hp <= scenario.ICE_BLAST_HP_THRESHOLD:
            first_use = not state.quest_flags.get(scenario.ICE_BLAST_FLAG)
            suffix = " (restores HP, first use)" if first_use else ""
            actions.append((
                f"Unleash the crown's ice blast{suffix}",
                PlayerAction(intent=Intent.ICE_BLAST, target=room.monster, raw_text="unleash ice blast")
            ))

        # Take item options (items in current room)
        room_items = state.room_items.get(state.location, [])
        for item in room_items:
            actions.append((
                f"Take the {item}",
                PlayerAction(intent=Intent.TAKE_ITEM, target=item, raw_text=f"take {item}")
            ))

        # Use item options (only for consumable items, not weapons/quest items)
        for item in state.inventory:
            if is_usable_item(item):
                actions.append((
                    f"Use {item}",
                    PlayerAction(intent=Intent.USE_ITEM, target=item, raw_text=f"use {item}")
                ))

        # Place item option (only when this room has a spot for what we're carrying)
        if room.accepts_item and room.accepts_item in state.inventory:
            item = room.accepts_item
            actions.append((
                f"Place the {item}",
                PlayerAction(intent=Intent.PLACE_ITEM, target=item, raw_text=f"place {item}")
            ))

        # Always available actions
        actions.append((
            "Inspect the area",
            PlayerAction(intent=Intent.INSPECT, raw_text="inspect")
        ))

        if room.monster and state.monster_hp.get(room.monster, scenario.monster_max_hp(room.monster)) > 0:
            actions.append((
                "Flee from danger",
                PlayerAction(intent=Intent.FLEE, raw_text="flee")
            ))

        actions.append((
            "Wait and observe",
            PlayerAction(intent=Intent.WAIT, raw_text="wait")
        ))

        return actions


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
        print(f"\n{state.last_narration}\n", flush=True)
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
        print(f"> {action.raw_text}", flush=True)
        return action


class InterruptActionProvider:
    """Pauses via a real LangGraph interrupt() to get the next turn's raw
    text from outside the process, then parses it exactly like any other
    typed input. This is what lets a request/response server (the FastAPI
    wrapper, the MCP tool server) drive the game turn by turn: each external
    call resumes the paused graph with `Command(resume=raw_text)` instead of
    the graph blocking on a local `input()` the way HumanActionProvider does.
    """

    def get_action(self, state: GameState) -> PlayerAction:
        raw = interrupt(
            {
                "awaiting": "player_action",
                "narration": state.last_narration,
                "location": state.location,
                "turn": state.turn_count + 1,
            }
        )
        return parse_action(str(raw))


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
    if state.quest_flags.get(scenario.KEY_FLAG):
        lines.append(f"Flame spell charges remaining: {state.spell_charges}")
    if scenario.WIN_ITEM in state.inventory and state.hp <= scenario.ICE_BLAST_HP_THRESHOLD:
        first_use = not state.quest_flags.get(scenario.ICE_BLAST_FLAG)
        lines.append(
            "The frostbound crown's ice_blast is available right now"
            + (" and will restore HP the moment you use it" if first_use else "")
            + "."
        )
    if state.retrieved_lore:
        lines.append("Relevant lore/history:")
        lines.extend(f"- {chunk}" for chunk in state.retrieved_lore)
    lines.append(f"Valid intents: {', '.join(i.value for i in Intent)}")
    return "\n".join(lines)
