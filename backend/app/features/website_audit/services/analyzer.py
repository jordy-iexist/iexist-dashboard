import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass
class PageAnalysisResult:
    url: str
    path: str
    typography_data: dict[str, Any] = field(default_factory=dict)
    performance_data: dict[str, Any] = field(default_factory=dict)
    accessibility_data: dict[str, Any] = field(default_factory=dict)
    console_errors: list[dict[str, Any]] = field(default_factory=list)
    meta_data: dict[str, Any] = field(default_factory=dict)
    links_data: dict[str, Any] = field(default_factory=dict)
    responsive_data: dict[str, Any] = field(default_factory=dict)
    screenshots: dict[str, bytes] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


VIEWPORTS = [
    {"name": "mobile", "width": 375, "height": 812},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "desktop", "width": 1440, "height": 900},
]

_TYPOGRAPHY_JS = """
() => {
  const results = [];
  const walker = document.createTreeWalker(
    document.body || document.documentElement,
    NodeFilter.SHOW_ELEMENT
  );
  const seen = new Set();
  let node;
  while ((node = walker.nextNode())) {
    const tag = node.tagName.toLowerCase();
    const isText = ['p','h1','h2','h3','h4','h5','h6','span','a','li','td','th','label','button'].includes(tag);
    if (!isText) continue;
    const style = window.getComputedStyle(node);
    const key = [
      style.fontFamily, style.fontSize, style.fontWeight, style.lineHeight, style.color
    ].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({
      tag,
      fontFamily: style.fontFamily,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      lineHeight: style.lineHeight,
      color: style.color,
      letterSpacing: style.letterSpacing
    });
    if (results.length >= 100) break;
  }
  return results;
}
"""

_PERFORMANCE_JS = """
() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const paint = {};
  performance.getEntriesByType('paint').forEach(e => { paint[e.name] = e.startTime; });
  const lcp_entries = performance.getEntriesByType('largest-contentful-paint');
  const lcp = lcp_entries.length ? lcp_entries[lcp_entries.length - 1].startTime : null;
  const cls_entries = performance.getEntriesByType('layout-shift');
  const cls = cls_entries.reduce((sum, e) => sum + (e.value || 0), 0);
  return {
    dns_lookup: (nav.domainLookupEnd || 0) - (nav.domainLookupStart || 0),
    tcp_connect: (nav.connectEnd || 0) - (nav.connectStart || 0),
    ttfb: (nav.responseStart || 0) - (nav.requestStart || 0),
    dom_interactive: nav.domInteractive || 0,
    dom_complete: nav.domComplete || 0,
    load_event_end: nav.loadEventEnd || 0,
    first_paint: paint['first-paint'] || null,
    first_contentful_paint: paint['first-contentful-paint'] || null,
    lcp,
    cls: Math.round(cls * 1000) / 1000,
    transfer_size: nav.transferSize || 0,
    encoded_body_size: nav.encodedBodySize || 0
  };
}
"""

_META_JS = """
() => {
  const get = (sel) => { const el = document.querySelector(sel); return el ? el.content || el.textContent || el.getAttribute('href') : null; };
  const getMeta = (name) => {
    const el = document.querySelector(`meta[name="${name}"]`) || document.querySelector(`meta[property="${name}"]`);
    return el ? el.getAttribute('content') : null;
  };
  const h1s = Array.from(document.querySelectorAll('h1')).map(e => e.textContent.trim()).filter(Boolean);
  const canonical = document.querySelector('link[rel="canonical"]');
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .slice(0, 200)
    .map(el => ({
      level: parseInt(el.tagName.substring(1)),
      text: el.textContent.trim().substring(0, 120)
    }));
  return {
    title: document.title || null,
    description: getMeta('description'),
    og_title: getMeta('og:title'),
    og_description: getMeta('og:description'),
    og_image: getMeta('og:image'),
    og_type: getMeta('og:type'),
    canonical: canonical ? canonical.href : null,
    robots: getMeta('robots'),
    viewport: getMeta('viewport'),
    h1_count: h1s.length,
    h1_texts: h1s.slice(0, 3),
    lang: document.documentElement.lang || null,
    headings: headings
  };
}
"""

_LINKS_JS = """
() => {
  const links = Array.from(document.querySelectorAll('a[href]'))
    .map(a => a.href)
    .filter(href => href && (href.startsWith('http://') || href.startsWith('https://')));
  const imgs = Array.from(document.querySelectorAll('img[src]'))
    .map(img => img.src)
    .filter(src => src && (src.startsWith('http://') || src.startsWith('https://')));
  return { links: [...new Set(links)].slice(0, 100), images: [...new Set(imgs)].slice(0, 50) };
}
"""

