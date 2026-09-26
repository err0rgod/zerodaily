import sys
import os
import argparse
import json
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services.fcm_client import FCMClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_push")


def send_test_push(topic: str, category: str, punchline: str, article_id: str, image_url: str):
    print("=" * 65)
    print("ZeroDaily FCM Push Dispatch Diagnostic")
    print("=" * 65)
    print(f"Target Topic:   {topic}")
    print(f"Category:       {category}")
    print(f"Punchline:      {punchline}")
    print(f"Article ID:     {article_id}")
    print(f"Image URL:      {image_url}")
    print("-" * 65)

    client = FCMClient()

    print("[1/3] Loading service account from AWS Secrets Manager...")
    info = client.get_service_account_info()
    print(f"      Project ID:   {client.project_id}")
    print(f"      Client Email: {info.get('client_email')}")

    print("[2/3] Generating Google OAuth2 Bearer token...")
    token = client.get_access_token()
    print(f"      Token length: {len(token)} characters [OK]")

    print("[3/3] Dispatched payload to FCM HTTP v1 endpoint...")
    payload = client.build_payload(
        topic=topic,
        push_punchline=punchline,
        article_id=article_id,
        category=category,
        image_url=image_url,
    )
    print("--- Payload ---")
    print(json.dumps(payload, indent=2))
    print("---------------")

    response = client.send_notification(
        topic=topic,
        push_punchline=punchline,
        article_id=article_id,
        category=category,
        image_url=image_url,
    )

    print("\n" + "=" * 65)
    print("[SUCCESS] FCM Message Accepted by Google Servers!")
    print(f"Message ID: {response.get('name')}")
    print("=" * 65)
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send a test FCM push notification.")
    parser.add_argument(
        "--topic",
        default="topic_breaking_all",
        help="FCM topic to target (default: topic_breaking_all)",
    )
    parser.add_argument(
        "--category",
        default="ai",
        help="Category for display title and data (default: ai)",
    )
    parser.add_argument(
        "--punchline",
        default="ZeroDaily Test: Push Notification Pipeline Verified 🚀",
        help="Punchline body for notification",
    )
    parser.add_argument(
        "--article-id",
        default="https://zerodaily.in/test-push",
        help="Article ID for deep linking",
    )
    parser.add_argument(
        "--image-url",
        default="https://media.zerodaily.in/images/ai/02e22737315fe005.webp",
        help="Cloudflare CDN WebP image URL",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Broadcast test notification across all topics (topic_breaking_all + all categories)",
    )

    args = parser.parse_args()

    if args.all:
        TOPICS = [
            ("topic_breaking_all", "all"),
            ("topic_cybersec", "cybersec"),
            ("topic_ai", "ai"),
            ("topic_programming", "programming"),
            ("topic_robotics", "robotics"),
            ("topic_defense_aerospace", "defense_aerospace"),
            ("topic_hardware", "hardware"),
            ("topic_finance", "finance"),
        ]
        print(f"Broadcasting test notification to ALL {len(TOPICS)} topics...")
        for topic, cat in TOPICS:
            try:
                send_test_push(
                    topic=topic,
                    category=cat,
                    punchline=args.punchline,
                    article_id=args.article_id,
                    image_url=args.image_url,
                )
            except Exception as e:
                print(f"Failed to send to {topic}: {e}")
    else:
        send_test_push(
            topic=args.topic,
            category=args.category,
            punchline=args.punchline,
            article_id=args.article_id,
            image_url=args.image_url,
        )
