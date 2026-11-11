from typing import Any

from app.features.launch_checklist.schemas import (
    LaunchScanDetail,
    LaunchScanIssueItem,
    LaunchScanItem,
    LaunchScanPageItem,
)
from app.features.launch_checklist.services.issues import ISSUE_TYPES


def row_to_dict(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def to_scan_item(row: Any) -> LaunchScanItem:
    return LaunchScanItem.model_validate(row_to_dict(row))


def to_scan_detail(row: Any) -> LaunchScanDetail:
    return LaunchScanDetail.model_validate(row_to_dict(row))


def to_page_item(row: Any, issue_count: int = 0) -> LaunchScanPageItem:
    return LaunchScanPageItem.model_validate({**row_to_dict(row), "issue_count": issue_count})


def to_issue_item(row: Any) -> LaunchScanIssueItem:
    data = row_to_dict(row)
    data["issue_label"] = ISSUE_TYPES.get(row.issue_type, {}).get("label", row.issue_type)
    return LaunchScanIssueItem.model_validate(data)
