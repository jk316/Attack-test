"""
Pktgen TCP Socket Client
Connects to a running Pktgen instance via TCP port 22022 (0x5606).
Sends Lua code and returns the response.

Default host/port are read from topology.yaml via the shared topology module.

Reference: knowledge/socket.html
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

from pktgen_agent.topology import load_topology_config

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
BUFFER_SIZE = 65536


class PktgenConnectionError(ConnectionError):
    """Raised when connection to Pktgen fails or is lost."""


class PktgenClient:
    """TCP client for communicating with a running Pktgen instance.

    Supports context manager protocol::

        with PktgenClient(host="10.99.80.222") as client:
            response = client.execute(lua_code)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if host is None or port is None:
            default_host, default_port = load_topology_config()
            host = host or default_host
            port = port or default_port
        self.host: str = host  # type: ignore[assignment]
        self.port: int = port  # type: ignore[assignment]
        self.timeout: float = timeout
        self._sock: socket.socket | None = None

    def connect(self) -> None:
        """Establish TCP connection to Pktgen."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            logger.info("Connected to Pktgen at %s:%d", self.host, self.port)
        except OSError as e:
            self._sock = None
            raise PktgenConnectionError(
                f"Failed to connect to Pktgen at {self.host}:{self.port}: {e}"
            ) from e

    def disconnect(self) -> None:
        """Close TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass  # Best-effort close
            self._sock = None
            logger.info("Disconnected from Pktgen")

    def is_connected(self) -> bool:
        """Check if socket is currently connected."""
        return self._sock is not None

    def send_lua(self, lua_code: str, read_response: bool = True) -> str:
        """Send Lua code to Pktgen and optionally read the response.

        Args:
            lua_code: Complete Lua script to execute.
            read_response: Whether to wait for and return the response.

        Returns:
            Response string from Pktgen (empty if read_response=False).

        Raises:
            PktgenConnectionError: If not connected.
        """
        if not self._sock:
            raise PktgenConnectionError(
                "Not connected to Pktgen. Call connect() first."
            )

        # Pktgen expects complete Lua statements terminated by newline
        if not lua_code.endswith("\n"):
            lua_code += "\n"

        self._sock.sendall(lua_code.encode("utf-8"))

        if not read_response:
            return ""

        # Read response — Pktgen keeps the connection open so we rely on
        # socket timeout as the end-of-response signal.  This is a known
        # limitation of the Pktgen wire protocol (no length prefix or
        # delimiter).  For large responses, ensure timeout is generous.
        response_parts: list[str] = []
        try:
            while True:
                data = self._sock.recv(BUFFER_SIZE)
                if not data:
                    break
                response_parts.append(data.decode("utf-8", errors="replace"))
        except socket.timeout:
            pass  # Expected — Pktgen doesn't close after each command

        return "".join(response_parts)

    def execute(self, lua_code: str) -> str:
        """High-level: send Lua code and return response."""
        return self.send_lua(lua_code, read_response=True)

    def __enter__(self) -> PktgenClient:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        self.disconnect()
        return False  # Don't suppress exceptions


def execute_lua(
    lua_code: str,
    host: str | None = None,
    port: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Convenience function: connect, execute Lua, disconnect.

    Args:
        lua_code: Lua code to execute.
        host: Pktgen hostname or IP (default: from topology.yaml).
        port: Pktgen TCP port (default: from topology.yaml).
        timeout: Socket timeout in seconds.

    Returns:
        Response from Pktgen.

    Raises:
        PktgenConnectionError: On connection failure.
    """
    with PktgenClient(host=host, port=port, timeout=timeout) as client:
        return client.execute(lua_code)
