from typing import List, Optional
from pydantic import BaseModel, Field


# --- Article & Feed Schemas ---

class Article(BaseModel):
    id: str = Field(..., description="Canonical source URL")
    category: str = Field(..., description="Category key (e.g. cybersec, ai)")
    heading: str = Field(..., description="Satirical roasted headline")
    shortSummary: str = Field(..., description="Witty bullet or condensed summary")
    fullSummary: str = Field(..., description="Full multi-paragraph roasted story")
    published_at: str = Field(..., description="ISO-8601 UTC timestamp")
    link: str = Field(..., description="Link to original article source")
    image_url: str = Field(..., description="Cloudflare CDN WebP image URL")


class Pagination(BaseModel):
    has_more: bool = Field(..., description="True if more records exist after this page")
    next_cursor: Optional[str] = Field(None, description="ISO-8601 UTC timestamp of last item for next query")
    count: int = Field(..., description="Number of items returned in current page")


class FeedResponse(BaseModel):
    status: str = "success"
    data: List[Article]
    pagination: Pagination


class CategoryFeedResponse(BaseModel):
    status: str = "success"
    category: str
    data: List[Article]
    pagination: Pagination


class ArticleDetailResponse(BaseModel):
    status: str = "success"
    data: Article


class Category(BaseModel):
    key: str
    name: str
    description: str


class CategoryListResponse(BaseModel):
    status: str = "success"
    categories: List[Category]


class HealthResponse(BaseModel):
    status: str
    service: str
    region: str
    timestamp: str


# --- Notification Schemas ---

class BreakingArticleRecord(BaseModel):
    id: str
    category: str
    is_breaking: bool = False
    push_punchline: str
    heading: str
    image_url: str
    published_at: str


class NotificationHistoryItem(BaseModel):
    article_id: str
    category: str
    heading: str
    push_punchline: str
    image_url: str
    published_at: str


class NotificationHistoryResponse(BaseModel):
    status: str = "success"
    data: List[NotificationHistoryItem]
    count: int


class TopicSubscriptionRequest(BaseModel):
    token: str = Field(..., min_length=10, description="FCM device registration token")
    topics: List[str] = Field(..., min_length=1, description="List of FCM topics to subscribe or unsubscribe")


class TopicSubscriptionResponse(BaseModel):
    status: str = "success"
    message: str
    token: str
    topics: List[str]

