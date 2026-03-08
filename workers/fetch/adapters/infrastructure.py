"""Infrastructure adapter for DNS/HTTP probing of project websites.

Probes:
- DNS resolution (does the domain resolve?)
- HTTP response (status code, TLS, server headers, content size)

No API key required — uses standard DNS and HTTP requests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Domains to skip (not real project infrastructure)
SKIP_DOMAINS = {
    "github.com",
    "twitter.com",
    "x.com",
    "t.me",
    "telegram.org",
    "discord.gg",
    "discord.com",
    "medium.com",
    "reddit.com",
    "youtube.com",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "linkedin.com",
}


class InfrastructureAdapter:
    """DNS and HTTP probing for project websites."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "CryptoInvestigator/0.1"},
        )

    def close(self) -> None:
        self.client.close()

    def probe_url(self, url: str) -> dict[str, Any]:
        """
        Probe a URL with DNS resolution and HTTP request.

        Returns a normalized dict with:
          - url: str (original)
          - domain: str
          - dns_resolves: bool
          - ip_addresses: list[str]
          - http_status: int | None
          - is_https: bool
          - has_valid_tls: bool
          - content_length: int
          - server_header: str | None
          - response_time_ms: float | None
          - final_url: str | None (after redirects)
          - error: str | None
        """
        parsed = urlparse(url if "://" in url else f"https://{url}")
        domain = parsed.hostname or ""

        result: dict[str, Any] = {
            "url": url,
            "domain": domain,
            "dns_resolves": False,
            "ip_addresses": [],
            "http_status": None,
            "is_https": False,
            "has_valid_tls": False,
            "content_length": 0,
            "server_header": None,
            "response_time_ms": None,
            "final_url": None,
            "error": None,
        }

        if not domain:
            result["error"] = "invalid_url"
            return result

        # Step 1: DNS resolution
        try:
            addr_info = socket.getaddrinfo(domain, None, socket.AF_UNSPEC)
            ips = list({info[4][0] for info in addr_info})
            result["dns_resolves"] = True
            result["ip_addresses"] = ips[:5]
        except socket.gaierror:
            result["error"] = "dns_failed"
            return result

        # Step 2: HTTP probe (prefer HTTPS, fall back to HTTP)
        probe_url = url if "://" in url else f"https://{url}"
        if not probe_url.startswith("https"):
            probe_url = probe_url.replace("http://", "https://", 1)

        for attempt_url in [probe_url, probe_url.replace("https://", "http://", 1)]:
            try:
                start = time.monotonic()
                resp = self.client.get(attempt_url)
                elapsed_ms = (time.monotonic() - start) * 1000

                result["http_status"] = resp.status_code
                result["response_time_ms"] = round(elapsed_ms, 1)
                result["final_url"] = str(resp.url)
                result["is_https"] = str(resp.url).startswith("https")
                result["has_valid_tls"] = result["is_https"]
                result["server_header"] = resp.headers.get("server")
                result["content_length"] = len(resp.content)
                break

            except httpx.ConnectError:
                if "https" in attempt_url:
                    continue  # Try HTTP fallback
                result["error"] = "connection_failed"
            except httpx.TimeoutException:
                result["error"] = "timeout"
                break
            except httpx.HTTPError as exc:
                result["error"] = f"http_error: {exc}"
                break

        return result

    def probe_domain_summary(self, urls: list[str]) -> dict[str, Any]:
        """
        Probe multiple URLs and return an aggregate summary.

        Filters out social media / known third-party domains.
        Returns the best-scoring probe result plus aggregate stats.
        """
        filtered: list[str] = []
        for url in urls:
            parsed = urlparse(url if "://" in url else f"https://{url}")
            domain = (parsed.hostname or "").lower()
            if domain and not any(domain.endswith(skip) for skip in SKIP_DOMAINS):
                filtered.append(url)

        if not filtered:
            return {
                "probed": 0,
                "urls_checked": [],
                "best_probe": None,
                "any_live": False,
            }

        probes: list[dict[str, Any]] = []
        for url in filtered[:3]:  # Limit to 3 probes to avoid timeouts
            logger.info("Probing infrastructure: %s", url)
            probe = self.probe_url(url)
            probes.append(probe)

        # Pick best probe: prefer HTTPS 2xx with content
        def probe_quality(p: dict[str, Any]) -> tuple:
            status = p.get("http_status") or 0
            is_2xx = 200 <= status < 300
            return (
                is_2xx,
                p.get("has_valid_tls", False),
                p.get("content_length", 0),
            )

        best = max(probes, key=probe_quality)
        any_live = any(
            200 <= (p.get("http_status") or 0) < 300 for p in probes
        )

        return {
            "probed": len(probes),
            "urls_checked": [p["url"] for p in probes],
            "best_probe": best,
            "any_live": any_live,
        }

    @staticmethod
    def hash_payload(payload: Any) -> str:
        """Deterministic SHA256 hash for evidence deduplication."""
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
