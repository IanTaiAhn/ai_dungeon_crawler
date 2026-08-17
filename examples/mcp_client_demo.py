"""Demonstrates the MCP *client* side of the protocol -- the mirror image
of mcp_server.py. Where mcp_server.py exposes the game as MCP tools for an
external caller (e.g. Claude Desktop), this script *is* that external
caller: it opens a real mcp.ClientSession against a running server and
plays a couple of turns purely through the wire protocol. It never
imports GameState, PlayerAction, or anything from graph.py -- as far as
this script is concerned, "dungeon crawler" is just four remote tools with
JSON schemas.

Three things this walks through step by step, on purpose:

1. `session.initialize()` -- the capability-negotiation handshake every
   MCP connection opens with, before any tool can be listed or called.
   `create_connected_server_and_client_session` (used in test_mcp_server.py
   -style tests) does this for you silently; here it's inlined so the
   handshake is visible.
2. `session.list_tools()` -- proof the client discovers tool names,
   descriptions, and JSON schemas from the server *at runtime*. It never
   sees mcp_server.py's `@mcp.tool()` Python functions, only their
   protocol-level descriptions.
3. `session.call_tool(...)` -- each call is a JSON-RPC-shaped request over
   the transport, not a Python function call. The server executes it
   against the *same* GameServer/graph that api.py's HTTP endpoints use
   (see ENTRY-POINTS.md's "sessions.py is not MCP-only" section).

Runs entirely in-process over an in-memory transport (mcp.shared.memory),
with MockNarrator/MockEmbedder standing in for Ollama -- same reason
mock_playthrough_demo.py doesn't need Ollama running (see MOCK-MODE.md).
A real deployment would swap the in-memory streams below for
`mcp.client.stdio.stdio_client` spawning `python -m dungeon_crawler.mcp_server`
as a subprocess (or an SSE/HTTP transport) -- every line from
`ClientSession(...)` down would be unchanged, because MCP clients don't
know or care which transport carried the bytes.

Run it:
    uv run python examples/mcp_client_demo.py
"""

import asyncio
import json
import logging

import anyio

from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from dungeon_crawler.llm import MockNarrator
from dungeon_crawler.mcp_server import create_mcp_server
from dungeon_crawler.retrieval import MockEmbedder

# The server logs "Processing request of type ..." at INFO for every call --
# real evidence each session.call_tool() below is a request over the
# transport, not a local function call. Quieted here so it doesn't interleave
# with this script's own prints; drop this line to see it.
logging.getLogger("mcp").setLevel(logging.WARNING)


def _unwrap(result):
    """CallToolResult carries the tool's return value two ways at once:
    a human-readable TextContent block in .content (always present -- for
    LLMs that just read text) and, *only when FastMCP could infer a
    schema from the tool's return type annotation*, the parsed value
    again in .structuredContent. mcp_server.py's tools are annotated
    `-> dict` (unparametrized), which isn't precise enough for FastMCP to
    build a schema from, so structuredContent comes back None here even
    though every one of these tools does return a dict -- annotating them
    `-> dict[str, Any]` would turn structured output back on. Real
    clients prefer structuredContent when present and fall back to
    parsing .content otherwise, which is what this does."""
    if result.isError:
        raise RuntimeError(result.content[0].text if result.content else "tool call failed")
    if result.structuredContent is not None:
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


async def main() -> None:
    mcp_server = create_mcp_server(MockNarrator(), MockEmbedder())
    low_level_server = mcp_server._mcp_server  # the Server FastMCP wraps; see mcp_server.py's docstring

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low_level_server.run(
                    server_read, server_write, low_level_server.create_initialization_options()
                )
            )

            try:
                async with ClientSession(client_read, client_write) as session:
                    print("=" * 70)
                    print("session.initialize() -- handshake every MCP connection opens with")
                    print("=" * 70)
                    init = await session.initialize()
                    print(f"  server:            {init.serverInfo.name} v{init.serverInfo.version}")
                    print(f"  protocol version:  {init.protocolVersion}")
                    print(f"  server has tools?: {init.capabilities.tools is not None}")

                    print("\n" + "=" * 70)
                    print("session.list_tools() -- tool discovery, purely from the wire")
                    print("=" * 70)
                    tools = await session.list_tools()
                    for tool in tools.tools:
                        params = ", ".join(tool.inputSchema.get("properties", {}))
                        print(f"  {tool.name}({params})")
                        print(f"      {tool.description.splitlines()[0]}")

                    print("\n" + "=" * 70)
                    print("session.call_tool('start_game', {}) -- playing entirely through MCP")
                    print("=" * 70)
                    game = _unwrap(await session.call_tool("start_game", {}))
                    thread_id = game["thread_id"]
                    print(f"  thread_id={thread_id!r}")
                    print(f"  DM said: {game['narration']!r}")

                    for action in ["take rusty sword", "go north"]:
                        print(f"\n>>> call_tool('take_action', {{'raw_text': {action!r}}})")
                        turn = _unwrap(
                            await session.call_tool("take_action", {"thread_id": thread_id, "raw_text": action})
                        )
                        print(f"  DM said: {turn['narration']!r}")

                    print("\n" + "=" * 70)
                    print("session.call_tool('check_inventory', ...) -- state lives server-side,")
                    print("not in this client -- proof the graph's checkpointer is doing the work")
                    print("=" * 70)
                    inventory = _unwrap(await session.call_tool("check_inventory", {"thread_id": thread_id}))
                    print(f"  inventory={inventory!r}")
            finally:
                tg.cancel_scope.cancel()


if __name__ == "__main__":
    asyncio.run(main())
