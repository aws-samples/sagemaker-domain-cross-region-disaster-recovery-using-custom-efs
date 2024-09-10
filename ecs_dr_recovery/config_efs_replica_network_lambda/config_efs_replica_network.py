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

import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOURCE_EFS_ID = os.environ["SOURCE_EFS_ID"]
TARGET_EFS_ID = os.environ["TARGET_EFS_ID"]
SECONDARY_SAGEMAKER_DOMAIN_ID = os.environ["SECONDARY_SAGEMAKER_DOMAIN_ID"]
DEFAULT_SECURITY_GROUP_ID = os.environ["DEFAULT_SECURITY_GROUP_ID"]


efs_client = boto3.client("efs")
ec2_client = boto3.client("ec2")


def is_mount_target_valid(availability_zone):
    target_efs_describe_response = efs_client.describe_mount_targets(FileSystemId=TARGET_EFS_ID)
    target_efs_mount_targets = target_efs_describe_response["MountTargets"]
    target_efs_mt_dict = [d for d in target_efs_mount_targets if d["AvailabilityZoneName"] == availability_zone][0]
    target_efs_mt_sg = efs_client.describe_mount_target_security_groups(
        MountTargetId=target_efs_mt_dict["MountTargetId"]
    )["SecurityGroups"]

    source_efs_describe_response = efs_client.describe_mount_targets(FileSystemId=SOURCE_EFS_ID)
    source_efs_mount_targets = source_efs_describe_response["MountTargets"]
    source_efs_mt_dict = [d for d in source_efs_mount_targets if d["AvailabilityZoneName"] == availability_zone][0]
    source_efs_mt_sg = efs_client.describe_mount_target_security_groups(
        MountTargetId=source_efs_mt_dict["MountTargetId"]
    )["SecurityGroups"]
    if (target_efs_mt_dict["SubnetId"] == source_efs_mt_dict["SubnetId"]) and (source_efs_mt_sg == target_efs_mt_sg):
        return True
    else:
        return False


def get_efs_security_groups_ids():
    response = ec2_client.describe_security_groups(
        GroupNames=[
            f"security-group-for-inbound-nfs-{SECONDARY_SAGEMAKER_DOMAIN_ID}",
            f"security-group-for-outbound-nfs-{SECONDARY_SAGEMAKER_DOMAIN_ID}"
        ]
    )
    efs_security_groups_ids = [sg["GroupId"] for sg in response["SecurityGroups"]]
    return efs_security_groups_ids


def lambda_handler(event, context):
    efs_security_groups = []
    efs_subnets = []
    target_efs_describe_response = efs_client.describe_mount_targets(FileSystemId=TARGET_EFS_ID)
    for mount_target in target_efs_describe_response["MountTargets"]:
        availability_zone = mount_target["AvailabilityZoneName"]
        vpc_id = mount_target["VpcId"]
        if mount_target["LifeCycleState"] == "available":
            security_groups = efs_client.describe_mount_target_security_groups(
                MountTargetId=mount_target["MountTargetId"]
            )["SecurityGroups"]
            efs_security_groups += security_groups
            efs_subnets.append(mount_target["SubnetId"])
            create_mount_target_kwargs = {
                "FileSystemId": SOURCE_EFS_ID,
                "SubnetId": mount_target["SubnetId"],
                "SecurityGroups": security_groups
            }
            try:
                source_efs_mount_target_creation_response = efs_client.create_mount_target(
                    **create_mount_target_kwargs
                )
            except efs_client.exceptions.MountTargetConflict:
                if is_mount_target_valid(availability_zone):
                    logger.info(f"{availability_zone} MountTarget already exists, skip creation.")
                    continue
                else:
                    raise Exception(
                        f"MountTargetConflict. Please delete existing {availability_zone} MountTarget."
                    )
            source_efs_mount_target_id = source_efs_mount_target_creation_response["MountTargetId"]
            logger.info(
                f"MountTarget {source_efs_mount_target_id} in {vpc_id} {availability_zone} created for {SOURCE_EFS_ID}."
            )
            # Wait MountTarget to be available
            wait_time = 0
            mount_target_state = source_efs_mount_target_creation_response["LifeCycleState"]
            while mount_target_state != "available":
                source_efs_describe_response = efs_client.describe_mount_targets(
                    MountTargetId=source_efs_mount_target_id
                )
                mount_target_state = source_efs_describe_response["MountTargets"][0]["LifeCycleState"]
                time.sleep(30)
                wait_time += 30
                logger.info(f"Waiting {source_efs_mount_target_id} creation completed. {wait_time}s elapsed.")
                if wait_time >= 180:
                    raise Exception(f"MountTarget {vpc_id} {availability_zone} creation failed.")
        else:
            raise Exception(f"Source EFS mount target {mount_target} is not in available status")
    ecs_task_security_groups = get_efs_security_groups_ids() + [DEFAULT_SECURITY_GROUP_ID]
    return {
        "statusCode": 200,
        "body": {
            "vpc_id": vpc_id,
            "ecs_task_security_groups": ecs_task_security_groups,
            "ecs_task_subnets": list(set(efs_subnets))
        }
    }
