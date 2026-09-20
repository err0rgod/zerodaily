from typing import Optional
from fastapi import APIRouter, Query, Path, Response, HTTPException, status
from app.schemas import FeedResponse, CategoryFeedResponse, Article, Pagination
from app.db import get_db_service

router = APIRouter(prefix="/api/v1/feed", tags=["Feed"])

CACHE_CONTROL_FEED = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"

CATEGORY_ALIASES = {
    "cybersecurity": "cybersec",
    "cybersec": "cybersec",
    "ai": "ai",
    "artificial_intelligence": "ai",
    "programming": "programming",
    "dev": "programming",
    "software": "programming",
    "robotics": "robotics",
    "defense_aerospace": "defense_aerospace",
    "defense": "defense_aerospace",
    "aerospace": "defense_aerospace",
    "hardware": "hardware",
    "finance": "finance",
    "markets": "finance",
    "commodities": "finance",
    "pharma": "finance",
    "energy": "finance",
}


def normalize_category(category: str) -> str:
    cleaned = category.strip().lower()
    canonical = CATEGORY_ALIASES.get(cleaned)
    if not canonical:
        valid_options = ", ".join(sorted(set(CATEGORY_ALIASES.values())))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category '{category}' not recognized. Valid options: {valid_options}"
        )
    return canonical


ISO_8601_REGEX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"


@router.get("", response_model=FeedResponse)
def get_global_feed(
    response: Response,
    limit: int = Query(20, ge=1, le=50, description="Number of items to return"),
    cursor: Optional[str] = Query(
        None,
        max_length=40,
        pattern=ISO_8601_REGEX,
        description="ISO-8601 UTC timestamp of last item for pagination"
    ),
) -> FeedResponse:
    """
    Returns the unified chronological feed across all tech categories.
    Sorted newest first.
    """
    response.headers["Cache-Control"] = CACHE_CONTROL_FEED
    db = get_db_service()
    raw_items, next_cursor, has_more = db.query_global_feed(limit=limit, cursor=cursor)

    articles = [
        Article(
            id=item["id"],
            category=item["category"],
            heading=item.get("heading", item.get("title", "")),
            shortSummary=item.get("shortSummary", ""),
            fullSummary=item.get("fullSummary", ""),
            published_at=item["published_at"],
            link=item.get("link", item["id"]),
            image_url=item.get("image_url", ""),
        )
        for item in raw_items
    ]

    return FeedResponse(
        status="success",
        data=articles,
        pagination=Pagination(
            has_more=has_more,
            next_cursor=next_cursor,
            count=len(articles)
        )
    )


@router.get("/{category}", response_model=CategoryFeedResponse)
def get_category_feed(
    response: Response,
    category: str = Path(..., max_length=30, pattern=r"^[a-zA-Z0-9_]+$", description="Category key (e.g. cybersec, ai)"),
    limit: int = Query(20, ge=1, le=50, description="Number of items to return"),
    cursor: Optional[str] = Query(
        None,
        max_length=40,
        pattern=ISO_8601_REGEX,
        description="ISO-8601 UTC timestamp of last item for pagination"
    ),
) -> CategoryFeedResponse:
    """
    Returns articles strictly within a single category, sorted newest first.
    """
    canonical_category = normalize_category(category)
    response.headers["Cache-Control"] = CACHE_CONTROL_FEED

    db = get_db_service()
    raw_items, next_cursor, has_more = db.query_category_feed(
        category=canonical_category, limit=limit, cursor=cursor
    )

    articles = [
        Article(
            id=item["id"],
            category=item["category"],
            heading=item.get("heading", item.get("title", "")),
            shortSummary=item.get("shortSummary", ""),
            fullSummary=item.get("fullSummary", ""),
            published_at=item["published_at"],
            link=item.get("link", item["id"]),
            image_url=item.get("image_url", ""),
        )
        for item in raw_items
    ]

    return CategoryFeedResponse(
        status="success",
        category=canonical_category,
        data=articles,
        pagination=Pagination(
            has_more=has_more,
            next_cursor=next_cursor,
            count=len(articles)
        )
    )
