import pytest
from unittest.mock import MagicMock, patch
from app.services.fcm_client import FCMClient


def test_fcm_topic_normalization():
    assert FCMClient.normalize_topic("topic_cybersec") == "topic_cybersec"
    assert FCMClient.normalize_topic("/topics/topic_cybersec") == "topic_cybersec"
    assert FCMClient.normalize_topic(" /topics/topic_ai ") == "topic_ai"


def test_fcm_build_payload_structure():
    client = FCMClient(project_id="test-project")
    payload = client.build_payload(
        topic="topic_cybersec",
        push_punchline="Massive Zero-Day Exposed!",
        article_id="https://example.com/exploit",
        category="cybersec",
        image_url="https://media.zerodaily.in/images/cybersec/hash.webp",
    )

    message = payload["message"]
    assert message["topic"] == "topic_cybersec"
    assert message["notification"]["title"] == "ZeroDaily Breaking"
    assert message["notification"]["body"] == "Massive Zero-Day Exposed!"

    # Data check
    assert message["data"]["article_id"] == "https://example.com/exploit"
    assert message["data"]["category"] == "cybersec"
    assert message["data"]["click_action"] == "FLUTTER_NOTIFICATION_CLICK"

    # Android check
    assert message["android"]["priority"] == "high"
    assert message["android"]["notification"]["channel_id"] == "zerodaily_breaking"
    assert message["android"]["notification"]["image"] == "https://media.zerodaily.in/images/cybersec/hash.webp"

    # APNs check
    assert message["apns"]["payload"]["aps"]["sound"] == "default"


@patch.object(FCMClient, "get_access_token", return_value="fake_test_token")
@patch("httpx.Client.post")
def test_fcm_send_notification(mock_post, mock_token):
    mock_response = MagicMock()
    mock_response.is_error = False
    mock_response.json.return_value = {"name": "projects/test-project/messages/12345"}
    mock_post.return_value = mock_response

    client = FCMClient(project_id="test-project")
    res = client.send_notification(
        topic="topic_ai",
        push_punchline="New Model Shatters Benchmarks",
        article_id="https://example.com/ai-1",
        category="ai",
        image_url="",
    )

    assert res["name"] == "projects/test-project/messages/12345"
    mock_post.assert_called_once()
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer fake_test_token"


@patch.object(FCMClient, "send_notification")
def test_dispatch_breaking_news_targets_both_topics(mock_send):
    mock_send.return_value = {"name": "msg_ok"}
    client = FCMClient(project_id="test-project")

    results = client.dispatch_breaking_news(
        article_id="https://example.com/break",
        category="robotics",
        push_punchline="Humanoid Robots Learn Backflips",
        image_url="",
    )

    assert "topic_robotics" in results
    assert "topic_breaking_all" in results
    assert mock_send.call_count == 2
