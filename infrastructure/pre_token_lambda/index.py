"""Pre-token-generation Lambda V2: copies custom:roles into access token claims."""


def handler(event, context):
    roles = event["request"]["userAttributes"].get("custom:roles", "")
    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "accessTokenGeneration": {
                "claimsToAddOrOverride": {"custom:roles": roles},
            }
        }
    }
    return event
