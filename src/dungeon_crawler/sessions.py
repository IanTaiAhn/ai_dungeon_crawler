"""Shared game-session management for the serving layer (FastAPI + MCP).

One compiled graph is built per GameServer and reused across every game -
LangGraph's checkpointer already isolates each game's GameState by
thread_id, so there's no need for a graph-per-game. Every served game uses
InterruptActionProvider, so submitting a turn's action is always
`Command(resume=raw_text)` against the same graph, regardless of which
serving surface (HTTP, MCP) the caller came in through.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from dungeon_crawler.agents import InterruptActionProvider
from dungeon_crawler.checkpointing import checkpoint_serde
from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import Narrator
from dungeon_crawler.observability import trace_config
from dungeon_crawler.retrieval import Embedder, build_lore_store
from dungeon_crawler.schemas import PersonaConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]


class GameNotFoundError(Exception):
    pass


class GameServer:
    """Owns one compiled graph and answers start/act/status calls for any
    number of concurrently active games, each identified by its thread_id.
    """

    def __init__(
        self,
        narrator: Narrator,
        embedder: Embedder,
        *,
        lore_dir: Path | None = None,
        db_path: str = ":memory:",
        lore_collection_name: str | None = None,
    ) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(self._conn, serde=checkpoint_serde())
        lore_store = build_lore_store(
            embedder, lore_dir or (_REPO_ROOT / "lore"), collection_name=lore_collection_name
        )
        self._graph: CompiledStateGraph = build_graph(narrator, InterruptActionProvider(), checkpointer, lore_store)

    def start_game(self, persona: PersonaConfig | None = None, thread_id: str | None = None) -> dict[str, Any]:
        thread_id = thread_id or uuid.uuid4().hex
        config = trace_config(thread_id)
        result = self._graph.invoke(new_game_state(persona=persona), config)
        return self._summarize(thread_id, result)

    def submit_action(self, thread_id: str, raw_text: str) -> dict[str, Any]:
        config = trace_config(thread_id)
        values = self._graph.get_state(config).values
        if not values:
            raise GameNotFoundError(thread_id)
        if values["game_over"]:
            return self._summarize(thread_id, values)
        result = self._graph.invoke(Command(resume=raw_text), config)
        return self._summarize(thread_id, result)

    def get_status(self, thread_id: str) -> dict[str, Any]:
        config = trace_config(thread_id)
        values = self._graph.get_state(config).values
        if not values:
            raise GameNotFoundError(thread_id)
        # Optional[...] fields (outcome, last_action) are absent from `values`
        # entirely - not just None - until some node actually writes to them
        # (e.g. right after start_game, before check_end_node has ever run),
        # unlike non-Optional fields which are always present. Use .get() for
        # those, not [...].
        persona = values["persona"]
        return {
            "thread_id": thread_id,
            "persona": persona.name if persona else None,
            "location": values["location"],
            "hp": values["hp"],
            "max_hp": values["max_hp"],
            "inventory": values["inventory"],
            "turn_count": values["turn_count"],
            "game_over": values["game_over"],
            "outcome": values.get("outcome"),
            "last_narration": values["last_narration"],
        }

    @staticmethod
    def _summarize(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
        if "__interrupt__" in result:
            info = result["__interrupt__"][0].value
            return {
                "thread_id": thread_id,
                "status": "awaiting_action",
                "narration": info["narration"],
                "location": info["location"],
                "turn": info["turn"],
            }
        return {
            "thread_id": thread_id,
            "status": "game_over" if result["game_over"] else "in_progress",
            "narration": result["last_narration"],
            "location": result["location"],
            "turn": result["turn_count"],
            "outcome": result["outcome"],
        }
