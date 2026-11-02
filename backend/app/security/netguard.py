"""Outbound URL validation to reduce SSRF risk.

Integration base URLs are user-supplied. We require HTTPS (HTTP only for loopback
AI providers in development), reject credentials embedded in URLs, and reject
hosts that resolve to private/link-local/loopback ranges unless explicitly allowed.
Outbound HTTP clients additionally pin requests to the configured host only.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import get_settings


class UnsafeUrlError(ValueError):
    pass


def _is_private(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise UnsafeUrlError("URL is required")
    if "://" not in url:
        url = "https://" + url
    return url.rstrip("/")


def validate_outbound_url(url: str, *, allow_loopback_http: bool = False, resolve: bool = True) -> str:
    """Validate and normalise an integration base URL. Returns the normalised URL."""
    settings = get_settings()
    url = normalize_base_url(url)
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Credentials must not be embedded in the URL")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no host")
    host = parsed.hostname
    loopback_names = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    is_loopback_name = host in loopback_names

    if parsed.scheme == "http":
        if not (allow_loopback_http and is_loopback_name) and not settings.allow_private_network_targets:
            raise UnsafeUrlError("HTTPS is required for integration URLs")
    elif parsed.scheme != "https":
        raise UnsafeUrlError("Only http(s) URLs are supported")

    if allow_loopback_http and is_loopback_name:
        return url
    if settings.allow_private_network_targets or not resolve:
        return url
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Host '{host}' could not be resolved") from exc
    for info in infos:
        addr = info[4][0]
        if _is_private(addr):
            raise UnsafeUrlError(
                f"Host '{host}' resolves to a private or reserved address. Set "
                "ALLOW_PRIVATE_NETWORK_TARGETS=true only for trusted on-premises instances."
            )
    return url


def same_origin(base_url: str, target_url: str) -> bool:
    b, t = urlparse(base_url), urlparse(target_url)
    return (b.scheme, b.hostname, b.port) == (t.scheme, t.hostname, t.port)
