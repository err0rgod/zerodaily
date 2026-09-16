import logging
from typing import Dict, Any, List, Optional
from app.services.cooldown import NotificationCooldownManager
from app.services.fcm_client import FCMClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zerodaily.stream_handler")


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


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    AWS Lambda entrypoint triggered by DynamoDB Streams on zerodaily-articles.
    Processes INSERT events for breaking news and dispatches FCM topic notifications.
    """
    records: List[Dict[str, Any]] = event.get("Records", [])
    logger.info(f"Received DynamoDB stream batch with {len(records)} records.")

    cooldown_manager = NotificationCooldownManager()
    fcm_client = FCMClient()

    processed_count = 0
    dispatched_count = 0
    suppressed_count = 0

    for record in records:
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

        # 2. Dispatch push notification to FCM topics
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

    summary = {
        "status": "success",
        "total_records": len(records),
        "breaking_candidates": processed_count,
        "dispatched": dispatched_count,
        "cooldown_suppressed": suppressed_count,
    }
    logger.info(f"Batch processing complete: {summary}")
    return summary
