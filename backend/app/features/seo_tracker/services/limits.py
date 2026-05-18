def clamp_max_requests(value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 1
    return max(parsed, 1)


def apply_scan_limit(items: list[dict], max_requests: int) -> tuple[list[dict], int, bool]:
    limit = clamp_max_requests(max_requests)
    selected = items[:limit]
    skipped_due_to_limit = max(len(items) - len(selected), 0)
    return selected, skipped_due_to_limit, skipped_due_to_limit > 0
