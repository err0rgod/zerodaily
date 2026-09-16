import os
import shutil
import subprocess
import sys
import zipfile
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("deploy")

REGION = "us-east-1"
ACCOUNT_ID = "339087217625"
API_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/zerodaily-api-role"
WORKER_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/zerodaily-worker-role"
STREAM_ARN = f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/zerodaily-articles/stream/2026-09-16T09:39:09.468"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(BASE_DIR, "build")
API_PKG_DIR = os.path.join(BUILD_DIR, "api_pkg")
WORKER_PKG_DIR = os.path.join(BUILD_DIR, "worker_pkg")

API_ZIP = os.path.join(BUILD_DIR, "zerodaily-api.zip")
WORKER_ZIP = os.path.join(BUILD_DIR, "zerodaily-worker.zip")

lambda_client = boto3.client("lambda", region_name=REGION)


def clean_build():
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    os.makedirs(API_PKG_DIR, exist_ok=True)
    os.makedirs(WORKER_PKG_DIR, exist_ok=True)


def install_dependencies(requirements: list[str], target_dir: str):
    logger.info(f"Installing Linux-compatible binary wheels into {target_dir}...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--platform",
        "manylinux2014_x86_64",
        "--target",
        target_dir,
        "--implementation",
        "cp",
        "--python-version",
        "3.11",
        "--only-binary=:all:",
        "--upgrade",
    ] + requirements

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Pip install failed:\n{result.stderr}")
        raise RuntimeError(f"Pip install failed: {result.stderr}")
    logger.info(f"Successfully installed dependencies in {target_dir}")


