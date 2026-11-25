from typing import Any

from app.features.agency_overview.schemas import OverviewResponse


def to_overview(data: dict[str, Any]) -> OverviewResponse:
    """Het dict van `build_overview` als antwoordmodel."""
    return OverviewResponse.model_validate(data)
