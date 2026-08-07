import pytest
from fastapi.testclient import TestClient

from dungeon_crawler.api import create_app
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import MockEmbedder


@pytest.fixture
def client():
    app = create_app(MockNarrator(), MockEmbedder())
    return TestClient(app)


def test_start_game_returns_thread_id_and_intro(client):
    response = client.post("/games", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_action"
    assert "thread_id" in body


def test_start_game_with_unknown_persona_is_404(client):
    response = client.post("/games", json={"persona_name": "does_not_exist"})
    assert response.status_code == 404


def test_start_game_with_known_persona_applies_it(client):
    response = client.post("/games", json={"persona_name": "cautious_scout"})
    assert response.status_code == 200
    thread_id = response.json()["thread_id"]
    status = client.get(f"/games/{thread_id}").json()
    assert status["persona"] == "Wren the Scout"


def test_submit_action_advances_the_game(client):
    thread_id = client.post("/games", json={}).json()["thread_id"]
    response = client.post(f"/games/{thread_id}/actions", json={"raw_text": "wait"})
    assert response.status_code == 200
    assert response.json()["turn"] == 2


def test_submit_action_to_unknown_game_is_404(client):
    response = client.post("/games/nonexistent/actions", json={"raw_text": "wait"})
    assert response.status_code == 404


def test_get_status_reflects_progress(client):
    thread_id = client.post("/games", json={}).json()["thread_id"]
    client.post(f"/games/{thread_id}/actions", json={"raw_text": "take rusty sword"})
    status = client.get(f"/games/{thread_id}").json()
    assert status["inventory"] == ["rusty sword"]


def test_get_status_for_unknown_game_is_404(client):
    response = client.get("/games/nonexistent")
    assert response.status_code == 404


def test_full_playthrough_reaches_a_terminal_outcome(client):
    thread_id = client.post("/games", json={}).json()["thread_id"]
    script = [
        "take rusty sword",
        "go north",
        "attack goblin",
        "attack goblin",
        "attack goblin",
        "attack goblin",
        "attack goblin",
        "go east",
        "take ancient amulet",
        "go down",
        "take frostbound crown",
    ] + ["wait"] * 40
    result = None
    for action in script:
        result = client.post(f"/games/{thread_id}/actions", json={"raw_text": action}).json()
        if result["status"] == "game_over":
            break
    assert result["status"] == "game_over"
    assert result["outcome"] in {"win", "lose"}
