"""Shared test scaffolding: build a graph wired with mocks (no Ollama/GPU
needed) so tests can exercise the full loop, including the check-in
interrupt, without a real model.
"""

from langgraph.checkpoint.memory import InMemorySaver

from dungeon_crawler.agents import ScriptedActionProvider
from dungeon_crawler.checkpointing import checkpoint_serde
from dungeon_crawler.graph import build_graph
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import LoreStore, MockEmbedder


def build_test_graph(script, narrator=None, lore_store=None, checkin_every=None):
    """`script` is a list of raw text commands - ScriptedActionProvider parses
    them the same way a human's typed input would be, then falls back to
    "wait" once exhausted (a script shorter than the session length must not
    exhaust the underlying iterator, since StopIteration raised inside a
    LangGraph node surfaces as a RuntimeError per PEP 479). Standing in for an
    OllamaPlayerAgent lets these tests exercise the persona-driven wiring
    without needing a real model.
    """
    narrator = narrator or MockNarrator()
    lore_store = lore_store or LoreStore(MockEmbedder())
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    return build_graph(narrator, ScriptedActionProvider(script), checkpointer, lore_store, checkin_every=checkin_every)
