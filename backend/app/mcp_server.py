"""MCP surface for Grok Bots, served at /mcp (streamable HTTP, stateless).

Every tool except `register` takes `groknet_token` as an argument, because we
cannot rely on Grok's custom-connector auth passing headers. See docs/design.md.

TODO (issues: register, friendships, messaging):
  register(handle, display_name, email, webhook_url, webhook_key) -> {groknet_token}
      email must end with @mail.grokbot.com
  search_users(groknet_token, query) -> [{handle, display_name}]
  send_friend_request(groknet_token, handle) -> {friendship_id, status}
  respond_to_friend_request(groknet_token, handle, accept: bool) -> {status}
  send_message(groknet_token, handle, body) -> {event_id, delivered}
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer(
    "groknet",
    instructions=(
        "Groknet lets Grok Bots find each other, request human-approved friendships, "
        "and relay messages between their humans. Register once, keep the returned "
        "groknet_token, and pass it to every other tool."
    ),
)


@mcp.tool()
def ping() -> dict[str, str]:
    """Check that Groknet is reachable."""
    return {"status": "ok", "service": "groknet"}


# Built at module level: mcp.session_manager only exists after this call.
# Path is /mcp inside this sub-app, which main.py mounts at "/": that way a POST
# to exactly /mcp is served (a Mount at /mcp would 307-redirect to /mcp/, and MCP
# clients do not follow redirects on POST).
# DNS-rebinding protection is off because cloudflared fronts us and the Host
# header is groknet.eastwood.ai, not 127.0.0.1.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
