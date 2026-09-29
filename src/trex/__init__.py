"""TRex client integration.

TRex uses a client-server architecture: the agent (client) writes a Python
script that drives the TRex server via its STL/ASTF Python API, then runs it.
This package exposes the "generate → run" loop while keeping file writes and
subprocess execution confined to the `trex_scripts/` sandbox directory.
"""
