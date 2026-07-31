"""The core game loop as a LangGraph StateGraph.

Phase 1 scope: DM narration (Ollama or a mock) + a human player + the
PlayerAction/GameState schemas + checkpointing for save/resume.

Phase 2 adds retrieval: before each narration, relevant lore/event chunks are
pulled from a LoreStore (Chroma-backed) and passed to the narrator; after
narration, the turn's outcome is written back into the same store so later
turns can retrieve what happened earlier in the session.

Phase 3 swaps the action source: an ActionProvider decides each turn's
PlayerAction, whether that's a human typing at a terminal, an autonomous
persona-driven player agent, or a scripted stand-in for the sandbox/tests.

Phase 4 adds an optional human check-in: when `checkin_every` is set, a real
LangGraph `interrupt()` pauses the graph before combat actions and every N
turns otherwise, allowing the human to review progress periodically. This is
automatically disabled in autonomous mode (when a persona is provided) - the
CLI forces `checkin_every=None` to let the agent play without interruption.
In human mode, it's off by default (None) to avoid interrupting the player
on their own typed actions.

A single `invoke()` call runs the graph until it either ends or hits an
interrupt; the caller must check the result for `__interrupt__` and, if
present, call `invoke(Command(resume=...), config)` to continue (see
`cli.py` for the loop). Turn order: intro, then get-action -> checkin ->
resolve (deterministic) -> retrieve -> narrate -> remember -> check win/lose,
repeating until the game ends. The checkpointer persists state after every
node, keyed by thread_id, so a session can be resumed later (whether picking
back up after an interrupt or reloading a finished/abandoned save) by
invoking again with the same thread_id.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from dungeon_crawler import scenario
from dungeon_crawler.agents import ActionProvider
from dungeon_crawler.game_logic import (
    apply_damage_to_player,
    check_end_state,
    resolve_attack,
    take_item,
    use_item,
)
from dungeon_crawler.llm import Narrator
from dungeon_crawler.parser import parse_action
from dungeon_crawler.retrieval import LoreStore
from dungeon_crawler.schemas import GameState, Intent, PersonaConfig

_RETRIEVAL_K = 3
_APPROVE_RESPONSES = {"", "approve", "ok", "yes", "y"}


def build_graph(
    narrator: Narrator,
    action_provider: ActionProvider,
    checkpointer: Any,
    lore_store: LoreStore,
    checkin_every: int | None = None,
) -> CompiledStateGraph:
    def _retrieve_for(state: GameState, extra_query: str = "") -> list[str]:
        room = scenario.DUNGEON[state.location]
        query = f"{room.description} {extra_query}".strip()
        return lore_store.retrieve(query, k=_RETRIEVAL_K)

    def intro_node(state: GameState) -> dict:
        retrieved = _retrieve_for(state)
        narration = narrator.narrate(state, None, retrieved_lore=retrieved)
        lore_store.add_event(f"Turn 0: the adventure begins in {state.location}. {narration}", turn=0)
        return {"last_narration": narration, "retrieved_lore": retrieved, "log": [*state.log, narration]}

    def get_action_node(state: GameState) -> dict:
        action = action_provider.get_action(state)
        return {"last_action": action}

    def checkin_node(state: GameState) -> dict:
        """No-op unless checkin_every is set. When enabled, pauses before
        combat actions and every `checkin_every` turns otherwise, so a human
        can approve or override the agent's proposed action.
        """
        if checkin_every is None:
            return {}
        proposed = state.last_action
        is_combat = proposed.intent is Intent.ATTACK
        upcoming_turn = state.turn_count + 1
        on_schedule = checkin_every > 0 and upcoming_turn % checkin_every == 0
        if not (is_combat or on_schedule):
            return {}

        response = interrupt(
            {
                "reason": "combat" if is_combat else f"every {checkin_every} turns",
                "turn": upcoming_turn,
                "location": state.location,
                "narration": state.last_narration,
                "proposed_action": proposed.raw_text,
            }
        )
        if str(response).strip().lower() in _APPROVE_RESPONSES:
            return {}
        return {"last_action": parse_action(str(response))}

    def resolve_node(state: GameState) -> dict:
        """Runs the deterministic outcome of the last action against a scratch
        copy of state (via game_logic), then returns the changed fields as a
        LangGraph update. Never mutates the incoming `state` itself.
        """
        action = state.last_action
        room = scenario.DUNGEON[state.location]
        working = state.model_copy(deep=True)
        result = ""

        if action.intent is Intent.MOVE:
            direction = (action.direction or "").lower()
            dest = room.exits.get(direction)
            if dest:
                working.location = dest
                result = f"You move {direction} into the {dest.replace('_', ' ')}."
            else:
                result = f"You can't go {direction} from here."

        elif action.intent is Intent.ATTACK:
            monster = room.monster
            current_hp = working.monster_hp.get(monster, scenario.monster_max_hp(monster)) if monster else 0
            if not monster or current_hp <= 0:
                result = "There's nothing here to attack."
            else:
                stats = scenario.MONSTERS[monster]
                atk = resolve_attack(attacker_bonus=2, target_ac=stats.ac, damage_range=(2, 6))
                if atk.hit:
                    current_hp -= atk.damage
                    working.monster_hp[monster] = current_hp
                    result = f"You hit the {monster} for {atk.damage}."
                    if current_hp <= 0:
                        result += f" The {monster} is defeated."
                else:
                    result = f"You swing at the {monster} and miss."
                if current_hp > 0:
                    retaliation = resolve_attack(
                        attacker_bonus=stats.attack_bonus, target_ac=8, damage_range=stats.damage_range
                    )
                    if retaliation.hit:
                        apply_damage_to_player(working, retaliation.damage)
                        result += f" The {monster} hits you back for {retaliation.damage}."

        elif action.intent is Intent.TAKE_ITEM:
            item = action.target
            available = working.room_items.get(working.location, [])
            if item and take_item(working, item, available):
                result = f"You take the {item}."
                if item == scenario.WIN_ITEM:
                    working.quest_flags[scenario.WIN_FLAG] = True
            else:
                result = f"There's no {item or 'that'} here to take."

        elif action.intent is Intent.USE_ITEM:
            item = action.target
            if item and use_item(working, item):
                result = f"You use the {item}."
            else:
                result = f"You don't have a {item or 'that'} to use."

        elif action.intent is Intent.INSPECT:
            result = room.description

        elif action.intent is Intent.TALK:
            result = "There's no one here who answers."

        elif action.intent is Intent.FLEE:
            result = "You back away, weapon raised."

        elif action.intent is Intent.WAIT:
            result = "You wait a moment."

        working.last_engine_result = result
        working.turn_count += 1
        return working.model_dump(
            include={
                "location",
                "hp",
                "room_items",
                "monster_hp",
                "inventory",
                "quest_flags",
                "last_engine_result",
                "turn_count",
            }
        )

    def retrieve_node(state: GameState) -> dict:
        return {"retrieved_lore": _retrieve_for(state, extra_query=state.last_engine_result)}

    def narrate_node(state: GameState) -> dict:
        narration = narrator.narrate(state, state.last_action, retrieved_lore=state.retrieved_lore)
        return {
            "last_narration": narration,
            "log": [*state.log, f"> {state.last_action.raw_text if state.last_action else '(start)'}", narration],
        }

    def remember_node(state: GameState) -> dict:
        event_text = f"Turn {state.turn_count}: {state.last_engine_result} {state.last_narration}".strip()
        lore_store.add_event(event_text, turn=state.turn_count)
        return {}

    def check_end_node(state: GameState) -> dict:
        working = state.model_copy(deep=True)
        check_end_state(working, win_flag=scenario.WIN_FLAG)
        return {"game_over": working.game_over, "outcome": working.outcome}

    def route_after_check(state: GameState) -> str:
        return END if state.game_over else "get_action"

    graph = StateGraph(GameState)
    graph.add_node("intro", intro_node)
    graph.add_node("get_action", get_action_node)
    graph.add_node("checkin", checkin_node)
    graph.add_node("resolve", resolve_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("narrate", narrate_node)
    graph.add_node("remember", remember_node)
    graph.add_node("check_end", check_end_node)

    graph.add_edge(START, "intro")
    graph.add_edge("intro", "get_action")
    graph.add_edge("get_action", "checkin")
    graph.add_edge("checkin", "resolve")
    graph.add_edge("resolve", "retrieve")
    graph.add_edge("retrieve", "narrate")
    graph.add_edge("narrate", "remember")
    graph.add_edge("remember", "check_end")
    graph.add_conditional_edges("check_end", route_after_check, {END: END, "get_action": "get_action"})

    return graph.compile(checkpointer=checkpointer)


def new_game_state(location: str = scenario.START_ROOM, persona: PersonaConfig | None = None) -> GameState:
    return GameState(location=location, room_items=scenario.new_room_items(), persona=persona)
