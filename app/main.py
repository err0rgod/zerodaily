import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.config import get_settings
from app.middleware import SecurityHeadersMiddleware
from app.routers import meta, feed, articles, notifications, auth

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

# 1. Defense-in-depth Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# 2. CORS Configuration - Restrict to read-only methods
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
)

# 3. Global Exception Handler (Prevents stack trace / infrastructure info leakage)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error processing '{request.method} {request.url.path}': {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "message": "An internal server error occurred. Please try again later."
        },
        headers={"Cache-Control": "no-store"}
    )

# 4. Register Routers
app.include_router(meta.router)
app.include_router(feed.router)
app.include_router(articles.router)
app.include_router(notifications.router)
app.include_router(auth.router)


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
