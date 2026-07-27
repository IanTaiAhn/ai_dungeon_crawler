"""Entry point for Phase 5: score retrieval quality against the golden Q&A
set, then run every persona in `personas/` through the same fixed dungeon
and compare goal-achievement scores side by side - numbers instead of vibes.

`--dry-run` swaps every Ollama-backed piece for its mock/scripted
counterpart, so the whole pipeline can be smoke-tested without a real model
(e.g. in a sandbox with no GPU/Ollama). It reuses one fixed demo script for
every persona, so it proves the wiring works - it says nothing about how any
persona actually plays, since that requires the real autonomous agent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dungeon_crawler.agents import OllamaPlayerAgent, ScriptedActionProvider
from dungeon_crawler.evaluation import (
    OllamaJudge,
    MockJudge,
    evaluate_retrieval,
    load_golden_qa,
    run_persona_playthrough,
)
from dungeon_crawler.llm import MockNarrator, OllamaNarrator
from dungeon_crawler.retrieval import MockEmbedder, OllamaEmbedder, build_lore_store
from dungeon_crawler.schemas import PersonaConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DRY_RUN_SCRIPT = [
    "take rusty sword",
    "go north",
    "attack goblin",
    "attack goblin",
    "attack goblin",
    "go east",
    "take ancient amulet",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality and compare player-agent personas.")
    parser.add_argument("--lore-dir", default=str(_REPO_ROOT / "lore"), help="Directory of lore markdown files")
    parser.add_argument("--personas-dir", default=str(_REPO_ROOT / "personas"), help="Directory of persona JSON files")
    parser.add_argument(
        "--qa-file", default=str(_REPO_ROOT / "evaluation" / "lore_qa.json"), help="Golden Q&A set for retrieval eval"
    )
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model for the DM")
    parser.add_argument("--player-model", default="llama3.2:3b", help="Ollama model for the player agent")
    parser.add_argument("--judge-model", default="qwen2.5:7b", help="Ollama model for the goal-achievement judge")
    parser.add_argument("--embedding-model", default="nomic-embed-text", help="Ollama embedding model for lore RAG")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mocks/scripted actions instead of real Ollama calls, to smoke-test the harness",
    )
    args = parser.parse_args()

    embedder = MockEmbedder() if args.dry_run else OllamaEmbedder(model=args.embedding_model)
    judge = MockJudge() if args.dry_run else OllamaJudge(model=args.judge_model)

    print("=== Retrieval evaluation ===")
    qa_store = build_lore_store(embedder, Path(args.lore_dir))
    cases = load_golden_qa(Path(args.qa_file))
    report = evaluate_retrieval(qa_store, cases)
    for result in report.results:
        mark = "hit " if result.hit else "MISS"
        print(f"[{mark}] {result.question}")
    print(f"recall@k: {report.recall_at_k:.2f} ({sum(r.hit for r in report.results)}/{len(report.results)})\n")

    print("=== Persona comparison ===")
    if args.dry_run:
        print("(dry run: every persona follows the same scripted demo playthrough)\n")

    persona_files = sorted(Path(args.personas_dir).glob("*.json"))
    rows = []
    for path in persona_files:
        persona = PersonaConfig.model_validate(json.loads(path.read_text()))
        lore_store = build_lore_store(embedder, Path(args.lore_dir))  # fresh per run - no cross-persona event bleed

        if args.dry_run:
            narrator = MockNarrator()
            action_provider = ScriptedActionProvider(list(_DRY_RUN_SCRIPT))
        else:
            narrator = OllamaNarrator(model=args.model)
            action_provider = OllamaPlayerAgent(persona, model=args.player_model)

        result = run_persona_playthrough(persona, action_provider, narrator, lore_store, judge)
        rows.append(result)
        print(
            f"{result.persona_name:30s} outcome={result.outcome or 'in_progress':6s} "
            f"turns={result.turn_count:3d} goal_score={result.goal_score.score}/5"
        )
        print(f"    {result.goal_score.rationale}")

    if not rows:
        print("No persona files found.")


if __name__ == "__main__":
    main()
