import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from app.services.cooldown import NotificationCooldownManager


@patch("boto3.resource")
def test_cooldown_permits_when_no_active_lock(mock_boto_resource):
    mock_table = MagicMock()
    mock_boto_resource.return_value.Table.return_value = mock_table

    # put_item succeeds (no exception)
    mock_table.put_item.return_value = {}

    manager = NotificationCooldownManager(table_name="zerodaily-articles", region_name="us-east-1")
    allowed = manager.acquire_push_permission("cybersec", "https://example.com/1", cooldown_minutes=30)

    assert allowed is True
    mock_table.put_item.assert_called_once()
    item_arg = mock_table.put_item.call_args[1]["Item"]
    assert item_arg["id"] == "NOTIF_COOLDOWN#cybersec"
    assert item_arg["category"] == "cybersec"
    assert item_arg["last_article_id"] == "https://example.com/1"


@patch("boto3.resource")
def test_cooldown_rejects_when_conditional_check_fails(mock_boto_resource):
    mock_table = MagicMock()
    mock_boto_resource.return_value.Table.return_value = mock_table

    # Simulate ConditionalCheckFailedException
    error_response = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Condition check failed"}}
    mock_table.put_item.side_effect = ClientError(error_response, "PutItem")

    manager = NotificationCooldownManager(table_name="zerodaily-articles", region_name="us-east-1")
    allowed = manager.acquire_push_permission("cybersec", "https://example.com/2", cooldown_minutes=30)

    assert allowed is False
