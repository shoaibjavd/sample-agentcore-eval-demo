import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.aws_bedrockagentcore import CfnRuntime
import cdk_nag
from constructs import Construct

from infrastructure.roles import AgentCoreRuntimeRole, MCPServerRole


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
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="index.handler",
            code=_lambda.Code.from_asset(str(repo_root / "infrastructure" / "pre_token_lambda")),
        )

        pool = cognito.UserPool(
            self, "SharedPool",
            user_pool_name=f"shared-{stage}-pool",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            custom_attributes={"roles": cognito.StringAttribute(mutable=True)},
            lambda_triggers=cognito.UserPoolTriggers(
                pre_token_generation=pre_token_fn,
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
            ),
        )

        # Upgrade to V2_0 trigger (required for access token customization —
        # V1_0 only supports ID token customization, not access tokens)
        cfn_pool = pool.node.default_child
        cfn_pool.add_property_override(
            "LambdaConfig.PreTokenGenerationConfig",
            {"LambdaArn": pre_token_fn.function_arn, "LambdaVersion": "V2_0"},
        )

        mcp_rs = pool.add_resource_server(
            "MCPRS", identifier="mcp",
            scopes=[cognito.ResourceServerScope(scope_name="invoke", scope_description="Invoke MCP server")],
        )
        agent_rs = pool.add_resource_server(
            "AgentRS", identifier="agentcore",
            scopes=[cognito.ResourceServerScope(scope_name="invoke", scope_description="Invoke assistant agent")],
        )

        m2m_client = pool.add_client(
            "M2MClient", generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.custom("agentcore/invoke"), cognito.OAuthScope.custom("mcp/invoke")],
            ),
        )
        m2m_client.node.add_dependency(mcp_rs)
        m2m_client.node.add_dependency(agent_rs)

        user_client = pool.add_client(
            "UserClient", generate_secret=False,
            auth_flows=cognito.AuthFlow(admin_user_password=True, user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True, implicit_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE,
                    cognito.OAuthScope.custom("agentcore/invoke"), cognito.OAuthScope.custom("mcp/invoke"),
                ],
                callback_urls=["http://localhost:3000/callback"],
            ),
        )
        user_client.node.add_dependency(mcp_rs)
        user_client.node.add_dependency(agent_rs)

        domain = pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"shared-{stage}-{cdk.Aws.ACCOUNT_ID}"),
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
            removal_policy=cdk.RemovalPolicy.DESTROY,
            secret_object_value={
                "client_id": cdk.SecretValue.unsafe_plain_text(m2m_client.user_pool_client_id),
                "client_secret": m2m_client.user_pool_client_secret,
                "token_endpoint": cdk.SecretValue.unsafe_plain_text(token_endpoint),
            },
        )

        # --- MCP Server Runtime ---
        mcp_role = MCPServerRole(self, "MCPServerRole", description="Execution role for MCP server", runtime_name=f"mcp_server_{stage}")

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
            environment_variables={"AWS_DEFAULT_REGION": region, "LOG_LEVEL": "DEBUG", "DEPLOY_VERSION": "9", "USER_POOL_ID": pool.user_pool_id},
        )

        # --- Assistant Agent Runtime ---
        agent_role = AgentCoreRuntimeRole(
            self, "AgentRole",
            description="Execution role for assistant agent",
            runtime_name=f"assistant_agent_{stage}",
            model_id="au.anthropic.claude-haiku-4-5-20251001-v1:0",
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
                "LOG_LEVEL": "DEBUG",
                "MODEL_ID": "au.anthropic.claude-haiku-4-5-20251001-v1:0",
                "MCP_SERVER_ARN": mcp_runtime.attr_agent_runtime_arn,
                "MCP_OAUTH_SCOPE": "mcp/invoke",
                "MCP_CLIENT_ID": m2m_client.user_pool_client_id,
                "MCP_TOKEN_ENDPOINT": token_endpoint,
                "SECRET_ARN": m2m_secret.secret_arn,
                "DEPLOY_VERSION": "18",
            },
        )

        m2m_secret.grant_read(agent_role.role)

        # --- Outputs ---
        cdk.CfnOutput(self, "SharedUserPoolId", value=pool.user_pool_id)
        cdk.CfnOutput(self, "M2MClientId", value=m2m_client.user_pool_client_id)
        cdk.CfnOutput(self, "UserClientId", value=user_client.user_pool_client_id)
        cdk.CfnOutput(self, "TokenEndpoint", value=token_endpoint)
        cdk.CfnOutput(self, "MCPRuntimeId", value=mcp_runtime.attr_agent_runtime_id)
        cdk.CfnOutput(self, "MCPRuntimeArn", value=mcp_runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "AgentRuntimeId", value=agent_runtime.attr_agent_runtime_id)
        cdk.CfnOutput(self, "AgentRuntimeArn", value=agent_runtime.attr_agent_runtime_arn)

        # --- cdk-nag suppressions ---
        cdk_nag.NagSuppressions.add_resource_suppressions(
            pool,
            [
                cdk_nag.NagPackSuppression(id="AwsSolutions-COG2", reason="MFA not required for dev/demo environment with pre-created test users"),
                cdk_nag.NagPackSuppression(id="AwsSolutions-COG8", reason="Cognito Plus tier not needed for dev/demo — advanced security features are not required"),
            ],
        )
        cdk_nag.NagSuppressions.add_resource_suppressions(
            m2m_secret,
            [cdk_nag.NagPackSuppression(id="AwsSolutions-SMG4", reason="M2M client secret is managed by Cognito User Pool; independent rotation is not applicable")],
        )
        cdk_nag.NagSuppressions.add_resource_suppressions(
            pre_token_fn,
            [cdk_nag.NagPackSuppression(id="AwsSolutions-IAM4", reason="AWSLambdaBasicExecutionRole is acceptable for a simple pre-token-generation Lambda with no other resource access")],
            apply_to_children=True,
        )
        # Custom resource Lambda created by CDK for DescribeUserPoolClient
        cdk_nag.NagSuppressions.add_stack_suppressions(
            self,
            [cdk_nag.NagPackSuppression(id="AwsSolutions-IAM4", reason="CDK-managed custom resource Lambda uses AWSLambdaBasicExecutionRole; not user-controlled", applies_to=["Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"])],
        )
        # Remaining wildcards are required by AWS API design:
        # - ecr:GetAuthorizationToken requires Resource:* (API constraint)
        # - xray:Put*/Get* requires Resource:* (API constraint)
        # - cloudwatch:PutMetricData requires Resource:* (scoped by condition key)
        # - logs:DescribeLogGroups scoped to /aws/bedrock-agentcore/runtimes/* (narrowest possible)
        # - A2A InvokeAgentRuntime uses agent-runtime/* due to circular dependency (MCP ARN unknown at role creation time)
        cdk_nag.NagSuppressions.add_resource_suppressions(
            mcp_role.role,
            [cdk_nag.NagPackSuppression(id="AwsSolutions-IAM5", reason="ecr:GetAuthorizationToken, xray, and logs:DescribeLogGroups require Resource:* per AWS API constraints. Log streams scoped to runtime name prefix.")],
            apply_to_children=True,
        )
        cdk_nag.NagSuppressions.add_resource_suppressions(
            agent_role.role,
            [cdk_nag.NagPackSuppression(id="AwsSolutions-IAM5", reason="ecr:GetAuthorizationToken, xray, cloudwatch:PutMetricData (condition-scoped), and logs:DescribeLogGroups require Resource:* per AWS API constraints. Bedrock scoped to specific model. A2A uses agent-runtime/* due to circular deploy dependency.")],
            apply_to_children=True,
        )
