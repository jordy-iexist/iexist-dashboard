"""Samenvattende cijfers voor het overzicht en de Nulmeting-agent."""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.db.models import LaunchScanPage
from app.features.launch_checklist.services.issues import final_status


def build_summary_stats(pages: list[LaunchScanPage], issues: list[dict[str, Any]]) -> dict[str, Any]:
    status_buckets: Counter[str] = Counter()
    for p in pages:
        if p.status_code is None:
            status_buckets["error"] += 1
        elif p.redirect_chain:
            status_buckets["3xx"] += 1
        else:
            status_buckets[f"{str(p.status_code)[0]}xx"] += 1

    html_ok = [
        p for p in pages
        if p.status_code == 200 and not p.redirect_chain and "html" in (p.content_type or "").lower()
    ]
    indexable = [p for p in html_ok if p.indexable is True]
    response_times = [p.response_time_ms for p in html_ok if p.response_time_ms is not None]

    cwv_counts: Counter[str] = Counter(p.cwv_status for p in pages if p.cwv_status)
    perf_scores = [
        (p.cwv or {}).get("lab", {}).get("performance_score")
        for p in pages
        if (p.cwv or {}).get("lab", {}).get("performance_score") is not None
    ]

    by_severity: Counter[str] = Counter(i["severity"] for i in issues)
    by_category: Counter[str] = Counter(i["category"] for i in issues)
    by_type: Counter[str] = Counter(i["issue_type"] for i in issues)

    return {
        "total_urls": len(pages),
        "status": dict(status_buckets),
        "html_pages": len(html_ok),
        "indexable": len(indexable),
        "non_indexable": len([p for p in pages if p.indexable is False]),
        "http2_pages": len([p for p in html_ok if (p.http_version or "").upper().startswith("HTTP/2")]),
        "missing_title": len([p for p in indexable if not p.title]),
        "missing_meta": len([p for p in indexable if not p.meta_description]),
        "missing_h1": len([p for p in indexable if not (p.h1_count or 0)]),
        "multiple_h1": len([p for p in indexable if (p.h1_count or 0) > 1]),
        "broken_link_pages": len([p for p in pages if p.broken_links]),
        "images_missing_alt": sum(p.images_missing_alt or 0 for p in pages),
        "avg_response_ms": round(sum(response_times) / len(response_times)) if response_times else None,
        "avg_word_count": round(sum(p.word_count or 0 for p in indexable) / len(indexable)) if indexable else None,
        "redirects": len([p for p in pages if p.redirect_chain]),
        "final_4xx": len([p for p in pages if (final_status(p) or 0) >= 400 and (final_status(p) or 0) < 500]),
        "cwv": {
            "measured": sum(cwv_counts.values()),
            "good": cwv_counts.get("good", 0),
            "needs_improvement": cwv_counts.get("needs_improvement", 0),
            "poor": cwv_counts.get("poor", 0),
            "avg_performance_score": round(sum(perf_scores) / len(perf_scores)) if perf_scores else None,
        },
        "issues": {
            "total": len(issues),
            "by_severity": dict(by_severity),
            "by_category": dict(by_category),
            "by_type": dict(by_type.most_common()),
        },
    }
