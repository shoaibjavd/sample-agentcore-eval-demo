# MCP Server

FastMCP server deployed as an AgentCore MCP runtime with role-based access control.

## 3-Layer Auth Pattern

1. **AgentCore (Layer 1):** Validates JWT signature, issuer, and expiry before the request reaches the server.
2. **Starlette middleware (Layer 2):** `JWTClaimsMiddleware` decodes the JWT payload and extracts `roles` (from `custom:roles`) and `scopes` (from `scope`/`scp`). Stores the result on `request.state.auth`.
3. **Tool-level checks (Layer 3):** Each tool calls `_check_role()` which consults the `TOOL_ROLES` dict. M2M tokens (scopes but no roles) bypass checks. User tokens must have the required role.

## TOOL_ROLES Configuration

```python
TOOL_ROLES: dict[str, list[str]] = {
    "get_stock_price": ["FinanceUser"],
    "get_employee_count": ["HRUser"],
}
```

Tools not listed in `TOOL_ROLES` are public (no role check).

## Adding a new role-gated tool

1. Define the tool function with `@mcp.tool()` and accept `ctx: Context = None`.
2. Call `_check_role(ctx, "your_tool_name")` at the top — return the error string if denied.
3. Add the tool name and required roles to `TOOL_ROLES`.

```python
@mcp.tool()
def my_sensitive_tool(param: str, ctx: Context = None) -> str:
    if ctx:
        denied = _check_role(ctx, "my_sensitive_tool")
        if denied:
            return denied
    return "result"

TOOL_ROLES["my_sensitive_tool"] = ["AdminUser"]
```
