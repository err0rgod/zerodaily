import pytest
from unittest.mock import MagicMock, patch
from workers.stream_handler import (
    parse_dynamodb_attribute,
    extract_breaking_article,
    lambda_handler,
)


def test_parse_dynamodb_attribute():
    assert parse_dynamodb_attribute({"S": "cybersec"}) == "cybersec"
    assert parse_dynamodb_attribute({"BOOL": True}) is True
    assert parse_dynamodb_attribute({"BOOL": False}) is False
    assert parse_dynamodb_attribute({"N": "42"}) == 42
    assert parse_dynamodb_attribute({"N": "42.5"}) == 42.5
    assert parse_dynamodb_attribute({"NULL": True}) is None
    assert parse_dynamodb_attribute({"L": [{"S": "a"}, {"S": "b"}]}) == ["a", "b"]
    assert parse_dynamodb_attribute({"M": {"key": {"S": "val"}}}) == {"key": "val"}


def test_extract_breaking_article_qualifies():
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "id": {"S": "https://example.com/breaking-1"},
                "category": {"S": "cybersec"},
                "is_breaking": {"BOOL": True},
                "push_punchline": {"S": "Critical Vulnerability Disclosed in Linux Kernel!"},
                "heading": {"S": "Linux Kernel Flaw Exposes Root Privileges"},
                "image_url": {"S": "https://media.zerodaily.in/images/cybersec/hash.webp"},
                "published_at": {"S": "2026-09-16T12:00:00Z"},
            }
        },
    }
    extracted = extract_breaking_article(record)
    assert extracted is not None
    assert extracted["article_id"] == "https://example.com/breaking-1"
    assert extracted["category"] == "cybersec"
    assert extracted["push_punchline"] == "Critical Vulnerability Disclosed in Linux Kernel!"


def test_extract_breaking_article_ignores_modify_or_remove():
    record = {
        "eventName": "MODIFY",
        "dynamodb": {
            "NewImage": {
                "id": {"S": "https://example.com/test"},
                "is_breaking": {"BOOL": True},
            }
        },
    }
    assert extract_breaking_article(record) is None


def test_extract_breaking_article_ignores_non_breaking():
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "id": {"S": "https://example.com/test"},
                "is_breaking": {"BOOL": False},
            }
        },
    }
    assert extract_breaking_article(record) is None


def test_extract_breaking_article_ignores_internal_locks():
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "id": {"S": "NOTIF_COOLDOWN#cybersec"},
                "is_breaking": {"BOOL": True},
            }
        },
    }
    assert extract_breaking_article(record) is None


@patch("workers.stream_handler.CDNClient")
@patch("workers.stream_handler.FCMClient")
@patch("workers.stream_handler.NotificationCooldownManager")
def test_lambda_handler_dispatches_when_cooldown_permits(mock_cooldown_cls, mock_fcm_cls, mock_cdn_cls):
    mock_cooldown = mock_cooldown_cls.return_value
    mock_cooldown.acquire_push_permission.return_value = True

    mock_fcm = mock_fcm_cls.return_value
    mock_fcm.dispatch_breaking_news.return_value = {"topic_cybersec": {"name": "msg_123"}}

    event = {
        "Records": [
            {
                "eventName": "INSERT",
                "dynamodb": {
                    "NewImage": {
                        "id": {"S": "https://example.com/alert-1"},
                        "category": {"S": "cybersec"},
                        "is_breaking": {"BOOL": True},
                        "push_punchline": {"S": "Major Outage!"},
                        "heading": {"S": "Global Cloud Outage"},
                        "image_url": {"S": "https://media.zerodaily.in/images/cybersec/alert.webp"},
                        "published_at": {"S": "2026-09-16T12:00:00Z"},
                    }
                }
            }
        ]
    }

    result = lambda_handler(event)
    assert result["total_records"] == 1
    assert result["breaking_candidates"] == 1
    assert result["dispatched"] == 1
    assert result["cooldown_suppressed"] == 0
    mock_fcm.dispatch_breaking_news.assert_called_once()


@patch("workers.stream_handler.CDNClient")
@patch("workers.stream_handler.FCMClient")
@patch("workers.stream_handler.NotificationCooldownManager")
def test_lambda_handler_suppresses_when_in_cooldown(mock_cooldown_cls, mock_fcm_cls, mock_cdn_cls):
    mock_cooldown = mock_cooldown_cls.return_value
    mock_cooldown.acquire_push_permission.return_value = False

    mock_fcm = mock_fcm_cls.return_value

    event = {
        "Records": [
            {
                "eventName": "INSERT",
                "dynamodb": {
                    "NewImage": {
                        "id": {"S": "https://example.com/alert-2"},
                        "category": {"S": "ai"},
                        "is_breaking": {"BOOL": True},
                        "heading": {"S": "New AI Model Released"},
                        "image_url": {"S": ""},
                        "published_at": {"S": "2026-09-16T12:00:00Z"},
                    }
                }
            }
        ]
    }

    result = lambda_handler(event)
    assert result["breaking_candidates"] == 1
    assert result["dispatched"] == 0
    assert result["cooldown_suppressed"] == 1
    mock_fcm.dispatch_breaking_news.assert_not_called()
