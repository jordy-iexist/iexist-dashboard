from app.services.crawler import crawl_website_pages
from app.features.seo_meta.services.types import MetaPageDiscoveryResult
from app.features.seo_meta.services.validation import normalize_path_filters


def discover_website_pages(
    *,
    base_url: str,
    max_pages: int,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    timeout_seconds: float = 15.0,
    crawl_max_depth: int = 2,
    crawl_max_pages: int = 200,
) -> MetaPageDiscoveryResult:
    include_paths_normalized = normalize_path_filters(include_paths or [])
    exclude_paths_normalized = normalize_path_filters(exclude_paths or [])

    result = crawl_website_pages(
        base_url=base_url,
        max_pages=max_pages,
        include_paths=include_paths_normalized,
        exclude_paths=exclude_paths_normalized,
        timeout_seconds=timeout_seconds,
        crawl_max_depth=crawl_max_depth,
        crawl_max_pages=crawl_max_pages,
    )

    return MetaPageDiscoveryResult(
        urls=result.urls,
        skipped_due_to_limit=result.skipped_due_to_limit,
        source=result.source,
    )
