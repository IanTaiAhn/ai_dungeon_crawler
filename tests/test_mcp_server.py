import asyncio
import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.mcp_server import create_mcp_server
from dungeon_crawler.retrieval import MockEmbedder


def _call(mcp, name, arguments):
    """Normalizes mcp.call_tool()'s two possible return shapes (a bare
    content-block list, or (content, structured_result)) into the plain
    Python value the tool actually returned.
    """
    result = asyncio.run(mcp.call_tool(name, arguments))
    if isinstance(result, tuple):
        content, structured = result
        return structured.get("result", structured)
    return json.loads(result[0].text)


@pytest.fixture
def mcp():
    return create_mcp_server(MockNarrator(), MockEmbedder())


def test_start_game_returns_thread_id_and_intro(mcp):
    result = _call(mcp, "start_game", {})
    assert result["status"] == "awaiting_action"
    assert "thread_id" in result


def test_start_game_with_unknown_persona_raises(mcp):
    with pytest.raises(ToolError):
        _call(mcp, "start_game", {"persona_name": "does_not_exist"})


def test_take_action_advances_the_game(mcp):
    thread_id = _call(mcp, "start_game", {})["thread_id"]
    result = _call(mcp, "take_action", {"thread_id": thread_id, "raw_text": "wait"})
    assert result["turn"] == 2


def test_take_action_on_unknown_game_raises(mcp):
    with pytest.raises(ToolError):
        _call(mcp, "take_action", {"thread_id": "nonexistent", "raw_text": "wait"})


def test_check_inventory_reflects_progress(mcp):
    thread_id = _call(mcp, "start_game", {})["thread_id"]
    _call(mcp, "take_action", {"thread_id": thread_id, "raw_text": "take rusty sword"})
    inventory = _call(mcp, "check_inventory", {"thread_id": thread_id})
    assert inventory == ["rusty sword"]


def test_check_inventory_on_unknown_game_raises(mcp):
    with pytest.raises(ToolError):
        _call(mcp, "check_inventory", {"thread_id": "nonexistent"})


def test_save_game_reports_current_status(mcp):
    thread_id = _call(mcp, "start_game", {})["thread_id"]
    _call(mcp, "take_action", {"thread_id": thread_id, "raw_text": "wait"})
    saved = _call(mcp, "save_game", {"thread_id": thread_id})
    assert saved == {"saved": True, "turn_count": 1, "location": "entrance"}


def test_roll_dice_returns_the_requested_count_within_range(mcp):
    rolls = _call(mcp, "roll_dice", {"sides": 6, "count": 5})
    assert len(rolls) == 5
    assert all(1 <= roll <= 6 for roll in rolls)


def test_roll_dice_rejects_invalid_input(mcp):
    with pytest.raises(ToolError):
        _call(mcp, "roll_dice", {"sides": 1, "count": 1})
