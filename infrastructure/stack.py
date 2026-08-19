import hashlib
import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.aws_bedrockagentcore import CfnRuntime
from constructs import Construct

from infrastructure.roles import AgentCoreRuntimeRole, MCPServerRole

# Single source of truth for the model: used both for the agent runtime env var and to
# scope the Bedrock IAM grant, so the two cannot drift apart.
MODEL_ID = AgentCoreRuntimeRole.DEFAULT_MODEL_ID


def _removal_policy(stage: str) -> cdk.RemovalPolicy:
    """DESTROY for the throwaway dev stack, RETAIN everywhere else (TS011).

    The Cognito pool holds user identities and the secret holds live credentials, so a
    `cdk destroy` against a real environment would delete authentication data outright.
    The dev stage deliberately keeps DESTROY: the notebooks deploy and tear down
    repeatedly, and retained pools/secrets would collide with the next deploy.
    """
    return cdk.RemovalPolicy.DESTROY if stage == "dev" else cdk.RemovalPolicy.RETAIN


def _account_slug(scope: Construct) -> str:
    """Stable, non-identifying suffix for globally-unique public names.

    The Cognito domain prefix is resolvable from the internet, so embedding the raw
    account ID discloses it (TS009/TS018). Hashing keeps the value deterministic (the
    domain is stable across deploys) and unique per account without revealing it.

    If the account is an unresolved CloudFormation token — which happens when the stack
    is synthesised without an explicit env — fall back to the token so synth still
    works; that path re-exposes the ID, so app.py always passes an explicit account.
    """
    account = cdk.Stack.of(scope).account
    if cdk.Token.is_unresolved(account):
        return cdk.Aws.ACCOUNT_ID
    return hashlib.sha256(account.encode("utf-8")).hexdigest()[:12]


