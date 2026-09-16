from typing import Optional
from fastapi import APIRouter, Path, Query, Response, HTTPException, status
from fastapi.responses import JSONResponse
from app.schemas import ArticleDetailResponse, Article
from app.db import get_db_service

router = APIRouter(tags=["Articles"])

CACHE_CONTROL_ARTICLE = "public, max-age=3600"


def format_article_response(item: Optional[dict]) -> JSONResponse:
    if not item:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "status": "error",
                "message": "Article not found"
            },
            headers={"Cache-Control": "no-cache"}
        )

    article = Article(
        id=item["id"],
        category=item["category"],
        heading=item.get("heading", item.get("title", "")),
        shortSummary=item.get("shortSummary", ""),
        fullSummary=item.get("fullSummary", ""),
        published_at=item["published_at"],
        link=item.get("link", item["id"]),
        image_url=item.get("image_url", ""),
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "data": article.model_dump()
        },
        headers={"Cache-Control": CACHE_CONTROL_ARTICLE}
    )


def validate_article_url(url: str) -> None:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Article ID must be a valid HTTP or HTTPS URL"
        )


@router.get("/api/v1/articles/{id:path}")
def get_article_by_path(
    id: str = Path(..., max_length=2048, description="Canonical URL ID of the article")
):
    """Fetches a single roasted article by path URL."""
    validate_article_url(id)
    db = get_db_service()
    item = db.get_article_by_id(id)
    return format_article_response(item)


@router.get("/api/v1/article")
def get_article_by_query(
    id: str = Query(..., max_length=2048, description="Canonical URL ID of the article")
):
    """Fetches a single roasted article by query parameter."""
    validate_article_url(id)
    db = get_db_service()
    item = db.get_article_by_id(id)
    return format_article_response(item)
