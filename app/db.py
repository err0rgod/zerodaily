import logging
from typing import Optional, List, Dict, Any, Tuple
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger("zerodaily.db")


class DynamoDBService:
    def __init__(self, table_name: Optional[str] = None, region_name: Optional[str] = None):
        settings = get_settings()
        self.table_name = table_name or settings.DYNAMODB_TABLE_NAME
        self.region_name = region_name or settings.AWS_REGION
        self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)
        self.table = self._dynamodb.Table(self.table_name)

    def query_global_feed(
        self, limit: int = 20, cursor: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        """
        Queries GlobalFeedIndex for chronological feed across all categories.
        Uses published_at cursor for pagination.
        """
        try:
            if cursor:
                key_condition = Key("feed_bucket").eq("ALL") & Key("published_at").lt(cursor)
            else:
                key_condition = Key("feed_bucket").eq("ALL")

            response = self.table.query(
                IndexName="GlobalFeedIndex",
                KeyConditionExpression=key_condition,
                ScanIndexForward=False,  # Newest first
                Limit=limit,
            )

            items = response.get("Items", [])
            # Filter out any internal lock or metric keys if present
            items = [item for item in items if not str(item.get("id", "")).startswith("NOTIF_")]

            next_cursor = items[-1]["published_at"] if len(items) == limit else None
            has_more = next_cursor is not None

            return items, next_cursor, has_more
        except ClientError as e:
            logger.error(f"Error querying GlobalFeedIndex: {e}")
            raise

    def query_category_feed(
        self, category: str, limit: int = 20, cursor: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        """
        Queries CategoryIndex for chronological feed in a specific category.
        """
        try:
            clean_category = category.strip().lower()
            if cursor:
                key_condition = Key("category").eq(clean_category) & Key("published_at").lt(cursor)
            else:
                key_condition = Key("category").eq(clean_category)

            response = self.table.query(
                IndexName="CategoryIndex",
                KeyConditionExpression=key_condition,
                ScanIndexForward=False,  # Newest first
                Limit=limit,
            )

            items = response.get("Items", [])
            items = [item for item in items if not str(item.get("id", "")).startswith("NOTIF_")]

            next_cursor = items[-1]["published_at"] if len(items) == limit else None
            has_more = next_cursor is not None

            return items, next_cursor, has_more
        except ClientError as e:
            logger.error(f"Error querying CategoryIndex for category '{category}': {e}")
            raise

    def get_article_by_id(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single article item by its canonical URL ID.
        """
        try:
            response = self.table.get_item(Key={"id": article_id})
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching article by id '{article_id}': {e}")
            raise

    def get_recent_breaking_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Queries recent articles flagged with is_breaking=True for notification history.
        """
        try:
            # Query GlobalFeedIndex ordered by published_at with filter on is_breaking
            response = self.table.query(
                IndexName="GlobalFeedIndex",
                KeyConditionExpression=Key("feed_bucket").eq("ALL"),
                FilterExpression=Attr("is_breaking").eq(True),
                ScanIndexForward=False,
                Limit=limit * 2,  # Fetch extra to account for filter
            )
            items = response.get("Items", [])
            items = [item for item in items if not str(item.get("id", "")).startswith("NOTIF_")]
            return items[:limit]
        except ClientError as e:
            logger.error(f"Error querying breaking alerts: {e}")
            return []


# Global singleton instance
_db_service: Optional[DynamoDBService] = None


def get_db_service() -> DynamoDBService:
    global _db_service
    if _db_service is None:
        _db_service = DynamoDBService()
    return _db_service