class CombinedStack(cdk.Stack):
    """Deploys the full AgentCore eval demo infrastructure:

    1. Shared Cognito pool — JWT auth for both MCP server and assistant agent
       - M2M client (client_credentials grant) for CI pipelines
       - User client (auth code grant) for interactive users with role claims
       - Pre-token Lambda injects custom:roles into access tokens
    2. MCP Server Runtime — FastMCP server with role-gated tools (finance, HR, datetime)
    3. Assistant Agent Runtime — Strands agent that connects to MCP server for tools
    4. Secrets Manager — stores M2M client credentials for agent → MCP auth
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stage = "dev"
        region = "ap-southeast-2"
        repo_root = Path(__file__).parent.parent

        # --- Shared Cognito Pool ---
        pre_token_fn = _lambda.Function(
            self, "PreTokenFn",
            # Latest supported runtime (AwsSolutions-L1). The handler only reads the
            # event and returns validated claims, so there is no version-specific code.
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="index.handler",
            code=_lambda.Code.from_asset(str(repo_root / "infrastructure" / "pre_token_lambda")),
            # This function is in the authentication path: it injects the custom:roles
            # claim that the MCP server authorizes against. Tracing it means an
            # authorization anomaly can actually be investigated (CKV_AWS_115 / TS018).
            tracing=_lambda.Tracing.ACTIVE,
        )

        pool = cognito.UserPool(
            self, "SharedPool",
            user_pool_name=f"shared-{stage}-pool",
            removal_policy=_removal_policy(stage),
            # Explicit password policy rather than relying on the Cognito default
            # (AwsSolutions-COG1, which the current rule pack flags when unset).
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            # custom:roles is immutable (TS005): it is the authorization claim the MCP
            # server trusts, so it must not be changeable after user creation via
            # AdminUpdateUserAttributes. Roles are set once, at user creation below.
            custom_attributes={"roles": cognito.StringAttribute(mutable=False)},
            lambda_triggers=cognito.UserPoolTriggers(
                pre_token_generation=pre_token_fn,
            ),
        )

        # Upgrade to V2_0 trigger (required for access token customization —
        # V1_0 only supports ID token customization, not access tokens)
        cfn_pool = pool.node.default_child
        cfn_pool.add_property_override(
            "LambdaConfig.PreTokenGenerationConfig",
            {"LambdaArn": pre_token_fn.function_arn, "LambdaVersion": "V2_0"},
        )

        # Per-domain tool scopes (TS001). A machine caller is granted only the domains it
        # needs, so a leaked client secret cannot reach every gated tool, and a newly added
        # gated tool is denied to machine callers until its scope is granted here.
        mcp_rs = pool.add_resource_server(
            "MCPRS", identifier="mcp",
            scopes=[
                cognito.ResourceServerScope(scope_name="invoke", scope_description="Invoke MCP server"),
                cognito.ResourceServerScope(scope_name="finance", scope_description="Access finance tools"),
                cognito.ResourceServerScope(scope_name="hr", scope_description="Access HR tools"),
            ],
        )
        agent_rs = pool.add_resource_server(
            "AgentRS", identifier="agentcore",
            scopes=[cognito.ResourceServerScope(scope_name="invoke", scope_description="Invoke assistant agent")],
        )

        m2m_client = pool.add_client(
            "M2MClient", generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                # Explicit least privilege (TS001): the CI evaluation dataset exercises the
                # finance and HR tools, so those scopes are granted deliberately. Remove a
                # scope here and the matching tool becomes inaccessible to CI.
                scopes=[
                    cognito.OAuthScope.custom("agentcore/invoke"),
                    cognito.OAuthScope.custom("mcp/invoke"),
                    cognito.OAuthScope.custom("mcp/finance"),
                    cognito.OAuthScope.custom("mcp/hr"),
                ],
            ),
        )
        m2m_client.node.add_dependency(mcp_rs)
        m2m_client.node.add_dependency(agent_rs)

        user_client = pool.add_client(
            "UserClient", generate_secret=False,
            auth_flows=cognito.AuthFlow(admin_user_password=True, user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True, implicit_code_grant=True),
                # Deliberately NOT granted mcp/finance or mcp/hr. Tool scopes satisfy the
                # same authorization check as roles, so granting them here would let a user
                # request a scope and reach a tool their role does not permit (TS001/TS005).
                scopes=[
                    cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE,
                    cognito.OAuthScope.custom("agentcore/invoke"), cognito.OAuthScope.custom("mcp/invoke"),
                ],
                callback_urls=["http://localhost:3000/callback"],
            ),
        )
        user_client.node.add_dependency(mcp_rs)
        user_client.node.add_dependency(agent_rs)

        # Domain prefix must be globally unique per region, but it is also publicly
        # resolvable, so it must not disclose the AWS account ID (TS009/TS018).
        # A truncated SHA-256 of the account keeps uniqueness without leaking it.
        # "shared-*" was additionally too generic and collided with unrelated stacks.
        domain = pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"agentcore-{stage}-{_account_slug(self)}"),
        )

        # Pre-create users
        for username, email, role in [("user-a", "user-a@example.com", "FinanceUser"), ("user-b", "user-b@example.com", "HRUser")]:
            cognito.CfnUserPoolUser(
                self, username.replace("-", "").title(),
                user_pool_id=pool.user_pool_id, username=username,
                user_attributes=[
                    cognito.CfnUserPoolUser.AttributeTypeProperty(name="email", value=email),
                    cognito.CfnUserPoolUser.AttributeTypeProperty(name="custom:roles", value=role),
                ],
            )

        # Shared authorizer config
        authorizer = CfnRuntime.AuthorizerConfigurationProperty(
            custom_jwt_authorizer=CfnRuntime.CustomJWTAuthorizerConfigurationProperty(
                discovery_url=f"https://cognito-idp.{region}.amazonaws.com/{pool.user_pool_id}/.well-known/openid-configuration",
                allowed_clients=[m2m_client.user_pool_client_id, user_client.user_pool_client_id],
            )
        )

        token_endpoint = f"https://{domain.domain_name}.auth.{region}.amazoncognito.com/oauth2/token"

        # Store M2M client secret for agent → MCP auth
        m2m_secret = secretsmanager.Secret(
            self, "M2MClientSecret",
            secret_name=f"agentcore/{stage}/m2m-client",
            removal_policy=_removal_policy(stage),
            secret_object_value={
                "client_id": cdk.SecretValue.unsafe_plain_text(m2m_client.user_pool_client_id),
                "client_secret": m2m_client.user_pool_client_secret,
                "token_endpoint": cdk.SecretValue.unsafe_plain_text(token_endpoint),
            },
        )

        # --- MCP Server Runtime ---
        mcp_role = MCPServerRole(self, "MCPServerRole", description="Execution role for MCP server")

        mcp_image = ecr_assets.DockerImageAsset(
            self, "MCPImage",
            directory=str(repo_root / "mcp-server"),
            file="Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=["**/.venv", "**/__pycache__", "**/.pytest_cache", "**/infrastructure", "**/tests"],
        )

        mcp_runtime = CfnRuntime(
            self, "MCPRuntime",
            protocol_configuration="MCP",
            agent_runtime_name=f"mcp_server_{stage}".replace("-", "_"),
            description=f"MCP Server Runtime ({stage})",
            agent_runtime_artifact=CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=CfnRuntime.ContainerConfigurationProperty(container_uri=mcp_image.image_uri)
            ),
            network_configuration=CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
            role_arn=mcp_role.role.role_arn,
            authorizer_configuration=authorizer,
            request_header_configuration=CfnRuntime.RequestHeaderConfigurationProperty(
                request_header_allowlist=["Authorization"]
            ),
            # LOG_LEVEL stays at INFO: DEBUG logs decoded JWT claims and token
            # fragments, which anyone with CloudWatch read access could harvest (TS008).
            environment_variables={"AWS_DEFAULT_REGION": region, "LOG_LEVEL": "INFO", "DEPLOY_VERSION": "9", "USER_POOL_ID": pool.user_pool_id},
        )

        # --- Assistant Agent Runtime ---
        agent_role = AgentCoreRuntimeRole(
            self, "AgentRole",
            description="Execution role for assistant agent",
            model_id=MODEL_ID,
            # The only runtime this agent invokes is the MCP server.
            a2a_target_runtime_arns=[mcp_runtime.attr_agent_runtime_arn],
        )

        agent_image = ecr_assets.DockerImageAsset(
            self, "AgentImage",
            directory=str(repo_root / "agent"),
            file="Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=["**/.venv", "**/__pycache__", "**/.pytest_cache", "**/infrastructure", "**/tests"],
        )

        agent_runtime = CfnRuntime(
            self, "AgentRuntime",
            protocol_configuration="HTTP",
            agent_runtime_name=f"assistant_agent_{stage}".replace("-", "_"),
            description=f"Assistant Agent Runtime ({stage})",
            agent_runtime_artifact=CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=CfnRuntime.ContainerConfigurationProperty(container_uri=agent_image.image_uri)
            ),
            network_configuration=CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
            role_arn=agent_role.role.role_arn,
            authorizer_configuration=authorizer,
            request_header_configuration=CfnRuntime.RequestHeaderConfigurationProperty(
                request_header_allowlist=["Authorization"]
            ),
            environment_variables={
                "AWS_DEFAULT_REGION": region,
                # See TS008 note on the MCP runtime above.
                "LOG_LEVEL": "INFO",
                "MODEL_ID": MODEL_ID,
                "MCP_SERVER_ARN": mcp_runtime.attr_agent_runtime_arn,
                # Scopes the agent requests when minting its own machine token (the
                # fallback path when no user token is present). Must name each tool domain
                # it needs, since scopes now gate tools individually (TS001).
                "MCP_OAUTH_SCOPE": "mcp/invoke mcp/finance mcp/hr",
                "MCP_CLIENT_ID": m2m_client.user_pool_client_id,
                "MCP_TOKEN_ENDPOINT": token_endpoint,
                "SECRET_ARN": m2m_secret.secret_arn,
                "DEPLOY_VERSION": "18",
            },
        )

        m2m_secret.grant_read(agent_role.role)

        # --- Denial-of-wallet detection (TS010) ---
        # AgentCore exposes no request-rate throttle, and both runtimes are PUBLIC, so a
        # caller holding a valid token can drive unbounded model spend. These alarms are a
        # *detection* control on the metric that actually tracks cost. Preventing the spend
        # needs a fronting layer with rate limiting (e.g. API Gateway usage plans or WAF
        # rate rules) plus Bedrock quota limits, which is a deployment-topology decision.
        # Attach an SNS action (or AWS Budgets) to these alarms to get notified.
        for name, metric_name, threshold, unit_label in [
            ("BedrockInvocationSpike", "Invocations", 200, "invocations"),
            ("BedrockInputTokenSpike", "InputTokenCount", 500_000, "input tokens"),
        ]:
            cloudwatch.Alarm(
                self, name,
                alarm_description=(
                    f"More than {threshold} {unit_label} for {MODEL_ID} in 5 minutes — "
                    "possible denial-of-wallet or runaway loop (TS010). Tune per environment."
                ),
                metric=cloudwatch.Metric(
                    namespace="AWS/Bedrock",
                    metric_name=metric_name,
                    dimensions_map={"ModelId": MODEL_ID},
                    period=cdk.Duration.minutes(5),
                    statistic="Sum",
                ),
                threshold=threshold,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

        # --- Outputs ---
        cdk.CfnOutput(self, "SharedUserPoolId", value=pool.user_pool_id)
        cdk.CfnOutput(self, "M2MClientId", value=m2m_client.user_pool_client_id)
        cdk.CfnOutput(self, "UserClientId", value=user_client.user_pool_client_id)
        cdk.CfnOutput(self, "TokenEndpoint", value=token_endpoint)
        cdk.CfnOutput(self, "MCPRuntimeId", value=mcp_runtime.attr_agent_runtime_id)
        cdk.CfnOutput(self, "MCPRuntimeArn", value=mcp_runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "AgentRuntimeId", value=agent_runtime.attr_agent_runtime_id)
        cdk.CfnOutput(self, "AgentRuntimeArn", value=agent_runtime.attr_agent_runtime_arn)
