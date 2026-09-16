import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "zerodaily-api"
    assert "no-store" in response.headers.get("Cache-Control", "")


def test_categories_endpoint():
    response = client.get("/api/v1/categories")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["categories"]) == 6
    assert any(c["key"] == "cybersec" for c in data["categories"])
    assert "max-age=86400" in response.headers.get("Cache-Control", "")


@patch("app.routers.feed.get_db_service")
def test_global_feed_endpoint(mock_get_db):
    mock_db = MagicMock()
    mock_db.query_global_feed.return_value = (
        [
            {
                "id": "https://example.com/art-1",
                "category": "ai",
                "heading": "Roasted AI Headline",
                "shortSummary": "Short roast",
                "fullSummary": "Full roast breakdown",
                "published_at": "2026-09-16T12:00:00Z",
                "link": "https://example.com/art-1",
                "image_url": "https://media.zerodaily.in/images/ai/test.webp",
            }
        ],
        None,
        False,
    )
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/feed?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["data"]) == 1
    assert data["pagination"]["count"] == 1
    assert data["pagination"]["has_more"] is False
    assert "s-maxage=300" in response.headers.get("Cache-Control", "")


@patch("app.routers.feed.get_db_service")
def test_category_feed_endpoint(mock_get_db):
    mock_db = MagicMock()
    mock_db.query_category_feed.return_value = (
        [
            {
                "id": "https://example.com/sec-1",
                "category": "cybersec",
                "heading": "Roasted Sec Headline",
                "shortSummary": "Short sec roast",
                "fullSummary": "Full sec roast breakdown",
                "published_at": "2026-09-16T11:00:00Z",
                "link": "https://example.com/sec-1",
                "image_url": "https://media.zerodaily.in/images/cybersec/test.webp",
            }
        ],
        "2026-09-16T11:00:00Z",
        True,
    )
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/feed/cybersec?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "cybersec"
    assert len(data["data"]) == 1
    assert data["pagination"]["has_more"] is True
    assert data["pagination"]["next_cursor"] == "2026-09-16T11:00:00Z"


def test_category_feed_invalid_category():
    response = client.get("/api/v1/feed/invalid_category_name")
    assert response.status_code == 404
    assert "not recognized" in response.json()["detail"]


@patch("app.routers.articles.get_db_service")
def test_single_article_by_path(mock_get_db):
    mock_db = MagicMock()
    mock_db.get_article_by_id.return_value = {
        "id": "https://example.com/sample",
        "category": "programming",
        "heading": "Framework #4291 Released",
        "shortSummary": "Short summary",
        "fullSummary": "Full summary",
        "published_at": "2026-09-16T10:00:00Z",
        "link": "https://example.com/sample",
        "image_url": "https://media.zerodaily.in/images/programming/test.webp",
    }
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/articles/https://example.com/sample")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["heading"] == "Framework #4291 Released"
    assert "max-age=3600" in response.headers.get("Cache-Control", "")


@patch("app.routers.articles.get_db_service")
def test_single_article_not_found(mock_get_db):
    mock_db = MagicMock()
    mock_db.get_article_by_id.return_value = None
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/articles/https://example.com/nonexistent")
    assert response.status_code == 404
    assert response.json()["status"] == "error"


@patch("app.routers.notifications.get_db_service")
def test_notification_history(mock_get_db):
    mock_db = MagicMock()
    mock_db.get_recent_breaking_alerts.return_value = [
        {
            "id": "https://example.com/break-1",
            "category": "cybersec",
            "heading": "Big Breach",
            "push_punchline": "Major breach occurred",
            "image_url": "https://media.zerodaily.in/images/cybersec/b.webp",
            "published_at": "2026-09-16T12:00:00Z",
        }
    ]
    mock_get_db.return_value = mock_db

    response = client.get("/api/v1/notifications/history")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] == 1
    assert data["data"][0]["push_punchline"] == "Major breach occurred"
