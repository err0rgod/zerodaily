from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Optional, List, Dict, Any, Tuple
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger("zerodaily.db")


def float_to_decimal(obj: Any) -> Any:
    """Recursively converts float values to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    elif isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [float_to_decimal(v) for v in obj]
    return obj


def decimal_to_float(obj: Any) -> Any:
    """Recursively converts Decimal values to float/int for API serialization."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj


class DynamoDBService:
    def __init__(
        self,
        table_name: Optional[str] = None,
        users_table_name: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        settings = get_settings()
        self.table_name = table_name or settings.DYNAMODB_TABLE_NAME
        self.users_table_name = users_table_name or settings.DYNAMODB_USERS_TABLE_NAME
        self.region_name = region_name or settings.AWS_REGION
        self._dynamodb = boto3.resource("dynamodb", region_name=self.region_name)
        self.table = self._dynamodb.Table(self.table_name)
        self.users_table = self._dynamodb.Table(self.users_table_name)

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

    # =========================================================================
    # User Account, Authentication & Tracking Store Operations
    # =========================================================================

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a user profile by primary partition key user_id."""
        try:
            res = self.users_table.get_item(Key={"user_id": user_id})
            item = res.get("Item")
            return decimal_to_float(item) if item else None
        except ClientError as e:
            logger.error(f"Error fetching user by id '{user_id}': {e}")
            raise

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Queries the EmailIndex GSI for user with the specified email."""
        try:
            clean_email = email.strip().lower()
            res = self.users_table.query(
                IndexName="EmailIndex",
                KeyConditionExpression=Key("email").eq(clean_email),
                Limit=1,
            )
            items = res.get("Items", [])
            return decimal_to_float(items[0]) if items else None
        except ClientError as e:
            logger.error(f"Error querying user by email '{email}': {e}")
            raise

    def save_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Saves or updates a complete user record in DynamoDB."""
        try:
            dynamo_item = float_to_decimal(user_data)
            self.users_table.put_item(Item=dynamo_item)
            return user_data
        except ClientError as e:
            logger.error(f"Error saving user '{user_data.get('user_id')}': {e}")
            raise

    def update_user_preferences(
        self, user_id: str, topic_preferences: Dict[str, bool]
    ) -> Optional[Dict[str, Any]]:
        """Updates user category notification/feed topic preferences."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = self.users_table.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET topic_preferences = :tp, last_active_at = :la",
                ExpressionAttributeValues={
                    ":tp": topic_preferences,
                    ":la": now_iso,
                },
                ReturnValues="ALL_NEW",
            )
            return decimal_to_float(res.get("Attributes"))
        except ClientError as e:
            logger.error(f"Error updating preferences for '{user_id}': {e}")
            raise

    def record_user_interaction(
        self,
        user_id: str,
        article_id: str,
        category: str,
        action: str,
        duration_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Records user interaction, adjusts algorithmic category engagement weights,
        and records reading history for feed personalization.
        """
        from app.config import normalize_category_key

        user = self.get_user_by_id(user_id)
        if not user:
            logger.warning(f"User '{user_id}' not found for interaction tracking.")
            return {"algo_weights": {}, "reading_count": 0}

        clean_cat = normalize_category_key(category) or category.strip().lower()
        algo_weights = user.get("algo_weights") or {}
        current_weight = float(algo_weights.get(clean_cat, 1.0))

        safe_duration = min(max(0.0, float(duration_seconds or 0.0)), 300.0)

        # Dynamic weight tuning algorithm
        weight_delta = 0.0
        if action in ("read", "dwell", "full_roast"):
            # Dwell duration bonus: longer reads signal stronger category interest
            duration_bonus = min(safe_duration, 60.0) / 120.0  # max +0.5
            weight_delta = 0.15 + duration_bonus
        elif action == "bookmark":
            weight_delta = 0.30
        elif action == "share":
            weight_delta = 0.25
        elif action == "skip":
            weight_delta = -0.05

        new_weight = max(0.1, min(3.0, round(current_weight + weight_delta, 3)))
        algo_weights[clean_cat] = new_weight

        now_iso = datetime.now(timezone.utc).isoformat()
        reading_history = user.get("reading_history") or []
        reading_history.append({
            "article_id": article_id,
            "category": clean_cat,
            "action": action,
            "duration": safe_duration,
            "timestamp": now_iso,
        })
        # Bounded reading history (keep last 50 events)
        if len(reading_history) > 50:
            reading_history = reading_history[-50:]

        reading_count = int(user.get("reading_count", 0)) + (
            1 if action in ("read", "dwell", "full_roast") else 0
        )

        user["algo_weights"] = algo_weights
        user["reading_history"] = reading_history
        user["reading_count"] = reading_count
        user["last_active_at"] = now_iso

        self.save_user(user)
        return {"algo_weights": algo_weights, "reading_count": reading_count}

    def sync_user_bookmarks(
        self, user_id: str, incoming_bookmarks: List[str], mode: str = "merge"
    ) -> List[str]:
        """
        Syncs local device bookmarks with cloud user profile.
        mode="merge" performs union with cloud profile; mode="replace" overwrites.
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return incoming_bookmarks

        if mode == "replace":
            merged_list = list(dict.fromkeys(incoming_bookmarks))
        else:
            existing_bookmarks = user.get("bookmarked_articles") or []
            merged_list = list(dict.fromkeys(incoming_bookmarks + existing_bookmarks))

        now_iso = datetime.now(timezone.utc).isoformat()
        self.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET bookmarked_articles = :b, last_active_at = :la",
            ExpressionAttributeValues={
                ":b": merged_list,
                ":la": now_iso,
            },
        )
        return merged_list

    def migrate_guest_data(self, guest_user_id: str, permanent_user_id: str) -> bool:
        """
        Migrates reading history, topic preferences, algorithmic weights, and
        bookmarks from a temporary guest session into a permanent user account.
        Enforces security checks so only anonymous guest accounts can be migrated and deleted.
        """
        if not guest_user_id or guest_user_id == permanent_user_id:
            return False

        if not guest_user_id.startswith("guest_"):
            logger.warning(f"Security: Non-guest user ID '{guest_user_id}' cannot be migrated as guest.")
            return False

        guest_user = self.get_user_by_id(guest_user_id)
        if not guest_user:
            return False

        # Security check: guest_user must be an anonymous account without password hash
        if not guest_user.get("is_anonymous", False) or guest_user.get("password_hash"):
            logger.warning(
                f"Security violation: Attempted to migrate non-guest or password-protected user '{guest_user_id}'."
            )
            return False

        perm_user = self.get_user_by_id(permanent_user_id)
        if not perm_user:
            return False

        # Merge bookmarks (order-preserving union)
        guest_bookmarks = guest_user.get("bookmarked_articles") or []
        perm_bookmarks = perm_user.get("bookmarked_articles") or []
        merged_bookmarks = list(dict.fromkeys(guest_bookmarks + perm_bookmarks))

        # Merge algo weights (take max engagement weight per category)
        guest_weights = guest_user.get("algo_weights") or {}
        perm_weights = perm_user.get("algo_weights") or {}
        merged_weights = dict(perm_weights)
        for cat, w in guest_weights.items():
            merged_weights[cat] = max(float(w), float(merged_weights.get(cat, 1.0)))

        # Merge preferences
        guest_prefs = guest_user.get("topic_preferences") or {}
        perm_prefs = perm_user.get("topic_preferences") or {}
        merged_prefs = {**perm_prefs, **guest_prefs}

        # Merge reading history
        guest_history = guest_user.get("reading_history") or []
        perm_history = perm_user.get("reading_history") or []
        merged_history = (guest_history + perm_history)[-50:]
        merged_count = int(perm_user.get("reading_count", 0)) + int(guest_user.get("reading_count", 0))

        perm_user["bookmarked_articles"] = merged_bookmarks
        perm_user["algo_weights"] = merged_weights
        perm_user["topic_preferences"] = merged_prefs
        perm_user["reading_history"] = merged_history
        perm_user["reading_count"] = merged_count
        perm_user["last_active_at"] = datetime.now(timezone.utc).isoformat()

        self.save_user(perm_user)

        # Clean up temporary guest user
        try:
            self.users_table.delete_item(Key={"user_id": guest_user_id})
        except Exception as e:
            logger.warning(f"Could not delete migrated guest user '{guest_user_id}': {e}")

        return True

    def delete_user(self, user_id: str) -> bool:
        """Deletes a user record by user_id."""
        try:
            self.users_table.delete_item(Key={"user_id": user_id})
            return True
        except ClientError as e:
            logger.error(f"Error deleting user '{user_id}': {e}")
            raise


# Global singleton instance
_db_service: Optional[DynamoDBService] = None


def get_db_service() -> DynamoDBService:
    global _db_service
    if _db_service is None:
        _db_service = DynamoDBService()
    return _db_service
