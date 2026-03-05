# AgentCore Evaluation Pipeline with MCP Role-Based Access Control

Reference implementation for running automated evaluations on an AgentCore-hosted agent that connects to an MCP server with role-based access control. The CI/CD pipeline deploys infrastructure, invokes the agent, runs evaluations, and gates the PR on quality thresholds.

## Architecture

```
┌─────────────┐    client_credentials    ┌─────────────────┐
│  CI Pipeline │ ──────────────────────► │  Cognito Pool    │
│  (GitHub)    │ ◄────── M2M token ───── │  (shared)        │
└──────┬───────┘                         └─────────────────┘
       │ Bearer token                        │
       ▼                                     │ JWT validation
┌──────────────────┐                         │
│  Agent Runtime   │ ◄───────────────────────┘
│  (Strands agent) │
│  - calculator    │    Bearer token (forwarded)
│  - weather       │ ──────────────────────────────┐
└──────────────────┘                               ▼
                                          ┌──────────────────┐
                                          │  MCP Server       │
                                          │  (FastMCP)        │
                                          │  - get_capital    │  ← public
                                          │  - get_datetime   │  ← public
                                          │  - get_stock_price│  ← FinanceUser
                                          │  - get_employee   │  ← HRUser
                                          └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │  AgentCore Eval  │
                                          │  API (IAM auth)  │
                                          └──────────────────┘
```

## Auth Flows

**M2M (CI pipelines):** `client_credentials` grant → Cognito issues access token with scopes only → MCP middleware sees scopes + no roles → bypasses role checks → all tools accessible.

**User-scoped (interactive):** `authorization_code` grant → Cognito issues ID token with `custom:roles` claim → agent forwards token to MCP → middleware extracts roles → tool-level checks enforce access (e.g., only `FinanceUser` can call `get_stock_price`).

## 3-Layer MCP Auth

1. **JWT validation (AgentCore):** Signature, issuer, expiry verified by the platform before the request reaches your code.
2. **Claim extraction (Starlette middleware):** Decodes JWT payload, extracts `roles` and `scopes`, stores on `request.state.auth`.
3. **Tool-level role checks:** Each tool checks `TOOL_ROLES` config. M2M tokens bypass; user tokens must have the required role.

## Repo Structure

```
├── README.md                        # This file
├── app.py                           # CDK entry point
├── pyproject.toml                   # Root CDK dependencies
├── cdk.json                         # CDK config
├── agent/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── src/
│       └── assistant_agent.py       # Strands agent with MCP client
├── mcp-server/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── server.py                    # FastMCP server with role-gated tools
│   └── src/
│       ├── auth/
│       │   ├── models.py            # AccessToken Pydantic model
│       │   ├── starlette_middleware.py  # JWT claim extraction
│       │   └── utils.py             # Token parsing helpers
│       └── exceptions.py
├── infrastructure/
│   ├── stack.py                     # CDK stack (Cognito + both runtimes)
│   └── roles.py                     # IAM roles for AgentCore
├── fixtures/
│   └── sample_traces.json           # Pre-collected OTel traces for Approach A
├── scripts/
│   ├── agentcore_eval.py            # Unified eval script (Approach C — live invocation)
│   ├── evaluate_stored_traces.py    # Approach A — evaluate pre-collected fixtures
│   └── eval_dataset.json            # Test prompts
├── .github/
│   └── workflows/
│       └── agentcore-eval.yml       # CI/CD pipeline
└── notebooks/
    └── (placeholder for walkthrough notebook)
```

## Prerequisites

- AWS account with Bedrock AgentCore access
- CDK bootstrapped (`npx cdk bootstrap`)
- Docker installed and running
- Python 3.12+
- Node.js 18+

## Deployment

```bash
# Install CDK dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install .

# Deploy the stack
npx cdk deploy --outputs-file outputs.json
```

CDK outputs include: `SharedUserPoolId`, `M2MClientId`, `UserClientId`, `TokenEndpoint`, `MCPRuntimeId`, `MCPRuntimeArn`, `AgentRuntimeId`, `AgentRuntimeArn`.

## Testing

### M2M (CI-style) invocation

```bash
# Get M2M token
TOKEN=$(curl -s -X POST "$TOKEN_ENDPOINT" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=$M2M_CLIENT_ID&client_secret=$M2M_CLIENT_SECRET&scope=agentcore/invoke" \
  | jq -r '.access_token')

# Invoke agent
curl -X POST "https://bedrock-agentcore.$REGION.amazonaws.com/runtimes/$(python3 -c "import urllib.parse; print(urllib.parse.quote('$AGENT_ARN', safe=''))")/invocations?qualifier=DEFAULT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?"}'
```

### User-scoped invocation

Use the Cognito Hosted UI to sign in as `user-a` (FinanceUser) or `user-b` (HRUser), obtain an ID token, and invoke the agent with that token. Role-gated tools will be enforced based on the user's `custom:roles` claim.

### Run evaluations locally

```bash
cd scripts
export AGENT_RUNTIME_ARN="..."
export AGENT_RUNTIME_ID="..."
export TOKEN_ENDPOINT="..."
export OAUTH_CLIENT_ID="..."
export OAUTH_CLIENT_SECRET="..."
export OAUTH_SCOPE="agentcore/invoke"
export EVAL_THRESHOLD="0.8"

pip install boto3 requests bedrock-agentcore-starter-toolkit
python3 agentcore_eval.py
```

## CI/CD Setup

1. Create an IAM role for GitHub OIDC with permissions to deploy CDK stacks, manage AgentCore runtimes, and invoke Cognito.
2. Add the role ARN as a GitHub secret: `AWS_ROLE_ARN`.
3. Push a PR to `main` — the workflow deploys, evaluates, and tears down automatically.

## Teardown

```bash
source .venv/bin/activate
npx cdk destroy --force
```
