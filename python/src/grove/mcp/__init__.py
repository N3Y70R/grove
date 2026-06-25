"""grove MCP facade: worktree operations exposed as MCP tools.

Thin layer over ``grove.core`` (see spec §13). The operation logic lives in
``_ops`` (importable without the MCP SDK); ``server`` wraps it as tools.
"""
