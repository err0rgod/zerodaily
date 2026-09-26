from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_db_service
from app.services.auth_service import AuthService, get_auth_service

client = TestClient(app)


@pytest.fixture
def auth_service():
    return get_auth_service()


@pytest.fixture
def mock_db():
    mock = MagicMock()
    app.dependency_overrides[get_db_service] = lambda: mock
    yield mock
    app.dependency_overrides.clear()


def test_register_account_success(mock_db, auth_service):
    # No existing user with this email
    mock_db.get_user_by_email.return_value = None
    mock_db.save_user.side_effect = lambda u: u
    mock_db.get_user_by_id.return_value = None

    payload = {
        "email": "reader@example.com",
        "password": "Password123!",
        "display_name": "Satire Fan",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    user = data["user"]
    assert user["email"] == "reader@example.com"
    assert user["display_name"] == "Satire Fan"
    assert user["is_anonymous"] is False
    assert user["algo_weights"]["cybersec"] == 1.0
    assert user["topic_preferences"]["ai"] is True

    # Verify password was hashed and not saved in plaintext
    saved_user = mock_db.save_user.call_args[0][0]
    assert saved_user["password_hash"] != "Password123!"
    assert auth_service.verify_password("Password123!", saved_user["password_hash"])


def test_register_duplicate_email(mock_db):
    mock_db.get_user_by_email.return_value = {
        "user_id": "usr_existing123",
        "email": "existing@example.com",
    }

    payload = {
        "email": "existing@example.com",
        "password": "SecretPassword123",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_register_invalid_email():
    payload = {
        "email": "not-a-valid-email",
        "password": "ValidPassword123",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_register_short_password():
    payload = {
        "email": "valid@example.com",
        "password": "123",  # Under 6 chars
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_register_with_guest_migration(mock_db):
    mock_db.get_user_by_email.return_value = None
    mock_db.save_user.side_effect = lambda u: u

    def mock_migrate(guest_id, perm_id):
        return True

    mock_db.migrate_guest_data.side_effect = mock_migrate
    mock_db.get_user_by_id.return_value = {
        "user_id": "usr_migrated123",
        "email": "migrated@example.com",
        "display_name": "Migrated User",
        "is_anonymous": False,
        "created_at": "2026-09-26T12:00:00Z",
        "last_active_at": "2026-09-26T12:00:00Z",
        "topic_preferences": {"ai": True, "cybersec": True},
        "algo_weights": {"ai": 1.45, "cybersec": 1.20},
        "bookmarked_articles": ["https://example.com/art1"],
        "reading_history": [{"article_id": "https://example.com/art1"}],
        "reading_count": 5,
    }

    payload = {
        "email": "migrated@example.com",
        "password": "Password123!",
        "guest_user_id": "guest_abc123",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    mock_db.migrate_guest_data.assert_called_once()
    data = response.json()
    assert data["user"]["algo_weights"]["ai"] == 1.45
    assert len(data["user"]["bookmarked_articles"]) == 1


def test_login_account_success(mock_db, auth_service):
    hashed_pw = auth_service.hash_password("MyPassword456!")
    mock_db.get_user_by_email.return_value = {
        "user_id": "usr_login_test",
        "email": "user@example.com",
        "password_hash": hashed_pw,
        "display_name": "Test User",
        "is_anonymous": False,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
        "topic_preferences": {"cybersec": True},
        "algo_weights": {"cybersec": 1.2},
        "bookmarked_articles": [],
        "reading_count": 3,
    }
    mock_db.save_user.side_effect = lambda u: u

    payload = {
        "email": "user@example.com",
        "password": "MyPassword456!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["user"]["email"] == "user@example.com"
    assert data["user"]["display_name"] == "Test User"


def test_login_account_wrong_password(mock_db, auth_service):
    hashed_pw = auth_service.hash_password("CorrectPassword123")
    mock_db.get_user_by_email.return_value = {
        "user_id": "usr_wrong_pw",
        "email": "user@example.com",
        "password_hash": hashed_pw,
    }

    payload = {
        "email": "user@example.com",
        "password": "WrongPassword999",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_nonexistent_email(mock_db):
    mock_db.get_user_by_email.return_value = None

    payload = {
        "email": "doesnotexist@example.com",
        "password": "Password123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_guest_session_creation(mock_db):
    mock_db.save_user.side_effect = lambda u: u

    payload = {
        "device_id": "android_uuid_555",
        "initial_preferences": {"cybersec": True, "hardware": False},
    }
    response = client.post("/api/v1/auth/guest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert data["user"]["is_anonymous"] is True
    assert data["user"]["user_id"].startswith("guest_")
    assert data["user"]["topic_preferences"]["hardware"] is False


def test_get_current_user_profile_success(mock_db, auth_service):
    user_id = "usr_me_123"
    token = auth_service.create_access_token(user_id=user_id, email="me@example.com")

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "me@example.com",
        "display_name": "Me Profile",
        "is_anonymous": False,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
        "topic_preferences": {"ai": True},
        "algo_weights": {"ai": 1.1},
        "bookmarked_articles": [],
        "reading_count": 7,
    }

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user_id
    assert data["display_name"] == "Me Profile"
    assert data["reading_count"] == 7


def test_get_current_user_missing_token():
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_get_current_user_invalid_token():
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.jwt.token"})
    assert response.status_code == 401


def test_update_preferences(mock_db, auth_service):
    user_id = "usr_prefs_123"
    token = auth_service.create_access_token(user_id=user_id, email="prefs@example.com")

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "prefs@example.com",
        "topic_preferences": {"ai": True, "finance": True},
        "algo_weights": {"ai": 1.0},
        "bookmarked_articles": [],
        "reading_count": 0,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
    }
    mock_db.update_user_preferences.return_value = {
        "user_id": user_id,
        "email": "prefs@example.com",
        "topic_preferences": {"ai": False, "finance": True},
        "algo_weights": {"ai": 1.0},
        "bookmarked_articles": [],
        "reading_count": 0,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
    }

    response = client.patch(
        "/api/v1/auth/preferences",
        json={"topic_preferences": {"ai": False, "finance": True}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["topic_preferences"]["ai"] is False


def test_track_reading_event(mock_db, auth_service):
    user_id = "usr_track_123"
    token = auth_service.create_access_token(user_id=user_id, email="track@example.com")

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "track@example.com",
        "topic_preferences": {},
        "algo_weights": {"cybersec": 1.0},
        "bookmarked_articles": [],
        "reading_count": 0,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
    }
    mock_db.record_user_interaction.return_value = {
        "algo_weights": {"cybersec": 1.35},
        "reading_count": 1,
    }

    payload = {
        "article_id": "https://example.com/cyber-breach",
        "category": "cybersec",
        "action": "read",
        "duration_seconds": 25.5,
    }
    response = client.post(
        "/api/v1/auth/track",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["action"] == "read"
    assert data["algo_weights"]["cybersec"] == 1.35


def test_sync_bookmarks(mock_db, auth_service):
    user_id = "usr_sync_123"
    token = auth_service.create_access_token(user_id=user_id, email="sync@example.com")

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "sync@example.com",
        "topic_preferences": {},
        "algo_weights": {},
        "bookmarked_articles": ["https://example.com/art1"],
        "reading_count": 0,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
    }
    mock_db.sync_user_bookmarks.return_value = [
        "https://example.com/art1",
        "https://example.com/art2",
    ]

    payload = {
        "bookmarks": ["https://example.com/art2"],
    }
    response = client.post(
        "/api/v1/auth/sync-bookmarks",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["bookmarks"]) == 2
    assert "https://example.com/art2" in data["bookmarks"]


@patch.object(AuthService, "verify_firebase_id_token")
def test_firebase_login_success(mock_verify_fb, mock_db):
    mock_verify_fb.return_value = {
        "sub": "fb_uid_9876",
        "email": "googleuser@gmail.com",
        "name": "Google User",
        "picture": "https://lh3.googleusercontent.com/photo.jpg",
        "firebase": {"sign_in_provider": "google.com"},
    }
    mock_db.get_user_by_id.return_value = None
    mock_db.get_user_by_email.return_value = None
    mock_db.save_user.side_effect = lambda u: u

    payload = {
        "id_token": "valid_firebase_jwt_string",
    }
    response = client.post("/api/v1/auth/firebase-login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["user"]["user_id"] == "fb_fb_uid_9876"
    assert data["user"]["email"] == "googleuser@gmail.com"
    assert data["user"]["display_name"] == "Google User"


def test_expired_token_rejected(auth_service):
    from datetime import timedelta
    expired_token = auth_service.create_access_token(
        user_id="usr_expired",
        expires_delta=timedelta(seconds=-10),
    )
    # verify decoding returns None
    assert auth_service.decode_access_token(expired_token) is None
    # verify API rejects it
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401


def test_track_negative_duration_handled_gracefully(mock_db, auth_service):
    user_id = "usr_track_neg"
    token = auth_service.create_access_token(user_id=user_id, email="trackneg@example.com")
    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "trackneg@example.com",
        "algo_weights": {"ai": 1.0},
        "reading_history": [],
        "reading_count": 0,
    }
    mock_db.record_user_interaction.return_value = {
        "algo_weights": {"ai": 1.15},
        "reading_count": 1,
    }

    payload = {
        "article_id": "https://example.com/art-neg",
        "category": "ai",
        "action": "read",
        "duration_seconds": -15.0,  # Negative dwell
    }
    response = client.post(
        "/api/v1/auth/track",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_auth_service_verify_password_handles_corrupt_hash(auth_service):
    assert auth_service.verify_password("Password123!", "not_a_bcrypt_hash") is False
    assert auth_service.verify_password("", "some_hash") is False
    assert auth_service.verify_password("Password123!", "") is False


def test_register_long_password_handles_bcrypt_limit(mock_db, auth_service):
    """Test passwords > 72 bytes are handled gracefully without bcrypt ValueError."""
    mock_db.get_user_by_email.return_value = None
    mock_db.save_user.side_effect = lambda u: u
    mock_db.get_user_by_id.return_value = None

    long_password = "A" * 90  # 90 characters, exceeds 72 bytes
    payload = {
        "email": "longpw@example.com",
        "password": long_password,
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    saved_user = mock_db.save_user.call_args[0][0]
    assert auth_service.verify_password(long_password, saved_user["password_hash"])


def test_login_with_guest_migration(mock_db, auth_service):
    """Test logging in seamlessly migrates guest reading state and weights."""
    hashed_pw = auth_service.hash_password("MySecretPass123!")
    user_record = {
        "user_id": "usr_existing_login",
        "email": "returning@example.com",
        "password_hash": hashed_pw,
        "display_name": "Returning Reader",
        "is_anonymous": False,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
        "topic_preferences": {"cybersec": True},
        "algo_weights": {"cybersec": 1.2},
        "bookmarked_articles": ["https://example.com/art1"],
        "reading_history": [],
        "reading_count": 3,
    }
    mock_db.get_user_by_email.return_value = user_record
    mock_db.get_user_by_id.return_value = user_record
    mock_db.save_user.side_effect = lambda u: u
    mock_db.migrate_guest_data.return_value = True

    payload = {
        "email": "returning@example.com",
        "password": "MySecretPass123!",
        "guest_user_id": "guest_temp_999",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    mock_db.migrate_guest_data.assert_called_once_with("guest_temp_999", "usr_existing_login")


def test_security_migrate_guest_data_rejects_non_guest():
    """Security test: verify migrate_guest_data rejects migrating permanent users and does not delete them."""
    from app.db import DynamoDBService

    service = DynamoDBService.__new__(DynamoDBService)
    service.users_table = MagicMock()

    victim_user = {
        "user_id": "usr_victim_account",
        "email": "victim@example.com",
        "is_anonymous": False,
        "password_hash": "hash_abc",
        "bookmarked_articles": ["https://example.com/private"],
    }
    perm_user = {
        "user_id": "usr_attacker_account",
        "email": "attacker@example.com",
        "is_anonymous": False,
    }

    def get_user_mock(uid):
        if uid == "usr_victim_account":
            return dict(victim_user)
        if uid == "usr_attacker_account":
            return dict(perm_user)
        return None

    service.get_user_by_id = MagicMock(side_effect=get_user_mock)
    service.save_user = MagicMock()

    # Attempt to migrate victim into attacker
    result = service.migrate_guest_data("usr_victim_account", "usr_attacker_account")
    assert result is False
    service.users_table.delete_item.assert_not_called()
    service.save_user.assert_not_called()


def test_sync_bookmarks_replace_mode(mock_db, auth_service):
    """Test sync_bookmarks with mode='replace' enables removing unbookmarked articles."""
    user_id = "usr_sync_replace"
    token = auth_service.create_access_token(user_id=user_id, email="replace@example.com")

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "replace@example.com",
        "bookmarked_articles": ["https://example.com/art1", "https://example.com/art2"],
    }
    mock_db.sync_user_bookmarks.return_value = ["https://example.com/art2"]

    payload = {
        "bookmarks": ["https://example.com/art2"],
        "mode": "replace",
    }
    response = client.post(
        "/api/v1/auth/sync-bookmarks",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    mock_db.sync_user_bookmarks.assert_called_once_with(user_id, ["https://example.com/art2"], mode="replace")
    assert response.json()["bookmarks"] == ["https://example.com/art2"]


def test_track_reading_event_category_validation(mock_db, auth_service):
    """Test tracking endpoint validates category and rejects unrecognized ones."""
    user_id = "usr_track_val"
    token = auth_service.create_access_token(user_id=user_id, email="val@example.com")
    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "val@example.com",
    }

    # Unrecognized category
    payload = {
        "article_id": "https://example.com/art",
        "category": "completely_fake_category",
        "action": "read",
    }
    response = client.post(
        "/api/v1/auth/track",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "not recognized" in response.json()["detail"]


def test_track_reading_event_category_alias_normalized(mock_db, auth_service):
    """Test tracking endpoint normalizes category alias 'cybersecurity' to 'cybersec'."""
    user_id = "usr_track_alias"
    token = auth_service.create_access_token(user_id=user_id, email="alias@example.com")
    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "alias@example.com",
    }
    mock_db.record_user_interaction.return_value = {
        "algo_weights": {"cybersec": 1.25},
        "reading_count": 1,
    }

    payload = {
        "article_id": "https://example.com/art",
        "category": "cybersecurity",
        "action": "read",
        "duration_seconds": 10.0,
    }
    response = client.post(
        "/api/v1/auth/track",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    # Verify canonical category 'cybersec' was passed to db service
    mock_db.record_user_interaction.assert_called_once_with(
        user_id=user_id,
        article_id="https://example.com/art",
        category="cybersec",
        action="read",
        duration_seconds=10.0,
    )


def test_delete_account_success(mock_db, auth_service):
    """Test authenticated user scheduling account deletion with 24-hour grace period."""
    user_id = "usr_delete_test"
    token = auth_service.create_access_token(user_id=user_id, email="del@example.com")
    user_record = {
        "user_id": user_id,
        "email": "del@example.com",
        "is_anonymous": False,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
    }
    mock_db.get_user_by_id.return_value = user_record
    mock_db.save_user.side_effect = lambda u: u

    response = client.delete(
        "/api/v1/auth/account",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["is_pending_deletion"] is True
    assert "deletion_scheduled_at" in data
    assert "24 hours" in data["message"]

    # Verify user record updated in DynamoDB
    saved_user = mock_db.save_user.call_args[0][0]
    assert saved_user["is_pending_deletion"] is True
    assert saved_user["deletion_scheduled_at"] is not None


def test_delete_account_unauthorized():
    """Test account deletion rejected without authentication."""
    response = client.delete("/api/v1/auth/account")
    assert response.status_code == 401


def test_login_reactivates_account_within_grace_period(mock_db, auth_service):
    """Test logging in within 24-hour grace period cancels deletion and restores account."""
    user_id = "usr_restore_test"
    hashed_pw = auth_service.hash_password("SafePassword123!")
    future_deletion = (datetime.now(timezone.utc) + timedelta(hours=18)).isoformat()

    mock_db.get_user_by_email.return_value = {
        "user_id": user_id,
        "email": "restore@example.com",
        "password_hash": hashed_pw,
        "is_pending_deletion": True,
        "deletion_scheduled_at": future_deletion,
        "is_anonymous": False,
        "created_at": "2026-09-26T10:00:00Z",
        "last_active_at": "2026-09-26T10:00:00Z",
        "topic_preferences": {"ai": True},
        "algo_weights": {"ai": 1.0},
        "bookmarked_articles": [],
        "reading_count": 2,
    }
    mock_db.save_user.side_effect = lambda u: u

    payload = {
        "email": "restore@example.com",
        "password": "SafePassword123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "restored" in (data.get("message") or "").lower()
    assert data["user"]["is_pending_deletion"] is False
    assert data["user"]["account_restored"] is True

    # Verify saved state in DB has deletion cancelled
    saved_user = mock_db.save_user.call_args[0][0]
    assert saved_user["is_pending_deletion"] is False
    assert saved_user["deletion_scheduled_at"] is None


def test_login_permanently_deletes_expired_account(mock_db, auth_service):
    """Test logging in after 24-hour grace period permanently deletes account and rejects login."""
    user_id = "usr_expired_test"
    hashed_pw = auth_service.hash_password("SafePassword123!")
    past_deletion = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    mock_db.get_user_by_email.return_value = {
        "user_id": user_id,
        "email": "expired@example.com",
        "password_hash": hashed_pw,
        "is_pending_deletion": True,
        "deletion_scheduled_at": past_deletion,
        "is_anonymous": False,
    }
    mock_db.delete_user.return_value = True

    payload = {
        "email": "expired@example.com",
        "password": "SafePassword123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    assert "permanently deleted" in response.json()["detail"].lower()
    mock_db.delete_user.assert_called_once_with(user_id)


def test_protected_endpoint_rejects_and_deletes_expired_account(mock_db, auth_service):
    """Test accessing protected route with active token when 24h grace period has passed."""
    user_id = "usr_token_expired"
    token = auth_service.create_access_token(user_id=user_id, email="token_exp@example.com")
    past_deletion = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()

    mock_db.get_user_by_id.return_value = {
        "user_id": user_id,
        "email": "token_exp@example.com",
        "is_pending_deletion": True,
        "deletion_scheduled_at": past_deletion,
        "is_anonymous": False,
    }
    mock_db.delete_user.return_value = True

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "permanently deleted" in response.json()["detail"].lower()
    mock_db.delete_user.assert_called_once_with(user_id)


def test_register_purges_expired_pending_account_and_succeeds(mock_db):
    """Test registering with email of an account whose 24h deletion window expired."""
    user_id = "usr_purged_old"
    past_deletion = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()

    # First call returns old expired user, then after delete_user returns None
    mock_db.get_user_by_email.return_value = {
        "user_id": user_id,
        "email": "reregister@example.com",
        "is_pending_deletion": True,
        "deletion_scheduled_at": past_deletion,
    }
    mock_db.delete_user.return_value = True
    mock_db.save_user.side_effect = lambda u: u
    mock_db.get_user_by_id.return_value = None

    payload = {
        "email": "reregister@example.com",
        "password": "NewFreshPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    mock_db.delete_user.assert_called_once_with(user_id)


def test_register_rejects_during_pending_deletion_grace_period(mock_db):
    """Test registering with email of an account currently within 24h grace period is rejected."""
    user_id = "usr_pending_grace"
    future_deletion = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()

    mock_db.get_user_by_email.return_value = {
        "user_id": user_id,
        "email": "pending@example.com",
        "is_pending_deletion": True,
        "deletion_scheduled_at": future_deletion,
    }

    payload = {
        "email": "pending@example.com",
        "password": "Password123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()
