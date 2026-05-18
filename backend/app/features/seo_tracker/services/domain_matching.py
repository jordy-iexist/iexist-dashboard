import ipaddress
from urllib.parse import urlparse

SECOND_LEVEL_PUBLIC_SUFFIXES = {
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "com.au",
    "net.au",
    "org.au",
    "co.nz",
}


def extract_hostname(raw_value: str) -> str:
    cleaned = str(raw_value or "").strip().lower()
    if not cleaned:
        raise ValueError("Hostname ontbreekt.")

    candidate = cleaned
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    hostname = str(parsed.hostname or "").strip(".").lower()
    if not hostname:
        raise ValueError("Kon geen hostname bepalen.")
    return hostname


def to_root_domain(raw_hostname: str) -> str:
    hostname = extract_hostname(raw_hostname)

    try:
        ipaddress.ip_address(hostname)
        return hostname
    except ValueError:
        pass

    labels = [label for label in hostname.split(".") if label]
    if len(labels) <= 2:
        return hostname

    suffix = ".".join(labels[-2:])
    if suffix in SECOND_LEVEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])

    return ".".join(labels[-2:])


def normalize_website_url(raw_url: str) -> tuple[str, str]:
    cleaned_url = str(raw_url or "").strip()
    if not cleaned_url:
        raise ValueError("Site URL is verplicht.")

    if not cleaned_url.startswith(("http://", "https://")):
        cleaned_url = f"https://{cleaned_url}"

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Site URL is ongeldig. Gebruik bijvoorbeeld https://voorbeeld.nl.")

    path = parsed.path.rstrip("/")
    normalized_url = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
    root_domain = to_root_domain(str(parsed.hostname or ""))
    return normalized_url, root_domain


def matches_domain(raw_hostname: str, raw_target_domain: str) -> bool:
    try:
        hostname = extract_hostname(raw_hostname)
        target_domain = to_root_domain(raw_target_domain)
    except ValueError:
        return False

    return hostname == target_domain or hostname.endswith(f".{target_domain}")
