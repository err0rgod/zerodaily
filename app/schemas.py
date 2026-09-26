from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, EmailStr


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


# --- User & Authentication Schemas ---


class UserRegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=6, max_length=128, description="User password (min 6 characters)")
    display_name: Optional[str] = Field(None, max_length=60, description="Display name / alias")
    guest_user_id: Optional[str] = Field(None, description="Previous anonymous guest ID to migrate data from")


class UserLoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")
    guest_user_id: Optional[str] = Field(None, description="Previous anonymous guest ID to migrate data from upon login")


class GuestSessionRequest(BaseModel):
    device_id: Optional[str] = Field(None, description="Optional unique device identifier")
    initial_preferences: Optional[Dict[str, bool]] = Field(None, description="Initial category toggle states")


class FirebaseLoginRequest(BaseModel):
    id_token: str = Field(..., description="Firebase Auth ID Token")
    guest_user_id: Optional[str] = Field(None, description="Previous anonymous guest ID to migrate data from")


class UserProfile(BaseModel):
    user_id: str = Field(..., description="Unique user identifier")
    email: Optional[str] = Field(None, description="User email address")
    display_name: Optional[str] = Field(None, description="Display name")
    avatar_url: Optional[str] = Field(None, description="User avatar image URL")
    is_anonymous: bool = Field(False, description="True if guest account")
    created_at: str = Field(..., description="Account creation timestamp ISO-8601")
    last_active_at: str = Field(..., description="Last activity timestamp ISO-8601")
    topic_preferences: Dict[str, bool] = Field(default_factory=dict, description="Active topic preferences")
    algo_weights: Dict[str, float] = Field(default_factory=dict, description="Category affinity weights for feed algorithm")
    bookmarked_articles: List[str] = Field(default_factory=list, description="List of bookmarked article IDs")
    reading_count: int = Field(0, description="Total number of articles read")


class AuthResponse(BaseModel):
    status: str = "success"
    access_token: str = Field(..., description="JWT Bearer token")
    token_type: str = "bearer"
    user: UserProfile


class PreferencesUpdateRequest(BaseModel):
    topic_preferences: Dict[str, bool] = Field(..., description="Map of category keys to boolean subscriptions")


class UserTrackingEventRequest(BaseModel):
    article_id: str = Field(..., description="Canonical article URL ID")
    category: str = Field(..., description="Category of the article")
    action: Literal["read", "dwell", "skip", "bookmark", "share", "full_roast"] = Field(
        ..., description="Action performed: read, dwell, skip, bookmark, share, full_roast"
    )
    duration_seconds: Optional[float] = Field(0.0, description="Dwell/reading duration in seconds")


class TrackingResponse(BaseModel):
    status: str = "success"
    user_id: str
    action: str
    algo_weights: Dict[str, float]


class SyncBookmarksRequest(BaseModel):
    bookmarks: List[str] = Field(..., description="List of article IDs to sync")
    mode: Optional[Literal["merge", "replace"]] = Field(
        "merge", description="Sync mode: 'merge' (union) or 'replace' (set exact list)"
    )


class SyncBookmarksResponse(BaseModel):
    status: str = "success"
    bookmarks: List[str]

