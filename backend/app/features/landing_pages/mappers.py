from typing import Any


def extract_landing_page_context(
    landing_page_row_data: dict[str, Any] | None,
    filename: str | None,
    job_status: str | None,
) -> tuple[str, str, str]:
    """Returns (onderwerp, filename, status)."""
    onderwerp = ""
    if isinstance(landing_page_row_data, dict):
        onderwerp = str(landing_page_row_data.get("onderwerp", "") or "")
    return (
        onderwerp,
        str(filename or "Onbekend bestand"),
        str(job_status or "pending"),
    )
