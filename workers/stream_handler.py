import logging
from typing import Dict, Any, List, Optional
from app.services.cooldown import NotificationCooldownManager
from app.services.fcm_client import FCMClient
from app.services.cdn_client import CDNClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zerodaily.stream_handler")
logger.setLevel(logging.INFO)
logging.getLogger().setLevel(logging.INFO)


def parse_dynamodb_attribute(attr: Dict[str, Any]) -> Any:
    """Parses standard DynamoDB low-level attribute format to Python native type."""
    if not isinstance(attr, dict):
        return attr
    if "S" in attr:
        return attr["S"]
    if "N" in attr:
        val = attr["N"]
        return float(val) if "." in val else int(val)
    if "BOOL" in attr:
        return bool(attr["BOOL"])
    if "NULL" in attr:
        return None
    if "M" in attr:
        return {k: parse_dynamodb_attribute(v) for k, v in attr["M"].items()}
    if "L" in attr:
        return [parse_dynamodb_attribute(item) for item in attr["L"]]
    return str(attr)


def extract_breaking_article(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validates and extracts breaking article data from a DynamoDB stream record.
    Returns None if the record does not qualify.
    """
    event_name = record.get("eventName")
    if event_name != "INSERT":
        return None

    dynamodb_data = record.get("dynamodb", {})
    new_image = dynamodb_data.get("NewImage", {})
    if not new_image:
        return None

    # Check is_breaking flag
    is_breaking_raw = new_image.get("is_breaking")
    if not is_breaking_raw:
        return None

    is_breaking = parse_dynamodb_attribute(is_breaking_raw)
    if not is_breaking:
        return None

    # Extract required fields
    article_id = parse_dynamodb_attribute(new_image.get("id", {}))
    if not article_id or article_id.startswith("NOTIF_"):
        return None

    category = parse_dynamodb_attribute(new_image.get("category", {})) or "general"
    heading = parse_dynamodb_attribute(new_image.get("heading", {})) or ""
    push_punchline = parse_dynamodb_attribute(new_image.get("push_punchline", {}))
    
    # Fallback to heading (max 50 chars) if punchline was not populated
    if not push_punchline:
        push_punchline = heading[:50].strip() if heading else "Breaking Tech News Alert"
    else:
        push_punchline = str(push_punchline)[:50].strip()

    image_url = parse_dynamodb_attribute(new_image.get("image_url", {})) or ""
    published_at = parse_dynamodb_attribute(new_image.get("published_at", {})) or ""

    return {
        "article_id": article_id,
        "category": str(category).lower(),
        "push_punchline": push_punchline,
        "heading": heading,
        "image_url": image_url,
        "published_at": published_at,
    }


def extract_inserted_article_metadata(record: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extracts category and image_url from any INSERT record for CDN cache refresh."""
    if record.get("eventName") != "INSERT":
        return None
    new_image = record.get("dynamodb", {}).get("NewImage", {})
    if not new_image:
        return None
    article_id = parse_dynamodb_attribute(new_image.get("id", {}))
    if not article_id or str(article_id).startswith("NOTIF_"):
        return None
    category = parse_dynamodb_attribute(new_image.get("category", {})) or ""
    image_url = parse_dynamodb_attribute(new_image.get("image_url", {})) or ""
    return {"category": str(category).lower(), "image_url": str(image_url)}


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    AWS Lambda entrypoint triggered by DynamoDB Streams on zerodaily-articles.
    1. Processes INSERT events for breaking news and dispatches FCM topic notifications.
    2. Automatically invalidates and pre-warms the Cloudflare CDN edge cache for new stories.
    """
    records: List[Dict[str, Any]] = event.get("Records", [])
    logger.info(f"Received DynamoDB stream batch with {len(records)} records.")

    cooldown_manager = NotificationCooldownManager()
    fcm_client = FCMClient()
    cdn_client = CDNClient()

    processed_count = 0
    dispatched_count = 0
    suppressed_count = 0

    affected_categories = set()
    new_images: List[str] = []

    for record in records:
        # Collect metadata for CDN cache invalidation
        meta = extract_inserted_article_metadata(record)
        if meta:
            if meta["category"]:
                affected_categories.add(meta["category"])
            if meta["image_url"]:
                new_images.append(meta["image_url"])

        article = extract_breaking_article(record)
        if not article:
            continue

        processed_count += 1
        article_id = article["article_id"]
        category = article["category"]

        logger.info(f"Evaluating breaking article: {article_id} [Category: {category}]")

        # 1. Rate-limiting & Cooldown check
        has_permission = cooldown_manager.acquire_push_permission(
            category=category,
            article_id=article_id
        )

        if not has_permission:
            logger.info(f"Notification suppressed due to 30-min cooldown window for '{category}'.")
            suppressed_count += 1
            continue

        # 2. Dispatch push notification to FCM category topic
        try:
            results = fcm_client.dispatch_breaking_news(
                article_id=article_id,
                category=category,
                push_punchline=article["push_punchline"],
                image_url=article["image_url"],
            )
            dispatched_count += 1
            logger.info(f"Push dispatch completed for {article_id}: {results}")
        except Exception as e:
            logger.error(f"Failed to dispatch FCM push for {article_id}: {e}")

    # 3. Purge and Pre-Warm Cloudflare CDN edge cache for newly inserted articles
    cdn_summary = {}
    if affected_categories or new_images:
        try:
            cdn_summary = cdn_client.purge_and_warm(
                categories=list(affected_categories),
                image_urls=new_images,
            )
        except Exception as e:
            logger.error(f"Error during CDN purge & warm cycle: {e}")

    summary = {
        "status": "success",
        "total_records": len(records),
        "breaking_candidates": processed_count,
        "dispatched": dispatched_count,
        "cooldown_suppressed": suppressed_count,
        "cdn_refresh": cdn_summary,
    }
    logger.info(f"Batch processing complete: {summary}")
    return summary
