from .auth import TokenMiddleware
from .http_relay import ToolRelay
from .server import mcp

app = TokenMiddleware(ToolRelay(mcp.streamable_http_app()))
