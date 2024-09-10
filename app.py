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

# !/usr/bin/env python3


import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks, NagSuppressions

from constants import PRIMARY_REGION, SECONDARY_REGION, ACCOUNT_ID
from sagemaker_domain_dr.sagemaker_domain_dr_stack import SagemakerDomainDrStack
from ecs_dr_recovery.ecs_dr_recovery_stack import ECSTaskStack

DISASTER_RECOVERY = True

app = cdk.App()

env_primary_region = cdk.Environment(account=ACCOUNT_ID, region=PRIMARY_REGION)
domain_primary_stack = SagemakerDomainDrStack(
    app, "SagemakerDomainPrimaryStack-NewStudio", env=env_primary_region
)

if DISASTER_RECOVERY:
    env_secondary_region = cdk.Environment(account=ACCOUNT_ID, region=SECONDARY_REGION)
    domain_secondary_stack = SagemakerDomainDrStack(
        app, "SagemakerDomainSecondaryStack-NewStudio", env=env_secondary_region
    )
    ecs_stack = ECSTaskStack(app, "ECSTaskStack-NewStudio", env=env_secondary_region)

cdk.Aspects.of(app).add(AwsSolutionsChecks())
NagSuppressions.add_stack_suppressions(
    domain_primary_stack,
    [
        {"id": "AwsSolutions-IAM4", "reason": 'allow managed policies'},
        {"id": "AwsSolutions-IAM5", "reason": 'wildcard required'},
        {"id": "AwsSolutions-L1", "reason": 'use specific lambda runtime'}
    ]
)
NagSuppressions.add_stack_suppressions(
    domain_secondary_stack,
    [
        {"id": "AwsSolutions-IAM4", "reason": "allow managed policies"},
        {"id": "AwsSolutions-IAM5", "reason": "wildcard required"},
        {"id": "AwsSolutions-L1", "reason": "use specific lambda runtime"}
    ]
)
NagSuppressions.add_stack_suppressions(
    ecs_stack,
    [
        {"id": "AwsSolutions-ECS4", "reason": "CloudWatch Container Insights not required"},
        {"id": "AwsSolutions-IAM4", "reason": "allow managed policies"},
        {"id": "AwsSolutions-IAM5", "reason": "wildcard required"},
        {"id": "AwsSolutions-L1", "reason": "use specific lambda runtime"},
        {"id": "AwsSolutions-SF1", "reason": "not all events require logging"},
        {"id": "AwsSolutions-SF2", "reason": "X-Ray not required"}
    ]
)

app.synth()
