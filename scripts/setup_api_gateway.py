import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("apigw_setup")

REGION = "us-east-1"
CERT_ARN = "arn:aws:acm:us-east-1:339087217625:certificate/d4796ff5-133e-4d8c-bfc9-a1c6190aa869"
LAMBDA_ARN = "arn:aws:lambda:us-east-1:339087217625:function:zerodaily-api"
DOMAIN_NAME = "api.zerodaily.in"

apigw = boto3.client("apigatewayv2", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


def setup_api_gateway():
    logger.info("Setting up API Gateway HTTP API for zerodaily-api...")

    # 1. Create or Find HTTP API
    api_id = None
    apis = apigw.get_apis().get("Items", [])
    for a in apis:
        if a.get("Name") == "zerodaily-api-gw":
            api_id = a["ApiId"]
            logger.info(f"HTTP API 'zerodaily-api-gw' already exists: {api_id}")
            break

    if not api_id:
        logger.info("Creating HTTP API 'zerodaily-api-gw'...")
        res = apigw.create_api(
            Name="zerodaily-api-gw",
            ProtocolType="HTTP",
            Target=LAMBDA_ARN,
            Description="API Gateway HTTP API for ZeroDaily Serving Layer",
        )
        api_id = res["ApiId"]
        logger.info(f"Created HTTP API with ID: {api_id}")

    # 2. Ensure Lambda permission for API Gateway
    try:
        lambda_client.add_permission(
            FunctionName="zerodaily-api",
            StatementId="ApiGatewayInvokePermission",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:339087217625:{api_id}/*",
        )
        logger.info("Granted API Gateway permission to invoke Lambda.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            logger.info("Lambda invoke permission for API Gateway already exists.")
        else:
            logger.warning(f"Note on permission: {e}")

    # 3. Create Custom Domain Name in API Gateway
    target_cname = None
    try:
        res = apigw.get_domain_name(DomainName=DOMAIN_NAME)
        configs = res.get("DomainNameConfigurations", [])
        if configs:
            target_cname = configs[0].get("ApiGatewayDomainName")
        logger.info(f"Custom Domain '{DOMAIN_NAME}' already exists: {target_cname}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NotFoundException":
            logger.info(f"Creating Custom Domain '{DOMAIN_NAME}' in API Gateway...")
            res = apigw.create_domain_name(
                DomainName=DOMAIN_NAME,
                DomainNameConfigurations=[
                    {
                        "CertificateArn": CERT_ARN,
                        "EndpointType": "REGIONAL",
                        "SecurityPolicy": "TLS_1_2",
                    }
                ],
            )
            configs = res.get("DomainNameConfigurations", [])
            if configs:
                target_cname = configs[0].get("ApiGatewayDomainName")
            logger.info(f"Custom Domain created. Target: {target_cname}")
        else:
            raise

    # 4. Create API Mapping
    try:
        mappings = apigw.get_api_mappings(DomainName=DOMAIN_NAME).get("Items", [])
        mapped = any(m.get("ApiId") == api_id for m in mappings)
        if not mapped:
            logger.info(f"Mapping '{DOMAIN_NAME}' to API '{api_id}' ($default stage)...")
            apigw.create_api_mapping(
                DomainName=DOMAIN_NAME,
                ApiId=api_id,
                Stage="$default",
            )
            logger.info("API Mapping created successfully.")
        else:
            logger.info("API Mapping already active.")
    except Exception as e:
        logger.warning(f"Note on API mapping: {e}")

    print("\n" + "=" * 65)
    print("API GATEWAY CUSTOM DOMAIN READY! [SUCCESS]")
    print(f"Custom Domain:         {DOMAIN_NAME}")
    print(f"API Gateway ID:        {api_id}")
    print(f"Cloudflare CNAME Target: {target_cname}")
    print("=" * 65 + "\n")
    return target_cname


if __name__ == "__main__":
    setup_api_gateway()
