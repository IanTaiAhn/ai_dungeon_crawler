import pytest

from dungeon_crawler import observability


@pytest.fixture(autouse=True)
def _clear_handler_cache():
    observability.get_langfuse_handler.cache_clear()
    yield
    observability.get_langfuse_handler.cache_clear()


def test_handler_is_none_without_langfuse_env_vars(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert observability.get_langfuse_handler() is None


def test_trace_config_is_plain_thread_id_when_tracing_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert observability.trace_config("t1") == {"configurable": {"thread_id": "t1"}}


def test_trace_config_attaches_callback_and_session_id_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    fake_handler = object()
    monkeypatch.setattr(observability, "CallbackHandler", lambda: fake_handler)

    config = observability.trace_config("t1", tags=["eval"], persona="Wren")

    assert config["configurable"] == {"thread_id": "t1"}
    assert config["callbacks"] == [fake_handler]
    assert config["metadata"] == {"langfuse_session_id": "t1", "persona": "Wren"}
    assert config["tags"] == ["eval"]


def test_trace_config_omits_tags_key_when_none_given(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(observability, "CallbackHandler", lambda: object())

    config = observability.trace_config("t1")

    assert "tags" not in config
