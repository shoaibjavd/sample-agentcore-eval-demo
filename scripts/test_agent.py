"""Test agent tool access for user-a (FinanceUser) and user-b (HRUser).

Verifies the agent can reach MCP tools and that role-based access control
is enforced. Public tools (get_current_datetime, get_capital_city, calculator)
should work for everyone. Role-gated tools should only work for the right user.

Prerequisites:
  - Stack deployed with `npx cdk deploy --outputs-file outputs.json`
  - User passwords set via admin-set-user-password

Environment variables:
  AGENT_RUNTIME_ARN, USER_POOL_ID, USER_CLIENT_ID,
  USER_A_PASSWORD, USER_B_PASSWORD, AWS_REGION (default: ap-southeast-2)
"""

import json
import os
import sys
import time
import urllib.parse

import boto3
import requests

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
AGENT_ARN = os.environ["AGENT_RUNTIME_ARN"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
CLIENT_ID = os.environ["USER_CLIENT_ID"]


def get_access_token(username: str, password: str) -> str:
    cog = boto3.client("cognito-idp", region_name=REGION)
    resp = cog.admin_initiate_auth(
        UserPoolId=USER_POOL_ID, ClientId=CLIENT_ID,
        AuthFlow="ADMIN_NO_SRP_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["AccessToken"]


def invoke(prompt: str, token: str, timeout: int = 120) -> dict:
    escaped = urllib.parse.quote(AGENT_ARN, safe="")
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{escaped}/invocations?qualifier=DEFAULT"
    import uuid
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
        },
        data=json.dumps({"prompt": prompt}),
        timeout=timeout,
    )
    return {"status": r.status_code, "body": r.text}


def check(result: dict, should_contain: list[str] = None, should_not_contain: list[str] = None) -> bool:
    body = result["body"].lower()
    ok = result["status"] == 200
    if should_contain:
        for s in should_contain:
            if s.lower() not in body:
                ok = False
    if should_not_contain:
        for s in should_not_contain:
            if s.lower() in body:
                ok = False
    return ok


TEST_CASES = [
    # (user, prompt, should_contain, should_not_contain, description)

    # Public tools — both users
    ("user-a", "What is the capital of France?", ["paris"], [], "user-a: public tool get_capital_city"),
    ("user-b", "What is the capital of France?", ["paris"], [], "user-b: public tool get_capital_city"),
    ("user-a", "What is the current time in UTC?", ["202"], [], "user-a: public tool get_current_datetime"),
    ("user-b", "How much is 15 * 7?", ["105"], [], "user-b: calculator"),

    # Role-gated: get_stock_price (FinanceUser only)
    ("user-a", "What is the stock price of AAPL?", ["175.50"], [], "user-a (FinanceUser): get_stock_price ALLOWED"),
    ("user-b", "What is the stock price of AAPL?", [], ["175.50"], "user-b (HRUser): get_stock_price DENIED"),

    # Role-gated: get_employee_count (HRUser only)
    ("user-b", "How many employees are in engineering?", ["150"], [], "user-b (HRUser): get_employee_count ALLOWED"),
    ("user-a", "How many employees are in engineering?", [], ["150"], "user-a (FinanceUser): get_employee_count DENIED"),
]


def main():
    pw_a = os.environ["USER_A_PASSWORD"]
    pw_b = os.environ["USER_B_PASSWORD"]

    tokens = {
        "user-a": get_access_token("user-a", pw_a),
        "user-b": get_access_token("user-b", pw_b),
    }

    passed = 0
    failed = 0

    for user, prompt, should_contain, should_not_contain, desc in TEST_CASES:
        print(f"\n{'─'*60}")
        print(f"  {desc}")
        print(f"  Q: {prompt}")
        start = time.time()
        try:
            result = invoke(prompt, tokens[user])
            elapsed = time.time() - start
            body_preview = result["body"][:200].replace("\n", " ")
            print(f"  A: [{result['status']}] ({elapsed:.1f}s) {body_preview}")

            ok = check(result, should_contain, should_not_contain)
            if ok:
                print(f"  ✅ PASS")
                passed += 1
            else:
                print(f"  ❌ FAIL — expected {should_contain}, not {should_not_contain}")
                failed += 1
        except requests.exceptions.Timeout:
            print(f"  ❌ FAIL — TIMEOUT")
            failed += 1
        except Exception as e:
            print(f"  ❌ FAIL — {e}")
            failed += 1

    print(f"\n{'═'*60}")
    print(f"  Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'═'*60}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
