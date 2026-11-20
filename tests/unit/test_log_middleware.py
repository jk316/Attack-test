"""Tests for ToolTaggerMiddleware — injects last tool into log_result calls."""
import pytest

from src.tools.log_middleware import ToolTaggerMiddleware


class FakeRequest:
    """Minimal stand-in for langchain ToolCallRequest (dataclass with override)."""

    def __init__(self, tool_call):
        self.tool_call = tool_call
        self.overridden = None

    def override(self, **overrides):
        self.overridden = overrides
        return FakeRequest(overrides.get("tool_call", self.tool_call))


@pytest.fixture
def mw():
    return ToolTaggerMiddleware()


def test_log_result_gets_last_tool(mw):
    req1 = FakeRequest({"name": "pktgen_udp_flood", "args": {"rate": 50}, "id": "c1"})
    handled = []

    def handler(request):
        handled.append(request)
        return "done"

    assert mw.wrap_tool_call(req1, handler) == "done"
    assert handled[0].tool_call["name"] == "pktgen_udp_flood"

    req2 = FakeRequest({"name": "log_result", "args": {"params": {}, "rtt": 1}, "id": "c2"})
    mw.wrap_tool_call(req2, handler)
    assert handled[-1].tool_call["args"]["tool"] == "pktgen_udp_flood"


def test_explicit_tool_argument_wins(mw):
    # Simulate a preceding tool
    mw.wrap_tool_call(
        FakeRequest({"name": "traffic_send", "args": {}, "id": "c1"}),
        lambda r: None,
    )
    handled = []
    mw.wrap_tool_call(
        FakeRequest({
            "name": "log_result",
            "args": {"tool": "pktgen_tcp_flood", "params": {}, "rtt": 1},
            "id": "c2",
        }),
        lambda r: handled.append(r) or "ok",
    )
    assert handled[0].tool_call["args"]["tool"] == "pktgen_tcp_flood"


def test_log_result_without_prior_tool_gets_unknown(mw):
    handled = []
    mw.wrap_tool_call(
        FakeRequest({"name": "log_result", "args": {"params": {}}, "id": "c1"}),
        lambda r: handled.append(r) or "ok",
    )
    assert handled[0].tool_call["args"]["tool"] == "unknown"


def test_log_result_does_not_overwrite_last_tool(mw):
    """A log_result call must not become the 'last tool' for the next row."""
    mw.wrap_tool_call(
        FakeRequest({"name": "traffic_send", "args": {}, "id": "c1"}),
        lambda r: None,
    )
    mw.wrap_tool_call(
        FakeRequest({"name": "log_result", "args": {"params": {}}, "id": "c2"}),
        lambda r: None,
    )
    handled = []
    mw.wrap_tool_call(
        FakeRequest({"name": "log_result", "args": {"params": {}}, "id": "c3"}),
        lambda r: handled.append(r) or "ok",
    )
    assert handled[0].tool_call["args"]["tool"] == "traffic_send"


def test_async_path_tags_too(mw):
    import asyncio

    async def run():
        await mw.awrap_tool_call(
            FakeRequest({"name": "pktgen_icmp_flood", "args": {}, "id": "c1"}),
            lambda r: asyncio.sleep(0),
        )
        handled = []

        async def handler(request):
            handled.append(request)
            return "done"

        result = await mw.awrap_tool_call(
            FakeRequest({"name": "log_result", "args": {"params": {}}, "id": "c2"}),
            handler,
        )
        assert result == "done"
        assert handled[0].tool_call["args"]["tool"] == "pktgen_icmp_flood"

    asyncio.run(run())
