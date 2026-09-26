from datetime import datetime, timezone, timedelta
import logging
from typing import Optional, Dict, Any, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings, normalize_category_key, CANONICAL_CATEGORIES
from app.db import DynamoDBService, get_db_service
from app.services.auth_service import AuthService, get_auth_service
from app.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    GuestSessionRequest,
    FirebaseLoginRequest,
    UserProfile,
    AuthResponse,
    AccountDeletionResponse,
    PreferencesUpdateRequest,
    UserTrackingEventRequest,
    TrackingResponse,
    SyncBookmarksRequest,
    SyncBookmarksResponse,
)

logger = logging.getLogger("zerodaily.auth_router")

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & User Tracking"])
security = HTTPBearer(auto_error=False)

ALL_CATEGORIES = [
    "cybersec",
    "ai",
    "programming",
    "robotics",
    "defense_aerospace",
    "hardware",
    "finance",
]


def build_default_preferences() -> Dict[str, bool]:
    return {cat: True for cat in ALL_CATEGORIES}


def build_default_algo_weights() -> Dict[str, float]:
    return {cat: 1.0 for cat in ALL_CATEGORIES}


def to_user_profile(user_dict: Dict[str, Any]) -> UserProfile:
    """Converts a raw DynamoDB user record to UserProfile schema."""
    return UserProfile(
        user_id=user_dict["user_id"],
        email=user_dict.get("email"),
        display_name=user_dict.get("display_name"),
        avatar_url=user_dict.get("avatar_url"),
        is_anonymous=user_dict.get("is_anonymous", False),
        created_at=user_dict.get("created_at", datetime.now(timezone.utc).isoformat()),
        last_active_at=user_dict.get("last_active_at", datetime.now(timezone.utc).isoformat()),
        topic_preferences=user_dict.get("topic_preferences") or build_default_preferences(),
        algo_weights=user_dict.get("algo_weights") or build_default_algo_weights(),
        bookmarked_articles=user_dict.get("bookmarked_articles") or [],
        reading_count=int(user_dict.get("reading_count", 0)),
        is_pending_deletion=bool(user_dict.get("is_pending_deletion", False)),
        deletion_scheduled_at=user_dict.get("deletion_scheduled_at"),
        account_restored=bool(user_dict.get("account_restored", False)),
    )


