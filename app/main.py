import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.config import get_settings
from app.routers import meta, feed, articles, notifications

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zerodaily.api")

settings = get_settings()

app = FastAPI(
    title="ZeroDaily Serving API",
    description="High-performance backend serving roasted tech news feeds and breaking alerts.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(meta.router)
app.include_router(feed.router)
app.include_router(articles.router)
app.include_router(notifications.router)


@app.get("/")
def root():
    return {
        "service": "ZeroDaily API",
        "documentation": "/docs",
        "version": "1.0.0"
    }


# AWS Lambda entrypoint adapter
handler = Mangum(app, lifespan="off")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
