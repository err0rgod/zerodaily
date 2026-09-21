import json
import logging
import os
import time
from typing import Dict, Any, Optional, List
import httpx
from google.oauth2 import service_account
import google.auth.transport.requests
import boto3
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger("zerodaily.fcm")
logger.setLevel(logging.INFO)

FCM_SEND_URL_TEMPLATE = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


CATEGORY_DISPLAY_MAP = {
    "cybersec": "Cybersec",
    "ai": "AI",
    "programming": "Programming",
    "robotics": "Robotics",
    "defense_aerospace": "Defense & Aerospace",
    "hardware": "Hardware",
    "finance": "Finance",
}


class FCMClient:
    """
    Client for Firebase Cloud Messaging (FCM) using HTTP v1 API.
    Supports OAuth2 credentials via JSON string, file path, or AWS Secrets Manager.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        service_account_info: Optional[Dict[str, Any]] = None,
    ):
        settings = get_settings()
        self.project_id = project_id or settings.FIREBASE_PROJECT_ID
        self._service_account_info = service_account_info
        self._credentials: Optional[service_account.Credentials] = None
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    def _load_credentials_from_secrets_manager(self, secret_name: str, region: str) -> Dict[str, Any]:
        """Fetch credentials from AWS Secrets Manager."""
        client = boto3.client("secretsmanager", region_name=region)
        try:
            response = client.get_secret_value(SecretId=secret_name)
            secret_string = response.get("SecretString")
            if secret_string:
                return json.loads(secret_string)
            raise ValueError(f"Secret '{secret_name}' has no SecretString content")
        except ClientError as e:
            logger.error(f"Failed to retrieve Firebase secret '{secret_name}' from Secrets Manager: {e}")
            raise

    def get_service_account_info(self) -> Dict[str, Any]:
        """Loads and caches service account credentials from available sources."""
        if self._service_account_info:
            return self._service_account_info

        settings = get_settings()

        # 1. Check AWS Secrets Manager if configured
        if settings.FIREBASE_SECRET_NAME:
            info = self._load_credentials_from_secrets_manager(
                settings.FIREBASE_SECRET_NAME, settings.AWS_REGION
            )
            self._service_account_info = info
            if not self.project_id and "project_id" in info:
                self.project_id = info["project_id"]
            return info

        # 2. Check environment variable / config
        raw_json_or_path = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        if raw_json_or_path:
            raw_str = raw_json_or_path.strip()
            if os.path.exists(raw_str):
                with open(raw_str, "r", encoding="utf-8") as f:
                    info = json.load(f)
            else:
                info = json.loads(raw_str)

            self._service_account_info = info
            if not self.project_id and "project_id" in info:
                self.project_id = info["project_id"]
            return info

        raise ValueError(
            "Firebase credentials not found. Provide FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_SECRET_NAME."
        )

    def get_access_token(self) -> str:
        """Retrieves and caches a valid Google OAuth2 Bearer token."""
        now = time.time()
        # Refresh if token expires within 60 seconds
        if self._access_token and self._token_expiry > now + 60:
            return self._access_token

        info = self.get_service_account_info()
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)

        self._credentials = creds
        self._access_token = creds.token
        # creds.expiry is a datetime UTC object
        if creds.expiry:
            self._token_expiry = creds.expiry.timestamp()
        else:
            self._token_expiry = now + 3500

        return self._access_token

    @staticmethod
    def normalize_topic(topic_name: str) -> str:
        """Ensures topic name does not contain leading '/topics/'."""
        cleaned = topic_name.strip()
        if cleaned.startswith("/topics/"):
            cleaned = cleaned[len("/topics/"):]
        return cleaned

    @staticmethod
    def get_category_display_title(category: str) -> str:
        """Formats the notification title with the display name of the category."""
        if not category:
            return "ZeroDaily Breaking"
        cleaned = category.strip().lower()
        display_name = CATEGORY_DISPLAY_MAP.get(cleaned, cleaned.replace("_", " ").title())
        return f"ZeroDaily Breaking • {display_name}"

    def build_payload(
        self,
        topic: str,
        push_punchline: str,
        article_id: str,
        category: str,
        image_url: str,
    ) -> Dict[str, Any]:
        """Constructs the standard FCM HTTP v1 message structure."""
        clean_topic = self.normalize_topic(topic)
        title = self.get_category_display_title(category)
        return {
            "message": {
                "topic": clean_topic,
                "notification": {
                    "title": title,
                    "body": push_punchline,
                },
                "data": {
                    "article_id": article_id,
                    "category": category,
                    "image_url": image_url,
                    "push_punchline": push_punchline,
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                },
                "android": {
                    "priority": "high",
                    "notification": {
                        "channel_id": "zerodaily_breaking",
                        "image": image_url,
                    },
                },
                "apns": {
                    "payload": {
                        "aps": {
                            "sound": "default",
                        },
                    },
                },
            }
        }

    def send_notification(
        self,
        topic: str,
        push_punchline: str,
        article_id: str,
        category: str,
        image_url: str,
    ) -> Dict[str, Any]:
        """Dispatches an FCM message to the specified topic."""
        token = self.get_access_token()
        if not self.project_id:
            info = self.get_service_account_info()
            self.project_id = info.get("project_id")

        url = FCM_SEND_URL_TEMPLATE.format(project_id=self.project_id)
        payload = self.build_payload(
            topic=topic,
            push_punchline=push_punchline,
            article_id=article_id,
            category=category,
            image_url=image_url,
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; UTF-8",
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.is_error:
                logger.error(
                    f"FCM send failure (Status: {response.status_code}) to topic '{topic}': {response.text}"
                )
                response.raise_for_status()

            res_json = response.json()
            logger.info(f"FCM notification successfully dispatched to topic '{topic}'. Message ID: {res_json.get('name')}")
            return res_json

    def dispatch_breaking_news(
        self,
        article_id: str,
        category: str,
        push_punchline: str,
        image_url: str,
    ) -> Dict[str, Any]:
        """
        Dispatches to:
        1. Category topic: topic_{category}
        2. Catch-all topic: topic_breaking_all (if enabled)
        """
        settings = get_settings()
        clean_cat = category.strip().lower()
        cat_topic = f"topic_{clean_cat}"
        results = {}

        # 1. Category topic dispatch
        try:
            results[cat_topic] = self.send_notification(
                topic=cat_topic,
                push_punchline=push_punchline,
                article_id=article_id,
                category=clean_cat,
                image_url=image_url,
            )
        except Exception as e:
            logger.error(f"Failed sending breaking push to category topic '{cat_topic}': {e}")
            results[cat_topic] = {"error": str(e)}

        # 2. Catch-all topic dispatch
        if settings.ENABLE_ALL_BREAKING_TOPIC:
            all_topic = "topic_breaking_all"
            try:
                results[all_topic] = self.send_notification(
                    topic=all_topic,
                    push_punchline=push_punchline,
                    article_id=article_id,
                    category=clean_cat,
                    image_url=image_url,
                )
            except Exception as e:
                logger.error(f"Failed sending breaking push to catch-all topic '{all_topic}': {e}")
                results[all_topic] = {"error": str(e)}

        return results

    def subscribe_token_to_topics(self, token: str, topics: List[str]) -> List[str]:
        """
        Subscribes a device registration token to one or more FCM topics
        via the Google Instance ID batchAdd API.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "access_token_auth": "true",
            "Content-Type": "application/json; UTF-8",
        }
        url = "https://iid.googleapis.com/iid/v1:batchAdd"
        successful = []

        with httpx.Client(timeout=10.0) as client:
            for topic in topics:
                clean_topic = self.normalize_topic(topic)
                payload = {
                    "to": f"/topics/{clean_topic}",
                    "registration_tokens": [token.strip()],
                }
                try:
                    res = client.post(url, headers=headers, json=payload)
                    if res.is_success:
                        successful.append(clean_topic)
                        logger.info(f"Subscribed token to topic '{clean_topic}' successfully.")
                    else:
                        logger.warning(f"Failed subscribing token to topic '{clean_topic}': {res.status_code} {res.text}")
                except Exception as e:
                    logger.error(f"Error subscribing token to topic '{clean_topic}': {e}")

        return successful

    def unsubscribe_token_from_topics(self, token: str, topics: List[str]) -> List[str]:
        """
        Unsubscribes a device registration token from one or more FCM topics
        via the Google Instance ID batchRemove API.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "access_token_auth": "true",
            "Content-Type": "application/json; UTF-8",
        }
        url = "https://iid.googleapis.com/iid/v1:batchRemove"
        successful = []

        with httpx.Client(timeout=10.0) as client:
            for topic in topics:
                clean_topic = self.normalize_topic(topic)
                payload = {
                    "to": f"/topics/{clean_topic}",
                    "registration_tokens": [token.strip()],
                }
                try:
                    res = client.post(url, headers=headers, json=payload)
                    if res.is_success:
                        successful.append(clean_topic)
                        logger.info(f"Unsubscribed token from topic '{clean_topic}' successfully.")
                    else:
                        logger.warning(f"Failed unsubscribing token from topic '{clean_topic}': {res.status_code} {res.text}")
                except Exception as e:
                    logger.error(f"Error unsubscribing token from topic '{clean_topic}': {e}")

        return successful