_RESPONSIVE_JS = """
() => {
  const docWidth = document.documentElement.scrollWidth;
  const winWidth = window.innerWidth;
  const hasHorizScroll = docWidth > winWidth;
  const overflowing = [];
  document.querySelectorAll('*').forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.right > winWidth + 5) {
      const tag = el.tagName.toLowerCase();
      const cls = el.className && typeof el.className === 'string' ? el.className.split(' ').slice(0, 3).join(' ') : '';
      overflowing.push({ tag, class: cls, right: Math.round(rect.right), width: Math.round(winWidth) });
    }
  });
  return {
    viewport_width: winWidth,
    document_width: docWidth,
    has_horizontal_scroll: hasHorizScroll,
    overflowing_elements: overflowing.slice(0, 20)
  };
}
"""


def _normalize_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _check_links_status(links: list[str], timeout: float = 5.0) -> list[dict]:
    results = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url in links[:30]:  # limit to 30 links per page
            try:
                r = client.head(url, headers={"User-Agent": "WebAudit/1.0"})
                results.append({"url": url, "status": r.status_code, "ok": r.status_code < 400})
            except Exception as exc:
                results.append({"url": url, "status": None, "ok": False, "error": str(exc)[:100]})
    return results


def _build_issues_from_page_data(
    url: str,
    meta: dict,
    performance: dict,
    accessibility: dict,
    console_errors: list,
    links_data: dict,
    responsive_data_per_viewport: list[dict],
    typography: list[dict],
) -> list[dict]:
    issues: list[dict[str, Any]] = []

    # SEO meta issues
    if not meta.get("title"):
        issues.append({
            "category": "seo", "severity": "critical",
            "title": "Paginatitel ontbreekt",
            "description": "De pagina heeft geen <title> tag.",
            "page_url": url,
        })
    elif len(str(meta["title"])) > 60:
        issues.append({
            "category": "seo", "severity": "warning",
            "title": "Paginatitel te lang",
            "description": f"Titel is {len(str(meta['title']))} tekens (max aanbevolen: 60).",
            "page_url": url,
        })
    elif len(str(meta["title"])) < 10:
        issues.append({
            "category": "seo", "severity": "warning",
            "title": "Paginatitel te kort",
            "description": f"Titel is slechts {len(str(meta['title']))} tekens.",
            "page_url": url,
        })

    if not meta.get("description"):
        issues.append({
            "category": "seo", "severity": "warning",
            "title": "Meta description ontbreekt",
            "description": "De pagina heeft geen meta description.",
            "page_url": url,
        })
    elif len(str(meta["description"])) > 160:
        issues.append({
            "category": "seo", "severity": "info",
            "title": "Meta description te lang",
            "description": f"Description is {len(str(meta['description']))} tekens (max aanbevolen: 160).",
            "page_url": url,
        })

    if meta.get("h1_count", 0) == 0:
        issues.append({
            "category": "seo", "severity": "warning",
            "title": "H1 ontbreekt",
            "description": "De pagina heeft geen H1 heading.",
            "page_url": url,
        })
    elif meta.get("h1_count", 0) > 1:
        issues.append({
            "category": "seo", "severity": "info",
            "title": f"Meerdere H1 headings ({meta['h1_count']})",
            "description": "Gebruik bij voorkeur één H1 per pagina.",
            "page_url": url,
        })

    if not meta.get("canonical"):
        issues.append({
            "category": "seo", "severity": "info",
            "title": "Canonical tag ontbreekt",
            "description": "Voeg een canonical link element toe om duplicate content te voorkomen.",
            "page_url": url,
        })

    # Heading hierarchy checks
    headings = meta.get("headings", [])
    if headings:
        if headings[0]["level"] != 1:
            issues.append({
                "category": "seo", "severity": "info",
                "title": f"Eerste heading is geen H1 (H{headings[0]['level']})",
                "description": "De eerste heading op de pagina is geen H1.",
                "page_url": url,
            })

        reported_skips: set[tuple[int, int]] = set()
        prev_level = headings[0]["level"]
        for h in headings[1:]:
            cur_level = h["level"]
            if cur_level > prev_level + 1:
                skip_pair = (prev_level, cur_level)
                if skip_pair not in reported_skips:
                    reported_skips.add(skip_pair)
                    issues.append({
                        "category": "seo", "severity": "warning",
                        "title": f"Heading niveau overgeslagen (H{prev_level}→H{cur_level})",
                        "description": (
                            f"Heading niveau springt van H{prev_level} naar H{cur_level}, "
                            f"niveau H{prev_level + 1} is overgeslagen."
                        ),
                        "page_url": url,
                    })
            prev_level = cur_level

        empty_count = 0
        for h in headings:
            if not h.get("text") and empty_count < 5:
                empty_count += 1
                issues.append({
                    "category": "seo", "severity": "warning",
                    "title": f"Lege heading (H{h['level']})",
                    "description": f"H{h['level']} heading heeft geen zichtbare tekst.",
                    "page_url": url,
                })
    else:
        issues.append({
            "category": "seo", "severity": "info",
            "title": "Geen headings gevonden",
            "description": "De pagina heeft geen heading elementen (H1-H6).",
            "page_url": url,
        })

    # Performance issues
    if performance:
        ttfb = performance.get("ttfb") or 0
        if ttfb > 800:
            issues.append({
                "category": "performance", "severity": "critical",
                "title": f"Hoge TTFB ({int(ttfb)}ms)",
                "description": "Time to First Byte is meer dan 800ms. Onderzoek server-side performance.",
                "page_url": url, "issue_metadata": {"ttfb_ms": ttfb},
            })
        elif ttfb > 400:
            issues.append({
                "category": "performance", "severity": "warning",
                "title": f"Trage TTFB ({int(ttfb)}ms)",
                "description": "Time to First Byte is meer dan 400ms.",
                "page_url": url, "issue_metadata": {"ttfb_ms": ttfb},
            })

        lcp = performance.get("lcp")
        if lcp and lcp > 4000:
            issues.append({
                "category": "performance", "severity": "critical",
                "title": f"Slechte LCP ({int(lcp)}ms)",
                "description": "Largest Contentful Paint is meer dan 4 seconden (slecht).",
                "page_url": url, "issue_metadata": {"lcp_ms": lcp},
            })
        elif lcp and lcp > 2500:
            issues.append({
                "category": "performance", "severity": "warning",
                "title": f"Matige LCP ({int(lcp)}ms)",
                "description": "Largest Contentful Paint is meer dan 2.5 seconden (verbetering nodig).",
                "page_url": url, "issue_metadata": {"lcp_ms": lcp},
            })

        cls = performance.get("cls") or 0
        if cls > 0.25:
            issues.append({
                "category": "performance", "severity": "critical",
                "title": f"Slechte CLS ({cls})",
                "description": "Cumulative Layout Shift is hoger dan 0.25 (slecht).",
                "page_url": url, "issue_metadata": {"cls": cls},
            })
        elif cls > 0.1:
            issues.append({
                "category": "performance", "severity": "warning",
                "title": f"Matige CLS ({cls})",
                "description": "Cumulative Layout Shift is hoger dan 0.1 (verbetering nodig).",
                "page_url": url, "issue_metadata": {"cls": cls},
            })

    # Accessibility issues
    if isinstance(accessibility, dict):
        violations = accessibility.get("violations") or []
        for v in violations[:20]:
            severity_map = {"critical": "critical", "serious": "critical", "moderate": "warning", "minor": "info"}
            sev = severity_map.get(str(v.get("impact") or ""), "info")
            nodes = v.get("nodes") or []
            selector = nodes[0].get("target", [""])[0] if nodes else None
            issues.append({
                "category": "accessibility", "severity": sev,
                "title": str(v.get("description") or v.get("id") or "Toegankelijkheidsfout"),
                "description": str(v.get("help") or ""),
                "selector": selector,
                "page_url": url,
                "issue_metadata": {"axe_id": v.get("id"), "help_url": v.get("helpUrl")},
            })

    # Console error issues
    for err in console_errors[:10]:
        msg_type = str(err.get("type") or "error")
        sev = "warning" if msg_type == "warning" else "info" if msg_type == "log" else "critical"
        issues.append({
            "category": "console_error", "severity": sev,
            "title": f"Console {msg_type}: {str(err.get('text') or '')[:80]}",
            "description": str(err.get("text") or ""),
            "page_url": url,
        })

    # Links issues
    broken = [l for l in (links_data.get("link_statuses") or []) if not l.get("ok")]
    for link in broken[:10]:
        issues.append({
            "category": "links", "severity": "critical" if link.get("status") is None else "warning",
            "title": f"Gebroken link: {link.get('url', '')[:60]}",
            "description": f"Link geeft status {link.get('status') or 'geen response'} terug.",
            "page_url": url,
            "issue_metadata": {"broken_url": link.get("url"), "status": link.get("status")},
        })

    # Responsive issues
    for vp_data in responsive_data_per_viewport:
        if vp_data.get("has_horizontal_scroll"):
            vp_name = vp_data.get("viewport_name", "onbekend")
            issues.append({
                "category": "responsive", "severity": "warning",
                "title": f"Horizontale scroll op {vp_name} ({vp_data.get('viewport_width')}px)",
                "description": f"De pagina heeft horizontale overflow op {vp_name} viewport.",
                "page_url": url,
                "issue_metadata": {
                    "viewport": vp_name,
                    "overflowing": vp_data.get("overflowing_elements", [])[:5],
                },
            })

    return issues


