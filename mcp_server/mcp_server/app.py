from .auth import TokenMiddleware
from .server import mcp

app = TokenMiddleware(mcp.streamable_http_app())
