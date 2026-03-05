# Agent

Strands-based assistant agent deployed as an AgentCore HTTP runtime.

## How it works

The agent combines built-in tools with MCP server tools:

**Built-in tools:**
- `calculator` — math operations (from strands-agents-tools)
- `weather` — mock weather data

**MCP tools (from the MCP server):**
- `get_capital_city` — capital city lookup (public)
- `get_current_datetime` — current time in any timezone (public)
- `get_stock_price` — mock stock prices (requires `FinanceUser` role)
- `get_employee_count` — mock employee counts (requires `HRUser` role)

## Token forwarding

- **User tokens:** If the incoming request has a JWT with a `sub` claim (user token), the agent forwards it to the MCP server so role-based access is enforced.
- **M2M tokens:** For CI pipeline calls (no `sub` claim), the agent uses a shared M2M client-credentials token to call the MCP server. M2M tokens bypass role checks.

## Environment variables

> **Important:** AgentCore Runtime requires ARM64 container images. The Dockerfile uses `--platform=linux/arm64`. If building on x86_64 (e.g., GitHub Actions runners), you need QEMU + Docker Buildx for cross-compilation. The GitHub Actions workflow handles this with `docker/setup-qemu-action` and `docker/setup-buildx-action`.

| Variable | Description |
|---|---|
| `MODEL_ID` | Bedrock model ID (default: `au.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| `MCP_SERVER_ARN` | ARN of the MCP server AgentCore runtime |
| `MCP_OAUTH_SCOPE` | OAuth scope for MCP invocation (default: `mcp/invoke`) |
| `MCP_CLIENT_ID` | Cognito M2M client ID |
| `MCP_CLIENT_SECRET` | Cognito M2M client secret |
| `MCP_TOKEN_ENDPOINT` | Cognito token endpoint URL |
| `AWS_DEFAULT_REGION` | AWS region (default: `ap-southeast-2`) |
