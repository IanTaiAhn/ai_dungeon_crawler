"""Optional Langfuse tracing for the game graph.

Tracing is opt-in by presence of `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`
in the environment, not by an installed-package check - `langfuse` is a
regular dependency, but `get_langfuse_handler()` returns None with no
Langfuse instance required, so `uv run pytest -q` and any Ollama-less
environment stay fully offline unless someone explicitly configures a
Langfuse endpoint.

Every place that builds the `config` dict passed to `graph.invoke()` should
build it via `trace_config()` instead of hand-rolling `{"configurable":
{"thread_id": ...}}`, so tracing attaches uniformly. When enabled, the
callback attaches at the top-level `invoke()` call only - LangChain
propagates it through nested Runnable calls (node functions calling
`ChatOllama.invoke()`) automatically via a contextvar, so no changes are
needed inside graph.py/llm.py/agents.py themselves.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from langfuse.langchain import CallbackHandler


@lru_cache(maxsize=1)
def get_langfuse_handler() -> CallbackHandler | None:
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    return CallbackHandler()


def trace_config(thread_id: str, *, tags: list[str] | None = None, **metadata: Any) -> dict[str, Any]:
    """Builds the config dict for graph.invoke()/get_state(), with the
    checkpointer's thread_id always set, plus Langfuse tracing (grouped into
    one session per thread_id) attached when tracing is enabled.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    handler = get_langfuse_handler()
    if handler is None:
        return config
    config["callbacks"] = [handler]
    config["metadata"] = {"langfuse_session_id": thread_id, **metadata}
    if tags:
        config["tags"] = tags
    return config
