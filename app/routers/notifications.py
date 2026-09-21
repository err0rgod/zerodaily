from fastapi import APIRouter, Query, Response
from app.schemas import (
    NotificationHistoryResponse,
    NotificationHistoryItem,
    TopicSubscriptionRequest,
    TopicSubscriptionResponse,
)
from app.db import get_db_service
from app.services.fcm_client import FCMClient

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("/history", response_model=NotificationHistoryResponse)
def get_notification_history(
    response: Response,
    limit: int = Query(20, ge=1, le=50, description="Max alerts to retrieve")
) -> NotificationHistoryResponse:
    """
    Returns recent breaking news alerts dispatched to mobile devices.
    Used by the mobile client to populate the 'Recent Alerts' screen.
    """
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120"
    db = get_db_service()
    raw_alerts = db.get_recent_breaking_alerts(limit=limit)

    items = [
        NotificationHistoryItem(
            article_id=item["id"],
            category=item.get("category", "general"),
            heading=item.get("heading", item.get("title", "")),
            push_punchline=item.get("push_punchline", item.get("heading", "")[:50]),
            image_url=item.get("image_url", ""),
            published_at=item.get("published_at", ""),
        )
        for item in raw_alerts
    ]

    return NotificationHistoryResponse(
        status="success",
        data=items,
        count=len(items)
    )


@router.post("/subscribe", response_model=TopicSubscriptionResponse)
def subscribe_device_to_topics(body: TopicSubscriptionRequest) -> TopicSubscriptionResponse:
    """
    Subscribes an FCM device registration token to one or more topics.
    Used by mobile clients (e.g. Expo) to synchronize category and breaking news subscriptions.
    """
    fcm_client = FCMClient()
    successful = fcm_client.subscribe_token_to_topics(body.token, body.topics)
    return TopicSubscriptionResponse(
        status="success",
        message=f"Subscribed token to {len(successful)} topics",
        token=body.token,
        topics=successful,
    )


@router.post("/unsubscribe", response_model=TopicSubscriptionResponse)
def unsubscribe_device_from_topics(body: TopicSubscriptionRequest) -> TopicSubscriptionResponse:
    """
    Unsubscribes an FCM device registration token from one or more topics.
    Used by mobile clients when user toggles off a category notification preference.
    """
    fcm_client = FCMClient()
    successful = fcm_client.unsubscribe_token_from_topics(body.token, body.topics)
    return TopicSubscriptionResponse(
        status="success",
        message=f"Unsubscribed token from {len(successful)} topics",
        token=body.token,
        topics=successful,
    )

