from app.features.seo_tracker.services.cancel_marker import (
    build_scan_canceled_error_message,
    is_scan_canceled_error_message,
    strip_scan_canceled_error_marker,
)
from app.features.seo_tracker.services.client import (
    SerpApiServiceError,
    search_google_nl_desktop,
)
from app.features.seo_tracker.services.domain_matching import (
    extract_hostname,
    matches_domain,
    normalize_website_url,
    to_root_domain,
)
from app.features.seo_tracker.services.limits import apply_scan_limit, clamp_max_requests
from app.features.seo_tracker.services.parser import find_first_domain_match
from app.features.seo_tracker.services.types import SerpMatch
from app.features.seo_tracker.services.validation import normalize_keyword

__all__ = [
    "SerpApiServiceError",
    "SerpMatch",
    "apply_scan_limit",
    "build_scan_canceled_error_message",
    "clamp_max_requests",
    "extract_hostname",
    "find_first_domain_match",
    "is_scan_canceled_error_message",
    "matches_domain",
    "normalize_website_url",
    "search_google_nl_desktop",
    "strip_scan_canceled_error_marker",
    "to_root_domain",
    "normalize_keyword",
]
