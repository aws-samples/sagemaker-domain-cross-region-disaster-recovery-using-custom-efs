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

import base64
import time
import os
import yaml


from constructs import Construct
from aws_cdk import (
    aws_lambda,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_sagemaker as sagemaker,
    aws_ssm as ssm,
    Stack,
    Duration,
    RemovalPolicy,
    custom_resources as cr,
)
from aws_cdk import Environment

from constants import PRIMARY_REGION, SECONDARY_REGION


class SagemakerDomainDrStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        flag = "Primary" if self.region == PRIMARY_REGION else "Secondary"

        # Default VPC
        default_vpc = ec2.Vpc.from_lookup(self, id="DefaultVPC", is_default=True)

        # Studio Lifecycle Config
        def get_studio_lifecycle_config():
            if self.region == PRIMARY_REGION:
                with open("sagemaker_domain_dr/lifecycle_config_script/backup.sh") as f:
                    script = f.read()
            else:
                with open("sagemaker_domain_dr/lifecycle_config_script/restore.sh") as f:
                    script = f.read()
            script_content = base64.b64encode(script.encode("utf-8")).decode("utf-8")
            return script_content

        jupyterlab_lifecycle_config_custom_resource = cr.AwsCustomResource(
            self,
            id="StudioJupyterLabLifecycleConfig",
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            timeout=Duration.minutes(5),
            on_create=cr.AwsSdkCall(
                service="Sagemaker",
                action="CreateStudioLifecycleConfig",
                parameters={
                    "StudioLifecycleConfigAppType": "JupyterLab",
                    "StudioLifecycleConfigContent": get_studio_lifecycle_config(),
                    "StudioLifecycleConfigName": f"JupyterLab-studio-dr-lifecycle-config-{flag}",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "CreateJupyterLabStudioLifecycleConfig"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="Sagemaker",
                action="DeleteStudioLifecycleConfig",
                parameters={
                    "StudioLifecycleConfigName": f"JupyterLab-studio-dr-lifecycle-config-{flag}",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "CreateJupyterLabStudioLifecycleConfig"
                ),
            ),
        )
        jupyterlab_lifecycle_config_arn = jupyterlab_lifecycle_config_custom_resource.get_response_field(
            'StudioLifecycleConfigArn'
        )
        codeeditor_lifecycle_config_custom_resource = cr.AwsCustomResource(
            self,
            id="StudioCodeEditorLifecycleConfig",
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            timeout=Duration.minutes(5),
            on_create=cr.AwsSdkCall(
                service="Sagemaker",
                action="CreateStudioLifecycleConfig",
                parameters={
                    "StudioLifecycleConfigAppType": "CodeEditor",
                    "StudioLifecycleConfigContent": get_studio_lifecycle_config(),
                    "StudioLifecycleConfigName": f"CodeEditor-studio-dr-lifecycle-config-{flag}",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "CreateCodeEditorStudioLifecycleConfig"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="Sagemaker",
                action="DeleteStudioLifecycleConfig",
                parameters={
                    "StudioLifecycleConfigName": f"CodeEditor-studio-dr-lifecycle-config-{flag}",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "CreateCodeEditorStudioLifecycleConfig"
                ),
            ),
        )
        codeeditor_lifecycle_config_arn = codeeditor_lifecycle_config_custom_resource.get_response_field(
            'StudioLifecycleConfigArn'
        )

        # IAM
        role_sagemaker_studio_domain = iam.Role(
            self,
            f"RoleFor{flag}SagemakerStudioUsersNEW",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            role_name=f"Role{flag}SagemakerStudioUsersNEW",
            managed_policies=[
                iam.ManagedPolicy.from_managed_policy_arn(
                    self,
                    id="SagemakerFullAccess",
                    managed_policy_arn="arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
                ),
                iam.ManagedPolicy.from_managed_policy_arn(
                    self,
                    id="S3FullAccess",
                    managed_policy_arn="arn:aws:iam::aws:policy/AmazonS3FullAccess"
                )
            ],
        )
        role_sagemaker_studio_domain.add_to_policy(
            iam.PolicyStatement(
                actions=["elasticfilesystem:DescribeMountTargets"],
                effect=iam.Effect.ALLOW,
                resources=[
                    f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/*"
                ]
            )
        )

        # EFS & Replica
        if self.region == PRIMARY_REGION:
            custom_efs = efs.FileSystem(
                self, "SageMakerDomainCustomEfs",
                vpc=default_vpc,
                file_system_policy=None,
                replication_configuration=efs.ReplicationConfiguration.regional_file_system(SECONDARY_REGION),
                removal_policy=RemovalPolicy.DESTROY
            )
        else:
            custom_efs = efs.FileSystem(
                self, "SageMakerDomainCustomEfs",
                vpc=default_vpc,
                file_system_policy=None,
                removal_policy=RemovalPolicy.DESTROY
            )
        ssm.StringParameter(
            self,
            f"{flag}CustomEfsDefaultSecurityGroup",
            parameter_name=f"/SagemakerDomain/{flag}/CustomEfsDefaultSecurityGroup",
            string_value=custom_efs.connections.security_groups[0].security_group_id
        )
        efs_policy_removal = cr.AwsCustomResource(
            self,
            id="EfsPolicyRemoval",
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            timeout=Duration.minutes(1),
            on_update=cr.AwsSdkCall(
                service="Efs",
                action="DeleteFileSystemPolicy",
                parameters={
                    "FileSystemId": custom_efs.file_system_id,
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "DeleteEfsPolicy"
                ),
            ),
        )
        efs_root_access_point = custom_efs.add_access_point(
            "AccessPoint",
            path="/",
            create_acl=efs.Acl(
                owner_uid="0", owner_gid="0", permissions="770"
            ),
            # enforce the POSIX identity so lambda function will access with this identity
            posix_user=efs.PosixUser(uid="0", gid="0"),
        )
        ssm.StringParameter(
            self,
            f"{flag}CustomEfsId",
            parameter_name=f"/SagemakerDomain/{flag}/CustomEfsId",
            string_value=custom_efs.file_system_id
        )
        local_region_efs_id = custom_efs.file_system_id
        if self.region == PRIMARY_REGION:
            replica_efs_id_retrieval = cr.AwsCustomResource(
                self,
                id="CustomEfsReplicaSSM",
                policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                    resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
                ),
                timeout=Duration.minutes(5),
                on_update=cr.AwsSdkCall(
                    service="Efs",
                    action="DescribeReplicationConfigurations",
                    parameters={
                        "FileSystemId": local_region_efs_id,
                        "EventTime": f"{int(time.time())}",
                    },
                    physical_resource_id=cr.PhysicalResourceId.of(
                        "CustomEfsReplicaRetrieval"
                    ),
                ),
            )
            ssm.StringParameter(
                self,
                f"{flag}CustomEfsReplicaId",
                parameter_name=f"/SagemakerDomain/{flag}/ReplicaEfsId",
                string_value=replica_efs_id_retrieval.get_response_field(
                    'Replications.0.Destinations.0.FileSystemId'
                )
            )

        # SageMaker Domain
        domain = sagemaker.CfnDomain(
            self,
            f"{flag}SagemakerDomainNew",
            auth_mode="IAM",
            default_user_settings=sagemaker.CfnDomain.UserSettingsProperty(
                execution_role=role_sagemaker_studio_domain.role_arn,
                custom_file_system_configs=[
                    sagemaker.CfnDomain.CustomFileSystemConfigProperty(
                        efs_file_system_config=sagemaker.CfnDomain.EFSFileSystemConfigProperty(
                            file_system_id=local_region_efs_id,
                            file_system_path="/"
                        )
                    )
                ],
                code_editor_app_settings=sagemaker.CfnDomain.CodeEditorAppSettingsProperty(
                    default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                        lifecycle_config_arn=codeeditor_lifecycle_config_arn,
                    ),
                    lifecycle_config_arns=[codeeditor_lifecycle_config_arn]
                ),
                jupyter_lab_app_settings=sagemaker.CfnDomain.JupyterLabAppSettingsProperty(
                    default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                        lifecycle_config_arn=jupyterlab_lifecycle_config_arn,
                    ),
                    lifecycle_config_arns=[jupyterlab_lifecycle_config_arn]
                ),
            ),
            domain_name=f"sagemaker-domain-{flag}",
            vpc_id=default_vpc.vpc_id,
            subnet_ids=default_vpc.select_subnets().subnet_ids,
        )
        domain.node.add_dependency(jupyterlab_lifecycle_config_custom_resource)
        domain.node.add_dependency(codeeditor_lifecycle_config_custom_resource)
        domain.node.add_dependency(efs_policy_removal)
        ssm.StringParameter(
            self,
            f"{flag}SagemakerDomainId",
            parameter_name=f"/SagemakerDomain/{flag}/DomainId",
            string_value=domain.attr_domain_id
        )
        ssm.StringParameter(
            self,
            f"{flag}OriginalEFSId",
            parameter_name=f"/SagemakerDomain/{flag}/Original/EfsId",
            string_value=domain.attr_home_efs_file_system_id
        )

        # EFS User Directory
        create_user_directory_lambda = aws_lambda.Function(
            self, f"{flag}CreateUserDirectoryLambda",
            code=aws_lambda.Code.from_asset(
                "sagemaker_domain_dr/create_user_directory_lambda/",
            ),
            handler="create_user_directory.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            description="Lambda that creates user directory in SageMaker domain custom EFS",
            function_name=f"{flag}-create-user-directory",
            environment={'efs_id': local_region_efs_id},
            timeout=Duration.seconds(900),
            vpc=default_vpc,
            allow_public_subnet=True,
            filesystem=aws_lambda.FileSystem.from_efs_access_point(
                ap=efs_root_access_point, mount_path="/mnt/efs"
            ) if efs_root_access_point else None,
        )

        custom_efs.grant(create_user_directory_lambda.role, "elasticfilesystem:CreateAccessPoint")
        custom_efs.grant(create_user_directory_lambda.role, "elasticfilesystem:ClientWrite")

        # EFS SG
        modify_efs_sg_lambda = aws_lambda.Function(
            self, "ModifyEfsSgLambda",
            code=aws_lambda.Code.from_asset("sagemaker_domain_dr/modify_efs_security_group/"),
            handler="modify_efs_sg.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=Duration.minutes(10),
            description="Lambda that add Sagemaker Domain Security Group",
            function_name=f"{flag}-modify-efs-sg",
            environment={
                "EFS_ID": local_region_efs_id,
                "DOMAIN_ID": domain.attr_domain_id,
            }
        )
        modify_efs_sg_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeSecurityGroups"],
                resources=["*"]
            )
        )
        modify_efs_sg_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "elasticfilesystem:DescribeMountTargets",
                    "elasticfilesystem:DescribeMountTargetSecurityGroups",
                    "elasticfilesystem:ModifyMountTargetSecurityGroups"
                ],
                effect=iam.Effect.ALLOW,
                resources=[
                    f"arn:aws:elasticfilesystem:{self.region}:{self.account}:file-system/{local_region_efs_id}"
                ]
            )
        )
        modify_efs_sg_custom_resource = cr.AwsCustomResource(
            self,
            id="ModifyEfsSgCustomResource",
            timeout=Duration.minutes(5),
            policy=cr.AwsCustomResourcePolicy.from_statements(
                statements=[
                    iam.PolicyStatement(
                        actions=["lambda:InvokeFunction"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            modify_efs_sg_lambda.function_arn,
                        ],
                    ),
                ],
            ),
            on_update=cr.AwsSdkCall(
                service="Lambda",
                action="invoke",
                parameters={
                    "FunctionName": modify_efs_sg_lambda.function_name,
                    "EventTime": f"{int(time.time())}",
                    "InvocationType": "RequestResponse",
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "ModifyEfsSgCustomResource"
                ),
            ),
        )

        # Event Trigger
        user_profile_creation_rule = events.Rule(
            self,
            f"{flag}UserProfileEventRule",
            description="UserProfileEventRule",
            event_pattern=events.EventPattern(
                source=["aws.sagemaker"],
                detail_type=["AWS API Call via CloudTrail"],
                detail={
                    "eventSource": ["sagemaker.amazonaws.com"],
                    "eventName": ["CreateUserProfile", "DeleteUserProfile"]
                }
            ),
            rule_name=f"{flag}UserProfileEventRule"
        )
        user_profile_creation_rule.add_target(
            targets.LambdaFunction(create_user_directory_lambda)
        )

        # SageMaker User Profiles & Spaces
        with open("users.yaml", "r") as f:
            users = yaml.safe_load(f)["Users"]
        for user_name, user_config in users.items():
            custom_posix = user_config.get("CustomPosix", None)
            if custom_posix:
                uid, gid = map(int, custom_posix.split(":"))
                user_profile = sagemaker.CfnUserProfile(
                    self,
                    f"UserProfile{user_name}",
                    domain_id=domain.attr_domain_id,
                    user_profile_name=user_name,
                    user_settings=sagemaker.CfnUserProfile.UserSettingsProperty(
                        custom_file_system_configs=[sagemaker.CfnUserProfile.CustomFileSystemConfigProperty(
                            efs_file_system_config=sagemaker.CfnUserProfile.EFSFileSystemConfigProperty(
                                file_system_id=local_region_efs_id,
                                file_system_path="/"
                            )
                        )],
                        custom_posix_user_config=sagemaker.CfnUserProfile.CustomPosixUserConfigProperty(
                            uid=uid,
                            gid=gid
                        ),
                        jupyter_lab_app_settings=sagemaker.CfnUserProfile.JupyterLabAppSettingsProperty(
                            lifecycle_config_arns=[jupyterlab_lifecycle_config_arn]
                        ),
                        code_editor_app_settings=sagemaker.CfnUserProfile.CodeEditorAppSettingsProperty(
                            lifecycle_config_arns=[codeeditor_lifecycle_config_arn]
                        ),
                    ),
                )
                space_config = user_config.get("Spaces", None)
                if space_config:
                    for space_name, space_type_dict in space_config.items():
                        space_type = space_type_dict["type"]
                        user_space = sagemaker.CfnSpace(
                            self,
                            space_name,
                            domain_id=domain.attr_domain_id,
                            space_name=space_name,
                            ownership_settings=sagemaker.CfnSpace.OwnershipSettingsProperty(
                                owner_user_profile_name=user_profile.user_profile_name
                            ),
                            space_settings=sagemaker.CfnSpace.SpaceSettingsProperty(
                                app_type=space_type,
                                custom_file_systems=[sagemaker.CfnSpace.CustomFileSystemProperty(
                                    efs_file_system=sagemaker.CfnSpace.EFSFileSystemProperty(
                                        file_system_id=local_region_efs_id
                                    )
                                )],
                            ),
                            space_sharing_settings=sagemaker.CfnSpace.SpaceSharingSettingsProperty(
                                sharing_type="Private"
                            ),
                        )
                        user_space.node.add_dependency(user_profile)
            else:
                raise ValueError("This solution requires POSIX configuration for Sagemaker UserProfile.")
            user_profile.node.add_dependency(user_profile_creation_rule)
            user_profile.node.add_dependency(create_user_directory_lambda)
