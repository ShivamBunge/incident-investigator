"""Async MCP client wrapper: spawn a stdio MCP server and call its tools.

One server instance is spawned per investigation and reused for all tool
calls. Per-call timeouts enforce the bounded-tool requirement; failures are
raised as MCPToolError so the orchestrator can degrade gracefully (partial
results are allowed — spec Section 12).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    """An MCP tool call failed, timed out, or returned an error result."""


class MCPServer:
    """Async context manager around one stdio MCP server process."""

    def __init__(self, command: str | list[str], timeout_seconds: float = 8.0) -> None:
        if isinstance(command, str):
            command = shlex.split(command)
        self._command = command
        self._timeout = timeout_seconds
        self._stdio_ctx = None
        self._session_ctx = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "MCPServer":
        params = StdioServerParameters(command=self._command[0], args=self._command[1:])
        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        try:
            self._session_ctx = ClientSession(read, write)
            self._session = await self._session_ctx.__aenter__()
            await asyncio.wait_for(self._session.initialize(), self._timeout)
        except Exception as exc:
            await self.__aexit__(None, None, None)
            raise MCPToolError(
                f"failed to start MCP server {self._command!r}: {exc}"
            ) from exc
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(exc_type, exc, tb)
            finally:
                self._session = None
                await self._stdio_ctx.__aexit__(exc_type, exc, tb)
                self._session_ctx = None
                self._stdio_ctx = None

    async def call(self, tool: str, arguments: dict) -> dict:
        """Call a tool and return its JSON result. Raises MCPToolError on failure."""
        if self._session is None:
            raise MCPToolError("MCP server not started")
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool, arguments), self._timeout
            )
        except TimeoutError as exc:
            raise MCPToolError(f"tool {tool!r} timed out after {self._timeout}s") from exc
        except Exception as exc:  # transport/protocol failures
            raise MCPToolError(f"tool {tool!r} failed: {exc}") from exc

        if result.is_error:
            detail = result.content[0].text if result.content else "unknown error"
            raise MCPToolError(f"tool {tool!r} returned an error: {detail}")
        if not result.content:
            raise MCPToolError(f"tool {tool!r} returned no content")
        return json.loads(result.content[0].text)