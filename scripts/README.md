# Scripts

## agentcore_eval.py

Unified evaluation script that runs the full pipeline:

1. **Wait for runtime** — polls AgentCore control plane until the agent runtime is `READY`.
2. **Get OAuth token** — `client_credentials` grant against Cognito.
3. **Invoke agent** — sends each prompt from `eval_dataset.json` via HTTPS with Bearer token (SDK doesn't support OAuth-protected runtimes).
4. **Run evaluations** — uses `bedrock-agentcore-starter-toolkit` to run built-in evaluators against the session traces.
5. **Gate on threshold** — exits non-zero if any evaluator score falls below `EVAL_THRESHOLD`.

## eval_dataset.json

Test prompts covering the agent's tool surface:
- Math (calculator)
- Weather (built-in)
- Geography (MCP: `get_capital_city`)
- Finance (MCP: `get_stock_price`, role-gated)
- HR (MCP: `get_employee_count`, role-gated)

## Environment variables

| Variable | Description |
|---|---|
| `AGENT_RUNTIME_ARN` | ARN of the agent runtime |
| `AGENT_RUNTIME_ID` | ID of the agent runtime |
| `TOKEN_ENDPOINT` | Cognito token endpoint |
| `OAUTH_CLIENT_ID` | M2M client ID |
| `OAUTH_CLIENT_SECRET` | M2M client secret |
| `OAUTH_SCOPE` | OAuth scope (default: `agentcore/invoke`) |
| `EVAL_THRESHOLD` | Minimum passing score (default: `0.8`) |
| `EVAL_DATASET` | Path to dataset file (default: `eval_dataset.json`) |
