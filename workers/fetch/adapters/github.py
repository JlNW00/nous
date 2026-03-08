"""GitHub adapter for repository metadata and commit activity.

Fetches:
- Repository metadata (age, stars, forks, fork status, description)
- Recent commit count and unique author count (last 28 days)

GitHub REST API: https://docs.github.com/en/rest
Rate limits:
  - Unauthenticated: 60 requests/hour per IP
  - Authenticated (GITHUB_TOKEN): 5000 requests/hour
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from packages.common.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAdapter:
    """GitHub repository data via REST API v3."""

    def __init__(self) -> None:
        self.token = settings.github_token  # May be empty string — public repos work without auth
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.client = httpx.Client(timeout=20, headers=headers)

    def close(self) -> None:
        self.client.close()

    def get_repo_info(self, owner: str, repo: str) -> dict[str, Any]:
        """
        Fetch repository metadata.

        Returns a normalized dict including:
          - exists: bool
          - owner, repo: str
          - created_at: str (ISO 8601)
          - age_days: int
          - stars: int
          - forks: int
          - is_fork: bool  — True if this repo was forked from another
          - description: str | None
          - default_branch: str

        Returns {"exists": False, ...} on 404 (private/deleted/not-found).
        All other HTTP errors propagate via raise_for_status().
        """
        response = self.client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}")

        if response.status_code == 404:
            logger.warning("GitHub repo not found: %s/%s", owner, repo)
            return {"exists": False, "owner": owner, "repo": repo}

        response.raise_for_status()
        data = response.json()

        created_at_str = data.get("created_at", "")
        age_days = 0
        if created_at_str:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days

        return {
            "exists": True,
            "owner": owner,
            "repo": repo,
            "created_at": created_at_str,
            "age_days": age_days,
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "is_fork": data.get("fork", False),
            "description": data.get("description"),
            "default_branch": data.get("default_branch", "main"),
        }

    def get_recent_commit_activity(
        self, owner: str, repo: str, days: int = 28
    ) -> dict[str, Any]:
        """
        Fetch commit activity for the last `days` days.

        Uses /commits?since= (synchronous) instead of /stats/commit_activity
        which returns 202 Accepted on first call (requires async polling).

        Fetches up to 100 commits (single page). Any repo with >100 commits
        in 28 days saturates the top velocity bucket (>15/week) regardless.

        Returns:
          - commit_count_28d: int
          - unique_authors_28d: int  — distinct commit author emails
          - window_days: int
          - since_iso: str
        """
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
        since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        response = self.client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
            params={"since": since_iso, "per_page": 100},
        )

        if response.status_code == 409:
            # 409 = empty repo (no commits)
            logger.info("Repo %s/%s is empty (no commits)", owner, repo)
            return {
                "commit_count_28d": 0,
                "unique_authors_28d": 0,
                "window_days": days,
                "since_iso": since_iso,
            }

        response.raise_for_status()
        commits = response.json()

        # Count unique author emails for contributor diversity signal
        author_emails: set[str] = set()
        for c in commits:
            email = (
                c.get("commit", {}).get("author", {}).get("email") or ""
            ).lower().strip()
            if email:
                author_emails.add(email)

        return {
            "commit_count_28d": len(commits),
            "unique_authors_28d": len(author_emails),
            "window_days": days,
            "since_iso": since_iso,
        }

    @staticmethod
    def parse_github_url(url: str) -> tuple[str, str] | None:
        """
        Parse a GitHub URL into (owner, repo).

        Handles:
          - https://github.com/owner/repo
          - https://github.com/owner/repo.git
          - https://github.com/owner/repo/tree/main
          - http://github.com/owner/repo

        Returns None for org-only URLs or non-GitHub URLs.
        """
        pattern = r"https?://github\.com/([^/\s]+)/([^/?#\s]+?)(?:\.git)?(?:[/?#].*)?$"
        match = re.match(pattern, url.strip())
        if not match:
            return None
        owner, repo = match.group(1), match.group(2)
        if not owner or not repo:
            return None
        return owner, repo

    @staticmethod
    def hash_payload(payload: Any) -> str:
        """Deterministic SHA256 hash for evidence deduplication."""
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
