"""Pipeline configuration and environment settings."""

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env from current directory or parent directory
load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class PipelineConfig(BaseModel):
    # Pipeline Dedicated Database (Staging, Queue, Scrape Logs)
    pipeline_db_url: str = Field(
        default_factory=lambda: os.getenv("TURSO_PIPELINE_DB_URL", "")
    )
    pipeline_db_token: str = Field(
        default_factory=lambda: os.getenv("TURSO_PIPELINE_DB_TOKEN", "")
    )

    # Production Database (Catalog, Verified Bank, Verifications)
    prod_db_url: str = Field(
        default_factory=lambda: os.getenv("TURSO_PROD_DB_URL", os.getenv("TURSO_DB_URL", ""))
    )
    prod_db_token: str = Field(
        default_factory=lambda: os.getenv("TURSO_PROD_DB_TOKEN", os.getenv("TURSO_DB_TOKEN", ""))
    )

    # Media & Asset Cache
    media_cache_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("MEDIA_CACHE_DIR", ".pipeline_cache/media"))
    )

    # AI Models
    opencode_text_model: str = Field(
        default_factory=lambda: os.getenv("OPENCODE_TEXT_MODEL", "opencode/space-bunny-free")
    )
    opencode_vision_model: str = Field(
        default_factory=lambda: os.getenv("OPENCODE_VISION_MODEL", "opencode/muse-spark-1.3-contributor-free")
    )

    # Worker Settings
    default_concurrency: int = Field(
        default_factory=lambda: int(os.getenv("DEFAULT_CONCURRENCY", "4"))
    )
    request_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30.0"))
    )
    ai_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("AI_TIMEOUT_SECONDS", "120.0"))
    )


config = PipelineConfig()