def check_and_handle_account_deletion_on_login(user: Dict[str, Any], db: DynamoDBService) -> Optional[str]:
    """
    Checks if an account was marked for deletion:
    - If the 24-hour grace period has passed: permanently deletes the account from DynamoDB
      and raises HTTP 401.
    - If within the 24-hour grace period: cancels deletion, reactivates the account, and returns
      a welcome back notification message.
    - If not marked for deletion: returns None.
    """
    if not user.get("is_pending_deletion"):
        return None

    deletion_scheduled_at = user.get("deletion_scheduled_at")
    if deletion_scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(deletion_scheduled_at.replace("Z", "+00:00"))
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now >= sched_dt:
                db.delete_user(user["user_id"])
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account has been permanently deleted.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Error evaluating deletion expiration for user '{user.get('user_id')}': {e}")

    # Reactivate account within grace period
    user["is_pending_deletion"] = False
    user["deletion_scheduled_at"] = None
    user["account_restored"] = True
    return "Welcome back! Your account deletion request was cancelled and your account has been restored."


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DynamoDBService = Depends(get_db_service),
    auth: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """
    Dependency that extracts and verifies Bearer token, retrieving the user record.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    token_claims = auth.verify_token(token)
    if not token_claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = token_claims["user_id"]
    user = db.get_user_by_id(user_id)

    if not user:
        # Check by email if user registered with email previously
        email = token_claims.get("email")
        if email:
            clean_email = email.strip().lower()
            user = db.get_user_by_email(clean_email)

        # Auto-provision if authenticated via Firebase ID token and not existing
        if not user and token_claims.get("auth_type") == "firebase":
            now_iso = datetime.now(timezone.utc).isoformat()
            user = {
                "user_id": user_id,
                "email": clean_email if email else None,
                "display_name": token_claims.get("display_name") or "Tech Reader",
                "avatar_url": token_claims.get("avatar_url"),
                "is_anonymous": token_claims.get("is_anonymous", False),
                "created_at": now_iso,
                "last_active_at": now_iso,
                "topic_preferences": build_default_preferences(),
                "algo_weights": build_default_algo_weights(),
                "bookmarked_articles": [],
                "reading_history": [],
                "reading_count": 0,
            }
            db.save_user(user)
        elif not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # If account was scheduled for deletion, verify if the 24h grace period expired
    if user.get("is_pending_deletion"):
        deletion_scheduled_at = user.get("deletion_scheduled_at")
        if deletion_scheduled_at:
            try:
                sched_dt = datetime.fromisoformat(deletion_scheduled_at.replace("Z", "+00:00"))
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if now >= sched_dt:
                    db.delete_user(user["user_id"])
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Account has been permanently deleted.",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Error checking deletion expiration in get_current_user: {e}")

    return user


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register_account(
    req: UserRegisterRequest,
    response: Response,
    db: DynamoDBService = Depends(get_db_service),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """
    Creates a permanent user account with email and password.
    Seamlessly migrates reading history, bookmarks, and personalization
    weights from an existing guest session if provided.
    """
    response.headers["Cache-Control"] = "no-store"
    clean_email = req.email.strip().lower()

    # Check for existing email registration
    existing_user = db.get_user_by_email(clean_email)
    if existing_user:
        if existing_user.get("is_pending_deletion"):
            deletion_scheduled_at = existing_user.get("deletion_scheduled_at")
            if deletion_scheduled_at:
                try:
                    sched_dt = datetime.fromisoformat(deletion_scheduled_at.replace("Z", "+00:00"))
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    if now >= sched_dt:
                        db.delete_user(existing_user["user_id"])
                        existing_user = None
                except Exception:
                    pass
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists.",
            )

    user_id = f"usr_{uuid.uuid4().hex[:16]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    password_hash = auth.hash_password(req.password)

    user_data = {
        "user_id": user_id,
        "email": clean_email,
        "password_hash": password_hash,
        "display_name": req.display_name.strip() if req.display_name else clean_email.split("@")[0],
        "is_anonymous": False,
        "created_at": now_iso,
        "last_active_at": now_iso,
        "topic_preferences": build_default_preferences(),
        "algo_weights": build_default_algo_weights(),
        "bookmarked_articles": [],
        "reading_history": [],
        "reading_count": 0,
    }

    db.save_user(user_data)

    # Migrate guest reading state and weights if guest_user_id provided
    if req.guest_user_id:
        db.migrate_guest_data(req.guest_user_id, user_id)
        # Reload migrated user data
        refreshed = db.get_user_by_id(user_id)
        if refreshed:
            user_data = refreshed

    token = auth.create_access_token(user_id=user_id, email=clean_email, is_anonymous=False)
    return AuthResponse(
        status="success",
        access_token=token,
        token_type="bearer",
        user=to_user_profile(user_data),
    )


@router.post("/login", response_model=AuthResponse)
def login_account(
    req: UserLoginRequest,
    response: Response,
    db: DynamoDBService = Depends(get_db_service),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """
    Authenticates user with email and password, issuing a 30-day session JWT.
    If the account was pending deletion and the user logs in before the 24-hour
    grace period expires, the account is reactivated.
    """
    response.headers["Cache-Control"] = "no-store"
    clean_email = req.email.strip().lower()

    user = db.get_user_by_email(clean_email)
    if not user or not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    restored_message = check_and_handle_account_deletion_on_login(user, db)

    user["last_active_at"] = datetime.now(timezone.utc).isoformat()
    db.save_user(user)

    # Migrate guest reading state and weights if guest_user_id provided
    if req.guest_user_id:
        db.migrate_guest_data(req.guest_user_id, user["user_id"])
        refreshed = db.get_user_by_id(user["user_id"])
        if refreshed:
            user = refreshed

    token = auth.create_access_token(
        user_id=user["user_id"],
        email=clean_email,
        is_anonymous=user.get("is_anonymous", False),
    )

    return AuthResponse(
        status="success",
        access_token=token,
        token_type="bearer",
        user=to_user_profile(user),
        message=restored_message,
    )


@router.post("/guest", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def create_guest_session(
    req: GuestSessionRequest,
    response: Response,
    db: DynamoDBService = Depends(get_db_service),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """
    Creates an anonymous guest user account.
    Allows zero-friction cold start on mobile app while tracking engagement
    and tuning feed algorithm weights from the user's very first swipe.
    """
    response.headers["Cache-Control"] = "no-store"
    guest_id = f"guest_{uuid.uuid4().hex[:16]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    prefs = build_default_preferences()
    if req.initial_preferences:
        prefs.update(req.initial_preferences)

    guest_user = {
        "user_id": guest_id,
        "is_anonymous": True,
        "device_id": req.device_id,
        "display_name": "Guest Reader",
        "created_at": now_iso,
        "last_active_at": now_iso,
        "topic_preferences": prefs,
        "algo_weights": build_default_algo_weights(),
        "bookmarked_articles": [],
        "reading_history": [],
        "reading_count": 0,
    }

    db.save_user(guest_user)
    token = auth.create_access_token(user_id=guest_id, email=None, is_anonymous=True)

    return AuthResponse(
        status="success",
        access_token=token,
        token_type="bearer",
        user=to_user_profile(guest_user),
    )


@router.post("/firebase-login", response_model=AuthResponse)
def login_with_firebase(
    req: FirebaseLoginRequest,
    response: Response,
    db: DynamoDBService = Depends(get_db_service),
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """
    Exchanges a Firebase Auth ID token for a ZeroDaily user session.
    Provisions or synchronizes the DynamoDB profile and migrates guest history if requested.
    """
    response.headers["Cache-Control"] = "no-store"
    claims = auth.verify_firebase_id_token(req.id_token)
    if not claims or "sub" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase ID token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    fb_uid = claims["sub"]
    user_id = f"fb_{fb_uid}"
    email = claims.get("email")

    user = db.get_user_by_id(user_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    if not user:
        # Check by email if user signed up with email before
        if email:
            user = db.get_user_by_email(email)

    restored_message = None
    if not user:
        user = {
            "user_id": user_id,
            "email": email,
            "display_name": claims.get("name") or "Tech Reader",
            "avatar_url": claims.get("picture"),
            "is_anonymous": claims.get("firebase", {}).get("sign_in_provider") == "anonymous",
            "created_at": now_iso,
            "last_active_at": now_iso,
            "topic_preferences": build_default_preferences(),
            "algo_weights": build_default_algo_weights(),
            "bookmarked_articles": [],
            "reading_history": [],
            "reading_count": 0,
        }
        db.save_user(user)
    else:
        restored_message = check_and_handle_account_deletion_on_login(user, db)
        user["last_active_at"] = now_iso
        db.save_user(user)

    if req.guest_user_id and req.guest_user_id != user["user_id"]:
        db.migrate_guest_data(req.guest_user_id, user["user_id"])
        refreshed = db.get_user_by_id(user["user_id"])
        if refreshed:
            user = refreshed

    token = auth.create_access_token(
        user_id=user["user_id"],
        email=user.get("email"),
        is_anonymous=user.get("is_anonymous", False),
    )

    return AuthResponse(
        status="success",
        access_token=token,
        token_type="bearer",
        user=to_user_profile(user),
        message=restored_message,
    )


@router.get("/me", response_model=UserProfile)
def get_authenticated_profile(
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> UserProfile:
    """Returns the authenticated user's profile and algorithmic status."""
    response.headers["Cache-Control"] = "no-store"
    return to_user_profile(current_user)


