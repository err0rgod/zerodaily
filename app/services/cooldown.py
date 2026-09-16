import time
import logging
from datetime import datetime, timezone
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger("zerodaily.cooldown")


class NotificationCooldownManager:
    """
    Manages rate-limiting and anti-spam cooldowns for breaking news notifications
    using DynamoDB conditional writes and TTL.
    """

    def __init__(self, table_name: Optional[str] = None, region_name: Optional[str] = None):
        settings = get_settings()
        self.table_name = table_name or settings.DYNAMODB_TABLE_NAME
        self.region_name = region_name or settings.AWS_REGION
        self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)
        self.table = self._dynamodb.Table(self.table_name)

    def acquire_push_permission(
        self,
        category: str,
        article_id: str,
        cooldown_minutes: Optional[int] = None
    ) -> bool:
        """
        Atomically checks if a breaking notification can be sent for this category.
        Returns True if allowed (and updates the cooldown timestamp).
        Returns False if a notification was already sent within the cooldown window.
        """
        settings = get_settings()
        cooldown_mins = cooldown_minutes if cooldown_minutes is not None else settings.NOTIFICATION_COOLDOWN_MINUTES
        cooldown_seconds = cooldown_mins * 60

        now_epoch = int(time.time())
        expiry_epoch = now_epoch + cooldown_seconds
        now_iso = datetime.now(timezone.utc).isoformat()

        lock_key = f"NOTIF_COOLDOWN#{category.lower()}"

        try:
            # Atomic conditional put: succeed ONLY if key doesn't exist OR previous cooldown has expired
            self.table.put_item(
                Item={
                    "id": lock_key,
                    "category": category.lower(),
                    "last_sent_at": now_iso,
                    "last_article_id": article_id,
                    "ttl": expiry_epoch,
                },
                ConditionExpression="attribute_not_exists(id) OR #ttl_field <= :now_epoch",
                ExpressionAttributeNames={
                    "#ttl_field": "ttl"
                },
                ExpressionAttributeValues={
                    ":now_epoch": now_epoch
                }
            )
            logger.info(f"Cooldown lock acquired for category '{category}'. Valid until epoch {expiry_epoch}.")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(f"Cooldown active for category '{category}'. Notification suppressed.")
                return False
            logger.error(f"Error accessing DynamoDB cooldown lock: {e}")
            # If DynamoDB fails for unexpected reasons, reject to prevent potential notification storms
            return False
