# MCP Server

FastMCP server deployed as an AgentCore MCP runtime with role-based access control.

## 3-Layer Auth Pattern

1. **AgentCore (Layer 1):** Validates JWT signature, issuer, and expiry via `authorizer_configuration` before the request reaches the container.
2. **Header passthrough (Layer 2):** `request_header_allowlist=["Authorization"]` ensures the JWT is forwarded to the MCP server container.
3. **AuthMiddleware (Layer 3):** `fastmcp.server.dependencies.get_http_headers(include={"authorization"})` reads the JWT from HTTP headers. The middleware decodes claims (without signature verification — already done by Layer 1) and enforces `custom:roles` against tool `meta`. M2M tokens (scopes but no roles) bypass role checks; user tokens must have the required role.

## Role Configuration

Roles are declared directly on tools using `auth_meta()`:

```python
from src.auth import auth_meta

@mcp.tool(tags={"Finance"}, meta=auth_meta(roles=["FinanceUser"]))
def get_stock_price(symbol: str) -> str:
    """Requires FinanceUser role."""
    ...

@mcp.tool(tags={"HR"}, meta=auth_meta(roles=["HRUser"]))
def get_employee_count(department: str) -> str:
    """Requires HRUser role."""
    ...
```

Tools without `meta` are public (no role check).

## Adding a new role-gated tool

1. Define the tool with `@mcp.tool()` and add `meta=auth_meta(roles=[...])`.
2. The `AuthMiddleware` handles enforcement automatically — no manual checks needed.

```python
@mcp.tool(tags={"Admin"}, meta=auth_meta(roles=["AdminUser"]))
def my_sensitive_tool(param: str) -> str:
    """Requires AdminUser role."""
    return "result"
```
