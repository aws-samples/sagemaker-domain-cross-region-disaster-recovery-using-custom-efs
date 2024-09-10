#!/bin/bash

set -eux

echo pwd=${PWD}
echo SpaceName=${SAGEMAKER_SPACE_NAME}

efs_id=$(ls ./custom-file-systems/efs/ | grep "fs-" | tail -n 1)
echo ${efs_id}

time_now=$(date +%s)
echo ${time_now}

printenv > env.log

mkdir -p custom-file-systems/efs/${efs_id}/space_ebs_backup/${SAGEMAKER_SPACE_NAME}
rsync -a --ignore-existing --exclude custom-file-systems ./ custom-file-systems/efs/${efs_id}/space_ebs_backup/${SAGEMAKER_SPACE_NAME}/