import logging
import os
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP, Context
from pydantic import Field
from pythonjsonlogger.json import JsonFormatter

from src.auth.starlette_middleware import JWTClaimsMiddleware

# json structured logging configuration
json_logging_formatter = JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(message)s",
    datefmt="%Y-%m-%d %H:%M:%Sz"
)
json_logging_handler = logging.StreamHandler()
json_logging_handler.setFormatter(json_logging_formatter)
logging.basicConfig(
    level=logging.getLevelNamesMapping().get(os.getenv("LOG_LEVEL", "INFO")),
    handlers=[json_logging_handler]
)
logger = logging.getLogger(__name__)

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

# Role metadata keys (used by _check_role)
TOOL_ROLES: dict[str, list[str]] = {
    "get_stock_price": ["FinanceUser"],
    "get_employee_count": ["HRUser"],
}


def _check_role(ctx: Context, tool_name: str) -> str | None:
    """Check role-based access. Returns error message if denied, None if allowed.
    M2M tokens (scopes but no roles) bypass role checks.
    Tools not in TOOL_ROLES are public.
    """
    required_roles = TOOL_ROLES.get(tool_name)
    if not required_roles:
        return None  # Public tool

    try:
        auth = ctx.request_context.request.state.auth
    except Exception:
        return None  # No auth state — middleware didn't run or no JWT

    if auth is None:
        return None  # No JWT — let AgentCore handle

    # M2M: has scopes but no roles → bypass
    if auth.scopes and not auth.roles:
        return None

    # User: check roles
    if any(role in auth.roles for role in required_roles):
        return None

    return f"Access denied: requires one of {required_roles}"


@mcp.tool()
def get_current_datetime(
    timezone_name: Annotated[str, Field(
        description="Name of the time zone (IANA time zone database format e.g. 'Australia/Perth', 'UTC')",
        min_length=1
    )] = "UTC"
) -> str:
    """Returns the current date and time in ISO 8601 format."""
    try:
        return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    except ZoneInfoNotFoundError:
        return f"Error: '{timezone_name}' is not a valid time zone."


@mcp.tool()
def get_capital_city(
    country: Annotated[str, Field(description="Country name", min_length=1)]
) -> str:
    """Returns the capital city of a given country."""
    capitals = {
        "united states": "Washington, D.C.",
        "us": "Washington, D.C.",
        "usa": "Washington, D.C.",
        "australia": "Canberra",
        "france": "Paris",
        "germany": "Berlin",
        "japan": "Tokyo",
        "china": "Beijing",
        "india": "New Delhi",
        "brazil": "Brasília",
        "canada": "Ottawa",
        "uk": "London",
        "united kingdom": "London",
    }
    result = capitals.get(country.lower())
    return result if result else f"Capital city for '{country}' not found in database"


@mcp.tool()
def get_stock_price(
    symbol: Annotated[str, Field(description="Stock symbol (e.g., AAPL, GOOGL)", min_length=1)],
    ctx: Context = None,
) -> str:
    """Returns mock stock price. Requires FinanceUser role for user-scoped tokens."""
    if ctx:
        denied = _check_role(ctx, "get_stock_price")
        if denied:
            return denied

    prices = {
        "aapl": "$175.50",
        "googl": "$142.30",
        "msft": "$380.20",
        "amzn": "$178.90",
    }
    symbol_lower = symbol.lower()
    if symbol_lower in prices:
        return f"{symbol.upper()}: {prices[symbol_lower]}"
    return f"{symbol.upper()}: $100.00"


@mcp.tool()
def get_employee_count(
    department: Annotated[str, Field(description="Department name", min_length=1)],
    ctx: Context = None,
) -> str:
    """Returns mock employee count. Requires HRUser role for user-scoped tokens."""
    if ctx:
        denied = _check_role(ctx, "get_employee_count")
        if denied:
            return denied

    counts = {
        "engineering": "150 employees",
        "sales": "80 employees",
        "hr": "25 employees",
        "finance": "40 employees",
    }
    dept_lower = department.lower()
    if dept_lower in counts:
        return f"{department}: {counts[dept_lower]}"
    return f"{department}: 50 employees"


# Build Starlette app with JWT middleware instead of using mcp.run()
app = mcp.streamable_http_app()
app.add_middleware(JWTClaimsMiddleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
