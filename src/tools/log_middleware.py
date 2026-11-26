"""LangChain middleware that tags ``log_result`` calls with the last traffic tool.

The LLM writes free-form params into ``log_result`` and often forgets to say
which tool produced the iteration. This middleware tracks the last non-log
tool call and injects it into ``log_result``'s ``tool`` argument before the
tool executes — the canonicalizer in :mod:`src.tools.log_tool` never sees an
untagged row unless the LLM itself passes an explicit ``tool``.

Both sync (``invoke``) and async (``ainvoke``) hooks are implemented because
the CLI runs the graph synchronously while the web backend runs it with
``ainvoke``.
"""

import threading
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest

_LOG_TOOL_NAME = "log_result"

# Type alias so both hook signatures stay readable.
_Handler = Callable[[ToolCallRequest], Any]
_AHandler = Callable[[ToolCallRequest], Any]


class ToolTaggerMiddleware(AgentMiddleware):
    """Inject the last traffic tool name into ``log_result`` tool calls.

    State is kept on the middleware instance (one instance per graph). The
    experiment loop executes tool calls serially within a run, so a simple
    lock-guarded attribute is sufficient; the LLM's explicit ``tool`` argument
    always wins, so a stale fallback can only affect untagged legacy rows.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._last_tool: str | None = None

    def _tag(self, tool_call: dict) -> dict:
        """Return the tool_call dict with `tool` injected for log_result."""
        name = tool_call.get("name")
        args = dict(tool_call.get("args") or {})
        if name == _LOG_TOOL_NAME:
            if not args.get("tool"):
                with self._lock:
                    last = self._last_tool
                args["tool"] = last or "unknown"
            return {**tool_call, "args": args}
        with self._lock:
            self._last_tool = name
        return tool_call

    def wrap_tool_call(self, request: ToolCallRequest, handler: _Handler):
        """Sync path (CLI ``graph.invoke``)."""
        request = request.override(tool_call=self._tag(request.tool_call))
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: _AHandler):
        """Async path (web backend ``graph.ainvoke``)."""
        request = request.override(tool_call=self._tag(request.tool_call))
        return await handler(request)
