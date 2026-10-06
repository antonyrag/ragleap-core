"""
ragleap_integrations - connectors that return ragleap_tools.Tool objects.

v0.1.0: an MCP client over Streamable HTTP (see docs/design/mcp-client.md).
"""

__version__ = "0.1.0"

from ragleap_integrations.mcp import (
    Discovery,
    McpClient,
    McpConfig,
    McpConfigError,
    McpDiscoveryError,
    McpServerConfig,
    McpToolSpec,
    make_mcp_tools,
)

__all__ = [
    "__version__",
    "Discovery",
    "McpClient",
    "McpConfig",
    "McpConfigError",
    "McpDiscoveryError",
    "McpServerConfig",
    "McpToolSpec",
    "make_mcp_tools",
]
