"""Terminal entry point: play the fixed dungeon-crawl scenario either as a
human, or hand it off to an autonomous persona-driven player agent, both
narrated by a local Ollama model.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import chromadb
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from dungeon_crawler.agents import HumanActionProvider, OllamaPlayerAgent
from dungeon_crawler.checkpointing import checkpoint_serde
from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import OllamaNarrator
from dungeon_crawler.retrieval import OllamaEmbedder, build_lore_store
from dungeon_crawler.schemas import PersonaConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_until_done(graph, initial, config: dict) -> dict:
    """Runs the graph to completion, handling any check-in interrupts along
    the way by asking the human at the terminal to approve or override.
    """
    result = graph.invoke(initial, config)
    while "__interrupt__" in result:
        info = result["__interrupt__"][0].value
        print(f"\n--- Check-in ({info['reason']}), turn {info['turn']} at {info['location']} ---")
        print(info["narration"])
        print(f"Proposed action: {info['proposed_action']}")
        response = input("Press Enter to approve, or type an override action: ")
        result = graph.invoke(Command(resume=response), config)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the AI dungeon crawler.")
    parser.add_argument("--thread-id", default="default", help="Save slot to resume or start")
    parser.add_argument("--db", default="dungeon_crawler.sqlite", help="Path to the save-game database")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model for the DM")
    parser.add_argument("--embedding-model", default="nomic-embed-text", help="Ollama embedding model for lore RAG")
    parser.add_argument("--lore-dir", default=str(_REPO_ROOT / "lore"), help="Directory of lore markdown files")
    parser.add_argument(
        "--chroma-dir", default="dungeon_crawler_chroma", help="Directory for the persistent lore/event store"
    )
    parser.add_argument(
        "--persona",
        default=None,
        help="Path to a persona JSON file (see personas/) to play autonomously instead of as a human",
    )
    parser.add_argument("--player-model", default="llama3.2:3b", help="Ollama model for the autonomous player agent")
    parser.add_argument(
        "--checkin-every",
        type=int,
        default=None,
        help="Pause for human approval before combat and every N turns otherwise (only useful with --persona)",
    )
    args = parser.parse_args()

    narrator = OllamaNarrator(model=args.model)
    embedder = OllamaEmbedder(model=args.embedding_model)
    lore_store = build_lore_store(
        embedder,
        Path(args.lore_dir),
        client=chromadb.PersistentClient(path=args.chroma_dir),
        collection_name="lore",
    )

    persona = None
    if args.persona:
        persona = PersonaConfig.model_validate(json.loads(Path(args.persona).read_text()))
        action_provider = OllamaPlayerAgent(persona, model=args.player_model)
        print(f"Playing as {persona.name}: {persona.goal}")
    else:
        action_provider = HumanActionProvider()

    with closing(sqlite3.connect(args.db, check_same_thread=False)) as conn:
        checkpointer = SqliteSaver(conn, serde=checkpoint_serde())
        graph = build_graph(narrator, action_provider, checkpointer, lore_store, checkin_every=args.checkin_every)
        config = {"configurable": {"thread_id": args.thread_id}}

        existing = graph.get_state(config)
        initial = None if existing.values else new_game_state(persona=persona)

        final_state = _run_until_done(graph, initial, config)
        print(f"\n{final_state['last_narration']}\n")
        print(f"Game over: {final_state['outcome']}")


if __name__ == "__main__":
    main()