def zip_directory(source_dir: str, zip_path: str):
    logger.info(f"Creating zip archive at {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_dir)
                zf.write(full_path, rel_path)
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    logger.info(f"Zip archive created: {zip_path} ({size_mb:.2f} MB)")


def package_api():
    logger.info("--- Packaging zerodaily-api ---")
    api_deps = [
        "fastapi>=0.110.0",
        "mangum>=0.17.0",
        "pydantic>=2.6.0",
        "pydantic-settings>=2.2.0",
        "python-dotenv>=1.0.0",
    ]
    install_dependencies(api_deps, API_PKG_DIR)

    # Copy application code
    dest_app = os.path.join(API_PKG_DIR, "app")
    shutil.copytree(os.path.join(BASE_DIR, "app"), dest_app, dirs_exist_ok=True)

    zip_directory(API_PKG_DIR, API_ZIP)


def package_worker():
    logger.info("--- Packaging zerodaily-worker ---")
    worker_deps = [
        "google-auth>=2.28.0",
        "httpx>=0.27.0",
        "pydantic>=2.6.0",
        "pydantic-settings>=2.2.0",
        "cryptography>=42.0.0",
        "requests>=2.31.0",
    ]
    install_dependencies(worker_deps, WORKER_PKG_DIR)

    # Copy app and workers packages
    shutil.copytree(os.path.join(BASE_DIR, "app"), os.path.join(WORKER_PKG_DIR, "app"), dirs_exist_ok=True)
    shutil.copytree(os.path.join(BASE_DIR, "workers"), os.path.join(WORKER_PKG_DIR, "workers"), dirs_exist_ok=True)

    zip_directory(WORKER_PKG_DIR, WORKER_ZIP)


import time


def wait_for_function_ready(func_name: str):
    logger.info(f"Waiting for '{func_name}' to become active and ready...")
    for _ in range(60):
        try:
            res = lambda_client.get_function(FunctionName=func_name)
            state = res.get("Configuration", {}).get("State")
            update_status = res.get("Configuration", {}).get("LastUpdateStatus")
            if update_status != "InProgress" and state != "Pending":
                return
        except ClientError:
            pass
        time.sleep(2)


def deploy_or_update_lambda(
    func_name: str,
    role_arn: str,
    handler: str,
    zip_path: str,
    env_vars: dict,
    memory_mb: int = 512,
    timeout_sec: int = 15,
):
    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    try:
        lambda_client.get_function(FunctionName=func_name)
        logger.info(f"Function '{func_name}' already exists. Updating code and configuration...")
        wait_for_function_ready(func_name)
        lambda_client.update_function_code(
            FunctionName=func_name,
            ZipFile=zip_bytes,
        )
        wait_for_function_ready(func_name)
        lambda_client.update_function_configuration(
            FunctionName=func_name,
            Handler=handler,
            Role=role_arn,
            Runtime="python3.11",
            Timeout=timeout_sec,
            MemorySize=memory_mb,
            Environment={"Variables": env_vars},
        )
        wait_for_function_ready(func_name)
        logger.info(f"Updated '{func_name}' successfully.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info(f"Creating Lambda function '{func_name}'...")
            lambda_client.create_function(
                FunctionName=func_name,
                Runtime="python3.11",
                Role=role_arn,
                Handler=handler,
                Code={"ZipFile": zip_bytes},
                Description=f"ZeroDaily service component: {func_name}",
                Timeout=timeout_sec,
                MemorySize=memory_mb,
                Environment={"Variables": env_vars},
            )
            wait_for_function_ready(func_name)
            logger.info(f"Function '{func_name}' created successfully.")
        else:
            raise


def setup_function_url(func_name: str) -> str:
    """Configures public Lambda Function URL with CORS."""
    try:
        res = lambda_client.get_function_url_config(FunctionName=func_name)
        url = res["FunctionUrl"]
        logger.info(f"Function URL already exists: {url}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("Creating Lambda Function URL...")
            res = lambda_client.create_function_url_config(
                FunctionName=func_name,
                AuthType="NONE",
                Cors={
                    "AllowOrigins": ["*"],
                    "AllowMethods": ["*"],
                    "AllowHeaders": ["*"],
                },
            )
            url = res["FunctionUrl"]
            logger.info(f"Function URL created: {url}")
        else:
            raise

    # Allow public unauthenticated invocation on the function url
    try:
        lambda_client.add_permission(
            FunctionName=func_name,
            StatementId="FunctionURLAllowPublicAccess",
            Action="lambda:InvokeFunctionUrl",
            Principal="*",
            FunctionUrlAuthType="NONE",
        )
        logger.info("Added public invoke permission to Function URL")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            logger.info("Public invoke permission already exists.")
        else:
            logger.warning(f"Note on permission: {e}")

    return url


def setup_stream_trigger(func_name: str, stream_arn: str):
    """Hooks up DynamoDB Stream to the Notification Worker Lambda."""
    paginator = lambda_client.get_paginator("list_event_source_mappings")
    for page in paginator.paginate(FunctionName=func_name):
        for mapping in page["EventSourceMappings"]:
            if mapping.get("EventSourceArn") == stream_arn:
                logger.info(f"DynamoDB Stream mapping already active: {mapping['UUID']}")
                return

    logger.info("Attaching DynamoDB Stream trigger to worker Lambda...")
    res = lambda_client.create_event_source_mapping(
        EventSourceArn=stream_arn,
        FunctionName=func_name,
        Enabled=True,
        BatchSize=10,
        StartingPosition="LATEST",
    )
    logger.info(f"Stream trigger successfully attached! Mapping UUID: {res['UUID']}")


def main():
    logger.info("Starting ZeroDaily Automated Package & Deployment...")

    # Only package if zip archives do not exist
    if not (os.path.exists(API_ZIP) and os.path.exists(WORKER_ZIP)):
        clean_build()
        package_api()
        package_worker()
    else:
        logger.info("Existing deployment packages found in build/. Skipping wheel installation.")

    # Step 2: Deploy API Lambda (Note: AWS_REGION is reserved in Lambda, so omitted)
    api_env = {
        "DYNAMODB_TABLE_NAME": "zerodaily-articles",
        "CORS_ORIGINS": "*",
        "ENVIRONMENT": "production",
    }
    deploy_or_update_lambda(
        func_name="zerodaily-api",
        role_arn=API_ROLE_ARN,
        handler="app.main.handler",
        zip_path=API_ZIP,
        env_vars=api_env,
        memory_mb=512,
        timeout_sec=15,
    )
    function_url = setup_function_url("zerodaily-api")

    # Step 3: Deploy Worker Lambda
    worker_env = {
        "DYNAMODB_TABLE_NAME": "zerodaily-articles",
        "DYNAMODB_STREAM_ARN": STREAM_ARN,
        "FIREBASE_SECRET_NAME": "zerodaily/firebase-key",
        "FIREBASE_PROJECT_ID": "zerodaily-prod",
        "NOTIFICATION_COOLDOWN_MINUTES": "30",
        "ENABLE_ALL_BREAKING_TOPIC": "true",
    }
    deploy_or_update_lambda(
        func_name="zerodaily-notification-worker",
        role_arn=WORKER_ROLE_ARN,
        handler="workers.stream_handler.lambda_handler",
        zip_path=WORKER_ZIP,
        env_vars=worker_env,
        memory_mb=256,
        timeout_sec=30,
    )
    setup_stream_trigger("zerodaily-notification-worker", STREAM_ARN)

    print("\n" + "=" * 65)
    print("DEPLOYMENT COMPLETE! 🚀")
    print(f"API Lambda:               zerodaily-api")
    print(f"Worker Lambda:            zerodaily-notification-worker")
    print(f"Public Live URL:          {function_url}")
    print(f"Swagger Docs Live:        {function_url}docs")
    print(f"Health Check:             {function_url}health")
    print(f"Global Feed:              {function_url}api/v1/feed")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