@router.patch("/preferences", response_model=UserProfile)
def update_preferences(
    req: PreferencesUpdateRequest,
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: DynamoDBService = Depends(get_db_service),
) -> UserProfile:
    """Updates the user's category notification & feed topic subscriptions."""
    response.headers["Cache-Control"] = "no-store"
    # Sanitize preferences map to recognized canonical categories
    sanitized: Dict[str, bool] = {}
    for cat, enabled in req.topic_preferences.items():
        canonical = normalize_category_key(cat)
        if canonical:
            sanitized[canonical] = bool(enabled)

    updated = db.update_user_preferences(current_user["user_id"], sanitized)
    return to_user_profile(updated or current_user)


@router.post("/track", response_model=TrackingResponse)
def track_reading_event(
    req: UserTrackingEventRequest,
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: DynamoDBService = Depends(get_db_service),
) -> TrackingResponse:
    """
    Telemetry and algorithmic feedback beacon.
    Adjusts user category weights based on reading duration and interactions.
    """
    response.headers["Cache-Control"] = "no-store"
    canonical_cat = normalize_category_key(req.category)
    if not canonical_cat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{req.category}' is not recognized. Valid options: {CANONICAL_CATEGORIES}",
        )

    res = db.record_user_interaction(
        user_id=current_user["user_id"],
        article_id=req.article_id,
        category=canonical_cat,
        action=req.action,
        duration_seconds=req.duration_seconds or 0.0,
    )
    return TrackingResponse(
        status="success",
        user_id=current_user["user_id"],
        action=req.action,
        algo_weights=res.get("algo_weights", {}),
    )


@router.post("/sync-bookmarks", response_model=SyncBookmarksResponse)
def sync_bookmarks(
    req: SyncBookmarksRequest,
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: DynamoDBService = Depends(get_db_service),
) -> SyncBookmarksResponse:
    """Merges offline local bookmarks with user cloud profile or replaces them."""
    response.headers["Cache-Control"] = "no-store"
    mode = req.mode or "merge"
    merged = db.sync_user_bookmarks(current_user["user_id"], req.bookmarks, mode=mode)
    return SyncBookmarksResponse(
        status="success",
        bookmarks=merged,
    )


@router.delete("/account", response_model=AccountDeletionResponse)
@router.post("/delete-account", response_model=AccountDeletionResponse)
def request_account_deletion(
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: DynamoDBService = Depends(get_db_service),
) -> AccountDeletionResponse:
    """
    Schedules user account deletion with a 1-day (24-hour) grace period.
    If the user logs in before the 24-hour window expires, the account is reactivated.
    If after 24 hours, the account is permanently deleted.
    """
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    deletion_scheduled_at = (now + timedelta(days=1)).isoformat()

    current_user["is_pending_deletion"] = True
    current_user["deletion_scheduled_at"] = deletion_scheduled_at
    current_user["account_restored"] = False
    current_user["last_active_at"] = now.isoformat()
    db.save_user(current_user)

    return AccountDeletionResponse(
        status="success",
        message="Account scheduled for deletion. You have 24 hours to log in again to cancel deletion and reactivate your account.",
        deletion_scheduled_at=deletion_scheduled_at,
        is_pending_deletion=True,
    )
