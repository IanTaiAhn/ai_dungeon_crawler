"""Lore RAG: naive chunking, an embedder interface (Ollama or a deterministic
mock), and a Chroma-backed store the narrate step retrieves from - plus a way
to write new events back in, so the DM can "remember" earlier turns.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Protocol

import chromadb

_MOCK_EMBED_DIM = 256
_MOCK_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "for", "in", "is",
    "it", "me", "not", "of", "on", "or", "tell", "that", "the", "this",
    "to", "was", "were", "will", "with", "you", "your",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Real embedder, backed by a local Ollama embedding model."""

    def __init__(self, model: str = "nomic-embed-text") -> None:
        from langchain_ollama import OllamaEmbeddings

        self._embeddings = OllamaEmbeddings(model=model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)


class MockEmbedder:
    """Deterministic hashing-trick embedder - no model required. Shared
    (non-stopword) words land in the same buckets, so word-overlap still
    drives similarity - enough to exercise retrieval in the sandbox and in
    tests, though nowhere near a real embedding model's quality.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        vec = [0.0] * _MOCK_EMBED_DIM
        for word in _WORD_RE.findall(text.lower()):
            if word in _MOCK_STOPWORDS:
                continue
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % _MOCK_EMBED_DIM
            vec[bucket] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec


def chunk_text(text: str, *, size: int = 400, overlap: int = 50) -> list[str]:
    """Naive fixed-size chunking. Revisit if retrieval quality is bad."""
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size].strip())
        start += size - overlap
    return [c for c in chunks if c]


def load_lore_corpus(lore_dir: Path) -> list[str]:
    chunks: list[str] = []
    for path in sorted(lore_dir.glob("*.md")):
        chunks.extend(chunk_text(path.read_text()))
    return chunks


class LoreStore:
    """Wraps a Chroma collection: static lore plus events written back during
    play, all retrieved the same way.

    Chroma's default/ephemeral clients share a process-wide backend, so
    collections - not client instances - are what isolate one store's data
    from another's. `collection_name` therefore defaults to a fresh unique
    name per instance (right for the sandbox and tests); pass a stable name
    explicitly (as the CLI does) to persist and reconnect across restarts.
    """

    def __init__(
        self,
        embedder: Embedder,
        *,
        client: chromadb.ClientAPI | None = None,
        collection_name: str | None = None,
    ) -> None:
        self._embedder = embedder
        self._client = client or chromadb.Client()
        self._collection = self._client.get_or_create_collection(collection_name or f"lore-{uuid.uuid4().hex}")
        self._next_id = self._collection.count()

    def add_lore(self, texts: list[str]) -> None:
        """Upserts static lore chunks with stable, content-derived ids, so
        reloading the same corpus (e.g. on every CLI launch) overwrites the
        existing entries instead of duplicating them.
        """
        if not texts:
            return
        embeddings = self._embedder.embed_documents(texts)
        ids = [f"lore-{hashlib.sha1(t.encode()).hexdigest()[:16]}" for t in texts]
        self._collection.upsert(documents=texts, embeddings=embeddings, ids=ids)

    def add_event(self, text: str, *, turn: int) -> None:
        """Appends a new event chunk. Ids increment monotonically (seeded
        from the collection's count at startup), so this is safe to call
        repeatedly across a persistent store's lifetime.
        """
        embeddings = self._embedder.embed_documents([text])
        event_id = f"event-{turn}-{self._next_id}"
        self._next_id += 1
        self._collection.add(documents=[text], embeddings=embeddings, ids=[event_id])

    def retrieve(self, query: str, *, k: int = 3) -> list[str]:
        count = self._collection.count()
        if count == 0:
            return []
        results = self._collection.query(
            query_embeddings=[self._embedder.embed_query(query)],
            n_results=min(k, count),
        )
        documents = results.get("documents") or []
        return documents[0] if documents else []


def build_lore_store(
    embedder: Embedder,
    lore_dir: Path,
    *,
    client: chromadb.ClientAPI | None = None,
    collection_name: str | None = None,
) -> LoreStore:
    """A LoreStore preloaded with the chunked lore corpus."""
    store = LoreStore(embedder, client=client, collection_name=collection_name)
    store.add_lore(load_lore_corpus(lore_dir))
    return store
