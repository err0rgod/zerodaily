from fastapi import APIRouter, Query, Response
from app.schemas import NotificationHistoryResponse, NotificationHistoryItem
from app.db import get_db_service

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
