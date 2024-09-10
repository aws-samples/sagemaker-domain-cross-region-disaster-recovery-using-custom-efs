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
import shutil
import subprocess

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MOUNT_POINT = '/mnt/efs/'
DELETED_DIRECTORY = os.path.join(MOUNT_POINT, "deleted")
EBS_BACKUP_DIRECTORY = os.path.join(MOUNT_POINT, "space_ebs_backup")


def create_user_efs_dir(event):
    domain_id = event['detail']['requestParameters']['domainId']
    user_profile_name = event['detail']['requestParameters']['userProfileName']
    user_uid = event['detail']['requestParameters']['userSettings']['customPosixUserConfig']['uid']
    user_gid = event['detail']['requestParameters']['userSettings']['customPosixUserConfig']['gid']

    logger.info(
        f"domainId: {domain_id}; "
        f"userProfileName: {user_profile_name}; "
        f"event_uid: {user_uid} event_gid: {user_gid}"
    )

    # Create the mount point directory if it doesn't exist
    if not os.path.exists(MOUNT_POINT):
        os.makedirs(MOUNT_POINT)
        logger.info(f'Created mount point directory: {MOUNT_POINT}')
    else:
        logger.info(f'Mount point directory already exists: {MOUNT_POINT}')

    # Create directories in the mounted EFS file system
    directory_path = os.path.join(MOUNT_POINT, user_profile_name)
    os.makedirs(directory_path, exist_ok=True)
    logger.info(f'Created directory: {directory_path}')
    logger.info(f"Directories in {MOUNT_POINT}: {os.listdir(MOUNT_POINT)}")
    # input validation check
    if os.path.isdir(directory_path):
        logger.info(f'Running chown on {directory_path} to {user_uid}')
        subprocess.call(["chown", "-R", str(user_uid), directory_path])
        stat_info = os.stat(directory_path)
        uid = stat_info.st_uid
        gid = stat_info.st_gid
        mode = stat_info.st_mode
        logger.info(f"uid: {uid}, gid: {gid}, mode: {mode}")

        logger.info(f'Running chmod on {directory_path} with 770 permission')
        subprocess.call(["chmod", "-R", "770", directory_path])
        return directory_path


def delete_user_efs_dir(event):
    user_profile_name = event['detail']['requestParameters']['userProfileName']

    if not os.path.exists(DELETED_DIRECTORY):
        os.makedirs(DELETED_DIRECTORY)
        logger.info(f'Created deleted directory: {DELETED_DIRECTORY}')
    else:
        logger.info(f'deleted directory already exists: {MOUNT_POINT}')

    source_dir = os.path.join(MOUNT_POINT, user_profile_name)
    destination_dir = os.path.join(DELETED_DIRECTORY, user_profile_name)
    logger.info(f"Moving: {source_dir}, to: {destination_dir}")
    dest = shutil.move(source_dir, destination_dir)
    logger.info(f"Output: {dest}")

    logger.info(f"Directories in {MOUNT_POINT}: {os.listdir(MOUNT_POINT)}")
    logger.info(f"Directories in {DELETED_DIRECTORY}: {os.listdir(DELETED_DIRECTORY)}")


def create_ebs_backup_dir():
    if not os.path.exists(EBS_BACKUP_DIRECTORY):
        os.makedirs(EBS_BACKUP_DIRECTORY)
        logger.info(f'Created ebs backup directory: {EBS_BACKUP_DIRECTORY}')
        subprocess.call(["chmod", "-R", "777", EBS_BACKUP_DIRECTORY])
    else:
        logger.info('ebs backup directory already exists.')


def lambda_handler(event, context):
    logger.info(f"event: {event}")
    event_type = event['detail']['eventName']
    logger.info(f"event_type: {event_type}")  # DeleteUserProfile, CreateUserProfile
    logger.info(f"context: {context}")

    create_ebs_backup_dir()
    logger.info(f"Directories in /mnt/: {os.listdir('/mnt/')}")
    logger.info(f"Directories in /mnt/efs/: {os.listdir('/mnt/efs/')}")

    if event_type == "DeleteUserProfile":
        delete_user_efs_dir(event)
    elif event_type == "CreateUserProfile":
        user_efs_dir = create_user_efs_dir(event)
        logger.info(f"EFS new dir {user_efs_dir} created.")
    else:
        raise ValueError("Valid Events are DeleteUserProfile or CreateUserProfile")

    return {
        'statusCode': 200,
        'body': json.dumps('EFS directory configured.')
    }
