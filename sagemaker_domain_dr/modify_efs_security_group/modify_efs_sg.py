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
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EFS_ID = os.environ["EFS_ID"]
DOMAIN_ID = os.environ["DOMAIN_ID"]


def get_sagemaker_domain_security_group_id():
    ec2 = boto3.client("ec2")
    group_name = f"security-group-for-inbound-nfs-{DOMAIN_ID}"
    response = ec2.describe_security_groups(
        Filters=[
            dict(Name="group-name", Values=[group_name])
        ]
    )
    group_id = response["SecurityGroups"][0]["GroupId"]
    logger.info(f"Sagemaker Domain {DOMAIN_ID} SG: {group_id}")
    return group_id


def lambda_handler(event, context):
    efs_client = boto3.client("efs")
    mount_target_list = efs_client.describe_mount_targets(
        FileSystemId=EFS_ID
    )["MountTargets"]
    logger.info(f"MountTargets: {mount_target_list}")
    for mount_target in mount_target_list:
        mount_target_id = mount_target["MountTargetId"]
        existing_sg_list = efs_client.describe_mount_target_security_groups(
            MountTargetId=mount_target_id
        )["SecurityGroups"]
        logger.info(f"Existing SG list: {existing_sg_list}")
        new_sg = get_sagemaker_domain_security_group_id()
        if new_sg not in existing_sg_list:
            logger.info(f"SG {new_sg} needs to be added to {mount_target_id}")
            modified_security_group_ids = existing_sg_list + [new_sg]
            logger.info(f"Modified SG list: {modified_security_group_ids}")
            response = efs_client.modify_mount_target_security_groups(
                MountTargetId=mount_target_id,
                SecurityGroups=modified_security_group_ids
            )
        logger.info(f"Security groups {new_sg} added successfully.")
    return {
        "statusCode": 200,
    }
