"""AI tool registry facade."""

from src.tool_registry import TOOLS, call, complete_with_tools

__all__ = ["TOOLS", "call", "complete_with_tools"]
