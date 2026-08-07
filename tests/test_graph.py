from dungeon_crawler import graph as graph_module
from dungeon_crawler import scenario
from dungeon_crawler.game_logic import AttackResult
from dungeon_crawler.graph import new_game_state
from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.retrieval import LoreStore, MockEmbedder
from dungeon_crawler.schemas import PersonaConfig
from helpers import build_test_graph


def _run(script, thread_id="t", narrator=None, lore_store=None, persona=None, checkin_every=None):
    graph = build_test_graph(script, narrator=narrator, lore_store=lore_store, checkin_every=checkin_every)
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(new_game_state(persona=persona), config)


def test_frozen_cavern_is_sealed_without_the_amulet():
    final = _run(
        [
            "go north",
            "go east",
            "go down",
        ]
    )
    assert final["location"] == "treasure_room"


def test_full_playthrough_can_be_won():
    final = _run(
        [
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
    )
    assert final["outcome"] == "win"
    assert final["location"] == "frozen_cavern"
    assert "ancient amulet" in final["inventory"]
    assert "frostbound crown" in final["inventory"]


def test_moving_into_a_wall_does_not_change_location():
    final = _run(["go west"] * 40)
    assert final["location"] == "entrance"
    assert final["outcome"] == "lose"  # ran out the turn clock


def test_taking_an_absent_item_fails_gracefully():
    final = _run(["take dragon egg"] + ["wait"] * 39)
    assert "dragon egg" not in final["inventory"]
    assert final["outcome"] == "lose"


def test_game_ends_at_the_turn_limit_if_nothing_else_happens():
    final = _run(["wait"] * 40)
    assert final["turn_count"] == 40
    assert final["game_over"] is True
    assert final["outcome"] == "lose"


def test_retrieved_lore_reaches_the_narrator():
    narrator = MockNarrator()
    lore_store = LoreStore(MockEmbedder())
    lore_store.add_lore(["A crumbling stone entrance, torchlight flickering against moss-covered walls."])
    _run(["wait"], narrator=narrator, lore_store=lore_store)
    assert narrator.last_retrieved_lore
    assert "torchlight" in narrator.last_retrieved_lore[0]


def test_turn_events_are_written_back_and_later_retrievable():
    lore_store = LoreStore(MockEmbedder())
    _run(["take rusty sword", "go north"], lore_store=lore_store)
    results = lore_store.retrieve("rusty sword", k=5)
    assert any("rusty sword" in r for r in results)


def test_persona_config_flows_through_to_persisted_state():
    persona = PersonaConfig(name="Wren", goal="Recover the amulet cautiously", risk_tolerance="low")
    final = _run(["wait"] * 40, persona=persona)
    assert final["persona"].name == "Wren"
    assert final["persona"].goal == "Recover the amulet cautiously"


def test_casting_the_flame_spell_before_the_amulet_does_nothing():
    final = _run(["go north", "cast flame at goblin"])
    assert final["spell_charges"] == 0
    assert "goblin" not in final["monster_hp"]


def test_recovering_the_amulet_grants_flame_spell_charges():
    final = _run(["go north", "go east", "take ancient amulet"])
    assert final["spell_charges"] == scenario.FLAME_SPELL_CHARGES


def test_casting_the_flame_spell_consumes_a_charge():
    final = _run(["go north", "go east", "take ancient amulet", "go west", "cast flame at goblin"])
    assert final["spell_charges"] == scenario.FLAME_SPELL_CHARGES - 1


def test_flame_spell_charges_do_not_go_negative():
    # Constructed directly (amulet already held, 0 charges left) rather than
    # scripted from scratch: how many casts it actually takes to defeat the
    # goblin is randomized, and once it's dead, casting again correctly stops
    # consuming charges at all ("nothing here to burn") - so scripting several
    # casts in a row can't reliably exercise the "0 charges left" guard itself.
    graph = build_test_graph(["cast flame at goblin"])
    state = new_game_state()
    state.location = "guard_room"
    state.quest_flags[scenario.KEY_FLAG] = True
    state.spell_charges = 0
    final = graph.invoke(state, {"configurable": {"thread_id": "t"}})
    assert final["spell_charges"] == 0


def test_resolve_combat_applies_the_fire_weakness_bonus(monkeypatch):
    monkeypatch.setattr(graph_module, "resolve_attack", lambda **kwargs: AttackResult(hit=True, damage=4))
    working = new_game_state()
    stats = scenario.MONSTERS["crystal golem"]

    result = graph_module._resolve_combat(
        working,
        "crystal golem",
        stats,
        attacker_bonus=0,
        damage_range=(1, 1),
        hit_verb="hit",
        desc_hit="",
        miss_verb="miss",
        desc_miss="",
        bonus_damage=scenario.FLAME_SPELL_WEAKNESS_BONUS,
        bonus_note="The ice cracks and shatters under the heat.",
    )

    assert working.monster_hp["crystal golem"] == stats.hp - (4 + scenario.FLAME_SPELL_WEAKNESS_BONUS)
    assert "The ice cracks and shatters under the heat." in result
