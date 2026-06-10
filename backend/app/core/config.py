from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PRIMARY_ENV_FILE = BASE_DIR / ".env"
FALLBACK_ENV_FILE = BASE_DIR / ".env.example"
ENV_FILE = PRIMARY_ENV_FILE if PRIMARY_ENV_FILE.exists() else FALLBACK_ENV_FILE


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/csv_blog_generator",
        validation_alias="DATABASE_URL",
    )
    postgrest_url: str = Field(
        default="http://localhost:3001",
        validation_alias="POSTGREST_URL",
    )
    postgrest_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="POSTGREST_TIMEOUT_SECONDS",
    )
    jwt_secret_key: str = Field(
        default="",
        validation_alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=60 * 24,
        validation_alias=AliasChoices(
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "JWT_ACCESS_TOKEN_EXPIRES_MINUTES",
        ),
    )
    jwt_refresh_token_expires_days: int = Field(
        default=30,
        validation_alias="JWT_REFRESH_TOKEN_EXPIRES_DAYS",
    )
    backend_public_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("BACKEND_PUBLIC_URL", "MEDIA_BASE_URL"),
    )
    storage_root: str = Field(
        default=str(BASE_DIR / "media"),
        validation_alias=AliasChoices("STORAGE_ROOT", "MEDIA_ROOT"),
    )
    storage_signing_secret: str = Field(
        default="",
        validation_alias="STORAGE_SIGNING_SECRET",
    )
    cors_allowed_origins: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )
    openai_api_key: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="REDIS_URL"
    )
    worker_concurrency: int = Field(default=1, validation_alias="WORKER_CONCURRENCY")
    wordpress_credentials_key: str = Field(
        default="",
        validation_alias="WORDPRESS_CREDENTIALS_KEY",
    )
    wordpress_request_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="WORDPRESS_REQUEST_TIMEOUT_SECONDS",
    )
    blog_images_bucket: str = Field(
        default="blog-images",
        validation_alias="BLOG_IMAGES_BUCKET",
    )
    blog_image_max_size_bytes: int = Field(
        default=5 * 1024 * 1024,
        validation_alias="BLOG_IMAGE_MAX_SIZE_BYTES",
    )
    blog_image_signed_url_ttl_seconds: int = Field(
        default=3600,
        validation_alias="BLOG_IMAGE_SIGNED_URL_TTL_SECONDS",
    )
    openai_image_model: str = Field(
        default="gpt-image-1",
        validation_alias="OPENAI_IMAGE_MODEL",
    )
    openai_image_responses_model: str = Field(
        default="gpt-5",
        validation_alias="OPENAI_IMAGE_RESPONSES_MODEL",
    )
    openai_image_size: str = Field(
        default="1024x1024",
        validation_alias="OPENAI_IMAGE_SIZE",
    )
    serpapi_api_key: str = Field(
        default="",
        validation_alias="SERPAPI_API_KEY",
    )
    serpapi_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="SERPAPI_TIMEOUT_SECONDS",
    )
    serpapi_results_depth: int = Field(
        default=20,
        ge=1,
        le=100,
        validation_alias="SERPAPI_RESULTS_DEPTH",
    )
    serpapi_max_requests_per_scan: int = Field(
        default=25,
        ge=1,
        validation_alias="SERPAPI_MAX_REQUESTS_PER_SCAN",
    )
    seo_meta_max_pages_per_run: int = Field(
        default=50,
        ge=1,
        le=500,
        validation_alias="SEO_META_MAX_PAGES_PER_RUN",
    )
    seo_meta_http_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="SEO_META_HTTP_TIMEOUT_SECONDS",
    )
    seo_meta_crawl_max_depth: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias="SEO_META_CRAWL_MAX_DEPTH",
    )
    seo_meta_crawl_max_pages: int = Field(
        default=200,
        ge=1,
        le=1000,
        validation_alias="SEO_META_CRAWL_MAX_PAGES",
    )
    seo_meta_title_max_chars: int = Field(
        default=60,
        ge=20,
        le=120,
        validation_alias="SEO_META_TITLE_MAX_CHARS",
    )
    seo_meta_description_max_chars: int = Field(
        default=160,
        ge=50,
        le=320,
        validation_alias="SEO_META_DESCRIPTION_MAX_CHARS",
    )
    seo_meta_openai_model: str = Field(
        default="gpt-5.2",
        validation_alias="SEO_META_OPENAI_MODEL",
    )
    openai_blog_model: str = Field(
        default="gpt-5.4",
        validation_alias="OPENAI_BLOG_MODEL",
    )
    openai_blog_reasoning_effort: str = Field(
        default="high",
        validation_alias="OPENAI_BLOG_REASONING_EFFORT",
    )
    openai_seo_meta_reasoning_effort: str = Field(
        default="low",
        validation_alias="OPENAI_SEO_META_REASONING_EFFORT",
    )

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        ] or ["http://localhost:3000"]


_INSECURE_SECRET_VALUES = {
    "",
    "change-me",
    "change-me-in-production",
    "change-me-storage-secret",
}


def validate_required_secrets(s: "Settings") -> None:
    problems: list[str] = []
    if s.jwt_secret_key.strip() in _INSECURE_SECRET_VALUES:
        problems.append("JWT_SECRET_KEY")
    if s.storage_signing_secret.strip() in _INSECURE_SECRET_VALUES:
        problems.append("STORAGE_SIGNING_SECRET")
    if problems:
        raise RuntimeError(
            "Onveilige of ontbrekende secrets: "
            + ", ".join(problems)
            + ". Zet deze env-vars in backend/.env (genereer met: openssl rand -hex 32)."
        )


settings = Settings()

__all__ = ["Settings", "settings", "validate_required_secrets"]
