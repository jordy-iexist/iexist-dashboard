from collections import Counter
from typing import Any


def generate_cross_page_issues(pages_data: list[dict]) -> list[dict[str, Any]]:
    """Detect style inconsistencies across pages: heading style variance and too many font families."""
    issues: list[dict[str, Any]] = []

    # Check 1: Inconsistent heading styles across pages
    # For each heading level, collect (page_url, style_key) pairs
    heading_styles: dict[int, list[tuple[str, str]]] = {i: [] for i in range(1, 7)}

    for page in pages_data:
        page_url = page.get("url", "")
        typography = page.get("typography_data") or {}
        fonts = typography.get("fonts") or []

        for level in range(1, 7):
            tag = f"h{level}"
            tag_fonts = [f for f in fonts if f.get("tag") == tag]
            if tag_fonts:
                f = tag_fonts[0]
                family = str(f.get("fontFamily") or "").split(",")[0].strip().strip("\"'")
                size = str(f.get("fontSize") or "")
                weight = str(f.get("fontWeight") or "")
                style_key = f"{size}|{weight}|{family}"
                heading_styles[level].append((page_url, style_key))

    for level in range(1, 7):
        entries = heading_styles[level]
        if len(entries) < 2:
            continue

        styles = set(style_key for _, style_key in entries)
        if len(styles) > 1:
            style_counts = Counter(style_key for _, style_key in entries)
            dominant, _ = style_counts.most_common(1)[0]
            non_dominant_pages = [url for url, style in entries if style != dominant]
            issues.append({
                "category": "typography",
                "severity": "warning",
                "title": f"Inconsistente H{level}-stijl over pagina's",
                "description": (
                    f"{len(non_dominant_pages)} van {len(entries)} pagina's heeft een afwijkende "
                    f"H{level}-opmaak. Controleer lettertype, grootte en gewicht van H{level}."
                ),
                "page_url": None,
                "issue_metadata": {
                    "heading_level": level,
                    "unique_styles": len(styles),
                    "pages_count": len(entries),
                    "non_dominant_pages": non_dominant_pages[:5],
                },
            })

    # Check 2: Too many primary font families (>4 unique across all pages)
    all_families: set[str] = set()
    for page in pages_data:
        typography = page.get("typography_data") or {}
        fonts = typography.get("fonts") or []
        for f in fonts:
            ff = str(f.get("fontFamily") or "").strip()
            if ff:
                family = ff.split(",")[0].strip().strip("\"'")
                if family:
                    all_families.add(family)

    if len(all_families) > 4:
        issues.append({
            "category": "typography",
            "severity": "info",
            "title": f"Te veel lettertypes ({len(all_families)})",
            "description": (
                f"Er zijn {len(all_families)} unieke primaire lettertypes gevonden over alle pagina's. "
                f"Beperk het gebruik tot maximaal 3-4 lettertypes voor visuele consistentie."
            ),
            "page_url": None,
            "issue_metadata": {
                "font_families": sorted(all_families)[:20],
                "count": len(all_families),
            },
        })

    return issues


def generate_audit_summary(pages_data: list[dict]) -> dict[str, Any]:
    """Cross-page analysis: count issues per category/severity, detect typography inconsistencies, compute score."""
    total_issues = 0
    critical = 0
    warnings = 0
    info = 0
    categories: dict[str, int] = {}

    # Collect all font families across pages for cross-page typography consistency
    font_families_per_page: dict[str, set[str]] = {}

    for page in pages_data:
        page_url = page.get("url", "")

        # Count severity from pre-computed issues
        for issue in page.get("issues", []):
            total_issues += 1
            sev = issue.get("severity", "info")
            cat = issue.get("category", "functionality")
            if sev == "critical":
                critical += 1
            elif sev == "warning":
                warnings += 1
            else:
                info += 1
            categories[cat] = categories.get(cat, 0) + 1

        # Track font families for cross-page consistency check
        typography = page.get("typography_data") or {}
        fonts = typography.get("fonts") or []
        families: set[str] = set()
        for f in fonts:
            ff = str(f.get("fontFamily") or "").strip()
            if ff:
                families.add(ff.split(",")[0].strip().strip('"\''))
        if families:
            font_families_per_page[page_url] = families

    # Compute score: start at 100, deduct for issues
    score = 100
    score -= critical * 10
    score -= warnings * 3
    score -= info * 1
    score = max(0, min(100, score))

    # Typography consistency: find font families used
    all_families: set[str] = set()
    for families in font_families_per_page.values():
        all_families.update(families)

    return {
        "total_issues": total_issues,
        "critical": critical,
        "warnings": warnings,
        "info": info,
        "categories": categories,
        "score": score,
        "typography_summary": {
            "unique_font_families": sorted(all_families),
            "pages_with_data": len(font_families_per_page),
        },
    }
