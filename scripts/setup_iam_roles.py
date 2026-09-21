import json
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("setup_iam")

iam = boto3.client("iam")

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
            ],
            "Resource": [
                "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles",
                "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles/index/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
            ],
            "Resource": "arn:aws:secretsmanager:us-east-1:339087217625:secret:zerodaily/firebase-key*",
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
            "Resource": "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles/stream/2026-09-16T09:39:09.468",
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
            ],
            "Resource": "arn:aws:dynamodb:us-east-1:339087217625:table/zerodaily-articles",
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
            ],
            "Resource": "arn:aws:secretsmanager:us-east-1:339087217625:secret:zerodaily/firebase-key*",
        },
    ],
}

BASIC_EXECUTION_ARN = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"


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

    print("\n" + "=" * 60)
    print("SUCCESSFULLY CREATED / CONFIGURED IAM ROLES:")
    print(f"API Role ARN:    {api_arn}")
    print(f"Worker Role ARN: {worker_arn}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    setup()
