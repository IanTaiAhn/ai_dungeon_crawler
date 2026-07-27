import random

from dungeon_crawler.game_logic import (
    apply_damage_to_player,
    check_end_state,
    resolve_attack,
    take_item,
    use_item,
)
from dungeon_crawler.schemas import GameState


def test_resolve_attack_is_deterministic_given_a_seeded_rng():
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    result_a = resolve_attack(attacker_bonus=2, target_ac=10, damage_range=(1, 6), rng=rng_a)
    result_b = resolve_attack(attacker_bonus=2, target_ac=10, damage_range=(1, 6), rng=rng_b)
    assert result_a == result_b


def test_resolve_attack_deals_no_damage_on_a_miss():
    rng = random.Random(1)  # rolls a 1 -> guaranteed miss against a high AC
    result = resolve_attack(attacker_bonus=0, target_ac=100, damage_range=(1, 6), rng=rng)
    assert not result.hit
    assert result.damage == 0


def test_apply_damage_floors_at_zero_hp():
    state = GameState(location="entrance", hp=5)
    apply_damage_to_player(state, 100)
    assert state.hp == 0


def test_take_item_moves_item_from_room_to_inventory():
    state = GameState(location="entrance")
    room_items = ["torch"]
    assert take_item(state, "torch", room_items) is True
    assert state.inventory == ["torch"]
    assert room_items == []


def test_take_item_fails_when_item_not_present():
    state = GameState(location="entrance")
    room_items: list[str] = []
    assert take_item(state, "torch", room_items) is False
    assert state.inventory == []


def test_use_item_removes_from_inventory():
    state = GameState(location="entrance", inventory=["torch"])
    assert use_item(state, "torch") is True
    assert state.inventory == []


def test_use_item_fails_when_not_carried():
    state = GameState(location="entrance")
    assert use_item(state, "torch") is False


def test_check_end_state_lose_on_zero_hp():
    state = GameState(location="entrance", hp=0)
    check_end_state(state, win_flag="won")
    assert state.game_over is True
    assert state.outcome == "lose"


def test_check_end_state_win_on_quest_flag():
    state = GameState(location="entrance", hp=5, quest_flags={"won": True})
    check_end_state(state, win_flag="won")
    assert state.game_over is True
    assert state.outcome == "win"


def test_check_end_state_lose_on_turn_limit():
    state = GameState(location="entrance", hp=5, turn_count=40, max_turns=40)
    check_end_state(state, win_flag="won")
    assert state.game_over is True
    assert state.outcome == "lose"


def test_check_end_state_continues_when_nothing_triggered():
    state = GameState(location="entrance", hp=5, turn_count=1, max_turns=40)
    check_end_state(state, win_flag="won")
    assert state.game_over is False
    assert state.outcome is None
