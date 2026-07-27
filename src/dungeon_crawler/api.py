"""FastAPI wrapper: the dungeon crawler as a deployable HTTP app instead of
just a terminal script. Wraps a single GameServer (see sessions.py) - one
compiled graph, many concurrently active games identified by thread_id.

Run locally with real Ollama:
    uvicorn dungeon_crawler.api:app_factory --factory --reload

`app_factory` (not a module-level `app`) is deliberate: constructing the real
app eagerly embeds the whole lore corpus via Ollama, so a module-level `app`
would make importing this module (e.g. from tests, with mocks instead) fail
outright without Ollama running. The --factory flag defers that to uvicorn's
own startup instead of import time.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dungeon_crawler.llm import Narrator, OllamaNarrator
from dungeon_crawler.retrieval import Embedder, OllamaEmbedder
from dungeon_crawler.schemas import PersonaConfig
from dungeon_crawler.sessions import GameNotFoundError, GameServer

_REPO_ROOT = Path(__file__).resolve().parents[2]


class StartGameRequest(BaseModel):
    persona_name: str | None = None
    """Stem of a persona JSON file in personas/, e.g. "cautious_scout". Omit
    to play as a human (an autonomous game with no interrupt-driven human
    turns doesn't apply here - every served game is turn-by-turn via HTTP,
    so this only affects the persona recorded on GameState/scoring, not who
    submits actions)."""


class ActionRequest(BaseModel):
    raw_text: str


def create_app(narrator: Narrator, embedder: Embedder, *, lore_dir: Path | None = None, db_path: str = ":memory:") -> FastAPI:
    """Builds the FastAPI app around a GameServer constructed from the given
    narrator/embedder - real Ollama-backed ones for actual serving, mocks for
    tests/sandbox use (see `app` below vs. tests/test_api.py).
    """
    server = GameServer(narrator, embedder, lore_dir=lore_dir, db_path=db_path, lore_collection_name="lore")
    app = FastAPI(title="AI Dungeon Crawler")

    @app.post("/games")
    def start_game(request: StartGameRequest) -> dict:
        persona = None
        if request.persona_name:
            persona_path = _REPO_ROOT / "personas" / f"{request.persona_name}.json"
            if not persona_path.exists():
                raise HTTPException(status_code=404, detail=f"Unknown persona: {request.persona_name}")
            persona = PersonaConfig.model_validate(json.loads(persona_path.read_text()))
        return server.start_game(persona=persona)

    @app.post("/games/{thread_id}/actions")
    def submit_action(thread_id: str, request: ActionRequest) -> dict:
        try:
            return server.submit_action(thread_id, request.raw_text)
        except GameNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"No such game: {e}") from e

    @app.get("/games/{thread_id}")
    def get_status(thread_id: str) -> dict:
        try:
            return server.get_status(thread_id)
        except GameNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"No such game: {e}") from e

    return app


def app_factory() -> FastAPI:
    return create_app(OllamaNarrator(), OllamaEmbedder(), db_path="dungeon_crawler.sqlite")
