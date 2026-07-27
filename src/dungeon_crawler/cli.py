"""Terminal entry point: play the fixed dungeon-crawl scenario as a human,
narrated by a local Ollama model.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import chromadb
from langgraph.checkpoint.sqlite import SqliteSaver

from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import OllamaNarrator
from dungeon_crawler.retrieval import OllamaEmbedder, build_lore_store

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _human_action_source(state) -> str:
    print(f"\n{state.last_narration}\n")
    return input("> ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the AI dungeon crawler.")
    parser.add_argument("--thread-id", default="default", help="Save slot to resume or start")
    parser.add_argument("--db", default="dungeon_crawler.sqlite", help="Path to the save-game database")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model for the DM")
    parser.add_argument("--embedding-model", default="nomic-embed-text", help="Ollama embedding model for lore RAG")
    parser.add_argument("--lore-dir", default=str(_REPO_ROOT / "lore"), help="Directory of lore markdown files")
    parser.add_argument("--chroma-dir", default="dungeon_crawler_chroma", help="Directory for the persistent lore/event store")
    args = parser.parse_args()

    narrator = OllamaNarrator(model=args.model)
    embedder = OllamaEmbedder(model=args.embedding_model)
    lore_store = build_lore_store(
        embedder,
        Path(args.lore_dir),
        client=chromadb.PersistentClient(path=args.chroma_dir),
        collection_name="lore",
    )

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(narrator, _human_action_source, checkpointer, lore_store)
        config = {"configurable": {"thread_id": args.thread_id}}

        existing = graph.get_state(config)
        initial = None if existing.values else new_game_state()

        final_state = graph.invoke(initial, config)
        print(f"\n{final_state['last_narration']}\n")
        print(f"Game over: {final_state['outcome']}")


if __name__ == "__main__":
    main()
