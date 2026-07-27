"""Phase 5: measure instead of vibes-check.

Two independent scorers:
- Retrieval quality: a small gold Q&A set for the lore corpus, scored as a
  simplified recall@k (does at least one retrieved chunk contain an expected
  keyword?) - a lightweight proxy for RAGAS-style context recall, without
  pulling in the full ragas package (which itself needs an LLM judge and a
  much heavier dependency footprint than this project needs).
- Goal achievement: given a persona and a full turn-by-turn transcript, did
  the agent actually behave consistently with its stated goal? This is
  judgment, not string-matching, so it's behind a TranscriptJudge interface -
  OllamaJudge for real scoring, MockJudge (a risk-tolerance/decisiveness
  heuristic over structured intents) for the sandbox and tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from dungeon_crawler.agents import ActionProvider
from dungeon_crawler.checkpointing import checkpoint_serde
from dungeon_crawler.graph import build_graph, new_game_state
from dungeon_crawler.llm import Narrator
from dungeon_crawler.retrieval import LoreStore
from dungeon_crawler.schemas import PersonaConfig

# --- Retrieval evaluation -----------------------------------------------


class RetrievalCase(BaseModel):
    question: str
    expected_keywords: list[str]


class RetrievalCaseResult(BaseModel):
    question: str
    hit: bool
    retrieved: list[str]


class RetrievalReport(BaseModel):
    results: list[RetrievalCaseResult]
    recall_at_k: float


def load_golden_qa(path: Path) -> list[RetrievalCase]:
    return [RetrievalCase.model_validate(case) for case in json.loads(path.read_text())]


def evaluate_retrieval(lore_store: LoreStore, cases: list[RetrievalCase], *, k: int = 3) -> RetrievalReport:
    results = []
    for case in cases:
        retrieved = lore_store.retrieve(case.question, k=k)
        lowered = [chunk.lower() for chunk in retrieved]
        hit = any(keyword.lower() in chunk for chunk in lowered for keyword in case.expected_keywords)
        results.append(RetrievalCaseResult(question=case.question, hit=hit, retrieved=retrieved))
    recall_at_k = sum(r.hit for r in results) / len(results) if results else 0.0
    return RetrievalReport(results=results, recall_at_k=recall_at_k)


# --- Goal-achievement evaluation -----------------------------------------


class GoalScore(BaseModel):
    score: int = Field(ge=1, le=5, description="1 = ignored the goal entirely, 5 = pursued it consistently")
    rationale: str = Field(description="One or two sentences justifying the score")


JUDGE_SYSTEM_PROMPT = (
    "You are scoring how consistently a text-adventure player agent pursued "
    "its stated goal across a full playthrough. Given the agent's persona "
    "and a turn-by-turn transcript, score 1-5: 1 means the agent's actions "
    "were inconsistent with or ignored its goal/values, 5 means every action "
    "was a clear, decisive step toward the goal in the spirit of its values. "
    "Judge actions taken, not narration quality."
)


class TranscriptJudge(Protocol):
    def score(self, persona: PersonaConfig, transcript: str) -> GoalScore:
        """Score how consistently the transcript pursued the persona's goal."""
        ...


class OllamaJudge:
    """Real judge, backed by a local Ollama model via structured output."""

    def __init__(self, model: str = "qwen2.5:7b", temperature: float = 0.0) -> None:
        from langchain_ollama import ChatOllama

        self._structured_llm = ChatOllama(model=model, temperature=temperature).with_structured_output(GoalScore)

    def score(self, persona: PersonaConfig, transcript: str) -> GoalScore:
        user_prompt = (
            f"Persona: {persona.name}\n"
            f"Goal: {persona.goal}\n"
            f"Risk tolerance: {persona.risk_tolerance.value}\n"
            f"Values: {', '.join(persona.values) or 'none specified'}\n\n"
            f"Transcript:\n{transcript}"
        )
        result = self._structured_llm.invoke(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        return result if isinstance(result, GoalScore) else GoalScore.model_validate(result)


class MockJudge:
    """Deterministic heuristic stand-in - no model required. Matching a
    goal's free-text vocabulary ("grab", "value") against concrete game verbs
    ("take", "attack") doesn't work, since they're different vocabularies, so
    instead this scores against the structured signals the schemas already
    give us: an action is "decisive" if it isn't WAIT, and "risk-aligned" if
    it isn't an ATTACK from a low-risk-tolerance persona (a cautious agent
    that ends up fighting is less consistent with its stated risk tolerance;
    a high/medium-risk persona isn't penalized for it). Good enough to
    exercise the harness in the sandbox and in tests - nowhere near real
    judgment of whether the goal itself was pursued.
    """

    def score(self, persona: PersonaConfig, transcript: str) -> GoalScore:
        from dungeon_crawler.parser import parse_action
        from dungeon_crawler.schemas import Intent, RiskTolerance

        action_lines = [line[2:].strip() for line in transcript.splitlines() if line.startswith("> ")]
        if not action_lines:
            return GoalScore(score=3, rationale="No actions found in the transcript to judge.")

        intents = [parse_action(line).intent for line in action_lines]
        aligned = sum(
            1
            for intent in intents
            if intent is not Intent.WAIT and not (persona.risk_tolerance is RiskTolerance.LOW and intent is Intent.ATTACK)
        )
        ratio = aligned / len(intents)
        score = max(1, min(5, round(1 + ratio * 4)))
        return GoalScore(
            score=score,
            rationale=(
                f"{aligned}/{len(intents)} actions were decisive and consistent with "
                f"risk_tolerance={persona.risk_tolerance.value}."
            ),
        )


# --- Persona comparison ---------------------------------------------------


class PersonaRunResult(BaseModel):
    persona_name: str
    outcome: str | None
    turn_count: int
    transcript: str
    goal_score: GoalScore


def run_persona_playthrough(
    persona: PersonaConfig,
    action_provider: ActionProvider,
    narrator: Narrator,
    lore_store: LoreStore,
    judge: TranscriptJudge,
) -> PersonaRunResult:
    """Runs one full session for `persona` and scores the result. Each call
    gets its own in-memory checkpointer/thread, so comparing personas never
    shares game state between runs - only the (already-built) `lore_store`'s
    static lore is shared; pass a fresh LoreStore per persona to also avoid
    one run's written-back events leaking into another's retrieval.
    """
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    graph = build_graph(narrator, action_provider, checkpointer, lore_store)
    config = {"configurable": {"thread_id": f"eval-{persona.name}"}}
    final = graph.invoke(new_game_state(persona=persona), config)
    transcript = "\n".join(final["log"])
    return PersonaRunResult(
        persona_name=persona.name,
        outcome=final["outcome"],
        turn_count=final["turn_count"],
        transcript=transcript,
        goal_score=judge.score(persona, transcript),
    )
