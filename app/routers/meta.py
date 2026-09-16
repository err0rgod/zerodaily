from datetime import datetime, timezone
from fastapi import APIRouter, Response
from app.config import get_settings
from app.schemas import HealthResponse, CategoryListResponse, Category

router = APIRouter(tags=["Metadata & System"])

CATEGORIES = [
    Category(
        key="cybersec",
        name="Cybersecurity & Threat Intel",
        description="Zero-days, breach debacles, and security failures."
    ),
    Category(
        key="ai",
        name="Artificial Intelligence",
        description="LLMs, benchmark wars, and autonomous agents."
    ),
    Category(
        key="programming",
        name="Software Engineering",
        description="Languages, tools, and developer culture."
    ),
    Category(
        key="robotics",
        name="Robotics & Automation",
        description="Humanoids, industrial automation, and robotic systems."
    ),
    Category(
        key="defense_aerospace",
        name="Defense & Aerospace",
        description="Hypersonics, satellite swarms, and defense tech."
    ),
    Category(
        key="hardware",
        name="Hardware & Semiconductors",
        description="Silicon, GPUs, fabrication, and quantum chips."
    ),
]


@router.get("/health", response_model=HealthResponse)
def health_check(response: Response) -> HealthResponse:
    """Diagnostic health check verifying API operational status."""
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service="zerodaily-api",
        region=settings.AWS_REGION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api/v1/categories", response_model=CategoryListResponse)
def get_categories(response: Response) -> CategoryListResponse:
    """Returns active content categories with descriptions."""
    response.headers["Cache-Control"] = "public, max-age=86400"
    return CategoryListResponse(
        status="success",
        categories=CATEGORIES
    )
