import logging
import os
import sys
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("setup_users_table")

REGION = "us-east-1"
TABLE_NAME = "zerodaily-users"

profile = os.environ.get("AWS_PROFILE", "err0rgod")
if len(sys.argv) > 1 and sys.argv[1].startswith("--profile="):
    profile = sys.argv[1].split("=")[1]
elif len(sys.argv) > 2 and sys.argv[1] == "--profile":
    profile = sys.argv[2]

logger.info(f"Connecting to DynamoDB using profile '{profile}' in region '{REGION}'...")
session = boto3.Session(profile_name=profile, region_name=REGION)
ddb = session.client("dynamodb")


def create_or_verify_users_table():
    try:
        desc = ddb.describe_table(TableName=TABLE_NAME)["Table"]
        logger.info(f"Table '{TABLE_NAME}' already exists (Status: {desc['TableStatus']}).")
        return desc["TableArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    logger.info(f"Creating DynamoDB table '{TABLE_NAME}' with EmailIndex GSI...")
    response = ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "EmailIndex",
                "KeySchema": [
                    {"AttributeName": "email", "KeyType": "HASH"},
                ],
                "Projection": {
                    "ProjectionType": "ALL",
                },
            }
        ],
        BillingMode="PAY_PER_REQUEST",
        Tags=[
            {"Key": "Service", "Value": "ZeroDaily"},
            {"Key": "Environment", "Value": "production"},
        ],
    )
    table_arn = response["TableDescription"]["TableArn"]
    logger.info(f"DynamoDB table creation initiated. ARN: {table_arn}")
    waiter = ddb.get_waiter("table_exists")
    logger.info(f"Waiting for '{TABLE_NAME}' to reach ACTIVE status...")
    waiter.wait(TableName=TABLE_NAME)
    logger.info(f"Table '{TABLE_NAME}' is now ACTIVE and ready for serving.")
    return table_arn


if __name__ == "__main__":
    create_or_verify_users_table()
