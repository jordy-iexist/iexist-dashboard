"""Bescherming tegen SSRF: weiger URLs die naar interne adressen wijzen."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


_ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_external_url(url: str) -> None:
    """Raise UnsafeURLError als de URL niet naar een publiek internetadres wijst.

    Blokkeert loopback, RFC1918, link-local (incl. cloud-metadata 169.254.169.254)
    en niet-http(s)-schema's. Resolved alle DNS-records van de host zodat een
    hostname die naar een intern IP wijst ook geweigerd wordt.
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError("Alleen http(s)-URLs zijn toegestaan.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL bevat geen geldige hostname.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if _is_blocked_ip(ip):
            raise UnsafeURLError("URL wijst naar een intern of gereserveerd IP-adres.")
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Hostname kon niet worden opgezocht: {host}") from exc

    for info in infos:
        resolved = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(resolved):
            raise UnsafeURLError(
                "URL wijst naar een intern of gereserveerd IP-adres."
            )


def is_safe_external_url(url: str) -> bool:
    try:
        validate_external_url(url)
    except UnsafeURLError:
        return False
    return True


__all__ = ["UnsafeURLError", "validate_external_url", "is_safe_external_url"]
