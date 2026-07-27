from dungeon_crawler.retrieval import LoreStore, MockEmbedder, chunk_text


def test_chunk_text_splits_long_text_with_overlap():
    text = "a" * 1000
    chunks = chunk_text(text, size=400, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)


def test_chunk_text_returns_short_text_as_one_chunk():
    assert chunk_text("short text", size=400, overlap=50) == ["short text"]


def test_mock_embedder_is_deterministic():
    embedder = MockEmbedder()
    assert embedder.embed_query("goblin guard room") == embedder.embed_query("goblin guard room")


def test_lore_store_retrieves_the_most_relevant_chunk():
    store = LoreStore(MockEmbedder())
    store.add_lore(
        [
            "The goblin in the guard room is territorial but will not chase you.",
            "The ancient amulet rests on a stone pedestal in the treasure room.",
        ]
    )
    results = store.retrieve("Tell me about the goblin sentry", k=1)
    assert results == ["The goblin in the guard room is territorial but will not chase you."]


def test_lore_store_add_event_is_retrievable():
    store = LoreStore(MockEmbedder())
    store.add_event("Turn 3: the player defeated the goblin guard.", turn=3)
    results = store.retrieve("What happened to the goblin guard?", k=1)
    assert "goblin" in results[0]


def test_add_lore_upserts_instead_of_duplicating():
    store = LoreStore(MockEmbedder())
    corpus = ["The goblin guards the room."]
    store.add_lore(corpus)
    store.add_lore(corpus)  # simulate a second CLI launch reloading the same corpus
    results = store.retrieve("goblin", k=10)
    assert results.count("The goblin guards the room.") == 1


def test_stores_are_isolated_by_default():
    store_a = LoreStore(MockEmbedder())
    store_b = LoreStore(MockEmbedder())
    store_a.add_lore(["only in store a"])
    assert store_b.retrieve("only in store a", k=5) == []
