from pathlib import Path

from dungeon_crawler.agents import ScriptedActionProvider
from dungeon_crawler.evaluation import (
    MockJudge,
    RetrievalCase,
    evaluate_retrieval,
    load_golden_qa,
    run_persona_playthrough,
)
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import LoreStore, MockEmbedder
from dungeon_crawler.schemas import PersonaConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_golden_qa_reads_the_real_lore_qa_file():
    cases = load_golden_qa(_REPO_ROOT / "evaluation" / "lore_qa.json")
    assert len(cases) >= 1
    assert all(case.expected_keywords for case in cases)


def test_evaluate_retrieval_scores_a_perfect_hit():
    store = LoreStore(MockEmbedder())
    store.add_lore(["The goblin in the guard room is territorial."])
    cases = [RetrievalCase(question="Tell me about the goblin sentry", expected_keywords=["goblin"])]

    report = evaluate_retrieval(store, cases, k=1)

    assert report.recall_at_k == 1.0
    assert report.results[0].hit is True


def test_evaluate_retrieval_scores_a_miss():
    store = LoreStore(MockEmbedder())
    store.add_lore(["The goblin in the guard room is territorial."])
    cases = [RetrievalCase(question="Tell me about the goblin sentry", expected_keywords=["dragon"])]

    report = evaluate_retrieval(store, cases, k=1)

    assert report.recall_at_k == 0.0
    assert report.results[0].hit is False


def test_evaluate_retrieval_handles_an_empty_case_list():
    store = LoreStore(MockEmbedder())
    report = evaluate_retrieval(store, [], k=3)
    assert report.recall_at_k == 0.0
    assert report.results == []


def test_mock_judge_scores_low_risk_persona_lower_for_attacking():
    wren = PersonaConfig(name="Wren", goal="Recover the amulet cautiously", risk_tolerance="low")
    attacking_transcript = "> attack goblin\nYou hit the goblin.\n> take ancient amulet\nYou take it."
    cautious_transcript = "> flee\nYou back away.\n> take ancient amulet\nYou take it."

    attacking_score = MockJudge().score(wren, attacking_transcript)
    cautious_score = MockJudge().score(wren, cautious_transcript)

    assert cautious_score.score > attacking_score.score


def test_mock_judge_does_not_penalize_high_risk_persona_for_attacking():
    bram = PersonaConfig(name="Bram", goal="Grab everything fast", risk_tolerance="high")
    transcript = "> attack goblin\nYou hit the goblin.\n> take ancient amulet\nYou take it."

    score = MockJudge().score(bram, transcript)

    assert score.score == 5  # both actions decisive, neither penalized for a high-risk persona


def test_mock_judge_penalizes_idling():
    bram = PersonaConfig(name="Bram", goal="Grab everything fast", risk_tolerance="high")
    idle_transcript = "> wait\nYou wait.\n> wait\nYou wait."

    score = MockJudge().score(bram, idle_transcript)

    assert score.score == 1


def test_mock_judge_handles_a_transcript_with_no_actions():
    persona = PersonaConfig(name="Wren", goal="Explore", risk_tolerance="low")
    score = MockJudge().score(persona, "just narration, no action lines")
    assert score.score == 3


def test_run_persona_playthrough_returns_a_scored_result():
    persona = PersonaConfig(name="Bram", goal="Grab everything fast", risk_tolerance="high", values=["greed"])
    script = [
        "take rusty sword",
        "go north",
        "attack goblin",
        "attack goblin",
        "attack goblin",
        "go east",
        "take ancient amulet",
        "go down",
        "take frostbound crown",
    ]
    lore_store = LoreStore(MockEmbedder())

    result = run_persona_playthrough(persona, ScriptedActionProvider(script), MockNarrator(), lore_store, MockJudge())

    assert result.persona_name == "Bram"
    assert result.outcome == "win"
    assert result.turn_count > 0
    assert "attack goblin" in result.transcript
    assert 1 <= result.goal_score.score <= 5
