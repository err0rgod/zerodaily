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
    assert message["notification"]["title"] == "ZeroDaily Breaking • Cybersec"
    assert message["notification"]["body"] == "Massive Zero-Day Exposed!"

    # Data check
    assert message["data"]["article_id"] == "https://example.com/exploit"
    assert message["data"]["category"] == "cybersec"
    assert message["data"]["push_punchline"] == "Massive Zero-Day Exposed!"
    assert message["data"]["click_action"] == "FLUTTER_NOTIFICATION_CLICK"

    # Android check
    assert message["android"]["priority"] == "high"
    assert message["android"]["notification"]["channel_id"] == "zerodaily_breaking"
    assert message["android"]["notification"]["image"] == "https://media.zerodaily.in/images/cybersec/hash.webp"

    # APNs check
    assert message["apns"]["payload"]["aps"]["sound"] == "default"


def test_fcm_build_payload_structure_finance():
    client = FCMClient(project_id="test-project")
    payload = client.build_payload(
        topic="topic_finance",
        push_punchline="Markets Tumble After Algo Flash Crash",
        article_id="https://example.com/finance-crash",
        category="finance",
        image_url="https://media.zerodaily.in/images/finance/f1.webp",
    )

    message = payload["message"]
    assert message["topic"] == "topic_finance"
    assert message["notification"]["title"] == "ZeroDaily Breaking • Finance"
    assert message["notification"]["body"] == "Markets Tumble After Algo Flash Crash"
    assert message["data"]["article_id"] == "https://example.com/finance-crash"
    assert message["data"]["category"] == "finance"
    assert message["data"]["image_url"] == "https://media.zerodaily.in/images/finance/f1.webp"
    assert message["data"]["push_punchline"] == "Markets Tumble After Algo Flash Crash"
    assert message["data"]["click_action"] == "FLUTTER_NOTIFICATION_CLICK"
    assert message["android"]["priority"] == "high"
    assert message["android"]["notification"]["channel_id"] == "zerodaily_breaking"
    assert message["android"]["notification"]["image"] == "https://media.zerodaily.in/images/finance/f1.webp"
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
def test_dispatch_breaking_news_targets_category_topics(mock_send):
    mock_send.return_value = {"name": "msg_ok"}
    client = FCMClient(project_id="test-project")

    results = client.dispatch_breaking_news(
        article_id="https://example.com/break",
        category="robotics",
        push_punchline="Humanoid Robots Learn Backflips",
        image_url="",
    )

    assert "topic_robotics" in results
    assert "topic_breaking_all" not in results
    assert mock_send.call_count == 1
    assert mock_send.call_args[1]["topic"] == "topic_robotics"


@patch.object(FCMClient, "send_notification")
def test_dispatch_breaking_news_finance_targets_category_topics(mock_send):
    mock_send.return_value = {"name": "msg_ok"}
    client = FCMClient(project_id="test-project")

    results = client.dispatch_breaking_news(
        article_id="https://example.com/finance-flash",
        category="finance",
        push_punchline="Major Bank AI Trading Model Goes Rogue",
        image_url="https://media.zerodaily.in/images/finance/f2.webp",
    )

    assert "topic_finance" in results
    assert "topic_breaking_all" not in results
    assert mock_send.call_count == 1
    assert mock_send.call_args[1]["topic"] == "topic_finance"

    
