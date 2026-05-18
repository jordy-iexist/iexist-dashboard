from dataclasses import dataclass


@dataclass
class SerpMatch:
    position: int | None
    result_url: str | None
    matched_host: str | None