async def analyze_page(url: str) -> PageAnalysisResult:
    """Analyze a single page using Playwright. Returns structured data and issues."""
    path = _normalize_path(url)
    result = PageAnalysisResult(url=url, path=path)

    try:
        from playwright.async_api import async_playwright  # type: ignore[import]
    except ImportError:
        result.error = "Playwright is niet geïnstalleerd. Voer 'pip install playwright && playwright install chromium' uit."
        return result

    console_messages: list[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; WebAudit/1.0)",
                java_script_enabled=True,
            )
            page = await context.new_page()

            page.on("console", lambda msg: console_messages.append({
                "type": msg.type,
                "text": msg.text,
                "location": str(msg.location) if msg.location else None,
            }))

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception as nav_err:
                    result.error = f"Pagina laden mislukt: {str(nav_err)[:200]}"
                    await browser.close()
                    return result

            # Typography
            try:
                result.typography_data = {"fonts": await page.evaluate(_TYPOGRAPHY_JS)}
            except Exception as e:
                result.typography_data = {"error": str(e)[:100]}

            # Performance
            try:
                result.performance_data = await page.evaluate(_PERFORMANCE_JS)
            except Exception as e:
                result.performance_data = {"error": str(e)[:100]}

            # Meta
            try:
                result.meta_data = await page.evaluate(_META_JS)
            except Exception as e:
                result.meta_data = {"error": str(e)[:100]}

            # Links
            try:
                raw_links = await page.evaluate(_LINKS_JS)
                link_statuses = await asyncio.get_event_loop().run_in_executor(
                    None, _check_links_status, raw_links.get("links", [])
                )
                result.links_data = {
                    "total_links": len(raw_links.get("links", [])),
                    "total_images": len(raw_links.get("images", [])),
                    "link_statuses": link_statuses,
                    "broken_count": sum(1 for l in link_statuses if not l.get("ok")),
                }
            except Exception as e:
                result.links_data = {"error": str(e)[:100]}

            # Accessibility via axe-core (injected from CDN)
            try:
                await page.add_script_tag(
                    url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
                )
                axe_result = await page.evaluate("() => axe.run()")
                result.accessibility_data = {
                    "violations": axe_result.get("violations", [])[:30],
                    "passes_count": len(axe_result.get("passes", [])),
                    "violations_count": len(axe_result.get("violations", [])),
                    "incomplete_count": len(axe_result.get("incomplete", [])),
                }
            except Exception as e:
                result.accessibility_data = {"error": str(e)[:100], "violations": [], "violations_count": 0}

            # Responsive - test 3 viewports + capture desktop/mobile screenshots
            responsive_per_viewport: list[dict] = []
            for vp in VIEWPORTS:
                try:
                    vp_context = await browser.new_context(
                        viewport={"width": vp["width"], "height": vp["height"]},
                        user_agent="Mozilla/5.0 (compatible; WebAudit/1.0)",
                    )
                    vp_page = await vp_context.new_page()
                    await vp_page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    vp_data = await vp_page.evaluate(_RESPONSIVE_JS)
                    vp_data["viewport_name"] = vp["name"]
                    responsive_per_viewport.append(vp_data)
                    if vp["name"] in {"desktop", "mobile"}:
                        try:
                            screenshot_bytes = await vp_page.screenshot(
                                full_page=True, type="jpeg", quality=70
                            )
                            result.screenshots[vp["name"]] = screenshot_bytes
                        except Exception:
                            pass
                    await vp_context.close()
                except Exception as e:
                    responsive_per_viewport.append({
                        "viewport_name": vp["name"],
                        "error": str(e)[:100],
                    })

            result.responsive_data = {"viewports": responsive_per_viewport}
            result.console_errors = console_messages[:50]

            await browser.close()

        # Build issues from collected data
        result.issues = _build_issues_from_page_data(
            url=url,
            meta=result.meta_data if isinstance(result.meta_data, dict) else {},
            performance=result.performance_data if isinstance(result.performance_data, dict) else {},
            accessibility=result.accessibility_data if isinstance(result.accessibility_data, dict) else {},
            console_errors=result.console_errors,
            links_data=result.links_data if isinstance(result.links_data, dict) else {},
            responsive_data_per_viewport=result.responsive_data.get("viewports", []) if isinstance(result.responsive_data, dict) else [],
            typography=result.typography_data.get("fonts", []) if isinstance(result.typography_data, dict) else [],
        )

    except Exception as exc:
        result.error = str(exc)[:500]

    return result
