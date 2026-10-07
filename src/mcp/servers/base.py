from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..models import ToolDefinition, ToolSecurityContext


class BaseMCPServer(ABC):
    """Abstract base class for all Model Context Protocol (MCP) servers."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any], ToolSecurityContext], Any]] = {}
        self._register_tools()

    @abstractmethod
    def _register_tools(self) -> None:
        """Subclasses register their tools and handler methods."""
        pass

    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable[[dict[str, Any], ToolSecurityContext], Any],
    ) -> None:
        """Registers a tool definition and execution handler with the server."""
        self.tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def list_tools(self) -> list[ToolDefinition]:
        """Returns all registered tool definitions."""
        return list(self.tools.values())

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Retrieves definition for a tool."""
        return self.tools.get(name)

    async def execute_tool(
        self,
        tool_name: str,
        validated_input: dict[str, Any],
        context: ToolSecurityContext,
    ) -> Any:
        """Executes handler for the validated tool call."""
        handler = self._handlers.get(tool_name)
        if not handler:
            raise KeyError(f"Tool handler for '{tool_name}' not implemented.")

        import inspect
        if inspect.iscoroutinefunction(handler):
            return await handler(validated_input, context)
        return handler(validated_input, context)
