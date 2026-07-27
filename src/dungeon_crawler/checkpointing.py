"""Shared checkpoint serializer configuration.

GameState nests custom types (Intent, PlayerAction, PersonaConfig,
RiskTolerance) that langgraph's checkpoint serializer doesn't recognize out
of the box. Its default behavior is to allow them anyway with a warning that
this will be blocked in a future version, so we allowlist them explicitly
instead of relying on that default.
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from dungeon_crawler.schemas import Intent, PersonaConfig, PlayerAction, RiskTolerance


def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=[Intent, RiskTolerance, PlayerAction, PersonaConfig])
