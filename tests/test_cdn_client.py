import pytest
from unittest.mock import MagicMock, patch
from app.services.cdn_client import CDNClient


@patch.object(CDNClient, "_load_credentials_from_secrets_manager")
def test_cdn_purge_without_credentials_skips_gracefully(mock_load):
    client = CDNClient(zone_id=None, api_token=None)
    result = client.purge_cache(["https://api.zerodaily.in/api/v1/feed"])
    assert result is False


def test_cdn_purge_empty_list_returns_true():
    client = CDNClient(zone_id="test_zone", api_token="test_token")
    assert client.purge_cache([]) is True


@patch("httpx.Client.post")
def test_cdn_purge_successful_request(mock_post):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.content = b'{"success": true, "result": {"id": "purge_123"}}'
    mock_response.json.return_value = {"success": True, "result": {"id": "purge_123"}}
    mock_post.return_value = mock_response

    client = CDNClient(
        zone_id="abc123zone",
        api_token="secure_token_xyz",
        api_domain="https://api.zerodaily.in",
    )

    success = client.purge_feed_cache(categories=["ai", "cybersec"])

    assert success is True
    assert mock_post.call_count == 1

    call_args = mock_post.call_args
    url = call_args[0][0]
    headers = call_args[1]["headers"]
    json_body = call_args[1]["json"]

    assert url == "https://api.cloudflare.com/client/v4/zones/abc123zone/purge_cache"
    assert headers["Authorization"] == "Bearer secure_token_xyz"
    assert headers["Content-Type"] == "application/json"
    assert set(json_body["files"]) == {
        "https://api.zerodaily.in/api/v1/feed",
        "https://api.zerodaily.in/api/v1/feed/ai",
        "https://api.zerodaily.in/api/v1/feed/cybersec",
    }


@patch("httpx.Client.post")
def test_cdn_purge_batches_urls_above_limit(mock_post):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.content = b'{"success": true}'
    mock_response.json.return_value = {"success": True}
    mock_post.return_value = mock_response

    client = CDNClient(zone_id="test_zone", api_token="test_token")
    
    # 45 URLs should be split into 2 batches (30 + 15)
    urls = [f"https://api.zerodaily.in/api/v1/test/{i}" for i in range(45)]
    success = client.purge_cache(urls)

    assert success is True
    assert mock_post.call_count == 2
    assert len(mock_post.call_args_list[0][1]["json"]["files"]) == 30
    assert len(mock_post.call_args_list[1][1]["json"]["files"]) == 15
