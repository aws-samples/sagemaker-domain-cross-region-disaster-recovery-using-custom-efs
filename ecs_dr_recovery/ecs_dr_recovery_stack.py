"""
 Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 SPDX-License-Identifier: MIT-0

 Permission is hereby granted, free of charge, to any person obtaining a copy of this
 software and associated documentation files (the "Software"), to deal in the Software
 without restriction, including without limitation the rights to use, copy, modify,
 merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 permit persons to whom the Software is furnished to do so.

 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import json
from constructs import Construct
from aws_cdk import (
    aws_lambda,
    aws_ecr_assets as ecr_asset,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_ec2 as ec2,
    aws_stepfunctions as sfn,
    custom_resources as cr,
    Stack,
    Duration,
)
from constants import PRIMARY_REGION


class ECSTaskStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Default VPC
        default_vpc = ec2.Vpc.from_lookup(self, id="DefaultVPC", is_default=True)
        custom_efs_default_sg_id_ssm = ssm.StringParameter.from_string_parameter_name(
            self,
            "RecoveryCustomEFSDefaultSecurityGroupParameter",
            string_parameter_name="/SagemakerDomain/Secondary/CustomEfsDefaultSecurityGroup"
        )
        custom_efs_default_sg_id = custom_efs_default_sg_id_ssm.string_value
        ecs_efs_sg = ec2.CfnSecurityGroup(
            self, "ECSAllowEfsSecurityGroup",
            group_description="Allow Traffic from Custom EFS",
            # the properties below are optional
            group_name="SecurityGroup4EcsAllowEfs",
            security_group_egress=[ec2.CfnSecurityGroup.EgressProperty(
                ip_protocol="-1",
                cidr_ip="0.0.0.0/0",
                description="Allow all outbound",
            )],
            security_group_ingress=[ec2.CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp",
                description=f"Allow HTTP Inbound from {custom_efs_default_sg_id}",
                from_port=80,
                source_security_group_id=custom_efs_default_sg_id,
                to_port=80
            )],
            vpc_id=default_vpc.vpc_id
        )

        # Docker Image
        asset = ecr_asset.DockerImageAsset(
            self,
            "ECSRecoveryImage",
            directory="ecs_image",
        )
        # cluster
        cluster = ecs.Cluster(
            self,
            "SagemakerDomainDrECSCluster",
            cluster_name="SagemakerDomainDrTaskCluster",
            vpc=default_vpc
        )

        # Task Definition
        fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            "SagemakerDomainRecoveryTaskDef",
            ephemeral_storage_gib=50,
            cpu=1024,
            memory_limit_mib=4096,
        )
        # Add Volume
        source_efs_id_ssm = cr.AwsCustomResource(
            self,
            "RetrieveReplicatedEFSId",
            on_update=cr.AwsSdkCall(
                service="SSM",
                action="getParameter",
                parameters={
                    "Name": "/SagemakerDomain/Primary/ReplicaEfsId"
                },
                region=PRIMARY_REGION,
                physical_resource_id=cr.PhysicalResourceId.of(
                    "retrieve-replicated-efs-id-cross-region"
                )
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            )
        )
        source_efs_id = source_efs_id_ssm.get_response_field("Parameter.Value")
        target_efs_id_ssm = ssm.StringParameter.from_string_parameter_name(
            self,
            "RecoveryEFSIdParameter",
            string_parameter_name="/SagemakerDomain/Secondary/CustomEfsId"
        )
        target_efs_id = target_efs_id_ssm.string_value
        fargate_task_definition.add_volume(
            name="source_domain_efs",
            efs_volume_configuration={
                "file_system_id": source_efs_id,
                "root_directory": "/",
                "transit_encryption": "ENABLED",
                "authorization_config": {
                    "iam": "ENABLED"
                }
            }
        )
        fargate_task_definition.add_volume(
            name="target_domain_efs",
            efs_volume_configuration={
                "file_system_id": target_efs_id,
                "root_directory": "/",
                "transit_encryption": "ENABLED",
                "authorization_config": {
                    "iam": "ENABLED"
                }
            }
        )
        # Add Permission
        ecs_exec_role_ecr_token_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=["*"],
            actions=["ecr:GetAuthorizationToken"]
        )
        fargate_task_definition.add_to_execution_role_policy(ecs_exec_role_ecr_token_policy)
        ecs_exec_role_ecr_image_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[f"arn:aws:ecr:{self.region}:{self.account}:repository/{asset.repository}"],
            actions=[
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ]
        )
        fargate_task_definition.add_to_execution_role_policy(ecs_exec_role_ecr_image_policy)
        ecs_exec_role_cw_log_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ]
        )
        fargate_task_definition.add_to_execution_role_policy(ecs_exec_role_cw_log_policy)
        ecs_exec_role_efs_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{source_efs_id}",
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{target_efs_id}"
            ],
            actions=[
                "elasticfilesystem:ClientMount",
                "elasticfilesystem:ClientRootAccess",
                "elasticfilesystem:ClientWrite"
            ]
        )
        fargate_task_definition.add_to_execution_role_policy(ecs_exec_role_efs_policy)
        ecs_dr_task_efs_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{source_efs_id}",
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{target_efs_id}"
            ],
            actions=[
                "elasticfilesystem:ClientMount",
                "elasticfilesystem:ClientRootAccess",
                "elasticfilesystem:ClientWrite"
            ]
        )
        fargate_task_definition.add_to_task_role_policy(ecs_dr_task_efs_policy)
        # Add Container
        container = fargate_task_definition.add_container(
            "SagemakerDomainRecoveryContainer",
            image=ecs.ContainerImage.from_docker_image_asset(asset),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ecs",
            )
        )
        # Add PortMapping
        port_mapping = ecs.PortMapping(
            container_port=80,
            app_protocol=ecs.AppProtocol.http,
            host_port=80,
            name="port-80-mapping",
            protocol=ecs.Protocol.TCP
        )
        container.add_port_mappings(port_mapping)
        # Add MountPoint
        mount_point_source_efs = ecs.MountPoint(
            container_path="/source_efs",
            read_only=True,
            source_volume="source_domain_efs"
        )
        mount_point_target_efs = ecs.MountPoint(
            container_path="/target_efs",
            read_only=False,
            source_volume="target_domain_efs"
        )
        container.add_mount_points(mount_point_source_efs, mount_point_target_efs)

        # Lambda Function for EFS Replica Network Config
        secondary_sagemaker_domain_id_ssm = ssm.StringParameter.from_string_parameter_name(
            self,
            "SecondarySagemakerDomainIdParameter",
            string_parameter_name="/SagemakerDomain/Secondary/DomainId"
        )
        secondary_sagemaker_domain_id = secondary_sagemaker_domain_id_ssm.string_value
        config_efs_replica_network_lambda = aws_lambda.Function(
            self,
            f"ConfigEfsReplicaNetworkLambda",
            code=aws_lambda.Code.from_asset(
                "ecs_dr_recovery/config_efs_replica_network_lambda"
            ),
            handler="config_efs_replica_network.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_10,
            description="Lambda function to config primary region's EFS replica mount target",
            function_name="config-efs-replica-network-lambda-function",
            environment={
                "SOURCE_EFS_ID": source_efs_id,
                "TARGET_EFS_ID": target_efs_id,
                "SECONDARY_SAGEMAKER_DOMAIN_ID": secondary_sagemaker_domain_id,
                "DEFAULT_SECURITY_GROUP_ID": ecs_efs_sg.attr_group_id,
            },
            timeout=Duration.seconds(900),
        )
        lambda_role_efs_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{source_efs_id}",
                f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{target_efs_id}"
            ],
            actions=[
                "elasticfilesystem:DescribeMountTargets",
                "elasticfilesystem:DescribeMountTargetSecurityGroups",
                "elasticfilesystem:CreateMountTarget",
            ]
        )
        config_efs_replica_network_lambda.add_to_role_policy(lambda_role_efs_policy)
        lambda_role_sg_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSecurityGroupRules"
            ]
        )
        config_efs_replica_network_lambda.add_to_role_policy(lambda_role_sg_policy)

        # Recovery Step Function
        sfn_definition = {
            "Comment": "A description of my state machine",
            "StartAt": "Config EFS Mount Target",
            "States": {
                "Config EFS Mount Target": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "OutputPath": "$.Payload",
                    "Parameters": {
                        "FunctionName": f"{config_efs_replica_network_lambda.function_arn}:$LATEST",
                        "Payload.$": "$"
                    },
                    "Retry": [
                        {
                            "ErrorEquals": [
                                "Lambda.ServiceException",
                                "Lambda.AWSLambdaException",
                                "Lambda.SdkClientException",
                                "Lambda.TooManyRequestsException"
                            ],
                            "IntervalSeconds": 1,
                            "MaxAttempts": 3,
                            "BackoffRate": 2
                        }
                    ],
                    "Next": "ECS DR Recovery Task"
                },
                "ECS DR Recovery Task": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::ecs:runTask.sync",
                    "Parameters": {
                        "LaunchType": "FARGATE",
                        "Cluster": cluster.cluster_arn,
                        "TaskDefinition": fargate_task_definition.task_definition_arn,
                        "NetworkConfiguration": {
                            "AwsvpcConfiguration": {
                                "Subnets.$": "$.body.ecs_task_subnets",
                                "SecurityGroups.$": "$.body.ecs_task_security_groups",
                                "AssignPublicIp": "ENABLED"
                            }
                        }
                    },
                    "End": True
                }
            }
        }
        sfn_definition_string = json.dumps(sfn_definition)
        # Create state machine
        dr_state_machine = sfn.StateMachine(
            self,
            "SagemakerStudioDrStateMachine",
            definition_body=sfn.DefinitionBody.from_string(sfn_definition_string),
            state_machine_name="Sagemaker-Studio-DR-SFN",
            timeout=Duration.minutes(60),
        )
        sfn_role_lambda_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[f"{config_efs_replica_network_lambda.function_arn}*"],
            actions=["lambda:InvokeFunction"]
        )
        dr_state_machine.add_to_role_policy(sfn_role_lambda_policy)
        sfn_role_run_task_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[fargate_task_definition.task_definition_arn],
            actions=["ecs:RunTask"]
        )
        dr_state_machine.add_to_role_policy(sfn_role_run_task_policy)

        sfn_role_stop_task_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[f"arn:aws:ecs:{self.region}:{self.account}:task/{cluster.cluster_name}/*"],
            actions=[
                "ecs:StopTask",
                "ecs:DescribeTasks"
            ]
        )
        dr_state_machine.add_to_role_policy(sfn_role_stop_task_policy)
        sfn_role_xray_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=["*"],
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ]
        )
        dr_state_machine.add_to_role_policy(sfn_role_xray_policy)
        sfn_role_pass_role_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[
                config_efs_replica_network_lambda.role.role_arn,
                fargate_task_definition.task_role.role_arn,
                fargate_task_definition.execution_role.role_arn
            ],
            actions=["iam:PassRole"]
        )
        dr_state_machine.add_to_role_policy(sfn_role_pass_role_policy)
        sfn_role_rule_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[f"arn:aws:events:{self.region}:{self.account}:rule/*"],
            actions=[
                "events:PutRule",
                "events:DescribeRule",
                "events:PutTargets"
            ]
        )
        dr_state_machine.add_to_role_policy(sfn_role_rule_policy)

