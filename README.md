# ZeroDaily Serving API & Notification Worker (`api.zerodaily.in`)

[![Tests](https://img.shields.io/badge/tests-21%20passed-success)](tests/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-blue.svg)](https://fastapi.tiangolo.com)
[![AWS](https://img.shields.io/badge/AWS-DynamoDB%20%7C%20Lambda%20%7C%20S3-orange.svg)](https://aws.amazon.com)
[![Cloudflare](https://img.shields.io/badge/Cloudflare-Edge%20Cache-F38020.svg)](https://cloudflare.com)
[![FCM](https://img.shields.io/badge/FCM-HTTP%20v1%20Topics-FFCA28.svg)](https://firebase.google.com/docs/cloud-messaging)

The high-performance serving layer and push notification engine for **ZeroDaily** — an automated, satirical tech news platform delivering curated, roasted summaries across 6 tech domains.

---

## Architecture Overview

ZeroDaily operates on a decoupled Producer/Consumer architecture:

```
[ Ingestion Pipeline (Producer) ]
  D:/bot1 (Scraper + Bedrock DeepSeek + Pillow WebP)
    ↳ Writes articles to DynamoDB ("zerodaily-articles")
    ↳ Uploads 800px WebP images to S3 ("zerodaily-article-images")

                   │
                   ▼
       [ Amazon DynamoDB: zerodaily-articles ]
          │                               │
          ▼ (DynamoDB Streams)            ▼ (GSI Queries)
[ Stream Notification Worker ]     [ FastAPI Serving API ]
  (workers/stream_handler.py)        (app/main.py + Mangum)
    ↳ Filter is_breaking == True      ↳ Global & Category Feeds
    ↳ 30-min Atomic Cooldown          ↳ Single Article Lookup
    ↳ FCM HTTP v1 Topic Dispatch      ↳ Cloudflare Edge Caching
          │                               │
          ▼                               ▼
 [ Firebase Cloud Messaging ]     [ Cloudflare CDN: api.zerodaily.in ]
          │                               │
          └───────────────┬───────────────┘
                          ▼
            [ ZeroDaily Mobile App ]
           (Offline-first SQLite/Hive)
```

---

## Key Features

- **Blazing Fast Serving Layer**: Powered by FastAPI and wrapped with [Mangum](file:///D:/zerodaily/app/main.py) for serverless deployment on AWS Lambda.
- **Edge CDN Optimization**: Emits tuned `Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=600` headers. Cloudflare serves requests globally in **10–20ms**.
- **Cursor-Based Pagination**: Clean chronologically sorted feed queries against DynamoDB GSIs (`GlobalFeedIndex` and `CategoryIndex`) using ISO-8601 UTC timestamps.
- **Event-Driven Push Notifications**: AWS Lambda worker listening to DynamoDB Streams (`INSERT` events) for breaking news.
- **Atomic 30-Minute Cooldown**: DynamoDB conditional writes enforce a 30-minute anti-spam cooldown per category with TTL expiration — **zero Redis or external infrastructure needed**.
- **Zero-Database Device Management**: Uses Firebase Cloud Messaging (FCM) HTTP v1 **topic subscriptions** (`topic_{category}` and `topic_breaking_all`).

---

## Supported Categories

| Key | Name | Focus |
| :--- | :--- | :--- |
| `cybersec` | Cybersecurity & Threat Intel | Zero-days, critical CVEs, data breaches |
| `ai` | Artificial Intelligence | LLMs, benchmark wars, frontier agents |
| `programming` | Software Engineering | Languages, runtimes, developer tooling |
| `robotics` | Robotics & Automation | Humanoids, industrial automation, autonomy |
| `defense_aerospace` | Defense & Aerospace | Hypersonics, satellite swarms, defense tech |
| `hardware` | Hardware & Semiconductors | Silicon fabrication, GPUs, quantum chips |

---

## Directory Layout

```text
zerodaily/
├── app/
│   ├── config.py                 # Pydantic BaseSettings & environment variables
│   ├── db.py                     # Boto3 DynamoDB query service for GSIs & tables
│   ├── main.py                   # FastAPI app, CORS, and Mangum Lambda adapter
│   ├── schemas.py                # Strict Pydantic contracts for API & alerts
│   ├── routers/
│   │   ├── articles.py           # GET /api/v1/articles/{id:path} & /api/v1/article
│   │   ├── feed.py               # GET /api/v1/feed & /api/v1/feed/{category}
│   │   ├── meta.py               # GET /health & GET /api/v1/categories
│   │   └── notifications.py      # GET /api/v1/notifications/history
│   └── services/
│       ├── cooldown.py           # Atomic DynamoDB 30-min rate-limiting lock
│       └── fcm_client.py         # FCM HTTP v1 OAuth2 client & payload builder
├── docs/
│   └── MOBILE_NOTIFICATIONS.md   # Mobile client integration & subscription protocol
├── workers/
│   └── stream_handler.py         # AWS Lambda handler for DynamoDB Streams
├── tests/
│   ├── test_api.py               # API route, pagination, and header tests
│   ├── test_cooldown.py          # Atomic cooldown & conditional lock tests
│   ├── test_fcm_dispatch.py      # FCM payload construction & dispatch tests
│   └── test_stream_handler.py    # DynamoDB Stream record filter & parsing tests
├── Docs.md                       # Comprehensive architectural & API reference manual
├── requirements.txt              # Project dependencies
└── .env.example                  # Environment configuration template
```

---

## Quick Start

### 1. Prerequisites
- Python 3.10+
- AWS credentials with read permissions for DynamoDB table `zerodaily-articles`

### 2. Setup Virtual Environment
```bash
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy [.env.example](file:///D:/zerodaily/.env.example) to `.env`:
```bash
cp .env.example .env
```

Adjust settings in `.env`:
```ini
AWS_REGION=us-east-1
DYNAMODB_TABLE_NAME=zerodaily-articles
FIREBASE_PROJECT_ID=zerodaily-prod
FIREBASE_SERVICE_ACCOUNT_JSON=path/to/service-account.json
NOTIFICATION_COOLDOWN_MINUTES=30
```

### 4. Run the Development Server
```bash
uvicorn app.main:app --reload --port 8000
```
- Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Alternative ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Running Unit Tests

Run the complete test suite:
```bash
pytest -v
```

All 21 tests cover:
- FastAPI endpoints, status codes, and HTTP cache headers.
- DynamoDB Stream event parsing and `is_breaking` filtering.
- DynamoDB conditional write rate-limiting / cooldown locks.
- FCM HTTP v1 message structure, topic routing, and multi-topic dispatch.

---

## Deployment & Cloudflare Setup

For complete deployment instructions, IAM policies, and Cloudflare CNAME caching rules, see [Docs.md](file:///D:/zerodaily/Docs.md).
