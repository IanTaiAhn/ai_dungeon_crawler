"""MCP tool server: expose game actions (start_game, take_action,
check_inventory, save_game, roll_dice) as MCP tools instead of hardcoded
graph tools, so any MCP-compatible agent can play the dungeon crawler as an
external tool user rather than through LangGraph directly.

Run locally with real Ollama (stdio transport, e.g. for Claude Desktop):
    python -m dungeon_crawler.mcp_server

`create_mcp_server` (not a module-level server) is deliberate, same reason
as api.py's app_factory: building the real server eagerly embeds the lore
corpus via Ollama, so importing this module for tests (with mocks instead)
would otherwise fail outright without Ollama running.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from dungeon_crawler.llm import Narrator, OllamaNarrator
from dungeon_crawler.retrieval import Embedder, OllamaEmbedder
from dungeon_crawler.schemas import PersonaConfig
from dungeon_crawler.sessions import GameNotFoundError, GameServer

_REPO_ROOT = Path(__file__).resolve().parents[2]


def create_mcp_server(
    narrator: Narrator, embedder: Embedder, *, lore_dir: Path | None = None, db_path: str = ":memory:"
) -> FastMCP:
    server = GameServer(narrator, embedder, lore_dir=lore_dir, db_path=db_path, lore_collection_name="lore")
    mcp = FastMCP("dungeon-crawler")

    @mcp.tool()
    def start_game(persona_name: str | None = None) -> dict:
        """Start a new dungeon-crawl game, optionally as a named persona (a
        file stem in personas/, e.g. "cautious_scout"). Returns a thread_id
        and the intro narration; use take_action to play a turn."""
        persona = None
        if persona_name:
            persona_path = _REPO_ROOT / "personas" / f"{persona_name}.json"
            if not persona_path.exists():
                raise ValueError(f"Unknown persona: {persona_name}")
            persona = PersonaConfig.model_validate(json.loads(persona_path.read_text()))
        return server.start_game(persona=persona)

    @mcp.tool()
    def take_action(thread_id: str, raw_text: str) -> dict:
        """Submit the next turn's action (free text, e.g. "go north" or
        "attack goblin") for an in-progress game started with start_game."""
        try:
            return server.submit_action(thread_id, raw_text)
        except GameNotFoundError as e:
            raise ValueError(f"No such game: {e}") from e

    @mcp.tool()
    def check_inventory(thread_id: str) -> list[str]:
        """List the items currently carried in the given game."""
        try:
            return server.get_status(thread_id)["inventory"]
        except GameNotFoundError as e:
            raise ValueError(f"No such game: {e}") from e

    @mcp.tool()
    def save_game(thread_id: str) -> dict:
        """Confirm the current save state of a game. Every turn is already
        auto-persisted by the checkpointer, so this reports the latest
        checkpointed status rather than performing a new save."""
        try:
            status = server.get_status(thread_id)
        except GameNotFoundError as e:
            raise ValueError(f"No such game: {e}") from e
        return {"saved": True, "turn_count": status["turn_count"], "location": status["location"]}

    @mcp.tool()
    def roll_dice(sides: int = 20, count: int = 1) -> list[int]:
        """Roll `count` dice with `sides` sides each. A standalone utility -
        doesn't require an active game."""
        if sides < 2 or count < 1:
            raise ValueError("sides must be >= 2 and count must be >= 1")
        return [random.randint(1, sides) for _ in range(count)]

    return mcp


def main() -> None:
    create_mcp_server(OllamaNarrator(), OllamaEmbedder(), db_path="dungeon_crawler.sqlite").run()


if __name__ == "__main__":
    main()
