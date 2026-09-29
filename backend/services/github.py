"""Download a GitHub repository as a ZIP (explicit user action; the only data sent is the repo URL).

Only github.com / api.github.com / codeload.github.com are contacted, through the network guard
allowlist. Private repositories work with a personal access token supplied for that request
(it is used once and never stored).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from backend.utils import network_guard

GITHUB_HOSTS = ["github.com", "api.github.com", "codeload.github.com"]
URL = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/tree/([^?#]+))?/?(?:[?#].*)?$")
MAX_BYTES = 400 * 1024 * 1024


class GitHubError(Exception):
    pass


def parse_url(url: str) -> tuple[str, str, Optional[str]]:
    m = URL.match(url.strip())
    if not m:
        raise GitHubError("Enter a GitHub repository URL like https://github.com/owner/repository")
    return m.group(1), m.group(2), m.group(3)


def download_repo(url: str, token: str = "") -> tuple[Path, str]:
    owner, repo, ref = parse_url(url)
    api = f"https://api.github.com/repos/{owner}/{repo}/zipball" + (f"/{ref}" if ref else "")
    headers = {"User-Agent": "ZensarContentStudio", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    import os

    os.close(fd)
    out = Path(tmp)
    try:
        with network_guard.allow_hosts(GITHUB_HOSTS):
            with httpx.Client(timeout=120, headers=headers, follow_redirects=True) as c:
                with c.stream("GET", api) as r:
                    if r.status_code == 404:
                        raise GitHubError("Repository not found (or it is private - add an access token).")
                    if r.status_code in (401, 403):
                        raise GitHubError("GitHub refused the request (rate limit or missing access token).")
                    if r.status_code != 200:
                        raise GitHubError(f"GitHub returned HTTP {r.status_code}.")
                    size = 0
                    with open(out, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise GitHubError("The repository archive is larger than 400 MB.")
                            f.write(chunk)
    except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as exc:
        out.unlink(missing_ok=True)
        raise GitHubError("GitHub could not be reached. Check the internet connection, or upload the repository as a ZIP.") from exc
    except GitHubError:
        out.unlink(missing_ok=True)
        raise
    return out, f"{repo}.zip"
