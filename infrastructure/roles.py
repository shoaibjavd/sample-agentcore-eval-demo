import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct


class MCPServerRole(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, description: str, runtime_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = cdk.Stack.of(self)
        region = stack.region
        account = stack.account

        self.role = iam.Role(
            self,
            "Role",
            description=description,
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "CloudWatchLogs": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="LogGroupManagement",
                            actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/{runtime_name}*"],
                        ),
                        iam.PolicyStatement(
                            sid="LogGroupDiscovery",
                            actions=["logs:DescribeLogGroups"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
                        ),
                        iam.PolicyStatement(
                            sid="LogStreamWrite",
                            actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/{runtime_name}*:log-stream:*"],
                        ),
                    ]
                ),
                "ECRAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="ECRTokenAccess",
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],  # Required by ECR API — cannot be scoped
                        ),
                        iam.PolicyStatement(
                            sid="ECRImageAccess",
                            actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                            resources=[f"arn:aws:ecr:{region}:{account}:repository/cdk-hnb659fds-container-assets-{account}-{region}"],
                        ),
                    ]
                ),
                "XRay": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="XRayTracing",
                            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
                            resources=["*"],  # Required by X-Ray API — cannot be scoped
                        ),
                    ]
                ),
            },
        )


class AgentCoreRuntimeRole(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, description: str, runtime_name: str, model_id: str, mcp_runtime_arn: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = cdk.Stack.of(self)
        region = stack.region
        account = stack.account

        # Extract the base model name without cross-region prefix for ARN construction
        # e.g. "au.anthropic.claude-haiku-4-5-20251001-v1:0" -> "anthropic.claude-haiku-4-5-20251001-v1:0"
        base_model = model_id.split(".", 1)[-1] if "." in model_id else model_id

        bedrock_resources = [
            f"arn:aws:bedrock:{region}::foundation-model/{base_model}",
            f"arn:aws:bedrock:*::foundation-model/{base_model}",
        ]

        a2a_resources = []
        if mcp_runtime_arn:
            a2a_resources.append(mcp_runtime_arn)
        else:
            # Fallback: scope to agent-runtime/* if ARN not yet known (circular dependency)
            a2a_resources.append(f"arn:aws:bedrock-agentcore:{region}:{account}:agent-runtime/*")

        self.role = iam.Role(
            self,
            "Role",
            description=description,
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "CloudWatchLogs": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="LogGroupManagement",
                            actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/{runtime_name}*"],
                        ),
                        iam.PolicyStatement(
                            sid="LogGroupDiscovery",
                            actions=["logs:DescribeLogGroups"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
                        ),
                        iam.PolicyStatement(
                            sid="LogStreamWrite",
                            actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/{runtime_name}*:log-stream:*"],
                        ),
                    ]
                ),
                "ECRAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="ECRTokenAccess",
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],  # Required by ECR API — cannot be scoped
                        ),
                        iam.PolicyStatement(
                            sid="ECRImageAccess",
                            actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                            resources=[f"arn:aws:ecr:{region}:{account}:repository/cdk-hnb659fds-container-assets-{account}-{region}"],
                        ),
                    ]
                ),
                "XRay": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="XRayTracing",
                            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
                            resources=["*"],  # Required by X-Ray API — cannot be scoped
                        ),
                    ]
                ),
                "CloudWatch": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="MetricsPublish",
                            actions=["cloudwatch:PutMetricData"],
                            resources=["*"],  # PutMetricData does not support resource-level permissions
                            conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
                        ),
                    ]
                ),
                "BedrockInvocation": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="BedrockModelInvocation",
                            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                            resources=bedrock_resources,
                        ),
                    ]
                ),
                "A2AInvocation": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="InvokeAgentRuntime",
                            actions=["bedrock-agentcore:InvokeAgentRuntime"],
                            resources=a2a_resources,
                        ),
                    ]
                ),
            },
        )

        self.role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                sid="AssumeRolePolicy",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("bedrock-agentcore.amazonaws.com")],
                actions=["sts:AssumeRole"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"},
                },
            )
        )
