import json
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("setup_iam")

import os
import sys

REGION = "us-east-1"
profile = os.environ.get("AWS_PROFILE", "err0rgod")
if len(sys.argv) > 1 and sys.argv[1].startswith("--profile="):
    profile = sys.argv[1].split("=")[1]
elif len(sys.argv) > 2 and sys.argv[1] == "--profile":
    profile = sys.argv[2]

logger.info(f"Using AWS Profile: '{profile}'")
session = boto3.Session(profile_name=profile, region_name=REGION)
sts = session.client("sts")
iam = session.client("iam")
ddb = session.client("dynamodb")

ACCOUNT_ID = sts.get_caller_identity()["Account"]
logger.info(f"Targeting AWS Account ID: {ACCOUNT_ID} (Region: {REGION})")

# Look up DynamoDB stream ARN dynamically
try:
    desc = ddb.describe_table(TableName="zerodaily-articles")["Table"]
    STREAM_ARN = desc.get("LatestStreamArn", f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles/stream/*")
except ClientError:
    STREAM_ARN = f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles/stream/*"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

API_ROLE_NAME = "zerodaily-api-role"
API_POLICY_NAME = "zerodaily-api-dynamodb"
API_POLICY_DOC = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
            ],
            "Resource": [
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles",
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles/index/*",
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-users",
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-users/index/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
            ],
            "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:zerodaily/firebase-key*",
        },
    ],
}

WORKER_ROLE_NAME = "zerodaily-worker-role"
WORKER_POLICY_NAME = "zerodaily-worker-permissions"
WORKER_POLICY_DOC = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:DescribeStream",
                "dynamodb:GetRecords",
                "dynamodb:GetShardIterator",
                "dynamodb:ListStreams",
            ],
            "Resource": STREAM_ARN,
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
            ],
            "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles",
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
            ],
            "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:zerodaily/firebase-key*",
        },
    ],
}

SCRAPER_ROLE_NAME = "zerodaily-scraper-role"
SCRAPER_POLICY_NAME = "zerodaily-scraper-permissions"
SCRAPER_POLICY_DOC = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
                "secretsmanager:DescribeSecret",
            ],
            "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:zerodaily/firebase-key*",
        },
    ],
}

BASIC_EXECUTION_ARN = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
DYNAMODB_FULL_ARN = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
S3_FULL_ARN = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
BEDROCK_FULL_ARN = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"


def ensure_role(role_name: str, trust_policy: dict) -> str:
    try:
        response = iam.get_role(RoleName=role_name)
        arn = response["Role"]["Arn"]
        logger.info(f"Role '{role_name}' already exists: {arn}")
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            logger.info(f"Creating role '{role_name}'...")
            response = iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Execution role for {role_name}",
            )
            arn = response["Role"]["Arn"]
            logger.info(f"Role '{role_name}' created: {arn}")
            return arn
        raise


def setup():
    # 1. Setup API Role
    api_arn = ensure_role(API_ROLE_NAME, TRUST_POLICY)
    iam.attach_role_policy(RoleName=API_ROLE_NAME, PolicyArn=BASIC_EXECUTION_ARN)
    iam.put_role_policy(
        RoleName=API_ROLE_NAME,
        PolicyName=API_POLICY_NAME,
        PolicyDocument=json.dumps(API_POLICY_DOC),
    )
    logger.info(f"Attached policies to {API_ROLE_NAME}")

    # 2. Setup Worker Role
    worker_arn = ensure_role(WORKER_ROLE_NAME, TRUST_POLICY)
    iam.attach_role_policy(RoleName=WORKER_ROLE_NAME, PolicyArn=BASIC_EXECUTION_ARN)
    iam.put_role_policy(
        RoleName=WORKER_ROLE_NAME,
        PolicyName=WORKER_POLICY_NAME,
        PolicyDocument=json.dumps(WORKER_POLICY_DOC),
    )
    logger.info(f"Attached policies to {WORKER_ROLE_NAME}")

    # 3. Setup Scraper Role
    scraper_arn = ensure_role(SCRAPER_ROLE_NAME, TRUST_POLICY)
    iam.attach_role_policy(RoleName=SCRAPER_ROLE_NAME, PolicyArn=BASIC_EXECUTION_ARN)
    iam.attach_role_policy(RoleName=SCRAPER_ROLE_NAME, PolicyArn=DYNAMODB_FULL_ARN)
    iam.attach_role_policy(RoleName=SCRAPER_ROLE_NAME, PolicyArn=S3_FULL_ARN)
    iam.attach_role_policy(RoleName=SCRAPER_ROLE_NAME, PolicyArn=BEDROCK_FULL_ARN)
    iam.put_role_policy(
        RoleName=SCRAPER_ROLE_NAME,
        PolicyName=SCRAPER_POLICY_NAME,
        PolicyDocument=json.dumps(SCRAPER_POLICY_DOC),
    )
    logger.info(f"Attached policies to {SCRAPER_ROLE_NAME}")

    print("\n" + "=" * 60)
    print("SUCCESSFULLY CREATED / CONFIGURED IAM ROLES:")
    print(f"API Role ARN:     {api_arn}")
    print(f"Worker Role ARN:  {worker_arn}")
    print(f"Scraper Role ARN: {scraper_arn}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    setup()

