# ZeroDaily Mobile Notifications Specification & Client Contract

This document provides the mobile engineering team (Flutter / React Native / iOS / Android) with the exact contract for integrating Firebase Cloud Messaging (FCM) topic-based notifications for ZeroDaily breaking news.

---

## 1. Architectural Philosophy: Zero Server Token Management

ZeroDaily uses **FCM Topic-Based Messaging**. 
- **No Device Token Database:** The backend does **not** store or manage individual APNs or FCM device tokens.
- **Client-Managed Subscriptions:** The mobile client subscribes and unsubscribes directly to FCM topics on the device using the Firebase SDK.
- **Instant Broadcast:** When breaking news is detected, the server dispatches a single message to the topic, and Firebase handles distribution to millions of devices with sub-second latency.

---

## 2. Topic Naming Conventions

All topics follow the lower-case naming convention:

| Category / Alert Type | FCM Topic String | Description |
| :--- | :--- | :--- |
| **All Breaking (Catch-All)** | `topic_breaking_all` | Dispatched on any critical news item across all domains. |
| **Cybersecurity** | `topic_cybersec` | Zero-days, critical vulnerabilities, high-profile breach alerts. |
| **Artificial Intelligence** | `topic_ai` | Major foundation model releases, benchmark disruptions, AI safety debacles. |
| **Software Engineering** | `topic_programming` | Critical language changes, kernel releases, infrastructure outages. |
| **Robotics & Automation** | `topic_robotics` | Humanoid milestones, major industrial automation breakthroughs. |
| **Defense & Aerospace** | `topic_defense_aerospace`| Satellite launches, hypersonic updates, defense technology events. |
| **Hardware & Silicon** | `topic_hardware` | GPU shortages, architectural tape-outs, semiconductor advances. |
| **Finance & Markets** | `topic_finance` | Quant glitches, crypto debacles, venture capital, and market panics. |

---

## 3. Client Subscription Protocol

### When to Subscribe
1. **First App Launch / Permission Granted:**
   - Prompt the user for notification permissions.
   - If granted, subscribe by default to `topic_breaking_all` (or whichever default your onboarding selects).
2. **Category Toggle in Settings:**
   - When a user flips the toggle for a category (e.g. *Cybersecurity* ON):
     - Call `FirebaseMessaging.instance.subscribeToTopic('topic_cybersec')`.
   - When a user flips the toggle OFF:
     - Call `FirebaseMessaging.instance.unsubscribeFromTopic('topic_cybersec')`.

### Flutter Integration Example
```dart
import 'package:firebase_messaging/firebase_messaging.dart';

class NotificationService {
  static final FirebaseMessaging _fcm = FirebaseMessaging.instance;

  static Future<void> updateCategoryPreference(String categoryKey, bool isEnabled) async {
    final topic = 'topic_$categoryKey';
    if (isEnabled) {
      await _fcm.subscribeToTopic(topic);
    } else {
      await _fcm.unsubscribeFromTopic(topic);
    }
  }

  static Future<void> updateAllBreakingPreference(bool isEnabled) async {
    const topic = 'topic_breaking_all';
    if (isEnabled) {
      await _fcm.subscribeToTopic(topic);
    } else {
      await _fcm.unsubscribeFromTopic(topic);
    }
  }
}
```

---

## 4. Inbound Notification Payload Contract

The backend sends the following standardized JSON payload conforming to FCM HTTP v1:

```json
{
  "message": {
    "topic": "topic_finance",
    "notification": {
      "title": "ZeroDaily Breaking • Finance",
      "body": "Algo Liquidation Cascade Wipes $40B in Flash Crash"
    },
    "data": {
      "article_id": "https://example.com/finance-crash",
      "category": "finance",
      "image_url": "https://media.zerodaily.in/images/finance/a1b2c3d4.webp",
      "push_punchline": "Algo Liquidation Cascade Wipes $40B in Flash Crash",
      "click_action": "FLUTTER_NOTIFICATION_CLICK"
    },
    "android": {
      "priority": "high",
      "notification": {
        "channel_id": "zerodaily_breaking",
        "image": "https://media.zerodaily.in/images/finance/a1b2c3d4.webp"
      }
    },
    "apns": {
      "payload": {
        "aps": {
          "sound": "default"
        }
      }
    }
  }
}
```

### Key Data Fields:
- `article_id`: Canonical URL ID. Use this to open the article card directly in the app swiper.
- `category`: The category key to highlight the active tab.
- `image_url`: CDN WebP image URL. Rendered in expanded Android / iOS push previews.
- `push_punchline`: Short punchline string sent in the push notification alert.
- `channel_id`: Android notification channel `zerodaily_breaking` (ensure your app creates this notification channel on startup).

---

## 5. Notification History API

To populate a "Recent Alerts" or "Notification Bell" inbox inside the mobile app without relying solely on local device push history:

- **Endpoint:** `GET https://api.zerodaily.in/api/v1/notifications/history?limit=20`
- **Response Format:**
```json
{
  "status": "success",
  "data": [
    {
      "article_id": "https://example.com/sample-breaking",
      "category": "cybersec",
      "heading": "Kernel Bug Crashes Global Infrastructure",
      "push_punchline": "Kernel Bug Crashes Global Infrastructure",
      "image_url": "https://media.zerodaily.in/images/cybersec/a1b2c3d4.webp",
      "published_at": "2026-09-16T10:00:00Z"
    }
  ],
  "count": 1
}
```
