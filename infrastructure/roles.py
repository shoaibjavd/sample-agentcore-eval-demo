import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct


class MCPServerRole(Construct):
    def __init__(self, scope: Construct, construct_id: str, description: str, **kwargs) -> None:
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
                "MCPServerPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:DescribeLogGroups"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:*"],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"],
                        ),
                        iam.PolicyStatement(
                            actions=["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
                            resources=["*"],
                        ),
                    ]
                )
            },
        )


class AgentCoreRuntimeRole(Construct):
    def __init__(self, scope: Construct, construct_id: str, description: str, **kwargs) -> None:
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
                "AgentCoreRuntimePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="ECRImageAccess",
                            actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                            resources=[f"arn:aws:ecr:{region}:{account}:repository/*"],
                        ),
                        iam.PolicyStatement(
                            sid="ECRTokenAccess",
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:DescribeLogGroups"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:*"],
                        ),
                        iam.PolicyStatement(
                            actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                            resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"],
                        ),
                        iam.PolicyStatement(
                            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=["cloudwatch:PutMetricData"],
                            resources=["*"],
                            conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
                        ),
                        iam.PolicyStatement(
                            sid="BedrockModelInvocation",
                            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                            resources=["arn:aws:bedrock:*::foundation-model/*", f"arn:aws:bedrock:{region}:{account}:*"],
                        ),
                        iam.PolicyStatement(
                            sid="A2AInvocation",
                            actions=["bedrock-agentcore:InvokeAgentRuntime"],
                            resources=[f"arn:aws:bedrock-agentcore:{region}:{account}:agent-runtime/*"],
                        ),
                    ]
                )
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
