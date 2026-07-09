"""E2E tests for PktgenClient — real TCP connection to Pktgen-DPDK.

Auto-skips when Pktgen is not reachable (detected at session scope via
the ``pktgen_available`` fixture in conftest.py).

Requires: a running Pktgen instance at the host:port defined in topology.yaml.
"""

from __future__ import annotations

import pytest

from pktgen_agent.client import (
    DEFAULT_TIMEOUT,
    PktgenClient,
    PktgenConnectionError,
    execute_lua,
)

pytestmark = pytest.mark.integration


class TestClientConnectDisconnect:
    """Connection lifecycle against a real Pktgen instance."""

    def test_connect_sets_is_connected(self, pktgen_available, pktgen_host_port):
        host, port = pktgen_host_port
        client = PktgenClient(host=host, port=port)
        try:
            client.connect()
            assert client.is_connected()
        finally:
            client.disconnect()

    def test_disconnect_clears_connected(self, pktgen_available, pktgen_host_port):
        host, port = pktgen_host_port
        client = PktgenClient(host=host, port=port)
        client.connect()
        client.disconnect()
        assert not client.is_connected()

    def test_context_manager_auto_disconnects(self, pktgen_available, pktgen_host_port):
        host, port = pktgen_host_port
        with PktgenClient(host=host, port=port) as client:
            assert client.is_connected()
        assert not client.is_connected()

    def test_double_disconnect_is_safe(self, pktgen_available, pktgen_host_port):
        host, port = pktgen_host_port
        client = PktgenClient(host=host, port=port)
        client.connect()
        client.disconnect()
        client.disconnect()  # Should not raise
        assert not client.is_connected()


class TestSendLua:
    """Sending Lua code and reading responses."""

    def test_send_simple_printf(self, client):
        """Send a minimal printf and verify we get a response."""
        response = client.execute('printf("integration_test_hello\\n")\n')
        # Pktgen should echo or acknowledge — response may vary by version
        # but should not contain error markers
        assert "error" not in response.lower()

    def test_send_multiple_commands(self, client):
        """Send two commands in sequence over the same connection."""
        r1 = client.execute('printf("cmd1\\n")\n')
        r2 = client.execute('printf("cmd2\\n")\n')
        # Both should succeed without connection errors
        assert isinstance(r1, str)
        assert isinstance(r2, str)

    def test_send_lua_no_newline_appends_one(self, client):
        """Lua code without trailing newline should still execute."""
        response = client.send_lua('printf("no_newline_test\\n")', read_response=True)
        assert "error" not in response.lower()

    def test_send_lua_without_response(self, client):
        """read_response=False returns empty string immediately."""
        result = client.send_lua('printf("fire_and_forget\\n")\n', read_response=False)
        assert result == ""


class TestExecuteLuaConvenience:
    """The execute_lua() one-shot convenience function."""

    def test_execute_lua_returns_response(self, pktgen_available, pktgen_host_port):
        host, port = pktgen_host_port
        response = execute_lua(
            'printf("convenience_test\\n")\n', host=host, port=port, timeout=10.0
        )
        assert isinstance(response, str)


class TestConnectionErrors:
    """Error handling when Pktgen is not reachable."""

    def test_connection_refused(self):
        """Connecting to a closed port raises PktgenConnectionError."""
        client = PktgenClient(host="127.0.0.1", port=19999, timeout=1.0)
        with pytest.raises(PktgenConnectionError, match="Failed to connect"):
            client.connect()

    def test_send_without_connect_raises(self, pktgen_host_port):
        """Sending Lua without calling connect() raises."""
        host, port = pktgen_host_port
        client = PktgenClient(host=host, port=port)
        with pytest.raises(PktgenConnectionError, match="Not connected"):
            client.execute('printf("test\\n")\n')

    def test_connect_bad_host_raises(self):
        """Connecting to a non-existent host raises."""
        client = PktgenClient(host="192.0.2.1", port=22022, timeout=2.0)
        with pytest.raises(PktgenConnectionError, match="Failed to connect"):
            client.connect()


class TestFullPipeline:
    """Compile skill → send Lua → verify response against live Pktgen."""

    def test_compile_and_send_hello(self, pktgen_available, pktgen_host_port, compiler):
        """Compile a safe_stop_and_reset skill and send to Pktgen."""
        from pktgen_agent.tools.execute import execute_skill_live

        host, port = pktgen_host_port
        result = execute_skill_live("safe_stop_and_reset", {}, host=host, port=port)
        assert result["success"] is True
        assert result["mode"] == "live"
        assert "lua_code" in result
        # Response may be empty or contain status — should not have error markers
        response = result.get("response", "")
        assert "error" not in response.lower()

    def test_compile_and_send_stats(self, pktgen_available, pktgen_host_port, compiler):
        """Compile a stats_monitoring skill and send to Pktgen."""
        from pktgen_agent.tools.execute import execute_skill_live

        host, port = pktgen_host_port
        result = execute_skill_live(
            "stats_monitoring",
            {"interval_ms": 500, "iterations": 2},
            host=host, port=port,
        )
        assert result["success"] is True
        assert result["mode"] == "live"
